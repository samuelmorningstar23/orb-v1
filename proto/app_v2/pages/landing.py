"""Landing: two doors (13.3). The user is never sent automatically from one mode to the other."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import view_models as VM
from app_v2.ui import shell, empty_states
from app_v2.ui.formatting import esc


def _status_html(items) -> str:
    return '<div class="cs-status">' + ''.join(f'<span class="item {"ok" if i.ok else "no"}" title="{esc(i.detail)}">{"●" if i.ok else "○"} {esc(i.label)}</span>' for i in items) + '</div>'


def render() -> None:
    ctx = common.context('landing')
    common.header(ctx, 'landing', session='Landing', support='—' if ctx.lock is None else 'lock loaded', latency='n/a')
    if ctx.lock is None:
        empty_states.missing_lock(); shell.ready_marker('landing'); return
    vm = VM.build_landing(ctx.lock)
    st.markdown('## Predict. Monitor. Decide. Prove.')
    st.markdown(f'<div class="cs-muted">Pre-race prior locked and hashed ({vm.forecast_hash6}) · live posterior every lap · ranked pit and compound actions · Race Twin proof. Two tools, two data boundaries, one frozen forecast.</div>', unsafe_allow_html=True)
    left, right = st.columns(2, gap='large')
    with left:
        st.html(f'<div class="cs-mode live"><h2>LIVE PREDICTOR</h2><div class="lead">Compare actual tyre behaviour against the locked pre-race forecast and receive updated pit and compound recommendations. Sees only what existed at the current timestamp; makes the call.</div>{_status_html(vm.live_status)}</div>')
        c1, c2, c3 = st.columns(3)
        if c1.button('Start historical replay', type='primary', width='stretch', key='btn_replay'):
            common.goto('live', mode='live')
        c2.button('Load recorded-live session', width='stretch', disabled=True, help='RecordedLive source arrives with Workstream 2 (task 0.9).', key='btn_recorded')
        c3.button('Connect live feed', width='stretch', disabled=True, help='Live adapter is Phase 1.', key='btn_live')
        st.markdown(f'<div class="cs-muted">Recorded races available for replay: {esc(", ".join(vm.race_files))}. Live forecast weekend: {esc(", ".join(vm.live_events) or "none")} (no race file yet: the forecast is shown, replay waits for a source).</div>', unsafe_allow_html=True)
    with right:
        st.html(f'<div class="cs-mode ghost"><h2>GHOST STRATEGY</h2><div class="lead">Audit a completed race, test alternative tyre strategies and inspect generalisation across supported drivers, circuits and weather. Sees the finished race; audits whether the model deserved to make the call.</div>{_status_html(vm.ghost_status)}</div>')
        c1, c2, c3 = st.columns(3)
        if c1.button('Historical audit', type='primary', width='stretch', key='btn_audit'):
            common.goto('ghost', mode='audit')
        if c2.button('Scenario explorer', width='stretch', key='btn_scenario'):
            common.goto('ghost', mode='scenario')
        if c3.button('Generalisation scorecard', width='stretch', key='btn_gen'):
            common.goto('generalisation', mode='audit')
        st.markdown(f'<div class="cs-muted">Scored weekends in the lock: {esc(", ".join(vm.scored_events))}.</div>', unsafe_allow_html=True)
    st.markdown('<div class="cs-muted" style="margin-top:16px">Defensible sentence: Orb v1 can be tested across any available driver, circuit and supported weather regime, and it abstains when the selected conditions fall outside the evidence.</div>', unsafe_allow_html=True)
    shell.ready_marker('landing')
