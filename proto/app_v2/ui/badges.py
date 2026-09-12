"""Badges and chips. Status is never colour-only: every badge carries a glyph or a word."""
from __future__ import annotations
import streamlit as st
from app_v2.theme.tokens import COMPOUNDS, COMPOUND_GLYPH, STATUS, STATUS_GLYPH
from app_v2.ui.formatting import esc

TONES = ('live', 'decision', 'critical', 'neutral', 'fixture', 'placeholder')


def badge_html(text: str, tone: str = 'neutral', title: str = '') -> str:
    tone = tone if tone in TONES else 'neutral'
    return f'<span class="cs-badge {tone}" title="{esc(title)}">{esc(text)}</span>'


def compound_html(compound: str, text: str = '') -> str:
    c = (compound or '').upper(); col = COMPOUNDS.get(c, '#98A3B3'); g = COMPOUND_GLYPH.get(c, '?')
    label = text or c.title()
    return f'<span class="cs-badge compound" style="border-color:{col};color:{col}" aria-label="{esc(c)}">{g} · {esc(label)}</span>'


def status_html(status: str) -> str:
    col = STATUS.get(status, STATUS['PENDING']); g = STATUS_GLYPH.get(status, '◌')
    return f'<span class="cs-badge" style="border-color:{col};color:{col}">{g} {esc(status)}</span>'


def bool_chip_html(label: str, ok, true_text: str = 'yes', false_text: str = 'no') -> str:
    if ok is None:
        return badge_html(f'{label}: pending', 'neutral')
    return badge_html(f'{label}: {true_text if ok else false_text}', 'live' if ok else 'critical')


def support_chips_html(support, hash6: str = '') -> str:
    parts = [status_html(support.overall_support_status),
             bool_chip_html('track seen', support.track_seen_during_training),
             bool_chip_html('driver seen', support.driver_seen_during_training),
             bool_chip_html('weather in range', support.weather_in_training_range),
             bool_chip_html('compound', support.compound_support, 'supported', 'unsupported'),
             bool_chip_html('season', support.season_support)]
    if hash6:
        parts.append(badge_html(f'snapshot {hash6}', 'neutral', 'forecast snapshot hash'))
    reason = f'<div class="cs-muted">{esc(support.abstention_reason)}</div>' if support.abstention_reason else ''
    return f'<div class="cs-chips">{"".join(parts)}</div>{reason}'


def badges(*items: str) -> None:
    st.html('<div class="cs-chips">' + ''.join(items) + '</div>')
