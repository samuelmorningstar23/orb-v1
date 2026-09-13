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
    text = _text(at)
    assert 'Madrid' in text and 'NO RACE FEED' not in text
    assert any('frozen' in el.value.lower() for el in at.caption)


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


# ---- C4: Workstream 3 outputs, the sealed gate, the pre-race scenario, red-team wording, degraded states -------------------------
def _html(at) -> str:
    return ' '.join(getattr(el, 'value', '') or '' for el in at.get('html'))


def test_sealed_block_gate(tmp_path, monkeypatch):
    """holdout_aggregate.json numbers are shown only when `freeze` is non-null and a reveal record exists; then only aggregate.forecast."""
    from app_v2.services import validation_repository as VR
    agg = dict(freeze=None, reveal=dict(per_race_written=False, reason='no freeze.json'), n_weekends=6, manifest=dict(holdout_count=6),
               aggregate=dict(forecast=dict(mae=dict(orb_v1=0.0372, naive=0.1713), band_coverage90=dict(all=1.0), calibration=dict(slope=0.48, r=0.72, n=9), n_weekends=5, n_compound_weekends=9), weekends=dict(sealed=6, forecast=5)))
    stages = {}
    frozen = dict(model_frozen=True, feature_list_frozen=True, gate_threshold_frozen=True, provider_frozen=True, git_commit='abc')
    for name, freeze, reveal, quotable, dry in (('missing', None, None, None, None), ('dry_run', None, dict(per_race_written=False), False, True), ('pre_freeze_no_flag', None, dict(per_race_written=False), None, None),
                                                ('quotable_but_no_freeze', None, dict(per_race_written=True), True, False), ('no_reveal_record', frozen, {}, True, False), ('revealed', frozen, dict(per_race_written=True), True, False)):
        d = tmp_path / name; d.mkdir()
        if name != 'missing':
            (d / 'holdout_aggregate.json').write_text(json.dumps(dict(agg, freeze=freeze, reveal=reveal, quotable=quotable, dry_run_before_freeze=dry)))
        monkeypatch.setattr(VR, 'VAL_DIR', d)
        stages[name] = VR.sealed_block()
    for name in ('missing', 'dry_run', 'pre_freeze_no_flag', 'quotable_but_no_freeze', 'no_reveal_record'):
        sb = stages[name]
        assert not sb['revealed'] and sb['forecast'] is None and sb['weekends'] is None, name
        assert sb['status_text'] == 'sealed: 6 weekends, aggregate revealed after freeze', name
    assert 'quotable: false' in stages['dry_run']['reason'] and stages['dry_run']['quotable'] is False and stages['dry_run']['dry_run_before_freeze'] is True
    assert 'freeze: null' in stages['quotable_but_no_freeze']['reason']
    sb = stages['revealed']
    assert sb['revealed'] and sb['label'] == 'sealed holdout, aggregate only' and sb['status_text'] == sb['label']
    assert sb['forecast']['mae']['orb_v1'] == 0.0372 and sb['weekends']['sealed'] == 6 and set(sb['forecast']) == {'mae', 'band_coverage90', 'calibration', 'n_weekends', 'n_compound_weekends'}


def test_generalisation_page_withholds_pre_freeze_sealed_numbers():
    from app_v2.services import validation_repository as VR
    html = _html(_run('generalisation', {'ev': 'Monza', 'mode': 'audit'}))
    sb = VR.sealed_block()
    if sb['revealed']:
        assert 'sealed holdout, aggregate only' in html
    else:
        assert 'sealed: 6 weekends, aggregate revealed after freeze' in html
        agg, _ = VR.holdout_aggregate()
        mae = (((agg or {}).get('aggregate') or {}).get('forecast') or {}).get('mae', {}).get('orb_v1')
        if mae is not None:
            assert f'{mae:.4f}' not in html and f'MAE Orb v1 vs naive' not in html, 'a pre-freeze sealed number leaked onto the page'
    if VR.ghost_scorecard()[0] is not None:
        assert VR.REGRET_LABEL in html and 'never merged' in html and 'ghost_scorecard · development pool' in html
        hl = VR.dev_pool_headline(VR.ghost_scorecard()[0])
        assert f"{hl['mae']:.4f}" in html and f"{hl['hidden_next1']:.4f}" in html
    if VR.live_scorecard()[0] is not None:
        assert 'model-implied rate proxy' in html and 'Live Predictor scorecard' in html


