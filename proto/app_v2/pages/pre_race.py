"""Frozen pre-race forecast and plans, with optional technical evidence."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.ui import shell, cards, badges, charts, empty_states
from app_v2.ui.formatting import spl, band, esc


def render() -> None:
    ctx = common.context('prerace')
    if not common.require_lock(ctx, 'prerace'):
        return
    lock, ev = ctx.lock, ctx.event
    common.header(ctx, 'prerace', session='Pre-race')
    st.markdown(f'## {ev} · tyre forecast')
    st.caption('Expected pace loss per additional lap of tyre age. Shaded bands show uncertainty.')
    if lock.is_live_event(ev):
        st.caption('Frozen before the race. Built from practice and qualifying; no race results used.')
    forecasts = [lock.forecast_for(ev, c) for c in lock.compounds_for(ev)]
    if not forecasts:
        empty_states.empty('Forecast unavailable', 'No forecast was issued for this weekend.')
        shell.ready_marker('prerace'); return
    for col, f in zip(st.columns(len(forecasts)), forecasts):
        with col:
            cards.kpi_card(f.compound.title(), spl(f.prediction), f'90% band {band(*f.band90)} · {f.n_prac or "—"} clean laps · ' + ('issued' if f.issued else 'withheld; fallback applies'), 'live' if f.issued else 'decision', unit='s/lap')
    left, right = st.columns([2, 1], gap='medium')
    with left:
        st.plotly_chart(charts.pre_race_curves(forecasts, lock.n_laps(ev)), width='stretch', config={'displayModeBar': False})
    with right:
        plan = lock.primary_plan(ev)
        if plan:
            body = f'<div class="headline">{esc(plan.plan)}</div>'
            body += '<p>' + ' → '.join(str(x) + ' laps' for x in plan.stints) + '</p>'
            body += '<div class="cs-muted">Pit after lap ' + ', '.join(map(str, plan.pit_laps)) + '. Modelled tyre time; traffic and safety cars are not simulated.</div>'
            st.html(cards.card_html('Suggested plan', body, extra_class='cs-decision'))
        else:
            empty_states.no_strategy(ev)
        if st.button('Open replay', width='stretch'):
            from app_v2.pages.landing import replay_target
            from app_v2.services.asset_repository import available_race_events
            target = replay_target(ev, available_race_events())
            if target:
                common.goto('live', ev=target, drv=None, lap=1, mode='live')
    with st.expander('Alternative plans & assumptions'):
        views = lock.plan_views(ev)
        rows = [[name, v.plan, ' / '.join(map(str, v.stints)), ', '.join(map(str, v.pit_laps))] for name, v in views.items()]
        st.html(cards.table_html(['Curve assumption', 'Plan', 'Stint lengths', 'Pit laps'], rows))
        a = lock.strategy_assumptions(ev)
        st.caption(f"Pit loss {a['pit_loss']:.0f} s. Compound offsets: " + ', '.join(f'{k.lower()} {v:+.2f} s' for k, v in a['offsets'].items()) + '. Assumed set inventory; no live tyre-set feed.')
        for f in forecasts:
            st.caption(f'{f.compound.title()}: {f.basis}. Gate: {f.gate}.')
    with st.expander('Forecast provenance'):
        st.caption(f'Forecast generated {lock.generated_at}. Hash {lock.forecast_hash}.')
        if ev == 'Madrid':
            from app_v2.services import paths as P
            from app_v2.services import asset_repository as A
            fc, asset = A.load_json_asset(P.OUT_DIR / 'forecast_Madrid_2026.json')
            if fc:
                st.caption(f"Published {fc.get('issued_at', '—')}. JSON SHA256 {asset.sha256}.")
                st.download_button('Download frozen forecast', (P.OUT_DIR / 'forecast_Madrid_2026.pdf').read_bytes(), file_name='forecast_Madrid_2026.pdf', mime='application/pdf')
    shell.ready_marker('prerace')
