"""Query-param routing: ?ev=&mode=&lap=&drv=&cmp=&present= make every demo view URL-addressable.

URL values win on first sight; afterwards session state is the truth and is mirrored back to the URL so a copied
link reproduces the view. st.navigation clears params on route change, hence the mirror on every run.
"""
from __future__ import annotations
from typing import Optional
import streamlit as st

KEYS = ('ev', 'mode', 'lap', 'drv', 'cmp', 'present', 'scenario', 'ilap', 'rep')
MODES = ('live', 'audit', 'scenario')


def _get_qp() -> dict:
    try:
        return {k: st.query_params.get(k) for k in KEYS if st.query_params.get(k) not in (None, '')}
    except Exception:
        return {}


def sync(valid_events: list[str]) -> dict:
    """Read URL params into session state (validated), then mirror session state to the URL."""
    qp = _get_qp(); s = st.session_state
    if 'ev' in qp and qp['ev'] in valid_events:
        s['ev'] = qp['ev']
    if 'ev' not in s or s['ev'] not in valid_events:
        s['ev'] = valid_events[0] if valid_events else ''
    if 'mode' in qp and qp['mode'] in MODES:
        s['mode'] = qp['mode']
    s.setdefault('mode', 'live')
    if 'lap' in qp:
        try:
            s['lap'] = int(qp['lap'])
        except ValueError:
            pass
    if 'drv' in qp:
        s['drv'] = qp['drv'].upper()[:3]
    if 'cmp' in qp and qp['cmp'].upper() in ('SOFT', 'MEDIUM', 'HARD'):
        s['cmp'] = qp['cmp'].upper()
    if 'present' in qp:
        s['present'] = qp['present'] in ('1', 'true', 'yes')
    s.setdefault('present', False)
    if 'scenario' in qp:
        s['scenario'] = qp['scenario']
    if 'ilap' in qp:
        try:
            s['ilap'] = int(qp['ilap'])
        except ValueError:
            pass
    if 'rep' in qp and qp['rep'].upper() in ('SOFT', 'MEDIUM', 'HARD'):
        s['rep'] = qp['rep'].upper()
    mirror()
    return {k: s.get(k) for k in KEYS}


def mirror() -> None:
    s = st.session_state
    out = {'ev': s.get('ev', ''), 'mode': s.get('mode', 'live')}
    for k in ('lap', 'drv', 'cmp', 'scenario', 'ilap', 'rep'):
        if s.get(k) not in (None, ''):
            out[k] = str(s[k])
    if s.get('present'):
        out['present'] = '1'
    try:
        current = dict(st.query_params)
        desired = {k: v for k, v in current.items() if k not in KEYS}
        desired.update(out)
        if current != desired:
            for key in list(current):
                if key in KEYS and key not in out:
                    del st.query_params[key]
            st.query_params.update(out)
    except Exception:
        pass


def set_state(**kw) -> None:
    s = st.session_state
    event_changed = 'ev' in kw and kw['ev'] != s.get('ev')
    driver_changed = 'drv' in kw and kw['drv'] != s.get('drv')
    if event_changed or driver_changed:
        for key in ('lap', 'ilap', 'rep', 'glap', 'scenario', 'set_state', 'fid'):
            s.pop(key, None)
        if event_changed:
            s.pop('drv', None); s.pop('cmp', None)
        for key in list(s):
            if key.startswith('_src_'):
                src = s.pop(key)
                if hasattr(src, 'pause'):
                    src.pause()
    for k, v in kw.items():
        st.session_state[k] = v
    mirror()
