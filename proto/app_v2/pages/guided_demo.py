"""Five guided questions, backed by the dashboard's real models and prepared scenarios."""
from __future__ import annotations
import numpy as np
import plotly.graph_objects as go
import streamlit as st
from app_v2.pages import common
from app_v2.services import demo_service as D, counterfactual_repository as CF
from app_v2.services import lock_repository as LR
from app_v2.ui import charts, model_guide, shell
from app_v2.components import race_twin as RT

TITLES = ('Choose a race story', 'What are the tyres doing?', 'Why make this pit call?', 'What if we change the stop?', 'Watch the two plans')
CSS = '''
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {display:none!important}
.block-container {max-width:1100px!important;padding-top:4.5rem!important}
.demo-model-flow {display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
.demo-model-node {border:1px solid #343c48;border-radius:20px;padding:5px 12px;color:#aeb8c7;font-size:12px}
.demo-model-node.active {background:#123a38;border-color:#32c9bd;color:#bff9ee;font-weight:700}
.demo-task {border-left:3px solid #32c9bd;padding:10px 16px;background:#111b21;border-radius:0 8px 8px 0;margin:10px 0 16px}
</style>
'''


def move(step):
    st.session_state['_demo_step'] = max(0, min(4, step))


def reset_case():
    for key in ('_demo_live_lap', '_demo_pit_lap', '_demo_compound', '_demo_source'):
        st.session_state.pop(key, None)
    move(0)


def task(text):
    from html import escape
    st.html('<div class="demo-task"><strong>Try this</strong> · ' + escape(text) + '</div>')


def choose(lock, cases, case):
    model_guide.render('Forecast', lock)
    st.markdown('### Pick a question to explore')
    st.radio('Demo scenario', [c.key for c in cases], format_func=lambda key: next(c.label for c in cases if c.key == key),
             key='_demo_case', horizontal=True, on_change=reset_case)
    st.write(case.lesson)
    st.caption(f'{case.event} · {case.driver} · recorded race. You will move from a live replay to a clearly labelled historical comparison.')
    st.markdown('**You will learn to:** read the graph, advance the race, understand the pit call, and compare another tyre choice.')
    task('Start with Norris at Monza. Then try Verstappen to explore more stop times and tyres.')
    st.caption('Tyre pressure, temperature and physical wear are not measured here. The model works with public lap and telemetry proxies.')


def live_controls(lock, case):
    st.session_state.setdefault('_demo_live_lap', case.lap)
    st.slider('Race lap · reveal data up to this lap', 1, int(lock.n_laps(case.event)), key='_demo_live_lap')
    a, b, c = st.columns(3)
    def set_lap(lap):
        st.session_state['_demo_live_lap'] = int(lap)
    a.button('Early race', on_click=set_lap, args=(2,), width='stretch')
    b.button('Return to example', on_click=set_lap, args=(case.lap,), width='stretch')
    lap = st.session_state['_demo_live_lap']
    c.button('Reveal next lap +1', on_click=set_lap, args=(min(lap + 1, lock.n_laps(case.event)),),
             disabled=lap >= lock.n_laps(case.event), width='stretch')
    vm, reason = D.live_snapshot(lock, case, lap)
    if reason:
        st.info(reason)
    return vm


def prediction(lock, case):
    task('Reveal one more lap. Watch the clean-lap count and forecast update. “Early race” shows what little evidence looks like.')
    vm = live_controls(lock, case)
    if vm is None:
        return
    model_guide.render('Live estimate', lock, vm=vm)
    state, orb = vm.state, vm.orb_live
    projection = charts.live_projection(vm)
    left, middle, right = st.columns(3)
    left.metric('Tyres now', f'{state.compound.title()} · age {state.tyre_age}')
    middle.metric('Clean laps used', str(orb['n_obs']))
    right.metric('Next-lap pace loss', f"{projection[0]['loss']:+.2f} s" if projection else 'Race complete')
    st.plotly_chart(charts.forecast_vs_live(vm, estimator_label=orb['estimator_label'], projection=projection),
                    width='stretch', config={'displayModeBar':False}, key='demo_live_chart')
    st.markdown('**Read left to right.** Dots are usable laps from this tyre set. The solid line is the current fitted trend. Beyond **Now**, the dotted line estimates pace loss if you stay on these tyres.')
    st.caption('Vertical axis: seconds lost relative to the fitted fresh-tyre baseline, with fuel correction. The shaded area is the full 90% model range. A wider area means less certainty; negative values are allowed by the model.')
    if state.kept_laps < 3:
        st.info('There are very few usable laps. The estimate still relies heavily on its pre-race starting point.')
    if vm.feed.get('status') != 'OK':
        st.caption('Feed quality: ' + str(vm.feed.get('status')) + '. The model retains its uncertainty adjustments.')
    if orb.get('feedback_log'):
        st.caption('Existing driver reports are included through this lap. The demo does not add or change reports.')


