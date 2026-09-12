"""ClearStint v2: degradation per unit tyre energy vs per lap, fitted on practice, validated on race.

For each event:
  practice = FP1+FP2+FP3 long-run laps (stint >= 5 clean laps), traffic laps removed, lifted laps kept (energy explains them)
  Model A (lap-count):   y = FE_stint + deg_A[c] * TyreLife
  Model B (energy):      y = FE_stint + deg_B[c] * CumEnergy_MJ
  where y = lap_s - fuel_prior - track_evolution(session time, per session)
  Race: same estimators give observed per-lap degradation and mean energy per lap per compound.
  Prediction of race per-lap deg:  A -> deg_A ;  B -> deg_B * race_energy_per_lap[c]
"""
import numpy as np, pandas as pd, json, glob, sys, os
FUEL_S_PER_KG, FUEL_KG_PER_LAP_PRACTICE, RACE_FUEL_KG = 0.03, 1.1, 70.0   # 2026 regs: ~70 kg race fuel
COMPS = ['SOFT','MEDIUM','HARD']
TRAFFIC_MAX = 0.30      # share of lap spent < 60 m behind another car
MIN_STINT = 5

def load_event(ev):
    fs = sorted(glob.glob(f'feat/{ev}_*.csv'))
    if not fs: return None
    d = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    d['clean'] = d['IsAccurate'] & (d['TrackStatus'].astype(str)=='1') & ~d['pit_in'] & ~d['pit_out'] & d['energy_MJ'].notna() & d['Compound'].isin(COMPS) & (~d['deleted'])
    d['stint_id'] = d['session']+'_'+d['Driver']+'_'+d['Stint'].fillna(0).astype(int).astype(str)
    # cumulative tyre energy over the stint uses every lap actually driven (out-lap included, fill missing with stint median)
    d = d.sort_values(['stint_id','LapNumber'])
    d['e_fill'] = d['energy_MJ'].fillna(d.groupby('stint_id')['energy_MJ'].transform('median'))
    d['cum_E'] = d.groupby('stint_id')['e_fill'].cumsum() - d['e_fill']   # energy already in the tyre *before* this lap
    d['cum_E'] += d.groupby('stint_id')['e_fill'].transform('median') * (d['TyreLife'] - d.groupby('stint_id')['TyreLife'].transform('min'))*0  # (age already counted by cumsum order)
    return d

def evolution(sess_df):
    """track evolution per minute from each driver's push laps (<=101% of own best), driver-demeaned"""
    p = sess_df[sess_df['clean']].copy()
    if p.empty: return 0.0
    p = p[p['lap_s'] <= 1.01*p.groupby('Driver')['lap_s'].transform('min')]
    if len(p) < 8 or p['t_min'].std() < 1: return 0.0
    p['dm'] = p['lap_s'] - p.groupby('Driver')['lap_s'].transform('mean')
    return float(np.polyfit(p['t_min'], p['dm'], 1)[0])

def fit(df, xcol):
    """stint fixed effects + per-compound slope on xcol. returns slopes, se, resid std, fitted df"""
    d = df.dropna(subset=[xcol, 'y']).copy(); stints = sorted(d['stint_id'].unique())
    X = [(d['stint_id']==s).astype(float).values for s in stints]
    comps = [c for c in COMPS if (d['Compound']==c).sum() >= 8]
    X += [((d['Compound']==c)*d[xcol]).values.astype(float) for c in comps]
    X = np.column_stack(X); y = d['y'].values
    b, *_ = np.linalg.lstsq(X, y, rcond=None); r = y - X@b
    dof = max(1, len(y)-X.shape[1]); s2 = (r@r)/dof
    try: cov = s2*np.linalg.pinv(X.T@X); se = np.sqrt(np.diag(cov))
    except Exception: se = np.full(X.shape[1], np.nan)
    k = len(stints)
    slopes = {c: float(b[k+i]) for i,c in enumerate(comps)}; ses = {c: float(se[k+i]) for i,c in enumerate(comps)}
    d['fe'] = d['stint_id'].map(dict(zip(stints, b[:k]))); d['y_rel'] = d['y'] - d['fe']; d['resid'] = r
    return slopes, ses, float(r.std()), d

def prep_practice(d):
    p = d[d['session'].isin(['FP1','FP2','FP3'])].copy()
    evo = {s: evolution(p[p['session']==s]) for s in p['session'].unique()}
    p = p[p['clean'] & (p['traffic'] <= TRAFFIC_MAX)]   # NaN traffic (no gap data) is excluded, not assumed clean
    p = p[p.groupby('stint_id')['lap_s'].transform('size') >= MIN_STINT]     # long runs only
    # keep laps within 105% of stint best: removes cool-down / aborted laps but keeps tyre-management laps
    p = p[p['lap_s'] <= 1.05*p.groupby('stint_id')['lap_s'].transform('min')]
    fuel = 40 - FUEL_KG_PER_LAP_PRACTICE*(p['TyreLife']-1)
    p['y'] = p['lap_s'] - FUEL_S_PER_KG*fuel - p['session'].map(evo)*p['t_min']
    return p, evo

def energy_from_pace(d):
    """Fallback for degraded telemetry: fit E = a + b*lap_s on clean practice laps of this event."""
    p = d[d['session'].isin(['FP1','FP2','FP3']) & d['clean'] & (d['pos_distinct'] >= 100)]
    if len(p) < 50: return None
    b, a = np.polyfit(p['lap_s'], p['energy_MJ'], 1); return (a, b)

