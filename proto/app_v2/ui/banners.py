"""Support banners (roadmap 13.5): the two audit / scenario banners plus labelled placeholder and fixture notes."""
from __future__ import annotations
import streamlit as st
from app_v2.ui.formatting import esc


def audit_banner() -> None:
    st.html('<div class="cs-banner-audit" role="note">HISTORICAL AUDIT · OBSERVED WEATHER · HELD-OUT SCORING · this page is evidence</div>')


def scenario_banner() -> None:
    st.html('<div class="cs-banner-scenario" role="note">MODEL-IMPLIED SCENARIO · NO OBSERVED OUTCOME EXISTS FOR THIS COMBINATION · not evidence</div>')


def note_banner(text: str) -> None:
    st.html(f'<div class="cs-banner-note" role="note">{esc(text)}</div>')


def placeholder_banner(text: str) -> None:
    note_banner(f'PLACEHOLDER · {text}')


def fixture_banner(text: str) -> None:
    st.html(f'<div class="cs-banner-scenario" role="note">FIXTURE · {esc(text)}</div>')
