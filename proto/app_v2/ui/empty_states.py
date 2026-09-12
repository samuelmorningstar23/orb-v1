"""Intentional degraded-state screens (13.6 'Failure mode'): every missing feed has a designed empty state."""
from __future__ import annotations
import streamlit as st
from app_v2.ui.formatting import esc


def empty(title: str, body: str, glyph: str = '◌', tone: str = '') -> None:
    st.html(f'<div class="cs-empty {tone}" role="status"><div class="glyph" aria-hidden="true">{glyph}</div><div class="title">{esc(title)}</div><div class="body">{esc(body)}</div></div>')


def missing_lock() -> None:
    empty('NO LOCK FILE', 'out/lock.json (or out/lock_v2.json) is missing. Run pipeline.py to regenerate the lock; the dashboard shows nothing it cannot trace to a lock.', '⊘', 'critical')


def missing_feed(event: str) -> None:
    empty('NO RACE FEED', f'No recorded race file for {event} (feat/{event}_R.csv). The forecast is available; replay needs a recorded or live source. Start a replay on a scored weekend, or connect a feed.', '⊘', 'decision')


def missing_position() -> None:
    empty('POSITION DATA UNAVAILABLE', 'No canonical centreline for this circuit yet. The Race Twin map falls back to a synthetic loop; lap timing, deltas and curves are unaffected.', '◌', 'decision')


def out_of_support(status: str, reason: str) -> None:
    empty(status, reason or 'The selected combination is outside the evidence. The model abstains rather than extrapolate.', '○', 'critical')


def pending(what: str, workstream: str) -> None:
    empty(f'{what.upper()} PENDING', f'{what} arrives with {workstream}. The layout, labels and data contract are final; the values are not.', '◌')


def no_strategy(event: str) -> None:
    empty('NO STRATEGY IN LOCK', f'The lock carries no strategy block for {event} (no race-lap count available). Curves and validation remain visible.', '⊘', 'decision')


def offline_notice() -> None:
    empty('OFFLINE MODE', 'No CDN, API or network dependency is loaded by this page. Everything on screen comes from local hashed artifacts.', '●', '')
