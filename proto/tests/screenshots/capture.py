"""Golden screenshots, console-error audit, offline audit and timing for the Orb v1 shell (tasks 0.14 / 0.17).

Usage (server must be running on --base):
    ../.venv/bin/streamlit run app_v2/streamlit_app.py --server.port 8502 --server.headless true
    ../.venv/bin/python tests/screenshots/capture.py --update          # (re)write golden PNGs + report.json
    ../.venv/bin/python tests/screenshots/capture.py --compare         # capture to a temp dir, diff against golden

Every non-localhost request is aborted and recorded: the demo must be offline. Browser console errors and page
errors are recorded per route. The capture never writes the shared driver-feedback log (app_v2/state/feedback_events.jsonl). Cold load = navigation start to the page's [data-orb-ready] marker; route switch =
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
    ('live_stable', '/live?ev=Monza&drv=NOR&lap=30&mode=live'),
    ('live_after_feedback', '/live?ev=Monza&drv=NOR&lap=32&mode=live'),      # feedback rows only from the server's own log (never a written fixture)
    ('decision_change', '/live?ev=Barcelona&drv=PIA&lap=35&mode=live'),
    ('decision_board', '/decision?ev=Barcelona&drv=PIA&lap=35&mode=live'),
    ('ghost_audit', '/ghost?ev=Monza&drv=NOR&mode=audit&ilap=24&rep=MEDIUM'),
    ('ghost_audit_fixed_context', '/ghost?ev=Monza&drv=VER&mode=audit&ilap=28&rep=SOFT'),
    ('scenario_explorer', '/ghost?ev=Monza&drv=NOR&mode=scenario&scenario=hotter_dry&ilap=24&rep=MEDIUM'),
    ('out_of_support', '/ghost?ev=Monza&drv=NOR&mode=scenario&scenario=wet&ilap=24&rep=MEDIUM'),
    ('missing_position', '/ghost?ev=Australia&drv=ANT&mode=audit'),
    ('offline_mode', '/live?ev=Madrid&mode=live'),
    ('presentation_live', '/live?ev=Monza&drv=NOR&lap=30&mode=live&present=1'),
    ('presentation_ghost', '/ghost?ev=Monza&drv=NOR&mode=audit&ilap=24&rep=MEDIUM&present=1'),
    ('prerace', '/pre-race?ev=Madrid'),
    ('feedback', '/feedback?ev=Monza&drv=NOR&lap=32'),
    ('generalisation', '/generalisation?ev=Monza'),
    ('validation', '/validation?ev=Monza'),
    ('degraded_feed', '/live?ev=Hungary&drv=NOR&lap=30&mode=live'),
    ('position_refused', '/ghost?ev=Hungary&drv=NOR&mode=audit'),
]
NAV_TITLES = ['Landing', 'Pre-race plan', 'Live Predictor', 'Decision board', 'Driver feedback', 'Ghost Strategy', 'Generalisation', 'Validation']
# designed degraded / labelled states every route must show (13.6 failure modes, 0.17 release gate); a tuple = any of these
EXPECTED_TEXT = {
    'offline_mode': ['NO RACE FEED'], 'out_of_support': ['OUT OF SUPPORT', 'MODEL-IMPLIED SCENARIO'], 'missing_position': ['POSITION DATA UNAVAILABLE'],
    'degraded_feed': ['DEGRADED'], 'position_refused': ['POSITION FEED REFUSED'], 'scenario_explorer': ['MODEL-IMPLIED SCENARIO', 'model-implied, pre-race curve'],
    'ghost_audit': ['HISTORICAL AUDIT', 'leave-one-driver-out Sunday reference', 'held-out strategy replay under a post-race reference model'],
    'generalisation': [('aggregate revealed after freeze', 'sealed holdout, aggregate only'), 'never merged'], 'validation': ['identity test'], 'landing': ['Ghost Strategy scorecard', 'Live Predictor scorecard'],
    'decision_board': ['not a position forecast'], 'live_stable': ['not a position forecast'], 'presentation_live': [], 'presentation_ghost': [],
}


def write_feedback_fixture(path: Path) -> Path:
    """A labelled driver-feedback fixture row for a *separate* log file. The capture never writes the shared
    app_v2/state/feedback_events.jsonl (Workstream 3's scorecards read it: a fixture row there would trigger the ablation).
    To capture the after-feedback routes with the row active, start the server with ORB_FEEDBACK_LOG=<that file>
    (honoured by app_v2/services/paths.py; live/session.py reads its own hard-coded path until Workstream 8 honours it too)."""
    sys.path.insert(0, str(PROTO))
    from app_v2.services import feedback_service as FS
    e = FS.make_event('Monza', 'NOR', 31, 'rear', 'traction', 'lack_of_grip', 4, 'worsening', 0.8, 'radio', FEEDBACK_MARKER, True)
    return FS.append(e, path)


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


FOCUS_JS = """() => { const a = document.activeElement; if (!a) return null; const link = a.closest('a'); const btn = a.closest('button');
  const nav = !!(link && (link.closest('[data-testid=\"stTopNav\"]') || link.closest('header') || link.closest('nav')));
  return {tag: a.tagName, text: (a.textContent || '').trim().slice(0, 40), is_nav: nav, is_button: !!btn}; }"""


def keyboard_nav(page, base: str, max_tabs: int = 60) -> dict:
    """Tab through the top navigation from the landing page: every route title must be reachable by keyboard (an overflow
    'More' menu is opened with Enter), and Enter on a focused link must switch the route."""
    page.goto(base + '/?ev=Monza&drv=LIN', wait_until='domcontentloaded'); page.wait_for_selector('[data-orb-ready="landing"]', state='attached'); page.wait_for_timeout(400)
    page.evaluate('document.activeElement && document.activeElement.blur && document.activeElement.blur()')
    reached, tabs = [], 0
    for _ in range(max_tabs):
        page.keyboard.press('Tab'); tabs += 1
        info = page.evaluate(FOCUS_JS)
        if not info:
            continue
        if info['is_button'] and 'More' in info['text']:
            page.keyboard.press('Enter'); page.wait_for_timeout(200)
            continue
        if info['is_nav'] and info['text'] in NAV_TITLES and info['text'] not in reached:
            reached.append(info['text'])
        if len(reached) == len(NAV_TITLES):
            break
    # second pass: Enter on a focused nav link activates the route
    page.goto(base + '/?ev=Monza&drv=LIN', wait_until='domcontentloaded'); page.wait_for_selector('[data-orb-ready="landing"]', state='attached'); page.wait_for_timeout(400)
    page.evaluate('document.activeElement && document.activeElement.blur && document.activeElement.blur()')
    activated, enter_ms = False, None
    for _ in range(max_tabs):
        page.keyboard.press('Tab')
        info = page.evaluate(FOCUS_JS)
        if info and info['is_button'] and 'More' in info['text']:
            page.keyboard.press('Enter'); page.wait_for_timeout(200); continue
        if info and info['is_nav'] and info['text'] == 'Generalisation':
            t0 = time.perf_counter(); page.keyboard.press('Enter')
            try:
                page.wait_for_selector('[data-orb-ready="generalisation"]', state='attached', timeout=15000); activated = True; enter_ms = round((time.perf_counter() - t0) * 1000)
            except Exception:
                activated = False
            break
    return {'reached': reached, 'missing': [t for t in NAV_TITLES if t not in reached], 'tabs': tabs, 'enter_activates': activated, 'enter_switch_ms': enter_ms}


def scripted_pass(base: str, speed: int = 1, viewport=(1440, 900)) -> dict:
    """Task 0.17 scripted demo pass: replay Monza NOR through the Live Predictor from lap 1 to the flag at `speed`x, then
    Ghost Strategy (NOR lap 24 -> new MEDIUM, the default scenario) via the top navigation, then Validation, then
    Generalisation. Records per-step timings, lap progression, console errors and external requests; writes
    tests/screenshots/golden/scripted_pass.json. About five minutes at 1x including the reading pauses."""
    import re
    from playwright.sync_api import sync_playwright
    rep = {'base': base, 'speed': speed, 'viewport': f'{viewport[0]}x{viewport[1]}', 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'steps': [], 'external_requests': [], 'feedback_fixture': 'none (shared log never written)'}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(); ctx = browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]}, device_scale_factor=1, color_scheme='dark')

            def block(route, request):
                url = request.url
                if url.startswith(base) or url.startswith('ws://') or url.startswith('data:') or url.startswith('blob:'):
                    route.continue_()
                else:
                    rep['external_requests'].append(url); route.abort()
            ctx.route('**/*', block)
            page = ctx.new_page(); errors: list[dict] = []
            page.on('console', lambda msg: errors.append({'type': msg.type, 'text': msg.text}) if msg.type == 'error' and not msg.text.startswith('Failed to load resource') else None)
            page.on('pageerror', lambda exc: errors.append({'type': 'pageerror', 'text': str(exc)}))
            header = lambda: ' '.join(page.locator('[data-orb-header]').first.inner_text().split())
            t_all = time.perf_counter()
            # 1. Live Predictor: replay Monza NOR from lap 1 to the flag
            t0 = time.perf_counter(); page.goto(base + '/live?ev=Monza&drv=NOR&lap=1&mode=live', wait_until='domcontentloaded'); page.wait_for_selector('[data-orb-ready="live"]', state='attached', timeout=30000)
            load_ms = round((time.perf_counter() - t0) * 1000); page.wait_for_timeout(600)
            if speed != 1:
                page.get_by_role('radio', name=f'{speed}x').first.click(); page.wait_for_timeout(300)
            page.get_by_role('button', name='Start replay').first.click()
            t1 = time.perf_counter(); samples = []; lap = n = None; deadline = t1 + 60.0 / max(speed, 1) + 45
            while time.perf_counter() < deadline:
                page.wait_for_timeout(1000)
                m = re.search(r'Lap (\d+)/(\d+)', header())
                lap, n = (int(m.group(1)), int(m.group(2))) if m else (None, None)
                samples.append([round(time.perf_counter() - t1, 1), lap])
                if lap and n and lap >= n:
                    break
            replay_s = round(time.perf_counter() - t1, 1)
            body = page.inner_text('body').lower()
            rep['steps'].append({'step': 'live_replay_monza_nor', 'load_ms': load_ms, 'replay_wall_s': replay_s, 'laps_reached': f'{lap}/{n}', 'samples_every_5s': samples[::5], 'final_header': header()[:160],
                                 'rejoin_wording_ok': 'not a position forecast' in body, 'console_errors': list(errors)}); errors.clear()
            # 2. Ghost Strategy via the top navigation (NOR lap 24 -> new MEDIUM is the default scenario for Monza NOR)
            t0 = time.perf_counter(); page.get_by_role('link', name='Ghost Strategy').first.click(); page.wait_for_selector('[data-orb-ready="ghost"]', state='attached', timeout=30000); ms = round((time.perf_counter() - t0) * 1000)
            page.wait_for_timeout(1200); body = page.inner_text('body').lower()
            rep['steps'].append({'step': 'ghost_strategy_nor_lap24_medium', 'switch_ms': ms, 'player_iframes': page.locator('iframe').count(), 'audit_banner': 'historical audit' in body, 'reference_label': 'leave-one-driver-out sunday reference' in body,
                                 'workstream3_rows': 'held-out strategy replay under a post-race reference model' in body, 'header': header()[:160], 'console_errors': list(errors)}); errors.clear()
            # 3. Validation
            t0 = time.perf_counter(); page.get_by_role('link', name='Validation').first.click(); page.wait_for_selector('[data-orb-ready="validation"]', state='attached', timeout=30000); ms = round((time.perf_counter() - t0) * 1000)
            page.wait_for_timeout(800); body = page.inner_text('body').lower()
            rep['steps'].append({'step': 'validation', 'switch_ms': ms, 'prefix_eval': 'prior' in body, 'regret_table': 'orb v1 (pre-race slopes)' in body, 'console_errors': list(errors)}); errors.clear()
            # 4. Generalisation
            t0 = time.perf_counter(); page.get_by_role('link', name='Generalisation').first.click(); page.wait_for_selector('[data-orb-ready="generalisation"]', state='attached', timeout=30000); ms = round((time.perf_counter() - t0) * 1000)
            page.wait_for_timeout(800); body = page.inner_text('body').lower()
            rep['steps'].append({'step': 'generalisation', 'switch_ms': ms, 'sealed_gate_text': 'aggregate revealed after freeze' in body or 'sealed holdout, aggregate only' in body, 'cells': 'development pool' in body, 'console_errors': list(errors)}); errors.clear()
            rep['total_wall_s'] = round(time.perf_counter() - t_all, 1)
            browser.close()
    finally:
        pass
    (GOLDEN / 'scripted_pass.json').write_text(json.dumps(rep, indent=1))
    return rep


def run(base: str, out: Path, compare: bool, routes=ROUTES) -> dict:
    from playwright.sync_api import sync_playwright
    out.mkdir(parents=True, exist_ok=True)
    report = {'base': base, 'routes': {}, 'external_requests': [], 'timings': {}, 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
              'feedback_fixture': 'none: the capture never writes app_v2/state/feedback_events.jsonl (use ORB_FEEDBACK_LOG on the server for a fixture log)'}
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
                    body_text = page.inner_text('body').lower()          # inner_text carries CSS text-transform (labels are uppercase)
                    missing_text = [t if isinstance(t, str) else ' | '.join(t) for t in EXPECTED_TEXT.get(name, []) if not any(x.lower() in body_text for x in ((t,) if isinstance(t, str) else t))]
                    sidebar_visible = page.locator('[data-testid="stSidebar"]').first.is_visible() if page.locator('[data-testid="stSidebar"]').count() else False
                    entry[vp_name] = {'path': path, 'load_ms': round(load_ms), 'console_errors': real, 'benign_base_path_probes_404': probes, 'other_4xx_5xx': [u for u in bad_responses if u not in probes], 'horizontal_overflow': bool(scroll_w > inner_w), 'scroll_width': scroll_w, 'inner_width': inner_w,
                                      'expected_text_missing': missing_text, 'sidebar_visible': sidebar_visible}
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
                report['timings'][f'keyboard_nav_{vp_name}'] = keyboard_nav(page, base)
                # five-second replay run: no console errors while the fragment polls
                page.goto(base + '/live?ev=Monza&drv=NOR&lap=5&mode=live', wait_until='domcontentloaded'); page.wait_for_selector('[data-orb-ready="live"]', state='attached')
                page.wait_for_timeout(500); errors.clear(); bad_responses.clear()
                page.get_by_role('button', name='Start replay').first.click(); page.wait_for_timeout(6000)
                lap_text = ' '.join(page.locator('[data-orb-header]').first.inner_text().split())
                report['timings'][f'replay_run_{vp_name}'] = {'console_errors': list(errors), 'bad_responses': list(bad_responses), 'header_after_6s': lap_text[:200]}
                ctx.close()
            browser.close()
    finally:
        pass
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
    ap.add_argument('--routes', default=None, help='comma-separated route names (default: all); with --update only those goldens are rewritten and the report is merged')
    ap.add_argument('--scripted', action='store_true', help='run the task 0.17 scripted pass (live replay, ghost, validation, generalisation) and write golden/scripted_pass.json')
    ap.add_argument('--speed', type=int, default=1, help='replay speed for --scripted (1, 2, 5, 10)')
    a = ap.parse_args()
    if a.scripted:
        rep = scripted_pass(a.base, a.speed)
        print(json.dumps({k: v for k, v in rep.items() if k != 'steps'}, indent=1))
        for st in rep['steps']:
            print(json.dumps(st))
        sys.exit(0)
    routes = [r for r in ROUTES if r[0] in a.routes.split(',')] if a.routes else ROUTES
    if a.compare:
        tmp = Path(tempfile.mkdtemp(prefix='orb_shots_')); rep = run(a.base, tmp, compare=True, routes=routes); print(summarise(rep)); print(f'captures in {tmp}')
    else:
        out = Path(a.out) if a.out else GOLDEN
        previous = json.loads((GOLDEN / 'report.json').read_text()) if (a.routes and out == GOLDEN and (GOLDEN / 'report.json').exists()) else None   # read before run() rewrites it
        rep = run(a.base, out, compare=False, routes=routes)
        if previous is not None:
            previous['routes'].update(rep['routes']); previous['timings'].update(rep['timings']); previous['external_requests'] = rep['external_requests']; previous['generated_at'] = rep['generated_at']; previous['base'] = rep['base']
            rep = previous; (GOLDEN / 'report.json').write_text(json.dumps(rep, indent=1))
        print(summarise(rep)); print(f'golden written to {out}')
