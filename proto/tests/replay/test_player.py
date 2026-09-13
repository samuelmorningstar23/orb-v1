import re
import numpy as np
import pytest
from conftest import MAPS
from app_v2.components.race_twin import player_html, race_twin_animation, race_twin_map, assets_status, list_frames


def test_player_html_is_self_contained(mini_frames, mini_track):
    fr, _ = mini_frames; tr, pl = mini_track
    html = player_html(fr, tr, pl, height=520)
    assert '/*__ORB_DATA__*/null' not in html and '"frames":{' in html and 'requestAnimationFrame' in html
    assert not re.search(r'https?://', html) and '<script src' not in html and '<link' not in html
    for c in ('#E10600', '#F2C230', '#D9DEE5', '#39D0C3', '#090C11'):
        assert c in html
    for key in ('ArrowLeft', 'PageUp', "case ' '", 'setSpeed(10)'):
        assert key in html


def test_player_accepts_dicts_and_presentation(mini_frames, mini_track):
    fr, _ = mini_frames; tr, pl = mini_track
    html = player_html(fr.to_player_dict(), tr.to_dict(), pl.to_dict(), height=600, presentation=True, autoplay=True, speed=5, start_t=30)
    assert '"presentation":true' in html and '"speed":5' in html and '"start_t":30.0' in html


def test_plotly_fallback_animates_same_frames(mini_frames, mini_track):
    fr, _ = mini_frames; tr, pl = mini_track
    fig = race_twin_animation(fr, tr, pl, step_s=5)
    assert len(fig.frames) >= fr.n // 5 - 1 and fig.layout.updatemenus and fig.layout.sliders
    fig2 = race_twin_map(5, 14, 45.3, 2.0, 'SOFT', 'HARD', 6, track=tr, pitlane=pl)
    fig3 = race_twin_map(5, 14, 45.3, 2.0, 'SOFT', 'HARD', 6)             # Workstream 6's original call still works
    assert len(fig2.data) == len(fig3.data) == 6


def test_assets_status_missing(tmp_path):
    s = assets_status('NoSuchEvent', root=tmp_path)
    assert s['status'] == 'missing' and list_frames('NoSuchEvent', root=tmp_path) == []


def test_player_runs_headless(mini_frames, mini_track):
    pytest.importorskip('playwright')
    from playwright.sync_api import sync_playwright, Error
    fr, _ = mini_frames; tr, pl = mini_track
    html = player_html(fr, tr, pl, height=520)
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1200, 'height': 700})
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.set_content(html, wait_until='load')
            page.wait_for_function('window.__orbTwin && window.__orbTwin.frames > 0', timeout=10000)
            page.evaluate('window.__orbTwin.setSpeed(10); window.__orbTwin.play()')
            page.wait_for_timeout(2200)
            fps = page.evaluate('window.__orbTwin.fps'); t = page.evaluate('window.__orbTwin.t')
            page.focus('#orb-twin'); page.keyboard.press('Space'); page.wait_for_timeout(100)
            paused = not page.evaluate('window.__orbTwin.playing')
            browser.close()
    except Error as e:                                   # browser binary missing on this machine
        pytest.skip(f'playwright chromium unavailable: {e}')
    assert errors == [] and fps >= 30 and t > 10 and paused


@pytest.mark.skipif(not (MAPS / 'Monza' / 'meta.json').exists(), reason='Monza assets not built')
def test_player_on_monza_assets():
    from app_v2.components.race_twin import load_assets
    fr, tr, pl = load_assets('Monza', 'NOR')
    assert fr is not None and tr.L > 5000 and pl.source == 'recorded'
    html = player_html(fr, tr, pl)
    assert len(html) < 1_500_000 and ('FIXTURE' in html or 'out/counterfactual/' in html)


def test_tyre_change_button_uses_ghost_lap_and_rewinds_independently(mini_frames, mini_track):
    from playwright.sync_api import sync_playwright
    fr, _ = mini_frames; tr, pl = mini_track
    lap = 9  # mini_frames changes to HARD after lap 9
    first_lap = int(min(fr.arrays['lap_cf']))
    assert max(fr.arrays['lap_cf']) > lap
    html = player_html(fr, tr, pl, stop_lap=lap)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width':1200,'height':700})
        page.set_content(html, wait_until='load')
        page.wait_for_function('window.__orbTwin && window.__orbTwin.frames > 0')
        assert page.evaluate('window.__orbTwin.t') == 0
        page.locator('#orb-tyre-change').click()
        state=page.evaluate('window.__orbTwin.state()')
        assert state['lapC'] == lap + 1
        assert state['compC'] == 3 and state['ageC'] == 1  # new HARD set
        assert not page.evaluate('window.__orbTwin.playing')
        page.locator('#orb-race-start').click()
        assert page.evaluate('window.__orbTwin.t') == 0
        assert page.evaluate('window.__orbTwin.state().lapC') == first_lap
        browser.close()
