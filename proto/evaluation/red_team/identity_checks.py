"""Independent identity checks on Workstream 2's counterfactual core and Workstream 8's live estimator, public API only.

For Monza and Austria 2026, two drivers each (NOR, VER):
    identity            replay the actual plan with the standardised pit event disabled -> every sampled per-lap delta is 0
                        (both modes); with it enabled the cumulative delta equals engine.stop_replacement_delta_s exactly
    same compound       intervene at the driver's own stop lap to the compound actually fitted -> zero delta (both modes)
    zero degradation    every reference slope forced to 0 -> the tyre term is exactly the compound-offset difference on each
                        unfrozen lap after the intervention and the pit term is the standardised event (recomputed here from
                        the sampled parameter means), nothing else
    time accounting     sum(lap_delta) == cumulative_delta[-1] == engine.elapsed_delta_mean_s; cf_lap_time - actual == lap_delta;
                        tyre + pit == lap_delta; the summary quantiles are those of the sampled totals; q10 <= median <= q90
    conservation        a scenario adding one stop adds exactly one pit_entry, stationary, pit_exit, age_reset and warm_up
    on-disk reproduce   every scenario under out/counterfactual/ (race-context) and out/counterfactual/pre_race/
                        (Scenario Explorer, curve_source='pre_race_forecast') recompiles to the same summary numbers (same seed)
    provider A          every lock curve (29 validation rows + Madrid) is reproduced exactly by ProviderA.predict_curve
Pit-loss derivation: the 2026 season pool is recomputed from the feature files with a fresh cache and the transit loss, its sd,
the in-lap share and the pool counts are compared with what out/counterfactual/*/summary.json and counterfactual/README.md report.
Batch equals replay: Workstream 8's sequential filter is compared with the joint-Gaussian batch posterior on every lap of one race
for several drivers (claim: identical to 1e-9).

    python evaluation/red_team/identity_checks.py [--events Monza,Austria] [--drivers NOR,VER] [--out PATH]
Exit 0 when every check passes, 1 otherwise. Report: evaluation/red_team/identity_checks_report.json
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Optional

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))
from evaluation.red_team import PROTO, RT_DIR, LOCK_V1, now_iso, read_json, write_json  # noqa: E402

REPORT_PATH = RT_DIR / 'identity_checks_report.json'
TOL = 1e-9


def _check(name: str, ok: bool, **detail) -> dict:
    return dict(check=name, status='PASS' if ok else 'FAIL', **detail)


# ---------------------------------------------------------------- counterfactual identities
def _stop(dl, non_free: bool):
    for i, s in enumerate(dl.stops):
        if (not s.free) if non_free else True:
            return i, s
    return None, None


def counterfactual_checks(event: str, driver: str, engine) -> list[dict]:
    from counterfactual.engine import ScenarioSpec, P_TRANSIT, P_STAT
    out = []
    dl = engine.race(event).driver(driver)
    if not dl.stops:
        return [_check('identity', False, event=event, driver=driver, note='driver made no stop; identity replay needs a stop')]
    i_any, s_any = _stop(dl, non_free=False)
    i_nf, s_nf = _stop(dl, non_free=True)
    # identity, standardised event disabled, both modes
    for mode in ('fixed_context', 'tyre_only'):
        spec = ScenarioSpec(event, driver, s_any.in_lap, s_any.to_compound, mode=mode, standardised_pit_event=False, replace_stop=i_any + 1, set_age=dl.stints[i_any + 1].start_age)
        r = engine.compile(spec)
        worst = float(np.abs(r.deltas).max())
        out.append(_check(f'identity actual plan, std event off, {mode}', r.scenario['counterfactual_plan'] == r.scenario['actual_plan'] and worst < TOL and r.scenario['validation']['identity_test'] == 'pass',
                          event=event, driver=driver, max_abs_sampled_delta=worst, cumulative=r.cumulative_delta_mean, plans_equal=r.scenario['counterfactual_plan'] == r.scenario['actual_plan']))
    # identity with the standardised event: cumulative == stop replacement, tyre term zero
    if s_nf is not None:
        spec = ScenarioSpec(event, driver, s_nf.in_lap, s_nf.to_compound, mode='fixed_context', standardised_pit_event=True, replace_stop=i_nf + 1, set_age=dl.stints[i_nf + 1].start_age)
        r = engine.compile(spec)
        rep = r.engine['stop_replacement_delta_s']
        tyre_zero = float(r.table['delta_tyre_mean'].abs().max())
        out.append(_check('identity actual plan, std event on == stop replacement', abs(r.cumulative_delta_mean - rep) < TOL and abs(r.engine['elapsed_delta_mean_s'] - rep) < TOL and tyre_zero < TOL,
                          event=event, driver=driver, cumulative=r.cumulative_delta_mean, stop_replacement_delta_s=rep, max_abs_tyre_term=tyre_zero))
    else:
        r = engine.compile(ScenarioSpec(event, driver, s_any.in_lap, s_any.to_compound, replace_stop=i_any + 1, standardised_pit_event=True))
        out.append(_check('identity free (red-flag) stop, std event on == 0', abs(r.cumulative_delta_mean) < TOL and r.engine['stop_replacement_delta_s'] == 0.0, event=event, driver=driver, cumulative=r.cumulative_delta_mean))
    # same-compound swap at the driver's own stop
    i_s, s_s = (i_nf, s_nf) if s_nf is not None else (i_any, s_any)
    for mode in ('fixed_context', 'tyre_only'):
        r = engine.compile(ScenarioSpec(event, driver, s_s.in_lap, s_s.to_compound, mode=mode, replace_stop=i_s + 1, set_age=dl.stints[i_s + 1].start_age, standardised_pit_event=False))
        worst = float(np.abs(r.deltas).max())
        out.append(_check(f'same compound at own stop -> zero, {mode}', abs(r.cumulative_delta_mean) < TOL and worst < TOL, event=event, driver=driver, max_abs_sampled_delta=worst))
    # zero degradation: intervention mid-race to a compound different from the one fitted at that lap
    L = max(2, min(dl.n - 8, dl.n // 2))
    actual_comp = dl.compound[L - 1]
    target = next(c for c in ('MEDIUM', 'HARD', 'SOFT') if c != actual_comp and c in engine.offsets(event)[0])
    engine.override_curves = {c: dict(slope=0.0, sd=0.0) for c in ('SOFT', 'MEDIUM', 'HARD')}
    try:
        r = engine.compile(ScenarioSpec(event, driver, L, target, mode='fixed_context', replace_stop='none', continuation='one_stop'))
    finally:
        engine.override_curves = None
    t = r.table
    th = r.engine['theta_sample_mean']
    offs = th
    tyre_expected = np.array([(offs[f'offset_{cf}'] - offs[f'offset_{ac}']) if (cf != ac and not fz) else 0.0 for cf, ac, fz in zip(t['cf_compound'], t['actual_compound'], t['frozen'])])
    tyre_ok = bool(np.allclose(t['delta_tyre_mean'].to_numpy(), tyre_expected, atol=1e-6))
    pit_total = float(t['delta_pit_mean'].sum())
    out.append(_check('zero degradation -> offsets only in the tyre term', tyre_ok, event=event, driver=driver, intervention_lap=L, to_compound=target, max_abs_tyre_error=float(np.abs(t['delta_tyre_mean'].to_numpy() - tyre_expected).max()),
                      pit_term_total_s=pit_total, cumulative=r.cumulative_delta_mean, closes=abs(r.cumulative_delta_mean - (tyre_expected.sum() + pit_total)) < 1e-6))
    # time accounting on a real intervention
    r = engine.compile(ScenarioSpec(event, driver, L, target, mode='fixed_context'))
    t = r.table
    totals = r.deltas.sum(axis=0)
    s = r.summary
    acc = {
        'sum(lap_delta) == cumulative[-1]': abs(t['lap_delta'].sum() - t['cumulative_delta'].iloc[-1]) < TOL,
        'cumulative[-1] == engine.elapsed_delta_mean_s': abs(t['cumulative_delta'].iloc[-1] - r.engine['elapsed_delta_mean_s']) < TOL,
        'cf_lap_time_mean - actual == lap_delta': bool(np.allclose(t['cf_lap_time_mean'] - t['actual_lap_time'], t['lap_delta'], atol=TOL)),
        'tyre + pit == lap_delta': bool(np.allclose(t['delta_tyre_mean'] + t['delta_pit_mean'], t['lap_delta'], atol=TOL)),
        'median of sampled totals == summary median': abs(np.quantile(totals, 0.5) - s['elapsed_delta_median_s']) < TOL,
        'q10 <= median <= q90': s['elapsed_delta_q10_s'] <= s['elapsed_delta_median_s'] <= s['elapsed_delta_q90_s'],
        'probability_of_gain == share of totals < 0': abs(np.mean(totals < 0) - s['probability_of_gain']) < TOL,
        'cumsum(lap_delta) == cumulative': bool(np.allclose(np.cumsum(t['lap_delta']), t['cumulative_delta'], atol=TOL)),
    }
    out.append(_check('time accounting', all(acc.values()), event=event, driver=driver, intervention_lap=L, to_compound=target, detail=acc, elapsed_delta_median_s=s['elapsed_delta_median_s']))
    # conservation: one added stop -> one of each event kind
    kinds_cf = {k: sum(1 for e in r.events_cf if e['kind'] == k) for k in ('pit_entry', 'stationary', 'pit_exit', 'age_reset', 'warm_up')}
    kinds_act = {k: sum(1 for e in r.events_actual if e['kind'] == k) for k in kinds_cf}
    added = {k: kinds_cf[k] - kinds_act[k] for k in kinds_cf}
    n_added_stops = len(r.scenario['counterfactual_plan']['pit_laps']) - len(r.scenario['actual_plan']['pit_laps'])
    out.append(_check('event conservation: one stop -> one of each event', all(v == n_added_stops for v in added.values()), event=event, driver=driver, added=added, stops_added=n_added_stops))
    return out


def reproduce_on_disk(engine) -> list[dict]:
    from counterfactual.engine import ScenarioSpec
    out = []
    cf_root = PROTO / 'out' / 'counterfactual'
    # race-context scenarios sit directly under out/counterfactual/; the Scenario Explorer's pre-race
    # scenarios (curve_source='pre_race_forecast') sit one level deeper under pre_race/ and are checked too.
    for p in sorted(cf_root.glob('*/summary.json')) + sorted(cf_root.glob('pre_race/*/summary.json')):
        s = read_json(p)
        sc, eng = s['scenario'], s['engine']
        rel = p.parent.relative_to(cf_root).as_posix()
        ev = sc['event_id'].split('_', 1)[-1]
        iv = sc['intervention']
        try:
            spec = ScenarioSpec(ev, sc['driver_id'], int(iv['lap']), iv['to_compound'], set_status=iv.get('set_status', 'new'), mode=sc['simulation_mode'], curve_source=eng.get('curve_source', 'race_reference'),
                                n_samples=int(eng.get('n_samples', 500)), seed=int(eng.get('seed', 2026)), sc_factor=float(eng['pit_model']['sc_factor']), exclude_target_driver=bool(eng['curves'].get('target_driver_excluded', True)))
            r = engine.compile(spec)
            diffs = {k: abs(float(r.summary[k]) - float(sc['summary'][k])) for k in ('elapsed_delta_median_s', 'elapsed_delta_q10_s', 'elapsed_delta_q90_s', 'probability_of_gain')}
            same_hash = r.scenario['model_hash'] == sc['model_hash']
            out.append(_check(f'on-disk scenario reproduces: {rel}', max(diffs.values()) < 1e-6 and same_hash, max_abs_diff=max(diffs.values()), diffs=diffs, model_hash_unchanged=same_hash,
                              curve_source=eng.get('curve_source', 'race_reference'), disk_generated_at=sc.get('generated_at'), disk_git_sha=sc.get('git_sha')))
        except Exception as e:
            out.append(_check(f'on-disk scenario reproduces: {rel}', False, error=f'{type(e).__name__}: {e}'))
    return out


def provider_reproduces_lock() -> dict:
    from counterfactual.provider import ProviderA
    lock = read_json(LOCK_V1)
    prov = ProviderA()
    bad = []
    n = 0
    for r in lock['validation_rows']:
        cv = prov.predict_curve(r['event'], None, r['compound'], None, (1, 3))
        n += 1
        if abs(cv.slope - r['pred_clearstint']) > 1e-12 or abs(cv.band[0] - r['lo']) > 1e-12 or abs(cv.band[1] - r['hi']) > 1e-12 or not np.allclose(cv.mean_loss_s, r['pred_clearstint'] * np.arange(1, 4)):
            bad.append(f"{r['event']} {r['compound']}: {cv.slope} vs {r['pred_clearstint']}")
    for ev, lv in lock.get('live', {}).items():
        for c in lv['compounds']:
            cv = prov.predict_curve(ev, None, c['compound'], None, (1, 3))
            n += 1
            if abs(cv.slope - c['prediction']) > 1e-12 or abs(cv.band[0] - c['band90'][0]) > 1e-12 or abs(cv.band[1] - c['band90'][1]) > 1e-12:
                bad.append(f'{ev} {c["compound"]}: {cv.slope} vs {c["prediction"]}')
    return _check('provider A reproduces every lock curve', not bad, curves_checked=n, mismatches=bad)


# ---------------------------------------------------------------- pit-loss derivation
def pit_loss_derivation() -> dict:
    from counterfactual.pitmodel import season_pool, STATIONARY_Q
    with tempfile.TemporaryDirectory() as td:
        pool = season_pool(PROTO / 'feat', cache_path=Path(td) / 'fresh_pool.json')      # recomputed from the feature files, not the cache
    green = [s for s in pool['stops'] if s['kind'] == 'green']
    tot = np.array([s['total'] for s in green]); ins = np.array([s['meas_in'] for s in green])
    med = float(np.median(tot)); mad = float(np.median(np.abs(tot - med)))
    mine = dict(n_green_stops=len(green), n_races=len({s['event'] for s in green}), median_total_s=med, mad_s=mad, transit_s=med - STATIONARY_Q[1], transit_sd_s=max(1.4826 * mad, 0.8),
                share_in=float(np.median(ins) / med), n_sc_stops=sum(1 for s in pool['stops'] if s['kind'] == 'sc'), n_outlap_stints=len(pool['outlaps']))
    reported = []
    for p in sorted((PROTO / 'out' / 'counterfactual').glob('*/summary.json')):
        pm = read_json(p)['engine']['pit_model']
        d = pm['derivation']['season_pool']
        reported.append(dict(scenario=p.parent.name, transit_med=pm['transit_med'], transit_sd=pm['transit_sd'], share_in=pm['share_in'], pool_n_green=d['n_green_stops'], pool_n_races=d['n_races'], pool_median=d['median_total_s'], pool_mad=d['mad_s'],
                             source=pm['derivation']['transit']['source']))
    # Every scenario must record the same season pool. The transit itself equals the pool only when the pit model fell
    # back to it: a race with enough green stops of its own derives transit from those (pitmodel.derivation.transit.source).
    pool_agree = all(x['pool_n_green'] == mine['n_green_stops'] and abs(x['pool_median'] - mine['median_total_s']) < 1e-6
                     and abs(x['pool_mad'] - mine['mad_s']) < 1e-6 for x in reported)
    pooled = [x for x in reported if x['source'] == 'season_pool']
    transit_agree = all(abs(x['transit_med'] - mine['transit_s']) < 1e-6 and abs(x['share_in'] - mine['share_in']) < 1e-6
                        and abs(x['transit_sd'] - mine['transit_sd_s']) < 1e-6 for x in pooled)
    agree = pool_agree and transit_agree
    readme = (PROTO / 'counterfactual' / 'README.md').read_text(encoding='utf-8')
    m = re.search(r'(\d+) green stops over (\d+) race files, median ([\d.]+) s \(MAD ([\d.]+)\) -> transit ([\d.]+) s,\s*sd ([\d.]+), ([\d.]+)% of it on the in-lap', readme)
    readme_claim = dict(n=int(m.group(1)), races=int(m.group(2)), median=float(m.group(3)), mad=float(m.group(4)), transit=float(m.group(5)), sd=float(m.group(6)), share_pct=float(m.group(7))) if m else None
    readme_ok = bool(m) and readme_claim['n'] == mine['n_green_stops'] and readme_claim['races'] == mine['n_races'] and abs(readme_claim['median'] - mine['median_total_s']) < 0.006 and abs(readme_claim['mad'] - mine['mad_s']) < 0.006 \
        and abs(readme_claim['transit'] - mine['transit_s']) < 0.006 and abs(readme_claim['sd'] - mine['transit_sd_s']) < 0.006 and abs(readme_claim['share_pct'] - 100 * mine['share_in']) < 0.06
    doc = (PROTO / 'counterfactual' / 'pitmodel.py').read_text(encoding='utf-8')
    m2 = re.search(r'2026 pool: (\d+) stops, median ([\d.]+) s, MAD ([\d.]+) s', doc)
    docstring_claim = dict(n=int(m2.group(1)), median=float(m2.group(2)), mad=float(m2.group(3))) if m2 else None
    doc_ok = bool(m2) and docstring_claim['n'] == mine['n_green_stops'] and abs(docstring_claim['median'] - mine['median_total_s']) < 0.006
    return dict(check='pit-loss derivation recomputed from the feature files', status='PASS' if (agree and readme_ok) else 'FAIL', recomputed=mine, reported_in_summaries=reported, summaries_agree=agree,
                readme_claim=readme_claim, readme_agrees=readme_ok, pitmodel_docstring_claim=docstring_claim, pitmodel_docstring_agrees=doc_ok,
                pool_block_agrees=pool_agree, pooled_transit_agrees=transit_agree, n_pooled_source=len(pooled), n_race_source=len(reported) - len(pooled),
                note='the docstring of counterfactual/pitmodel.py is informational; a stale value there is a LOW finding, not a failure' if not doc_ok else '')


# ---------------------------------------------------------------- batch == replay
def batch_equals_replay(event: str = 'Monza', drivers: Optional[list[str]] = None) -> dict:
    from live.session import LiveSession
    from live.estimator import batch_posterior
    from live.lapfeed import LapFeed
    feed = LapFeed(event)
    drivers = drivers or sorted(feed.drivers, key=lambda d: -len(feed.laps_of(d)))[:6]
    worst, n_laps, per_driver, flags = 0.0, 0, {}, []
    for drv in drivers:
        s = LiveSession.open(event, drv, feedback_enabled=False)
        st, w, n = None, 0.0, 0
        for k in s.laps():
            row = s.feed.row(drv, k)
            st = s.estimator.update(st, row, s.context_for(k, row))
            if st.uses_future_data or st.uses_post_race_reference:
                flags.append(f'{drv} lap {k}')
            if st.n_obs >= 1:
                m, P = batch_posterior(st)
                w = max(w, abs(m[0] - st.m[0]), abs(m[1] - st.m[1]), float(np.max(np.abs(P - np.array(st.P)))))
                n += 1
        per_driver[drv] = dict(laps_compared=n, max_abs_diff=w)
        worst, n_laps = max(worst, w), n_laps + n
    return _check(f'batch conditioning == sequential filter ({event})', worst < TOL and n_laps > 20 and not flags, event=event, drivers=drivers, laps_compared=n_laps, max_abs_diff=worst, per_driver=per_driver, online_safe_flags_violated=flags)


def run(events: Optional[list[str]] = None, drivers: Optional[list[str]] = None, out: Path | str | None = REPORT_PATH) -> dict:
    events = events or ['Monza', 'Austria']
    drivers = drivers or ['NOR', 'VER']
    rep: dict[str, Any] = dict(generated_at=now_iso(), events=events, drivers=drivers, checks=[])
    try:
        from counterfactual.engine import CounterfactualEngine
        engine = CounterfactualEngine()
        for ev in events:
            for drv in drivers:
                try:
                    rep['checks'].extend(counterfactual_checks(ev, drv, engine))
                except Exception as e:
                    rep['checks'].append(_check(f'counterfactual checks {ev} {drv}', False, error=f'{type(e).__name__}: {e}', traceback=traceback.format_exc()[-800:]))
        rep['checks'].extend(reproduce_on_disk(engine))
        rep['checks'].append(provider_reproduces_lock())
        rep['checks'].append(pit_loss_derivation())
    except Exception as e:
        rep['checks'].append(_check('counterfactual core', False, error=f'{type(e).__name__}: {e}', traceback=traceback.format_exc()[-800:]))
    try:
        rep['checks'].append(batch_equals_replay(events[0]))
    except Exception as e:
        rep['checks'].append(_check('batch == replay', False, error=f'{type(e).__name__}: {e}', traceback=traceback.format_exc()[-800:]))
    rep['summary'] = dict(passed=sum(1 for c in rep['checks'] if c['status'] == 'PASS'), failed=sum(1 for c in rep['checks'] if c['status'] != 'PASS'))
    rep['status'] = 'PASS' if rep['summary']['failed'] == 0 else 'FAIL'
    rep['exit_code'] = 0 if rep['status'] == 'PASS' else 1
    if out:
        write_json(out, rep)
    return rep


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--events', default='Monza,Austria'); ap.add_argument('--drivers', default='NOR,VER'); ap.add_argument('--out', default=str(REPORT_PATH))
    a = ap.parse_args(argv)
    rep = run([x.strip() for x in a.events.split(',')], [x.strip() for x in a.drivers.split(',')], a.out)
    print(f"identity checks: {rep['status']} ({rep['summary']['passed']} passed, {rep['summary']['failed']} failed) -> exit {rep['exit_code']}")
    for c in rep['checks']:
        tag = f"{c.get('event', '')} {c.get('driver', '')}".strip()
        extra = ''
        if 'max_abs_sampled_delta' in c: extra = f" max|delta| {c['max_abs_sampled_delta']:.2e}"
        if 'max_abs_diff' in c: extra = f" max|diff| {c['max_abs_diff']:.2e}"
        if 'recomputed' in c: extra = f" pool n={c['recomputed']['n_green_stops']} median {c['recomputed']['median_total_s']:.3f} transit {c['recomputed']['transit_s']:.3f} share_in {c['recomputed']['share_in']:.3f}; README agrees {c['readme_agrees']}; docstring agrees {c['pitmodel_docstring_agrees']}"
        if 'error' in c: extra = f" error: {c['error']}"
        print(f"  {c['status']:<5} {c['check']} {tag}{extra}")
    print(f'report: {a.out}')
    return rep['exit_code']


if __name__ == '__main__':
    sys.exit(main())
