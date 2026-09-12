"""Application shell: CSS injection (once per run), the sticky global frame from a HeaderVM, the sidebar."""
from __future__ import annotations
from functools import lru_cache
import streamlit as st
from app_v2.theme.tokens import BASE_CSS_PATH, PREMIUM_CSS_PATH
from app_v2.ui.formatting import esc


def _css_bundle() -> str:   # not cached: two small local files, and CSS edits then apply without a restart
    parts = []
    for p in (BASE_CSS_PATH, PREMIUM_CSS_PATH):
        if p.exists():
            parts.append(p.read_text())
    return '\n'.join(parts)


PRESENT_CSS = """
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display: none !important; }
.cs-card.kpi .cs-kpi-value { font-size: 2.7rem; } .cs-card.kpi { min-height: 140px; }
.cs-decision .headline { font-size: 2.3rem; } .cs-decision .grid .v { font-size: 1.3rem; }
.cs-eng { display: none !important; }
.block-container { max-width: 100%; }
"""


def inject_css(presentation: bool = False) -> None:
    """Inject base.css + premium.css (+ the presentation block). The shell calls this once per run; pages never do."""
    st.html(f'<style>{_css_bundle()}{PRESENT_CSS if presentation else ""}</style>')


OFFLINE_NOTICE = 'Recorded races replay locally. Runs offline.'


def header_html(vm, presentation: bool = False) -> str:
    items = [f'<span class="brand">ORB</span>', f'<span class="mode">{esc(vm.mode)}</span>',
             f'<span class="hot">{esc(vm.event)} {vm.season}</span>']
    if vm.lap_text and vm.lap_text != 'Lap —':
        items.append(f'<span>{esc(vm.lap_text)}</span>')
    if 'replay' in str(vm.session).lower():
        items.append('<span class="cs-badge neutral">Recorded replay</span>')
    if presentation:                         # the sidebar is hidden here, so the offline claim travels with the header
        items.append(f'<span class="cs-offline">{esc(OFFLINE_NOTICE)}</span>')
    return f'<header class="cs-header" data-orb-header="1" aria-label="global frame">{"".join(items)}</header>'


def render_header(vm, presentation: bool = False) -> None:
    st.html(header_html(vm, presentation))


def ready_marker(page: str) -> None:
    """Invisible marker used by screenshot and performance tests to detect a fully rendered page."""
    st.html(f'<div data-orb-ready="{esc(page)}" hidden></div>')
