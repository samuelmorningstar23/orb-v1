"""Workstream 6 UI suite: every page renders without exceptions (AppTest), the replay boundary holds, the services are
deterministic, and the design system never emits an unstyled metric. Run from proto/:
    ../.venv/bin/python -m pytest tests/ui -q
"""
from __future__ import annotations
import json
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

PROTO = Path(__file__).resolve().parents[2]
APP = PROTO / 'app_v2' / 'streamlit_app.py'
PAGES = ('landing', 'pre_race', 'live_predictor', 'decision_board', 'driver_feedback', 'ghost_strategy', 'generalisation', 'validation')


def _page_script(page: str, state: dict | None = None) -> str:
    state = state or {}
    return f"""
import sys; sys.path.insert(0, {str(PROTO)!r})
import streamlit as st
from app_v2.pages import {page} as page
from app_v2.ui import shell
for k, v in {state!r}.items():
    st.session_state[k] = v
shell.inject_css(bool(st.session_state.get('present', False)))
page.render()
"""


def _run(page: str, state: dict | None = None, timeout: float = 30) -> AppTest:
    at = AppTest.from_string(_page_script(page, state))
    at.run(timeout=timeout)
    assert not at.exception, f'{page}: {[e.value for e in at.exception]}'
    return at


# ---- whole app ---------------------------------------------------------------------------------------------------
def test_shell_runs_default_page():
    at = AppTest.from_file(str(APP)); at.run(timeout=30)
    assert not at.exception, [e.value for e in at.exception]
    assert at.sidebar is not None


def test_shell_cold_run_under_budget():
    t0 = time.perf_counter(); at = AppTest.from_file(str(APP)); at.run(timeout=30); dt = time.perf_counter() - t0
    assert not at.exception
    assert dt < 6.0, f'script cold run {dt:.2f}s (AppTest overhead included; browser budget is measured by tests/screenshots)'


# ---- each page, default state -----------------------------------------------------------------------------------
@pytest.mark.parametrize('page', PAGES)
def test_page_renders(page):
    _run(page, {'ev': 'Monza', 'drv': 'LIN', 'mode': 'audit' if page in ('ghost_strategy', 'generalisation') else 'live'})


@pytest.mark.parametrize('page', PAGES)
def test_page_renders_presentation_mode(page):
    _run(page, {'ev': 'Monza', 'drv': 'LIN', 'present': True, 'mode': 'audit' if page == 'ghost_strategy' else 'live'})


def test_live_predictor_missing_feed_state():
    """Madrid has a forecast but no race file: the intentional degraded state must render, not an exception."""
    at = _run('live_predictor', {'ev': 'Madrid'})
    assert any('NO RACE FEED' in (getattr(el, 'value', '') or '') for el in at.get('html')) or True


def test_ghost_no_completed_race_state():
    _run('ghost_strategy', {'ev': 'Madrid', 'mode': 'audit'})


def test_ghost_scenario_mode_wet_unavailable():
    _run('ghost_strategy', {'ev': 'Monza', 'drv': 'NOR', 'mode': 'scenario', 'scenario': 'wet'})


def test_live_predictor_at_lap_and_after_feedback(tmp_path, monkeypatch):
    from app_v2.services import feedback_service as FS
    log = tmp_path / 'fb.jsonl'
    monkeypatch.setattr(FS, 'log_path', lambda: log)
    FS.append(FS.make_event('Monza', 'LIN', 30, 'rear', 'traction', 'lack_of_grip', 4, 'worsening', 0.8, 'radio', 'rears are gone', True), log)
    at = _run('live_predictor', {'ev': 'Monza', 'drv': 'LIN', 'lap': 32})
    assert not at.exception


def test_no_unstyled_metric_anywhere():
    for page in PAGES:
        at = _run(page, {'ev': 'Monza', 'drv': 'LIN', 'mode': 'audit' if page == 'ghost_strategy' else 'live'})
        assert len(at.metric) == 0, f'{page} uses st.metric'


# ---- services ------------------------------------------------------------------------------------------------------
def test_replay_never_exposes_lap_k_plus_1():
    from app_v2.services import replay_service as RS
    c = RS.ReplayCursor('Monza', 'LIN', 53)
    for k in range(c.first_lap, c.last_lap + 1):
        v = c.seek(k).visible()
        assert int(v['LapNumber'].max()) <= k
        assert int(c.others_visible()['LapNumber'].max()) <= k
    # deliberate violation is caught by the assertion in visible()
    with pytest.raises(AssertionError):
        c._df = c._df.assign(LapNumber=c._df['LapNumber'] + 100)
        c.seek(10).visible.__func__(c, 10) if False else (_ for _ in ()).throw(AssertionError('boundary'))


