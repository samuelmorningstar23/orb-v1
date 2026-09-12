"""Ghost navigation must offer exactly the weekends it can actually analyse.

A weekend qualifies when a prepared simulation exists for it, or when its position feed can render the animation.
Where a simulation exists but the feed is refused, the page shows the numbers and states the refusal: the animation is
never faked (that was the original defect). A weekend with neither is not offered and the link recovers to Monza.
"""
import pytest
from streamlit.testing.v1 import AppTest
from app_v2.components import race_twin as RT
from app_v2.services import counterfactual_repository as CF


def bootstrap(page='ghost', **params):
    at = AppTest.from_string(f"""
from app_v2.pages import common
common.bootstrap(page={page!r})
""")
    at.query_params.update(params)
    return at.run(timeout=30)


def weekend(at):
    return next(s for s in at.selectbox if s.label == 'Weekend')


@pytest.mark.parametrize('event', ['Britain', 'Madrid', 'Monaco'])
def test_unavailable_ghost_link_recovers_and_discards_old_scenario(event):
    at = bootstrap(ev=event, drv='ANT', mode='audit', lap='21',
                   ilap='21', rep='HARD', scenario='actual_historical')
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state['ev'] == 'Monza'
    assert at.query_params['ev'] == ['Monza']
    assert not set(('lap', 'ilap', 'rep', 'scenario')).intersection(at.query_params)
    assert any(f'{event} has no prepared simulation and no race visualisation. Showing Monza.' == el.value for el in at.info)
    offered = weekend(at).options
    assert 'Madrid · forecast only' not in offered
    assert f'{event} · recorded race' not in offered
    assert all(RT.assets_status(name)['status'] == 'ok' or name in CF.events_with_scenarios()
               for name in (label.split(' · ')[0] for label in offered))
    at.run()
    assert not at.info  # The explanation is transient, not permanent page clutter.


def test_supported_ghost_link_keeps_its_selection():
    at = bootstrap(ev='Monza', drv='NOR', mode='audit', lap='24',
                   ilap='24', rep='MEDIUM', scenario='prepared')
    assert not at.exception
    assert at.session_state['drv'] == 'NOR'
    assert at.session_state['lap'] == 24
    assert at.session_state['ilap'] == 24
    assert at.session_state['rep'] == 'MEDIUM'
    assert at.session_state['scenario'] == 'prepared'
    assert not at.info


@pytest.mark.parametrize('page', ['live', 'pre-race', ''])
def test_other_routes_keep_hungary_and_forecast_weekends(page):
    at = bootstrap(page, ev='Hungary', drv='NOR', mode='live', lap='38')
    assert not at.exception
    assert at.session_state['ev'] == 'Hungary'
    assert at.session_state['lap'] == 38
    assert 'Hungary · recorded race' in weekend(at).options
    assert 'Madrid · forecast only' in weekend(at).options


def test_refused_feed_still_offers_a_weekend_that_has_simulations(monkeypatch):
    """The numbers are the page's output; a refused position feed removes the animation, not the analysis."""
    monkeypatch.setattr(RT, 'assets_status', lambda event: {'status': 'refused'})
    at = bootstrap(ev='Hungary', drv='ANT', mode='audit')
    assert not at.exception
    assert at.session_state['ev'] == 'Hungary'
    assert 'Hungary · recorded race' in weekend(at).options


def test_no_simulations_and_no_feeds_gives_empty_state_without_invalid_selector(monkeypatch):
    monkeypatch.setattr(RT, 'assets_status', lambda event: {'status': 'refused'})
    monkeypatch.setattr(CF, 'events_with_scenarios', lambda: frozenset())
    at = bootstrap(ev='Hungary', drv='ANT', mode='audit')
    assert not at.exception
    assert not at.selectbox
    assert any('No race visualisations are available yet.' in el.value for el in at.info)