def decision(lock, case):
    task('Advance a lap or return to the early race. A recommendation changes only when the model has a reason to rank another legal plan first.')
    vm = live_controls(lock, case)
    if vm is None:
        return
    model_guide.render('Pit decision', lock, vm=vm)
    actions = vm.orb_live.get('recommendations') or []
    if not actions:
        st.info('There is no legal pit action to rank at this lap. Move the race lap back to explore a decision.')
        return
    top = actions[0]
    st.markdown('### ' + D.action_title(top))
    baseline = vm.orb_live.get('baseline') or {}
    st.caption('Compared with the remaining pre-race plan: ' + str(baseline.get('plan', 'saved baseline')))
    a, b, c = st.columns(3)
    a.metric('Modelled time gain', f"{top['expected_gain_median']:+.1f} s")
    b.metric('80% outcome range', f"{top['expected_gain_q10']:+.1f} to {top['expected_gain_q90']:+.1f} s")
    c.metric('Probability of gain', f"{top['probability_of_gain']:.0%}")
    st.write('**Positive gain means this plan is modelled to be faster.** The range includes uncertainty in tyre pace and pit cost.')
    if top['expected_gain_q10'] <= 0 <= top['expected_gain_q90']:
        st.info('The range includes losing time as well as gaining it. Treat the top choice as a trade-off, not a guaranteed win.')
    st.markdown('**What drives this call?**')
    st.write(f"The current {vm.state.compound.lower()} tyre estimate comes from {vm.orb_live['n_obs']} clean laps. The optimiser weighs continuing on that set against a pit stop and the frozen forecast for replacement tyres.")
    if len(actions) > 1:
        with st.expander('Compare other legal actions'):
            st.table([{'Action':D.action_title(a), 'Modelled gain (s)':f"{a['expected_gain_median']:+.1f}", 'Probability of gain':f"{a['probability_of_gain']:.0%}"} for a in actions[1:4]])
    with st.expander('Exact model reasons and constraints'):
        for reason in top.get('reasons', []):
            st.write('• ' + reason)
        st.caption(' · '.join(top.get('constraints') or []))


def selected_scenario(lock, case, controls=True):
    labels = {'Historical audit':CF.RACE_REFERENCE, 'Pre-race scenario':CF.PRE_RACE}
    if controls:
        st.radio('Which curve should the simulation use?', list(labels), key='_demo_source', horizontal=True,
                 on_change=lambda: [st.session_state.pop(k, None) for k in ('_demo_pit_lap', '_demo_compound')])
    source = labels[st.session_state.get('_demo_source', 'Historical audit')]
    scenarios = D.scenarios(case, source)
    if not scenarios:
        st.info('No prepared example uses this curve for this driver. Select the historical audit or another demo scenario.')
        return None
    laps = sorted({s.lap for s in scenarios})
    if st.session_state.get('_demo_pit_lap') not in laps:
        st.session_state['_demo_pit_lap'] = min(laps, key=lambda lap:abs(lap-case.lap))
    if controls:
        st.selectbox('Pit at the end of race lap', laps, key='_demo_pit_lap',
                     on_change=lambda: st.session_state.pop('_demo_compound', None))
    lap = st.session_state['_demo_pit_lap']
    compounds = sorted({s.to_compound for s in scenarios if s.lap == lap})
    if st.session_state.get('_demo_compound') not in compounds:
        st.session_state['_demo_compound'] = 'MEDIUM' if 'MEDIUM' in compounds else compounds[0]
    if controls:
        st.radio('Fit a new set of', compounds, format_func=str.title, horizontal=True, key='_demo_compound')
    sc = next(s for s in scenarios if s.lap == lap and s.to_compound == st.session_state['_demo_compound'])
    problem = D.scenario_problem(sc, lock)
    if problem:
        st.warning(problem)
        return None
    return sc


def outcome(sc):
    headline, reading = D.finish_reading(sc)
    st.markdown('### ' + headline + ' · modelled finish')
    st.caption(('MODEL-IMPLIED SCENARIO · ' if sc.is_pre_race else 'HISTORICAL AUDIT · ') + sc.curve_label)
    st.write('Compared with this driver’s recorded race, after changing the selected stop. **Negative finish delta means sooner; positive means later.**')
    st.caption(f'Finish delta {sc.finish_delta_s:+.1f} s · 80% range {sc.q10:+.1f} to {sc.q90:+.1f} s · probability of gain {sc.probability_of_gain:.0%}')
    st.write(reading)


def comparison_figure(sc):
    fig = go.Figure(go.Scatter(x=[sc.finish_delta_s], y=['Changed plan'], mode='markers',
        marker=dict(color='#32c9bd',size=16), error_x=dict(type='data',array=[sc.q90-sc.finish_delta_s],
        arrayminus=[sc.finish_delta_s-sc.q10],color='#32c9bd',thickness=3),
        hovertemplate='Median %{x:+.1f} s<extra>80% outcome range</extra>'))
    fig.add_vline(x=0,line_dash='dot',line_color='#c6ccd5',annotation_text='Recorded finish',annotation_position='top')
    extent=max(abs(sc.q10),abs(sc.q90),abs(sc.finish_delta_s),1)*1.25
    fig.update_layout(height=230,margin=dict(l=10,r=20,t=35,b=45),paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',font=dict(color='#dce2ed'),showlegend=False,
        xaxis=dict(title='← Finishes sooner     ·     Difference in seconds     ·     Finishes later →',range=[-extent,extent],gridcolor='#27313b'),
        yaxis=dict(showticklabels=False,showgrid=False,zeroline=False))
    return fig


