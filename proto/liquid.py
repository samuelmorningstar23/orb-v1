"""Liquid tyre model: a closed-form continuous-time (CfC) cell reads each race stint as a sequence of per-lap inputs and
predicts the cleaned pace-loss trajectory up to a per-stint constant (the same fixed-effect treatment as the linear model).
Validation is within weekend on held-out stints (5-fold over stints), against linear and quadratic fixed-effects fits on the
same folds. Outputs per compound-weekend: held-out MAE for all three, the liquid curve at mean inputs, the cliff lap, and the
sign of curvature. Writes out/liquid.json."""
import os, sys, json, glob, time, numpy as np, pandas as pd, torch, warnings
import model_v2 as M
from ncps.torch.cfc_cell import CfCCell
warnings.filterwarnings('ignore'); torch.set_num_threads(4)
COMPS = ['SOFT', 'MEDIUM', 'HARD']; HID, EPOCHS, SEEDS, FOLDS, LR = int(os.environ.get('LQ_HID', 16)), int(os.environ.get('LQ_EPOCHS', 160)), int(os.environ.get('LQ_SEEDS', 3)), 5, float(os.environ.get('LQ_LR', 5e-3)); BACKBONE = int(os.environ.get('LQ_BACKBONE', 32)); OUT = os.environ.get('LQ_OUT', 'out/liquid.json')

def stint_tensors(r, ev_mean_E, ev_sd_E):
    """per stint: inputs (age/30, compound one-hot, energy z, traffic, track temp scaled, fuel/70, race progress), elapsed laps, target y."""
    seqs = []
    for sid, s in r.sort_values(['stint_id', 'LapNumber']).groupby('stint_id'):
        s = s.dropna(subset=['TyreLife', 'y']);
        if len(s) < 6: continue
        age = s['TyreLife'].values.astype(float); c = s['Compound'].iloc[0]
        E = ((s['energy_MJ'].fillna(ev_mean_E).values - ev_mean_E) / max(ev_sd_E, 1e-6))
        X = np.column_stack([age / 30.0, (c == 'SOFT') * np.ones(len(s)), (c == 'MEDIUM') * np.ones(len(s)), (c == 'HARD') * np.ones(len(s)), E, s['traffic'].fillna(0).values,
                             (s['track_temp'].fillna(45).values - 45) / 10.0, (1 - (s['LapNumber'].values - 1) / max(s['LapNumber'].max(), 1)), ])
        ts = np.r_[1.0, np.diff(age)]; seqs.append(dict(sid=sid, comp=c, X=X, ts=ts, y=s['y'].values.astype(float), age=age))
    return seqs

def pad(seqs):
    L = max(len(q['y']) for q in seqs); N = len(seqs); F = seqs[0]['X'].shape[1]
    X = np.zeros((N, L, F)); TS = np.ones((N, L, 1)); Y = np.zeros((N, L)); Mk = np.zeros((N, L))
    for i, q in enumerate(seqs): n = len(q['y']); X[i, :n] = q['X']; TS[i, :n, 0] = q['ts']; Y[i, :n] = q['y']; Mk[i, :n] = 1
    return [torch.tensor(a, dtype=torch.float32) for a in (X, TS, Y, Mk)]

class Liquid(torch.nn.Module):
    def __init__(self, F):
        super().__init__(); self.cell = CfCCell(F, HID, mode='default', backbone_units=BACKBONE, backbone_layers=1); self.out = torch.nn.Linear(HID, 1)
    def forward(self, X, TS):
        h = torch.zeros(X.shape[0], HID); outs = []
        for t in range(X.shape[1]): o, h = self.cell(X[:, t], h, TS[:, t]); outs.append(self.out(o)[:, 0])
        return torch.stack(outs, 1)

def demean(v, Mk): m = (v * Mk).sum(1, keepdim=True) / Mk.sum(1, keepdim=True).clamp(min=1); return (v - m) * Mk