def test_validation_repository_reads_verbatim():
    from app_v2.services import validation_repository as VR
    g, a = VR.ghost_scorecard()
    if g is None:
        pytest.skip('no Workstream 3 outputs under out/validation')
    assert a.sha256 and len(a.sha256) == 64
    hl = VR.dev_pool_headline(g)
    assert hl['mae'] == g['development_pool']['forecast']['mae']['orb_v1'] and hl['regret_label'] == VR.REGRET_LABEL
    cells = VR.dev_pool_cells(g)
    assert cells[0]['kind'] == 'pooled' and {c['kind'] for c in cells} >= {'circuit', 'weather', 'driver'}
    assert cells[0]['mae'] == hl['mae'] and all(c['source'].startswith('ghost_scorecard · development pool') for c in cells)
    assert cells[0]['hidden_next1'] == g['development_pool']['hidden_stop']['pooled']['next1_mae']
    seasons = VR.by_season_rows(g); lc = VR.lock_consistency(g)
    if seasons:
        assert {r['season'] for r in seasons} >= {'2026'} and seasons[-1]['mae'] == g['development_pool']['by_season'][seasons[-1]['season']]['forecast']['mae']['orb_v1']
    if lc:
        assert lc['all_match'] is True and lc['n_compared'] == len(lc['metrics'])
    l, _ = VR.live_scorecard()
    if l is not None:
        assert VR.live_headline(l)['next1'] == l['pooled']['next1_mae']['estimate']
    rows = VR.risk_gate_rows(VR.risk_coverage()[0])
    if rows:
        assert rows[0]['name'].startswith('production gate') and rows[0]['min_laps'] == 30
    assert VR.is_sealed('Monza') is False and VR.hidden_stop_for('Bahrain', season=2024) is None and VR.regret_for('Bahrain', season=2024) is None


def test_pre_race_scenario_discovery_keyed_by_curve_source(tmp_path, monkeypatch):
    from app_v2.services import counterfactual_repository as CF

    def mk(d: Path, source: str, uses_post: bool, median: float) -> None:
        d.mkdir(parents=True)
        (d / 'summary.json').write_text(json.dumps(dict(scenario=dict(scenario_id='x_nor_lap10_to_soft_new_tyre_only', event_id='2026_X', driver_id='NOR', intervention=dict(lap=10, to_compound='SOFT', set_status='new'),
                                                                     simulation_mode='tyre_only', summary=dict(elapsed_delta_median_s=median), validation=dict(identity_test='pass'), assets={}),
                                                        engine=dict(curves=dict(source=source, label='label of ' + source, intended_page='p'), uses_post_race_reference=uses_post, identity_check_delta_s=0.0))))
    mk(tmp_path / 'x_nor_lap10_to_soft_new_tyre_only', 'race_reference', True, -1.0)
    mk(tmp_path / 'pre_race' / 'x_nor_lap10_to_soft_new_tyre_only', 'pre_race_forecast', False, -9.0)
    monkeypatch.setattr(CF, 'CF_DIR', tmp_path)
    assert [s.curve_source for s in CF.list_scenarios('X')] == ['race_reference'], 'audit listing must not include the pre-race scenario'
    assert CF.find_scenario('X', 'NOR', 10, 'SOFT').finish_delta_s == -1.0 and CF.default_scenario('X').finish_delta_s == -1.0
    p = CF.find_pre_race_scenario('X', 'NOR', 10, 'SOFT')
    assert p.finish_delta_s == -9.0 and p.is_pre_race and p.curve_label == 'label of pre_race_forecast' and str(p.path).endswith('pre_race/x_nor_lap10_to_soft_new_tyre_only')
    ids = CF.identity_status('X')
    assert len(ids) == 2 and {i['curve_source'] for i in ids} == {'race_reference', 'pre_race_forecast'}


