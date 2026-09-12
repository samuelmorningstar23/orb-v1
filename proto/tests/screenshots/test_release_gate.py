"""Fail-closed instrumentation regression tests; no server/browser required."""
from copy import deepcopy
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import pytest
import capture
import release_gate
from network_guard import is_local_url


@pytest.mark.parametrize('url', ['http://localhost:8502.evil.invalid/x', 'http://localhost:85020/x', 'http://localhost:8502@evil.invalid/x',
                                'http://evil.invalid:8502/x', 'ws://evil.invalid/x', 'wss://localhost:8502/x', 'http://localhost:8503/x'])
def test_network_guard_rejects_external_and_prefix_tricks(url):
    assert not is_local_url('http://localhost:8502', url)


@pytest.mark.parametrize('url', ['http://localhost:8502/static/a.js', 'ws://localhost:8502/_stcore/stream', 'blob:http://localhost:8502/local', 'data:image/png;base64,AA'])
def test_network_guard_permits_app_origin_and_browser_local_resources(url):
    assert is_local_url('http://localhost:8502', url)


def fixture():
    row = dict(console_errors=[], benign_base_path_probes_404=[], other_4xx_5xx=[], horizontal_overflow=False, load_ms=100, expected_text_missing=[],
               offline_notice_visible=True, network=dict(external_requests=[], local_request_count=1, websockets=['ws://localhost:8502/_stcore/stream']), diff_vs_golden=0, sidebar_visible=True)
    raw = dict(base='http://localhost:8502', raw_console_errors=[], raw_network_failures=[], external_requests=[], routes={name:{vp:deepcopy(row) for vp in capture.VIEWPORTS} for name,_ in capture.ROUTES}, timings={})
    for name in ('presentation_live','presentation_ghost'):
        for vp in capture.VIEWPORTS:
            raw['routes'][name][vp]['sidebar_visible']=False
    for vp in capture.VIEWPORTS:
        raw['timings'].update({f'route_switch_ms_{vp}':100,f'route_switch_validation_ms_{vp}':100,
                              f'keyboard_nav_{vp}':dict(reached=capture.NAV_TITLES,missing=[],enter_activates=True,tabs=10,activations=[dict(target=t,activated=True,switch_ms=100) for t in capture.NAV_TITLES]),
                              f'replay_run_{vp}':dict(console_errors=[],bad_responses=[],header_after_6s='Lap 10/53')})
    return raw


def failed(raw):
    return {check['name'] for check in release_gate.evaluate(raw) if check['status']=='FAIL'}


def test_complete_fixture_passes_all_gates():
    assert not failed(fixture())


def test_missing_viewport_or_golden_never_silently_passes():
    raw=fixture();del raw['routes']['landing']['1440x900']
    assert 'complete_route_matrix' in failed(raw)
    raw=fixture();raw['routes']['landing']['1440x900']['diff_vs_golden']=None
    assert 'landing@1440x900:golden' in failed(raw)


def test_network_and_offline_notice_are_required_per_route():
    raw=fixture();row=raw['routes']['offline_mode']['1440x900'];row['network']['websockets']=['ws://external.invalid/x'];row['offline_notice_visible']=False
    assert {'offline_mode@1440x900:network','offline_mode@1440x900:offline_notice'}<=failed(raw)


def test_timing_limits_not_rounded_or_relaxed():
    raw=fixture();raw['timings']['route_switch_validation_ms_1920x1080']=601;raw['routes']['landing']['1440x900']['load_ms']=2001
    assert {'route_switch_validation_ms_1920x1080','landing@1440x900:cold_load'}<=failed(raw)


def test_real_keyboard_activation_and_refusal_labels_are_required():
    raw=fixture();raw['timings']['keyboard_nav_1440x900']['enter_activates']=False;raw['routes']['degraded_feed']['1920x1080']['expected_text_missing']=['DEGRADED']
    assert {'keyboard_1440x900','degraded_feed@1920x1080:refusal_labels'}<=failed(raw)


def test_unavailable_dashboard_writes_failure_report_not_skip(tmp_path, monkeypatch):
    import json
    def unavailable(*args, **kwargs):
        raise OSError('synthetic unavailable dashboard')
    monkeypatch.setattr(release_gate.urllib.request, 'urlopen', unavailable)
    report=tmp_path/'release.json'
    assert release_gate.main(['--base','http://localhost:8502','--out',str(tmp_path/'capture'),'--report',str(report)])==1
    data=json.loads(report.read_text())
    assert data['status']=='FAIL' and data['capture'] is None
    assert data['failures'][0]['name']=='execution'


def test_each_keyboard_destination_must_activate_within_existing_budget():
    raw=fixture();raw['timings']['keyboard_nav_1920x1080']['activations'][0]['activated']=False
    assert 'keyboard_all_destinations_1920x1080' in failed(raw)


def test_no_probe_or_raw_error_allowlist():
    raw=fixture();raw['routes']['live_stable']['1440x900']['benign_base_path_probes_404']=['http://localhost:8502/live/_stcore/health']
    raw['raw_console_errors']=[{'text':'Failed to load resource'}]
    raw['raw_network_failures']=[{'url':'http://localhost:8502/live/_stcore/health','status':404}]
    assert {'live_stable@1440x900:responses','raw_console_errors','raw_network_failures'} <= failed(raw)


def test_missing_raw_error_evidence_fails_closed():
    raw=fixture();del raw['raw_console_errors'];del raw['raw_network_failures']
    assert {'raw_console_errors','raw_network_failures'} <= failed(raw)
