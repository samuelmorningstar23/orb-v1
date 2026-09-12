"""Golden screenshots, console-error audit, offline audit and timing for the Orb v1 shell (tasks 0.14 / 0.17).

Usage (server must be running on --base):
    ../.venv/bin/streamlit run app_v2/streamlit_app.py --server.port 8502 --server.headless true
    ../.venv/bin/python tests/screenshots/capture.py --update          # (re)write golden PNGs + report.json
    ../.venv/bin/python tests/screenshots/capture.py --compare         # capture to a temp dir, diff against golden

Every non-localhost request is aborted and recorded: the demo must be offline. Browser console errors and page
errors are recorded per route. Cold load = navigation start to the page's [data-orb-ready] marker; route switch =
top-nav click to the next page's marker.
"""
from __future__ import annotations
import argparse, json, shutil, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROTO = HERE.parents[1]
GOLDEN = HERE / 'golden'
VIEWPORTS = {'1440x900': (1440, 900), '1920x1080': (1920, 1080)}
FEEDBACK_MARKER = 'screenshot fixture (capture.py)'

ROUTES = [
    ('landing', '/?ev=Monza&drv=LIN'),
    ('live_stable', '/live?ev=Monza&drv=LIN&lap=30&mode=live'),
    ('live_after_feedback', '/live?ev=Monza&drv=LIN&lap=32&mode=live'),
    ('decision_change', '/live?ev=Barcelona&drv=PIA&lap=61&mode=live'),
    ('decision_board', '/decision?ev=Barcelona&drv=PIA&lap=61&mode=live'),
    ('ghost_audit', '/ghost?ev=Monza&drv=NOR&mode=audit&ilap=20&rep=SOFT'),
    ('scenario_explorer', '/ghost?ev=Monza&drv=NOR&mode=scenario&scenario=hotter_dry&ilap=20&rep=SOFT'),
    ('out_of_support', '/ghost?ev=Monza&drv=NOR&mode=scenario&scenario=wet&ilap=20&rep=SOFT'),
    ('missing_position', '/ghost?ev=Australia&drv=ANT&mode=audit'),
    ('offline_mode', '/live?ev=Madrid&mode=live'),
    ('presentation_live', '/live?ev=Monza&drv=LIN&lap=30&mode=live&present=1'),
    ('presentation_ghost', '/ghost?ev=Monza&drv=NOR&mode=audit&ilap=20&rep=SOFT&present=1'),
    ('prerace', '/pre-race?ev=Madrid'),
    ('feedback', '/feedback?ev=Monza&drv=LIN&lap=32'),
    ('generalisation', '/generalisation?ev=Monza'),
    ('validation', '/validation?ev=Monza'),
]


def add_feedback_fixture() -> Path:
    sys.path.insert(0, str(PROTO))
    from app_v2.services import feedback_service as FS
    e = FS.make_event('Monza', 'LIN', 31, 'rear', 'traction', 'lack_of_grip', 4, 'worsening', 0.8, 'radio', FEEDBACK_MARKER, True)
    return FS.append(e)


def remove_feedback_fixture(path: Path) -> None:
    if not path.exists():
        return
    lines = [l for l in path.read_text().splitlines() if FEEDBACK_MARKER not in l]
    path.write_text(('\n'.join(lines) + '\n') if lines else '')


def diff_ratio(a: Path, b: Path) -> float | None:
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None
    ia, ib = Image.open(a).convert('RGB'), Image.open(b).convert('RGB')
    if ia.size != ib.size:
        return 1.0
    d = ImageChops.difference(ia, ib).convert('L').point(lambda v: 255 if v > 24 else 0)
    hist = d.histogram(); return hist[255] / float(ia.size[0] * ia.size[1])


