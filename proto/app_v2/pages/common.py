"""Shared page context: lock, routing state, sidebar controls, header rendering. Pages call `context(mode)`."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import streamlit as st
from app_v2.services import asset_repository as A
from app_v2.services import replay_service as RS
from app_v2.services import view_models as VM
from app_v2.state import query_state, app_state
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


def bootstrap() -> Ctx:
    """Runs once per script run from the shell: syncs query params and renders the sidebar."""
    lock = app_state.lock()
    events = lock.event_names() if lock else []
    q = query_state.sync(events)
    s = st.session_state
    with st.sidebar:
        st.markdown('**ORB V1 · controls**')
        present = st.toggle('Presentation mode', value=bool(s.get('present', False)), help='Hides engineering controls and enlarges the decisive visuals.')
        if present != bool(s.get('present', False)):
            query_state.set_state(present=present)
            st.rerun()
        if lock is None:
            st.caption('No lock loaded.')
            return Ctx(None, '', None, None, present, s.get('mode', 'live'), q)
        race_files = set(A.available_race_events())
        ev = st.selectbox('Weekend', events, index=events.index(s['ev']) if s.get('ev') in events else 0,
                          format_func=lambda e: f"{e}  ·  {'LIVE forecast' if lock.is_live_event(e) else 'scored'}{'' if e in race_files else '  ·  no race file'}")
        if ev != s.get('ev'):
            query_state.set_state(ev=ev, lap=None, drv=None, cmp=None)
            st.rerun()
        drivers = RS.drivers_for(ev)
        drv = None
        if drivers:
            default = s.get('drv') if s.get('drv') in drivers else app_state.default_driver(lock, ev)
            drv = st.selectbox('Driver (replay / audit)', drivers, index=drivers.index(default) if default in drivers else 0)
            if drv != s.get('drv'):
                query_state.set_state(drv=drv, lap=None)
                st.rerun()
        comps = lock.compounds_for(ev)
        cmp_default = s.get('cmp') if s.get('cmp') in comps else (comps[0] if comps else None)
        cmp = st.selectbox('Forecast compound (pre-race view)', comps, index=comps.index(cmp_default) if cmp_default in comps else 0) if comps else None
        if cmp != s.get('cmp'):
            query_state.set_state(cmp=cmp)
        st.divider()
        st.caption(f"lock {lock.version} · {lock.generated_at}\n\nforecast hash {lock.forecast_hash[:12]} ({lock.forecast_hash_source})")
        st.caption(f'lock file {lock.asset.short_hash} · {lock.asset.sidecar_status}')
        if drv and ev in race_files:
            a = A.race_csv_asset(ev); st.caption(f'race file {ev}_R.csv sha256 {a.short_hash} · {a.sidecar_status}')
        st.caption('offline build: no CDN, API or font download')
    return Ctx(lock, s.get('ev', ''), s.get('drv'), s.get('cmp'), present, s.get('mode', 'live'), q)


def context(mode: str) -> Ctx:
    s = st.session_state
    lock = app_state.lock()
    return Ctx(lock, s.get('ev', ''), s.get('drv'), s.get('cmp'), bool(s.get('present', False)), s.get('mode', 'live'), {})


def header(ctx: Ctx, mode: str, lap: Optional[int] = None, n_laps: Optional[int] = None, support: str = 'PENDING', latency: str = '—', session: Optional[str] = None) -> None:
    vm = VM.build_header(ctx.lock, mode, ctx.event, session or SESSION_LABEL.get(ctx.mode, 'Race'), lap, n_laps, support, latency)
    shell.render_header(vm)


def require_lock(ctx: Ctx, mode: str) -> bool:
    if ctx.lock is None:
        header(ctx, mode); empty_states.missing_lock(); shell.ready_marker(mode); return False
    return True


def goto(key: str, **state) -> None:
    pages = st.session_state.get('_pages', {})
    query_state.set_state(**state)
    if key in pages:
        st.switch_page(pages[key])
