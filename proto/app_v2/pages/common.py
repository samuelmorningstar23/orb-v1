"""Shared page context: lock, routing state, sidebar controls, header rendering. Pages call `context(mode)`."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import streamlit as st
from app_v2.services import asset_repository as A
from app_v2.services import counterfactual_repository as CF
from app_v2.services import replay_service as RS
from app_v2.services import view_models as VM
from app_v2.state import query_state, app_state
from app_v2.components import race_twin as RT
from app_v2.ui import shell, empty_states

SESSION_LABEL = {'live': 'Race (replay)', 'audit': 'Race (post-race audit)', 'scenario': 'Race (scenario)'}


@dataclass
class Ctx:
    lock: object
    event: str
    driver: Optional[str]
    compound: Optional[str]
    presentation: bool
    mode: str
    q: dict


def bootstrap(page: str = "") -> Ctx:
    """Runs once per script run from the shell: syncs query params and renders the sidebar."""
    lock = app_state.lock()
    events = lock.event_names() if lock else []
    q = query_state.sync(events)
    s = st.session_state
    if lock and page == 'ghost':
        with_sims = CF.events_with_scenarios()
        # Keep the strategy workspace focused on races with a prepared analysis.
        events = [ev for ev in events
                  if lock.event_meta(ev).get('completed')
                  and A.race_csv_asset(ev).exists
                  and ev in with_sims]
        if not events:
            st.info('No race visualisations are available yet. Choose another page above.')
            st.stop()
        if s.get('ev') not in events:
            previous = s.get('ev')
            fallback = 'Monza' if 'Monza' in events else events[0]
            query_state.set_state(ev=fallback, drv=None, lap=None, cmp=None)
            s['_ghost_event_notice'] = f'{previous} has no prepared simulation and no race visualisation. Showing {fallback}.'
            st.rerun()
    elif page != 'ghost':
        s.pop('_ghost_event_notice', None)
    with st.sidebar:
        st.markdown('**Race workspace**')
        present = st.toggle('Presentation mode', value=bool(s.get('present', False)), help='Hides engineering controls and enlarges the decisive visuals.')
        if present != bool(s.get('present', False)):
            query_state.set_state(present=present)
            st.rerun()
        if lock is None:
            st.caption('No lock loaded.')
            return Ctx(None, '', None, None, present, s.get('mode', 'live'), q)
        race_files = set(A.available_race_events())
        ev = st.selectbox('Weekend', events, index=events.index(s['ev']) if s.get('ev') in events else 0,
                          format_func=lambda e: f"{e} · {'pre-race' if e not in race_files else 'replay'}", help='Choose a weekend. Pre-race weekends show the frozen tyre forecast; replay weekends reveal a recorded race lap by lap.')
        if ev != s.get('ev'):
            query_state.set_state(ev=ev, lap=None, drv=None, cmp=None)
            st.rerun()
        drivers = RS.drivers_for(ev)
        if page == 'ghost':
            prepared_drivers = {sc.driver for sc in CF.scenarios_for(ev, curve_source=CF.PRE_RACE if s.get('mode') == 'scenario' else CF.RACE_REFERENCE)}
            drivers = [driver for driver in drivers if driver in prepared_drivers]
        drv = None
        if drivers:
            default = s.get('drv') if s.get('drv') in drivers else app_state.default_driver(lock, ev)
            drv = st.selectbox('Driver', drivers, index=drivers.index(default) if default in drivers else 0, help='All graphs and strategy results follow this driver. Ghost Strategy lists drivers with a prepared analysis.')
            if drv != s.get('drv'):
                query_state.set_state(drv=drv, lap=None)
                st.rerun()
        comps = lock.compounds_for(ev)
        cmp_default = s.get('cmp') if s.get('cmp') in comps else (comps[0] if comps else None)
        cmp = cmp_default
        if cmp != s.get('cmp'):
            query_state.set_state(cmp=cmp)
        st.caption('Recorded races replay locally. Madrid is a frozen pre-race forecast.')
        with st.expander('Data & model details'):
            st.caption(f"lock {lock.version} · {lock.generated_at}")
            st.caption(f"forecast hash {lock.forecast_hash} ({lock.forecast_hash_source})")
            st.caption(f'lock file {lock.asset.short_hash} · {lock.asset.sidecar_status}')
            if drv and ev in race_files:
                a = A.race_csv_asset(ev)
                st.caption(f'race file {ev}_R.csv sha256 {a.short_hash} · {a.sidecar_status}')
            st.caption('Public telemetry proxies; tyre pressures and temperatures are not measured. Runs offline; no CDN, API or font download.')
    if page == 'ghost' and (notice := s.pop('_ghost_event_notice', None)):
        st.info(notice)
    return Ctx(lock, s.get('ev', ''), s.get('drv'), s.get('cmp'), present, s.get('mode', 'live'), q)


def context(mode: str) -> Ctx:
    s = st.session_state
    lock = app_state.lock()
    return Ctx(lock, s.get('ev', ''), s.get('drv'), s.get('cmp'), bool(s.get('present', False)), s.get('mode', 'live'), {})


def header(ctx: Ctx, mode: str, lap: Optional[int] = None, n_laps: Optional[int] = None, support: str = 'PENDING', latency: str = '—', session: Optional[str] = None) -> None:
    vm = VM.build_header(ctx.lock, mode, ctx.event, session or SESSION_LABEL.get(ctx.mode, 'Race'), lap, n_laps, support, latency)
    shell.render_header(vm, ctx.presentation)


def require_lock(ctx: Ctx, mode: str) -> bool:
    if ctx.lock is None:
        header(ctx, mode); empty_states.missing_lock(); shell.ready_marker(mode); return False
    return True


def goto(key: str, **state) -> None:
    pages = st.session_state.get('_pages', {})
    query_state.set_state(**state)
    if key in pages:
        st.switch_page(pages[key])