def run(base: str, out: Path, compare: bool, routes=ROUTES) -> dict:
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    report = {'base': base, 'routes': {}, 'external_requests': [], 'timings': {}, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S')}
    fb_path = add_feedback_fixture()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for vp_name, (w, h) in VIEWPORTS.items():
                ctx = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1, color_scheme='dark')

                def block(route, request):
                    url = request.url
                    if url.startswith(base) or url.startswith('ws://') or url.startswith('data:') or url.startswith('blob:'):
                        route.continue_()
                    else:
                        report['external_requests'].append({'viewport': vp_name, 'url': url}); route.abort()
                ctx.route('**/*', block)
                page = ctx.new_page()
                errors: list[dict] = []; bad_responses: list[str] = []
                page.on('console', lambda msg: errors.append({'type': msg.type, 'text': msg.text}) if msg.type == 'error' else None)
                page.on('pageerror', lambda exc: errors.append({'type': 'pageerror', 'text': str(exc)}))
                page.on('response', lambda r: bad_responses.append(r.url) if r.status >= 400 else None)
                for name, path in routes:
                    errors.clear(); bad_responses.clear()
                    marker = {'landing': 'landing', 'prerace': 'prerace', 'feedback': 'feedback', 'generalisation': 'generalisation', 'validation': 'validation', 'decision_board': 'decision'}.get(name, 'ghost' if '/ghost' in path else 'live')
                    t0 = time.perf_counter()
                    page.goto(base + path, wait_until='domcontentloaded')
                    page.wait_for_selector(f'[data-orb-ready="{marker}"]', state='attached', timeout=30000)
                    load_ms = (time.perf_counter() - t0) * 1000   # navigation start -> page marker attached
                    page.wait_for_timeout(900)          # let Plotly settle and fonts paint before the screenshot
                    scroll_w = page.evaluate('document.documentElement.scrollWidth'); inner_w = page.evaluate('window.innerWidth')
                    fname = out / f'{name}_{vp_name}.png'
                    page.screenshot(path=str(fname), full_page=False)
                    entry = report['routes'].setdefault(name, {})
                    probes = [u for u in bad_responses if u.rstrip('/').endswith(('/_stcore/host-config', '/_stcore/health'))]
                    real = [e for e in errors if not (e['text'].startswith('Failed to load resource') and len(probes) >= 1 and len(bad_responses) == len(probes))]
                    entry[vp_name] = {'path': path, 'load_ms': round(load_ms), 'console_errors': real, 'benign_base_path_probes_404': probes, 'other_4xx_5xx': [u for u in bad_responses if u not in probes], 'horizontal_overflow': bool(scroll_w > inner_w), 'scroll_width': scroll_w, 'inner_width': inner_w}
                    if compare:
                        g = GOLDEN / fname.name
                        entry[vp_name]['diff_vs_golden'] = diff_ratio(fname, g) if g.exists() else None
                # route switch timing: landing -> Live Predictor via the top navigation (assets cached)
                page.goto(base + '/?ev=Monza&drv=LIN', wait_until='domcontentloaded'); page.wait_for_selector('[data-orb-ready="landing"]', state='attached')
                page.wait_for_timeout(500)
                link = page.get_by_role('link', name='Live Predictor').first
                t0 = time.perf_counter(); link.click(); page.wait_for_selector('[data-orb-ready="live"]', state='attached', timeout=30000)
                report['timings'][f'route_switch_ms_{vp_name}'] = round((time.perf_counter() - t0) * 1000)
                t0 = time.perf_counter(); page.get_by_role('link', name='Validation').first.click(); page.wait_for_selector('[data-orb-ready="validation"]', state='attached', timeout=30000)
                report['timings'][f'route_switch_validation_ms_{vp_name}'] = round((time.perf_counter() - t0) * 1000)
                # keyboard: tab reaches the top navigation and the first control
                page.keyboard.press('Tab'); page.keyboard.press('Tab')
                report['timings'][f'keyboard_focus_{vp_name}'] = page.evaluate('document.activeElement && (document.activeElement.tagName + ":" + (document.activeElement.textContent || "").trim().slice(0, 40))')
                # five-second replay run: no console errors while the fragment polls
                page.goto(base + '/live?ev=Monza&drv=LIN&lap=5&mode=live', wait_until='domcontentloaded'); page.wait_for_selector('[data-orb-ready="live"]', state='attached')
                page.wait_for_timeout(500); errors.clear(); bad_responses.clear()
                page.get_by_role('button', name='Start replay').first.click(); page.wait_for_timeout(6000)
                lap_text = ' '.join(page.locator('[data-orb-header]').first.inner_text().split())
                report['timings'][f'replay_run_{vp_name}'] = {'console_errors': list(errors), 'bad_responses': list(bad_responses), 'header_after_6s': lap_text[:200]}
                ctx.close()
            browser.close()
    finally:
        remove_feedback_fixture(fb_path)
    (out / 'report.json').write_text(json.dumps(report, indent=1))
    return report


def summarise(report: dict) -> str:
    lines = [f"base {report['base']} · generated {report['generated_at']}"]
    worst_load = max(v['load_ms'] for r in report['routes'].values() for v in r.values())
    lines.append(f"cold loads: worst {worst_load} ms · route switches: " + ', '.join(f'{k} {v}' for k, v in report['timings'].items() if k.startswith('route_switch')))
    errs = [(n, vp, e) for n, r in report['routes'].items() for vp, v in r.items() for e in v['console_errors']]
    lines.append(f"console errors (excluding Streamlit's benign base-path 404 probes on deep links): {len(errs)}" + (' ' + json.dumps(errs[:5]) if errs else ''))
    probes = sum(len(v.get('benign_base_path_probes_404', [])) for r in report['routes'].values() for v in r.values())
    lines.append(f'benign base-path probe 404s (Streamlit client, deep links only): {probes}')
    over = [(n, vp) for n, r in report['routes'].items() for vp, v in r.items() if v['horizontal_overflow']]
    lines.append(f"horizontal overflow: {over or 'none'}")
    lines.append(f"external requests attempted: {len(report['external_requests'])}" + (' ' + json.dumps(report['external_requests'][:5]) if report['external_requests'] else ''))
    for k, v in report['timings'].items():
        if k.startswith('replay_run'):
            lines.append(f"{k}: console errors {len(v['console_errors'])} · bad responses {len(v.get('bad_responses', []))} · {v['header_after_6s'][:120]}")
    diffs = [(n, vp, v.get('diff_vs_golden')) for n, r in report['routes'].items() for vp, v in r.items() if v.get('diff_vs_golden') is not None]
    if diffs:
        lines.append('diff vs golden (share of changed pixels): ' + ', '.join(f'{n}@{vp} {d:.3%}' for n, vp, d in diffs))
    return '\n'.join(lines)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--base', default='http://localhost:8502'); ap.add_argument('--out', default=None)
    ap.add_argument('--update', action='store_true', help='write golden PNGs'); ap.add_argument('--compare', action='store_true', help='capture to a temp dir and diff against golden')
    a = ap.parse_args()
    if a.compare:
        tmp = Path(tempfile.mkdtemp(prefix='orb_shots_')); rep = run(a.base, tmp, compare=True); print(summarise(rep)); print(f'captures in {tmp}')
    else:
        out = Path(a.out) if a.out else GOLDEN
        rep = run(a.base, out, compare=False); print(summarise(rep)); print(f'golden written to {out}')