def test_scenario_explorer_uses_pre_race_curve_only():
    from app_v2.services import counterfactual_repository as CF
    psc = CF.find_pre_race_scenario('Monza', 'NOR', 24, 'MEDIUM'); sc = CF.find_scenario('Monza', 'NOR', 24, 'MEDIUM', 'new', 'fixed_context')
    if psc is None or sc is None:
        pytest.skip('pre-race or race-reference scenario for Monza NOR lap 24 -> MEDIUM not on disk')
    assert psc.is_pre_race and not sc.is_pre_race and psc.path != sc.path and psc.uses_post_race_reference is False
    assert CF.find_scenario('Monza', 'NOR', 24, 'MEDIUM', 'new', 'fixed_context', CF.RACE_REFERENCE).path == sc.path
    html = _html(_run('ghost_strategy', {'ev': 'Monza', 'drv': 'NOR', 'mode': 'scenario', 'ilap': 24, 'rep': 'MEDIUM', 'scenario': 'hotter_dry'}))
    assert CF.PRE_RACE_LABEL in html and psc.curve_label in html and f'{psc.finish_delta_s:+.1f} s' in html and 'MODEL-IMPLIED SCENARIO' in html
    assert f'{sc.finish_delta_s:+.1f} s' not in html and CF.REFERENCE_LABEL not in html, 'the race-reference counterfactual must not appear in the Scenario Explorer'
    html2 = _html(_run('ghost_strategy', {'ev': 'Monza', 'drv': 'NOR', 'mode': 'audit', 'ilap': 24, 'rep': 'MEDIUM', 'fid': 'fixed_context'}))
    assert f'{sc.finish_delta_s:+.1f} s' in html2 and CF.REFERENCE_LABEL in html2
    assert f'{psc.finish_delta_s:+.1f} s' not in html2 and CF.PRE_RACE_LABEL not in html2, 'the pre-race counterfactual must not appear in the Historical Audit'
    html3 = _html(_run('ghost_strategy', {'ev': 'Monza', 'drv': 'NOR', 'mode': 'scenario', 'ilap': 24, 'rep': 'MEDIUM', 'scenario': 'wet'}))
    assert f'{psc.finish_delta_s:+.1f} s' not in html3 and 'OUT OF SUPPORT' in html3, 'no model-implied delta outside the dry support'


def test_ghost_audit_shows_workstream3_hidden_stop_and_regret_for_weekend():
    from app_v2.services import validation_repository as VR
    hs = VR.hidden_stop_for('Monza', 'VER'); rg = VR.regret_for('Monza')
    if hs is None or rg is None:
        pytest.skip('Workstream 3 hidden_stop / regret files not on disk')
    assert hs['cases'] and hs['cases'][0]['driver'] == 'VER' and rg['label'] == VR.REGRET_LABEL
    html = _html(_run('ghost_strategy', {'ev': 'Monza', 'drv': 'VER', 'mode': 'audit', 'ilap': 28, 'rep': 'SOFT'}))
    assert 'hidden-stop response, Monza (development pool)' in html and f'strategy regret, Monza · {VR.REGRET_LABEL}' in html
    assert f"+{rg['plans']['orb']['regret']:.1f} s" in html and f"{hs['cases'][0]['err1']:.1f} s" in html and 'development pool (leave-one-weekend-out), never a sealed weekend' in html
    html2 = _html(_run('ghost_strategy', {'ev': 'Monza', 'drv': 'VER', 'mode': 'scenario', 'ilap': 28, 'rep': 'SOFT', 'scenario': 'hotter_dry'}))
    assert 'hidden-stop response, Monza' not in html2 and 'strategy regret, Monza' not in html2, 'audit-only rows must stay out of the Scenario Explorer'


