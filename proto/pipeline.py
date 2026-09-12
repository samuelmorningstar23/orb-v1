"""Orb v1 pipeline. Every weekend in feat/ -> out/lock.json (single source of truth for dashboard and deck),
out/results.csv (one row per compound-weekend) and out/excluded_<event>.csv (every dropped practice lap with its reason).

Completed weekends (practice + race): scored leave-one-weekend-out. Live weekend (practice only): curves issued with
transfer factors learned from all completed weekends. Withheld compounds get the low-degradation fallback, also learned
leave-one-out from the race outcomes of other withheld cases. The push covariate (within-run tyre-energy deviation) is
reported as a diagnostic that explains the gate; the as-driven estimator remains the predictor."""
import glob, os, json, sys, datetime as dt, numpy as np, pandas as pd, warnings
import model_v2 as M, strategy2 as S
warnings.filterwarnings('ignore')
COMPS = ['SOFT', 'MEDIUM', 'HARD']; MIN_PRAC, MIN_SLOPE, MIN_AGREE = 30, 0.02, 3
PIRELLI = {'Madrid': 'C2 hard / C3 medium / C4 soft (Pirelli nomination)'}
rng = np.random.default_rng(0)

def fit_push(df, xcol='TyreLife'):
    """as M.fit plus a pooled within-run energy-deviation covariate (s per MJ): degradation at constant push."""
    d = df.dropna(subset=[xcol, 'y']).copy(); d['e_dm'] = (d['energy_MJ'] - d.groupby('stint_id')['energy_MJ'].transform('mean')).fillna(0.0)
    stints = sorted(d.stint_id.unique()); comps = [c for c in COMPS if (d.Compound == c).sum() >= 8]
    X = np.column_stack([(d.stint_id == s).astype(float).values for s in stints] + [((d.Compound == c) * d[xcol]).values.astype(float) for c in comps] + [d['e_dm'].values])
    y = d['y'].values; b, *_ = np.linalg.lstsq(X, y, rcond=None); r = y - X @ b; s2 = (r @ r) / max(1, len(y) - X.shape[1])
    se = np.sqrt(np.diag(s2 * np.linalg.pinv(X.T @ X))); k = len(stints)
    return {c: float(b[k + i]) for i, c in enumerate(comps)}, {c: float(se[k + i]) for i, c in enumerate(comps)}, float(b[-1]), float(se[-1])

def energy_trend(p, c):
    s = p[p.Compound == c].dropna(subset=['energy_MJ', 'TyreLife'])
    if len(s) < 10: return float('nan')
    a = s['TyreLife'] - s.groupby('stint_id')['TyreLife'].transform('mean'); e = s['energy_MJ'] - s.groupby('stint_id')['energy_MJ'].transform('mean')
    m = np.isfinite(a) & np.isfinite(e)
    return float(np.polyfit(a[m], e[m], 1)[0]) if (m.sum() >= 10 and a[m].std() > 0) else float('nan')

def exclusions(d):
    """every practice lap that the estimator drops, with the first reason that applies (same order as M.prep_practice)."""
    p = d[d['session'].isin(['FP1', 'FP2', 'FP3'])].copy(); reason = pd.Series('kept', index=p.index)
    def mark(mask, why): reason[(reason == 'kept') & mask] = why
    mark(~p['Compound'].isin(COMPS), 'unknown / wet compound'); mark(p['deleted'].astype(bool), 'lap deleted (track limits)')
    mark(p['pit_in'] | p['pit_out'], 'pit in/out lap'); mark(p['TrackStatus'].astype(str) != '1', 'yellow / SC / VSC / red flag')
    mark(~p['IsAccurate'].astype(bool), 'timing flagged inaccurate'); mark(p['energy_MJ'].isna(), 'telemetry missing')
    mark(p['traffic'].isna(), 'no gap-to-car-ahead data'); mark(p['traffic'] > M.TRAFFIC_MAX, f'traffic (>{int(M.TRAFFIC_MAX*100)}% of lap within 60 m of a car)')
    kept = reason == 'kept'; size = p[kept].groupby('stint_id')['lap_s'].transform('size').reindex(p.index)
    mark(kept & (size < M.MIN_STINT), f'short run (<{M.MIN_STINT} clean laps)')
    kept = reason == 'kept'; best = p[kept].groupby('stint_id')['lap_s'].transform('min').reindex(p.index)
    mark(kept & (p['lap_s'] > 1.05 * best), 'cool-down / aborted (>105% of run best)')
    p['reason'] = reason; return p[['session', 'Driver', 'LapNumber', 'Stint', 'Compound', 'TyreLife', 'lap_s', 'traffic', 'reason']]