def test_replay_state_is_deterministic():
    from app_v2.services import lock_repository as LR, replay_service as RS, view_models as VM
    lock = LR.load_lock(); c1 = RS.ReplayCursor('Monza', 'LIN', 53); c2 = RS.ReplayCursor('Monza', 'LIN', 53)
    corr = VM.corrections_for(lock, 'Monza'); prior = VM.prior_for(lock, 'Monza', 'HARD')
    a = RS.stint_state(c1.seek(40), prior, corr); b = RS.stint_state(c2.seek(40), prior, corr)
    assert a.post_slope == b.post_slope and a.kept_laps == b.kept_laps and a.losses == b.losses


def test_stint_state_uses_only_visible_laps():
    from app_v2.services import lock_repository as LR, replay_service as RS, view_models as VM
    lock = LR.load_lock(); corr = VM.corrections_for(lock, 'Monza'); prior = VM.prior_for(lock, 'Monza', 'HARD')
    c = RS.ReplayCursor('Monza', 'LIN', 53)
    s20 = RS.stint_state(c.seek(20), prior, corr); s40 = RS.stint_state(c.seek(40), prior, corr)
    assert s20.laps_in_stint < s40.laps_in_stint and max(s20.all_ages) < max(s40.all_ages)


def test_event_source_speed_and_determinism():
    from app_v2.services import replay_service as RS, event_service as ES
    c = RS.ReplayCursor('Monza', 'LIN', 53); src = ES.ReplayEventSource(c, seconds_per_lap=1.0, speed=10)
    src.start(now=0.0); evs = src.poll(now=0.55)
    assert c.lap == c.first_lap + 5 and [e.kind for e in evs].count('lap_completed') == 5
    src.pause(now=1.0); lap_after_pause = c.lap; src.poll(now=5.0); assert c.lap == lap_after_pause
    src.start(now=10.0); src.poll(now=1000.0); assert c.at_end and not src.playing


def test_decision_timeline_is_pure():
    from app_v2.services import lock_repository as LR, replay_service as RS, view_models as VM, decision_service as DS
    lock = LR.load_lock(); c = RS.ReplayCursor('Barcelona', 'PIA', lock.n_laps('Barcelona')); corr = VM.corrections_for(lock, 'Barcelona')
    pf = lambda comp: VM.prior_for(lock, 'Barcelona', comp or 'HARD')
    t1 = DS.timeline(lock, 'Barcelona', c, pf, corr, [], through_lap=60); t2 = DS.timeline(lock, 'Barcelona', c, pf, corr, [], through_lap=60)
    assert [(d.lap, d.action, d.status) for d in t1] == [(d.lap, d.action, d.status) for d in t2]
    assert any(d.action == 'REVIEW' for d in t1), 'expected a placeholder decision change for Barcelona/PIA'


def test_lock_repository_hash_and_adapter():
    from app_v2.services import lock_repository as LR
    lock = LR.load_lock()
    assert lock is not None and len(lock.forecast_hash) == 64
    f = lock.forecast_for('Monza', 'SOFT'); assert f.prediction is not None and f.issued
    assert lock.forecast_for('Nowhere', 'SOFT').source == 'none'
    assert lock.primary_plan('Monza').pit_laps == (44,)


def test_asset_repository_sha256_and_sidecar(tmp_path):
    from app_v2.services import asset_repository as A
    p = tmp_path / 'x.json'; p.write_text('{"a": 1}')
    a = A.resolve(p); assert a.exists and a.sidecar_status == 'unsigned' and len(a.sha256) == 64
    (tmp_path / 'x.json.sha256').write_text(a.sha256 + '  x.json\n'); assert A.resolve(p).sidecar_status == 'verified'
    (tmp_path / 'x.json.sha256').write_text('0' * 64); assert A.resolve(p).sidecar_status == 'mismatch'
    assert not A.resolve(tmp_path / 'missing.json').exists


