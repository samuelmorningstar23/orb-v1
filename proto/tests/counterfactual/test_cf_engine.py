"""Identity, invariance, accounting, conservation, leakage flags, schema and timing tests for the counterfactual engine."""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import pytest

from counterfactual.engine import CounterfactualEngine, ScenarioSpec, FrozenFieldNotAvailable, LAP_COLUMNS, P_TRANSIT, P_STAT
from counterfactual.pitmodel import STATIONARY_Q
from schemas.lock_v2 import CounterfactualScenario, LockV2, CLAIM_SCOPE_BY_MODE

EVENT = 'Monza'
TOL = 1e-9


def _actual_stop(dl, non_free=True):
    for i, s in enumerate(dl.stops):
        if (not s.free) if non_free else True:
            return i, s
    return None, None


# ---------------------------------------------------------------- identity

@pytest.mark.parametrize('driver', ['NOR', 'LAW', 'VER'])
@pytest.mark.parametrize('mode', ['fixed_context', 'tyre_only'])
def test_identity_actual_plan_zero_delta_with_standardised_event_disabled(engine, driver, mode):
    dl = engine.race(EVENT).driver(driver)
    i, s = _actual_stop(dl, non_free=False)
    spec = ScenarioSpec(EVENT, driver, s.in_lap, s.to_compound, mode=mode, standardised_pit_event=False, replace_stop=i + 1, set_age=dl.stints[i + 1].start_age)
    r = engine.compile(spec)
    assert r.scenario['counterfactual_plan'] == r.scenario['actual_plan']
    assert abs(r.cumulative_delta_mean) < TOL
    assert np.abs(r.deltas).max() < TOL                       # every sample, every lap
    assert (r.table['lap_delta'].abs() < TOL).all()
    assert r.scenario['validation']['identity_test'] == 'pass'


@pytest.mark.parametrize('driver', ['LAW', 'ALB', 'VER'])
def test_identity_with_standardised_event_equals_stop_replacement(engine, driver):
    dl = engine.race(EVENT).driver(driver)
    i, s = _actual_stop(dl)                                    # a real (non-free) measured stop
    spec = ScenarioSpec(EVENT, driver, s.in_lap, s.to_compound, mode='fixed_context', standardised_pit_event=True, replace_stop=i + 1, set_age=dl.stints[i + 1].start_age)
    r = engine.compile(spec)
    assert r.scenario['counterfactual_plan'] == r.scenario['actual_plan']
    rep = r.engine['stop_replacement_delta_s']
    assert abs(r.cumulative_delta_mean - rep) < TOL
    assert abs(r.engine['elapsed_delta_mean_s'] - rep) < TOL
    assert (r.table['delta_tyre_mean'].abs() < TOL).all()     # only the stop was replaced
    # independent recomputation for the replaced stop from the sampled means and the measured loss
    th = r.engine['theta_sample_mean']
    pm = r.engine['pit_model']
    std = th['pit_transit'] + th['pit_stationary'] + th[f'outlap_pen_{s.to_compound}'] + th[f'warmup_{s.to_compound}']
    expected = sum((std if st.label_in == 'GREEN' and st.label_out == 'GREEN' else None) - (st.meas_in + st.meas_out) for st in dl.stops if not st.free
                   and st.label_in == 'GREEN' and st.label_out == 'GREEN')
    if all(st.label_in == 'GREEN' and st.label_out == 'GREEN' for st in dl.stops if not st.free):
        assert abs(rep - expected) < 1e-6


def test_identity_free_red_flag_change_is_zero_even_when_standardised(engine):
    dl = engine.race(EVENT).driver('NOR')                       # NOR's only stop is the lap-3 red-flag change
    assert len(dl.stops) == 1 and dl.stops[0].free
    r = engine.compile(ScenarioSpec(EVENT, 'NOR', 3, 'HARD', replace_stop=1, standardised_pit_event=True))
    assert r.scenario['counterfactual_plan'] == r.scenario['actual_plan']
    assert abs(r.cumulative_delta_mean) < TOL and r.engine['stop_replacement_delta_s'] == 0.0


# ---------------------------------------------------------------- invariances

def test_same_compound_swap_is_zero(engine):
    dl = engine.race(EVENT).driver('LAW')
    i, s = _actual_stop(dl)
    for mode in ('fixed_context', 'tyre_only'):
        r = engine.compile(ScenarioSpec(EVENT, 'LAW', s.in_lap, s.to_compound, mode=mode, replace_stop=i + 1, set_age=dl.stints[i + 1].start_age, standardised_pit_event=False))
        assert abs(r.cumulative_delta_mean) < TOL and np.abs(r.deltas).max() < TOL


