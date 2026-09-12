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
from app_v2.services import validation_repository as VR
from app_v2.services import view_models as VM
from app_v2.state import app_state, query_state
from app_v2.ui import shell, cards, badges, charts, empty_states, banners, alerts
from app_v2.ui.formatting import spl, esc, band, pct
from app_v2.components import race_twin as RT

MODES = {'audit': 'Historical audit', 'scenario': 'Scenario explorer'}
FIDELITY = {'tyre_only': 'tyre-only', 'fixed_context': 'fixed context'}


def _fmt(v, f='{:+.1f} s'):
    return '—' if v is None else f.format(v)


def audit_evidence_html(sc: CF.Scenario | None, lattice: dict | None, vm, verified: dict, hs: dict | None = None, rg: dict | None = None) -> str:
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
              ('best plan under the race-observed curves (lock)', hidden), ('frozen plan cost above that best (lock)', regret)]
    pairs += workstream3_audit_pairs(vm.event, vm.driver, hs, rg)
    return cards.kv_html(pairs, stack=True)


def _s1(v) -> str:
    return '—' if v is None else f'{v:.1f} s'


def workstream3_audit_pairs(event: str, driver: str, hs: dict | None, rg: dict | None) -> list[tuple[str, str]]:
    """Workstream 3's held-out results for the selected weekend (development pool only): hidden-stop response and strategy regret.
    Values are read verbatim from out/validation/hidden_stop_<season>.json and regret_<season>.json; labels are Workstream 3's."""
    pairs = []
    if hs is None:
        pairs.append(('hidden-stop response (development pool)', 'not available for this weekend (not in the development pool, or hidden_stop file missing)'))
    else:
        mine = hs['cases']
        if mine:
            c = mine[0]
            own = (f"{driver} in-lap L{c['in_lap']} {str(c['compound_old']).lower()} → new {str(c['compound_new']).lower()}" if c['set_status'] == 'new' else f"{driver} in-lap L{c['in_lap']} {str(c['compound_old']).lower()} → used {str(c['compound_new']).lower()}")
            own += f" ({c['stop_regime'].replace('_', '/')}): next-lap error {_s1(c['err1'])} vs naive {_s1(c['err1_naive'])} · {'inside' if c['cov1'] else 'outside'} the 90% interval"
            if c.get('err3') is not None:
                own += f" · 3-lap {_s1(c['err3'])} vs naive {_s1(c['err3_naive'])}"
            if c.get('err5') is not None:
                own += f" · 5-lap {_s1(c['err5'])} vs naive {_s1(c['err5_naive'])}"
            if len(mine) > 1:
                own += f' · {len(mine) - 1} more stop(s) scored'
        else:
            skipped = ', '.join(f'{k} {v}' for k, v in hs['skipped'].items()) or 'none'
            own = f'no scorable stop for {driver} this weekend (weekend skips: {skipped})'
        sp = hs['season_pooled']
        pairs.append((f'hidden-stop response, {event} (development pool)', f"{hs['n_cases']} stops scored · {own}"))
        pairs.append((f'hidden-stop response, {VM.P.SEASON_OF_FEAT} pool', f"next-lap MAE {_s1(sp['next1_mae'])} vs naive {_s1(sp['next1_mae_naive'])} · 3-lap {_s1(sp['cum3_mae'])} vs {_s1(sp['cum3_mae_naive'])} · 5-lap {_s1(sp['cum5_mae'])} vs {_s1(sp['cum5_mae_naive'])} · next-lap coverage {pct(sp['next1_coverage90'])} · {sp['n_cases']} stops, {sp['n_weekends']} weekends"))
    if rg is None:
        pairs.append(('strategy regret', 'not available for this weekend (not in the development pool, or regret file missing)'))
    else:
        pl = rg['plans']; o = rg['oracle']
        def plan_txt(name):
            x = pl.get(name)
            if not x:
                return '—'
            reg = 'unscorable' if x.get('regret') is None else f"+{x['regret']:.1f} s"
            return f"{x['plan']} ({'/'.join(map(str, x['stints']))}) {reg}"
        pairs.append((f'strategy regret, {event} · {rg["label"]}', f"Orb v1 {plan_txt('orb')} · naive {plan_txt('naive')} · observed field {plan_txt('observed')} · default {plan_txt('default')} · hindsight oracle {o['plan']} ({'/'.join(map(str, o['stints']))}) · pit loss {rg['pit_loss']:.0f} s"))
        sp = rg['season_plans'].get('orb') or {}
        pairs.append((f'strategy regret, {VM.P.SEASON_OF_FEAT} pool · {rg["label"]}', f"Orb v1 median +{sp.get('median', 0):.1f} s, mean +{sp.get('mean', 0):.1f} s over {sp.get('n', '—')} scorable weekends ({rg['season_n']} in the pool) · within 5 s {pct(sp.get('within5'))}"))
    return pairs


