"""Filesystem layout of the prototype, resolved relative to this package (never to the cwd)."""
from __future__ import annotations
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]          # proto/app_v2
PROTO_ROOT = APP_ROOT.parent                           # proto
OUT_DIR = PROTO_ROOT / 'out'
FEAT_DIR = PROTO_ROOT / 'feat'
FIXTURE_DIR = PROTO_ROOT / 'fixtures'
STATE_DIR = APP_ROOT / 'state'
LOCK_V1 = OUT_DIR / 'lock.json'
LOCK_V2 = OUT_DIR / 'lock_v2.json'
LOCK_V2_FIXTURE = FIXTURE_DIR / 'lock_v2_fixture.json'
SENSITIVITY = OUT_DIR / 'sensitivity.json'
FEEDBACK_LOG = STATE_DIR / 'feedback_events.jsonl'
SEASON_OF_FEAT = 2026   # proto/feat holds the current (2026) season; feat2023/24/25 hold earlier seasons


def race_csv(event: str) -> Path:
    return FEAT_DIR / f'{event}_R.csv'
