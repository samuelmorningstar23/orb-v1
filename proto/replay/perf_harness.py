"""Headless frame-rate and console-error measurement of the Race Twin player (acceptance 13.6: >= 30 FPS).

    python replay/perf_harness.py --event Monza --driver NOR [--seconds 8] [--speeds 1,10] [--width 1440 --height 900]
    python replay/perf_harness.py --mini                      # fixtures/mini_race, no FastF1 needed

Renders player_html() for the saved assets, loads it into headless Chromium (Playwright, installed by Workstream 6), blocks every
non-data request (the demo is offline), plays at each speed and samples window.__orbTwin.fps once a second. Also exercises the
keyboard shortcuts. Prints a JSON report; PERF.md records the numbers.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROTO = Path(__file__).resolve().parents[1]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))


def build_html(args) -> tuple[str, dict]:
    from app_v2.components.race_twin.player import player_html, load_assets
    if args.mini:
        from replay import sources, geometry, trajectory, timewarp
        src = sources.from_mini_race(PROTO / 'fixtures' / 'mini_race')
        tr = geometry.build_track(src); pl = geometry.build_pitlane(src, tr); tr = geometry.attach_pit_flags(tr, pl)
        dt = trajectory.build_trajectory(src, 'ALP', tr, pl)
        fr = timewarp.build_frames(dt, tr, pl, timewarp.fixture_laps(dt, 9, 'HARD'))
        info = dict(event='Mini', driver='ALP', n_frames=fr.n)
    else:
        fr, tr, pl = load_assets(args.event, args.driver, args.scenario)
        if fr is None:
            raise SystemExit(f'no frames for {args.event} {args.driver}')
        info = dict(event=args.event, driver=args.driver, scenario=fr.meta.get('scenario_id'), n_frames=fr.n)
    html = player_html(fr, tr, pl, height=args.player_height, presentation=args.presentation)
    info['html_kb'] = round(len(html) / 1024, 1)
    return html, info


def measure(html: str, seconds: float, speeds: list[int], width: int, height: int, presentation: bool) -> dict:
    from playwright.sync_api import sync_playwright
    report: dict = dict(viewport=f'{width}x{height}', runs=[], console_errors=[], external_requests=[], keyboard={})
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=1, color_scheme='dark')

        def block(route, request):
            url = request.url
            if url.startswith('data:') or url.startswith('blob:') or url.startswith('about:'):
                route.continue_()
            else:
                report['external_requests'].append(url); route.abort()
        ctx.route('**/*', block)
        page = ctx.new_page()
        page.on('console', lambda m: report['console_errors'].append(dict(type=m.type, text=m.text)) if m.type == 'error' else None)
        page.on('pageerror', lambda e: report['console_errors'].append(dict(type='pageerror', text=str(e))))
        t0 = time.perf_counter()
        page.set_content(html, wait_until='load')
        page.wait_for_function('window.__orbTwin && window.__orbTwin.frames > 0', timeout=15000)
        report['ready_ms'] = round((time.perf_counter() - t0) * 1000)
        report['frames'] = page.evaluate('window.__orbTwin.frames')
        for spd in speeds:
            page.evaluate('window.__orbTwin.seek(0)'); page.evaluate(f'window.__orbTwin.setSpeed({spd})'); page.evaluate('window.__orbTwin.play()')
            samples = []; t1 = time.perf_counter(); d0 = page.evaluate('window.__orbTwin.drawn')
            while time.perf_counter() - t1 < seconds:
                page.wait_for_timeout(1000)
                samples.append(page.evaluate('window.__orbTwin.fps'))
            d1 = page.evaluate('window.__orbTwin.drawn'); elapsed = time.perf_counter() - t1
            page.evaluate('window.__orbTwin.pause()')
            samples = [s for s in samples[1:] if s] or samples
            report['runs'].append(dict(speed=spd, seconds=round(elapsed, 1), fps_samples=samples, fps_min=min(samples) if samples else None, fps_median=sorted(samples)[len(samples) // 2] if samples else None,
                                       draws_per_s=round((d1 - d0) / elapsed, 1), t_reached=round(page.evaluate('window.__orbTwin.t'), 1), state=page.evaluate('(() => { const s = window.__orbTwin.state(); return {lapA: s.lapA, lapC: s.lapC, td: +s.td.toFixed(2), dd: +s.dd.toFixed(1)}; })()')))
        # keyboard shortcuts on the focused root
        page.focus('#orb-twin')
        before = page.evaluate('window.__orbTwin.t')
        page.keyboard.press('ArrowRight'); page.keyboard.press('ArrowRight'); page.wait_for_timeout(120)
        report['keyboard']['arrow_right_2'] = round(page.evaluate('window.__orbTwin.t') - before, 2)
        page.keyboard.press('5'); report['keyboard']['digit_5_speed'] = page.evaluate('window.__orbTwin.speed')
        page.keyboard.press('0'); report['keyboard']['digit_0_speed'] = page.evaluate('window.__orbTwin.speed')
        page.keyboard.press('Space'); page.wait_for_timeout(300); report['keyboard']['space_plays'] = page.evaluate('window.__orbTwin.playing')
        page.keyboard.press('Space'); page.wait_for_timeout(100); report['keyboard']['space_pauses'] = not page.evaluate('window.__orbTwin.playing')
        page.keyboard.press('PageUp'); page.wait_for_timeout(100); report['keyboard']['pageup_lap'] = page.evaluate('window.__orbTwin.state().lapA')
        page.keyboard.press('Home'); page.wait_for_timeout(100); report['keyboard']['home_t'] = page.evaluate('window.__orbTwin.t')
        report['hud'] = dict(lap=page.inner_text('#orb-lapno'), gap=page.inner_text('#orb-gap'), badge_a=page.inner_text('#orb-a-txt'), badge_g=page.inner_text('#orb-g-txt'), fps_text=page.inner_text('#orb-fps'))
        report['canvas_px'] = page.evaluate('(() => { const c = document.getElementById("orb-canvas"); return [c.width, c.height]; })()')
        report['horizontal_overflow'] = page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
        browser.close()
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--event', default='Monza'); ap.add_argument('--driver', default='NOR'); ap.add_argument('--scenario', default=None)
    ap.add_argument('--mini', action='store_true'); ap.add_argument('--seconds', type=float, default=6.0); ap.add_argument('--speeds', default='1,10')
    ap.add_argument('--width', type=int, default=1440); ap.add_argument('--height', type=int, default=900); ap.add_argument('--player-height', type=int, default=520)
    ap.add_argument('--presentation', action='store_true'); ap.add_argument('--out', default=None)
    a = ap.parse_args(argv)
    html, info = build_html(a)
    rep = measure(html, a.seconds, [int(x) for x in a.speeds.split(',')], a.width, a.height, a.presentation)
    rep.update(info, generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'))
    text = json.dumps(rep, indent=1)
    print(text)
    if a.out:
        Path(a.out).write_text(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