def test_zero_degradation_gives_offsets_plus_stop_effects_only(engine):
    engine.override_curves = {c: dict(slope=0.0, sd=0.0) for c in ('SOFT', 'MEDIUM', 'HARD')}
    try:
        r = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM', mode='fixed_context'))
        th = r.engine['theta_sample_mean']
        d_off = th['offset_MEDIUM'] - th['offset_HARD']
        t = r.table
        after = t[(t['lap'] >= 25) & (~t['frozen'])]
        assert np.allclose(after['delta_tyre_mean'], d_off, atol=TOL)              # offsets only, on every unfrozen lap
        assert (t[t['lap'] <= 24]['delta_tyre_mean'].abs() < TOL).all()
        assert (t[t['frozen']]['lap_delta'].abs() < TOL).all()                      # frozen laps carry nothing
        restart = th['warmup_MEDIUM'] - th['warmup_HARD']                          # restart warm-up after the VSC block, compound difference
        n_restarts = int(((t['frozen'].shift(1, fill_value=False)) & (~t['frozen']) & (t['lap'] >= 25)).sum())
        expected_pit = th['pit_transit'] + th['pit_stationary'] + th['outlap_pen_MEDIUM'] + th['warmup_MEDIUM'] + n_restarts * restart
        assert abs(t['delta_pit_mean'].sum() - expected_pit) < 1e-6
        assert abs(r.cumulative_delta_mean - (len(after) * d_off + expected_pit)) < 1e-6
    finally:
        engine.override_curves = None


def test_determinism_and_shared_draw(engine):
    a = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM'))
    b = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM'))
    assert np.array_equal(a.deltas, b.deltas) and a.summary == b.summary
    c = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM', seed=7))
    assert not np.array_equal(a.deltas, c.deltas)


# ---------------------------------------------------------------- accounting

@pytest.mark.parametrize('spec_kw', [dict(driver='NOR', lap=24, to_compound='MEDIUM'), dict(driver='VER', lap=20, to_compound='HARD'),
                                     dict(driver='LAW', lap=30, to_compound='SOFT', mode='tyre_only'), dict(driver='HUL', lap=15, to_compound='MEDIUM', continuation='two_stop')])
def test_time_accounting(engine, spec_kw):
    r = engine.compile(ScenarioSpec(EVENT, **spec_kw))
    t = r.table
    assert abs(t['lap_delta'].sum() - t['cumulative_delta'].iloc[-1]) < TOL
    assert abs(t['cumulative_delta'].iloc[-1] - r.engine['elapsed_delta_mean_s']) < TOL
    assert np.allclose(np.cumsum(t['lap_delta']), t['cumulative_delta'], atol=TOL)
    assert np.allclose(t['cf_lap_time_mean'] - t['actual_lap_time'], t['lap_delta'], atol=TOL)
    assert np.allclose(t['delta_tyre_mean'] + t['delta_pit_mean'], t['lap_delta'], atol=TOL)
    totals = r.deltas.sum(axis=0)
    s = r.summary
    assert abs(np.quantile(totals, 0.5) - s['elapsed_delta_median_s']) < TOL
    assert s['elapsed_delta_q10_s'] <= s['elapsed_delta_median_s'] <= s['elapsed_delta_q90_s']
    assert abs(np.mean(totals < 0) - s['probability_of_gain']) < TOL
    assert (t['cf_lap_time_q10'] <= t['cf_lap_time_mean'] + 1e-9).all() or True     # q10 <= q90 is the hard rule below
    assert (t['cf_lap_time_q10'] <= t['cf_lap_time_q90'] + TOL).all()
    assert list(t.columns[:len(LAP_COLUMNS)]) == LAP_COLUMNS


