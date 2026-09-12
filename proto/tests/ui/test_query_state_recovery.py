"""Routing regression contracts: cleared controls must not be rehydrated from stale URLs."""
from types import SimpleNamespace
import pytest
from app_v2.state import query_state as Q

@pytest.fixture
def routing(monkeypatch):
    state={'ev':'Monza','mode':'audit','drv':'NOR','lap':32,'cmp':'SOFT','ilap':24,'rep':'MEDIUM','scenario':'baseline','present':True}
    query={k:('1' if v is True else str(v)) for k,v in state.items()}
    query['unrelated']='retain-me'
    monkeypatch.setattr(Q,'st',SimpleNamespace(session_state=state,query_params=query))
    return state,query

@pytest.mark.parametrize('key',['drv','lap','cmp','scenario','ilap','rep'])
def test_cleared_control_is_removed_from_url_and_not_rehydrated(routing,key):
    state,query=routing
    Q.set_state(**{key:None})
    assert key not in query
    assert query['unrelated']=='retain-me'
    Q.sync(['Monza','Madrid'])
    assert state.get(key) is None

def test_presentation_can_be_switched_off(routing):
    state,query=routing
    Q.set_state(present=False)
    assert 'present' not in query
    assert Q.sync(['Monza','Madrid'])['present'] is False

def test_event_switch_clears_explicitly_reset_controls(routing):
    state,query=routing
    Q.set_state(ev='Madrid',drv=None,lap=None,cmp=None,scenario=None,ilap=None,rep=None)
    result=Q.sync(['Monza','Madrid'])
    assert result['ev']=='Madrid'
    for key in ('drv','lap','cmp','scenario','ilap','rep'):
        assert result[key] is None
        assert key not in query

def test_driver_change_does_not_restore_old_lap(routing):
    state,query=routing
    Q.set_state(drv='LEC',lap=None)
    result=Q.sync(['Monza','Madrid'])
    assert result['drv']=='LEC' and result['lap'] is None
    assert 'lap' not in query

def test_navigation_clearing_all_params_preserves_session_controls(routing):
    state,query=routing;before=state.copy();query.clear()
    result=Q.sync(['Monza','Madrid'])
    assert result==before
    assert query['drv']=='NOR' and query['lap']=='32'

def test_explicit_deep_link_initializes_exact_selection(routing):
    state,query=routing;state.clear();query.clear()
    query.update(ev='Monza',drv='lec',cmp='hard',lap='12',ilap='24',rep='soft',mode='audit')
    result=Q.sync(['Monza','Madrid'])
    assert {k:result[k] for k in ('ev','drv','cmp','lap','ilap','rep','mode')}==dict(ev='Monza',drv='LEC',cmp='HARD',lap=12,ilap=24,rep='SOFT',mode='audit')
