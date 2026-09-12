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


def decision_html(d, vm) -> str:
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
    status = d.status + (' · changed this lap' if d.changed_since_last_update else '')
    tyre = badges.compound_html(d.target_compound) if d.target_compound else ''
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
    empty_states.missing_feed(ev)
    comps = lock.compounds_for(ev)
    if comps:
        cards.section('Pre-race forecast for this weekend (lock)', 'The prior the live posterior starts from once a feed exists.')
        cols = st.columns(len(comps))
        for col, c in zip(cols, comps):
            f = lock.forecast_for(ev, c)
            with col:
                cards.kpi_card(f'{c} FORECAST', spl(f.prediction), f'90% band {spl(f.band90[0])} to {spl(f.band90[1])} · ' + ('issued' if f.issued else 'withheld → fallback'), 'live' if f.issued else 'decision', f.source, 's/lap')
    shell.ready_marker('live')


def render() -> None:
    ctx = common.context('live')
    if not common.require_lock(ctx, 'live'):
        return
    lock, ev = ctx.lock, ctx.event
    st.session_state['mode'] = 'live'
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
        vm = LB.build(lock, ev, driver, src.cursor, replay_latency)
        orb = getattr(vm, 'orb_live', None)
        label = LB.estimator_label_short(vm)
        common.header(ctx, 'live', lap=vm.lap, n_laps=vm.n_laps, support=LB.support_status(vm), latency=LB.latency_text(vm, replay_latency))
        if vm.live_source == 'PLACEHOLDER':
            banners.placeholder_banner('live package not importable: posterior and decision are the labelled placeholders (' + (LB.IMPORT_ERROR or 'unknown') + ')')
        # ---- playback controls -------------------------------------------------------------------------------------
        c1, c2, c3, c4, c5 = st.columns([0.9, 0.9, 2.3, 5.2, 0.9])
        if c1.button('Start replay' if not src.playing else 'Playing', type='primary', width='stretch', disabled=src.playing, key='play'):
            src.start(); st.rerun(scope='app')
        if c2.button('Pause', width='stretch', disabled=not src.playing, key='pause'):
            src.pause(); st.rerun(scope='app')
        speed = c3.segmented_control('Speed', options=list(ES.SPEEDS), format_func=lambda s: f'{s}x', default=int(src.speed) if int(src.speed) in ES.SPEEDS else 1, key='speed_ctl')
        if speed and float(speed) != src.speed:
            src.set_speed(float(speed)); st.session_state['speed'] = speed
        lap = c4.slider('Lap scrubber', src.cursor.first_lap, src.cursor.last_lap, value=src.cursor.lap, key=None)
        if lap != src.cursor.lap:
            was = src.playing; src.pause(); src.seek(int(lap)); st.session_state['lap'] = int(lap)
            st.rerun(scope='app' if was else 'fragment')
        if c5.button('Step +1', width='stretch', disabled=src.cursor.at_end or src.playing, key='step'):
            src.seek(src.cursor.lap + 1); st.session_state['lap'] = src.cursor.lap; st.rerun(scope='fragment')
        query_state.mirror()
        # ---- KPI strip -------------------------------------------------------------------------------------------
        if vm.kpis:
            cards.kpi_strip(vm.kpis)
        # ---- 2:1 hero ---------------------------------------------------------------------------------------------
        left, right = st.columns([2, 1], gap='medium')
        with left:
            st.plotly_chart(charts.forecast_vs_live(vm, presentation, estimator_label=label, projection=(orb or {}).get('projection')), width='stretch', config={'displayModeBar': False}, key='live_chart')
            chips = [badges.badge_html(f'estimator: {label}', 'live' if orb else 'placeholder'), badges.badge_html(f'prior: {vm.prior.source}', 'neutral')]
            if orb:
                chips.append(badges.badge_html(f"regime {orb['regime'].lower().replace('_', ' ')}", 'critical' if orb['regime'] in ('CLIFF', 'ACCELERATING_WEAR', 'ANOMALY') else 'neutral'))
                for w in orb.get('widening') or []:
                    chips.append(badges.badge_html(f"widened: {w['rule']} x{w['applied']:.2f}", 'decision'))
                chips.append(badges.badge_html(f"data cutoff {orb.get('data_cutoff', '—')} · no future data", 'neutral'))
            elif vm.state and vm.state.widened:
                chips.append(badges.badge_html(f'band widened after {vm.state.widen_reason}', 'decision'))
            note = LB.support_note(vm)
            if note:
                chips.append(badges.badge_html(f"support: 7.1 says {LB.support_status(vm)} · lock chips say {vm.support.overall_support_status} (both shown)", 'decision', note))
            chips.append(badges.compound_html(vm.state.compound if vm.state else vm.prior.compound, f'{(vm.state.compound if vm.state else vm.prior.compound).title()} · age {vm.state.tyre_age if vm.state else "—"}'))
            st.html('<div class="cs-chips">' + ''.join(chips) + '</div>')
            if orb and orb.get('changes'):
                st.html(cards.card_html('what this lap changed', '<div class="cs-list">' + ''.join(f'<div>{esc(c)}</div>' for c in orb['changes'][-3:]) + '</div>'))
        with right:
            st.html(decision_html(vm.decision, vm))
            st.html(cards.card_html('alternatives (ranked)' if orb else 'alternatives (lock)', alternatives_html(vm.decision, orb)))
        # ---- lower rail --------------------------------------------------------------------------------------------
        r1, r2, r3, r4 = st.columns(4, gap='small')
        with r1:
            st.html(cards.card_html('driver-feedback timeline' + (' · regime shift, telemetry corroboration' if orb else ''), feedback_html(vm)))
        with r2:
            st.plotly_chart(charts.temperature_history(vm.temp_history_lock, vm.temp_series, presentation), width='stretch', config={'displayModeBar': False}, key='temp_chart')
        with r3:
            if not presentation:
                st.html(cards.card_html('live tyre state (7.1) · feed quality' if orb else 'feed quality', state_panel_html(vm, src)))
            else:
                ts = (orb or {}).get('tyre_state') or {}
                st.html(cards.card_html('feed', cards.kv_html([('quality', ts.get('quality_status', vm.feed['status'])), ('sensor mode', ts.get('sensor_mode', VM.SENSOR_MODE)), ('latency', LB.latency_text(vm, replay_latency))])))
        with r4:
            st.html(cards.card_html('recommendation history · what changed', history_html(vm.history)))
        if orb and not presentation:
            top = (orb.get('recommendations') or [None])[0]
            if top:
                st.html(cards.card_html('7.2 live_recommendation record (rank 1)', cards.kv_html(LB.recommendation_rows(top), stack=False)))

    hero()
    shell.ready_marker('live')