def scenario_evidence_html(vm, sc_row: dict, psc: CF.Scenario | None = None, verified: dict | None = None, fid_requested: str | None = None) -> str:
    """Scenario Explorer rail: the pre-race forecast and, when Workstream 2 has run one, the pre-race-curve counterfactual under
    its own label. Nothing here comes from the race-derived reference.

    `fid_requested` is the Simulation-fidelity control's value; when Workstream 2 has no pre-race scenario at that fidelity the
    other one is shown and the substitution is stated on the row (never silently)."""
    fa, fb = vm.forecast, vm.forecast_alt
    pairs = [('scenario', f"{sc_row['label']} · {sc_row['support']}"), ('weather support reason', sc_row['reason'] or '—'),
             (f'{fa.compound.lower()} pre-race forecast', f'{spl(fa.prediction)} s/lap · band {band(*fa.band90)}'),
             (f'{fb.compound.lower()} pre-race forecast' if fb else 'replacement', f'{spl(fb.prediction)} s/lap · band {band(*fb.band90)}' if fb else '—')]
    if psc is not None and sc_row['available']:
        tag = f'Workstream 2 {psc.mode.replace("_", " ")} · {psc.generated_at[:16]} · {CF.PRE_RACE_LABEL}'
        fid_txt = f'{FIDELITY[psc.mode]} ({psc.mode})' + (f' · no pre-race scenario built at {FIDELITY[fid_requested]} fidelity for this combination' if fid_requested and fid_requested != psc.mode else '')
        pairs += [('simulation fidelity', fid_txt),
                  ('model-implied finish delta (pre-race curve)', f'{_fmt(psc.finish_delta_s)} · {tag}'), ('80% interval (q10 to q90), model-implied', f'{_fmt(psc.q10)} to {_fmt(psc.q90)}'),
                  ('probability of gain, model-implied', f'{100 * psc.probability_of_gain:.0f}%' if psc.probability_of_gain is not None else '—'),
                  ('curve', f'{psc.curve_label} · curve_source {psc.curve_source} · forecast hash {psc.pre_race_forecast_hash[:6] or vm.forecast.source}'),
                  ('race data used', f"none: uses_post_race_reference = {str(psc.uses_post_race_reference).lower()} · identity / leakage tests {psc.validation.get('identity_test', '—')} / {psc.validation.get('future_leakage_test', '—')}"),
                  ('counterfactual plan', f"{psc.actual_plan.get('label', '—')} → {psc.cf_plan.get('label', '—')} (pit laps {', '.join(map(str, psc.cf_plan.get('pit_laps', [])))})"),
                  ('assets (out/counterfactual/pre_race)', ' · '.join(f"{k} {v['short']} {v['status']}" for k, v in (verified or {}).items()) or '—'),
                  ('claim scope', f"{psc.claim_scope} · model-implied scenario; not evidence")]
    elif psc is not None:
        pairs += [('model-implied finish delta (pre-race curve)', f"withheld: {sc_row['label']} is outside the dry support; the pre-race-curve counterfactual is shown for supported dry scenarios only"), ('claim scope', 'model-implied scenario; not evidence')]
    else:
        pairs += [('model-implied finish delta (pre-race curve)', 'pending: no pre-race-curve counterfactual (curve_source = pre_race_forecast) under out/counterfactual/pre_race for this combination (Workstream 2 CLI --curve pre_race_forecast)'), ('claim scope', 'model-implied scenario; not evidence')]
    pairs.append(('observed outcome', 'none exists for this combination'))
    return cards.kv_html(pairs, stack=True)


FRAME_DELTA_TOL_S = 1.0   # the player integrates the per-lap table, so a few tenths from the scenario median is normal; a second is not


