"""Alerts rendered in the design system (st.info/st.warning are hidden by the theme on purpose)."""
from __future__ import annotations
import streamlit as st
from app_v2.ui.formatting import esc


def alert_html(kind: str, title: str, body: str = '') -> str:
    kind = kind if kind in ('live', 'decision', 'critical', 'neutral') else 'neutral'
    b = f'<div>{esc(body)}</div>' if body else ''
    return f'<div class="cs-alert {kind}" role="alert"><div class="title">{esc(title)}</div>{b}</div>'


def alert(kind: str, title: str, body: str = '') -> None:
    st.html(alert_html(kind, title, body))
