"""Route 2, Live Predictor hero screen (13.4). The whole hero lives in one fragment so replay never full-reruns."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import asset_repository as A
from app_v2.services import event_service as ES
from app_v2.services import view_models as VM
from app_v2.state import app_state, query_state
from app_v2.ui import shell, cards, badges, charts, empty_states, banners
from app_v2.ui.formatting import spl, secs, pct, esc, temp

FRAGMENT_PERIOD_S = 0.7


def decision_html(d, vm, fixture=None, fixture_label='') -> str:
    changed = 'changed' if d.action == 'REVIEW' else ''
    gain = f'{secs(d.expected_gain_s)} s vs {d.gain_vs} (lock)' if d.expected_gain_s is not None else '—'
    prob = 'pending Workstream 8'
    grid = [('expected gain', gain), ('probability of gain', prob), ('downside q10', 'pending Workstream 8'), ('rejoin traffic', d.rejoin_context)]
    g = ''.join(f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in grid)
    reasons = ''.join(f'<li>{esc(r)}</li>' for r in d.reasons) or '<li>no change</li>'
    status = d.status + (' · changed this lap' if d.changed_since_last_update else '')
    tyre = badges.compound_html(d.target_compound) if d.target_compound else ''
    return (f'<div class="cs-card cs-decision {changed}" role="region" aria-label="decision"><div class="status">{esc(status)}</div><div class="headline">{esc(d.headline)}</div>{tyre}'
            f'<div class="grid">{g}</div><div class="cs-card-title">why this changed</div><ul>{reasons}</ul><div class="cs-src">{esc(d.rule_label)} · plan source {esc(d.plan_source)}</div></div>')


def alternatives_html(d) -> str:
    if not d.alternatives:
        return '<div class="cs-muted">no alternatives in lock</div>'
    out = ''
    for a in d.alternatives:
        delta = f'+{a["delta_to_best_s"]:.1f} s' if a.get('delta_to_best_s') is not None else '—'
        out += f'<div class="cs-alt"><span>{esc(a["plan"])} · stints {esc("/".join(map(str, a["stints"])))} · {a["stops"]} stop</span><span class="d">{delta} vs plan (lock)</span></div>'
    return out


def history_html(history) -> str:
    if not history:
        return '<div class="cs-muted">no recommendation yet</div>'
    rows = ''.join(f'<div><span class="lap">L{d.lap:>2}</span><span class="hot">{esc(d.headline)}</span> · {esc(d.status)}</div>' for d in history[-8:])
    return f'<div class="cs-list">{rows}</div>'


def feedback_html(feedback) -> str:
    if not feedback:
        return '<div class="cs-muted">no driver feedback logged for this session</div>'
    rows = ''.join(f'<div><span class="lap">L{int(f["lap"]):>2}</span><span class="hot">{esc(f["symptom"])}</span> {esc(f["axle"])} {esc(f["corner_phase"])} · {f["severity"]}/5 {esc(f["trend"])}' + ('' if f.get('engineer_confirmed') else ' · unconfirmed') + '</div>' for f in feedback[-8:])
    return f'<div class="cs-list">{rows}</div>'


def feed_html(vm, src) -> str:
    q = vm.feed; c = vm.corrections
    pairs = [('status', q['status']), ('source', src.source_name), ('sensor mode', VM.SENSOR_MODE), ('position samples', q['pos_distinct'] if q['pos_distinct'] is not None else '—'),
             ('stale share', pct(q['stale_share']) if q['stale_share'] is not None else '—'), ('missing channels', ', '.join(q['missing_channels'])),
             ('fuel prior removed', f'{c.fuel_s_per_lap:.3f} s/lap (lock rules)'), ('race evolution', 'not in lock for R: not applied' if not vm.evolution_applied else f'{c.evolution_s_per_min:+.4f} s/min (lock)'),
             ('traffic rule', f'kept if <= {c.traffic_max:.0%} of lap in traffic'), ('race file', f'{vm.asset.short_hash} · {vm.asset.sidecar_status}')]
    return cards.kv_html(pairs, stack=True)


def forecast_only(ctx, lock, ev) -> None:
    sup = VM.SS.support_for(lock, ev, None, ctx.compound)
    common.header(ctx, 'live', n_laps=lock.n_laps(ev), support=sup.overall_support_status, latency='no feed')
    empty_states.missing_feed(ev)
    comps = lock.compounds_for(ev)
    if comps:
        cards.section('Pre-race forecast for this weekend (lock)', 'The prior the live posterior will start from once a feed exists.')
        cols = st.columns(len(comps))
        for col, c in zip(cols, comps):
            f = lock.forecast_for(ev, c)
            with col:
                cards.kpi_card(f'{c} FORECAST', f'{spl(f.prediction)} s/lap', f'90% band {spl(f.band90[0])} to {spl(f.band90[1])} · ' + ('issued' if f.issued else 'withheld → fallback'), 'live' if f.issued else 'decision', f.source)
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
        latency_text = f'{lat:.1f} s (replay)' if lat is not None else 'replay idle'
        vm = VM.build_live(lock, ev, driver, src.cursor, latency_text)
        common.header(ctx, 'live', lap=vm.lap, n_laps=vm.n_laps, support=vm.support.overall_support_status, latency=latency_text)
        # ---- playback controls -------------------------------------------------------------------------------------
        c1, c2, c3, c4, c5 = st.columns([0.9, 0.9, 2.3, 5.2, 0.9])
        if c1.button('Start replay' if not src.playing else 'Playing', type='primary', use_container_width=True, disabled=src.playing, key='play'):
            src.start(); st.rerun(scope='app')
        if c2.button('Pause', use_container_width=True, disabled=not src.playing, key='pause'):
            src.pause(); st.rerun(scope='app')
        speed = c3.segmented_control('Speed', options=list(ES.SPEEDS), format_func=lambda s: f'{s}x', default=int(src.speed) if int(src.speed) in ES.SPEEDS else 1, key='speed_ctl')
        if speed and float(speed) != src.speed:
            src.set_speed(float(speed)); st.session_state['speed'] = speed
        lap = c4.slider('Lap scrubber', src.cursor.first_lap, src.cursor.last_lap, value=src.cursor.lap, disabled=False, key=None)
        if lap != src.cursor.lap:
            was = src.playing; src.pause(); src.seek(int(lap)); st.session_state['lap'] = int(lap)
            if was:
                st.rerun(scope='app')
            else:
                st.rerun(scope='fragment')
        if c5.button('Step +1', use_container_width=True, disabled=src.cursor.at_end or src.playing, key='step'):
            src.seek(src.cursor.lap + 1); st.session_state['lap'] = src.cursor.lap; st.rerun(scope='fragment')
        query_state.mirror()
        # ---- KPI strip -------------------------------------------------------------------------------------------
        cards.kpi_strip(vm.kpis)
        # ---- 2:1 hero ---------------------------------------------------------------------------------------------
        left, right = st.columns([2, 1], gap='medium')
        with left:
            st.plotly_chart(charts.forecast_vs_live(vm, presentation), use_container_width=True, config={'displayModeBar': False}, key='live_chart')
            st.html('<div class="cs-chips">' + badges.badge_html('posterior: PLACEHOLDER (Workstream 8 pending)', 'placeholder') + badges.badge_html(f'prior: {vm.forecast.source}', 'neutral') +
                    badges.badge_html('corrections: lock rules', 'neutral') + (badges.badge_html(f'band widened after {vm.state.widen_reason}', 'decision') if vm.state and vm.state.widened else '') +
                    badges.compound_html(vm.state.compound if vm.state else vm.prior.compound, f'{(vm.state.compound if vm.state else vm.prior.compound).title()} · age {vm.state.tyre_age if vm.state else "—"}') + '</div>')
        with right:
            st.html(decision_html(vm.decision, vm, vm.fixture_reco, vm.fixture_label))
            st.html(cards.card_html('alternatives (lock)', alternatives_html(vm.decision)))
        # ---- lower rail --------------------------------------------------------------------------------------------
        r1, r2, r3, r4 = st.columns(4, gap='small')
        with r1:
            st.html(cards.card_html('driver-feedback timeline', feedback_html(vm.feedback)))
        with r2:
            st.plotly_chart(charts.temperature_history(vm.temp_history_lock, vm.temp_series, presentation), use_container_width=True, config={'displayModeBar': False}, key='temp_chart')
        with r3:
            if not presentation:
                st.html(cards.card_html('feed quality', feed_html(vm, src)))
            else:
                st.html(cards.card_html('feed', cards.kv_html([('status', vm.feed['status']), ('sensor mode', VM.SENSOR_MODE), ('latency', latency_text)])))
        with r4:
            st.html(cards.card_html('recommendation history · what changed', history_html(vm.history)))
        if vm.fixture_reco and not presentation:
            fx = vm.fixture_reco
            banners.fixture_banner(f'shape of Workstream 8 output: {fx["action"]} window {fx["pit_window"]} {fx["target_compound"]} p(gain) {fx["probability_of_gain"]:.0%} · "{fx["change_reason"]}" ({vm.fixture_label}, not this race)')

    hero()
    shell.ready_marker('live')