def weekend(ev):
    d = M.load_event(ev); sessions = sorted(d['session'].unique()); has_race = 'R' in sessions
    p, evo = M.prep_practice(d); r = M.prep_race(d) if has_race else d.iloc[0:0]
    if len(p) < 40: return None
    A, A_se, _, _ = M.fit(p, 'TyreLife'); A3, A3_se, beta_p, beta_p_se = fit_push(p)
    pn = p.dropna(subset=['TyreLife', 'lap_s'])
    naive = {c: float(np.polyfit(pn.loc[pn.Compound == c, 'TyreLife'], pn.loc[pn.Compound == c, 'lap_s'], 1)[0]) for c in COMPS if (pn.Compound == c).sum() >= 8}
    race = {}; race_unusable = bool(has_race and len(r) < 80)
    if has_race and len(r) >= 80:
        RA, RA_se, _, _ = M.fit(r, 'TyreLife'); tel_ok = r['energy_source'].iloc[0] == 'telemetry'
        R3, _, beta_r, _ = fit_push(r) if tel_ok else (RA, None, float('nan'), None)
        race = dict(obs=RA, obs_se=RA_se, obs_push=R3, beta_race=beta_r, n=int(len(r)), stints=int(r.stint_id.nunique()), telemetry=('telemetry' if tel_ok else 'degraded: energy pace-estimated'))
    rows = []
    for c in COMPS:
        if c not in A: continue
        n = int((p.Compound == c).sum()); gate = 'too few clean practice laps' if n < MIN_PRAC else ('no positive degradation signal in cleaned practice' if A[c] < MIN_SLOPE else 'ok')
        rows.append(dict(event=ev, compound=c, n_prac=n, naive=naive.get(c, np.nan), clean=A[c], clean_se=A_se[c], push_adj=A3.get(c, np.nan), push_adj_se=A3_se.get(c, np.nan),
                         energy_trend=energy_trend(p, c), gate=gate, obs=race['obs'].get(c, np.nan) if race else np.nan, obs_se=race['obs_se'].get(c, np.nan) if race else np.nan,
                         obs_push=race['obs_push'].get(c, np.nan) if race else np.nan, n_race=int((r.Compound == c).sum()) if len(r) else 0))
    ex = exclusions(d)
    meta = dict(event=ev, sessions=sessions, format=('sprint' if 'S' in sessions else 'conventional'), completed=bool(race), practice_laps_clean=int(len(p)), practice_runs=int(p.stint_id.nunique()),
                practice_laps_total=int((d['session'].isin(['FP1', 'FP2', 'FP3'])).sum()), evolution_s_per_min={k: round(float(v), 4) for k, v in evo.items()}, beta_practice_s_per_MJ=beta_p, beta_practice_se=beta_p_se,
                track_temp={s: float(d.loc[d.session == s, 'track_temp'].iloc[0]) for s in sessions if (d.session == s).any()}, rain={s: bool(d.loc[d.session == s, 'rain'].iloc[0]) for s in sessions if (d.session == s).any()},
                excluded_by_reason=ex[ex.reason != 'kept'].groupby('reason').size().sort_values(ascending=False).to_dict(), race=({k: v for k, v in race.items() if k in ('n', 'stints', 'telemetry', 'beta_race')} if race else None),
                race_unusable=race_unusable, tyres=PIRELLI.get(ev), offsets=S.offsets_from_sessions(d)[0], offsets_source=S.offsets_from_sessions(d)[1])
    return pd.DataFrame(rows), meta, ex

def agree_factor(ratios):
    """median of other weekends' race/practice ratio, applied only when >=3 exist and a majority sit within ±50% of the median."""
    o = pd.Series(ratios).dropna()
    if len(o) < MIN_AGREE: return 1.0, False
    med = float(o.median()); agree = int(((o >= 0.5 * med) & (o <= 1.5 * med)).sum())
    return (med, True) if agree >= max(MIN_AGREE, int(np.ceil(len(o) / 2))) else (1.0, False)

def band(clean, se, ratios, applied, n=4000):
    """5–95% band of clean × factor: slope noise from the regression, factor noise from resampling other weekends."""
    o = np.array(pd.Series(ratios).dropna()); s = rng.normal(clean, max(se, 1e-6), n)
    if len(o) >= MIN_AGREE: k = np.median(o[rng.integers(0, len(o), (n, len(o)))], axis=1) if applied else o[rng.integers(0, len(o), n)]
    else: k = np.ones(n)
    v = s * k; return [float(np.percentile(v, 5)), float(np.percentile(v, 95))]

