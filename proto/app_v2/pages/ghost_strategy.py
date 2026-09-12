"""Routes 6 / 6b, Ghost Strategy hero (13.5): Historical Audit and Scenario Explorer. Sees the finished race.

Audit: Workstream 2's counterfactual outputs (out/counterfactual/<scenario>/) on the leave-one-driver-out Sunday reference
curve; Workstream 4's Race Twin player from out/maps/<event>/ (Plotly fallback when assets are refused or missing).
Scenario Explorer: the pre-race forecast only, under the model-implied banner.
"""
from __future__ import annotations
import numpy as np
import streamlit as st
from app_v2.pages import common
from app_v2.services import asset_repository as A
from app_v2.services import counterfactual_repository as CF
from app_v2.services import replay_service as RS
from app_v2.services import view_models as VM
from app_v2.state import app_state, query_state
from app_v2.ui import shell, cards, badges, charts, empty_states, banners
from app_v2.ui.formatting import spl, esc, band
from app_v2.components import race_twin as RT

MODES = {'audit': 'Historical audit', 'scenario': 'Scenario explorer'}
FIDELITY = {'tyre_only': 'tyre-only', 'fixed_context': 'fixed context'}


def _fmt(v, f='{:+.1f} s'):
    return '—' if v is None else f.format(v)


def audit_evidence_html(sc: CF.Scenario | None, lattice: dict | None, vm, verified: dict) -> str:
    fc = vm.forecast
    err = spl(fc.err) if fc.err is not None else '—'
    covered = '—' if fc.covered is None else ('covered' if fc.covered else 'outside band')
    hidden = f'{vm.hidden_stop["plan"]} ({"/".join(map(str, vm.hidden_stop["stints"]))})' if vm.hidden_stop else '—'
    regret = f'+{vm.regret_s:.1f} s' if vm.regret_s is not None else '—'
    if sc is not None:
        tag = f'Workstream 2 {sc.mode.replace("_", " ")} · {sc.generated_at[:16]}'
        pairs = [('finish delta (median)', f'{_fmt(sc.finish_delta_s)} · {tag}'), ('80% interval (q10 to q90)', f'{_fmt(sc.q10)} to {_fmt(sc.q90)}'), ('probability of gain', f'{100 * sc.probability_of_gain:.0f}%' if sc.probability_of_gain is not None else '—'),
                 ('oracle regret', _fmt(sc.oracle_regret_s) if sc.oracle_regret_s is not None else 'not computed by the engine (null)'),
                 ('counterfactual plan', f"{sc.actual_plan.get('label', '—')} → {sc.cf_plan.get('label', '—')} (pit laps {', '.join(map(str, sc.cf_plan.get('pit_laps', [])))})"),
                 ('reference curves', f"{CF.REFERENCE_LABEL}: " + ', '.join(f"{c.lower()} {v['slope']:+.3f}" for c, v in sc.curves.items())),
                 ('identity / leakage tests', f"{sc.validation.get('identity_test', '—')} / {sc.validation.get('future_leakage_test', '—')} · target driver excluded {sc.validation.get('target_driver_excluded', '—')}"),
                 ('assets', ' · '.join(f"{k} {v['short']} {v['status']}" for k, v in verified.items()) or '—'), ('claim scope', sc.claim_scope or '—')]
    elif lattice is not None:
        pairs = [('finish delta (median)', f"{lattice['elapsed_delta_median_s']:+.1f} s · {lattice['source']} (summary only)"), ('80% interval (q10 to q90)', f"{lattice['elapsed_delta_q10_s']:+.1f} to {lattice['elapsed_delta_q90_s']:+.1f} s"),
                 ('probability of gain', f"{100 * lattice['probability_of_gain']:.0f}%"), ('tyre / pit terms', f"{lattice['tyre_delta_mean_s']:+.1f} / {lattice['pit_delta_mean_s']:+.1f} s"), ('in support', str(lattice.get('in_support'))),
                 ('lap table', 'not built for this combination: cumulative delta and waterfall wait for a full scenario run')]
    else:
        pairs = [('finish delta', 'no counterfactual for this combination (Workstream 2 has not run it)')]
    pairs += [('forecast error (frozen vs race reference)', f'{err} s/lap'), ('band coverage', covered), ('race-derived reference (lock)', f'{spl(fc.observed)} s/lap · {fc.n_race or "—"} laps'),
              ('hidden-stop response (lock)', hidden), ('regret of the frozen plan (lock)', regret)]
    return cards.kv_html(pairs, stack=True)


