"""C6 durable browser release gate; nonzero exit on missing evidence or any failed check.

From proto: ../.venv/bin/python tests/screenshots/release_gate.py --base http://localhost:8502
The browser only reads the product; screenshots/reports are written below --out. No golden is updated.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
import urllib.request

import capture
from network_guard import is_local_url

LIMITS = {'cold_load_ms': 2000, 'route_switch_ms': 600, 'golden_diff_ratio': 0.15}


def evaluate(raw: dict) -> list[dict]:
    checks = []
    def check(name, passed, detail):
        checks.append({'name': name, 'status': 'PASS' if passed else 'FAIL', 'detail': detail})
    routes = raw.get('routes') or {}
    expected = {name for name, _ in capture.ROUTES}
    viewports = set(capture.VIEWPORTS)
    check('complete_route_matrix', set(routes) == expected and all(set(routes.get(n, {})) == viewports for n in expected),
          {'expected_routes': sorted(expected), 'actual_routes': sorted(routes), 'viewports': sorted(viewports)})
    check('external_requests', raw.get('external_requests') == [], raw.get('external_requests', 'missing'))
    for key in ('raw_console_errors', 'raw_network_failures'):
        check(key, raw.get(key) == [], raw.get(key, 'missing'))
    for name in sorted(expected):
        for viewport in sorted(viewports):
            row = routes.get(name, {}).get(viewport) or {}
            prefix = f'{name}@{viewport}'
            check(prefix + ':console', row.get('console_errors') == [], row.get('console_errors', 'missing'))
            check(prefix + ':responses', row.get('other_4xx_5xx') == [] and row.get('benign_base_path_probes_404') == [], row.get('other_4xx_5xx', 'missing'))
            check(prefix + ':overflow', row.get('horizontal_overflow') is False, row.get('horizontal_overflow', 'missing'))
            load = row.get('load_ms')
            check(prefix + ':cold_load', isinstance(load, (int, float)) and 0 <= load <= LIMITS['cold_load_ms'], load)
            check(prefix + ':refusal_labels', row.get('expected_text_missing') == [], row.get('expected_text_missing', 'missing'))
            check(prefix + ':offline_notice', row.get('offline_notice_visible') is True, row.get('offline_notice_visible', 'missing'))
            network = row.get('network') or {}
            check(prefix + ':network', network.get('external_requests') == [] and network.get('local_request_count', 0) > 0
                  and isinstance(network.get('websockets'), list) and all(is_local_url(raw['base'], url) for url in network.get('websockets', [])), network)
            diff = row.get('diff_vs_golden')
            check(prefix + ':golden', isinstance(diff, (int, float)) and 0 <= diff <= LIMITS['golden_diff_ratio'], diff)
            if name in ('presentation_live', 'presentation_ghost', 'live_stable', 'ghost_audit'):
                expected_sidebar = name in ('live_stable', 'ghost_audit')
                check(prefix + ':presentation', row.get('sidebar_visible') is expected_sidebar, {'expected_sidebar': expected_sidebar, 'actual': row.get('sidebar_visible')})
    timings = raw.get('timings') or {}
    for viewport in sorted(viewports):
        for prefix in ('route_switch_ms_', 'route_switch_validation_ms_'):
            value = timings.get(prefix + viewport)
            check(prefix + viewport, isinstance(value, (int, float)) and 0 <= value <= LIMITS['route_switch_ms'], value)
        keyboard = timings.get('keyboard_nav_' + viewport) or {}
        check('keyboard_' + viewport, set(keyboard.get('reached', [])) == set(capture.NAV_TITLES)
              and keyboard.get('missing') == [] and keyboard.get('enter_activates') is True
              and isinstance(keyboard.get('tabs'), int) and keyboard['tabs'] > 0, keyboard)
        activations = keyboard.get('activations') or []
        check('keyboard_all_destinations_' + viewport, {a.get('target') for a in activations} == set(capture.NAV_TITLES)
              and all(a.get('activated') is True and isinstance(a.get('switch_ms'), (int, float))
                      and 0 <= a['switch_ms'] <= LIMITS['route_switch_ms'] for a in activations), activations)
        replay = timings.get('replay_run_' + viewport) or {}
        check('replay_' + viewport, replay.get('console_errors') == [] and replay.get('bad_responses') == []
              and 'Lap' in replay.get('header_after_6s', ''), replay)
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://localhost:8502')
    parser.add_argument('--out', type=Path, default=Path(__file__).parent / 'c6_capture')
    parser.add_argument('--report', type=Path, default=Path(__file__).parent / 'c6_release_report.json')
    args = parser.parse_args(argv)
    result = {'checkpoint': 'C6', 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'base': args.base,
              'limits': LIMITS, 'expected_matrix': {'routes': len(capture.ROUTES), 'viewports': list(capture.VIEWPORTS)},
              'capture': None, 'checks': [], 'failures': [], 'status': 'FAIL'}
    try:
        with urllib.request.urlopen(args.base.rstrip('/') + '/_stcore/health', timeout=5) as response:
            if response.status != 200:
                raise RuntimeError(f'dashboard health HTTP {response.status}; browser checks cannot run')
        raw = capture.run(args.base.rstrip('/'), args.out, compare=True)
        result['capture'] = raw
        result['checks'] = evaluate(raw)
        result['failures'] = [check for check in result['checks'] if check['status'] != 'PASS']
        result['status'] = 'FAIL' if result['failures'] else 'PASS'
    except Exception as exc:
        result['failures'].append({'name': 'execution', 'status': 'FAIL', 'detail': f'{type(exc).__name__}: {exc}'})
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'checks': len(result['checks']), 'failures': result['failures'], 'report': str(args.report)}, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
