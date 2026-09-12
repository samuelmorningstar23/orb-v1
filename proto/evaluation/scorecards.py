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
    driver-feedback ablation: run only when app_v2/state/feedback_events.jsonl carries events (defined experiment, not
    a pre-written result).
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
                r.update(circuit_class=circuit_class(ev), weather_regime=wx)
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
    return out


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


def live_scorecard(prefix_path: Path = PREFIX_EVAL, feedback_log: Path = FEEDBACK_LOG, quiet: bool = False) -> dict[str, Any]:
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
    out['driver_feedback_ablation'] = feedback_ablation(feedback_log, quiet=quiet)
    return out


def feedback_ablation(feedback_log: Path = FEEDBACK_LOG, quiet: bool = False) -> dict[str, Any]:
    """Telemetry only vs telemetry plus structured feedback, on the (event, driver) pairs that carry recorded feedback."""
    events = []
    if feedback_log.exists():
        for line in feedback_log.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    if not events:
        return dict(status='not run', reason=f'no recorded driver-feedback events in {feedback_log.relative_to(PROTO) if feedback_log.exists() else feedback_log} (defined experiment, not a pre-written result)',
                    design='for every (event, driver) with recorded feedback: replay with feedback disabled and enabled; report next-lap MAE, 3- and 5-lap cumulative MAE, coverage, accelerating-wear detection lead and false alerts per stint for both arms')
    try:
        from live.session import LiveSession
        from live.prefix_eval import evaluate_driver, aggregate as live_aggregate
    except Exception as e:
        return dict(status='not run', reason=f'live package unavailable: {e}')
    pairs = sorted({(e.get('event'), e.get('driver')) for e in events if e.get('event') and e.get('driver')})
    arms: dict[str, list] = dict(telemetry_only=[], with_feedback=[])
    done = []
    for ev, drv in pairs:
        try:
            arms['telemetry_only'].append(evaluate_driver(LiveSession.open(ev, drv, feedback_enabled=False)))
            arms['with_feedback'].append(evaluate_driver(LiveSession.open(ev, drv, feedback_enabled=True)))
            done.append(dict(event=ev, driver=drv))
        except Exception as e:
            if not quiet:
                print(f'feedback ablation {ev} {drv} skipped: {e}')
    if not done:
        return dict(status='not run', reason='no (event, driver) pair with recorded feedback could be replayed')
    return dict(status='run', pairs=done, n_events=len(events), telemetry_only=live_aggregate(arms['telemetry_only']), with_feedback=live_aggregate(arms['with_feedback']))


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
        sealed_agg = dict(generated_at=h.get('generated_at'), git_sha=h.get('git_sha'), reveal=h.get('reveal'), post_holdout_tuning=h.get('post_holdout_tuning'), n_weekends=h.get('n_weekends'), aggregate=h.get('aggregate'),
                          note='aggregate over the sealed weekends only; per-race results stay sealed until freeze.json')
    ghost = dict(scorecard='Ghost Strategy', generated_at=now_iso(), git_sha=sha, data_cutoff=DATA_CUTOFF_2026 + '; seasons 2023 to 2025 complete', units=UNITS, seasons=list(seasons), sealed_excluded=sealed,
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
    s = ghost.get('sealed_holdout')
    L += ['', '### Sealed holdout (aggregate only)', '']
    if s and s.get('aggregate'):
        a = s['aggregate']; sf = a.get('forecast', {}); sb = sf.get('bootstrap', {}); sh = a.get('hidden_stop', {}).get('pooled', {}); sr = a.get('regret', {}).get('plans', {})
        L += [f"{s.get('n_weekends')} sealed weekends, {sf.get('n_compound_weekends', 0)} compound-weekends; per-race results {'revealed' if s.get('reveal', {}).get('per_race_written') else 'sealed'} ({s.get('reveal', {}).get('reason')}); post_holdout_tuning={s.get('post_holdout_tuning')}.", '',
              '| metric | Orb v1 | naive |', '|---|---|---|', f"| pre-race degradation MAE | {_ci(sb.get('mae_orb_v1'))} | {_ci(sb.get('mae_naive'))} |", f"| 90 % band coverage | {_ci(sb.get('band_coverage90'), pct=True)} | |"]
        if sh.get('n_cases'):
            L.append(f"| hidden-stop next-lap / 3-lap / 5-lap MAE ({sh['n_cases']} stops) | {sh['next1_mae']:.3f} / {sh['cum3_mae']:.3f} / {sh['cum5_mae']:.3f} | {sh['next1_mae_naive']:.3f} / {sh['cum3_mae_naive']:.3f} / {sh['cum5_mae_naive']:.3f} |")
        for name, p in sr.items():
            L.append(f"| regret {name} | " + (f"n={p['n']}: median {p['median']:.1f} s, mean {p['mean']:.1f} s, within 5 s {p['share_within_5s']:.0%}" if p.get('n') and not p.get('suppressed') else f"n={p.get('n', 0)} suppressed") + ' | |')
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
        L += ['', f"Driver-feedback ablation: {fa.get('status')} ({fa.get('reason', '')})" if fa.get('status') != 'run' else f"Driver-feedback ablation run on {len(fa.get('pairs', []))} pairs: next-lap MAE telemetry only {fa['telemetry_only'].get('next1_mae')}, with feedback {fa['with_feedback'].get('next1_mae')}"]
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
