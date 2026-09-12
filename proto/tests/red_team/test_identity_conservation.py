"""Identity and conservation of the counterfactual core (roadmap v5 task 0.0; Phase 0 acceptance 6 'changing nothing in
Ghost produces zero delta'; stop-the-line condition 'the actual-plan counterfactual is non-zero').

Independent of Workstream 2's own tests: the public engine API is driven here and the identities are recomputed from the
returned table and samples. Self-tests plant a non-identity plan and a corrupted table to show the checks bite."""
from __future__ import annotations

import numpy as np
import pytest

from rt_helpers import EVENT, DRIVER

TOL = 1e-9
N_SAMPLES = 200      # enough for the identities (they hold sample by sample); keeps the suite fast


@pytest.fixture(scope='module')
def engine(race_csv, lock_v1_path, lock_v2_path):
    from counterfactual.engine import CounterfactualEngine
    return CounterfactualEngine()


@pytest.fixture(scope='module')
def driver_laps(engine):
    dl = engine.race(EVENT).driver(DRIVER)
    if not dl.stops:
        pytest.skip(f'{DRIVER} made no stop at {EVENT}; the identity replay needs a stop')
    return dl


def _actual_plan_spec(dl, mode: str, to_compound: str | None = None, n_samples: int = N_SAMPLES):
    from counterfactual.engine import ScenarioSpec
    s = dl.stops[0]
    return ScenarioSpec(EVENT, DRIVER, s.in_lap, to_compound or s.to_compound, mode=mode, standardised_pit_event=False, replace_stop=1, set_age=dl.stints[1].start_age, n_samples=n_samples)


def identity_violations(r) -> list[str]:
    """Why a compiled scenario is not the identity (empty list = the actual plan reproduced with zero delta)."""
    out = []
    if r.scenario['counterfactual_plan'] != r.scenario['actual_plan']:
        out.append('counterfactual plan differs from the actual plan')
    worst = float(np.abs(r.deltas).max())
    if worst >= TOL:
        out.append(f'max |sampled per-lap delta| = {worst:.3e}')
    if abs(r.cumulative_delta_mean) >= TOL:
        out.append(f'cumulative delta = {r.cumulative_delta_mean:.3e}')
    if r.scenario['validation']['identity_test'] != 'pass':
        out.append(f"engine identity_test = {r.scenario['validation']['identity_test']}")
    return out


def decomposition_violations(table, deltas, summary, elapsed_mean: float) -> list[str]:
    out = []
    if not np.allclose(table['delta_tyre_mean'] + table['delta_pit_mean'], table['lap_delta'], atol=TOL):
        out.append('tyre + pit != lap_delta')
    if not np.allclose(np.cumsum(table['lap_delta']), table['cumulative_delta'], atol=TOL):
        out.append('cumsum(lap_delta) != cumulative_delta')
    if abs(table['lap_delta'].sum() - elapsed_mean) >= TOL:
        out.append(f"sum(lap_delta) {table['lap_delta'].sum():.6f} != elapsed_delta_mean_s {elapsed_mean:.6f}")
    if not np.allclose(table['cf_lap_time_mean'] - table['actual_lap_time'], table['lap_delta'], atol=TOL):
        out.append('cf_lap_time_mean - actual_lap_time != lap_delta')
    totals = deltas.sum(axis=0)
    if abs(np.quantile(totals, 0.5) - summary['elapsed_delta_median_s']) >= TOL:
        out.append('summary median is not the median of the sampled totals')
    if not (summary['elapsed_delta_q10_s'] <= summary['elapsed_delta_median_s'] <= summary['elapsed_delta_q90_s']):
        out.append('quantiles not ordered')
    if abs(np.mean(totals < 0) - summary['probability_of_gain']) >= TOL:
        out.append('probability_of_gain is not the share of sampled totals below zero')
    return out


