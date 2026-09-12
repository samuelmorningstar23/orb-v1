"""Route 2, Live Predictor hero screen (13.4). One fragment holds the hero so replay never full-reruns.

View model: services/live_bridge (Workstream 8's live/viewmodel.build_live_vm; labelled placeholder when the package is absent).
Nothing on this page renders a race-derived reference; the bridge strips it.
"""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import asset_repository as A
from app_v2.services import event_service as ES
from app_v2.services import live_bridge as LB
from app_v2.services import replay_service as RS
from app_v2.services import view_models as VM
from app_v2.state import app_state, query_state
from app_v2.ui import shell, cards, badges, charts, empty_states, banners
from app_v2.ui.formatting import spl, secs, pct, esc

FRAGMENT_PERIOD_S = 0.7


def _rejoin_text(r: dict | None, d) -> str:
    """Observed gap structure only; no projected rejoin position on the live path (red team wording rule)."""
    if r and (r.get('rejoin_context') or {}).get('position_now') is not None:
        return LB.rejoin_text(r['rejoin_context'])
    return d.rejoin_context


def decision_html(d, vm, compact: bool = False) -> str:
    orb = getattr(vm, 'orb_live', None)
    top = (orb or {}).get('recommendations', [None])[0] if orb else None
    changed = 'changed' if (d.action == 'REVIEW' or d.changed_since_last_update or d.status not in ('HOLD PLAN',)) else ''
    if top:
        gain = f"{top['expected_gain_median']:+.1f} s vs pre-race plan (q90 {top['expected_gain_q90']:+.1f})"
        prob = f"{100 * top['probability_of_gain']:.0f}%"
        down = f"{top['expected_gain_q10']:+.1f} s"
        headline = f"{top['action'].replace('_', ' ')}" + (f" LAP {top['pit_window'][0]}" if top.get('pit_window') and top['pit_window'][0] == top['pit_window'][1] else (f" LAPS {top['pit_window'][0]}-{top['pit_window'][1]}" if top.get('pit_window') else '')) + (f", NEW {top['target_compound']}" if top.get('target_compound') else '')
        reasons = list(top.get('reasons') or [])
        if top.get('change_reason'):
            reasons = [f"changed: {top['change_reason']}"] + reasons
        src = f"7.2 live_recommendation · decision/optimizer.py · {orb.get('model_version', '')} · issued {top.get('issued_at', '')}"
    else:
        gain = f'{secs(d.expected_gain_s)} s vs {d.gain_vs} (lock)' if d.expected_gain_s is not None else '—'
        prob = f'{100 * d.probability_of_gain:.0f}%' if d.probability_of_gain is not None else 'pending'
        down = f'{d.downside_q10_s:+.1f} s' if d.downside_q10_s is not None else 'pending'
        headline = d.headline; reasons = d.reasons; src = d.rule_label
    grid = [('expected gain', gain), ('probability of gain', prob), ('downside q10', down), ('rejoin traffic', _rejoin_text(top, d))]
    g = ''.join(f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in grid)
    rs = ''.join(f'<li>{esc(r)}</li>' for r in reasons) or '<li>no change</li>'
    status = ('Recommended strategy' if d.status == 'HOLD PLAN' else d.status.replace('_', ' ').title()) + (' · updated this lap' if d.changed_since_last_update else '')
    if compact:
        grid = [('Modelled gain vs pre-race plan', gain.split(' vs pre-race plan')[0]), ('80% outcome range', f"{top['expected_gain_q10']:+.1f} to {top['expected_gain_q90']:+.1f} s" if top else down), ('Probability of gain', prob)]
        g = ''.join(f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in grid)
    tyre = badges.compound_html(d.target_compound) if d.target_compound else ''
    if compact:
        return (f'<div class="cs-card cs-decision compact {changed}" role="region" aria-label="decision"><div class="status">{esc(status)}</div><div class="headline">{esc(headline)}</div>{tyre}<div class="grid">{g}</div><div class="cs-muted">Modelled tyre-time gain; rivals are not simulated.</div></div>')
    return (f'<div class="cs-card cs-decision {changed}" role="region" aria-label="decision"><div class="status">{esc(status)}</div><div class="headline">{esc(headline)}</div>{tyre}'
            f'<div class="grid">{g}</div><div class="cs-card-title">why this changed</div><ul>{rs}</ul><div class="cs-src">{esc(src)}</div></div>')


