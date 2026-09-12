"""Actual DOM numeric audit at both C5 viewport sizes; unavailable dashboard is a failure."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

from evaluation.red_team import PROTO, RT_DIR, LOCK_V1, now_iso, read_json, write_json
from evaluation.red_team.consistency_probe import (
    ROUTES, _Extract, _label_of, build_base_references, match_surfaces, route_references,
)

REPORT_PATH = RT_DIR / 'browser_consistency_report.json'
VIEWPORTS = {'1440x900': (1440, 900), '1920x1080': (1920, 1080)}
PAGE_PATHS = {'landing': '', 'pre_race': 'pre-race', 'live_predictor': 'live',
              'decision_board': 'decision', 'driver_feedback': 'feedback',
              'ghost_strategy': 'ghost', 'generalisation': 'generalisation', 'validation': 'validation'}
MARKERS = {'pre_race': 'prerace', 'live_predictor': 'live', 'decision_board': 'decision',
           'driver_feedback': 'feedback', 'ghost_strategy': 'ghost'}


def browser_routes():
    """Original fifteen numeric cases plus every screenshot acceptance case."""
    cases = [(name, module, state, '/' + PAGE_PATHS[module] + '?' + urlencode(state))
             for name, module, state in ROUTES]
    spec = importlib.util.spec_from_file_location('orb_capture_routes', PROTO / 'tests/screenshots/capture.py')
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    inverse = {v: k for k, v in PAGE_PATHS.items()}
    for name, path in capture.ROUTES:
        parsed = urlparse(path)
        state = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        state.setdefault('mode', 'live')
        for key in ('lap', 'ilap'):
            if key in state:
                state[key] = int(state[key])
        cases.append(('acceptance/' + name, inverse[parsed.path.strip('/')], state, path))
    return cases


def dom_surfaces(page):
    # Extract semantic product text, including expanded audit details and table cells.
    # Chart axes are auto-generated from data domains; AppTest separately checks chart titles/annotations.
    rows = page.locator('[data-testid="stMain"]').evaluate("""root => {
      const selectors = '[data-testid="stHtml"], [data-testid="stMarkdownContainer"], [data-testid="stMetric"], [data-testid="stTable"]';
      return [...root.querySelectorAll(selectors)].filter(el =>
        !el.parentElement.closest(selectors) && !el.closest('[data-testid="stWidgetLabel"]')
      ).map(el => ({raw: el.innerHTML, text: el.innerText || '', kind: el.dataset.testid}));
    }""")
    surfaces = []
    for row in rows:
        p = _Extract(); p.feed(row['raw'])
        text = row['text'] or p.text
        if not text.strip():
            continue
        surfaces.append(dict(kind='browser:' + row['kind'], widget=_label_of(row['raw'], text, p.labels),
                             text=text, cells=p.cells, raw=row['raw']))
    for text in page.locator('[data-testid="stMain"] .js-plotly-plot .gtitle, [data-testid="stMain"] .js-plotly-plot .xtitle, [data-testid="stMain"] .js-plotly-plot .ytitle, [data-testid="stMain"] .js-plotly-plot .annotation-text, [data-testid="stMain"] .js-plotly-plot .legendtext').all_text_contents():
        surfaces.append(dict(kind='browser:plotly_label', widget='chart label', text=text, cells=[], raw=''))
    return surfaces


def run(base='http://localhost:8502', routes=None, out=REPORT_PATH):
    rep = dict(generated_at=now_iso(), base=base, engine='Chromium actual DOM', viewports=VIEWPORTS,
               routes=[], exit_code=2, error=None)
    try:
        with urlopen(base.rstrip('/') + '/_stcore/health', timeout=5) as response:
            if response.status != 200:
                raise RuntimeError(f'dashboard health HTTP {response.status}, expected 200')
        from playwright.sync_api import sync_playwright
        cases = [c for c in browser_routes() if routes is None or c[0] in routes or c[1] in routes]
        if not cases:
            raise ValueError('no browser routes selected')
        lock = read_json(LOCK_V1)
        values = [float(v) for _, _, state, _ in cases for k, v in state.items()
                  if k in ('lap', 'ilap') and isinstance(v, (float, int))]
        refs_base = build_base_references(lock, values)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for viewport, (width, height) in VIEWPORTS.items():
                context = browser.new_context(viewport=dict(width=width, height=height), device_scale_factor=1)
                for name, module, state, path in cases:
                    rec = dict(route=name, page=module, state=state, viewport=viewport, path=path,
                               status='ok', numbers=0, matched={}, ambiguous=[], placeholders=[],
                               unclassified=[], unhashed_live=[], mismatches=[], error=None, notes=[])
                    page = context.new_page()
                    try:
                        # Register st.navigation before resolving a deep link in a fresh browser session.
                        page.goto(base.rstrip('/') + '/?ev=Monza&drv=LIN', wait_until='domcontentloaded')
                        page.wait_for_selector('[data-orb-ready="landing"]', state='attached', timeout=60000)
                        page.goto(base.rstrip('/') + path, wait_until='domcontentloaded')
                        marker = MARKERS.get(module, module)
                        page.wait_for_selector(f'[data-orb-ready="{marker}"]', state='attached', timeout=60000)
                        # Open all audit rails, so below-fold/expanded evidence is checked too.
                        for detail in page.locator('details').all():
                            if detail.get_attribute('open') is None:
                                detail.locator('summary').click()
                        page.wait_for_timeout(300)
                        errors = page.locator('[data-testid="stException"]').all_text_contents()
                        if errors:
                            raise RuntimeError('; '.join(errors))
                        surfaces = dom_surfaces(page)
                        if not surfaces:
                            raise RuntimeError('no product DOM surfaces found')
                        rec['surfaces'] = len(surfaces)
                        match_surfaces(rec, surfaces, route_references(refs_base, lock, module, state))
                        if not rec['numbers']:
                            raise RuntimeError('no numeric product evidence found')
                    except Exception as error:
                        rec.update(status='load_failure', error=f'{type(error).__name__}: {error}')
                    finally:
                        page.close()
                    rep['routes'].append(rec)
                context.close()
            browser.close()
        rep['summary'] = dict(routes=len(cases), viewport_route_checks=len(rep['routes']),
                              numbers=sum(r['numbers'] for r in rep['routes']),
                              mismatches=sum(len(r['mismatches']) for r in rep['routes']),
                              load_failures=sum(r['status'] == 'load_failure' for r in rep['routes']))
        summary = rep['summary']
        rep['exit_code'] = 2 if summary['load_failures'] else (1 if summary['mismatches'] else 0)
    except Exception as error:
        rep['error'] = f'{type(error).__name__}: {error}'
    if out:
        write_json(out, rep)
    return rep