@pytest.mark.parametrize('mode', ['fixed_context', 'tyre_only'])
def test_actual_plan_counterfactual_is_zero(engine, driver_laps, mode):
    r = engine.compile(_actual_plan_spec(driver_laps, mode))
    v = identity_violations(r)
    assert not v, f'{EVENT} {DRIVER} {mode}: ' + '; '.join(v)


def test_identity_check_rejects_a_changed_plan(engine, driver_laps):
    """Self-test: fit a different compound at the driver's own stop and the identity must be broken (non-zero delta)."""
    s = driver_laps.stops[0]
    other = next(c for c in ('HARD', 'MEDIUM', 'SOFT') if c != s.to_compound and c in engine.offsets(EVENT)[0])
    r = engine.compile(_actual_plan_spec(driver_laps, 'fixed_context', to_compound=other))
    v = identity_violations(r)
    assert v and any('plan differs' in x for x in v) and abs(r.cumulative_delta_mean) > 1e-3, v


def test_decomposition_sums(engine, race_csv):
    from counterfactual.engine import ScenarioSpec
    r = engine.compile(ScenarioSpec(EVENT, DRIVER, 24, 'MEDIUM', mode='fixed_context', n_samples=N_SAMPLES))
    v = decomposition_violations(r.table, r.deltas, r.summary, r.engine['elapsed_delta_mean_s'])
    assert not v, '; '.join(v)


def test_decomposition_check_rejects_a_corrupted_table(engine, race_csv):
    """Self-test: 10 ms added to one tyre term must break tyre + pit == lap_delta."""
    from counterfactual.engine import ScenarioSpec
    r = engine.compile(ScenarioSpec(EVENT, DRIVER, 24, 'MEDIUM', mode='fixed_context', n_samples=N_SAMPLES))
    t = r.table.copy()
    t.loc[t.index[len(t) // 2], 'delta_tyre_mean'] += 0.01
    v = decomposition_violations(t, r.deltas, r.summary, r.engine['elapsed_delta_mean_s'])
    assert 'tyre + pit != lap_delta' in v, v


def test_one_added_stop_conserves_events(engine, race_csv):
    from counterfactual.engine import ScenarioSpec
    dl = engine.race(EVENT).driver(DRIVER)
    L = max(2, min(dl.n - 8, dl.n // 2))
    target = next(c for c in ('MEDIUM', 'HARD', 'SOFT') if c != dl.compound[L - 1] and c in engine.offsets(EVENT)[0])
    r = engine.compile(ScenarioSpec(EVENT, DRIVER, L, target, mode='fixed_context', n_samples=N_SAMPLES))
    kinds = ('pit_entry', 'stationary', 'pit_exit', 'age_reset', 'warm_up')
    added = {k: sum(1 for e in r.events_cf if e['kind'] == k) - sum(1 for e in r.events_actual if e['kind'] == k) for k in kinds}
    n_added = len(r.scenario['counterfactual_plan']['pit_laps']) - len(r.scenario['actual_plan']['pit_laps'])
    assert n_added >= 1 and all(v == n_added for v in added.values()), (n_added, added)


def test_ghost_page_scenario_decomposition_closes(lock_v1_path):
    """The scenario the Ghost page shows by default: tyre + pit + interaction == total and the engine's own identity delta is 0."""
    from app_v2.services import counterfactual_repository as CF
    sc = CF.default_scenario(EVENT)
    if sc is None:
        pytest.skip('no Workstream 2 scenario under out/counterfactual')
    d = CF.decomposition(sc)
    assert abs((d['tyre'] + d['pit'] + d['interaction']) - d['total']) < 1e-6 and d['identity_check_delta_s'] == 0.0, d
    assert all(i['identity_test'] == 'pass' and i['future_leakage_test'] == 'pass' for i in CF.identity_status(EVENT))
    assert all(v['status'] == 'verified' for v in CF.verify_assets(sc).values()), CF.verify_assets(sc)