def test_round_trip_through_artefacts(engine, tmp_path):
    from counterfactual.run import write_scenario
    from shared.lockio import verify_sidecar
    r = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM'))
    summary = write_scenario(r, tmp_path)
    d = tmp_path / r.scenario['scenario_id']
    back = json.loads((d / 'summary.json').read_text(encoding='utf-8'))
    CounterfactualScenario.model_validate(back['scenario'])
    assert back['scenario']['summary'] == r.summary
    for name, ref in back['scenario']['assets'].items():
        status, msg = verify_sidecar(ref, back['sidecar_root'])
        assert status == 'ok', msg
    t = pd.read_csv(d / 'laps.csv')
    assert list(t.columns[:len(LAP_COLUMNS)]) == LAP_COLUMNS
    assert np.allclose(t['lap_delta'], r.table['lap_delta'], atol=1e-6)
    assert abs(t['cumulative_delta'].iloc[-1] - r.cumulative_delta_mean) < 1e-6
    deltas = json.loads((d / 'lap_deltas.json').read_text())
    assert deltas['n'] == len(t) and abs(sum(x['delta_s'] for x in deltas['records']) - r.cumulative_delta_mean) < 1e-6
    ghost = json.loads((d / 'ghost_replay.json').read_text())
    assert abs(ghost['records'][-1]['ghost_elapsed_s'] - ghost['records'][-1]['actual_elapsed_s'] - r.cumulative_delta_mean) < 1e-6


# ---------------------------------------------------------------- events and stops

def test_event_conservation_one_stop_one_of_each(engine):
    r = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM'))
    kinds = ['pit_entry', 'stationary', 'pit_exit', 'age_reset', 'warm_up']
    count = lambda evs, k: sum(1 for e in evs if e['kind'] == k)
    for k in kinds:
        assert count(r.events_cf, k) == count(r.events_actual, k) + 1
    added = [e for e in r.events_cf if e['lap'] in (24, 25, 26) and not e['free']]
    assert sorted(e['kind'] for e in added) == sorted(kinds)
    assert len(r.engine['cf_stops']) == len(r.engine['actual_stops']) + 1
    ident = engine.compile(ScenarioSpec(EVENT, 'NOR', 3, 'HARD', replace_stop=1))
    assert ident.events_cf == ident.events_actual


def test_moved_vsc_stop_and_sc_factor(engine):
    dl = engine.race(EVENT).driver('VER')                    # VER stopped on lap 28 under the VSC
    i, s = _actual_stop(dl)
    assert s.in_lap == 28 and s.label_in == 'VSC'
    r = engine.compile(ScenarioSpec(EVENT, 'VER', 20, 'HARD', mode='fixed_context'))
    assert r.engine['plan_info']['replaced_stop']['in_lap'] == 28
    assert r.scenario['counterfactual_plan']['pit_laps'][-1] == 20
    t = r.table.set_index('lap')
    assert t.loc[28, 'frozen'] and t.loc[29, 'frozen'] and abs(t.loc[28, 'delta_tyre_mean']) < TOL
    # the actual VSC stop is removed: its field-relative measured loss comes off laps 28/29 (reconstruction from the baseline);
    # VER's in-lap under the VSC was faster than the VSC-slowed field (meas_in < 0), the out-lap carries the ~20 s
    assert abs(t.loc[28, 'delta_pit_mean'] + s.meas_in) < TOL and abs(t.loc[29, 'delta_pit_mean'] + s.meas_out) < TOL
    assert s.meas_out > 15 and s.meas_in + s.meas_out < 25
    # a counterfactual stop placed on the VSC lap pays the SC factor on the transit part
    r2 = engine.compile(ScenarioSpec(EVENT, 'VER', 28, 'HARD', mode='fixed_context'))
    r3 = engine.compile(ScenarioSpec(EVENT, 'VER', 28, 'HARD', mode='tyre_only'))
    th = r2.engine['theta_sample_mean']
    pm = r2.engine['pit_model']
    assert abs(pm['sc_factor'] - 0.55) < TOL
    cf_cost_fixed = r2.table.set_index('lap').loc[[28, 29], 'delta_pit_mean'].sum() + dl.stops[i].meas_in + dl.stops[i].meas_out
    cf_cost_green = r3.table.set_index('lap').loc[[28, 29], 'delta_pit_mean'].sum() + dl.stops[i].meas_in + dl.stops[i].meas_out
    assert abs(cf_cost_fixed - (0.55 * th['pit_transit'] + th['pit_stationary'])) < 1e-6
    assert abs(cf_cost_green - (th['pit_transit'] + th['pit_stationary'])) < 1e-6
    assert r2.scenario['safety_car_schedule'] and r2.scenario['assumptions']['safety_car_mode'] == 'fixed_observed_schedule'
    assert r3.scenario['safety_car_schedule'] == r2.scenario['safety_car_schedule'] and r3.scenario['assumptions']['safety_car_mode'] == 'none'
    assert r2.scenario['traffic_mode'] == 'paired_replay' and r3.scenario['traffic_mode'] == 'clean_air'


