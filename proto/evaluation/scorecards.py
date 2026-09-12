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
Every interval is a weekend-grouped bootstrap (evaluation.common.weekend_bootstrap); each block carries generated_at,
git_sha, data_cutoff and units.

CLI:  python -m evaluation.scorecards [--seasons 2026,2025,2024,2023] [--out out/validation]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from evaluation import PROTO, OUT_DIR, SEASON_DIRS, COMPS, CALENDAR_2026, circuit_class, weather_regime, git_sha, now_iso
from evaluation.common import mae, share, weekend_bootstrap, paired_probability, write_json, finite
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
        out['bootstrap'] = dict(mae_orb_v1=weekend_bootstrap(rows, lambda d: mae(d['err'])), mae_naive=weekend_bootstrap(rows, lambda d: mae(d['err_naive'])),
                                band_coverage90=weekend_bootstrap(rows, lambda d: share(d['covered'])), p_orb_beats_naive=paired_probability(rows, 'err', 'err_naive'))
    return out


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
            cell = dict(forecast=_forecast_block(d, bootstrap=False))
            if len(hs):
                cell['hidden_stop'] = hs_aggregate([c for c in hs_cases if c.get(key) == val], bootstrap=False)['pooled']
            cell['regret'] = regret_aggregate([r for r in regret_rows if r.get(key) == val], bootstrap=False)
            out[store][str(val)] = cell
    if len(hs):
        for val, d in hs.groupby('driver_support'):
            out['by_driver_support'][str(val)] = dict(hidden_stop=hs_aggregate([c for c in hs_cases if c.get('driver_support') == val], bootstrap=False)['pooled'],
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
    return dict(path=_rel(lock_path), generated_at=lock.get('generated_at'), validation_n_weekends=v.get('n_weekends'), validation_n_compound_weekends=v.get('n_compound_weekends'),
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
    L = ['| round | event | pool | compounds | issued | no forecast | MAE Orb v1 | MAE naive | cov90 |', '|---|---|---|---|---|---|---|---|---|']
    f = lambda v: '—' if v is None else f'{v:.4f}'
    g = lambda v: '—' if v is None else f'{v:.2f}'
    for s in out['series']:
        if 'note' in s:
            L.append(f"| {s['round']} | {s['event']} | {s['n_pool']} | — | — | — | {s['note']} | | |"); continue
        L.append(f"| {s['round']} | {s['event']} | {s['n_pool']} | {s['n_compounds']} | {s['n_issued']} | {s['n_no_forecast']} | {f(s['mae_orb_v1'])} | {f(s['mae_naive'])} | {g(s['band_coverage90'])} |")
    p = out.get('pooled', {}); q = out.get('pooled_from_round_4', {})
    if p.get('n_weekends'):
        L.append(f"pooled over {p['n_weekends']} rounds: MAE Orb v1 {f(p['mae']['orb_v1'])} vs naive {f(p['mae']['naive'])}; from a pool of >= 3 rounds ({q.get('n_weekends', 0)} rounds): {f(q.get('mae', {}).get('orb_v1'))} vs {f(q.get('mae', {}).get('naive'))}")
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
    out: dict[str, Any] = dict(source=dict(path=str(prefix_path.relative_to(PROTO)), generated_at=pe.get('generated_at'), estimator=pe.get('estimator'), model_version=pe.get('model_version'), feedback=pe.get('feedback')),
                               races=list(pe['races']), per_race=pe['races'], pooled_as_reported=pe.get('pooled'), pooled={}, note='all numbers from prefix evaluation where only data through lap k is revealed; re-pooled here with a race-grouped, laps-weighted bootstrap')
    for metric, wcol in METRICS_LIVE:
        if metric not in races or wcol not in races:
            continue
        def stat(d: pd.DataFrame, m=metric, w=wcol) -> Optional[float]:
            x = d.dropna(subset=[m, w])
            x = x[x[w] > 0]
            return float(np.average(x[m], weights=x[w])) if len(x) else None
        out['pooled'][metric] = weekend_bootstrap(races, stat)
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
        sealed_agg = dict(generated_at=h.get('generated_at'), git_sha=h.get('git_sha'), dry_run_before_freeze=bool(h.get('dry_run_before_freeze', not quotable)), quotable=quotable,
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
    if not b or b.get('estimate') is None:
        return '—'
    e = b['estimate']; ci = b.get('ci90')
    fmt = (lambda v: f'{v:.0%}') if pct else (lambda v: f'{v:.{nd}f}')
    return fmt(e) + (f' [{fmt(ci[0])}, {fmt(ci[1])}]' if ci else '')


def render_md(ghost: dict[str, Any], live: dict[str, Any]) -> str:
    d = ghost['development_pool']; f = d['forecast']; b = f.get('bootstrap', {})
    L = [f"# Orb v1 scorecards ({ghost['generated_at']}, git {ghost['git_sha']})", '', 'Two scorecards, never merged (roadmap v5 9.0.1). Intervals: weekend-grouped bootstrap, 90 %.', '',
         '## Ghost Strategy scorecard', '', f"Development pool: {f.get('n_weekends', 0)} weekends, {f.get('n_compound_weekends', 0)} compound-weekends ({f.get('n_issued', 0)} issued, {f.get('n_withheld', 0)} withheld); sealed weekends excluded from every pool.", '',
         '| metric | Orb v1 | naive / baseline |', '|---|---|---|',
         f"| pre-race degradation MAE (s/lap per lap) | {_ci(b.get('mae_orb_v1'))} | {_ci(b.get('mae_naive'))} |",
         f"| 90 % band coverage | {_ci(b.get('band_coverage90'), pct=True)} | nominal 90 % |",
         f"| P(Orb v1 beats naive), weekend bootstrap | {b.get('p_orb_beats_naive', {}).get('p_bootstrap', '—')} | |",
         f"| abstention: share issued | {f.get('abstention', {}).get('share_issued', float('nan')):.2f} | MAE issued {f.get('mae', {}).get('orb_v1_issued', float('nan')):.4f}, fallback {f.get('mae', {}).get('orb_v1_fallback', float('nan')):.4f} |"]
    h = d['hidden_stop']; hp = h.get('pooled', {}); hb = h.get('bootstrap', {})
    if hp.get('n_cases'):
        L += [f"| hidden-stop next-lap MAE (s), {hp['n_cases']} stops | {_ci(hb.get('next1_mae'), 3)} | naive {_ci(hb.get('next1_mae_naive'), 3)} |",
              f"| hidden-stop 3-lap cumulative MAE (s) | {_ci(hb.get('cum3_mae'), 3)} | naive {_ci(hb.get('cum3_mae_naive'), 3)} |",
              f"| hidden-stop 5-lap cumulative MAE (s) | {_ci(hb.get('cum5_mae'), 3)} | naive {_ci(hb.get('cum5_mae_naive'), 3)} |",
              f"| hidden-stop 90 % coverage next / +3 / +5 | {_ci(hb.get('next1_coverage90'), pct=True)} / {_ci(hb.get('cum3_coverage90'), pct=True)} / {_ci(hb.get('cum5_coverage90'), pct=True)} | nominal 90 % |"]
    r = d['regret']
    for name in ('orb', 'naive', 'observed', 'default'):
        p = r.get('plans', {}).get(name, {})
        if p.get('n'):
            L.append(f"| strategy regret, {name} plan (s; {REGRET_LABEL}), n={p['n']} | median {p['median']:.1f}, mean {_ci(p.get('ci90_mean'), 1)} | p90 {p['p90']:.1f}; within 2/5/10 s {p['share_within_2s']:.0%}/{p['share_within_5s']:.0%}/{p['share_within_10s']:.0%} |")
    for k in ('p_orb_beats_naive', 'p_orb_beats_observed'):
        v = r.get(k)
        if v and v.get('share_rows') is not None:
            L.append(f"| {k.replace('_', ' ')} | share of weekends {v['share_rows']:.2f} | bootstrap P {v['p_bootstrap']} (n={v['n_weekends']}) |")
    L += ['', '### By cell (development pool)', '', '| cell | weekends | pre-race MAE Orb v1 | naive | cov90 | hidden-stop next-lap MAE | naive | regret Orb v1 median (n) |', '|---|---|---|---|---|---|---|---|']
    for store in ('by_circuit_class', 'by_weather_regime'):
        for val, cell in d.get(store, {}).items():
            cf = cell['forecast']; ch = cell.get('hidden_stop', {}); cr = cell.get('regret', {}).get('plans', {}).get('orb', {})
            L.append(f"| {store[3:]}={val} | {cf.get('n_weekends', 0)} | {cf.get('mae', {}).get('orb_v1', float('nan')):.4f} | {cf.get('mae', {}).get('naive', float('nan')):.4f} | {(cf.get('band_coverage90', {}).get('all') or float('nan')):.0%} | "
                     f"{(ch.get('next1_mae') if ch.get('next1_mae') is not None else float('nan')):.3f} | {(ch.get('next1_mae_naive') if ch.get('next1_mae_naive') is not None else float('nan')):.3f} | {(cr.get('median') if cr.get('n') else float('nan')):.1f} ({cr.get('n', 0)}) |")
    for val, cell in d.get('by_driver_support', {}).items():
        ch = cell['hidden_stop']
        L.append(f"| driver_support={val} | — | — | — | — | {ch.get('next1_mae', float('nan')):.3f} | {ch.get('next1_mae_naive', float('nan')):.3f} | — |")
    bs = d.get('by_season', {})
    if bs:
        L += ['', '### By season (development pool, leave-one-weekend-out inside the season)', '', '| season | weekends | compound-weekends (issued / withheld) | MAE Orb v1 | MAE naive | cov90 | wins over naive | calibration r |', '|---|---|---|---|---|---|---|---|']
        for season, cell in bs.items():
            cf = cell['forecast']; cb = cf.get('bootstrap', {}); cr = cf.get('calibration', {}).get('r')
            L.append(f"| {season} | {cf.get('n_weekends', 0)} | {cf.get('n_compound_weekends', 0)} ({cf.get('n_issued', 0)} / {cf.get('n_withheld', 0)}) | {_ci(cb.get('mae_orb_v1'))} | {_ci(cb.get('mae_naive'))} | "
                     f"{_ci(cb.get('band_coverage90'), pct=True)} | {cf.get('wins_orb_over_naive')} of {cf.get('n_compound_weekends')} | {'—' if cr is None else f'{cr:.2f}'} |")
    lc = d.get('lock_consistency_2026')
    if lc and lc.get('metrics'):
        L += ['', f"### Lock consistency: 2026 leave-one-weekend-out vs {lc['lock'].get('path')} (generated {lc['lock'].get('generated_at')})", '', '| metric | scorecard | lock | match |', '|---|---|---|---|']
        fmt = lambda v: '—' if v is None else (f'{v}' if isinstance(v, int) else f'{v:.4f}')
        for k, c in lc['metrics'].items():
            L.append(f"| {k} | {fmt(c['scorecard'])} | {fmt(c['lock'])} | {'yes' if c['match'] else ('n/a' if c['match'] is None else 'NO')} |")
        L += ['', f"All {lc['n_compared']} compared values match: {lc['all_match']} (floats within {lc['tolerance']}, counts exact). {lc['note']}."]
    s = ghost.get('sealed_holdout')
    L += ['', '### Sealed holdout (aggregate only)', '']
    if s and s.get('quotable') and s.get('aggregate'):
        a = s['aggregate']; sf = a.get('forecast', {}); sb = sf.get('bootstrap', {}); sh = a.get('hidden_stop', {}).get('pooled', {}); sr = a.get('regret', {}).get('plans', {})
        L += [f"{s.get('n_weekends')} sealed weekends, {sf.get('n_compound_weekends', 0)} compound-weekends; per-race results {'revealed' if s.get('reveal', {}).get('per_race_written') else 'sealed'} ({s.get('reveal', {}).get('reason')}); post_holdout_tuning={s.get('post_holdout_tuning')}.", '',
              '| metric | Orb v1 | naive |', '|---|---|---|', f"| pre-race degradation MAE | {_ci(sb.get('mae_orb_v1'))} | {_ci(sb.get('mae_naive'))} |", f"| 90 % band coverage | {_ci(sb.get('band_coverage90'), pct=True)} | |"]
        if sh.get('n_cases'):
            L.append(f"| hidden-stop next-lap / 3-lap / 5-lap MAE ({sh['n_cases']} stops) | {sh['next1_mae']:.3f} / {sh['cum3_mae']:.3f} / {sh['cum5_mae']:.3f} | {sh['next1_mae_naive']:.3f} / {sh['cum3_mae_naive']:.3f} / {sh['cum5_mae_naive']:.3f} |")
        for name, p in sr.items():
            L.append(f"| regret {name} | " + (f"n={p['n']}: median {p['median']:.1f} s, mean {p['mean']:.1f} s, within 5 s {p['share_within_5s']:.0%}" if p.get('n') and not p.get('suppressed') else f"n={p.get('n', 0)} suppressed") + ' | |')
    elif s:
        L.append(f"**DRY RUN BEFORE FREEZE, numbers withheld.** holdout_aggregate.json (generated {s.get('generated_at')}, git {s.get('git_sha')}, {s.get('n_weekends')} sealed weekends) was produced without a valid "
                 f"evaluation/holdout/freeze.json (quotable: false); per-race results {'revealed' if (s.get('reveal') or {}).get('per_race_written') else 'sealed'}. Nothing from a pre-freeze run is quoted anywhere. "
                 "After the lead writes freeze.json (C4): `python -m evaluation.holdout.evaluator`, then `python -m evaluation.scorecards`.")
    else:
        L.append('holdout_aggregate.json not found: run evaluation/holdout/evaluator.py')
    ro = ghost.get('rolling_origin_2026', {})
    L += ['', '### Rolling origin, 2026', '', render_rolling(ro), '', '## Live Predictor scorecard', '']
    if live.get('pooled'):
        L += [f"Source: {live['source']['path']} ({live['source']['estimator']}, {live['source']['model_version']}, generated {live['source']['generated_at']}); races {', '.join(live['races'])}; race-grouped laps-weighted bootstrap.", '',
              '| metric | estimator | prior-only baseline |', '|---|---|---|']
        P = live['pooled']
        L += [f"| next-lap MAE (s) | {_ci(P.get('next1_mae'), 3)} | {_ci(P.get('next1_mae_prior_only'), 3)} |", f"| 3-lap cumulative MAE (s) | {_ci(P.get('cum3_mae'), 3)} | {_ci(P.get('cum3_mae_prior_only'), 3)} |",
              f"| 5-lap cumulative MAE (s) | {_ci(P.get('cum5_mae'), 3)} | {_ci(P.get('cum5_mae_prior_only'), 3)} |", f"| 90 % coverage next lap | {_ci(P.get('coverage90_next1'), pct=True)} | {_ci(P.get('coverage90_next1_prior_only'), pct=True)} |",
              f"| cliff-5 Brier (model-implied rate proxy) | {_ci(P.get('cliff5_brier'), 3)} | climatology {_ci(P.get('cliff5_brier_climatology'), 3)} |", f"| accelerating-wear detection rate / lead (laps) | {_ci(P.get('aw_detection_rate'), pct=True)} / {_ci(P.get('aw_lead_laps_median'), 1)} | |",
              f"| false alert episodes per stint | {_ci(P.get('aw_false_alert_episodes_per_stint'), 2)} | |", f"| recommendation change rate | {_ci(P.get('recommendation_change_rate'), pct=True)} | |"]
        fa = live.get('driver_feedback_ablation', {})
        if fa.get('status') == 'run':
            L += ['', f"### Driver-feedback ablation ({len(fa.get('pairs', []))} (event, driver) pairs, {fa.get('n_events')} recorded events)", '', '| metric | telemetry only | with feedback | difference |', '|---|---|---|---|']
            g = lambda v: '—' if v is None else f'{v:.3f}'
            for k, c in fa.get('comparison', {}).items():
                L.append(f"| {k} | {g(c['telemetry_only'])} | {g(c['with_feedback'])} | {g(c['difference'])} |")
            L += ['', f"Pairs: {', '.join(f'{p['event']} {p['driver']} ({p['n_events']} events)' for p in fa.get('pairs', []))}. {fa.get('note', '')}"]
        else:
            L += ['', f"**{fa.get('statement') or ('Driver-feedback ablation: ' + str(fa.get('status')) + ' (' + str(fa.get('reason', '')) + ')')}**", '',
                  'Sources checked: ' + '; '.join(f"`{x['path']}` ({'missing' if not x['exists'] else str(x['n_events']) + ' events'})" for x in fa.get('sources', [])) + '.',
                  '', f"Design (runs automatically once events exist): {fa.get('design', ABLATION_DESIGN)}."]
    else:
        L.append(f"prefix evaluation not available: {live.get('note')}")
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
