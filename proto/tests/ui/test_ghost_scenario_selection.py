"""Ghost must refuse unmatched replays and expose only selected prepared results."""
from types import SimpleNamespace
import numpy as np
import pytest
from streamlit.testing.v1 import AppTest
from app_v2.pages import ghost_strategy as G
from app_v2.services import counterfactual_repository as CF


def scenario(**kw):
    data = dict(event='Monza', driver='NOR', scenario_id='exact', is_pre_race=False, finish_delta_s=-5.7, generated_at='2026-09-12')
    return SimpleNamespace(**(data | kw))


def frames(**kw):
    meta = dict(event='Monza', driver='NOR', scenario_id='exact', finish_delta_s=-5.7)
    return SimpleNamespace(meta=meta | kw, arrays={'time_delta_s':np.array([0., -5.7])})


@pytest.mark.parametrize('selection', [None, scenario(driver='VER'), scenario(event='Austria'), scenario(scenario_id=''), scenario(is_pre_race=True)])
def test_unmatched_or_prerace_never_calls_ambiguous_asset_loader(monkeypatch, selection):
    def forbidden(*args, **kwargs):
        pytest.fail('Missing selection invoked the first-frame fallback')
    monkeypatch.setattr(G.RT, 'load_assets', forbidden)
    assert G.load_exact_frames('Monza', 'NOR', selection)[:3] == (None, None, None)


def test_exact_id_is_required_and_wrong_signed_endpoint_is_refused(monkeypatch):
    selected=scenario(); f=frames(); calls=[]
    def load(ev, drv, scenario_id):
        calls.append((ev, drv, scenario_id));return f, 'track', 'pitlane'
    monkeypatch.setattr(G.RT, 'load_assets', load)
    assert G.load_exact_frames('Monza', 'NOR', selected)[0] is f
    assert calls == [('Monza', 'NOR', 'exact')]
    f.arrays['time_delta_s'][-1] = 5.7
    assert G.load_exact_frames('Monza', 'NOR', selected)[0] is None


@pytest.mark.parametrize('mismatch', [{'driver':'VER'}, {'event':'Austria'}, {'scenario_id':'other'}])
def test_frames_identity_must_match_selection(monkeypatch, mismatch):
    monkeypatch.setattr(G.RT,'load_assets',lambda *a,**k:(frames(**mismatch),None,None))
    f,_,_,reason=G.load_exact_frames('Monza','NOR',scenario())
    assert f is None and 'does not match' in reason


def run_page(state):
    script=f'''import streamlit as st
from app_v2.pages import ghost_strategy
if '_test_initialized' not in st.session_state:
    st.session_state.update({state!r})
    st.session_state['_test_initialized']=True
ghost_strategy.render()
'''
    at=AppTest.from_string(script).run(timeout=30)
    assert not at.exception, [x.value for x in at.exception]
    return at


def test_missing_combination_refuses_arbitrary_frames_and_offers_working_defaults(monkeypatch):
    calls=[]
    real=G.RT.load_assets
    def load(*a,**kw):
        calls.append((a,kw)); return real(*a,**kw)
    monkeypatch.setattr(G.RT,'load_assets',load)
    at=run_page(dict(ev='Monza',drv='NOR',mode='audit',ilap=23,rep='MEDIUM',fid='fixed_context'))
    assert not calls
    html=' '.join(x.value for x in at.get('html'))
    assert 'SIMULATION NOT AVAILABLE' in html
    assert len(at.expander)==1 and at.expander[0].label=='Details'
    assert at.expander[0].proto.expanded is False
    assert {'NOR · lap 24 → Medium','VER · lap 28 → Soft'} <= {b.label for b in at.button}
    at.button(key='quick_audit_VER').click().run(timeout=30)
    assert not at.exception
    assert at.session_state['drv']=='VER' and at.session_state['ilap']==28 and at.session_state['rep']=='SOFT'
    assert calls and all(kw['scenario_id']=='monza_ver_lap28_to_soft_new_fixed_context' for _,kw in calls)


def test_out_of_support_never_loads_frames_or_shows_simulated_finish(monkeypatch):
    monkeypatch.setattr(G.RT,'load_assets',lambda *a,**k:pytest.fail('Unsupported weather loaded audit frames'))
    at=run_page(dict(ev='Monza',drv='NOR',mode='scenario',scenario='wet',ilap=24,rep='MEDIUM',fid='fixed_context'))
    html=' '.join(x.value for x in at.get('html'))
    assert 'OUT OF SUPPORT' in html and 'Finish delta · median' not in html


def test_geometry_only_view_has_no_cars_or_time_positions():
    fig=G.geometry_only_figure(SimpleNamespace(x=np.array([0,1,1]),y=np.array([0,0,1])))
    assert len(fig.data)==1 and fig.data[0].mode=='lines'
    assert not fig.frames and list(fig.data[0].x)==[0,1,1,0]


@pytest.mark.parametrize('driver,lap,compound',[('NOR',24,'MEDIUM'),('VER',28,'SOFT')])
def test_prepared_defaults_use_their_own_verified_frames(driver,lap,compound):
    sc=CF.find_scenario('Monza',driver,lap,compound,'new','fixed_context')
    assert sc is not None
    f,_,_,reason=G.load_exact_frames('Monza',driver,sc)
    assert f is not None and not reason
    assert f.meta['scenario_id']==sc.scenario_id
    assert float(f.arrays['time_delta_s'][-1])==pytest.approx(sc.finish_delta_s,abs=G.FRAME_DELTA_TOL_S)


def test_prepared_action_recovers_from_unsupported_weather():
    at=run_page(dict(ev='Monza',drv='NOR',mode='scenario',scenario='wet',ilap=24,rep='MEDIUM',fid='fixed_context'))
    at.button(key='quick_scenario_NOR').click().run(timeout=30)
    assert not at.exception
    assert at.session_state['scenario']=='actual_historical'
    html=' '.join(x.value for x in at.get('html'))
    assert 'Finish delta · median' in html and 'OUT OF SUPPORT' not in html