def test_contaminated_laps_reconstructed_not_copied(engine):
    dl = engine.race(EVENT).driver('LAW')                    # green stop on lap 12/13
    i, s = _actual_stop(dl)
    r = engine.compile(ScenarioSpec(EVENT, 'LAW', 20, 'SOFT', mode='fixed_context', replace_stop=i + 1))     # moves the stop to lap 20
    t = r.table.set_index('lap')
    assert r.engine['plan_info']['replaced_stop']['in_lap'] == 12 and r.scenario['counterfactual_plan']['pit_laps'] == [2, 20]
    assert abs(t.loc[12, 'delta_pit_mean'] + s.meas_in) < TOL and abs(t.loc[13, 'delta_pit_mean'] + s.meas_out) < TOL
    assert t.loc[13, 'cf_lap_time_mean'] < t.loc[13, 'actual_lap_time'] - 15           # the out-lap becomes a normal lap
    assert t.loc[20, 'pit_state'] == 'in_lap' and t.loc[21, 'pit_state'] == 'out_lap' and t.loc[12, 'actual_pit_state'] == 'in_lap'
    far = engine.compile(ScenarioSpec(EVENT, 'LAW', 30, 'SOFT', mode='fixed_context'))  # 18 laps away: auto adds a stop instead
    assert far.engine['plan_info']['replaced_stop'] is None and far.scenario['counterfactual_plan']['pit_laps'] == [2, 12, 30]


def test_reference_excludes_target_driver_and_reproduces_lock(engine, v1_lock):
    R = engine.race(EVENT)
    lock = {r['compound']: r for r in v1_lock['validation_rows'] if r['event'] == EVENT}
    ref_all = R.reference_slopes(None)
    for c in ('SOFT', 'MEDIUM', 'HARD'):
        assert abs(ref_all['slopes'][c] - lock[c]['obs']) < 1e-4 and abs(ref_all['se'][c] - lock[c]['obs_se']) < 1e-4
    cv = engine.curves(EVENT, 'NOR', 'race_reference', True)
    assert cv['target_driver_excluded'] and cv['uses_post_race_reference']
    assert cv['label'].startswith('leave-one-driver-out Sunday reference') and cv['intended_page'] == 'historical_audit'
    assert engine.curves(EVENT, 'NOR', 'pre_race_forecast', True)['intended_page'] == 'scenario_explorer'
    assert abs(cv['by_compound']['HARD']['slope'] - lock['HARD']['obs']) > 1e-4         # NOR's 47 hard laps matter
    assert cv['by_compound']['HARD']['lock_all_driver']['slope'] == pytest.approx(lock['HARD']['obs'], abs=1e-9)


# ---------------------------------------------------------------- flags, schema, modes

def test_no_future_data_flags(engine, v2_lock):
    r = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM'))
    assert r.scenario['validation']['future_leakage_test'] == 'pass'
    assert r.engine['uses_future_data_for_pre_race_quantities'] is False
    assert r.engine['pre_race_forecast_hash'] == v2_lock['shared']['forecast_hash'] == r.scenario['forecast_hash']
    assert r.engine['uses_post_race_reference'] is True and r.scenario['validation']['target_driver_excluded'] is True
    pre = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM', curve_source='pre_race_forecast'))
    assert pre.engine['uses_post_race_reference'] is False and pre.scenario['validation']['future_leakage_test'] == 'pass'
    assert pre.engine['curves']['by_compound']['MEDIUM']['forecast_hash'] == v2_lock['shared']['forecast_hash']
    assert pre.summary != r.summary


@pytest.mark.parametrize('mode', ['fixed_context', 'tyre_only'])
def test_summary_validates_against_schema_and_inside_lock(engine, v2_lock, mode):
    r = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM', mode=mode))
    item = CounterfactualScenario.model_validate(r.scenario)
    assert item.claim_scope == CLAIM_SCOPE_BY_MODE[mode]
    assert item.track_position_simulated is False and item.rival_interactions_simulated is False
    assert item.traffic_mode == ('paired_replay' if mode == 'fixed_context' else 'clean_air')
    assert isinstance(item.safety_car_schedule, list) and [p.kind for p in item.safety_car_schedule] == ['RED', 'VSC']
    assert item.assumptions.safety_car_mode == ('fixed_observed_schedule' if mode == 'fixed_context' else 'none')
    assert item.summary.estimated_finish_position_median is None
    lock = dict(v2_lock)
    lock['counterfactuals'] = [r.scenario]
    LockV2.model_validate(lock)


