"""Route 3, Decision board: top three actions with target compound, pit lap, expected gain, downside, rejoin, why changed."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import asset_repository as A
from app_v2.services import view_models as VM
from app_v2.state import app_state
from app_v2.ui import shell, cards, badges, empty_states, banners
from app_v2.ui.formatting import secs, esc
from app_v2.pages.live_predictor import decision_html, history_html


def action_card(rank: int, title: str, compound: str | None, pit: str, gain: str, downside: str, rejoin: str, source: str, tone: str = 'neutral') -> str:
    tyre = badges.compound_html(compound) if compound else badges.badge_html('no compound change', 'neutral')
    grid = ''.join(f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in [('pit', pit), ('expected gain', gain), ('downside q10', downside), ('rejoin traffic', rejoin)])
    return f'<div class="cs-card cs-decision" style="border-left-color:var(--{ "decision" if rank == 1 else "border"})"><div class="status">action {rank}</div><div class="headline" style="font-size:1.2rem">{esc(title)}</div>{tyre}<div class="grid">{grid}</div><div class="cs-src">{esc(source)}</div></div>'


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
    vm = VM.build_live(lock, ev, driver, src.cursor, 'replay')
    common.header(ctx, 'decision', lap=vm.lap, n_laps=vm.n_laps, support=vm.support.overall_support_status, latency='replay')
    st.markdown(f'## Decision board · {ev} · {driver} · lap {vm.lap}')
    banners.placeholder_banner('ranked actions are the lock plan and its lock alternatives; expected gain is the lock delta_to_best; probability, downside and rejoin arrive with Workstream 8 (0.12). No recommendation changes silently: see the log.')
    d = vm.decision
    c1, c2, c3 = st.columns(3, gap='medium')
    with c1:
        st.html(decision_html(d, vm, vm.fixture_reco, vm.fixture_label))
    alts = d.alternatives + [None, None]
    for col, rank, a in ((c2, 2, alts[0]), (c3, 3, alts[1])):
        with col:
            if a is None:
                st.html(action_card(rank, 'no further alternative in lock', None, '—', '—', '—', '—', 'lock'))
            else:
                comps = [{'S': 'SOFT', 'M': 'MEDIUM', 'H': 'HARD'}.get(x, x) for x in a['plan'].split('-')]
                pits, acc = [], 0
                for s in a['stints'][:-1]:
                    acc += int(s); pits.append(str(acc))
                st.html(action_card(rank, f'{a["plan"]} · {a["stops"]} stop', comps[1] if len(comps) > 1 else None, 'laps ' + ', '.join(pits) if pits else 'no stop', f'{-a["delta_to_best_s"]:+.1f} s vs plan (lock)' if a.get('delta_to_best_s') is not None else '—', 'pending Workstream 8', 'not simulated (Phase 0)', f'lock.strategy.{ev} alternatives'))
    left, right = st.columns([3, 2], gap='large')
    with left:
        cards.section('Why the recommendation changed', 'Deterministic re-evaluation lap by lap: identical on scrub and on replay.')
        st.html(cards.card_html('', history_html(vm.history)))
    with right:
        cards.section('Live state feeding the board')
        s = vm.state
        st.html(cards.kv_html([('compound / age', f'{s.compound} / {s.tyre_age}' if s else '—'), ('posterior slope', f'{s.post_slope:+.3f} s/lap (PLACEHOLDER)' if s and s.post_slope is not None else '—'),
                               ('prior slope', f'{vm.prior.slope:+.3f} s/lap ({vm.prior.source})' if vm.prior.slope is not None else '—'), ('trend vs forecast', f'{s.trend_vs_prior:.2f}x' if s and s.trend_vs_prior else '—'),
                               ('kept laps in stint', s.kept_laps if s else '—'), ('driver reports', len(vm.feedback)), ('support', vm.support.overall_support_status)]))
        if vm.fixture_reco:
            fx = vm.fixture_reco
            st.html(cards.card_html('FIXTURE · Workstream 8 output shape', cards.kv_html([('action', fx['action']), ('pit window', f'{fx["pit_window"][0]} to {fx["pit_window"][1]}'), ('target', fx['target_compound']), ('p(gain)', f'{fx["probability_of_gain"]:.0%}'), ('change reason', fx['change_reason'])]), extra_class='raised'))
    shell.ready_marker('decision')
