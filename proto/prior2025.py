"""Season prior: does the practice-to-race transfer ratio at a track repeat from 2025 to 2026? Runs the same estimator on feat2025/."""
import glob, os, sys, numpy as np, pandas as pd, json, warnings; warnings.filterwarnings('ignore')
import model_v2 as M
def load_event_dir(ev, d):
    fs = sorted(glob.glob(f'{d}/{ev}_*.csv'))
    if not fs: return None
    df = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    df['clean'] = df['IsAccurate'] & (df['TrackStatus'].astype(str) == '1') & ~df['pit_in'] & ~df['pit_out'] & df['energy_MJ'].notna() & df['Compound'].isin(M.COMPS) & (~df['deleted'].astype(bool))
    df['stint_id'] = df['session'] + '_' + df['Driver'] + '_' + df['Stint'].fillna(0).astype(int).astype(str)
    df = df.sort_values(['stint_id', 'LapNumber']); df['e_fill'] = df['energy_MJ'].fillna(df.groupby('stint_id')['energy_MJ'].transform('median'))
    df['cum_E'] = df.groupby('stint_id')['e_fill'].cumsum() - df['e_fill']; return df
def ratios(d):
    p, evo = M.prep_practice(d); r = M.prep_race(d)
    if len(p) < 40 or len(r) < 80: return {}
    A, A_se, _, _ = M.fit(p, 'TyreLife'); RA, _, _, _ = M.fit(r, 'TyreLife')
    return {c: dict(clean=A[c], obs=RA[c], n_prac=int((p.Compound == c).sum()), ratio=(RA[c] / A[c] if A[c] >= 0.02 and (p.Compound == c).sum() >= 30 else np.nan)) for c in M.COMPS if c in A and c in RA}
rows = []
for f in sorted(glob.glob('feat2025/*_R.csv')):
    ev = os.path.basename(f).split('_')[0]; d25 = load_event_dir(ev, 'feat2025'); d26 = load_event_dir(ev, 'feat')
    if d25 is None or d26 is None: continue
    r25, r26 = ratios(d25), ratios(d26)
    for c in M.COMPS:
        if c in r25 and c in r26: rows.append(dict(event=ev, compound=c, clean_2025=r25[c]['clean'], obs_2025=r25[c]['obs'], ratio_2025=r25[c]['ratio'], clean_2026=r26[c]['clean'], obs_2026=r26[c]['obs'], ratio_2026=r26[c]['ratio']))
R = pd.DataFrame(rows); R.round(3).to_csv('out/prior2025.csv', index=False); print(R.round(3).to_string(index=False))
ok = R.dropna(subset=['ratio_2025', 'ratio_2026'])
if len(ok) >= 3: print(f"\nsame track, both years issued: n={len(ok)} | corr(ratio 2025, ratio 2026) = {np.corrcoef(ok.ratio_2025, ok.ratio_2026)[0,1]:+.2f} | median ratio 2025 {ok.ratio_2025.median():.2f} vs 2026 {ok.ratio_2026.median():.2f} | medium only: 2025 {ok[ok.compound=='MEDIUM'].ratio_2025.median():.2f} vs 2026 {ok[ok.compound=='MEDIUM'].ratio_2026.median():.2f}")
