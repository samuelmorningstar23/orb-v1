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
                 ('assets', ' · '.join(f"{k} sha256 {v['short']} {v['status']}" for k, v in verified.items()) or '—'), ('claim scope', sc.claim_scope or '—')]
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
                  ('assets (out/counterfactual/pre_race)', ' · '.join(f"{k} sha256 {v['short']} {v['status']}" for k, v in (verified or {}).items()) or '—'),
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
            f"details below. The animation is withheld until a matching replay is available.")


def _t_at_lap(frames, lap: int) -> float:
    a = frames.arrays; idx = np.argmax(a['lap_actual'] >= lap)
    return float(a['t'][idx]) if a['lap_actual'].max() >= lap else float(a['t'][-1])


def prepared_label(sc) -> str:
    return f'{sc.driver} · lap {sc.lap} → {sc.to_compound.title()} · {FIDELITY[sc.mode]} · {sc.set_status} set'


def load_exact_frames(event, driver, sc):
    """A missing selection must never invoke the repository's first-frame fallback."""
    if sc is None or sc.event != event or sc.driver != driver or not sc.scenario_id or sc.is_pre_race:
        return None, None, None, ''
    frames, track, pitlane = RT.load_assets(event, driver, scenario_id=sc.scenario_id)
    if frames is None:
        return None, track, pitlane, ''
    meta = frames.meta
    if any(meta.get(key) != value for key, value in (('event', event), ('driver', driver), ('scenario_id', sc.scenario_id))):
        return None, track, pitlane, 'The animation does not match the selected driver and scenario; it has been withheld.'
    stale = frames_behind_scenario(frames, sc)
    if stale:
        return None, track, pitlane, stale
    endpoint = np.asarray(frames.arrays.get('time_delta_s', []), dtype=float)
    if not len(endpoint) or not np.isfinite(endpoint[-1]) or sc.finish_delta_s is None or abs(float(endpoint[-1]) - sc.finish_delta_s) > FRAME_DELTA_TOL_S:
        return None, track, pitlane, 'The animation endpoint does not match this simulation; it has been withheld.'
    return frames, track, pitlane, ''


def geometry_only_figure(track):
    """Recorded track geometry, deliberately without cars or synthetic motion."""
    import plotly.graph_objects as go
    fig = go.Figure(go.Scatter(x=np.r_[track.x, track.x[0]], y=np.r_[track.y, track.y[0]], mode='lines',
                              line=dict(color='#8297a5', width=5), hoverinfo='skip', showlegend=False))
    fig.update_layout(height=350, margin=dict(l=12, r=12, t=12, b=12), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                      xaxis=dict(visible=False), yaxis=dict(visible=False, scaleanchor='x', scaleratio=1), dragmode=False)
    return fig