def alternatives_html(d, orb) -> str:
    recs = (orb or {}).get('recommendations') or []
    if len(recs) > 1:
        out = ''
        for a in recs[1:4]:
            w = a.get('pit_window'); lab = a['action'].replace('_', ' ').lower() + (f" laps {w[0]}-{w[1]}" if w and w[0] != w[1] else (f" lap {w[0]}" if w else '')) + (f" new {a['target_compound'].lower()}" if a.get('target_compound') else '')
            out += f'<div class="cs-alt"><span>{esc(lab)}</span><span class="d">{a["expected_gain_median"]:+.1f} s · p {100 * a["probability_of_gain"]:.0f}%</span></div>'
        return out
    if not d.alternatives:
        return '<div class="cs-muted">no alternatives</div>'
    return ''.join(f'<div class="cs-alt"><span>{esc(a["plan"])} · stints {esc("/".join(map(str, a["stints"])))} · {a["stops"]} stop</span><span class="d">{("+" + format(a["delta_to_best_s"], ".1f") + " s") if a.get("delta_to_best_s") is not None else "—"} vs plan (lock)</span></div>' for a in d.alternatives)


def history_html(history) -> str:
    if not history:
        return '<div class="cs-muted">no recommendation yet</div>'
    rows = ''
    for d in history[-8:]:
        why = f' · {esc(d.change_reason)}' if d.change_reason else ''
        rows += f'<div><span class="lap">L{d.lap:>2}</span><span class="hot">{esc(d.headline)}</span> · {esc(d.status)}{why}</div>'
    return f'<div class="cs-list">{rows}</div>'


def feedback_html(vm) -> str:
    orb = getattr(vm, 'orb_live', None)
    log = (orb or {}).get('feedback_log') or []
    if log:
        rows = ''
        for e in log[-6:]:
            shift = ', '.join(f'{k} {v:+.2f}' for k, v in (e.get('regime_shift') or {}).items()) or 'no regime shift'
            rows += f'<div><span class="lap">L{int(e["lap"]):>2}</span><span class="hot">{esc(e["symptom"])}</span> {esc(e["axle"])} {esc(e["corner_phase"])} · {e["severity"]}/5 · {esc(shift)} · telemetry {esc(e.get("telemetry_support", "pending"))} ({e.get("laps_since", 0)} laps)</div>'
        return f'<div class="cs-list">{rows}</div>'
    if not vm.feedback:
        return '<div class="cs-muted">no driver feedback logged for this session</div>'
    rows = ''.join(f'<div><span class="lap">L{int(f["lap"]):>2}</span><span class="hot">{esc(f["symptom"])}</span> {esc(f["axle"])} {esc(f["corner_phase"])} · {f["severity"]}/5 {esc(f["trend"])}' + ('' if f.get('engineer_confirmed') else ' · unconfirmed') + '</div>' for f in vm.feedback[-8:])
    return f'<div class="cs-list">{rows}</div>'


def state_panel_html(vm, src) -> str:
    orb = getattr(vm, 'orb_live', None)
    if orb and orb.get('tyre_state'):
        return cards.kv_html(LB.tyre_state_rows(orb['tyre_state']), stack=True)
    q = vm.feed; c = vm.corrections
    return cards.kv_html([('status', q['status']), ('source', src.source_name), ('sensor mode', VM.SENSOR_MODE), ('position samples', q['pos_distinct'] if q['pos_distinct'] is not None else '—'),
                          ('missing channels', ', '.join(q['missing_channels'])), ('fuel prior removed', f'{c.fuel_s_per_lap:.3f} s/lap (lock rules)'), ('race file', f'{vm.asset.short_hash} · {vm.asset.sidecar_status}')], stack=True)


