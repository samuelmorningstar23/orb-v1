"""Product screenshots for the deck: capture the running dashboard (read-only browsing) and crop the panels.

    ../.venv/bin/streamlit run app_v2/streamlit_app.py --server.port 8502 --server.headless true   # already running
    ../.venv/bin/python deck_src/product_shots.py --capture     # capture raw 1920 x 2600 pages into deck_src/assets/raw/
    ../.venv/bin/python deck_src/product_shots.py               # crop only, from the raw pages already on disk

Navigation reuses tests/screenshots/capture.py goto_route (root bootstrap, then the real top navigation). Every
non-localhost request is aborted. Nothing is clicked that writes state.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
PROTO = HERE.parent
RAW = HERE / 'assets' / 'raw'
ASSETS = HERE / 'assets'
BASE = 'http://localhost:8502'
ROUTES = [
    ('landing', '/?ev=Monza&drv=LIN&present=1', 'landing'),
    ('prerace', '/pre-race?ev=Madrid&present=1', 'prerace'),
    ('live', '/live?ev=Monza&drv=NOR&lap=30&mode=live&present=1', 'live'),
    ('decision', '/decision?ev=Barcelona&drv=PIA&lap=35&mode=live', 'decision'),
    ('ghost', '/ghost?ev=Monza&drv=NOR&mode=audit&ilap=24&rep=MEDIUM&present=1', 'ghost'),
    ('demo', '/demo', 'demo'),
]
# (output name, raw page, crop box left, top, right, bottom in raw pixels)
CROPS = [
    ('shot_landing', 'landing', (20, 195, 1900, 1100)),
    ('shot_live', 'live', (20, 190, 1900, 1178)),
    ('shot_ghost', 'ghost', (20, 918, 1900, 1690)),
    ('shot_ghost_change', 'ghost', (20, 405, 1900, 680)),
    ('shot_ghost_3d', 'ghost', (40, 1262, 1880, 1622)),
    ('shot_prerace', 'prerace', (20, 255, 1900, 960)),
    ('shot_decision', 'decision', (372, 255, 1850, 735)),
    ('shot_demo', 'demo', (430, 125, 1490, 975)),
]


def advance_twin(page, lap):
    """Move the Race Twin scrubber inside its component frame to a later lap (display only; nothing is written)."""
    for fr in page.frames:
        try:
            if fr.query_selector('#orb-lapslider'):
                fr.evaluate("(lap) => { const s = document.getElementById('orb-lapslider'); s.value = lap; s.dispatchEvent(new Event('input', {bubbles: true})); }", lap)
                return True
        except Exception:
            continue
    return False


def capture(only=None):
    sys.path.insert(0, str(PROTO / 'tests' / 'screenshots'))
    from capture import goto_route
    from playwright.sync_api import sync_playwright
    RAW.mkdir(parents=True, exist_ok=True)
    report = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={'width': 1920, 'height': 2600}, device_scale_factor=1, color_scheme='dark', service_workers='block')
        ctx.route('**/*', lambda r: r.continue_() if r.request.url.startswith((BASE, 'data:', 'blob:')) else r.abort())
        page = ctx.new_page()
        errors = []
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        for name, path, marker in ROUTES:
            if only and name not in only:
                continue
            errors.clear()
            goto_route(page, BASE, path)
            page.wait_for_selector(f'[data-orb-ready="{marker}"]', state='attached', timeout=45000)
            page.wait_for_timeout(3500)
            if name == 'ghost':
                report['ghost_twin_advanced'] = advance_twin(page, 44)
                page.wait_for_timeout(2500)
            page.screenshot(path=str(RAW / f'{name}.png'), full_page=False)
            report[name] = dict(path=path, console_errors=list(errors))
        browser.close()
    report['captured_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    old = json.loads((RAW / 'capture.json').read_text()) if (RAW / 'capture.json').exists() else {}
    old.update(report)
    (RAW / 'capture.json').write_text(json.dumps(old, indent=1))
    print(json.dumps(report, indent=1))


def crop():
    for out, raw, box in CROPS:
        img = Image.open(RAW / f'{raw}.png').convert('RGB').crop(box)
        img.save(ASSETS / f'{out}.png', optimize=True)
        print(out, img.size)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--capture', action='store_true')
    ap.add_argument('--only', default=None, help='comma-separated raw page names to recapture')
    a = ap.parse_args()
    if a.capture:
        capture(set(a.only.split(',')) if a.only else None)
    crop()
