"""The strategy story must describe the exact prepared plan, with correct timing and sign."""
from copy import deepcopy
from dataclasses import replace
import pytest
from app_v2.services import counterfactual_repository as CF
from app_v2.ui.ghost_summary import strategy_summary, summary_html
from test_ghost_scenario_selection import run_page


def example():
    return CF.find_scenario('Monza', 'NOR', 24, 'MEDIUM', 'new', 'tyre_only')


def test_recorded_stop_is_distinct_from_the_simulated_change():
    s=strategy_summary(example())
    assert s['title']=='After lap 24 · Hard → new Medium'
    assert s['timing']=='The Ghost fits new Medium tyres for lap 25.'
    assert s['actual']=='Medium → Hard after lap 3'
    assert s['ghost']=='Medium → Hard after lap 3 → Medium after lap 24'
    assert '7.8 s gain' in s['analysis'] and 'advantage is uncertain' in s['analysis']
    assert 'Historical reference' in s['model']


@pytest.mark.parametrize('delta,lo,hi,word,band', [(4.,1.,8.,'4.0 s loss','favours the original'), (-4.,-8.,-1.,'4.0 s gain','favours this plan'), (0.,-2.,2.,'almost no change','gain and loss')])
def test_analysis_tracks_the_signed_result_and_uncertainty(delta,lo,hi,word,band):
    sc=example(); data=deepcopy(sc.summary)
    data['scenario']['summary'].update(elapsed_delta_median_s=delta,elapsed_delta_q10_s=lo,elapsed_delta_q90_s=hi)
    s=strategy_summary(replace(sc,summary=data))
    assert word in s['analysis'] and band in s['analysis']


def test_pre_race_summary_names_its_own_curve_source():
    sc=CF.find_pre_race_scenario('Monza','NOR',24,'MEDIUM','new')
    assert sc is not None
    s=strategy_summary(sc)
    assert 'Frozen pre-race' in s['model'] and 'Historical reference' not in s['model']


def test_summary_precedes_controls_and_replay_always_opens_at_race_start(monkeypatch):
    from app_v2.pages import ghost_strategy as G
    rendered=[]
    monkeypatch.setattr(G.RT,'race_twin_player',lambda *a,**kw:rendered.append(kw))
    at=run_page(dict(ev='Monza',drv='NOR',mode='audit',ilap=24,rep='MEDIUM',glap=24,lap=47))
    html=' '.join(x.value for x in at.get('html'))
    assert 'Strategy at a glance' in html
    assert rendered[0]['start_t']==0.0 and rendered[0]['stop_lap']==24
    assert at.session_state['lap']==47  # Ghost cannot rewind the separate Live cursor.


def test_unverified_scenario_does_not_publish_strategy_story(monkeypatch):
    from app_v2.pages import ghost_strategy as G
    monkeypatch.setattr(G.DEMO,'scenario_problem',lambda *a:'Asset hash mismatch')
    at=run_page(dict(ev='Monza',drv='NOR',mode='audit',ilap=24,rep='MEDIUM'))
    assert 'Strategy at a glance' not in ' '.join(x.value for x in at.get('html'))
    assert any('Asset hash mismatch' in w.value for w in at.warning)
