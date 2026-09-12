"""Routes 6 / 6b, Ghost Strategy hero (13.5): Historical Audit and Scenario Explorer. Sees the finished race."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import asset_repository as A
from app_v2.services import replay_service as RS
from app_v2.services import view_models as VM
from app_v2.state import app_state, query_state
from app_v2.ui import shell, cards, badges, charts, empty_states, banners
from app_v2.ui.formatting import spl, esc
from app_v2.components.race_twin.plotly_fallback import race_twin_map

MODES = {'audit': 'Historical audit', 'scenario': 'Scenario explorer'}


def evidence_html(vm) -> str:
    fc = vm.forecast
    err = spl(fc.err) if fc.err is not None else '—'
    covered = '—' if fc.covered is None else ('covered' if fc.covered else 'outside band')
    cf = f'{vm.counterfactual_delta_s:+.1f} s' if vm.counterfactual_delta_s is not None else '—'
    hidden = f'{vm.hidden_stop["plan"]} ({"/".join(map(str, vm.hidden_stop["stints"]))})' if vm.hidden_stop else '—'
    regret = f'+{vm.regret_s:.1f} s' if vm.regret_s is not None else 'race pending'
    cs = vm.counterfactual_summary or {}; tag = vm.counterfactual_source
    q10, q90, pg, oreg = cs.get('elapsed_delta_q10_s'), cs.get('elapsed_delta_q90_s'), cs.get('probability_of_gain'), cs.get('oracle_regret_median_s')
    interval = f'{q10:+.1f} to {q90:+.1f} s · {tag}' if q10 is not None and q90 is not None else 'pending Workstream 2'
    prob = f'{pg:.0%} · {tag}' if pg is not None else 'pending Workstream 2'
    pairs = [('finish delta', f'{cf} · {tag}'), ('80% interval', interval), ('probability of gain', prob), ('oracle regret', f'{oreg:+.1f} s · {tag}' if oreg is not None else 'pending Workstream 2'),
             ('forecast error', f'{err} s/lap'), ('coverage', covered), ('race reference', f'{spl(fc.observed)} s/lap · {fc.n_race or "—"} laps'),
             ('hidden-stop response', hidden), ('regret of frozen plan', regret), ('claim scope', 'tyre-only, fixed context; rivals not simulated')]
    return cards.kv_html(pairs, stack=True)


def render() -> None:
    ctx = common.context('ghost')
    if not common.require_lock(ctx, 'ghost'):
        return
    lock, ev = ctx.lock, ctx.event
    s = st.session_state
    mode = s.get('mode') if s.get('mode') in ('audit', 'scenario') else 'audit'
    s['mode'] = mode
    ctx.mode = mode
    if not A.race_csv_asset(ev).exists or not lock.event_meta(ev).get('completed'):
        sup = VM.SS.support_for(lock, ev, None, ctx.compound)
        common.header(ctx, 'ghost', n_laps=lock.n_laps(ev), support=sup.overall_support_status, latency='n/a')
        empty_states.empty('NO COMPLETED RACE TO AUDIT', f'{ev} has no scored race in the lock. Ghost Strategy audits completed races only; the Live Predictor holds the forecast for this weekend.', '⊘', 'decision')
        shell.ready_marker('ghost'); return
    driver = ctx.driver or app_state.default_driver(lock, ev)
    stints = RS.race_stints(ev, driver)
    n_laps = lock.n_laps(ev) or (stints[-1]['last_lap'] if stints else 50)
    comps_lock = list((lock.strategy.get(ev) or {}).get('offsets') or {}) or lock.compounds_for(ev)
    default_ilap = stints[0]['last_lap'] + 1 if len(stints) > 1 else (n_laps // 2)
    ilap = int(s.get('ilap') or default_ilap); ilap = max(1, min(ilap, n_laps))
    actual_comp_at = next((x['compound'] for x in stints if x['first_lap'] <= ilap <= x['last_lap']), stints[-1]['compound'] if stints else 'MEDIUM')
    rep = s.get('rep') if s.get('rep') in comps_lock else next((c for c in comps_lock if c != actual_comp_at), actual_comp_at)
    scenario = s.get('scenario') or 'actual_historical'
    glap = int(s.get('glap') or ilap); glap = max(1, min(glap, n_laps))
    # ---- state first, then the full-width frame ------------------------------------------------------------------
    vm = VM.build_ghost(lock, ev, driver, actual_comp_at, 'historical_audit' if mode == 'audit' else 'scenario_explorer', ilap, rep, scenario)
    sc_row = next((x for x in vm.scenarios if x['key'] == scenario), vm.scenarios[0])
    chip_support = vm.support if mode == 'audit' else VM.SS.support_for(lock, ev, driver, actual_comp_at, scenario_temp=sc_row['track_temp'], scenario_weather=sc_row['weather'])
    support_status = chip_support.overall_support_status
    common.header(ctx, 'ghost', lap=glap, n_laps=n_laps, support=support_status, latency='n/a')
    if mode == 'audit':
        banners.audit_banner()
    else:
        banners.scenario_banner()
    m1, m2 = st.columns([1.7, 3.3])
    with m1:
        new_mode = st.segmented_control('Mode', options=list(MODES), format_func=lambda m: MODES[m], default=mode, key='ghost_mode')
        if new_mode and new_mode != mode:
            query_state.set_state(mode=new_mode); st.rerun()
    with m2:
        st.html(badges.support_chips_html(chip_support, lock.forecast_hash[:6]))
    left, centre, right = st.columns([1.0, 2.4, 1.25], gap='medium')
    with left:
        st.markdown('### controls')
        st.html(cards.kv_html([('season', str(VM.P.SEASON_OF_FEAT)), ('circuit', ev), ('driver', driver), ('forecast snapshot', lock.forecast_hash[:6]), ('weather context', 'actual historical' if mode == 'audit' else sc_row['label'])]))
        st.html('<div class="cs-card-title" style="margin-top:8px">actual strategy (recorded race)</div><div class="cs-chips">' + ''.join(badges.compound_html(x['compound'], f'{x["compound"].title()} L{x["first_lap"]}-{x["last_lap"]}') for x in stints) + '</div>')
        new_ilap = st.slider('Intervention lap', 1, n_laps, ilap, key='ilap_ctl')
        if new_ilap != ilap:
            query_state.set_state(ilap=new_ilap); st.rerun()
        new_rep = st.selectbox('Replacement compound', comps_lock, index=comps_lock.index(rep) if rep in comps_lock else 0, key='rep_ctl')
        if new_rep != rep:
            query_state.set_state(rep=new_rep); st.rerun()
        st.selectbox('Set state', ['new', 'used (placeholder)'], index=0, key='set_state_ctl', help='Set-condition effects arrive with Phase 1.')
        if mode == 'scenario':
            sc_keys = [x['key'] for x in vm.scenarios]; labels = {x['key']: x['label'] for x in vm.scenarios}
            new_sc = st.selectbox('Weather scenario', sc_keys, index=sc_keys.index(scenario) if scenario in sc_keys else 0, format_func=lambda k: labels[k], key='scenario_ctl')
            if new_sc != scenario:
                query_state.set_state(scenario=new_sc); st.rerun()
        st.html(cards.kv_html([('fidelity', 'tyre-only, fixed context'), ('SC / VSC', 'fixed observed schedule'), ('rivals', 'not simulated')]))
    with centre:
        if mode == 'scenario' and not sc_row['available']:
            empty_states.out_of_support(sc_row['support'], f"{sc_row['label']}: {sc_row['reason']} · scenario unavailable")
        playing = bool(s.get('gplay', False))

        @st.fragment(run_every=0.6 if playing else None)
        def player() -> None:
            lap = int(s.get('glap') or ilap)
            if s.get('gplay'):
                lap = min(lap + int(s.get('gspeed', 1)), n_laps); s['glap'] = lap
                if lap >= n_laps:
                    s['gplay'] = False
            c1, c2, c3 = st.columns([1, 1, 2.6])
            if c1.button('Play', use_container_width=True, disabled=bool(s.get('gplay')), key='gplay_btn'):
                s['gplay'] = True; st.rerun(scope='app')
            if c2.button('Pause', use_container_width=True, disabled=not s.get('gplay'), key='gpause_btn'):
                s['gplay'] = False; st.rerun(scope='app')
            sp = c3.segmented_control('Speed', [1, 2, 5, 10], format_func=lambda x: f'{x}x', default=int(s.get('gspeed', 1)), key='gspeed_ctl')
            if sp:
                s['gspeed'] = int(sp)
            new = st.slider('Lap scrubber', 1, n_laps, lap, key=None)
            if new != lap:
                s['glap'] = int(new); s['gplay'] = False; st.rerun(scope='app')
            mean_lap = None
            df = RS.load_race(ev)
            if df is not None:
                d = df[(df['Driver'] == driver) & df['green']]
                mean_lap = float(d['lap_s'].median()) if len(d) else None
            st.plotly_chart(race_twin_map(lap, n_laps, mean_lap, vm.counterfactual_delta_s, actual_comp_at, vm.replacement, ilap, ctx.presentation), use_container_width=True, config={'displayModeBar': False}, key='twin_map')
            st.html('<div class="cs-chips">' + badges.compound_html(actual_comp_at, f'A · actual car, {actual_comp_at.lower()}') + badges.compound_html(vm.replacement, f'G · ghost car, {vm.replacement.lower()} from lap {ilap}') + badges.badge_html('dotted: pit-lane path (schematic)', 'neutral') + badges.badge_html('keyboard: focus the slider, arrow keys scrub', 'neutral') + badges.badge_html('time-warped React player pending Workstream 4', 'placeholder') + badges.badge_html(f'race file {vm.asset.short_hash}', 'neutral') + '</div>')

        player()
        empty_states.missing_position()
    with right:
        st.markdown('### evidence')
        st.html(cards.card_html('', evidence_html(vm)))
        if vm.block and vm.block_source == 'FIXTURE':
            g = vm.block.get('generalisation_status', {})
            st.html(cards.card_html('FIXTURE · lock_v2 ghost block shape', cards.kv_html([('mode', vm.block.get('mode')), ('event', vm.block.get('event')), ('driver', vm.block.get('driver')), ('model_implied', str(vm.block.get('model_implied'))), ('support', g.get('overall_support_status', '—'))], stack=True), extra_class='raised'))
    # ---- lower: three synchronised panels ------------------------------------------------------------------------
    p1, p2, p3 = st.columns(3, gap='small')
    lap_sel = int(s.get('glap') or ilap)
    with p1:
        st.plotly_chart(charts.cumulative_delta_placeholder(vm, lap_sel), use_container_width=True, config={'displayModeBar': False}, key='cum_delta')
    with p2:
        st.plotly_chart(charts.waterfall_placeholder(vm), use_container_width=True, config={'displayModeBar': False}, key='waterfall')
    with p3:
        st.plotly_chart(charts.ghost_curves(vm), use_container_width=True, config={'displayModeBar': False}, key='ghost_curves')
    if mode == 'scenario':
        cards.section('Supported weather scenarios', 'Only actual-weather audits count as evidence. Each scenario carries a support status; damp and wet are unavailable until a model validates.')
        rows = [[('▶ ' if x['key'] == scenario else '') + x['label'], f"{x['track_temp']:.1f} °C" if x['track_temp'] is not None else '—', x['support'], x['reason'] or '—', 'evidence' if x['evidence'] else ('available' if x['available'] else 'unavailable')] for x in vm.scenarios]
        st.html(cards.table_html(['Scenario', 'Track temp', 'Support', 'Reason', 'Status'], rows))
        banners.note_banner('Scenario curves: the v1 lock carries no temperature response, so the frozen curve is shown unchanged; the temperature-adjusted curve arrives with the frozen-field model. Model-implied; no observed outcome exists.')
    shell.ready_marker('ghost')