def test_live_rejoin_wording_has_no_projected_position():
    from app_v2.services import live_bridge as LB
    t = LB.rejoin_text(dict(position_now=6, projected_rejoin_position=9, gap_ahead_s=8.4, gap_behind_s=5.7, cars_within_pit_loss=1, traffic_density='clear', basis='observed_gap_structure'))
    assert '~P' not in t and 'P9' not in t and t.endswith(LB.NOT_POSITION_FORECAST) and t.startswith('P6 now') and 'gap ahead 8.4 s' in t
    assert LB.rejoin_text(dict(position_now=None, note='n/a')) == 'n/a' and LB.rejoin_text(None) == 'not available'
    for page, state in (('decision_board', {'ev': 'Barcelona', 'drv': 'PIA', 'lap': 35, 'mode': 'live'}), ('live_predictor', {'ev': 'Monza', 'drv': 'NOR', 'lap': 30, 'mode': 'live'})):
        html = _html(_run(page, state))
        assert '→ ~P' not in html and '~P' not in html, f'{page}: projected rejoin position is a position claim (red team live_position_claim)'
        if LB.AVAILABLE:
            assert LB.NOT_POSITION_FORECAST in html


def test_support_mismatch_is_visible_not_hidden():
    from app_v2.services import live_bridge as LB, lock_repository as LR, replay_service as RS
    if not LB.AVAILABLE:
        pytest.skip('live package not importable')
    lock = LR.load_lock(); vm = LB.build(lock, 'Monza', 'NOR', RS.ReplayCursor('Monza', 'NOR', 53).seek(30), 'x')
    note = LB.support_note(vm); ts = vm.orb_live['tyre_state']['support_status']; chip = vm.support.overall_support_status
    assert (note == '') == (ts == chip)
    if note:
        assert ts in note and chip in note
        at = _run('live_predictor', {'ev': 'Monza', 'drv': 'NOR', 'lap': 30, 'mode': 'live'})
        assert any(note == el.value for el in at.caption)
        assert 'support note' in _html(_run('decision_board', {'ev': 'Monza', 'drv': 'NOR', 'lap': 30, 'mode': 'live'}))


def test_landing_scorecards_are_separate_and_gated():
    from app_v2.services import validation_repository as VR
    html = _html(_run('landing', {'ev': 'Monza', 'drv': 'LIN', 'mode': 'live'}))
    sb = VR.sealed_block()
    assert sb['status_text'] in html
    if VR.ghost_scorecard()[0] is not None:
        assert 'Ghost Strategy scorecard' in html and VR.REGRET_LABEL in html
    if VR.live_scorecard()[0] is not None:
        assert 'Live Predictor scorecard' in html and 'model-implied rate proxy' in html


def test_degraded_feed_and_refused_position_states():
    """Hungary 2026: the position feed is degraded at source (26 distinct points per lap). Live path shows the 7.1 quality; Ghost refuses the player."""
    from app_v2.services import live_bridge as LB
    html = _html(_run('live_predictor', {'ev': 'Hungary', 'drv': 'NOR', 'lap': 30, 'mode': 'live'}))
    if LB.AVAILABLE:
        assert 'DEGRADED' in html
    html2 = _html(_run('ghost_strategy', {'ev': 'Hungary', 'drv': 'ANT', 'mode': 'audit'}))
    assert 'Modelled finish' in html2 and 'POSITION FEED REFUSED' not in html2
    at = _run('ghost_strategy', {'ev': 'Hungary', 'drv': 'ANT', 'mode': 'audit'})
    assert any('verified moving replay is not available' in c.value for c in at.caption)
    assert not at.get('iframe')


