"""Guided interactions and numerical/model provenance, using real app adapters."""
from dataclasses import replace
from types import SimpleNamespace
import pytest
from streamlit.testing.v1 import AppTest
from app_v2.services import demo_service as D, lock_repository as LR, counterfactual_repository as CF
from app_v2.pages import guided_demo as G
from app_v2.ui import model_guide as M

SCRIPT = 'from app_v2.pages import guided_demo; guided_demo.render()'


def app(case='monza_nor', step=0):
    at = AppTest.from_string(SCRIPT)
    at.session_state['_demo_case'] = case
    at.session_state['_demo_step'] = step
    return at.run(timeout=60)


def button(at, label):
    return next(b for b in at.button if b.label == label)


@pytest.mark.parametrize('case', [c.key for c in D.CASES])
@pytest.mark.parametrize('step', range(5))
def test_each_prepared_demo_step_renders(case, step):
    at = app(case, step)
    assert not at.exception, [e.value for e in at.exception]
    assert any(G.TITLES[step] in x.value for x in at.markdown)


def test_next_back_and_case_switch_reset_only_demo_controls():
    at=app()
    at.session_state['ev']='Hungary'
    at.session_state['drv']='ANT'
    button(at,'Next →').click().run(timeout=60)
    assert at.session_state['_demo_step']==1
    next(s for s in at.slider if s.label.startswith('Race lap')).set_value(25).run(timeout=60)
    assert at.session_state['_demo_live_lap']==25
    button(at,'Reveal next lap +1').click().run(timeout=60)
    assert at.session_state['_demo_live_lap']==26
    button(at,'Return to example').click().run(timeout=60)
    assert at.session_state['_demo_live_lap']==24
    button(at,'← Back').click().run(timeout=60)
    next(r for r in at.radio if r.label=='Demo scenario').set_value('monza_ver').run(timeout=60)
    assert at.session_state['_demo_case']=='monza_ver'
    assert at.session_state['ev']=='Hungary' and at.session_state['drv']=='ANT'
    assert '_demo_live_lap' not in at.session_state
    assert not at.exception


def test_prepared_controls_and_chart_track_selected_source_lap_and_tyre():
    at=app('monza_ver',3)
    select=next(s for s in at.selectbox if s.label=='Pit at the end of race lap')
    select.select_index(len(select.options)-1).run(timeout=60)
    tyres=next(r for r in at.radio if r.label=='Fit a new set of')
    tyres.set_value(tyres.options[-1].upper()).run(timeout=60)
    lap=at.session_state['_demo_pit_lap']; compound=at.session_state['_demo_compound']
    sc=next(s for s in D.scenarios(D.CASES[1]) if s.lap==lap and s.to_compound==compound)
    assert any(D.finish_reading(sc)[0] in x.value for x in at.markdown)
    next(r for r in at.radio if r.label=='Which curve should the simulation use?').set_value('Pre-race scenario').run(timeout=60)
    assert not at.exception
    assert any('MODEL-IMPLIED SCENARIO' in x.value for x in at.caption)
    assert any('frozen pre-race curve' in x.value for x in at.caption)


def test_comparison_preserves_signed_median_and_full_interval():
    sc=SimpleNamespace(finish_delta_s=2.0,q10=-4.0,q90=8.0)
    fig=G.comparison_figure(sc)
    assert list(fig.data[0].x)==[2.0]
    assert list(fig.data[0].error_x.array)==[6.0]
    assert list(fig.data[0].error_x.arrayminus)==[6.0]
    assert fig.layout.xaxis.range[0] < -4.0 and fig.layout.xaxis.range[1] > 8.0
    assert 'later' in D.finish_reading(sc)[0]
    assert 'gain and a loss' in D.finish_reading(sc)[1]


def test_models_named_from_result_and_ghost_source():
    lock=LR.load_lock()
    vm,reason=D.live_snapshot(lock,D.CASES[0],24)
    assert not reason and vm.orb_live['uses_future_data'] is False
    assert vm.forecast.observed is None
    assert vm.orb_live['model_version'] in M.explain('Live estimate',lock,vm)[2]
    assert 'StrategyOptimizer' in M.explain('Pit decision',lock,vm)[2]
    for source, phrase in [(CF.RACE_REFERENCE,'post-race reference'),(CF.PRE_RACE,'frozen pre-race curve')]:
        sc=D.scenarios(D.CASES[0],source)[0]
        text=M.explain('Ghost simulation',lock,sc=sc)
        assert phrase in text[1]
        assert sc.engine['engine_version'] in text[2]


def test_scenario_gate_withholds_changed_assets_and_old_forecast(monkeypatch):
    lock=LR.load_lock(); sc=D.scenarios(D.CASES[0])[0]
    assert not D.scenario_problem(sc,lock)
    monkeypatch.setattr(CF,'verify_assets',lambda sc:{'laps':{'status':'mismatch'}})
    assert 'do not match' in D.scenario_problem(sc,lock)
    assert 'different forecast' in D.scenario_problem(sc,SimpleNamespace(forecast_hash='wrong'))


def test_replay_never_substitutes_another_scenario(monkeypatch):
    sc=D.scenarios(D.CASES[0])[0]
    fake=SimpleNamespace(meta={'event':sc.event,'driver':sc.driver,'scenario_id':'wrong'},arrays={'time_delta_s':[sc.finish_delta_s]})
    calls=[]
    def load(event,driver,scenario_id):
        calls.append((event,driver,scenario_id));return fake,None,None
    monkeypatch.setattr(D.RT,'load_assets',load)
    assert D.exact_replay(sc) is None
    assert calls==[(sc.event,sc.driver,sc.scenario_id)]


def test_madrid_decision_help_does_not_claim_a_live_model():
    at=AppTest.from_string("""
from app_v2.ui import model_guide
from app_v2.services import lock_repository
from types import SimpleNamespace
model_guide.route_help('decision',SimpleNamespace(lock=lock_repository.load_lock(),event='Madrid'))
""").run()
    assert not at.exception
    assert any('Madrid · frozen pre-race forecast' in x.value for x in at.markdown)
    assert any('pre-race stage' in x.value for x in at.markdown)


def test_all_steps_keep_case_and_adjusted_lap_across_hidden_widgets():
    at=app('monza_ver',0)
    button(at,'Next →').click().run(timeout=60)
    button(at,'Reveal next lap +1').click().run(timeout=60)
    assert at.session_state['_demo_live_lap']==25
    for step in (2,3,4):
        button(at,'Next →').click().run(timeout=60)
        assert at.session_state['_demo_step']==step
        assert at.session_state['_demo_case']=='monza_ver'
        assert at.session_state['_demo_live_lap']==25
        assert not at.exception
    button(at,'← Back').click().run(timeout=60)
    assert at.session_state['_demo_case']=='monza_ver'
