"""Visual and interaction release gate (task 0.17) as a pytest module.

Skips unless the Orb v2 server answers on ORB_BASE (default http://localhost:8502). Captures every demo route at
1440x900 and 1920x1080 into a temp dir, then asserts: no real console errors, no external network requests, no
horizontal overflow, cold load under 2 s, route switch under 600 ms, and screenshots within ORB_SHOT_TOL of the
golden set (default 15 % of pixels: lock regeneration by other workstreams legitimately moves numbers).
    ../.venv/bin/python -m pytest tests/screenshots -q
"""
from __future__ import annotations
import os, sys, tempfile, urllib.request
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
BASE = os.environ.get('ORB_BASE', 'http://localhost:8502')
TOL = float(os.environ.get('ORB_SHOT_TOL', '0.15'))


def _server_up() -> bool:
    try:
        with urllib.request.urlopen(BASE + '/_stcore/health', timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _server_up(), reason=f'no Orb v2 server on {BASE}; start it with streamlit run app_v2/streamlit_app.py --server.port 8502')


@pytest.fixture(scope='module')
def report():
    import capture
    out = Path(tempfile.mkdtemp(prefix='orb_shots_'))
    return capture.run(BASE, out, compare=True)


def test_no_console_errors(report):
    errs = [(n, vp, e) for n, r in report['routes'].items() for vp, v in r.items() for e in v['console_errors']]
    assert not errs, errs


def test_replay_run_clean(report):
    for k, v in report['timings'].items():
        if k.startswith('replay_run'):
            assert not v['console_errors'], (k, v['console_errors'])
            assert 'Lap' in v['header_after_6s']


def test_offline(report):
    assert report['external_requests'] == [], report['external_requests']


def test_no_horizontal_overflow(report):
    over = [(n, vp) for n, r in report['routes'].items() for vp, v in r.items() if v['horizontal_overflow']]
    assert not over, over


def test_cold_load_under_2s(report):
    slow = {f'{n}@{vp}': v['load_ms'] for n, r in report['routes'].items() for vp, v in r.items() if v['load_ms'] > 2000}
    assert not slow, slow


def test_route_switch_under_600ms(report):
    slow = {k: v for k, v in report['timings'].items() if k.startswith('route_switch') and v > 600}
    assert not slow, slow


def test_golden_screenshots_present():
    golden = HERE / 'golden'
    import capture
    missing = [f'{n}_{vp}.png' for n, _ in capture.ROUTES for vp in capture.VIEWPORTS if not (golden / f'{n}_{vp}.png').exists()]
    assert not missing, missing


def test_visual_regression_within_tolerance(report):
    diffs = {f'{n}@{vp}': v.get('diff_vs_golden') for n, r in report['routes'].items() for vp, v in r.items()}
    bad = {k: d for k, d in diffs.items() if d is not None and d > TOL}
    assert not bad, f'changed pixels above {TOL:.0%}: {bad} (re-run capture.py --update after an intended change)'