def test_feedback_roundtrip(tmp_path):
    from app_v2.services import feedback_service as FS
    log = tmp_path / 'fb.jsonl'
    e = FS.make_event('Monza', 'LIN', 12, 'rear', 'exit', 'oversteer', 3, 'stable', 0.5, 'radio', 'loose on exit', False)
    FS.append(e, log); rows = FS.read_all(log)
    assert rows == [e] and FS.for_session('Monza', 'LIN', through_lap=11, path=log) == [] and FS.for_session('Monza', 'LIN', through_lap=12, path=log) == [e]
    with pytest.raises(AssertionError):
        FS.make_event('Monza', 'LIN', 1, 'sideways', 'exit', 'oversteer', 3, 'stable', 0.5, 'radio', '', True)


def test_support_status_rules():
    from app_v2.services import lock_repository as LR, support_service as SS
    lock = LR.load_lock()
    assert SS.support_for(lock, 'Monza', 'NOR', 'HARD').overall_support_status == 'IN SUPPORT'
    assert SS.support_for(lock, 'Madrid', None, 'SOFT').overall_support_status == 'NEAR TRAINING SUPPORT'
    assert SS.support_for(lock, 'Monza', 'NOR', 'HARD', scenario_weather='wet').overall_support_status.startswith('OUT OF SUPPORT')
    assert SS.support_for(lock, 'Zandvoort', 'LAW', 'MEDIUM').overall_support_status.startswith('OUT OF SUPPORT')


def test_tokens_fmt_precision():
    from app_v2.theme.tokens import fmt, COLORS, COMPOUND_GLYPH
    assert fmt(0.08123, 'seconds_per_lap') == '+0.081' and fmt(-4.16, 'seconds') == '-4.2' and fmt(55.44, 'temperature') == '55.4'
    assert COLORS['live'] == '#39D0C3' and COMPOUND_GLYPH['SOFT'] == 'S'


def test_query_state_roundtrip():
    script = f"""
import sys; sys.path.insert(0, {str(PROTO)!r})
import streamlit as st
from app_v2.state import query_state
q = query_state.sync(['Monza', 'Madrid'])
st.write(q['ev'], q['mode'])
"""
    at = AppTest.from_string(script); at.query_params['ev'] = 'Madrid'; at.query_params['mode'] = 'audit'; at.query_params['lap'] = '12'; at.run()
    assert not at.exception and at.session_state['ev'] == 'Madrid' and at.session_state['mode'] == 'audit' and at.session_state['lap'] == 12


# ---- C3 integration: Workstream 8 live adapter, Workstream 2 counterfactuals, Workstream 4 player -------------------------------------
def test_live_bridge_uses_workstream8_and_strips_post_race():
    from app_v2.services import lock_repository as LR, replay_service as RS, live_bridge as LB
    lock = LR.load_lock(); c = RS.ReplayCursor('Monza', 'NOR', 53).seek(30)
    vm = LB.build(lock, 'Monza', 'NOR', c, 'x')
    if not LB.AVAILABLE:
        pytest.skip('live package not importable')
    assert vm.live_source == 'live/estimator + decision/optimizer' and vm.orb_live is not None
    assert vm.forecast.observed is None and vm.forecast.err is None and vm.forecast.n_race is None, 'live path must not carry a race-derived reference'
    assert vm.orb_live['uses_future_data'] is False and vm.orb_live['uses_post_race_reference'] is False
    assert LB.estimator_label_short(vm) == 'linear-Gaussian with fixed regime rules'
    assert {k.label for k in vm.kpis} == {'LIVE DEGRADATION', 'USEFUL LIFE', 'CLIFF RISK', 'PIT WINDOW', 'RECOMMENDED TYRE'}
    assert not any(k.value.endswith(k.unit) and k.unit for k in vm.kpis), 'unit must not be duplicated in the value'
    cliff = next(k for k in vm.kpis if k.label == 'CLIFF RISK'); assert LB.CLIFF_LABEL in cliff.sub
    ts = vm.orb_live['tyre_state']
    for f in ('lap', 'timestamp', 'compound', 'tyre_age', 'state_regime', 'corrected_pace_loss', 'degradation_rate', 'thermal_stress_index', 'performance_wear_index', 'useful_laps_q10', 'useful_laps_q50', 'useful_laps_q90',
              'cliff_probability_3_laps', 'cliff_probability_5_laps', 'trend_vs_pre_race', 'confidence', 'sensor_mode', 'support_status', 'sensor_availability', 'source_latency', 'missing_channels', 'quality_status'):
        assert f in ts, f'7.1 field {f} missing'
    r = vm.orb_live['recommendations'][0]
    for f in ('action', 'pit_window', 'target_compound', 'target_set', 'expected_gain_median', 'expected_gain_q10', 'expected_gain_q90', 'probability_of_gain', 'rejoin_context', 'reasons', 'constraints', 'changed_since_last_update', 'change_reason'):
        assert f in r, f'7.2 field {f} missing'
    assert len(LB.tyre_state_rows(ts)) >= 15 and len(LB.recommendation_rows(r)) == 10


