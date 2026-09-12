"""Sensitivity of the headline (leave-one-weekend-out MAE, all cases incl. fallback) to the fuel prior, the traffic threshold and the
minimum run length. Reuses pipeline.weekend() with patched constants. Writes out/sensitivity.json."""
import json, glob, os, numpy as np, pandas as pd, warnings; warnings.filterwarnings('ignore')
import model_v2 as M, pipeline as P
def ladder():
    tables, metas = [], {}
    for ev in sorted({os.path.basename(f).split('_')[0] for f in glob.glob('feat/*_R.csv')}):
        w = P.weekend(ev)
        if w is None: continue
        t, meta, _ = w; tables.append(t); metas[ev] = meta
    R = pd.concat(tables, ignore_index=True); R['issued'] = R.gate == 'ok'; R['completed'] = R.event.map(lambda e: metas[e]['completed'])
    V = R[R.completed & R.obs.notna()].copy(); V['ratio'] = np.where(V.issued, V.obs / V.clean, np.nan)
    for i, row in V.iterrows():
        others = V[(V.event != row.event) & (V.compound == row.compound) & V.issued]['ratio']; k, _ = P.agree_factor(others); wh = V[(V.event != row.event) & ~V.issued]['obs']
        V.loc[i, 'pred'] = row.clean * k if row.issued else (float(wh.median()) if len(wh) >= 2 else np.nan)
    V['err'] = (V.pred - V.obs).abs(); V['err_naive'] = (V.naive - V.obs).abs()
    return dict(n=int(len(V)), issued=int(V.issued.sum()), mae=float(V.err.mean()), mae_naive=float(V.err_naive.mean()), r=float(np.corrcoef(V.pred, V.obs)[0, 1]))
base = dict(fuel=M.FUEL_KG_PER_LAP_PRACTICE, s_per_kg=M.FUEL_S_PER_KG, traffic=M.TRAFFIC_MAX, min_stint=M.MIN_STINT)
runs = [('baseline', {}), ('fuel 0.9 kg/lap', dict(FUEL_KG_PER_LAP_PRACTICE=0.9)), ('fuel 1.3 kg/lap', dict(FUEL_KG_PER_LAP_PRACTICE=1.3)), ('0.025 s/kg', dict(FUEL_S_PER_KG=0.025)), ('0.035 s/kg', dict(FUEL_S_PER_KG=0.035)),
        ('traffic ≤20%', dict(TRAFFIC_MAX=0.20)), ('traffic ≤40%', dict(TRAFFIC_MAX=0.40)), ('runs ≥4 laps', dict(MIN_STINT=4)), ('runs ≥7 laps', dict(MIN_STINT=7))]
out = {}
for name, patch in runs:
    saved = {k: getattr(M, k) for k in patch}
    for k, v in patch.items(): setattr(M, k, v)
    out[name] = ladder(); print(f"{name:16s} n={out[name]['n']:2d} issued={out[name]['issued']:2d} MAE {out[name]['mae']:.4f} (naive {out[name]['mae_naive']:.3f}) r {out[name]['r']:+.2f}", flush=True)
    for k, v in saved.items(): setattr(M, k, v)
json.dump(dict(base=base, runs=out), open('out/sensitivity.json', 'w'), indent=1)
