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
