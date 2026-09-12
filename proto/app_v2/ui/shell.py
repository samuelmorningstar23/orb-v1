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


def header_html(vm) -> str:
    items = [f'<span class="brand">ORB V1</span>', '<span class="sep">|</span>', f'<span class="mode">{esc(vm.mode)}</span>',
             '<span class="sep">·</span>', f'<span class="hot">{esc(vm.event)} {vm.season}</span>', '<span class="sep">·</span>', f'<span>{esc(vm.session)}</span>',
             '<span class="sep">·</span>', f'<span class="hot">{esc(vm.lap_text)}</span>', '<span class="sep">·</span>', f'<span>Forecast <span class="mono">{esc(vm.forecast_hash6)}</span></span>',
             '<span class="sep">·</span>', f'<span>{esc(vm.sensor_mode)}</span>', '<span class="sep">·</span>', f'<span class="hot">{esc(vm.support_status)}</span>',
             '<span class="sep">·</span>', f'<span>Feed latency {esc(vm.latency_text)}</span>']
    note = f'<div class="cs-frame-note">lock {esc(vm.lock_version)} generated {esc(vm.generated_at)} · hash source {esc(vm.forecast_hash_source)} · offline: no CDN, API or font download</div>'
    return f'<header class="cs-header" data-orb-header="1" aria-label="global frame">{"".join(items)}</header>{note}'


def render_header(vm) -> None:
    st.html(header_html(vm))


def ready_marker(page: str) -> None:
    """Invisible marker used by screenshot and performance tests to detect a fully rendered page."""
    st.html(f'<div data-orb-ready="{esc(page)}" hidden></div>')