def forecast_only(ctx, lock, ev) -> None:
    sup = VM.SS.support_for(lock, ev, None, ctx.compound)
    common.header(ctx, 'live', n_laps=lock.n_laps(ev), support=sup.overall_support_status, latency='no feed')
    empty_states.empty('NO RACE FEED', f'{ev} has a pre-race forecast, but no recorded race to replay yet.')
    if st.button('Start Monza replay', type='primary'):
        common.goto('live', ev='Monza', drv='NOR', lap=1, mode='live')
    comps = lock.compounds_for(ev)
    if comps:
        cards.section('Tyre degradation forecast', 'Expected pace lost per additional lap of tyre age. The band shows uncertainty.')
        cols = st.columns(len(comps))
        for col, c in zip(cols, comps):
            f = lock.forecast_for(ev, c)
            with col:
                cards.kpi_card(f'{c} FORECAST', spl(f.prediction), f'90% band {spl(f.band90[0])} to {spl(f.band90[1])} · ' + ('issued' if f.issued else 'withheld → fallback'), 'live' if f.issued else 'decision', '', 's/lap')
    shell.ready_marker('live')


def render() -> None:
    ctx = common.context('live')
    if not common.require_lock(ctx, 'live'):
        return
    lock, ev = ctx.lock, ctx.event
    st.session_state['mode'] = 'live'
    ctx.mode = 'live'
    if not A.race_csv_asset(ev).exists:
        forecast_only(ctx, lock, ev); return
    driver = ctx.driver or app_state.default_driver(lock, ev)
    src = app_state.source_for(ev, driver, lock.n_laps(ev))
    if src is None:
        forecast_only(ctx, lock, ev); return
    presentation = ctx.presentation

    @st.fragment(run_every=FRAGMENT_PERIOD_S if src.playing else None)
    def hero() -> None:
        src.poll()
        st.session_state['lap'] = src.cursor.lap
        lat = src.latency_s()
        replay_latency = f'{lat:.1f} s (replay)' if lat is not None else 'replay idle'
        unavailable = RS.prediction_unavailable_reason(src.cursor)
        if unavailable:
            common.header(ctx, 'live', lap=src.cursor.lap, n_laps=src.cursor.n_laps, support='MISSING TYRE DATA', latency=replay_latency)
        else:
            vm = LB.build(lock, ev, driver, src.cursor, replay_latency)
            orb = getattr(vm, 'orb_live', None)
            label = LB.estimator_label_short(vm)
            common.header(ctx, 'live', lap=vm.lap, n_laps=vm.n_laps, support=LB.support_status(vm), latency=LB.latency_text(vm, replay_latency))
            if vm.live_source == 'PLACEHOLDER':
                banners.placeholder_banner('live package not importable: posterior and decision are the labelled placeholders (' + (LB.IMPORT_ERROR or 'unknown') + ')')
        st.markdown(f'## {driver} · live tyre prediction')
        st.caption('Replay a recorded race. The estimate uses only laps reached so far.')
        # Controls occupy two rows so all actions fit on a laptop.
        c1, c2, c3, c4 = st.columns([1.4, 1.1, 1.1, 3.4])
        if c1.button(('Restart replay' if src.cursor.at_end else 'Start replay') if not src.playing else 'Playing', type='primary', width='stretch', disabled=src.playing, key='play'):
            if src.cursor.at_end:
                src.seek(src.cursor.first_lap)
            src.start(); st.rerun(scope='app')
        if c2.button('Pause', width='stretch', disabled=not src.playing, key='pause'):
            src.pause(); st.rerun(scope='app')
        if c3.button('Step +1', width='stretch', disabled=src.cursor.at_end or src.playing, key='step'):
            src.seek(src.cursor.lap + 1); st.session_state['lap'] = src.cursor.lap; st.rerun(scope='fragment')
        speed = c4.segmented_control('Speed', options=list(ES.SPEEDS), format_func=lambda s: f'{s}x', default=int(src.speed) if int(src.speed) in ES.SPEEDS else 1, key='speed_ctl')
        if speed and float(speed) != src.speed:
            src.set_speed(float(speed)); st.session_state['speed'] = speed
        lap = st.slider('Lap scrubber', src.cursor.first_lap, src.cursor.last_lap, value=src.cursor.lap, key=None)
        if lap != src.cursor.lap:
            was = src.playing; src.pause(); src.seek(int(lap)); st.session_state['lap'] = int(lap)
            st.rerun(scope='app' if was else 'fragment')
        query_state.mirror()
        if unavailable:
            banners.note_banner(unavailable)
            return
        state = vm.state
        ts = (orb or {}).get('tyre_state') or {}
        quality = str(ts.get('quality_status', vm.feed.get('status', '')))
        if quality not in ('OK', ''):
            banners.note_banner(f'{quality}: feed quality is reduced; interpret the estimate with caution.')
        support = LB.support_status(vm)
        if 'OUT OF SUPPORT' in support:
            empty_states.out_of_support(support, 'These conditions are outside the supported data.')
        if state and state.kept_laps == 0:
            banners.note_banner('Waiting for clean laps. The estimate is still the pre-race prior; strategy recommendations are provisional.')
        a, b, c = st.columns(3)
        with a:
            k = next((k for k in vm.kpis if k.label == 'LIVE DEGRADATION'), None)
            if k:
                cards.kpi_card('Tyre degradation', k.value, f'Forecast {vm.prior.slope:+.3f} s/lap' if vm.prior.slope is not None else 'No prior available', 'live', unit=getattr(k, 'unit', 's/lap'))
        with b:
            proj = charts.live_projection(vm, [] if src.cursor.at_end else (orb or {}).get('projection'))
            if src.cursor.at_end:
                cards.kpi_card('Replay complete', 'Finished', 'Restart or scrub back to explore an earlier lap.')
            elif proj:
                nxt = proj[0]
                cards.kpi_card('Next lap · pace loss', f"{nxt['loss']:+.2f}", f"90% band {nxt['lo']:+.2f} to {nxt['hi']:+.2f} s · vs a fresh tyre", 'live', unit='s')
        with c:
            if state:
                cards.kpi_card('Clean laps used', str(state.kept_laps), f'Of {state.laps_in_stint} recorded laps on this tyre set', 'neutral', unit='laps')
        left, right = st.columns([2.1, 1.2], gap='medium')
        with left:
            compound = state.compound if state else vm.prior.compound
            st.markdown(f'### Pace loss on this {compound.lower()} tyre set')
            st.caption('Higher means slower. Dots are clean, fuel-corrected laps; the solid line is the current fitted trend.')
            st.plotly_chart(charts.forecast_vs_live(vm, presentation, estimator_label=label, projection=proj), width='stretch', config={'displayModeBar': False}, key='live_chart')
            st.caption(f'Tyre age {state.tyre_age if state else "—"} laps. Pace loss is relative to a fresh tyre of the same compound, not total lap time.'
                       + (' The dotted forecast assumes you stay on this set; shading is the 90% model range.' if proj else ''))
            if state and state.band90[0] is not None and state.band90[0] <= 0 <= state.band90[1]:
                st.caption('Trend uncertain: the 90% range includes both improving and worsening pace.')
        with right:
            if src.cursor.at_end:
                st.html(cards.card_html('Race complete', '<p>No further pit decision is needed.</p>'))
            else:
                st.html(decision_html(vm.decision, vm, compact=True))
            if st.button('Add driver feedback', width='stretch'):
                src.pause(); common.goto('feedback', lap=vm.lap)
        with st.expander('Why this recommendation?'):
            st.html(decision_html(vm.decision, vm))
            st.html(cards.card_html('Other strategies', alternatives_html(vm.decision, orb)))
            st.html(cards.card_html('Recommendation history', history_html(vm.history)))
        with st.expander('Driver reports'):
            st.html(feedback_html(vm))
        with st.expander('Model, uncertainty & feed details'):
            st.caption(f'Estimation method: {label}. Prior: {vm.prior.source}.')
            if orb:
                st.caption(f"Data cutoff {orb.get('data_cutoff', '—')} · no future data. Regime: {orb['regime']}.")
                st.caption('Useful-life figures below are a model crossover proxy, capped at laps remaining. They are not tyre expiry or a pit-stop countdown.')
            note = LB.support_note(vm)
            if note:
                st.caption(note)
            st.html(state_panel_html(vm, src))
            if orb and (orb.get('recommendations') or []):
                st.html(cards.kv_html(LB.recommendation_rows(orb['recommendations'][0]), stack=True))

    hero()
    shell.ready_marker('live')