def scenario_evidence_html(vm, sc_row: dict) -> str:
    fa, fb = vm.forecast, vm.forecast_alt
    pairs = [('scenario', f"{sc_row['label']} · {sc_row['support']}"), ('weather support reason', sc_row['reason'] or '—'),
             (f'{fa.compound.lower()} pre-race forecast', f'{spl(fa.prediction)} s/lap · band {band(*fa.band90)}'),
             (f'{fb.compound.lower()} pre-race forecast' if fb else 'replacement', f'{spl(fb.prediction)} s/lap · band {band(*fb.band90)}' if fb else '—'),
             ('model-implied finish delta', 'pending: a pre-race-curve counterfactual run (curve_source = pre_race) is not in out/counterfactual yet'),
             ('observed outcome', 'none exists for this combination'), ('claim scope', 'model-implied scenario; not evidence')]
    return cards.kv_html(pairs, stack=True)


def _t_at_lap(frames, lap: int) -> float:
    a = frames.arrays; idx = np.argmax(a['lap_actual'] >= lap)
    return float(a['t'][idx]) if a['lap_actual'].max() >= lap else float(a['t'][-1])


def render() -> None:
    ctx = common.context('ghost')
    if not common.require_lock(ctx, 'ghost'):
        return
    lock, ev = ctx.lock, ctx.event
    s = st.session_state
    mode = s.get('mode') if s.get('mode') in ('audit', 'scenario') else 'audit'
    s['mode'] = mode; ctx.mode = mode
    if not A.race_csv_asset(ev).exists or not lock.event_meta(ev).get('completed'):
        sup = VM.SS.support_for(lock, ev, None, ctx.compound)
        common.header(ctx, 'ghost', n_laps=lock.n_laps(ev), support=sup.overall_support_status, latency='n/a')
        empty_states.empty('NO COMPLETED RACE TO AUDIT', f'{ev} has no scored race in the lock. Ghost Strategy audits completed races only; the Live Predictor holds the forecast for this weekend.', '⊘', 'decision')
        shell.ready_marker('ghost'); return
    driver = ctx.driver or app_state.default_driver(lock, ev)
    stints = RS.race_stints(ev, driver)
    n_laps = lock.n_laps(ev) or (stints[-1]['last_lap'] if stints else 50)
    comps_lock = list((lock.strategy.get(ev) or {}).get('offsets') or {}) or lock.compounds_for(ev)
    default_sc = CF.default_scenario(ev)
    if default_sc is not None and default_sc.driver != driver:
        default_sc = next(iter(CF.scenarios_for(ev, driver)), None)
    fidelity = s.get('fid') if s.get('fid') in CF.MODES else (default_sc.mode if default_sc else 'tyre_only')
    default_ilap = default_sc.lap if default_sc else (stints[0]['last_lap'] + 1 if len(stints) > 1 else n_laps // 2)
    ilap = int(s.get('ilap') or default_ilap); ilap = max(1, min(ilap, n_laps))
    actual_comp_at = next((x['compound'] for x in stints if x['first_lap'] <= ilap <= x['last_lap']), stints[-1]['compound'] if stints else 'MEDIUM')
    rep_default = default_sc.to_compound if (default_sc and default_sc.lap == ilap) else next((c for c in comps_lock if c != actual_comp_at), actual_comp_at)
    rep = s.get('rep') if s.get('rep') in comps_lock else rep_default
    set_status = s.get('setst') if s.get('setst') in ('new', 'used') else 'new'
    scenario = s.get('scenario') or 'actual_historical'
    glap = int(s.get('glap') or ilap); glap = max(1, min(glap, n_laps))
    sc = CF.find_scenario(ev, driver, ilap, rep, set_status, fidelity) if mode == 'audit' else None
    lattice = CF.lattice_lookup(ev, driver, ilap, rep, set_status, fidelity) if (mode == 'audit' and sc is None) else None
    verified = CF.verify_assets(sc) if sc else {}
    laps = CF.load_laps(sc) if sc else None
    # ---- state first, then the full-width frame ------------------------------------------------------------------
    vm = VM.build_ghost(lock, ev, driver, actual_comp_at, 'historical_audit' if mode == 'audit' else 'scenario_explorer', ilap, rep, scenario)
    sc_row = next((x for x in vm.scenarios if x['key'] == scenario), vm.scenarios[0])
    chip_support = vm.support if mode == 'audit' else VM.SS.support_for(lock, ev, driver, actual_comp_at, scenario_temp=sc_row['track_temp'], scenario_weather=sc_row['weather'])
    common.header(ctx, 'ghost', lap=glap, n_laps=n_laps, support=chip_support.overall_support_status, latency='n/a')
    if mode == 'audit':
        st.html(f'<div class="cs-banner-audit" role="note">HISTORICAL AUDIT · OBSERVED WEATHER · HELD-OUT SCORING · curve: {esc(CF.REFERENCE_LABEL)} (target driver excluded) · this page is evidence</div>')
    else:
        banners.scenario_banner()
        banners.note_banner('Scenario Explorer uses the pre-race forecast only (lock, issued before the race). No race-derived curve and no observed outcome enter this mode.')
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
        st.html(cards.kv_html([('season', str(VM.P.SEASON_OF_FEAT)), ('circuit', ev), ('driver', driver), ('forecast snapshot', lock.forecast_hash[:6]), ('model snapshot', sc.model_hash[:6] if sc else '—'), ('weather context', 'actual historical' if mode == 'audit' else sc_row['label'])]))
        st.html('<div class="cs-card-title" style="margin-top:8px">actual strategy (recorded race)</div><div class="cs-chips">' + ''.join(badges.compound_html(x['compound'], f'{x["compound"].title()} L{x["first_lap"]}-{x["last_lap"]}') for x in stints) + '</div>')
        new_ilap = st.slider('Intervention lap', 1, n_laps, ilap, key='ilap_ctl')
        if new_ilap != ilap:
            query_state.set_state(ilap=new_ilap, glap=None); st.rerun()
        new_rep = st.selectbox('Replacement compound', comps_lock, index=comps_lock.index(rep) if rep in comps_lock else 0, key='rep_ctl')
        if new_rep != rep:
            query_state.set_state(rep=new_rep); st.rerun()
        new_set = st.selectbox('Set state', ['new', 'used'], index=0 if set_status == 'new' else 1, key='set_state_ctl', help='Workstream 2 scenarios exist for new sets; used-set scenarios are not built yet.')
        if new_set != set_status:
            s['setst'] = new_set; st.rerun()
        new_fid = st.selectbox('Simulation fidelity', list(FIDELITY), index=list(FIDELITY).index(fidelity), format_func=lambda k: FIDELITY[k], key='fid_ctl', help='tyre-only: tyre time only; fixed context: traffic and SC schedule held as observed.')
        if new_fid != fidelity:
            s['fid'] = new_fid; st.rerun()
        if mode == 'scenario':
            sc_keys = [x['key'] for x in vm.scenarios]; labels = {x['key']: x['label'] for x in vm.scenarios}
            new_sc = st.selectbox('Weather scenario', sc_keys, index=sc_keys.index(scenario) if scenario in sc_keys else 0, format_func=lambda k: labels[k], key='scenario_ctl')
            if new_sc != scenario:
                query_state.set_state(scenario=new_sc); st.rerun()
        avail = CF.scenarios_for(ev, driver)
        st.html(cards.kv_html([('scenarios built for driver', ', '.join(f'L{x.lap}→{x.to_compound[0]} {x.mode[:1]}' for x in avail) or 'none'), ('SC / VSC', ('fixed observed schedule: ' + ', '.join(f"{e['kind']} L{e['start_lap']}-{e['end_lap']}" for e in sc.safety_car_schedule)) if sc and sc.safety_car_schedule else 'observed schedule'), ('rivals', 'not simulated')]))
    with centre:
        if mode == 'scenario' and not sc_row['available']:
            empty_states.out_of_support(sc_row['support'], f"{sc_row['label']}: {sc_row['reason']} · scenario unavailable")
        status = RT.assets_status(ev)
        frames = track = pitlane = None
        if status.get('status') == 'ok':
            try:
                frames, track, pitlane = RT.load_assets(ev, driver, scenario_id=sc.scenario_id if sc else None)
            except Exception as e:  # asset present but unreadable: fall back, never crash the hero
                status = dict(status='missing', reason=f'assets unreadable: {type(e).__name__}: {e}')
        if status.get('status') == 'ok' and frames is not None and mode == 'audit':
            sel = st.slider('Selected lap for the panels (the player has its own scrubber)', 1, n_laps, glap, key=None)
            if sel != glap:
                s['glap'] = int(sel); st.rerun()
            RT.race_twin_player(frames, track, pitlane, height=560 if ctx.presentation else 520, presentation=ctx.presentation, autoplay=False, speed=1, start_t=_t_at_lap(frames, glap),
                                title=f'{driver}: ghost {rep.lower()} from lap {ilap} · {FIDELITY[fidelity]}', show_fps=not ctx.presentation, key='twin_player')
            meta = frames.meta
            st.html('<div class="cs-chips">' + badges.compound_html(actual_comp_at, f'A · actual car, {actual_comp_at.lower()}') + badges.compound_html(rep, f'G · ghost car, {rep.lower()} from lap {ilap}') +
                    badges.badge_html(f"frames {meta.get('source')} · {meta.get('n_frames')} @ {meta.get('hz')} Hz · finish delta {meta.get('finish_delta_s', 0):+.1f} s", 'live' if meta.get('source') == 'workstream2' else 'fixture') +
                    badges.badge_html(f"track sidecar {status.get('sidecar', '—')} · pit lane {status.get('pitlane', {}).get('source', '—')}", 'neutral') + badges.badge_html('keyboard: click the map; space, arrows, PgUp/PgDn, 1/2/5/0', 'neutral') + '</div>')
        else:
            if status.get('status') == 'refused':
                empty_states.out_of_support('POSITION FEED REFUSED', status.get('reason', ''))
            elif status.get('status') != 'ok':
                empty_states.missing_position()
            elif frames is None and mode == 'audit':
                empty_states.empty('NO FRAMES FOR THIS SCENARIO', f'The track and pit lane are built for {ev}, but no frames exist for {driver} at lap {ilap} → {rep.lower()} ({FIDELITY[fidelity]}). The lap-scrubbed fallback draws the canonical path; run replay.build_maps after Workstream 2 adds the scenario.', '◌', 'decision')
            playing = bool(s.get('gplay', False))
            replay_records = CF.load_ghost_replay(sc) if sc else []

            @st.fragment(run_every=0.6 if playing else None)
            def player() -> None:
                lap = int(s.get('glap') or ilap)
                if s.get('gplay'):
                    lap = min(lap + int(s.get('gspeed', 1)), n_laps); s['glap'] = lap
                    if lap >= n_laps:
                        s['gplay'] = False
                c1, c2, c3 = st.columns([1, 1, 2.6])
                if c1.button('Play', width='stretch', disabled=bool(s.get('gplay')), key='gplay_btn'):
                    s['gplay'] = True; st.rerun(scope='app')
                if c2.button('Pause', width='stretch', disabled=not s.get('gplay'), key='gpause_btn'):
                    s['gplay'] = False; st.rerun(scope='app')
                sp = c3.segmented_control('Speed', [1, 2, 5, 10], format_func=lambda x: f'{x}x', default=int(s.get('gspeed', 1)), key='gspeed_ctl')
                if sp:
                    s['gspeed'] = int(sp)
                new = st.slider('Lap scrubber', 1, n_laps, lap, key=None)
                if new != lap:
                    s['glap'] = int(new); s['gplay'] = False; st.rerun(scope='app')
                df = RS.load_race(ev); mean_lap = None
                if df is not None:
                    d = df[(df['Driver'] == driver) & df['green']]; mean_lap = float(d['lap_s'].median()) if len(d) else None
                delta = CF.ghost_delta_at(replay_records, lap) if replay_records else (sc.finish_delta_s if sc else None)
                st.plotly_chart(RT.race_twin_map(lap, n_laps, mean_lap, delta, actual_comp_at, rep, ilap, ctx.presentation, track=track, pitlane=pitlane), width='stretch', config={'displayModeBar': False}, key='twin_map')
                st.html('<div class="cs-chips">' + badges.compound_html(actual_comp_at, f'A · actual car, {actual_comp_at.lower()}') + badges.compound_html(rep, f'G · ghost car, {rep.lower()} from lap {ilap}') +
                        badges.badge_html('Plotly fallback' + (' on the canonical path' if track is not None else ' on a synthetic loop'), 'neutral') + (badges.badge_html('ghost position from Workstream 2 ghost_replay.json', 'live') if replay_records else badges.badge_html('no ghost replay for this combination', 'placeholder')) + '</div>')

            player()
    with right:
        st.markdown('### evidence')
        st.html(cards.card_html('', audit_evidence_html(sc, lattice, vm, verified) if mode == 'audit' else scenario_evidence_html(vm, sc_row)))
        if sc and sc.warnings:
            with st.expander(f'{len(sc.warnings)} engine warnings'):
                st.html('<div class="cs-list">' + ''.join(f'<div>{esc(w)}</div>' for w in sc.warnings) + '</div>')
    # ---- lower: three synchronised panels ------------------------------------------------------------------------
    p1, p2, p3 = st.columns(3, gap='small')
    lap_sel = int(s.get('glap') or ilap)
    src_label = f'Workstream 2 {sc.mode.replace("_", " ")}' if sc else 'Workstream 2'
    with p1:
        if mode == 'audit' and laps is not None:
            st.plotly_chart(charts.cumulative_delta_real(laps, lap_sel, src_label), width='stretch', config={'displayModeBar': False}, key='cum_delta')
        else:
            empty_states.pending('cumulative race-time delta', 'a full Workstream 2 scenario run for this combination' if mode == 'audit' else 'a pre-race-curve counterfactual run')
    with p2:
        if mode == 'audit' and sc is not None:
            st.plotly_chart(charts.waterfall_real(CF.decomposition(sc), src_label), width='stretch', config={'displayModeBar': False}, key='waterfall')
        else:
            empty_states.pending('lap decomposition waterfall', 'a full Workstream 2 scenario run for this combination' if mode == 'audit' else 'a pre-race-curve counterfactual run')
    with p3:
        st.plotly_chart(charts.ghost_curves_real(sc.curves if sc else {}, actual_comp_at, rep, vm.forecast, vm.forecast_alt, ilap, n_laps, audit=(mode == 'audit' and sc is not None), reference_label=CF.REFERENCE_LABEL), width='stretch', config={'displayModeBar': False}, key='ghost_curves')
    if mode == 'scenario':
        cards.section('Supported weather scenarios', 'Only actual-weather audits count as evidence. Each scenario carries a support status; damp and wet are unavailable until a model validates.')
        rows = [[('▶ ' if x['key'] == scenario else '') + x['label'], f"{x['track_temp']:.1f} °C" if x['track_temp'] is not None else '—', x['support'], x['reason'] or '—', 'evidence' if x['evidence'] else ('available' if x['available'] else 'unavailable')] for x in vm.scenarios]
        st.html(cards.table_html(['Scenario', 'Track temp', 'Support', 'Reason', 'Status'], rows))
        banners.note_banner('Scenario curves: the v1 lock carries no temperature response, so the frozen curve is shown unchanged; the temperature-adjusted curve arrives with the frozen-field model. Model-implied; no observed outcome exists.')
    shell.ready_marker('ghost')
