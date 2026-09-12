"""Data cutoff on the live path (roadmap v5 task 0.0; Phase 0 acceptance 4 'Live cannot read post-race reference fields').

The Live Predictor, decision board and driver-feedback pages build their view model through
app_v2/services/live_bridge.build (the only call site). Here that exact code path runs at cursor lap K behind two spies:
a ReplayCursor subclass that records every lap it is asked for, and the leakage audit's FeedProxy around Workstream 8's
LapFeed. Nothing may request or receive a lap beyond K, and forecast.observed / observed_se / err / n_race must be None.
Self-tests: the unstripped view model does carry the race-derived reference (so the None assertion is load-bearing) and
an injected read of lap K+1 is caught."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from rt_helpers import EVENT, DRIVER, LAP, PROTO

LIVE_PAGES = ('app_v2/pages/live_predictor.py', 'app_v2/pages/decision_board.py', 'app_v2/pages/driver_feedback.py')
LIVE_PATH_MODULES = LIVE_PAGES + ('app_v2/services/live_bridge.py', 'live/viewmodel.py', 'live/session.py', 'live/estimator.py', 'decision/optimizer.py')
REFERENCE_FIELD_RE = re.compile(r'\.(observed|observed_se|err|n_race|covered)\b|\[\s*[\'"](obs|obs_se|err_cs|err_naive|n_race|cost_under_truth_vs_best_s|best_under_truth)[\'"]\s*\]')


class CursorSpy:
    """Wraps the pages' ReplayCursor: records the lap every accessor is asked for and the last lap it returned."""

    def __init__(self, cursor):
        self._c = cursor
        self.requested: list[tuple[str, int]] = []
        self.returned_max: list[tuple[str, int]] = []

    def __getattr__(self, name):
        attr = getattr(self._c, name)
        if name in ('visible', 'lap_row', 'others_visible'):
            def wrapped(lap=None):
                k = self._c.lap if lap is None else int(lap)
                self.requested.append((name, k))
                out = attr(lap)
                if isinstance(out, pd.DataFrame) and not out.empty:
                    self.returned_max.append((name, int(out['LapNumber'].max())))
                elif isinstance(out, pd.Series):
                    self.returned_max.append((name, int(out['LapNumber'])))
                return out
            return wrapped
        return attr


def _build_with_spies(monkeypatch, inject: bool = False):
    from app_v2.services import lock_repository as LR, replay_service as RS, live_bridge as LB
    from evaluation.red_team.leakage_audit import FeedProxy
    from live import session as LS
    from live.lapfeed import LapFeed, FutureDataError
    if not LB.AVAILABLE:
        pytest.skip('live package not importable: the bridge would return the labelled placeholder')
    proxies = []

    def feed_factory(*a, **kw):
        p = FeedProxy(LapFeed(*a, **kw), inject=inject)
        p.cursor = LAP
        proxies.append(p)
        return p

    monkeypatch.setattr(LS, 'LapFeed', feed_factory)
    lock = LR.load_lock()
    spy = CursorSpy(RS.ReplayCursor(EVENT, DRIVER, lock.n_laps(EVENT)).seek(LAP))
    try:
        vm = LB.build(lock, EVENT, DRIVER, spy, 'replay')
    except FutureDataError as e:
        if not inject:
            raise
        vm = e                      # the estimator's own guard refused the injected row: also a catch
    assert proxies, 'the bridge did not open a LiveSession through live.session.LapFeed (spy not attached)'
    return vm, spy, proxies


def test_live_view_model_never_reads_beyond_cursor(fresh_live_cache, race_csv, monkeypatch):
    vm, spy, proxies = _build_with_spies(monkeypatch)
    over = [(n, k) for n, k in spy.requested if k > LAP] + [(n, k) for n, k in spy.returned_max if k > LAP]
    assert spy.requested and not over, f'ReplayCursor asked for or returned a lap beyond {LAP}: {over}'
    feed_violations = [v for p in proxies for v in p.violations]
    assert not feed_violations, f'LapFeed access beyond lap {LAP}: {feed_violations[:5]}'
    calls = [c for p in proxies for c in p.calls]
    assert calls and max(k for _, _, k in calls) <= LAP, f'feed calls beyond the cursor: {sorted(set(calls))[-3:]}'
    assert vm.lap == LAP and (vm.state is None or vm.state.lap == LAP)
    assert all(k <= LAP for k, _ in vm.temp_series), 'track temperature series runs beyond the cursor'
    assert all(d.lap <= LAP for d in vm.history), 'decision history runs beyond the cursor'
    assert all(int(r.get('lap', 0)) <= LAP for r in vm.feedback), 'driver feedback from a later lap reached the view model'
    orb = vm.orb_live
    assert orb is not None and orb['uses_future_data'] is False and orb['uses_post_race_reference'] is False
    assert orb['tyre_state']['lap'] == LAP