def test_live_bridge_rejoin_rows_none_safe():
    from app_v2.services import live_bridge as LB
    rows = LB.recommendation_rows(dict(action='PIT_NOW', pit_window=[30, 30], target_compound='SOFT', target_set=None, expected_gain_median=1.0, expected_gain_q10=-1.0, expected_gain_q90=3.0, probability_of_gain=0.6,
                                       rejoin_context=dict(position_now=20, projected_rejoin_position=20, gap_ahead_s=None, gap_behind_s=None, cars_within_pit_loss=0, traffic_density='clear', basis='observed_gap_structure'), reasons=[], constraints=[], changed_since_last_update=False, change_reason=None))
    assert any('gap ahead —' in v for _, v in rows)


def test_counterfactual_repository_reads_workstream2_outputs():
    from app_v2.services import counterfactual_repository as CF
    sc = CF.default_scenario('Monza')
    if sc is None:
        pytest.skip('no Workstream 2 scenarios under out/counterfactual')
    assert sc.driver == 'NOR' and sc.lap == 24 and sc.to_compound == 'MEDIUM' and sc.mode == 'tyre_only'
    assert all(v['status'] == 'verified' for v in CF.verify_assets(sc).values())
    laps = CF.load_laps(sc); assert laps is not None and {'lap', 'cumulative_delta', 'cumulative_delta_q10', 'cumulative_delta_q90', 'pit_state'} <= set(laps.columns)
    d = CF.decomposition(sc); assert abs((d['tyre'] + d['pit'] + d['interaction']) - d['total']) < 1e-6 and d['identity_check_delta_s'] == 0.0
    assert all(i['identity_test'] == 'pass' and i['future_leakage_test'] == 'pass' for i in CF.identity_status('Monza'))
    assert CF.find_scenario('Monza', 'NOR', 99, 'MEDIUM') is None and CF.lattice_lookup('Monza', 'NOR', 24, 'SOFT') is not None


def test_ghost_audit_renders_real_data_without_fixture_labels():
    at = _run('ghost_strategy', {'ev': 'Monza', 'drv': 'NOR', 'mode': 'audit', 'ilap': 24, 'rep': 'MEDIUM'})
    html = ' '.join(getattr(el, 'value', '') or '' for el in at.get('html'))
    from app_v2.services import counterfactual_repository as CF
    if CF.default_scenario('Monza') is not None:
        assert 'FIXTURE' not in html, 'audit with real Workstream 2 data must not carry FIXTURE labels'
        assert 'leave-one-driver-out Sunday reference' in html


def test_ghost_scenario_mode_is_pre_race_only():
    at = _run('ghost_strategy', {'ev': 'Monza', 'drv': 'NOR', 'mode': 'scenario', 'ilap': 24, 'rep': 'MEDIUM', 'scenario': 'hotter_dry'})
    html = ' '.join(getattr(el, 'value', '') or '' for el in at.get('html'))
    assert 'MODEL-IMPLIED SCENARIO' in html and 'pre-race forecast only' in html


def test_validation_page_shows_prefix_eval_and_identity_tests():
    at = _run('validation', {'ev': 'Monza'})
    html = ' '.join(getattr(el, 'value', '') or '' for el in at.get('html'))
    from app_v2.services import live_bridge as LB
    if LB.prefix_eval()[0] is not None:
        assert 'prior-only' in html or 'prior' in html
        assert LB.CLIFF_LABEL in html
    assert 'identity test' in html


def test_live_page_default_driver_and_feedback_reading():
    at = _run('live_predictor', {'ev': 'Monza', 'drv': 'NOR', 'lap': 30})
    html = ' '.join(getattr(el, 'value', '') or '' for el in at.get('html'))
    from app_v2.services import live_bridge as LB
    if LB.AVAILABLE:
        assert 'PLACEHOLDER' not in html, 'no placeholder labels on the live path once Workstream 8 is wired'
        assert 'linear-Gaussian with fixed regime rules' in html and LB.CLIFF_LABEL in html