def frames_behind_scenario(frames, sc: CF.Scenario | None) -> str:
    """'' when the Race Twin frame set matches the scenario on disk, else the sentence to show.

    Workstream 4 builds out/maps/<event>/frames_<driver>_<scenario_id>.npz from Workstream 2's laps.csv. When a scenario is
    regenerated and the frames are not, the animated ghost belongs to the superseded run: say so rather than let the
    player and the evidence rail disagree silently (run `python -m replay.build_maps` to rebuild the frames)."""
    if frames is None or sc is None or sc.finish_delta_s is None:
        return ''
    fd = (getattr(frames, 'meta', None) or {}).get('finish_delta_s')
    if fd is None or abs(float(fd) - float(sc.finish_delta_s)) <= FRAME_DELTA_TOL_S:
        return ''
    return (f"The player's frames finish {float(fd):+.1f} s from the actual car; this scenario's summary.json (generated {sc.generated_at[:16]}) says "
            f"{sc.finish_delta_s:+.1f} s. The frame set was built from a superseded run of {sc.scenario_id} and the animation is not the scenario in the "
            f"evidence rail below. Read the rail, not the map, until Workstream 4 re-runs replay.build_maps for this event.")


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
    default_ilap = default_sc.lap if default_sc else (stints[0]['last_lap'] + 1 if len(stints) > 1 else n_laps // 2)
    ilap = int(s.get('ilap') or default_ilap); ilap = max(1, min(ilap, n_laps))
    actual_comp_at = next((x['compound'] for x in stints if x['first_lap'] <= ilap <= x['last_lap']), stints[-1]['compound'] if stints else 'MEDIUM')
    rep_default = default_sc.to_compound if (default_sc and default_sc.lap == ilap) else next((c for c in comps_lock if c != actual_comp_at), actual_comp_at)
    rep = s.get('rep') if s.get('rep') in comps_lock else rep_default
    set_status = s.get('setst') if s.get('setst') in ('new', 'used') else 'new'
    fid_default = default_sc.mode if default_sc else 'tyre_only'                  # audit: the fidelity of the default race-reference scenario
    if mode == 'scenario':                                                       # explorer: the fidelity Workstream 2 actually built a pre-race scenario at (fixed context first)
        dps = CF.find_pre_race_scenario(ev, driver, ilap, rep, set_status)
        fid_default = dps.mode if dps is not None else fid_default
    fidelity = s.get('fid') if s.get('fid') in CF.MODES else fid_default
    scenario = s.get('scenario') or 'actual_historical'
    glap = int(s.get('glap') or ilap); glap = max(1, min(glap, n_laps))
    sc = CF.find_scenario(ev, driver, ilap, rep, set_status, fidelity, CF.RACE_REFERENCE) if mode == 'audit' else None       # audit: race reference only
    psc, fid_substituted = None, None                                                                                        # explorer: pre-race curve only, at the selected fidelity
    if mode == 'scenario':
        psc = CF.find_pre_race_scenario(ev, driver, ilap, rep, set_status, fidelity)
        if psc is None:
            psc = CF.find_pre_race_scenario(ev, driver, ilap, rep, set_status)     # that fidelity is not built: show the other one and say so
            fid_substituted = fidelity if psc is not None else None
    lattice = CF.lattice_lookup(ev, driver, ilap, rep, set_status, fidelity) if (mode == 'audit' and sc is None) else None
    verified = CF.verify_assets(sc) if sc else (CF.verify_assets(psc) if psc else {})
    laps = CF.load_laps(sc) if sc else (CF.load_laps(psc) if psc else None)
    hs = VR.hidden_stop_for(ev, driver) if mode == 'audit' else None
    rg = VR.regret_for(ev) if mode == 'audit' else None
    # ---- state first, then the full-width frame ------------------------------------------------------------------
    vm = VM.build_ghost(lock, ev, driver, actual_comp_at, 'historical_audit' if mode == 'audit' else 'scenario_explorer', ilap, rep, scenario)
    sc_row = next((x for x in vm.scenarios if x['key'] == scenario), vm.scenarios[0])
    chip_support = vm.support if mode == 'audit' else VM.SS.support_for(lock, ev, driver, actual_comp_at, scenario_temp=sc_row['track_temp'], scenario_weather=sc_row['weather'])
    common.header(ctx, 'ghost', lap=glap, n_laps=n_laps, support=chip_support.overall_support_status, latency='n/a')
    if mode == 'audit':
        st.html(f'<div class="cs-banner-audit" role="note">HISTORICAL AUDIT · OBSERVED WEATHER · HELD-OUT SCORING · curve: {esc(CF.REFERENCE_LABEL)} (target driver excluded) · this page is evidence</div>')
    else:
        banners.scenario_banner()
        banners.note_banner('Scenario Explorer uses the pre-race forecast only (lock, issued before the race). No race-derived curve and no observed outcome enter this mode; the counterfactual shown here runs on the frozen pre-race curve (curve_source = pre_race_forecast) and is model-implied.')
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
        new_fid = st.selectbox('Simulation fidelity', list(FIDELITY), index=list(FIDELITY).index(fidelity), format_func=lambda k: FIDELITY[k], key='fid_ctl', help='tyre-only: tyre time only; fixed context: traffic and SC schedule held as observed. Selects the audit scenario in Historical Audit and the pre-race-curve scenario in the Scenario Explorer; when Workstream 2 built only one fidelity for a combination, that one is shown and the rail says so.')
        if new_fid != fidelity:
            s['fid'] = new_fid; st.rerun()
        if mode == 'scenario':
            sc_keys = [x['key'] for x in vm.scenarios]; labels = {x['key']: x['label'] for x in vm.scenarios}
            new_sc = st.selectbox('Weather scenario', sc_keys, index=sc_keys.index(scenario) if scenario in sc_keys else 0, format_func=lambda k: labels[k], key='scenario_ctl')
            if new_sc != scenario:
                query_state.set_state(scenario=new_sc); st.rerun()
        avail = CF.scenarios_for(ev, driver); avail_p = CF.scenarios_for(ev, driver, CF.PRE_RACE)
        active = sc or psc
        st.html(cards.kv_html([('scenarios built for driver (race reference)', ', '.join(f'L{x.lap}→{x.to_compound[0]} {x.mode[:1]}' for x in avail) or 'none'), ('scenarios built for driver (pre-race curve)', ', '.join(f'L{x.lap}→{x.to_compound[0]} {x.mode[:1]}' for x in avail_p) or 'none'),
                               ('SC / VSC', ('fixed observed schedule: ' + ', '.join(f"{e['kind']} L{e['start_lap']}-{e['end_lap']}" for e in active.safety_car_schedule)) if active and active.safety_car_schedule else 'observed schedule'), ('rivals', 'not simulated')]))
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
            stale = frames_behind_scenario(frames, sc)
            if stale:
                alerts.alert('critical', 'PLAYER FRAMES PREDATE THIS SCENARIO', stale)
        else:
            if status.get('status') == 'refused':
                empty_states.out_of_support('POSITION FEED REFUSED', status.get('reason', ''))
            elif status.get('status') != 'ok':
                empty_states.missing_position()
            elif frames is None and mode == 'audit':
                empty_states.empty('NO FRAMES FOR THIS SCENARIO', f'The track and pit lane are built for {ev}, but no frames exist for {driver} at lap {ilap} → {rep.lower()} ({FIDELITY[fidelity]}). The lap-scrubbed fallback draws the canonical path; run replay.build_maps after Workstream 2 adds the scenario.', '◌', 'decision')
            playing = bool(s.get('gplay', False))
            replay_records = CF.load_ghost_replay(sc) if sc else (CF.load_ghost_replay(psc) if psc else [])
            replay_chip = ('ghost position from Workstream 2 ghost_replay.json' + (f' · {CF.PRE_RACE_LABEL}' if (psc and not sc) else '')) if replay_records else 'no ghost replay for this combination'

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
                delta = CF.ghost_delta_at(replay_records, lap) if replay_records else ((sc or psc).finish_delta_s if (sc or psc) else None)
                st.plotly_chart(RT.race_twin_map(lap, n_laps, mean_lap, delta, actual_comp_at, rep, ilap, ctx.presentation, track=track, pitlane=pitlane), width='stretch', config={'displayModeBar': False}, key='twin_map')
                st.html('<div class="cs-chips">' + badges.compound_html(actual_comp_at, f'A · actual car, {actual_comp_at.lower()}') + badges.compound_html(rep, f'G · ghost car, {rep.lower()} from lap {ilap}') +
                        badges.badge_html('Plotly fallback' + (' on the canonical path' if track is not None else ' on a synthetic loop'), 'neutral') + badges.badge_html(replay_chip, ('decision' if (psc and not sc) else 'live') if replay_records else 'placeholder') + '</div>')

            player()
    with right:
        st.markdown('### evidence')
        st.html(cards.card_html('', audit_evidence_html(sc, lattice, vm, verified, hs, rg) if mode == 'audit' else scenario_evidence_html(vm, sc_row, psc, verified, fid_substituted)))
        if mode == 'audit' and (hs is not None or rg is not None):
            st.html(f'<div class="cs-muted">Workstream 3 rows: {esc(VR.provenance(None, hs["asset"], "hidden_stop_" + str(VM.P.SEASON_OF_FEAT) + ".json") if hs else "hidden-stop file missing")} · {esc(VR.provenance(None, rg["asset"], "regret_" + str(VM.P.SEASON_OF_FEAT) + ".json") if rg else "regret file missing")} · development pool (leave-one-weekend-out), never a sealed weekend</div>')
        active = sc or psc
        if active and active.warnings:
            with st.expander(f'{len(active.warnings)} engine warnings'):
                st.html('<div class="cs-list">' + ''.join(f'<div>{esc(w)}</div>' for w in active.warnings) + '</div>')
    # ---- lower: three synchronised panels ------------------------------------------------------------------------
    p1, p2, p3 = st.columns(3, gap='small')
    lap_sel = int(s.get('glap') or ilap)
    active = sc if mode == 'audit' else (psc if sc_row['available'] else None)
    src_label = (f'Workstream 2 {active.mode.replace("_", " ")}' + (f' · {CF.PRE_RACE_LABEL}' if mode == 'scenario' else '')) if active else 'Workstream 2'
    t_cum = None if mode == 'audit' else f'Cumulative race-time delta · {CF.PRE_RACE_LABEL} (Workstream 2 pre_race laps.csv)'
    t_wf = None if mode == 'audit' else f'Lap decomposition · {CF.PRE_RACE_LABEL}'
    with p1:
        if active is not None and laps is not None:
            st.plotly_chart(charts.cumulative_delta_real(laps, lap_sel, src_label, title=t_cum), width='stretch', config={'displayModeBar': False}, key='cum_delta')
        else:
            empty_states.pending('cumulative race-time delta', 'a full Workstream 2 scenario run for this combination' if mode == 'audit' else ('a supported dry scenario' if psc else 'a pre-race-curve counterfactual run (out/counterfactual/pre_race)'))
    with p2:
        if active is not None:
            st.plotly_chart(charts.waterfall_real(CF.decomposition(active), src_label, title=t_wf), width='stretch', config={'displayModeBar': False}, key='waterfall')
        else:
            empty_states.pending('lap decomposition waterfall', 'a full Workstream 2 scenario run for this combination' if mode == 'audit' else ('a supported dry scenario' if psc else 'a pre-race-curve counterfactual run (out/counterfactual/pre_race)'))
    with p3:
        st.plotly_chart(charts.ghost_curves_real(sc.curves if sc else {}, actual_comp_at, rep, vm.forecast, vm.forecast_alt, ilap, n_laps, audit=(mode == 'audit' and sc is not None), reference_label=CF.REFERENCE_LABEL), width='stretch', config={'displayModeBar': False}, key='ghost_curves')
    if mode == 'scenario':
        cards.section('Supported weather scenarios', 'Only actual-weather audits count as evidence. Each scenario carries a support status; damp and wet are unavailable until a model validates.')
        rows = [[('▶ ' if x['key'] == scenario else '') + x['label'], f"{x['track_temp']:.1f} °C" if x['track_temp'] is not None else '—', x['support'], x['reason'] or '—', 'evidence' if x['evidence'] else ('available' if x['available'] else 'unavailable')] for x in vm.scenarios]
        st.html(cards.table_html(['Scenario', 'Track temp', 'Support', 'Reason', 'Status'], rows))
        banners.note_banner('Scenario curves: the v1 lock carries no temperature response, so the frozen curve is shown unchanged; the temperature-adjusted curve arrives with the frozen-field model. Model-implied; no observed outcome exists.')
    shell.ready_marker('ghost')
