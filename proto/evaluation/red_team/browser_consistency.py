"""Actual DOM numeric audit at both C5 viewport sizes; unavailable dashboard is a failure."""
from __future__ import annotations

import ast
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
              'ghost_strategy': 'ghost', 'generalisation': 'generalisation', 'validation': 'validation', 'guided_demo': 'demo'}
MARKERS = {'pre_race': 'prerace', 'live_predictor': 'live', 'decision_board': 'decision',
           'driver_feedback': 'feedback', 'ghost_strategy': 'ghost', 'guided_demo':'demo'}


def browser_routes():
    """Original fifteen numeric cases plus every screenshot acceptance case."""
    cases = [(name, module, state, '/' + PAGE_PATHS[module] + '?' + urlencode(state))
             for name, module, state in ROUTES]
    capture_path = PROTO / 'tests/screenshots/capture.py'
    tree = ast.parse(capture_path.read_text())
    declaration = next((node for node in tree.body if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == 'ROUTES' for target in node.targets)), None)
    if declaration is None:
        raise ValueError('capture.py must declare the acceptance ROUTES inventory')
    capture_routes = ast.literal_eval(declaration.value)
    inverse = {v: k for k, v in PAGE_PATHS.items()}
    for name, path in capture_routes:
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


def navigate(page, base, path, module):
    """Use the app's navigation after root bootstrap; preserve every case query parameter."""
    parsed=urlparse(path)
    page.goto(base.rstrip('/')+'/' + ('?'+parsed.query if parsed.query else ''),wait_until='domcontentloaded')
    page.wait_for_selector('[data-orb-ready="landing"]',state='attached',timeout=60000)
    titles={'pre_race':'Forecast','live_predictor':'Live Predictor','decision_board':'Decision board',
            'driver_feedback':'Driver feedback','ghost_strategy':'Ghost Strategy','generalisation':'Generalisation','validation':'Validation','guided_demo':'Guided demo'}
    if module!='landing':
        link=page.get_by_role('link',name=titles[module],exact=True).first
        if not link.is_visible():
            page.get_by_text('More tools',exact=True).click()
        link.click()
        page.wait_for_selector(f'[data-orb-ready="{MARKERS.get(module,module)}"]',state='attached',timeout=60000)
        if module == 'guided_demo':
            state={k:v[0] for k,v in parse_qs(parsed.query).items()}
            case=state.get('_demo_case','monza_nor')
            label={'monza_nor':'Norris · Monza','monza_ver':'Verstappen · Monza','austria_ver':'Verstappen · Austria'}[case]
            page.get_by_role('radio',name=label,exact=True).check()
            page.wait_for_selector(f'[data-orb-demo-ready="{case}:0"]',state='attached',timeout=30000)
            for step in range(int(state.get('_demo_step',0))):
                page.get_by_role('button',name='Next →',exact=True).click()
                page.wait_for_selector(f'[data-orb-demo-ready="{case}:{step+1}"]',state='attached',timeout=30000)



def network_guard():
    spec=importlib.util.spec_from_file_location('orb_numeric_network_guard',PROTO/'tests/screenshots/network_guard.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def run(base='http://localhost:8502', routes=None, out=REPORT_PATH):
    rep = dict(generated_at=now_iso(), base=base, engine='Chromium actual DOM', viewports=VIEWPORTS,
               routes=[], exit_code=2, error=None, raw_console_errors=[], raw_network_failures=[], external_requests=[])
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
        guard=network_guard()
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for viewport, (width, height) in VIEWPORTS.items():
                context = browser.new_context(viewport=dict(width=width, height=height), device_scale_factor=1, service_workers='block')
                active=guard.bucket('initial',viewport)
                guard.install(context,base,rep['external_requests'],lambda:active)
                for name, module, state, path in cases:
                    rec = dict(route=name, page=module, state=state, viewport=viewport, path=path,
                               status='ok', numbers=0, matched={}, ambiguous=[], placeholders=[],
                               unclassified=[], unhashed_live=[], mismatches=[], error=None, notes=[])
                    active=guard.bucket(name,viewport);rec['network']=active
                    rec['console_errors']=[];rec['network_failures']=[]
                    page = context.new_page()
                    def console_error(message):
                        item=dict(route=name,viewport=viewport,text=message)
                        rec['console_errors'].append(item);rep['raw_console_errors'].append(item)
                    def response_error(response):
                        if response.status>=400:
                            item=dict(route=name,viewport=viewport,url=response.url,status=response.status)
                            rec['network_failures'].append(item);rep['raw_network_failures'].append(item)
                    page.on('console',lambda message:console_error(message.text) if message.type=='error' else None)
                    page.on('pageerror',lambda error:console_error(str(error)))
                    page.on('response',response_error)
                    try:
                        navigate(page,base,path,module)
                        # Open all audit rails, so below-fold/expanded evidence is checked too.
                        for detail in page.locator('details').all():
                            if detail.is_visible() and detail.get_attribute('open') is None:
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
                            if module == 'guided_demo' and int(state.get('_demo_step',0)) == 0:
                                rec['nonnumeric_intro'] = True
                            else:
                                raise RuntimeError('no numeric product evidence found')
                    except Exception as error:
                        rec.update(status='load_failure', error=f'{type(error).__name__}: {error}')
                    finally:
                        page.close()
                    if rec['console_errors'] or rec['network_failures'] or active['external_requests']:
                        rec.update(status='load_failure',error='raw browser console/network/external request failure')
                    rep['routes'].append(rec)
                context.close()
            browser.close()
        rep['summary'] = dict(routes=len(cases), viewport_route_checks=len(rep['routes']),
                              numbers=sum(r['numbers'] for r in rep['routes']),
                              mismatches=sum(len(r['mismatches']) for r in rep['routes']),
                              load_failures=sum(r['status'] == 'load_failure' for r in rep['routes']),
                              console_errors=len(rep['raw_console_errors']),network_failures=len(rep['raw_network_failures']),external_requests=len(rep['external_requests']))
        summary = rep['summary']
        rep['exit_code'] = 2 if any(summary[k] for k in ('load_failures','console_errors','network_failures','external_requests')) else (1 if summary['mismatches'] else 0)
    except Exception as error:
        rep['error'] = f'{type(error).__name__}: {error}'
    if out:
        write_json(out, rep)
    return rep
