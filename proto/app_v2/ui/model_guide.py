"""Plain-language model attribution; identifiers come from the active result."""
from html import escape
import streamlit as st
from app_v2.services import asset_repository as A, live_bridge as LB

STAGES = ('Forecast', 'Live estimate', 'Pit decision', 'Ghost simulation', 'Replay')


def explain(stage, lock, vm=None, sc=None):
    orb = getattr(vm, 'orb_live', None) or {}
    if stage == 'Forecast':
        return ('Frozen pre-race curve',
                'The starting estimate of pace lost as a tyre gets older. It reads the saved pre-race forecast and its uncertainty range; it does not learn from this race.',
                lock.model_version)
    if stage == 'Live estimate':
        return ('Live tyre estimator',
                'This linear-Gaussian model tracks a straight-line pace trend and its uncertainty using clean laps seen so far. It starts from the pre-race curve, accounts for fuel, and widens uncertainty when the evidence is weak. Fixed rules label unusual behaviour.',
                orb.get('model_version', LB.MODEL_VERSION) + ' · ' + orb.get('estimator_label', LB.ESTIMATOR_LABEL))
    if stage == 'Pit decision':
        return ('Strategy optimiser',
                'It compares legal pit plans using the live tyre estimate, fresh-tyre forecasts and pit-stop cost. It samples their uncertainty and ranks the modelled time gain against the pre-race plan. Rival responses are not simulated; tyre inventory is a placeholder.',
                'StrategyOptimizer · decision/optimizer.py · input ' + orb.get('model_version', LB.MODEL_VERSION))
    if stage == 'Ghost simulation':
        source = ('the frozen pre-race curve' if sc and sc.is_pre_race else 'a post-race reference fitted without this driver')
        return ('Single-car counterfactual engine',
                f'It replaces the tyre and pit-time parts of a recorded race using {source}. Everything else stays paired with that race. The result asks “what if?”; it is not a live prediction or a finishing-position forecast.',
                str(sc.engine.get('engine_version', 'Unavailable')) + ' · ' + sc.curve_label if sc else 'No prepared simulation selected')
    return ('Race Twin replay',
            'The player animates the recorded car and the selected Ghost simulation on the circuit. It does not fit a model or calculate a new strategy. The ghost is a visualisation of modelled time, not a prediction of rival positions.',
            sc.scenario_id if sc else 'No prepared simulation selected')


def render(stage, lock, vm=None, sc=None):
    title, body, identifier = explain(stage, lock, vm, sc)
    pills = ''.join(f'<span class="demo-model-node {"active" if s == stage else ""}" aria-current="{"step" if s == stage else "false"}">{escape(s)}</span>' for s in STAGES)
    st.html('<div class="demo-model-flow" role="group" aria-label="Model stages">' + pills + '</div>')
    st.markdown(f'**Active: {title}**')
    st.caption(body)
    with st.expander('Model name & source'):
        st.code(identifier, language=None)
        if sc:
            st.caption('Curve source: ' + sc.curve_source + ' · ' + sc.curve_label)
        elif vm:
            st.caption('Data available through lap ' + str(vm.lap) + ' · ' + str((vm.orb_live or {}).get('data_cutoff', '')))
        else:
            st.caption('Forecast source: ' + lock.forecast_hash_source)


def route_help(page, ctx):
    """A small opt-in explanation on the full dashboard, including forecast-only states."""
    if ctx.lock is None:
        return
    with st.expander('Which model is working here?'):
        if page in ('live', 'decision', 'feedback') and not A.race_csv_asset(ctx.event).exists:
            st.markdown(f'**{ctx.event} · frozen pre-race forecast**')
            st.write('This weekend is in its pre-race stage. The saved forecast and tyre plan below are the available results. Choose a recorded race to explore the updating tyre estimate and pit decisions.')
        elif page in ('live', 'decision', 'feedback') and not LB.AVAILABLE:
            st.write('The live estimator is unavailable; any fallback output is a labelled placeholder.')
        elif page == 'ghost':
            st.markdown('**Single-car counterfactual engine**')
            st.write('Changes tyre and pit-time terms in a prepared race simulation. Historical audit uses a post-race reference excluding the selected driver; Scenario explorer uses the frozen pre-race curve. The map only animates the selected result.')
        elif page in ('validation', 'generalisation'):
            st.write('These pages display saved evaluation scorecards. They do not fit a model or make a new race decision.')
        else:
            stage = 'Pit decision' if page == 'decision' else ('Live estimate' if page in ('live', 'feedback') else 'Forecast')
            title, body, identifier = explain(stage, ctx.lock)
            st.markdown('**' + title + '**'); st.write(body); st.caption(identifier)
        pages = st.session_state.get('_pages', {})
        if 'demo' in pages:
            st.page_link(pages['demo'], label='Learn it step by step →')


def route_badge(page, ctx):
    from app_v2.ui.help import tip
    if not ctx.lock:
        return
    if page in ('live','decision','feedback') and A.race_csv_asset(ctx.event).exists:
        if not LB.AVAILABLE:
            return
        stage = 'Pit decision' if page == 'decision' else 'Live estimate'
    elif page == 'ghost':
        label = 'Ghost simulation · historical audit' if ctx.mode != 'scenario' else 'Ghost simulation · pre-race curve'
        st.html('<div class="orb-inline-note">' + tip(label, 'A single-car simulation changes tyre and pit-time terms. Historical audit uses a post-race reference excluding this driver; the pre-race option uses its frozen forecast. The track view only replays that result.') + '</div>')
        return
    elif page in ('validation','generalisation'):
        return
    else:
        stage = 'Forecast'
    title, body, identifier = explain(stage, ctx.lock)
    st.html('<div class="orb-inline-note">' + tip('Model · ' + title, body + ' ' + identifier) + '</div>')