if __name__ == '__main__':
    os.makedirs('out', exist_ok=True)
    evs = sorted({os.path.basename(f).split('_')[0] for f in glob.glob('feat/*_FP1.csv')})
    tables, metas = [], {}
    for ev in evs:
        w = weekend(ev)
        if w is None: print(f"{ev}: too few clean practice laps, skipped"); continue
        t, meta, ex = w; tables.append(t); metas[ev] = meta; ex.to_csv(f'out/excluded_{ev}.csv', index=False)
    R = pd.concat(tables, ignore_index=True); R['issued'] = R.gate == 'ok'; R['completed'] = R.event.map(lambda e: metas[e]['completed'])
    V = R[R.completed & R.obs.notna()].copy(); V['ratio'] = np.where(V.issued, V.obs / V.clean, np.nan)
    # leave-one-weekend-out transfer factors and fallback floor on completed weekends
    for i, row in V.iterrows():
        others = V[(V.event != row.event) & (V.compound == row.compound) & V.issued]['ratio']
        k, applied = agree_factor(others); V.loc[i, 'k'] = k; V.loc[i, 'k_applied'] = applied
        V.loc[i, ['lo', 'hi']] = band(row.clean, row.clean_se, others, applied) if row.issued else [np.nan, np.nan]
        wh = V[(V.event != row.event) & ~V.issued]['obs']
        V.loc[i, 'floor'] = float(wh.median()) if len(wh) >= 2 else np.nan
        if not row.issued: V.loc[i, ['lo', 'hi']] = [float(wh.quantile(0.1)), float(wh.quantile(0.9))] if len(wh) >= 3 else [np.nan, np.nan]
        o3 = V[(V.event != row.event) & (V.compound == row.compound) & (V.push_adj >= MIN_SLOPE)]; k3, applied3 = agree_factor(o3.obs / o3.push_adj); V.loc[i, 'k3'] = k3; V.loc[i, 'k3_applied'] = applied3
    V['pred_push'] = np.where(V.push_adj >= MIN_SLOPE, V.push_adj * V.k3, np.nan)
    V['pred_clearstint'] = np.where(V.issued, V.clean * V.k, V.floor)
    V['half'] = (V.hi - V.lo) / 2; V['z'] = (V.obs - V.pred_clearstint).abs() / V.half.replace(0, np.nan)
    V['lo_raw'], V['hi_raw'] = V.lo, V.hi
    for i, row in V.iterrows():
        z_other = V[(V.event != row.event)].z.dropna(); w = float(np.percentile(z_other, 90)) if len(z_other) >= 5 else 1.0   # pooled over case types: more stable at n≈30 than per-type
        V.loc[i, 'widen'] = w; V.loc[i, 'lo'] = row.pred_clearstint - w * (row.pred_clearstint - row.lo_raw); V.loc[i, 'hi'] = row.pred_clearstint + w * (row.hi_raw - row.pred_clearstint)
    WIDEN_ALL = float(np.percentile(V.z.dropna(), 90)) if V.z.notna().sum() >= 5 else 1.0; WIDEN = {True: WIDEN_ALL, False: WIDEN_ALL}
    V['err_naive'] = (V.naive - V.obs).abs(); V['err_clean'] = np.where(V.issued, (V.clean - V.obs).abs(), np.nan); V['err_cs'] = (V.pred_clearstint - V.obs).abs(); V['err_push'] = np.where(V.issued, (V.push_adj - V.obs).abs(), np.nan)
    iss = V[V.issued]
    def boot(a, b=None, n=4000):
        x = a.values if b is None else (a.values - b.values); idx = rng.integers(0, len(x), (n, len(x))); m = x[idx].mean(1); return [float(np.percentile(m, 5)), float(np.percentile(m, 95))], float((m > 0).mean())
    def calib(pred, obs):
        m = np.isfinite(pred) & np.isfinite(obs); s = np.polyfit(pred[m], obs[m], 1)[0]; return dict(slope=float(s), r=float(np.corrcoef(pred[m], obs[m])[0, 1]), n=int(m.sum()))
    validation = dict(
        n_weekends=int(V.event.nunique()), n_compound_weekends=int(len(V)), n_issued=int(V.issued.sum()), n_withheld=int((~V.issued).sum()),
        mae_issued=dict(naive=float(iss.err_naive.mean()), clean=float(iss.err_clean.mean()), clearstint=float(iss.err_cs.mean()), push_adjusted=float(iss.err_push.mean())),
        mae_all_with_fallback=dict(naive=float(V.err_naive.mean()), clearstint=float(V.err_cs.mean())),
        ci90_mae_clearstint_all=boot(V.err_cs)[0], p_clearstint_beats_clean_issued=boot(iss.err_clean, iss.err_cs)[1], p_clearstint_beats_naive_all=boot(V.err_naive, V.err_cs)[1],
        calibration=dict(naive=calib(V.naive.values, V.obs.values), clean=calib(iss.clean.values, iss.obs.values), clearstint=calib(iss.pred_clearstint.values, iss.obs.values), all_with_fallback=calib(V.pred_clearstint.values, V.obs.values)),
        by_compound={c: dict(n=int((V.compound == c).sum()), mae_naive=float(V[V.compound == c].err_naive.mean()), mae_clearstint=float(V[V.compound == c].err_cs.mean()), k_median=float(V[(V.compound == c) & V.issued].ratio.median())) for c in COMPS},
        withheld_cases=V[~V.issued][['event', 'compound', 'gate', 'clean', 'obs', 'floor']].round(4).to_dict(orient='records'),
        push_diagnostic=dict(energy_trend_withheld=V[~V.issued].energy_trend.describe()[['min', '50%', 'max']].round(3).to_dict(), energy_trend_issued=V[V.issued].energy_trend.describe()[['min', '50%', 'max']].round(3).to_dict(),
                             beta_practice_vs_race=[dict(event=e, practice=round(metas[e]['beta_practice_s_per_MJ'], 3), race=round(metas[e]['race']['beta_race'], 3)) for e in V.event.unique() if metas[e]['race'] and np.isfinite(metas[e]['race']['beta_race'])]),
        path_b_push_adjusted=dict(n_withheld_with_push_signal=int(((~V.issued) & V.pred_push.notna()).sum()), mae_fallback=float((V[(~V.issued) & V.pred_push.notna()].floor - V[(~V.issued) & V.pred_push.notna()].obs).abs().mean()), mae_push_adjusted=float((V[(~V.issued) & V.pred_push.notna()].pred_push - V[(~V.issued) & V.pred_push.notna()].obs).abs().mean()), k3_medians={c: float((V[(V.compound == c) & (V.push_adj >= MIN_SLOPE)].obs / V[(V.compound == c) & (V.push_adj >= MIN_SLOPE)].push_adj).median()) for c in COMPS}),
        band_coverage=dict(raw_all=float(((V.lo_raw <= V.obs) & (V.obs <= V.hi_raw)).mean()), calibrated_issued=float(((V[V.issued].lo <= V[V.issued].obs) & (V[V.issued].obs <= V[V.issued].hi)).mean()), calibrated_fallback=float(((V[~V.issued].lo <= V[~V.issued].obs) & (V[~V.issued].obs <= V[~V.issued].hi)).mean()), calibrated_all=float(((V.lo <= V.obs) & (V.obs <= V.hi)).mean()), nominal=0.90, widening_factor_median=float(V.widen.median()), widening_issued=float(V[V.issued].widen.median()), widening_fallback=float(V[~V.issued].widen.median()), method='leave-one-weekend-out conformal, pooled over issued and fallback cases: half-widths scaled by the 90th percentile of standardised residuals on the other weekends'),
        wins_clearstint_over_naive=int((V.err_cs < V.err_naive).sum()), wins_clearstint_over_clean_issued=int((iss.err_cs < iss.err_clean).sum()))
    # live weekends: factors from all completed weekends
    live = {}
    for ev in R[~R.completed].event.unique():
        if metas[ev].get('race_unusable'): continue   # race session exists but yielded no clean laps (disrupted race): neither scored nor live
        L = R[R.event == ev].copy(); out = []
        for _, row in L.iterrows():
            others = V[(V.compound == row.compound) & V.issued]['ratio']; k, applied = agree_factor(others); wh = V[~V.issued]['obs']
            if row.issued: pred, lo_hi = row.clean * k, band(row.clean, row.clean_se, others, applied)
            else: pred, lo_hi = float(wh.median()), [float(wh.quantile(0.1)), float(wh.quantile(0.9))]
            wf = WIDEN[bool(row.issued)]; lo_hi = [pred - wf * (pred - lo_hi[0]), pred + wf * (lo_hi[1] - pred)]
            o3 = V[(V.compound == row.compound) & (V.push_adj >= MIN_SLOPE)]; k3, applied3 = agree_factor(o3.obs / o3.push_adj)
            second = (dict(prediction=float(row.push_adj * k3), factor=k3, factor_applied=applied3, basis='push-adjusted Friday curve (degradation at constant tyre energy) × its own season factor') if (not row.issued and np.isfinite(row.push_adj) and row.push_adj >= MIN_SLOPE) else None)
            out.append(dict(compound=row.compound, n_prac=int(row.n_prac), second_opinion=second, naive=row.naive, clean=row.clean, clean_se=row.clean_se, gate=row.gate, issued=bool(row.issued), factor=k, factor_applied=applied,
                            factor_from_n_weekends=int(others.notna().sum()), prediction=pred, band90=lo_hi, energy_trend=row.energy_trend, push_adj=row.push_adj,
                            basis=('cleaned Friday curve × season transfer factor' if (row.issued and applied) else 'cleaned Friday curve (weekends disagree on the factor)' if row.issued else f'low-degradation fallback: median race degradation of the {int(len(wh))} withheld cases this season')))
        live[ev] = dict(meta=metas[ev], compounds=out)
    strategy = {}
    for ev in V.event.unique():
        rows = V[V.event == ev]; sl = lambda col: {r.compound: float(r[col]) for _, r in rows.iterrows() if np.isfinite(r[col])}
        offs = metas[ev]['offsets']; n_laps = int(pd.read_csv(f'feat/{ev}_R.csv')['LapNumber'].max())
        truth = sl('obs'); views = {'Naive fit': sl('naive'), 'Cleaned Friday curve': {**{c: v for c, v in sl('clean').items()}, **{r.compound: float(r.floor) for _, r in rows.iterrows() if not r.issued and np.isfinite(r.floor)}}, 'Orb v1': sl('pred_clearstint')}
        strategy[ev] = dict(n_laps=n_laps, offsets=offs, offsets_source=metas[ev]['offsets_source'], pit_loss=S.PIT_LOSS, views=S.replay(views, offs, n_laps, truth))
    for ev, Lv in live.items():
        n_laps = S.RACE_LAPS.get(ev); 
        if not n_laps: continue
        offs = metas[ev]['offsets']
        views = {'Naive fit': {c['compound']: c['naive'] for c in Lv['compounds'] if np.isfinite(c['naive'])}, 'Orb v1': {c['compound']: c['prediction'] for c in Lv['compounds']},
                 'Orb v1, band low': {c['compound']: c['band90'][0] for c in Lv['compounds']}, 'Orb v1, band high': {c['compound']: c['band90'][1] for c in Lv['compounds']}}
        strategy[ev] = dict(n_laps=n_laps, offsets=offs, offsets_source=metas[ev]['offsets_source'], pit_loss=S.PIT_LOSS, views=S.replay(views, offs, n_laps), note='two compounds in the data only; hard had 4 clean laps on Friday' if len(Lv['compounds']) < 3 else None)
    lock = dict(generated_at=dt.datetime.now().isoformat(timespec='seconds'), rules=dict(min_practice_laps=MIN_PRAC, min_slope=MIN_SLOPE, factor_rule='median of other weekends, applied only if >=3 exist and a majority sit within ±50% of it', fuel_prior_kg_per_lap=M.FUEL_KG_PER_LAP_PRACTICE, fuel_s_per_kg=M.FUEL_S_PER_KG, traffic_max=M.TRAFFIC_MAX, min_stint=M.MIN_STINT),
                events={e: metas[e] for e in metas}, validation=validation, validation_rows=V.round(4).replace({np.nan: None}).to_dict(orient='records'), live=live, strategy=strategy)
    json.dump(lock, open('out/lock.json', 'w'), indent=1, default=lambda o: float(o) if isinstance(o, (np.floating, np.integer)) else str(o)); R.round(4).to_csv('out/results.csv', index=False); V.round(4).to_csv('out/validation.csv', index=False)
    print(f"weekends: {len(metas)} | completed {V.event.nunique()} | live {list(live)}"); print(json.dumps(validation['mae_issued'], indent=0), json.dumps(validation['mae_all_with_fallback']), json.dumps(validation['calibration']['all_with_fallback']))
    for ev, L in live.items():
        print(f"\nLIVE {ev}:"); [print(f"  {c['compound']:6s} n={c['n_prac']:3d} naive {c['naive']:+.3f} clean {c['clean']:+.3f} -> {c['prediction']:+.3f} s/lap [{c['band90'][0]:+.3f},{c['band90'][1]:+.3f}] | {c['basis']}") for c in L['compounds']]