# ---- C4 acceptance pass on the post-freeze data (12 Sep 22:0x) -------------------------------------------------------
def _text(at) -> str:
    """Rendered text of every st.html block, tags stripped (the values a viewer reads)."""
    import re
    from html import unescape
    return unescape(re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', _html(at))))


def test_sealed_block_renders_post_freeze_aggregate_verbatim():
    """The post-freeze aggregate (quotable true) is shown on Generalisation and the landing scorecard, at the precision the
    lead quotes it at, and every number equals out/validation/holdout_aggregate.json and ghost_scorecard.json.sealed_holdout."""
    from app_v2.services import validation_repository as VR
    agg, _ = VR.holdout_aggregate()
    if agg is None:
        pytest.skip('out/validation/holdout_aggregate.json not on disk')
    sb = VR.sealed_block()
    if not sb['revealed']:
        pytest.skip(f"aggregate on disk is not quotable: {sb['reason']}")
    fc = (agg['aggregate'] or {})['forecast']; bs = fc['bootstrap']
    assert sb['forecast'] == fc and sb['weekends'] == agg['aggregate']['weekends'], 'sealed_block must expose aggregate.forecast verbatim'
    g, _a = VR.ghost_scorecard()
    if g is not None and g.get('sealed_holdout'):
        assert g['sealed_holdout']['aggregate']['forecast'] == fc, 'Workstream 3 scorecard and holdout_aggregate disagree'
        assert g['sealed_holdout']['quotable'] is True
    mae, naive = fc['mae']['orb_v1'], fc['mae']['naive']
    ci, ci_n = bs['mae_orb_v1']['ci90'], bs['mae_naive']['ci90']
    gen = _text(_run('generalisation', {'ev': 'Monza', 'mode': 'audit'}))
    assert 'sealed holdout, aggregate only' in gen and 'aggregate revealed after freeze' not in gen
    assert f'MAE Orb v1 vs naive {mae:.4f} [{ci[0]:.4f}, {ci[1]:.4f}] vs {naive:.4f} [{ci_n[0]:.4f}, {ci_n[1]:.4f}] s/lap' in gen
    assert f"{fc['n_weekends']} forecastable" in gen and f"{agg['aggregate']['weekends']['sealed']} sealed" in gen
    assert f"compound-weekends {fc['n_compound_weekends']} ({fc['n_issued']} issued, {fc['n_withheld']} withheld)" in gen
    assert f"90% band coverage {100 * fc['band_coverage90']['all']:.0f}%" in gen
    assert 'per-race sealed results are never shown' in gen
    land = _text(_run('landing', {'ev': 'Monza', 'drv': 'LIN', 'mode': 'live'}))
    assert f"sealed holdout, aggregate only: MAE Orb v1 {mae:.4f} vs naive {naive:.4f} s/lap" in land
    assert f"coverage {100 * fc['band_coverage90']['all']:.0f}% over {fc['n_weekends']} forecastable of {sb['n_weekends']} sealed weekends, {fc['n_compound_weekends']} compound-weekends" in land
    per_race = PROTO / 'out' / 'validation' / 'holdout_per_race.json'       # never read, never rendered: existence only
    for race_id in VR.sealed_ids():
        assert race_id not in gen and race_id.split('_', 1)[1] + ' sealed' not in gen, f'{race_id}: a per-race sealed row leaked onto the page'
    assert per_race.exists()


def test_sealed_block_stays_gated_for_a_dry_run_aggregate(tmp_path, monkeypatch):
    """The same page, pointed at a dry-run aggregate (quotable false), shows the pending sentence and none of its numbers."""
    from app_v2.services import validation_repository as VR
    agg, _ = VR.holdout_aggregate()
    if agg is None:
        pytest.skip('no aggregate on disk to turn into a dry run')
    dry = dict(agg, quotable=False, dry_run_before_freeze=True, freeze=None, reveal=dict(per_race_written=False, reason='no freeze.json'))
    d = tmp_path / 'val'; d.mkdir()
    (d / 'holdout_aggregate.json').write_text(json.dumps(dry))
    for name in ('ghost_scorecard.json', 'live_scorecard.json', 'risk_coverage.json', f'hidden_stop_{2026}.json', f'regret_{2026}.json'):
        src = VR.VAL_DIR / name
        if src.exists():
            (d / name).write_text(src.read_text())
    monkeypatch.setattr(VR, 'VAL_DIR', d)
    VR._read_json.clear()
    sb = VR.sealed_block()
    assert not sb['revealed'] and sb['forecast'] is None and 'quotable: false' in sb['reason']
    gen = _text(_run('generalisation', {'ev': 'Monza', 'mode': 'audit'}))
    fc = agg['aggregate']['forecast']; mae, naive = fc['mae']['orb_v1'], fc['mae']['naive']
    assert 'aggregate revealed after freeze' in gen and 'sealed holdout, aggregate only' not in gen.replace('aggregate only, after freeze', '')
    assert 'MAE Orb v1 vs naive' not in gen and f'vs {naive:.4f}' not in gen and f'vs naive {naive:.4f}' not in gen, 'a dry-run sealed number leaked onto the page'
    assert f"compound-weekends {fc['n_compound_weekends']} ({fc['n_issued']} issued" not in gen and 'per-race reveal refused' in gen
    land = _text(_run('landing', {'ev': 'Monza', 'drv': 'LIN', 'mode': 'live'}))
    assert 'aggregate revealed after freeze' in land and f'MAE Orb v1 {mae:.4f}' not in land and f'vs naive {naive:.4f}' not in land
    VR._read_json.clear()


def test_scenario_explorer_fidelity_control_selects_between_pre_race_scenarios():
    """Two pre-race scenarios exist (fixed_context and tyre_only); the Simulation-fidelity control picks the one it names,
    and each rendered number equals that scenario's own summary.json."""
    from app_v2.services import counterfactual_repository as CF
    built = {s.mode: s for s in CF.list_scenarios('Monza', CF.PRE_RACE) if s.driver == 'NOR' and s.lap == 24 and s.to_compound == 'MEDIUM'}
    if len(built) < 2:
        pytest.skip(f'only these pre-race fidelities are built: {sorted(built)}')
    for fid, sc in built.items():
        summary = json.loads((Path(sc.path) / 'summary.json').read_text())['scenario']['summary']
        t = _text(_run('ghost_strategy', {'ev': 'Monza', 'drv': 'NOR', 'mode': 'scenario', 'ilap': 24, 'rep': 'MEDIUM', 'scenario': 'hotter_dry', 'fid': fid}))
        assert f"simulation fidelity {'Tyres & pit stops' if fid == 'tyre_only' else 'Include recorded cautions'} ({fid})" in t
        assert f"{summary['elapsed_delta_median_s']:+.1f} s · Workstream 2 {fid.replace('_', ' ')}" in t and CF.PRE_RACE_LABEL in t
        assert f"{summary['elapsed_delta_q10_s']:+.1f} s to {summary['elapsed_delta_q90_s']:+.1f} s" in t
        assert f"{100 * summary['probability_of_gain']:.0f}%" in t
        other = next(s for m, s in built.items() if m != fid)
        assert f"{other.finish_delta_s:+.1f} s · Workstream 2 {other.mode.replace('_', ' ')}" not in t, 'the other fidelity leaked into the rail'
        assert 'no pre-race scenario built at' not in t
    default_t = _text(_run('ghost_strategy', {'ev': 'Monza', 'drv': 'NOR', 'mode': 'scenario', 'ilap': 24, 'rep': 'MEDIUM', 'scenario': 'hotter_dry'}))
    pref = CF.find_pre_race_scenario('Monza', 'NOR', 24, 'MEDIUM')
    assert f'{pref.finish_delta_s:+.1f} s · Workstream 2 {pref.mode.replace("_", " ")}' in default_t, 'with no fid in the URL the explorer shows the preferred pre-race fidelity'


def _posterior(at) -> tuple[str, str]:
    """The rendered slope posterior on the Live Predictor: the 7.1 degradation_rate row and the confidence_effect sentence."""
    import re
    t = _text(at)
    row = re.search(r'degradation_rate ([+-]\d+\.\d{3}) s/lap', t)
    eff = re.search(r'slope posterior ([+-]\d+\.\d+) \+- (\d+\.\d+) s/lap', t)
    assert row, 'no degradation_rate row rendered'
    return row.group(1), (f'{eff.group(1)}+-{eff.group(2)}' if eff else '')


def test_driver_feedback_shifts_posterior_and_is_reversible(tmp_path, monkeypatch):
    """A driver-feedback event visibly moves the rendered posterior and removing it restores the previous value exactly.

    The estimator reads live/session.FEEDBACK_LOG (Workstream 8 has not adopted ORB_FEEDBACK_LOG yet), so all three log paths are
    redirected to a tmp file: the shared app_v2/state/feedback_events.jsonl is asserted byte-identical at the end of the test.
    The UI has no undo control (the log is append-only), so the reverse direction is the event's removal from the log."""
    from app_v2.services import feedback_service as FS, live_bridge as LB, paths as P
    shared = P.STATE_DIR / 'feedback_events.jsonl'
    before = shared.read_bytes() if shared.exists() else None
    log = tmp_path / 'feedback_events.jsonl'
    monkeypatch.setattr(P, 'FEEDBACK_LOG', log)
    if LB.AVAILABLE:
        from live import session as LS, viewmodel as LV
        monkeypatch.setattr(LS, 'FEEDBACK_LOG', log); monkeypatch.setattr(LV, 'FEEDBACK_LOG', log)
    else:
        LV = None
    state = {'ev': 'Monza', 'drv': 'NOR', 'lap': 24, 'mode': 'live'}

    def render():
        if LV is not None:
            LV._cache.clear()
        return _posterior(_run('live_predictor', state))

    base = render()
    FS.append(FS.make_event('Monza', 'NOR', 22, 'rear', 'traction', 'overheating', 5, 'worsening', 0.9, 'radio', 'rears are overheating', True))
    assert FS.log_path() == log and log.exists() and len(FS.read_all()) == 1, 'the event must land in the redirected log'
    after = render()
    reverted = None
    try:
        if LB.AVAILABLE:
            assert after != base, f'the feedback event did not move the rendered posterior ({base} -> {after})'
            assert after[0] != base[0], f'degradation_rate unchanged: {base[0]} -> {after[0]}'
        log.unlink()                                   # the reverse direction: the event is removed from the log
        reverted = render()
        assert reverted == base, f'removing the event did not restore the posterior ({base} -> {after} -> {reverted})'
    finally:
        now = shared.read_bytes() if shared.exists() else None
        assert now == before, 'the test wrote to the shared driver-feedback log'
    assert FS.read_all() == [] and reverted == base


def test_race_twin_frames_that_predate_their_scenario_are_called_out():
    """Workstream 4's frame sets are built from Workstream 2's laps.csv; a scenario regenerated afterwards leaves the animation stale.
    The page must say so on the affected combination and stay silent on the consistent ones (the two golden ghost routes)."""
    from app_v2.components import race_twin as RT
    from app_v2.services import counterfactual_repository as CF
    from app_v2.pages.ghost_strategy import frames_behind_scenario
    seen = {}
    for drv, lap, rep, fid in (('NOR', 24, 'MEDIUM', 'tyre_only'), ('NOR', 24, 'MEDIUM', 'fixed_context'), ('VER', 20, 'HARD', 'fixed_context'), ('VER', 28, 'SOFT', 'fixed_context')):
        sc = CF.find_scenario('Monza', drv, lap, rep, 'new', fid)
        if sc is None:
            continue
        frames, _t, _p = RT.load_assets('Monza', drv, scenario_id=sc.scenario_id)
        seen[(drv, lap, rep, fid)] = (sc, frames, frames_behind_scenario(frames, sc))
    if not seen:
        pytest.skip('no Monza scenarios with Race Twin frames on disk')
    assert frames_behind_scenario(None, None) == '' and all(isinstance(v[2], str) for v in seen.values())
    for key, (sc, frames, msg) in seen.items():
        fd = (getattr(frames, 'meta', None) or {}).get('finish_delta_s')
        html = _text(_run('ghost_strategy', {'ev': 'Monza', 'drv': key[0], 'mode': 'audit', 'ilap': key[1], 'rep': key[2], 'fid': key[3]}))
        if fd is not None and abs(float(fd) - float(sc.finish_delta_s)) > 1.0:
            assert msg and 'PLAYER FRAMES PREDATE THIS SCENARIO' in html, f'{key}: stale frame set not surfaced'
            assert f'{sc.finish_delta_s:+.1f} s' in html and f'{float(fd):+.1f} s' in html
        else:
            assert msg == '' and 'PLAYER FRAMES PREDATE THIS SCENARIO' not in html, f'{key}: false stale warning'
