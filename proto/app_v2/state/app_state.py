"""Session-scoped objects: the lock view, replay cursors and event sources keyed by (event, driver)."""
from __future__ import annotations
from typing import Optional
import streamlit as st
from app_v2.services import lock_repository as LR
from app_v2.services import replay_service as RS
from app_v2.services import event_service as ES
from app_v2.services import view_models as VM


def lock() -> Optional[LR.LockView]:
    return LR.load_lock()


def source_for(event: str, driver: str, n_laps: Optional[int]) -> Optional[ES.ReplayEventSource]:
    key = f'_src_{event}_{driver}'
    src = st.session_state.get(key)
    if src is None:
        try:
            cur = RS.ReplayCursor(event, driver, n_laps)
        except (FileNotFoundError, KeyError):
            return None
        src = ES.ReplayEventSource(cur, seconds_per_lap=1.0, speed=float(st.session_state.get('speed', 1)))
        lap = st.session_state.get('lap')
        if lap:
            src.seek(int(lap))
        st.session_state[key] = src
    return src


def default_driver(lockv: LR.LockView, event: str) -> Optional[str]:
    """Demo default: the driver of Workstream 2's default counterfactual scenario (Monza NOR lap 24 -> new MEDIUM) when one
    exists for the event, else the driver whose longest stint has the most kept laps."""
    key = f'_drv_default_{event}'
    if key not in st.session_state:
        drv = None
        try:
            from app_v2.services import counterfactual_repository as CF
            sc = CF.default_scenario(event)
            drv = sc.driver if sc and sc.driver in RS.drivers_for(event) else None
        except Exception:
            drv = None
        st.session_state[key] = drv or VM.suggest_driver(lockv, event)
    return st.session_state[key]