def prep_race(d):
    r = d[d['session']=='R'].copy()
    if r.empty: return r
    r['telemetry_ok'] = r['pos_distinct'] >= 100
    r['energy_source'] = 'telemetry'
    if r['telemetry_ok'].mean() < 0.5:
        ab = energy_from_pace(d)
        if ab is not None:
            r['energy_MJ'] = ab[0] + ab[1]*r['lap_s']; r['energy_source'] = 'pace-estimated (telemetry degraded)'
    r = r.sort_values(['stint_id','LapNumber']); r['e_fill'] = r['energy_MJ'].fillna(r.groupby('stint_id')['energy_MJ'].transform('median'))
    r['cum_E'] = r.groupby('stint_id')['e_fill'].cumsum() - r['e_fill']
    n_laps = int(r['LapNumber'].max())
    r = r[r['clean'] & ((r['traffic'] <= TRAFFIC_MAX) | (~r['telemetry_ok'] & r['traffic'].isna()))]   # degraded feed: traffic unknown, keep lap but flag
    r = r[r.groupby('stint_id')['lap_s'].transform('size') >= 8]
    r = r[r['lap_s'] <= 1.05*r.groupby('stint_id')['lap_s'].transform('min')]
    fuel = RACE_FUEL_KG*(1-(r['LapNumber']-1)/n_laps)
    r['y'] = r['lap_s'] - FUEL_S_PER_KG*fuel
    return r

def run_event(ev, verbose=True):
    d = load_event(ev)
    if d is None or 'R' not in set(d['session']): return None
    p, evo = prep_practice(d); r = prep_race(d)
    if len(p) < 40 or len(r) < 80: return None
    A, A_se, A_rs, pA = fit(p, 'TyreLife')
    B, B_se, B_rs, pB = fit(p, 'cum_E')
    RA, RA_se, RA_rs, rA = fit(r, 'TyreLife')           # observed race deg per lap
    RB, RB_se, RB_rs, rB = fit(r, 'cum_E')
    race_E = r.groupby('Compound')['energy_MJ'].mean().to_dict()
    prac_E = p.groupby('Compound')['energy_MJ'].mean().to_dict()
    pn = p.dropna(subset=['TyreLife','lap_s'])
    naive = {c: float(np.polyfit(pn.loc[pn.Compound==c,'TyreLife'], pn.loc[pn.Compound==c,'lap_s'],1)[0]) for c in COMPS if (pn.Compound==c).sum()>=8}
    rows = []
    for c in COMPS:
        if c not in A or c not in RA or c not in B: continue
        predA = A[c]; predB = B[c]*race_E.get(c, np.nan); obs = RA[c]
        rows.append(dict(event=ev, compound=c, n_prac=int((p.Compound==c).sum()), n_race=int((r.Compound==c).sum()),
                         naive=naive.get(c, np.nan), predA=predA, predB=predB, obs=obs, errA=abs(predA-obs), errB=abs(predB-obs), err_naive=abs(naive.get(c,np.nan)-obs),
                         prac_E=prac_E.get(c,np.nan), race_E=race_E.get(c,np.nan), degB_per_MJ=B[c], seA=A_se[c], seB=B_se[c]*race_E.get(c,np.nan)))
    res = pd.DataFrame(rows)
    res['energy_source'] = r['energy_source'].iloc[0] if 'energy_source' in r else 'telemetry'
    if verbose and len(res):
        print(f"\n=== {ev}: practice laps {len(p)} ({p['stint_id'].nunique()} stints), race laps {len(r)} ({r['stint_id'].nunique()} stints); evo {({k: round(v,4) for k,v in evo.items()})}")
        print(res[['compound','n_prac','n_race','naive','predA','predB','obs','errA','errB','prac_E','race_E']].round(3).to_string(index=False)); print('race energy source:', res['energy_source'].iloc[0])
    return dict(res=res, p=pA, pB=pB, r=rA, rB=rB, A=A, B=B, RA=RA, race_E=race_E, prac_E=prac_E, evo=evo)

if __name__ == '__main__':
    evs = sys.argv[1:] or sorted({os.path.basename(f).split('_')[0] for f in glob.glob('feat/*_R.csv')})
    allres = []
    for ev in evs:
        out = run_event(ev)
        if out is not None: allres.append(out['res'])
    if allres:
        R = pd.concat(allres, ignore_index=True); R.to_csv('results_v2.csv', index=False)
        print("\n=== SUMMARY: mean abs error vs race (s/lap) ===")
        print(R.groupby('compound')[['err_naive','errA','errB']].mean().round(3).to_string())
        print("overall:", R[['err_naive','errA','errB']].mean().round(3).to_dict(), " n =", len(R))
        print("B better than A in", int((R.errB < R.errA).sum()), "of", len(R), "compound-weekends")

def sector_deg(r):
    """Where on the lap the tyre loses time: per-sector within-stint slope vs tyre age, per compound (race laps)."""
    out = {}
    for c in COMPS:
        s = r[(r['Compound']==c)].dropna(subset=['s1','s2','s3'])
        if len(s) < 30: continue
        res = {}
        for sec in ['s1','s2','s3']:
            d = s.copy(); d['y'] = d[sec]
            stints = sorted(d['stint_id'].unique())
            X = np.column_stack([(d['stint_id']==st).astype(float).values for st in stints] + [d['TyreLife'].values.astype(float)])
            b, *_ = np.linalg.lstsq(X, d['y'].values, rcond=None); res[sec] = float(b[-1])
        tot = sum(res.values()); out[c] = {k: v for k,v in res.items()} | {'total': tot, 'share': {k: (v/tot if tot else np.nan) for k,v in res.items()}}
    return out