def choose_prepared(sc):
    for key in ('ilap_ctl', 'rep_ctl', 'set_state_ctl', 'fid_ctl', 'scenario_ctl'):
        st.session_state.pop(key, None)
    query_state.set_state(drv=sc.driver, ilap=sc.lap, rep=sc.to_compound, setst=sc.set_status,
                          fid=sc.mode, glap=sc.lap, gplay=False, scenario='actual_historical')
    st.rerun()


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
    lattice = None  # A summary lattice is not a prepared, playable simulation.
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
        st.html(f'<div class="cs-banner-audit" role="note">HISTORICAL AUDIT · {esc(CF.REFERENCE_LABEL)} · target driver excluded</div>')
    else:
        banners.scenario_banner()
        banners.note_banner('Scenario Explorer uses the pre-race forecast only. Model-implied, pre-race curve; no observed outcome exists.')

    prepared = CF.scenarios_for(ev, curve_source=CF.RACE_REFERENCE if mode == 'audit' else CF.PRE_RACE)
    active = sc if mode == 'audit' else (psc if sc_row['available'] else None)
    top1, top2 = st.columns([1.2, 2.8])
    with top1:
        new_mode = st.segmented_control('Mode', options=list(MODES), format_func=lambda m: MODES[m], default=mode, key='ghost_mode')
        if new_mode and new_mode != mode:
            query_state.set_state(mode=new_mode); st.rerun()
    with top2:
        ids = [x.scenario_id for x in prepared]
        labels = {x.scenario_id: prepared_label(x) for x in prepared}
        selected = (sc or psc).scenario_id if (sc or psc) else None
        choice = st.selectbox('Prepared simulations', [None] + ids, index=ids.index(selected) + 1 if selected in ids else 0,
                              format_func=lambda x: labels.get(x, 'Choose a prepared simulation' if prepared else 'No simulations prepared for this race'),
                              key=f'prepared_{ev}_{mode}_{driver}_{ilap}_{rep}_{fidelity}_{set_status}', disabled=not prepared)
        if choice is not None and choice != selected:
            choose_prepared(next(x for x in prepared if x.scenario_id == choice))
    if ev == 'Monza':
        quick = st.columns(2)
        for col, drv, lap, compound in zip(quick, ('NOR', 'VER'), (24, 28), ('MEDIUM', 'SOFT')):
            sample = next((x for x in prepared if x.driver == drv and x.lap == lap and x.to_compound == compound and x.mode == 'fixed_context' and x.set_status == 'new'), None)
            if sample and col.button(f'{drv} · lap {lap} → {compound.title()}', width='stretch', key=f'quick_{mode}_{drv}'):
                choose_prepared(sample)

    # Every control lists only prepared choices, plus an explicitly unsupported incoming selection.
    mine = [x for x in prepared if x.driver == driver]
    columns = st.columns([1.1, 1.3, 1.1, 1.5])
    lap_options = sorted({x.lap for x in mine} | {ilap})
    with columns[0]:
        new_ilap = st.selectbox('Intervention lap', lap_options, index=lap_options.index(ilap), key=f'lap_{ev}_{driver}_{mode}_{ilap}',
                               format_func=lambda x: f'Lap {x}' + ('' if any(a.lap == x for a in mine) else ' · not simulated'))
        if new_ilap != ilap:
            candidate = next(x for x in mine if x.lap == new_ilap)
            choose_prepared(candidate)
    candidates = [x for x in mine if x.lap == ilap]
    rep_options = sorted({x.to_compound for x in candidates} | {rep})
    with columns[1]:
        new_rep = st.selectbox('Replacement compound', rep_options, index=rep_options.index(rep), key=f'rep_{ev}_{driver}_{mode}_{ilap}_{rep}',
                              format_func=lambda x: x.title() + ('' if any(a.to_compound == x for a in candidates) else ' · not simulated'))
        if new_rep != rep:
            choose_prepared(next(x for x in candidates if x.to_compound == new_rep))
    candidates = [x for x in candidates if x.to_compound == rep]
    set_options = sorted({x.set_status for x in candidates} | {set_status})
    with columns[2]:
        new_set = st.selectbox('Tyre set', set_options, index=set_options.index(set_status), key=f'set_{ev}_{driver}_{mode}_{ilap}_{rep}_{set_status}')
        if new_set != set_status:
            choose_prepared(next(x for x in candidates if x.set_status == new_set))
    candidates = [x for x in candidates if x.set_status == set_status]
    fid_options = sorted({x.mode for x in candidates} | {fidelity})
    with columns[3]:
        new_fid = st.selectbox('Simulation fidelity', fid_options, index=fid_options.index(fidelity), format_func=lambda x: FIDELITY[x],
                              key=f'fid_{ev}_{driver}_{mode}_{ilap}_{rep}_{set_status}_{fidelity}')
        if new_fid != fidelity:
            choose_prepared(next(x for x in candidates if x.mode == new_fid))
    if mode == 'scenario':
        sc_keys = [x['key'] for x in vm.scenarios]; labels = {x['key']: x['label'] for x in vm.scenarios}
        new_sc = st.selectbox('Weather scenario', sc_keys, index=sc_keys.index(scenario) if scenario in sc_keys else 0, format_func=lambda k: labels[k], key='scenario_ctl')
        if new_sc != scenario:
            query_state.set_state(scenario=new_sc); st.rerun()

    if mode == 'scenario' and not sc_row['available']:
        empty_states.out_of_support(sc_row['support'], f"{sc_row['label']}: {sc_row['reason']} · scenario unavailable")
    elif active is None:
        reason = ('No simulation is prepared for any driver at this race. A simulation is only written when replaying the actual plan '
                  'reproduces the race exactly; where the lap record has gaps or the race ran long under caution, the engine refuses rather than approximate.'
                  if not prepared else
                  f'{driver} · lap {ilap} → {rep.title()} · {FIDELITY[fidelity]} has no prepared simulation. Choose one above to see its result. No ghost animation is available for this selection.')
        empty_states.empty('SIMULATION NOT AVAILABLE', reason, '◌', 'decision')
    else:
        st.html(cards.kv_html([('Finish delta · median', _fmt(active.finish_delta_s)), ('80% interval · q10–q90', f'{_fmt(active.q10)} to {_fmt(active.q90)}'),
                               ('Probability of gain', pct(active.probability_of_gain))]))
        st.caption('Negative time means the simulated plan finishes sooner. ' + ('Historical counterfactual; not a position forecast.' if mode == 'audit' else 'Model-implied scenario; not evidence.'))

    status = RT.assets_status(ev)
    frames = track = pitlane = None
    frame_warning = ''
    if active is not None and mode == 'audit' and status.get('status') == 'ok':
        try:
            frames, track, pitlane, frame_warning = load_exact_frames(ev, driver, sc)
        except Exception as exc:
            frame_warning = f'The prepared animation could not be read ({type(exc).__name__}). The simulation summary is still available.'
    if frame_warning:
        alerts.alert('critical', 'PLAYER FRAMES PREDATE THIS SCENARIO' if 'superseded run' in frame_warning else 'ANIMATION UNAVAILABLE', frame_warning)
    if frames is not None:
        RT.race_twin_player(frames, track, pitlane, height=560 if ctx.presentation else 500, presentation=ctx.presentation,
                            autoplay=False, speed=1, start_t=_t_at_lap(frames, glap), title=f'{driver} · lap {ilap} → {rep.title()} · {FIDELITY[fidelity]}',
                            show_fps=False, key=f'twin_{sc.scenario_id}')
        st.caption('Actual and simulated car · use the player to play, pause or scrub the race. Click the map for keyboard controls: Space and arrow keys.')
    elif status.get('status') == 'refused':
        empty_states.out_of_support('POSITION FEED REFUSED', status.get('reason', ''))
    elif status.get('status') != 'ok':
        empty_states.missing_position()
    elif status.get('status') == 'ok':
        try:
            track = RT.load_track(ev)                 # geometry only, no frame set: pages never import replay directly
            st.plotly_chart(geometry_only_figure(track), width='stretch', config={'displayModeBar': False}, key='recorded_geometry')
            st.caption('Recorded circuit geometry · scenario replay unavailable. No car positions or ghost trajectory are shown.')
        except Exception:
            st.info('Scenario replay unavailable. No substitute animation is shown.')

    with st.expander('Details', expanded=False):
        st.html(badges.support_chips_html(chip_support, lock.forecast_hash[:6]))
        st.caption(f'{ev} · {driver} · {VM.P.SEASON_OF_FEAT} · {FIDELITY[fidelity]} · {set_status} set')
        if mode == 'audit':
            st.html(audit_evidence_html(sc, lattice, vm, verified, hs, rg))
            if hs is not None or rg is not None:
                st.html('<div class="cs-muted">development pool (leave-one-weekend-out), never a sealed weekend</div>')
        else:
            st.html(scenario_evidence_html(vm, sc_row, psc, verified, fid_substituted))
        if active and active.warnings:
            st.caption('Simulation notes')
            for warning in active.warnings:
                st.write(warning)
        if active is not None:
            p1, p2 = st.columns(2)
            src_label = FIDELITY[active.mode] + (f' · {CF.PRE_RACE_LABEL}' if mode == 'scenario' else '')
            if laps is not None:
                with p1:
                    st.plotly_chart(charts.cumulative_delta_real(laps, glap, src_label), width='stretch', config={'displayModeBar': False}, key='cum_delta')
            with p2:
                st.plotly_chart(charts.waterfall_real(CF.decomposition(active), src_label), width='stretch', config={'displayModeBar': False}, key='waterfall')
            st.plotly_chart(charts.ghost_curves_real(sc.curves if sc else {}, actual_comp_at, rep, vm.forecast, vm.forecast_alt, ilap, n_laps,
                                                  audit=mode == 'audit', reference_label=CF.REFERENCE_LABEL), width='stretch', config={'displayModeBar': False}, key='ghost_curves')
        if mode == 'scenario':
            st.caption('The frozen model has no temperature response; supported dry scenarios use the unchanged pre-race curve. Damp and wet scenarios are unavailable.')
    shell.ready_marker('ghost')