def train(seqs_tr, seed):
    torch.manual_seed(seed); np.random.seed(seed)
    idx = np.random.permutation(len(seqs_tr)); nv = max(2, len(idx) // 6); va, tr = [seqs_tr[i] for i in idx[:nv]], [seqs_tr[i] for i in idx[nv:]]
    Xt, Tt, Yt, Mt = pad(tr); Xv, Tv, Yv, Mv = pad(va); m = Liquid(Xt.shape[2]); opt = torch.optim.Adam(m.parameters(), LR); best, best_state, bad = 1e9, None, 0
    for ep in range(EPOCHS):
        m.train(); opt.zero_grad(); loss = ((demean(m(Xt, Tt), Mt) - demean(Yt, Mt)) ** 2).sum() / Mt.sum(); loss.backward(); opt.step()
        m.eval()
        with torch.no_grad(): vl = float(((demean(m(Xv, Tv), Mv) - demean(Yv, Mv)) ** 2).sum() / Mv.sum())
        if vl < best - 1e-5: best, best_state, bad = vl, {k: v.clone() for k, v in m.state_dict().items()}, 0
        else: bad += 1
        if bad >= max(25, EPOCHS // 6): break
    m.load_state_dict(best_state); m.eval(); return m

def predict(models, seqs):
    X, TS, Y, Mk = pad(seqs)
    with torch.no_grad(): P = torch.stack([demean(m(X, TS), Mk) for m in models]).mean(0)
    return P.numpy(), demean(Y, Mk).numpy(), Mk.numpy()

COV_COLS = [4, 5, 7]   # energy z-score, traffic share, race progress (fuel proxy) — the same per-lap inputs the liquid model sees
def poly_fit_predict(train_seqs, test_seqs, deg, covs=False):
    """stint fixed effects + per-compound polynomial in age (deg 1 or 2) [+ pooled per-lap covariates], predicting demeaned trajectories."""
    rows = []
    for q in train_seqs:
        for i, (a, y) in enumerate(zip(q['age'], q['y'])): rows.append((q['sid'], q['comp'], a, y, *q['X'][i, COV_COLS]))
    d = pd.DataFrame(rows, columns=['sid', 'comp', 'age', 'y', 'c1', 'c2', 'c3']); stints = sorted(d.sid.unique()); comps = [c for c in COMPS if (d.comp == c).sum() >= 8]
    cols = [(d.sid == s).astype(float).values for s in stints]
    for c in comps:
        for p in range(1, deg + 1): cols.append(((d.comp == c) * d.age ** p).values.astype(float))
    if covs: cols += [d['c1'].values, d['c2'].values, d['c3'].values]
    b, *_ = np.linalg.lstsq(np.column_stack(cols), d.y.values, rcond=None); coef = {c: b[len(stints) + i * deg: len(stints) + (i + 1) * deg] for i, c in enumerate(comps)}
    bc = b[len(stints) + len(comps) * deg:] if covs else np.zeros(3)
    preds = []
    for q in test_seqs:
        if q['comp'] not in coef: preds.append(None); continue
        f = sum(coef[q['comp']][p - 1] * q['age'] ** p for p in range(1, deg + 1)) + (q['X'][:, COV_COLS] @ bc if covs else 0); preds.append(f - f.mean())
    return preds, coef

def run_weekend(ev):
    d = M.load_event(ev); r = M.prep_race(d)
    if len(r) < 80: return None
    r['y'] = r['y'].astype(float); seqs = stint_tensors(r, r['energy_MJ'].mean(), r['energy_MJ'].std())
    if len(seqs) < 10: return None
    rng = np.random.default_rng(0); folds = rng.permutation(len(seqs)) % FOLDS; t0 = time.time()
    err = {c: {'linear': [], 'quadratic': [], 'linear_cov': [], 'liquid': []} for c in COMPS}; curv = {}
    for f in range(FOLDS):
        tr = [q for q, k in zip(seqs, folds) if k != f]; te = [q for q, k in zip(seqs, folds) if k == f]
        if not te or len(tr) < 6: continue
        models = [train(tr, seed) for seed in range(SEEDS)]; P, Yd, Mk = predict(models, te)
        lin, _ = poly_fit_predict(tr, te, 1); qua, qcoef = poly_fit_predict(tr, te, 2); lco, _ = poly_fit_predict(tr, te, 1, covs=True)
        for i, q in enumerate(te):
            n = len(q['y']); yd = q['y'] - q['y'].mean()
            err[q['comp']]['liquid'] += list(np.abs(P[i, :n] - yd))
            if lin[i] is not None: err[q['comp']]['linear'] += list(np.abs(lin[i] - yd))
            if qua[i] is not None: err[q['comp']]['quadratic'] += list(np.abs(qua[i] - yd))
            if lco[i] is not None: err[q['comp']]['linear_cov'] += list(np.abs(lco[i] - yd))
    # final curves on all stints: liquid at mean inputs per compound; quadratic curvature sign
    models = [train(seqs, seed) for seed in range(SEEDS)]; _, qcoef = poly_fit_predict(seqs, seqs, 2); curves = {}
    for c in COMPS:
        sc = [q for q in seqs if q['comp'] == c]
        if len(sc) < 3: continue
        Lmax = int(max(q['age'].max() for q in sc)); ages = np.arange(1, Lmax + 1, dtype=float)
        Xm = np.mean(np.concatenate([q['X'] for q in sc]), axis=0); X = np.tile(Xm, (Lmax, 1)); X[:, 0] = ages / 30.0
        Xt = torch.tensor(X[None], dtype=torch.float32); Tt = torch.ones(1, Lmax, 1)
        with torch.no_grad(): y = np.mean([m(Xt, Tt)[0].numpy() for m in models], axis=0)
        y = y - y[0]; slope = np.diff(y); early = float(np.mean(slope[:5])) if len(slope) >= 5 else float('nan'); mean_slope = float((y[-1] - y[0]) / max(len(y) - 1, 1))
        loc = np.convolve(slope, np.ones(3) / 3, mode='valid') if len(slope) >= 3 else slope
        cliff = next((int(ages[i + 2]) for i in range(4, len(loc)) if mean_slope > 0 and loc[i] > max(2 * mean_slope, 0.03)), None)
        curves[c] = dict(ages=ages.tolist(), liquid=y.round(4).tolist(), quadratic=[float(qcoef[c][0] * a + qcoef[c][1] * a * a - (qcoef[c][0] + qcoef[c][1])) for a in ages] if c in qcoef else None,
                         curvature=(float(qcoef[c][1]) if c in qcoef else None), early_slope=early, cliff_lap=cliff, n_stints=len(sc), n_laps=int(sum(len(q['y']) for q in sc)))
    out = dict(event=ev, seconds=round(time.time() - t0, 1), by_compound={c: dict(mae_linear=float(np.mean(e['linear'])) if e['linear'] else None, mae_quadratic=float(np.mean(e['quadratic'])) if e['quadratic'] else None, mae_linear_cov=float(np.mean(e['linear_cov'])) if e['linear_cov'] else None, mae_liquid=float(np.mean(e['liquid'])) if e['liquid'] else None, n_heldout_laps=len(e['liquid'])) for c, e in err.items() if e['liquid']}, curves=curves)
    print(f"{ev} ({out['seconds']}s):", {c: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()} for c, m in out['by_compound'].items()}, flush=True); return out

if __name__ == '__main__':
    evs = sys.argv[1:] or sorted({os.path.basename(f).split('_')[0] for f in glob.glob('feat/*_R.csv')})
    res = {}
    for ev in evs:
        o = run_weekend(ev)
        if o: res[ev] = o; json.dump(res, open(OUT, 'w'), indent=1)
    print("DONE", list(res))
