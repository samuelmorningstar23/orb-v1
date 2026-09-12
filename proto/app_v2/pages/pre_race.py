"""Route 1, Pre-race plan: compound curves and bands, strategy tree, pit windows, scenarios, priors, inventory."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import view_models as VM
from app_v2.ui import shell, cards, badges, charts, empty_states, banners
from app_v2.ui.formatting import spl, secs, band, esc


def render() -> None:
    ctx = common.context('prerace')
    if not common.require_lock(ctx, 'prerace'):
        return
    lock, ev = ctx.lock, ctx.event
    sup = VM.SS.support_for(lock, ev, ctx.driver, ctx.compound)
    common.header(ctx, 'prerace', n_laps=lock.n_laps(ev), support=sup.overall_support_status, session='Pre-race', latency='n/a')
    meta = lock.event_meta(ev)
    st.markdown(f'## {ev}: pre-race plan' + ('  ·  LIVE forecast weekend' if lock.is_live_event(ev) else '  ·  forecast as issued on Friday, scored on Sunday'))
    if lock.is_live_event(ev):
        banners.note_banner('FORECAST · issued from practice data only; nothing here has seen the race. Scored after the race with the same estimator.')
    else:
        banners.audit_banner()
    comps = lock.compounds_for(ev); forecasts = [lock.forecast_for(ev, c) for c in comps]
    if not forecasts:
        empty_states.pending('forecast', 'the lock (no compounds for this weekend)')
    cols = st.columns(max(len(forecasts), 1))
    for col, f in zip(cols, forecasts):
        with col:
            body = badges.compound_html(f.compound) + (badges.badge_html('issued', 'live') if f.issued else badges.badge_html('withheld → fallback', 'decision'))
            body += f'<div class="cs-kpi-value" style="margin-top:6px">{spl(f.prediction)} s/lap</div>'
            body += f'<div class="cs-kpi-sub">90% band {band(*f.band90)} · {f.n_prac or "—"} clean laps</div><div class="cs-muted">{esc(f.basis)}</div>'
            if not f.issued:
                body += f'<div class="cs-muted">gate: {esc(f.gate)}</div>'
            if f.observed is not None:
                body += f'<div class="cs-muted">race observed {spl(f.observed)} · error {spl(f.err)} · {"covered" if f.covered else "outside band"}</div>'
            cards.card('', body)
    if forecasts:
        st.plotly_chart(charts.pre_race_curves(forecasts, lock.n_laps(ev)), use_container_width=True, config={'displayModeBar': False})
    left, right = st.columns([3, 2], gap='large')
    with left:
        cards.section('Strategy tree (lock)', 'Linear degradation, pit loss and compound offsets from the lock; no traffic, safety car or weather.')
        views = lock.plan_views(ev)
        if not views:
            empty_states.no_strategy(ev)
        else:
            a = lock.strategy_assumptions(ev)
            rows = []
            for name, v in views.items():
                cost = f'+{v.cost_under_truth_s:.1f} s' if v.cost_under_truth_s is not None else 'race pending'
                rows.append([name, v.plan, ' / '.join(map(str, v.stints)), v.stops, ', '.join(f'{k} {x:.0f}' for k, x in v.crossover.items()) or '—', ', '.join(map(str, v.pit_laps)) or '—', cost])
            st.html(cards.table_html(['Curve', 'Best plan', 'Stint lengths', 'Stops', 'Crossover age', 'Pit laps', 'Cost under race-observed curves'], rows, numeric_cols=(3, 6)))
            src = a['offsets_source'] if isinstance(a['offsets_source'], str) else ', '.join(f'{c.lower()} {v}' for c, v in a['offsets_source'].items())
            st.markdown(f'<div class="cs-muted">Assumptions: pit loss {a["pit_loss"]:.0f} s; offsets ' + ', '.join(f'{c.lower()} {secs(v)}' for c, v in a['offsets'].items()) + f' ({esc(src)}). {esc(a.get("note") or "")}</div>', unsafe_allow_html=True)
            t = next((v for v in views.values() if v.best_under_truth), None)
            if t:
                st.markdown(f'<div class="cs-muted">Best plan under the race-observed curves: {t.best_under_truth["plan"]} with stints {" / ".join(map(str, t.best_under_truth["stints"]))}.</div>', unsafe_allow_html=True)
            cards.section('One-stop versus two-stop probability', 'Pending: strategy-tree probabilities arrive with the counterfactual core and the optimiser.')
            p = lock.primary_plan(ev)
            st.html(cards.kv_html([('central plan', f'{p.plan} ({p.stops} stop)'), ('band-edge plans', ', '.join(f'{n}: {v.plan}' for n, v in views.items() if 'band' in n) or 'not in lock for scored weekends'), ('probability', 'pending Workstream 8')]))
    with right:
        cards.section('Weather scenarios (supported only)')
        rows = [[s['label'], f"{s['track_temp']:.1f} °C" if s['track_temp'] is not None else '—', s['support'], 'yes' if s['available'] else 'unavailable'] for s in VM.scenario_table(lock, ev, ctx.driver, comps[0] if comps else 'MEDIUM')]
        st.html(cards.table_html(['Scenario', 'Track temp', 'Support', 'Available'], rows))
        cards.section('Weekend context (lock events)')
        tt = meta.get('track_temp') or {}
        st.html(cards.kv_html([('format', meta.get('format', '—')), ('sessions', ', '.join(meta.get('sessions', []))), ('clean long-run laps', f"{meta.get('practice_laps_clean', '—')} of {meta.get('practice_laps_total', '—')}"), ('long runs', meta.get('practice_runs', '—')),
                               ('track temperature', (' · '.join(f'{k} {v:.1f}' for k, v in tt.items()) + ' °C') if tt else '—'), ('rain', ', '.join(k for k, v in (meta.get('rain') or {}).items() if v) or 'none'), ('tyres', meta.get('tyres') or '—'),
                               ('energy price of lap time', f"{meta.get('beta_practice_s_per_MJ', 0):+.2f} s/MJ")]))
        cards.section('Driver-specific prior', 'Phase 2: style and outcome profile with hierarchical shrinkage. Population prior applies until then.')
        st.html(badges.badge_html('population prior · Phase 2 pending', 'placeholder'))
        cards.section('Tyre inventory', 'Placeholder until Phase 1: sets loaded = true by convention.')
        st.html(badges.badge_html('available sets: placeholder', 'placeholder'))
    shell.ready_marker('prerace')
