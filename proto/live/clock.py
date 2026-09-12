"""Session clock: turns a lap's session time (t_min = FastF1 LapStartTime in minutes, lap_s) into a naive local timestamp.

Convention (matches fixtures/make_fixtures.py, naive local time): the first car to start lap 1 does so at the race's local
start time (FastF1 session_info StartDate). A lap completes at start_time + (t_min * 60 + lap_s - t_ref) seconds, where
t_ref is the earliest lap-1 start in the feed. Both quantities are known once the race starts, so the clock is online-safe.
Race start times were read from the FastF1 cache (session_info.ff1pkl, 'StartDate', local) on 12 Sep 2026; the cache is
consulted again at runtime when present, the table is the fallback.
"""
from __future__ import annotations

import pickle
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

PROTO = Path(__file__).resolve().parents[1]
CACHE_ROOTS = [PROTO.parent / 'cache', PROTO.parent / 'cache2']

# event name (feat/<event>_R.csv) -> race StartDate, local, naive (FastF1 session_info)
RACE_START_LOCAL: dict[str, str] = {
    'Australia': '2026-03-08T15:00:00', 'China': '2026-03-15T15:00:00', 'Japan': '2026-03-29T14:00:00', 'Miami': '2026-05-03T13:00:00',
    'Canada': '2026-05-24T16:00:00', 'Monaco': '2026-06-07T15:00:00', 'Barcelona': '2026-06-14T15:00:00', 'Austria': '2026-06-28T15:00:00',
    'Britain': '2026-07-05T15:00:00', 'Belgium': '2026-07-19T15:00:00', 'Hungary': '2026-07-26T15:00:00', 'Zandvoort': '2026-08-23T15:00:00',
    'Monza': '2026-09-06T15:00:00', 'Madrid': '2026-09-13T15:00:00',
}
CACHE_FOLDER: dict[str, str] = {
    'Australia': '2026-03-08_Australian_Grand_Prix', 'China': '2026-03-15_Chinese_Grand_Prix', 'Japan': '2026-03-29_Japanese_Grand_Prix',
    'Miami': '2026-05-03_Miami_Grand_Prix', 'Canada': '2026-05-24_Canadian_Grand_Prix', 'Monaco': '2026-06-07_Monaco_Grand_Prix',
    'Barcelona': '2026-06-14_Barcelona_Grand_Prix', 'Austria': '2026-06-28_Austrian_Grand_Prix', 'Britain': '2026-07-05_British_Grand_Prix',
    'Belgium': '2026-07-19_Belgian_Grand_Prix', 'Hungary': '2026-07-26_Hungarian_Grand_Prix', 'Zandvoort': '2026-08-23_Dutch_Grand_Prix',
    'Monza': '2026-09-06_Italian_Grand_Prix', 'Madrid': '2026-09-13_Spanish_Grand_Prix',
}


def _start_from_cache(event: str) -> Optional[datetime]:
    folder = CACHE_FOLDER.get(event)
    if not folder:
        return None
    for root in CACHE_ROOTS:
        for p in (root / '2026' / folder).glob('*_Race/session_info.ff1pkl'):
            try:
                with open(p, 'rb') as f:
                    obj = pickle.load(f)
                d = obj.get('data', obj) if isinstance(obj, dict) else None
                sd = d.get('StartDate') if isinstance(d, dict) else None
                if isinstance(sd, datetime):
                    return sd.replace(tzinfo=None)
            except Exception:
                continue
    return None


def race_start(event: str) -> datetime:
    """Naive local race start; cache first, table second, 15:00 on an unknown date last (flagged by the caller)."""
    sd = _start_from_cache(event)
    if sd is not None:
        return sd
    if event in RACE_START_LOCAL:
        return datetime.fromisoformat(RACE_START_LOCAL[event])
    raise KeyError(f'no race start time known for {event!r}: add it to live/clock.py RACE_START_LOCAL')


class SessionClock:
    """Maps (t_min, lap_s) of a completed lap to a naive local ISO timestamp. t_ref_s is the earliest lap-1 start (seconds)."""

    def __init__(self, event: str, t_ref_s: float, start: Optional[datetime] = None):
        self.event = event
        self.start = start or race_start(event)
        self.t_ref_s = float(t_ref_s)

    def lap_end(self, t_min: float, lap_s: float) -> datetime:
        return self.start + timedelta(seconds=float(t_min) * 60.0 + float(lap_s) - self.t_ref_s)

    def lap_end_iso(self, t_min: float, lap_s: float) -> str:
        return self.lap_end(t_min, lap_s).isoformat(timespec='seconds')

    def seconds_since_start(self, t_min: float, lap_s: float) -> float:
        return float(t_min) * 60.0 + float(lap_s) - self.t_ref_s


__all__ = ['RACE_START_LOCAL', 'race_start', 'SessionClock']
