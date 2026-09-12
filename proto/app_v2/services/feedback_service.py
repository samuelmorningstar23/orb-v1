"""Structured driver-feedback log (roadmap 0.10 / 7.3), appended to proto/app_v2/state/feedback_events.jsonl.

Feedback never adds seconds to a curve here; the 'effect on posterior' is Workstream 8's, this module only records.
"""
from __future__ import annotations
import json, os
from datetime import datetime
from pathlib import Path
from typing import Optional
from app_v2.services import paths as P

AXLES = ('front', 'rear', 'all', 'unknown')
CORNER_PHASES = ('braking', 'entry', 'mid', 'exit', 'traction')
SYMPTOMS = ('understeer', 'oversteer', 'sliding', 'graining', 'overheating', 'vibration', 'lack_of_grip')
TRENDS = ('improving', 'stable', 'worsening')
SOURCES = ('radio', 'engineer', 'debrief', 'manual')
FIELDS = ('timestamp', 'event', 'driver', 'lap', 'axle', 'corner_phase', 'symptom', 'severity', 'trend', 'driver_confidence', 'source', 'raw_message', 'engineer_confirmed')


def log_path() -> Path:
    return P.FEEDBACK_LOG


def enabled() -> bool:
    """Feedback is 'enabled' when the log directory is writable (landing status strip)."""
    d = log_path().parent
    try:
        d.mkdir(parents=True, exist_ok=True)
        return os.access(d, os.W_OK)
    except OSError:
        return False


def make_event(event: str, driver: str, lap: int, axle: str, corner_phase: str, symptom: str, severity: int, trend: str,
               driver_confidence: float, source: str, raw_message: str, engineer_confirmed: bool, timestamp: Optional[str] = None) -> dict:
    assert axle in AXLES and corner_phase in CORNER_PHASES and symptom in SYMPTOMS and trend in TRENDS and source in SOURCES
    assert 1 <= int(severity) <= 5 and 0.0 <= float(driver_confidence) <= 1.0
    return dict(timestamp=timestamp or datetime.now().isoformat(timespec='seconds'), event=event, driver=driver, lap=int(lap), axle=axle, corner_phase=corner_phase,
                symptom=symptom, severity=int(severity), trend=trend, driver_confidence=float(driver_confidence), source=source, raw_message=raw_message.strip(),
                engineer_confirmed=bool(engineer_confirmed))


def append(evt: dict, path: Optional[Path] = None) -> Path:
    p = path or log_path(); p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'a') as f:
        f.write(json.dumps(evt) + '\n')
    return p


def read_all(path: Optional[Path] = None) -> list[dict]:
    p = path or log_path()
    if not p.exists():
        return []
    out = []
    with open(p) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def for_session(event: str, driver: Optional[str] = None, through_lap: Optional[int] = None, path: Optional[Path] = None) -> list[dict]:
    rows = [r for r in read_all(path) if r.get('event') == event and (driver is None or r.get('driver') == driver)]
    if through_lap is not None:
        rows = [r for r in rows if int(r.get('lap', 0)) <= through_lap]
    return rows


def latest(n: int = 10, path: Optional[Path] = None) -> list[dict]:
    return list(reversed(read_all(path)))[:n]
