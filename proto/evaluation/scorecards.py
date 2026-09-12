"""The two scorecards, never merged (roadmap v5 section 9.0.1), plus the rolling-origin 2026 series.

Ghost Strategy scorecard (out/validation/ghost_scorecard.json)
    development_pool   2026 and the non-sealed 2023 to 2025 weekends, each forecast leave-one-weekend-out with factors
                       from its own season (a sealed race never enters a pool): pre-race degradation MAE (Orb v1, naive,
                       clean-only), 90 % band coverage, hidden-stop next-1 MAE and 3- and 5-lap cumulative MAE, strategy
                       regret, probability the recommended plan beats naive, error by circuit class, by driver support
                       status (hidden-stop cases: the pre-race curve has no driver term), by actual-weather regime of
                       the race, abstention coverage (share issued; error issued vs fallback)
    sealed_holdout     copied from out/validation/holdout_aggregate.json (aggregate only; written by the evaluator)
    rolling_origin_2026  for each 2026 round k in calendar order, the forecast with factors from the rounds before k only
Live Predictor scorecard (out/validation/live_scorecard.json)
    from Workstream 8's out/live/prefix_eval.json (next-lap and cumulative error, coverage, cliff Brier, alert lead time,
    false alerts per stint, recommendation stability), re-pooled with a race-grouped bootstrap (laps-weighted), plus the
    driver-feedback ablation: run only when recorded feedback events exist, in app_v2/state/feedback_events.jsonl (the UI
    log) or in Workstream 8's per-run logs out/live/<event>_<driver>/driver_feedback.json (defined experiment, not a
    pre-written result; when no event exists the scorecard says so plainly).
Ghost scorecard extras: by_season blocks and lock_consistency_2026, which recomputes the 2026 leave-one-weekend-out
numbers and compares them with out/lock.json (MAE naive / Orb v1 with fallback, calibration r, wins over naive, calibrated
band coverage, counts). The sealed block is copied from holdout_aggregate.json only when that file says quotable: true; a
dry run before the freeze is reported as such and its numbers are withheld (lead decision, 12 Sep 2026).
Every interval is a weekend-grouped bootstrap (evaluation.common weekend_bootstrap / weekend_mean_bootstrap); each block carries generated_at,
git_sha, data_cutoff and units.

CLI:  python -m evaluation.scorecards [--seasons 2026,2025,2024,2023] [--out out/validation]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from evaluation import PROTO, OUT_DIR, SEASON_DIRS, COMPS, CALENDAR_2026, circuit_class, weather_regime, git_sha, now_iso
from evaluation.common import mae, share, weekend_bootstrap, weekend_mean_bootstrap, paired_probability, write_json, finite
from evaluation.forecast import SeasonForecaster, score_forecast
from evaluation.hidden_stop import stop_cases, aggregate as hs_aggregate, drivers_seen_in
from evaluation.regret import weekend_regret, aggregate as regret_aggregate, LABEL as REGRET_LABEL

from counterfactual.racedata import load_race     # noqa: E402

PREFIX_EVAL = PROTO / 'out' / 'live' / 'prefix_eval.json'
FEEDBACK_LOG = PROTO / 'app_v2' / 'state' / 'feedback_events.jsonl'
LIVE_OUT = PROTO / 'out' / 'live'
LOCK_PATH = PROTO / 'out' / 'lock.json'
LOCK_TOL = 5e-4
DATA_CUTOFF_2026 = '2026-09-06T15:00:00 (Monza race, the latest completed 2026 round on disk; Madrid is the live weekend)'
UNITS = dict(degradation='s/lap per lap of tyre age', hidden_stop='s (next lap) and s over h laps (cumulative)', regret='s over the race', coverage='share inside the 90 % band', probability='0 to 1')


def _forecast_block(rows: pd.DataFrame, bootstrap: bool = True) -> dict[str, Any]:
    if rows is None or len(rows) == 0:
        return dict(n_weekends=0)
    iss, fb = rows[rows['issued']], rows[~rows['issued']]
    out: dict[str, Any] = dict(n_weekends=int(rows['race_id'].nunique()), n_compound_weekends=int(len(rows)), n_issued=int(len(iss)), n_withheld=int(len(fb)),
                               mae=dict(orb_v1=mae(rows['err']), naive=mae(rows['err_naive']), clean_issued=mae(iss['err_clean']), orb_v1_issued=mae(iss['err']), orb_v1_fallback=mae(fb['err']), naive_issued=mae(iss['err_naive'])),
                               band_coverage90=dict(all=share(rows['covered']), issued=share(iss['covered']), fallback=share(fb['covered']), nominal=0.90),
                               abstention=dict(share_issued=len(iss) / len(rows), share_withheld=len(fb) / len(rows), mae_issued=mae(iss['err']), mae_fallback=mae(fb['err'])),
                               by_compound={c: dict(n=int((rows['compound'] == c).sum()), mae_orb_v1=mae(rows[rows['compound'] == c]['err']), mae_naive=mae(rows[rows['compound'] == c]['err_naive'])) for c in COMPS},
                               wins_orb_over_naive=int(((rows['err'] < rows['err_naive']) & rows['err'].notna()).sum()))
    m = rows.dropna(subset=['prediction', 'obs'])
    if len(m) >= 3 and m['prediction'].std() > 0:
        out['calibration'] = dict(slope=float(np.polyfit(m['prediction'], m['obs'], 1)[0]), r=float(np.corrcoef(m['prediction'], m['obs'])[0, 1]), n=int(len(m)))
    if bootstrap:
        specs = {'mae_orb_v1': (rows, 'err'), 'mae_naive': (rows, 'err_naive'),
                 'mae_clean_issued': (iss, 'err_clean'), 'mae_orb_v1_issued': (iss, 'err'),
                 'mae_orb_v1_fallback': (fb, 'err'), 'mae_naive_issued': (iss, 'err_naive'),
                 'band_coverage90': (rows, 'covered'), 'band_coverage90_issued': (iss, 'covered'),
                 'band_coverage90_fallback': (fb, 'covered'), 'share_issued': (rows, 'issued')}
        out['bootstrap'] = {k: weekend_mean_bootstrap(d, c, n_unit='compound-weekends') for k, (d, c) in specs.items()}
        paired = rows.dropna(subset=['err', 'err_naive']).copy()
        paired['win'] = (paired['err'] < paired['err_naive']).astype(float)
        out['bootstrap']['win_share'] = weekend_mean_bootstrap(paired, 'win', n_unit='compound-weekends')
        out['bootstrap']['p_orb_beats_naive'] = paired_probability(rows, 'err', 'err_naive')
        def correlation(d):
            return float(d[['prediction', 'obs']].corr().iloc[0, 1]) if len(d) >= 3 and d['prediction'].std() > 0 and d['obs'].std() > 0 else None
        out['bootstrap']['calibration_r'] = weekend_bootstrap(m, correlation)
        out['bootstrap']['calibration_r'].update(n=len(m), n_unit='compound-weekends')
        for c, d in rows.groupby('compound'):
            out['by_compound'][c]['bootstrap'] = {k: weekend_mean_bootstrap(d, col, n_unit='compound-weekends') for k, col in [('mae_orb_v1', 'err'), ('mae_naive', 'err_naive')]}
    return out


def _hidden_cell(cases):
    h = hs_aggregate(cases)
    return dict(h['pooled'], bootstrap=h.get('bootstrap', {}))


def development_pool(seasons: Iterable[int], sealed: Iterable[str], quiet: bool = False) -> dict[str, Any]:
    fc_rows, hs_cases, regret_rows, weekends = [], [], [], []
    for season in seasons:
        F = SeasonForecaster(SEASON_DIRS[season], season, sealed=[r for r in sealed if r.startswith(f'{season}_')])
        loo = F.loo_forecasts()
        seen_pool = {ev: drivers_seen_in(F, fc.pool_events) for ev, fc in loo.items()}
        for ev, fc in loo.items():
            ref = F.reference(ev)
            race = load_race(ev, str(F.race_path(ev)))
            wx = weather_regime(F.metas[ev]['track_temp'].get('R'), F.metas[ev]['rain'].get('R', False))
            rows = score_forecast(fc, ref)
            for r in rows:
                r.update(circuit_class=circuit_class(ev), weather_regime=wx, season=int(season))
            fc_rows.extend(rows)
            cases, _ = stop_cases(race, fc, fc.race_id, seen_pool[ev])
            for c in cases:
                c['weather_regime'] = wx
            hs_cases.extend(cases)
            rg = weekend_regret(fc, ref, race)
            rg.update(weather_regime=wx)
            regret_rows.append(rg)
            weekends.append(dict(race_id=fc.race_id, season=season, event=ev, circuit_class=circuit_class(ev), weather_regime=wx, pool_n=len(fc.pool_events)))
        if not quiet:
            print(f'{season}: {len(loo)} development weekends scored')
    rows = pd.DataFrame(fc_rows)
    hs = pd.DataFrame(hs_cases)
    out: dict[str, Any] = dict(split='development pool: leave-one-weekend-out inside each season; sealed weekends excluded from every pool', weekends=weekends,
                               forecast=_forecast_block(rows), hidden_stop=hs_aggregate(hs_cases), regret=regret_aggregate(regret_rows), by_circuit_class={}, by_weather_regime={}, by_driver_support={})
    for key, store in (('circuit_class', 'by_circuit_class'), ('weather_regime', 'by_weather_regime')):
        for val, d in rows.groupby(key):
            cell = dict(forecast=_forecast_block(d, bootstrap=True))
            if len(hs):
                ha = hs_aggregate([c for c in hs_cases if c.get(key) == val], bootstrap=True)
                cell['hidden_stop'] = dict(ha['pooled'], bootstrap=ha.get('bootstrap', {}))
            cell['regret'] = regret_aggregate([r for r in regret_rows if r.get(key) == val], bootstrap=True)
            out[store][str(val)] = cell
    if len(hs):
        for val, d in hs.groupby('driver_support'):
            out['by_driver_support'][str(val)] = dict(hidden_stop=_hidden_cell([c for c in hs_cases if c.get('driver_support') == val]),
                                                     note='the pre-race degradation curve has no driver term; support status applies to the hidden-stop cases (driver seen in a pool weekend race)')
    out['abstention_coverage'] = out['forecast'].get('abstention')
    out['by_season'] = {}
    if len(rows):
        for season, d in rows.groupby('season'):
            out['by_season'][str(int(season))] = dict(split='leave-one-weekend-out inside the season (pipeline.py rules; sealed weekends excluded from the pool)', forecast=_forecast_block(d, bootstrap=True))
        if (rows['season'] == 2026).any():
            out['lock_consistency_2026'] = lock_consistency(rows[rows['season'] == 2026])
    return out


def _rel(p: Path) -> str:
    return str(p.relative_to(PROTO)) if p.is_relative_to(PROTO) else str(p)


def lock_meta(lock_path: Path = LOCK_PATH) -> dict[str, Any]:
    if not lock_path.exists():
        return dict(path=_rel(lock_path), status='missing')
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    v = lock.get('validation', {})
    scored = sorted({r['event'] for r in lock.get('validation_rows', []) if r.get('obs') is not None})
    events = sorted(lock.get('events', {}).keys()) if isinstance(lock.get('events'), dict) else []
    return dict(path=_rel(lock_path), sha256=hashlib.sha256(lock_path.read_bytes()).hexdigest(), generated_at=lock.get('generated_at'), validation_n_weekends=v.get('n_weekends'), validation_n_compound_weekends=v.get('n_compound_weekends'),
                scored_events=scored, prospective_events=[e for e in events if e not in scored])


def lock_consistency(rows: pd.DataFrame, lock_path: Path = LOCK_PATH, tol: float = LOCK_TOL) -> dict[str, Any]:
    """The 2026 leave-one-weekend-out numbers reported here must equal out/lock.json's validation block (same rules, same
    pool): MAE naive / Orb v1 with fallback (all compound-weekends) and issued, calibration r, wins over naive, calibrated
    90 % band coverage and the counts. Returns every pair with a match flag (counts exact, floats within tol)."""
    if not lock_path.exists():
        return dict(status='lock not found', path=_rel(lock_path))
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    v = lock.get('validation', {})
    iss = rows[rows['issued']]
    m = rows.dropna(subset=['prediction', 'obs'])
    r = float(np.corrcoef(m['prediction'], m['obs'])[0, 1]) if len(m) >= 3 and m['prediction'].std() > 0 else None
    sc = dict(n_weekends=int(rows['race_id'].nunique()), n_compound_weekends=int(len(rows)), n_issued=int(len(iss)), n_withheld=int(len(rows) - len(iss)),
              mae_naive_all=mae(rows['err_naive']), mae_orb_v1_all=mae(rows['err']), mae_naive_issued=mae(iss['err_naive']), mae_orb_v1_issued=mae(iss['err']),
              calibration_r_all=r, wins_orb_over_naive=int(((rows['err'] < rows['err_naive']) & rows['err'].notna()).sum()), band_coverage90_all=share(rows['covered']))
    lk = dict(n_weekends=v.get('n_weekends'), n_compound_weekends=v.get('n_compound_weekends'), n_issued=v.get('n_issued'), n_withheld=v.get('n_withheld'),
              mae_naive_all=v.get('mae_all_with_fallback', {}).get('naive'), mae_orb_v1_all=v.get('mae_all_with_fallback', {}).get('clearstint'),
              mae_naive_issued=v.get('mae_issued', {}).get('naive'), mae_orb_v1_issued=v.get('mae_issued', {}).get('clearstint'),
              calibration_r_all=v.get('calibration', {}).get('all_with_fallback', {}).get('r'), wins_orb_over_naive=v.get('wins_clearstint_over_naive'),
              band_coverage90_all=v.get('band_coverage', {}).get('calibrated_all'))
    comp: dict[str, Any] = {}
    for k in sc:
        a, b = sc[k], lk[k]
        if a is None or b is None:
            comp[k] = dict(scorecard=a, lock=b, match=None)
        elif k.startswith('n_') or k.startswith('wins'):
            comp[k] = dict(scorecard=int(a), lock=int(b), match=int(a) == int(b))
        else:
            comp[k] = dict(scorecard=float(a), lock=float(b), abs_diff=abs(float(a) - float(b)), match=abs(float(a) - float(b)) <= tol)
    return dict(lock=lock_meta(lock_path), tolerance=tol, all_match=all(c['match'] for c in comp.values() if c['match'] is not None), n_compared=sum(1 for c in comp.values() if c['match'] is not None), metrics=comp,
                note="the lock is pipeline.py's own leave-one-weekend-out validation over the completed 2026 weekends; the scorecard recomputes it with evaluation.forecast "
                     "(pool = the other completed 2026 weekends; no 2026 weekend is sealed); the prospective weekend has no race file and enters neither")


def rolling_origin_2026(quiet: bool = False) -> dict[str, Any]:
    """Chronological evaluation: round k forecast with factors from the completed rounds before k only (strict widening)."""
    F = SeasonForecaster(SEASON_DIRS[2026], 2026)
    order = [ev for ev in CALENDAR_2026 if ev in F.metas]
    series, rows_all = [], []
    for i, ev in enumerate(order):
        pool = [e for e in order[:i] if F.metas[e]['completed']]
        if not F.metas[ev]['completed']:
            series.append(dict(round=i + 1, event=ev, n_pool=len(pool), note='no scored race (live weekend or race unusable)'))
            continue
        fc = F.forecast(ev, pool, target_obs_in_widening=False)
        rows = score_forecast(fc, F.reference(ev))
        rows_all.extend(rows)
        d = pd.DataFrame(rows)
        series.append(dict(round=i + 1, event=ev, n_pool=len(pool), n_compounds=int(len(d)), n_issued=int(d['issued'].sum()) if len(d) else 0, n_no_forecast=int(d['prediction'].isna().sum()) if len(d) else 0,
                           mae_orb_v1=mae(d['err']) if len(d) else None, mae_naive=mae(d['err_naive']) if len(d) else None, band_coverage90=share(d['covered']) if len(d) else None,
                           bootstrap={k: weekend_mean_bootstrap(d, col, n_unit='compound-weekends') for k, col in [('mae_orb_v1', 'err'), ('mae_naive', 'err_naive'), ('band_coverage90', 'covered')]},
                           factors={c: dict(k=f.factor, applied=f.factor_applied, from_n=f.factor_from_n_weekends) for c, f in fc.compounds.items()}))
    rows = pd.DataFrame(rows_all)
    scored = [s for s in series if s.get('mae_orb_v1') is not None]
    out = dict(method='rolling origin: factors, fallback floor and widening from the completed rounds before round k only; the first rounds carry factor 1.0 and no fallback (empty pool)',
               calendar=list(order), series=series, pooled=_forecast_block(rows) if len(rows) else dict(n_weekends=0),
               pooled_from_round_4=_forecast_block(rows[rows['event'].isin([s['event'] for s in scored if s['n_pool'] >= 3])]) if len(rows) else dict(n_weekends=0))
    if not quiet:
        print(render_rolling(out))
    return out


def render_rolling(out: dict[str, Any]) -> str:
    L = ['Only earlier completed rounds enter each forecast. A single-round point estimate has no weekend bootstrap interval: n=1 weekend is insufficient.', '',
         '| round | event | earlier pool | issued / compounds | no forecast | MAE Orb v1 | MAE naive | coverage90 |',
         '|---|---|---|---|---|---|---|---|']
    for s in out['series']:
        if 'note' in s:
            L.append(f"| {s['round']} | {s['event']} | {s['n_pool']} | — | — | {s['note']} | | |")
            continue
        b = s.get('bootstrap', {})
        L.append(f"| {s['round']} | {s['event']} | {s['n_pool']} | {s['n_issued']} / {s['n_compounds']} | {s['n_no_forecast']} | {_ci(b.get('mae_orb_v1'))} | {_ci(b.get('mae_naive'))} | {_ci(b.get('band_coverage90'), pct=True)} |")
    for label, p in [('All scored rounds', out.get('pooled', {})), ('At least 3 earlier rounds in pool', out.get('pooled_from_round_4', {}))]:
        b = p.get('bootstrap', {})
        L += ['', f"{label}: MAE Orb v1 {_ci(b.get('mae_orb_v1'))}; naive {_ci(b.get('mae_naive'))}; coverage90 {_ci(b.get('band_coverage90'), pct=True)}."]
    return '\n'.join(L)


# ---------------------------------------------------------------- Live Predictor scorecard

METRICS_LIVE = (('next1_mae', 'next1_n'), ('next1_mae_prior_only', 'next1_n'), ('cum3_mae', 'cum3_n'), ('cum3_mae_prior_only', 'cum3_n'), ('cum5_mae', 'cum5_n'), ('cum5_mae_prior_only', 'cum5_n'),
                ('coverage90_next1', 'next1_n'), ('coverage90_next1_prior_only', 'next1_n'), ('coverage90_next3', 'next3_n'), ('cliff3_brier', 'cliff3_n'), ('cliff5_brier', 'cliff5_n'),
                ('cliff5_brier_climatology', 'cliff5_n'), ('recommendation_change_rate', 'lap_pairs'), ('aw_false_alert_episodes_per_stint', 'aw_false_stints'), ('aw_detection_rate', 'aw_true_stints'), ('aw_lead_laps_median', 'aw_true_stints'))


def live_scorecard(prefix_path: Path = PREFIX_EVAL, feedback_log: Path = FEEDBACK_LOG, live_out: Path = LIVE_OUT, quiet: bool = False) -> dict[str, Any]:
    if not prefix_path.exists():
        return dict(status='missing', note=f'{prefix_path} not found: run live/prefix_eval.py')
    pe = json.loads(prefix_path.read_text(encoding='utf-8'))
    races = pd.DataFrame([dict(race_id=f'2026_{ev}', event=ev, **m) for ev, m in pe['races'].items()])
    out: dict[str, Any] = dict(source=dict(path=str(prefix_path.relative_to(PROTO)), sha256=hashlib.sha256(prefix_path.read_bytes()).hexdigest(), generated_at=pe.get('generated_at'), estimator=pe.get('estimator'), model_version=pe.get('model_version'), feedback=pe.get('feedback')),
                               races=list(pe['races']), per_race=pe['races'], pooled_as_reported=pe.get('pooled'), pooled={}, note='all numbers from prefix evaluation where only data through lap k is revealed; re-pooled here with whole-weekend bootstrap: means weighted by eligible windows/stints, alert lead median pooled from detected true stints, climatology from pooled event counts')
    for metric, wcol in METRICS_LIVE:
        if metric not in races or wcol not in races:
            continue
        unit = 'stints' if wcol.startswith('aw_') else ('lap pairs' if wcol == 'lap_pairs' else 'scored windows')
        out['pooled'][metric] = weekend_mean_bootstrap(races, metric, wcol, n_unit=unit)
        out['pooled'][metric]['metric_label'] = metric
    # A mean of per-race medians is not the pooled median. Prefix artifacts retain
    # the underlying alert rows, so bootstrap those rows in whole-weekend clusters.
    alerts = pd.DataFrame([dict(race_id=f'2026_{ev}', **a) for ev, aa in pe.get('per_stint_alerts', {}).items() for a in aa])
    if not alerts.empty and {'truth', 'lead_laps'} <= set(alerts):
        leads = alerts[alerts['truth'].astype(bool)].dropna(subset=['lead_laps'])
        lead = weekend_bootstrap(leads, lambda d: float(d['lead_laps'].median()))
        lead.update(n=len(leads), n_unit='detected true stints', metric_label='Median alert lead (laps)')
        out['pooled']['aw_lead_laps_median'] = lead
    else:
        out['pooled']['aw_lead_laps_median'] = dict(estimate=None, ci90=None, n=0, n_weekends=0, n_rows=0,
            n_unit='detected true stints', method='unavailable: prefix artifact has no per-stint alerts', metric_label='Median alert lead (laps)')
    # Climatology must be fitted to the pooled scored windows on each resample.
    for horizon in (3, 5):
        count, events = f'cliff{horizon}_n', f'cliff{horizon}_events'
        if count in races and events in races:
            eligible = races[races[count] > 0]
            def climatology(d, c=count, e=events):
                rate = d[e].sum() / d[c].sum()
                return float(rate * (1 - rate))
            b = weekend_bootstrap(eligible, climatology)
            b.update(n=int(eligible[count].sum()), n_unit='scored windows', metric_label=f'cliff{horizon}_brier_climatology')
            out['pooled'][f'cliff{horizon}_brier_climatology'] = b
    out['source_consistency'] = {k: dict(scorecard=v['estimate'], source=pe.get('pooled', {}).get(k),
        match=(abs(v['estimate'] - pe['pooled'][k]) < 1e-10 if v['estimate'] is not None and pe.get('pooled', {}).get(k) is not None else v['estimate'] is pe.get('pooled', {}).get(k)))
        for k, v in out['pooled'].items() if k in pe.get('pooled', {})}
    out['driver_feedback_ablation'] = feedback_ablation(feedback_log, live_out, quiet=quiet)
    return out


ABLATION_DESIGN = ('for every (event, driver) pair with recorded feedback: replay the race prefix-by-prefix with feedback disabled (telemetry only) and enabled '
                   '(telemetry + structured feedback through live.feedback.DriverFeedbackAdapter); report next-lap MAE, 3- and 5-lap cumulative MAE, 90 % coverage, '
                   'accelerating-wear detection rate and lead, false alert episodes per stint and recommendation change rate for both arms')
ABLATION_METRICS = ('next1_mae', 'cum3_mae', 'cum5_mae', 'coverage90_next1', 'aw_detection_rate', 'aw_lead_laps_median', 'aw_false_alert_episodes_per_stint', 'recommendation_change_rate')


def feedback_events(feedback_log: Path = FEEDBACK_LOG, live_out: Path = LIVE_OUT) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every recorded driver-feedback event and where it came from: the UI log (rows carry event and driver) and Workstream 8's
    per-run logs out/live/<event>_<driver>/driver_feedback.json (contract 7.3 events consumed by a replay; event and driver
    from the directory name). Returns (events, sources), each source {path, exists, n_events}."""
    events: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    n = 0
    if feedback_log.exists():
        for line in feedback_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(e, dict) and e.get('event') and e.get('driver'):
                events.append(e); n += 1
    sources.append(dict(path=_rel(feedback_log), exists=feedback_log.exists(), n_events=n))
    for f in (sorted(live_out.glob('*_*/driver_feedback.json')) if live_out.exists() else []):
        ev, _, drv = f.parent.name.rpartition('_')
        try:
            rows = json.loads(f.read_text(encoding='utf-8'))
        except json.JSONDecodeError:
            rows = []
        rows = [dict(r, event=r.get('event') or ev, driver=r.get('driver') or drv) for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        events.extend(rows)
        sources.append(dict(path=_rel(f), exists=True, n_events=len(rows)))
    return events, sources


def feedback_ablation(feedback_log: Path = FEEDBACK_LOG, live_out: Path = LIVE_OUT, quiet: bool = False) -> dict[str, Any]:
    """Telemetry only vs telemetry plus structured feedback, on the (event, driver) pairs that carry recorded feedback.
    Runs only when at least one event exists in either source; otherwise states that plainly."""
    events, sources = feedback_events(feedback_log, live_out)
    src_txt = '; '.join(f"{s['path']} ({'missing' if not s['exists'] else str(s['n_events']) + ' events'})" for s in sources)
    if not events:
        return dict(status='not run', n_events=0, sources=sources, reason=f'no recorded driver-feedback event exists in any source: {src_txt}',
                    statement='Driver-feedback ablation NOT RUN: no driver-feedback event has been recorded (the UI log is empty and every replay run consumed 0 events). '
                              'It is a defined experiment, not a pre-written result; it runs from python -m evaluation.scorecards as soon as events exist.',
                    design=ABLATION_DESIGN)
    try:
        from live.session import LiveSession
        from live.prefix_eval import evaluate_driver, aggregate as live_aggregate
    except Exception as e:
        return dict(status='not run', n_events=len(events), sources=sources, reason=f'live package unavailable: {e}', design=ABLATION_DESIGN)
    pairs = sorted({(e['event'], e['driver']) for e in events})
    arms: dict[str, list] = dict(telemetry_only=[], with_feedback=[])
    done, skipped = [], []
    for ev, drv in pairs:
        evts = [e for e in events if e['event'] == ev and e['driver'] == drv]
        try:
            arms['telemetry_only'].append(evaluate_driver(LiveSession.open(ev, drv, feedback_events=evts, feedback_enabled=False)))
            arms['with_feedback'].append(evaluate_driver(LiveSession.open(ev, drv, feedback_events=evts, feedback_enabled=True)))
            done.append(dict(event=ev, driver=drv, n_events=len(evts)))
        except Exception as e:
            skipped.append(dict(event=ev, driver=drv, reason=str(e)))
            if not quiet:
                print(f'feedback ablation {ev} {drv} skipped: {e}')
    if not done:
        return dict(status='not run', n_events=len(events), sources=sources, reason='no (event, driver) pair with recorded feedback could be replayed', skipped=skipped, design=ABLATION_DESIGN)
    t, w = live_aggregate(arms['telemetry_only']), live_aggregate(arms['with_feedback'])
    comparison = {k: dict(telemetry_only=t.get(k), with_feedback=w.get(k), difference=(w[k] - t[k]) if isinstance(t.get(k), (int, float)) and isinstance(w.get(k), (int, float)) else None) for k in ABLATION_METRICS}
    return dict(status='run', pairs=done, skipped=skipped, n_events=len(events), sources=sources, design=ABLATION_DESIGN, telemetry_only=t, with_feedback=w, comparison=comparison,
                note='model-implied replay on recorded feedback; the pairs are the ones that carry feedback, not a random sample')


# ---------------------------------------------------------------- assembly

def build(seasons: Iterable[int] = (2026, 2025, 2024, 2023), out_dir: Path = OUT_DIR, quiet: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    from evaluation.holdout.evaluator import sealed_race_ids
    sealed = sealed_race_ids()
    sha = git_sha()
    dev = development_pool(seasons, sealed, quiet=quiet)
    rolling = rolling_origin_2026(quiet=quiet)
    sealed_agg = None
    p = out_dir / 'holdout_aggregate.json'
    if p.exists():
        h = json.loads(p.read_text(encoding='utf-8'))
        quotable = h.get('quotable') is True                      # an aggregate file without the flag (pre 12 Sep evening) is treated as a dry run
        sealed_agg = dict(source_sha256=hashlib.sha256(p.read_bytes()).hexdigest(), generated_at=h.get('generated_at'), git_sha=h.get('git_sha'), dry_run_before_freeze=bool(h.get('dry_run_before_freeze', not quotable)), quotable=quotable,
                          reveal=h.get('reveal'), post_holdout_tuning=h.get('post_holdout_tuning'), n_weekends=h.get('n_weekends'), aggregate=h.get('aggregate') if quotable else None,
                          note=('aggregate over the sealed weekends only; per-race results stay in holdout_per_race.json under the freeze' if quotable else
                                'DRY RUN BEFORE FREEZE: holdout_aggregate.json was produced without a valid evaluation/holdout/freeze.json (quotable: false). Its numbers are withheld '
                                'from the scorecard and must not be quoted anywhere; after the lead writes freeze.json run python -m evaluation.holdout.evaluator then python -m evaluation.scorecards'))
    lk = lock_meta()
    ghost = dict(scorecard='Ghost Strategy', generated_at=now_iso(), git_sha=sha, data_cutoff=DATA_CUTOFF_2026 + f"; out/lock.json generated {lk.get('generated_at')} (prospective: {', '.join(lk.get('prospective_events') or []) or 'none'}); seasons 2023 to 2025 complete",
                 units=UNITS, seasons=list(seasons), sealed_excluded=sealed, lock=lk,
                 wording=dict(reference='race-derived pace-loss reference', regret=REGRET_LABEL, counterfactual='model-implied', untouched='reserved for the sealed holdout and the prospective race'),
                 development_pool=dev, sealed_holdout=sealed_agg, rolling_origin_2026=rolling)
    live = dict(scorecard='Live Predictor', generated_at=now_iso(), git_sha=sha, data_cutoff=DATA_CUTOFF_2026, units=dict(mae='s', coverage='share inside the 90 % band', brier='0 to 1', lead='laps', rate='per stint / per lap pair'),
                **live_scorecard(quiet=quiet))
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / 'ghost_scorecard.json', ghost)
    write_json(out_dir / 'live_scorecard.json', live)
    (out_dir / 'SCORECARDS.md').write_text(render_md(ghost, live), encoding='utf-8')
    if not quiet:
        print(f"wrote {out_dir / 'ghost_scorecard.json'}, {out_dir / 'live_scorecard.json'}, {out_dir / 'SCORECARDS.md'}")
    return ghost, live


def _ci(b: Optional[dict[str, Any]], nd: int = 4, pct: bool = False) -> str:
    if not b:
        return 'unavailable (no source interval)'
    n = b.get('n', b.get('n_rows', 0)); w = b.get('n_weekends', 0)
    suffix = f"; n={n} {b.get('n_unit', 'rows')}, {w} weekends"
    if b.get('estimate') is None:
        return 'undefined; 90% CI unavailable' + suffix
    fmt = (lambda v: f'{v:.1%}') if pct else (lambda v: f'{v:.{nd}f}')
    ci = b.get('ci90')
    return fmt(b['estimate']) + (f" [90% CI {fmt(ci[0])}, {fmt(ci[1])}]" if ci else '; 90% CI unavailable (insufficient weekends or undefined statistic)') + suffix


def render_md(ghost: dict[str, Any], live: dict[str, Any]) -> str:
    d = ghost['development_pool']; f = d['forecast']
    L = [f"# Orb v1 scorecards ({ghost['generated_at']}, git {ghost['git_sha']})", '',
         'Two scorecards, never merged. Every reported performance estimate below carries its eligible n and a 90% percentile bootstrap band from whole-weekend resampling (2000 draws; never row resampling). Counts and fixed gate settings are metadata, not estimates. Missing bands are explicit.', '',
         '## Ghost Strategy scorecard', '', f"Development pool: {f.get('n_weekends', 0)} weekends; {f.get('n_compound_weekends', 0)} compound-weekends; sealed weekends excluded from every pool.", '']
    def forecast_table(title, fc):
        L.extend([title, '', '| metric | estimate, 90% interval and support |', '|---|---|'])
        for k, label in [('mae_orb_v1', 'Orb v1 MAE (s/lap per lap)'), ('mae_naive', 'Naive MAE (s/lap per lap)'),
                         ('band_coverage90', '90% predictive-band coverage'), ('share_issued', 'Share issued'),
                         ('mae_orb_v1_issued', 'Issued MAE'), ('mae_orb_v1_fallback', 'Fallback MAE'),
                         ('calibration_r', 'Calibration correlation'), ('win_share', 'Share beating naive')]:
            L.append(f"| {label} | {_ci(fc.get('bootstrap', {}).get(k), pct=k in ('band_coverage90','share_issued','win_share'))} |")
        L.append('')
    forecast_table('### Development aggregate', f)
    L += ['### Hidden-stop response', '', '| metric | Orb v1 | naive |', '|---|---|---|']
    hb = d.get('hidden_stop', {}).get('bootstrap', {})
    for h in ('next1', 'cum3', 'cum5'):
        L.append(f"| {h} MAE (s) | {_ci(hb.get(h+'_mae'),3)} | {_ci(hb.get(h+'_mae_naive'),3)} |")
        L.append(f"| {h} coverage90 | {_ci(hb.get(h+'_coverage90'),pct=True)} | |")
    L += ['', f"### Strategy regret ({REGRET_LABEL})", '', '| plan | mean regret (s) | median regret (s) | within 5 s |', '|---|---|---|---|']
    for name, p in d.get('regret', {}).get('plans', {}).items():
        rb = p.get('bootstrap', {})
        L.append(f"| {name} | {_ci(p.get('ci90_mean'),1)} | {_ci(p.get('ci90_median'),1)} | {_ci(rb.get('share_within_5s'),pct=True)} |")
    for store in ('by_circuit_class', 'by_weather_regime'):
        for val, cell in d.get(store, {}).items():
            forecast_table(f"### {store[3:]}: {val}", cell['forecast'])
    for season, cell in d.get('by_season', {}).items():
        forecast_table(f"### Season {season} (leave-one-weekend-out inside season)", cell['forecast'])
    lc = d.get('lock_consistency_2026', {})
    L += ['### Lock consistency', '', f"{lc.get('n_compared', 0)} values compared with out/lock.json; all_match={lc.get('all_match')}. Counts exact; floats within {lc.get('tolerance')}. The 2026 performance estimates and intervals are in the season table above.", '']
    s = ghost.get('sealed_holdout')
    L += ['### sealed holdout, aggregate only', '']
    if s and s.get('quotable') is True and s.get('aggregate'):
        sf = s['aggregate']['forecast']; sb = sf.get('bootstrap', {})
        L += [f"sealed holdout, aggregate only: {s['n_weekends']} weekends / {sf['n_compound_weekends']} compound-weekends.", '',
              f"Orb v1 MAE {_ci(sb.get('mae_orb_v1'))}; naive MAE {_ci(sb.get('mae_naive'))} s/lap.",
              f"Coverage {_ci(sb.get('band_coverage90'), pct=True)}. Frozen post-freeze aggregate copied verbatim; no per-race data read.", '']
    else:
        L += ['Not quotable: numbers withheld until a valid post-freeze aggregate exists.', '']
    L += ['### Rolling origin, 2026', '', render_rolling(ghost['rolling_origin_2026']), '', '## Live Predictor scorecard', '']
    L += [f"Source: {live.get('source', {}).get('path')}; frozen prefix evaluation; source point-estimate agreement: {all(c['match'] for c in live.get('source_consistency', {}).values())}.",
          'Only data through lap k enters the predictor; realised future outcomes are scoring targets only. Alert lead is the median over detected true stints, recomputed from source per-stint alerts. Climatology Brier uses the pooled event rate on each whole-weekend resample.', '',
          '| metric | estimate, 90% interval and support |', '|---|---|']
    for k, v in live.get('pooled', {}).items():
        L.append(f"| {v.get('metric_label', k)} | {_ci(v,3)} |")
    fa = live.get('driver_feedback_ablation', {})
    L += ['', f"Driver-feedback ablation: {fa.get('status')}; {fa.get('statement', fa.get('reason', fa.get('note', '')))}", '',
          'Risk-coverage threshold sweep: see risk_coverage.json and risk_coverage.csv. Each table row includes eligible n and whole-weekend 90% bands for coverage and every MAE. The production gate is frozen; the development sweep is diagnostic and does not select a new gate.']
    return '\n'.join(L) + '\n'


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seasons', default='2026,2025,2024,2023')
    ap.add_argument('--out', type=Path, default=OUT_DIR)
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    build([int(s) for s in a.seasons.split(',') if s], a.out, a.quiet)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