def test_forecast_reference_fields_are_none_on_the_live_path(fresh_live_cache, race_csv, monkeypatch):
    vm, _, _ = _build_with_spies(monkeypatch)
    f = vm.forecast
    assert (f.observed, f.observed_se, f.err, f.n_race) == (None, None, None, None), f'race-derived reference on the live path: {f}'
    assert f.prediction is not None and f.source.startswith('lock'), 'the frozen forecast itself must still be there'


def test_unstripped_view_model_would_carry_the_reference(fresh_live_cache, race_csv, monkeypatch):
    """Self-test: without the bridge's scrub the reference is present for a scored weekend, so the None check is load-bearing."""
    from app_v2.services import live_bridge as LB
    monkeypatch.setattr(LB, '_strip_post_race', lambda vm: vm)
    vm, _, _ = _build_with_spies(monkeypatch)
    f = vm.forecast
    assert f.observed is not None and f.n_race, f'expected the race-derived reference to leak when the scrub is disabled; got {f}'


def test_spy_catches_a_read_of_lap_k_plus_1(fresh_live_cache, race_csv, monkeypatch):
    """Self-test: FeedProxy(inject=True) hands the session row k+1 while producing lap k. Two guards may catch it: the
    estimator's own timestamp check (live/estimator.py raises FutureDataError) or the proxy's cursor check; either is loud."""
    from live.lapfeed import FutureDataError
    vm, _, proxies = _build_with_spies(monkeypatch, inject=True)
    feed_violations = [v for p in proxies for v in p.violations]
    caught_by_estimator = isinstance(vm, FutureDataError)
    caught_by_proxy = any('requested while producing lap' in v or 'returned LapNumber' in v for v in feed_violations)
    assert caught_by_estimator or caught_by_proxy, f'an injected read of lap k+1 went unnoticed: violations={feed_violations[:3]}, result={type(vm).__name__}'


def test_only_the_bridge_builds_the_live_view_model():
    """Every live page calls services/live_bridge.build; no page or state module calls the raw builders."""
    pages_calling_bridge = []
    for rel in LIVE_PAGES:
        src = (PROTO / rel).read_text(encoding='utf-8')
        assert 'LB.build(' in src or 'live_bridge.build(' in src, f'{rel} does not build its view model through the bridge'
        pages_calling_bridge.append(rel)
    offenders = []
    for f in sorted((PROTO / 'app_v2').rglob('*.py')):
        rel = f.relative_to(PROTO).as_posix()
        if rel == 'app_v2/services/live_bridge.py':
            continue
        text = f.read_text(encoding='utf-8')
        for m in re.finditer(r'(VM\.build_live\(|build_live_vm\(|\bbuild_live\()', text):
            line = text[:m.start()].count('\n') + 1
            if not re.match(r'\s*def build_live', text.splitlines()[line - 1]):
                offenders.append(f'{rel}:{line} {m.group(0)}')
    assert not offenders, f'raw live builders called outside the bridge: {offenders}'
    assert len(pages_calling_bridge) == 3


def test_no_live_module_reads_reference_fields():
    """Static: nothing on the live path dereferences observed / err / n_race / covered or a post-race lock key."""
    hits = []
    for rel in LIVE_PATH_MODULES:
        p = PROTO / rel
        if not p.exists():
            continue
        for i, line in enumerate(p.read_text(encoding='utf-8').splitlines(), 1):
            if 'POST_RACE_FIELDS' in line or 'observed=None' in line or line.lstrip().startswith(('#', '"""', '-')):
                continue
            if REFERENCE_FIELD_RE.search(line):
                hits.append(f'{rel}:{i}: {line.strip()[:120]}')
    assert not hits, 'live-path module reads a race-derived reference field:\n  ' + '\n  '.join(hits)


def test_reference_scanner_sees_the_ghost_page():
    """Self-test: the Ghost Strategy audit renders the race-derived reference on purpose; the scanner must find it there."""
    src = (PROTO / 'app_v2/pages/ghost_strategy.py').read_text(encoding='utf-8')
    assert any(REFERENCE_FIELD_RE.search(l) for l in src.splitlines()), 'scanner regex no longer matches the reference fields'


def test_private_frame_is_not_touched_outside_replay_service():
    offenders = [f.relative_to(PROTO).as_posix() for f in (PROTO / 'app_v2').rglob('*.py') if '._df' in f.read_text(encoding='utf-8') and f.name != 'replay_service.py']
    offenders += [f.relative_to(PROTO).as_posix() for f in (PROTO / 'live').rglob('*.py') if 'cursor._df' in f.read_text(encoding='utf-8')]
    assert not offenders, f'the cursor\'s private race frame is read directly (bypasses visible(k)): {offenders}'
