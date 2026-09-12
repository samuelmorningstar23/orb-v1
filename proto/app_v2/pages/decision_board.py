"""Route 3, Decision board: the ranked actions (7.2 records) with target compound and set, pit window, expected gain,
downside, rejoin traffic and why the recommendation changed. Same view model as the Live Predictor (services/live_bridge)."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import asset_repository as A
from app_v2.services import live_bridge as LB
from app_v2.services import view_models as VM
from app_v2.state import app_state
from app_v2.ui import shell, cards, badges, empty_states, banners
from app_v2.ui.formatting import esc
from app_v2.pages.live_predictor import decision_html, history_html


def action_card(rank: int, r: dict, source: str) -> str:
    w = r.get('pit_window'); rj = r.get('rejoin_context') or {}
    title = r['action'].replace('_', ' ') + (f" laps {w[0]}-{w[1]}" if w and w[0] != w[1] else (f" lap {w[0]}" if w else ''))
    tyre = badges.compound_html(r['target_compound']) if r.get('target_compound') else badges.badge_html('no compound change', 'neutral')
    ts = r.get('target_set') or {}
    rejoin = f"P{rj['position_now']} → ~P{rj['projected_rejoin_position']} · {rj['cars_within_pit_loss']} cars within pit loss · {rj['traffic_density']}" if rj.get('position_now') is not None else rj.get('note', '—')
    grid = ''.join(f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in [
        ('target set', f"{ts.get('set_id')} ({ts.get('status')})" if ts else '—'), ('expected gain', f"{r['expected_gain_median']:+.1f} s (q10 {r['expected_gain_q10']:+.1f}, q90 {r['expected_gain_q90']:+.1f})"),
        ('probability of gain', f"{100 * r['probability_of_gain']:.0f}%"), ('rejoin traffic', rejoin)])
    reasons = ''.join(f'<li>{esc(x)}</li>' for x in (r.get('reasons') or [])[:3])
    return f'<div class="cs-card cs-decision" style="border-left-color:var(--{"decision" if rank == 1 else "border"})"><div class="status">action {rank}{" · changed" if r.get("changed_since_last_update") else ""}</div><div class="headline" style="font-size:1.2rem">{esc(title)}</div>{tyre}<div class="grid">{grid}</div><ul>{reasons}</ul><div class="cs-src">{esc(source)}</div></div>'


def placeholder_card(rank: int, a: dict | None, ev: str) -> str:
    if a is None:
        return f'<div class="cs-card cs-decision" style="border-left-color:var(--border)"><div class="status">action {rank}</div><div class="headline" style="font-size:1.2rem">no further alternative in lock</div></div>'
    comps = [{'S': 'SOFT', 'M': 'MEDIUM', 'H': 'HARD'}.get(x, x) for x in a['plan'].split('-')]
    pits, acc = [], 0
    for s in a['stints'][:-1]:
        acc += int(s); pits.append(str(acc))
    grid = ''.join(f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in [('pit', 'laps ' + ', '.join(pits) if pits else 'no stop'), ('expected gain', f'{-a["delta_to_best_s"]:+.1f} s vs plan (lock)' if a.get('delta_to_best_s') is not None else '—'), ('downside q10', 'pending'), ('rejoin traffic', 'not simulated')])
    tyre = badges.compound_html(comps[1]) if len(comps) > 1 else ''
    return f'<div class="cs-card cs-decision" style="border-left-color:var(--border)"><div class="status">action {rank} · PLACEHOLDER</div><div class="headline" style="font-size:1.2rem">{esc(a["plan"])} · {a["stops"]} stop</div>{tyre}<div class="grid">{grid}</div><div class="cs-src">lock.strategy.{esc(ev)} alternatives</div></div>'


def render() -> None:
    ctx = common.context('decision')
    if not common.require_lock(ctx, 'decision'):
        return
    lock, ev = ctx.lock, ctx.event
    st.session_state['mode'] = 'live'
    if not A.race_csv_asset(ev).exists:
        common.header(ctx, 'decision', n_laps=lock.n_laps(ev), support='—', latency='no feed'); empty_states.missing_feed(ev); shell.ready_marker('decision'); return
    driver = ctx.driver or app_state.default_driver(lock, ev)
    src = app_state.source_for(ev, driver, lock.n_laps(ev))
    if src is None:
        common.header(ctx, 'decision'); empty_states.missing_feed(ev); shell.ready_marker('decision'); return
    src.poll()
    vm = LB.build(lock, ev, driver, src.cursor, 'replay')
    orb = getattr(vm, 'orb_live', None)
    common.header(ctx, 'decision', lap=vm.lap, n_laps=vm.n_laps, support=LB.support_status(vm), latency=LB.latency_text(vm, 'replay'))
    st.markdown(f'## Decision board · {ev} · {driver} · lap {vm.lap}')
    if orb:
        b = orb.get('baseline') or {}
        banners.note_banner(f"{orb['estimator_label']} · ranked by decision/optimizer.py re-run from lap {vm.lap} · gains measured against the pre-race plan {b.get('plan', '—')} ({b.get('schedule', '—')}, {b.get('stops_remaining', '—')} stops remaining) · rival strategy responses are not simulated · no recommendation changes silently")
    else:
        banners.placeholder_banner('ranked actions are the lock plan and its lock alternatives; probability, downside and rejoin arrive with the live package (not importable here).')
    d = vm.decision
    c1, c2, c3 = st.columns(3, gap='medium')
    with c1:
        st.html(decision_html(d, vm))
    recs = (orb or {}).get('recommendations') or []
    src_label = f"7.2 live_recommendation · decision/optimizer.py · {(orb or {}).get('model_version', '')}"
    for col, rank in ((c2, 2), (c3, 3)):
        with col:
            if recs:
                if len(recs) >= rank:
                    st.html(action_card(rank, recs[rank - 1], src_label))
                else:
                    st.html(f'<div class="cs-card cs-decision" style="border-left-color:var(--border)"><div class="status">action {rank}</div><div class="headline" style="font-size:1.2rem">no further legal action</div><div class="cs-src">{esc(src_label)}</div></div>')
            else:
                alts = d.alternatives + [None, None]
                st.html(placeholder_card(rank, alts[rank - 2], ev))
    left, right = st.columns([3, 2], gap='large')
    with left:
        cards.section('Why the recommendation changed', 'Laps on which the top action changed, with the observation that moved the call.')
        st.html(cards.card_html('', history_html(vm.history)))
        if recs:
            cards.section('Constraints on every action (7.2)')
            st.html('<div class="cs-list">' + ''.join(f'<div>{esc(c)}</div>' for c in (recs[0].get('constraints') or [])) + '</div>')
    with right:
        cards.section('Live state feeding the board')
        s = vm.state
        rows = [('compound / age', f'{s.compound} / {s.tyre_age}' if s else '—'), ('posterior slope', f'{s.post_slope:+.3f} ± {s.post_sd:.3f} s/lap' if s and s.post_slope is not None else '—'),
                ('prior slope', f'{vm.prior.slope:+.3f} s/lap ({vm.prior.source})' if vm.prior.slope is not None else '—'), ('trend vs forecast', f'{s.trend_vs_prior:+.2f}x' if s and s.trend_vs_prior is not None else '—'),
                ('clean laps in stint', s.kept_laps if s else '—'), ('driver reports', len(vm.feedback)), ('support', LB.support_status(vm)), ('estimator', LB.estimator_label_short(vm))]
        if orb:
            ts = orb['tyre_state']
            rows += [('regime', orb['regime']), ('useful laps q10/q50/q90', f"{ts['useful_laps_q10']:.0f} / {ts['useful_laps_q50']:.0f} / {ts['useful_laps_q90']:.0f}"), ('cliff 3 / 5 laps', f"{100 * ts['cliff_probability_3_laps']:.0f}% / {100 * ts['cliff_probability_5_laps']:.0f}% · {LB.CLIFF_LABEL}"), ('data cutoff', orb.get('data_cutoff', '—'))]
        st.html(cards.kv_html(rows, stack=True))
    shell.ready_marker('decision')