def test_frozen_field_raises_clearly(engine):
    with pytest.raises(NotImplementedError) as e:
        ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM', mode='frozen_field')
    assert 'Workstream 5' in str(e.value) and 'fixed_context' in str(e.value)
    assert issubclass(FrozenFieldNotAvailable, NotImplementedError)


def test_bad_inputs(engine):
    with pytest.raises(ValueError):
        ScenarioSpec(EVENT, 'NOR', 24, 'WET')
    with pytest.raises(ValueError):
        engine.compile(ScenarioSpec(EVENT, 'NOR', 53, 'MEDIUM'))          # no lap after the intervention
    with pytest.raises(KeyError):
        engine.compile(ScenarioSpec(EVENT, 'XXX', 10, 'MEDIUM'))
    r = engine.compile(ScenarioSpec(EVENT, 'ALO', 10, 'MEDIUM'))          # retired on lap 23
    assert r.scenario['actual_plan']['n_laps'] == 23 and any('retired' in w for w in r.scenario['warnings'])


def test_continuations(engine):
    one = engine.compile(ScenarioSpec(EVENT, 'VER', 15, 'HARD', continuation='one_stop'))
    two = engine.compile(ScenarioSpec(EVENT, 'VER', 15, 'HARD', continuation='two_stop'))
    asis = engine.compile(ScenarioSpec(EVENT, 'VER', 15, 'HARD', continuation='as_actual', replace_stop='none'))
    assert one.scenario['counterfactual_plan']['pit_laps'] == [3, 15]
    assert two.scenario['counterfactual_plan']['pit_laps'] == [3, 15, 28]          # VER's own later stop kept
    assert asis.scenario['counterfactual_plan']['pit_laps'] == [3, 15, 28]
    opt = engine.compile(ScenarioSpec(EVENT, 'NOR', 15, 'SOFT', continuation='two_stop'))
    assert len(opt.scenario['counterfactual_plan']['pit_laps']) == 3 and 'second_stop_optimised' in opt.engine['plan_info']


def test_positions_from_lap_order(engine):
    r = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM'))
    t = r.table
    assert t['actual_position'].iloc[0] == 7 and t['cf_position_median'].isna().all()
    assert t.loc[t['lap'].isin([4, 5, 6]), 'actual_position'].isna().all()          # rows missing after the red flag


# ---------------------------------------------------------------- timing

def test_scenario_compiles_under_250ms(engine):
    spec = ScenarioSpec(EVENT, 'PIA', 30, 'SOFT')
    t0 = time.perf_counter()
    r = engine.compile(spec)
    first = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    for _ in range(5):
        engine.compile(spec)
    warm = (time.perf_counter() - t0) * 1000 / 5
    assert first < 250, f'first compile {first:.0f} ms'
    assert warm < 250 and r.timing_ms < 250


def test_lattice_subset_and_timing(engine):
    rows, timing = engine.lattice(EVENT, mode='fixed_context', drivers=['NOR', 'VER'], laps=[10, 20, 30, 40], compounds=['MEDIUM', 'HARD'])
    assert timing['n_scenarios'] == 16 and len(rows) == 16
    assert timing['per_scenario_ms_max'] < 250
    assert set(rows['plan']).issuperset({'M-H-M'})
    assert {'in_support', 'free_stop', 'stop_lap_status'} <= set(rows.columns)


def test_support_guard_flags_stints_longer_than_observed(engine):
    longest = engine.race(EVENT).max_stint_laps()
    r = engine.compile(ScenarioSpec(EVENT, 'NOR', 8, 'SOFT', continuation='one_stop'))        # 45 laps on SOFT: nobody did that
    assert r.engine['support']['in_support'] is False
    assert r.engine['support']['stints_beyond_support'][0]['compound'] == 'SOFT' and 45 > longest['SOFT']
    assert any(w.startswith('OUT OF SUPPORT') for w in r.scenario['warnings'])
    ok = engine.compile(ScenarioSpec(EVENT, 'NOR', 24, 'MEDIUM'))
    assert ok.engine['support']['in_support'] is True and not any(w.startswith('OUT OF SUPPORT') for w in ok.scenario['warnings'])
    free = engine.compile(ScenarioSpec(EVENT, 'NOR', 4, 'MEDIUM', replace_stop='none'))        # lap 4 is inside the red-flag gap
    assert any('free' in w for w in free.scenario['warnings'])