def compare(lock, case):
    task('Change the pit lap or tyre below. Only prepared combinations are offered. Try Verstappen for more choices; no simulation runs on a button press.')
    sc = selected_scenario(lock, case)
    if sc is None:
        return
    model_guide.render('Ghost simulation', lock, sc=sc)
    outcome(sc)
    st.plotly_chart(comparison_figure(sc), width='stretch', config={'displayModeBar':False})
    st.caption('The dot is the median result. The horizontal line is its 80% range. Crossing the recorded-finish line means the changed plan can plausibly gain or lose time.')
    st.caption('Tyre-only simulation: the same driver and race baseline, standardised pit costs, no simulated rival reactions. The historical audit has hindsight; it must not be used as a live forecast.')


def replay(lock, case):
    sc = selected_scenario(lock, case, controls=False)
    if sc is None:
        return
    model_guide.render('Replay', lock, sc=sc)
    st.markdown(f'### {case.event} · {case.driver} · lap {sc.lap} → new {sc.to_compound.lower()}')
    task('Press Play. Actual is the recorded car; Ghost is the changed plan. Use the lap slider to jump forward, or select a faster playback speed.')
    replay_data = D.exact_replay(sc)
    if replay_data:
        frames, track, pitlane = replay_data
        lap_values = frames.arrays['lap_actual']
        idx = int(np.argmax(lap_values >= sc.lap)) if np.max(lap_values) >= sc.lap else 0
        RT.race_twin_player(frames, track, pitlane, height=500, start_t=float(frames.arrays['t'][idx]),
                            title=f'{case.event} · {case.driver} · changed stop at lap {sc.lap}', show_fps=False)
    else:
        st.info('This prepared choice has no matching animation. Its verified time comparison is shown below. Norris at Monza includes a matching replay when those frames are available.')
        st.plotly_chart(comparison_figure(sc), width='stretch', config={'displayModeBar':False})
    outcome(sc)
    st.markdown('**You have followed the full chain:** a saved forecast → a live tyre estimate → a ranked pit decision → a separate “what if?” simulation → its replay.')
    a,b = st.columns(2)
    if a.button('Explore Live Predictor', width='stretch'):
        common.goto('live', ev=case.event, drv=case.driver, lap=st.session_state.get('_demo_live_lap',case.lap), mode='live')
    if b.button('Explore this Ghost strategy', width='stretch'):
        common.goto('ghost', ev=case.event, drv=case.driver, lap=None, ilap=sc.lap, rep=sc.to_compound,
                    mode='scenario' if sc.is_pre_race else 'audit', fid=sc.mode, setst=sc.set_status, scenario='actual_historical')


def render():
    # Preserve selections when their widgets are absent on another tutorial step.
    # Streamlit otherwise removes a widget-owned key after that step finishes.
    for key in ('_demo_case', '_demo_live_lap', '_demo_source', '_demo_pit_lap', '_demo_compound'):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    st.html(CSS)
    lock = LR.load_lock()
    if not st.session_state.get('_demo_step', 0):
        st.markdown('# From a lap to a tyre decision')
        st.caption('A hands-on guide · real recorded races and prepared simulations · runs locally')
    else:
        st.markdown('### Orb · guided demo')
    if lock is None:
        st.info('Load the saved forecast before starting the guide.'); return
    cases = D.available_cases(lock)
    if not cases:
        st.info('No verified demo scenarios are available yet.'); return
    if st.session_state.get('_demo_case') not in {c.key for c in cases}:
        st.session_state['_demo_case'] = cases[0].key
        reset_case()
    case = next(c for c in cases if c.key == st.session_state['_demo_case'])
    step = max(0,min(4,int(st.session_state.get('_demo_step',0))))
    st.progress((step+1)/5, text=f'Step {step+1} of 5 · {TITLES[step]}')
    left, mid, right = st.columns([1,2,1])
    left.button('← Back', disabled=step==0, on_click=move, args=(step-1,), width='stretch')
    if step:
        mid.button('Change demo scenario', on_click=move, args=(0,), width='stretch')
    right.button('Next →' if step<4 else 'Try another scenario', on_click=move,
                 args=(step+1 if step<4 else 0,), type='primary', width='stretch')
    st.markdown('## ' + TITLES[step])
    if step:
        st.caption(case.label)
    if step == 0:
        choose(lock, cases, case)
    else:
        (prediction, decision, compare, replay)[step-1](lock, case)
    st.caption('Recorded races replay locally. Madrid is a frozen pre-race forecast.')
    st.html(f'<div data-orb-demo-ready="{case.key}:{step}" hidden></div>')
    shell.ready_marker('demo')
