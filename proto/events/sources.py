"""Event sources: Replay (race CSV), RecordedLive (JSONL), Live (documented stub); one base class does pacing and polling.

Replay derivation from feat/<event>_R.csv (one row per driver-lap; t_min is the lap start in session minutes):
    lap_completed          at t_end = t_min*60 + lap_s, payload: lap time, sectors, compound, tyre age, stint, fresh, status,
                           traffic, energy, throttle, track temperature, rain, accuracy flags, position at completion
    position_update        same time, payload {position}; position = rank of the lap's completion time over the field
    overtake               when the driver's position improved vs the previous lap: payload {from, to, passed: [codes]}
    pit_entry              at the in-lap's completion (pit_in row), payload {compound_off, tyre_age}
    pit_exit               at the out-lap's start plus the out-lap's excess over the driver's median clean lap (the excess is
                           taken to be pit-lane time; an approximation, stated), payload {compound_on, tyre_age, fresh}
    track_status           race level, when the most severe status over the field changes between laps, timestamped at the
                           first car's start of that lap; payload {status: GREEN|YELLOW|VSC|SC|RED, codes, lap}
    weather_update         race level, one per lap at the first car's lap start: {track_temp, rain}
    retirement             a car whose last row is before the race distance: declared 1.5 lap times after its last
                           completion (online-safe: the car has failed to appear), payload {last_lap}
    feed_quality_warning   pos_distinct < 100 or stale_share > 0.3 or an inaccurate lap: payload {pos_distinct, stale_share, is_accurate}
Events are ordered by (timestamp, kind order, driver, lap) and numbered `seq`. The order is deterministic; only the
wall-clock pacing depends on `speed`.

Pacing: `events()` yields in order sleeping (dt / speed) between session timestamps (speed=None or 0: no sleeping);
`poll(now)` is the non-blocking form for a UI fragment: after `start(now)`, it returns every event whose session time
is <= s0 + (now - t0) * speed. The clock is injectable so tests run without sleeping.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Optional

import numpy as np
import pandas as pd

from events.model import RaceEvent, KIND_ORDER

LIVE_SOURCE_NOTE = (
    "LiveEventSource is not implemented in Phase 0. Free public live data: FastF1's live-timing recorder "
    "(`python -m fastf1.livetiming save <file>`) must run during the session and stores the raw SignalR timing stream; "
    "OpenF1's real-time API is a paid tier (its history is free with a delay). Phase 1 parses the recorder output into "
    "the same RaceEvent stream through this class; until then use RecordedLiveEventSource on a saved recording, which "
    "is the path used for the Madrid race on Sunday evening."
)


def _status_label(ts: Any) -> str:
    s = str(ts)
    if '5' in s:
        return 'RED'
    if '4' in s:
        return 'SC'
    if '6' in s or '7' in s:
        return 'VSC'
    if '2' in s:
        return 'YELLOW'
    return 'GREEN'


class RaceEventSource(ABC):
    """Base: subclasses provide the ordered list of events; pacing and polling live here so every source behaves alike."""

    def __init__(self, speed: Optional[float] = 1.0, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.speed = None if (speed is None or speed <= 0) else float(speed)
        self._clock = clock
        self._sleep = sleep
        self._events: Optional[list[RaceEvent]] = None
        self._cursor = 0
        self._t0: Optional[float] = None
        self._s0: Optional[float] = None
        self.playing = False

    @abstractmethod
    def _load(self) -> list[RaceEvent]: ...

    # ---------------------------------------------------------------- the stream
    def all_events(self) -> list[RaceEvent]:
        if self._events is None:
            evs = sorted(self._load(), key=RaceEvent.sort_key)
            self._events = [RaceEvent(e.kind, e.timestamp, e.lap, e.driver, e.payload, seq=i) for i, e in enumerate(evs)]
        return self._events

    def __iter__(self) -> Iterator[RaceEvent]:
        return self.events()

    def __len__(self) -> int:
        return len(self.all_events())

    def iter_unpaced(self) -> Iterator[RaceEvent]:
        yield from self.all_events()

    def events(self, paced: Optional[bool] = None) -> Iterator[RaceEvent]:
        """Generator in stream order. Paced by session time / speed unless speed is None (or paced=False)."""
        paced = (self.speed is not None) if paced is None else (paced and self.speed is not None)
        prev: Optional[float] = None
        for ev in self.all_events():
            if paced and prev is not None:
                dt = (ev.timestamp - prev) / self.speed
                if dt > 0:
                    self._sleep(dt)
            prev = ev.timestamp
            yield ev

    # ---------------------------------------------------------------- non-blocking polling (UI fragments)
    def start(self, now: Optional[float] = None) -> None:
        evs = self.all_events()
        self._t0 = self._clock() if now is None else now
        self._s0 = evs[self._cursor].timestamp if self._cursor < len(evs) else (evs[-1].timestamp if evs else 0.0)
        self.playing = True

    def pause(self, now: Optional[float] = None) -> None:
        self.poll(now)
        self.playing = False

    def seek(self, seq: int, now: Optional[float] = None) -> None:
        self._cursor = max(0, min(int(seq), len(self.all_events())))
        if self.playing:
            self.start(now)

    def set_speed(self, speed: Optional[float], now: Optional[float] = None) -> None:
        self.poll(now)
        self.speed = None if (speed is None or speed <= 0) else float(speed)
        if self.playing:
            self.start(now)

    def session_time(self, now: Optional[float] = None) -> Optional[float]:
        if not self.playing or self._t0 is None or self._s0 is None:
            return None
        now = self._clock() if now is None else now
        if self.speed is None:
            return float('inf')
        return self._s0 + (now - self._t0) * self.speed

    def poll(self, now: Optional[float] = None) -> list[RaceEvent]:
        """Every not-yet-delivered event whose session time has been reached; never an event beyond the current time."""
        if not self.playing:
            return []
        evs = self.all_events()
        limit = self.session_time(now)
        out: list[RaceEvent] = []
        while self._cursor < len(evs) and evs[self._cursor].timestamp <= limit:
            out.append(evs[self._cursor])
            self._cursor += 1
        if self._cursor >= len(evs):
            self.playing = False
        return out

    @property
    def at_end(self) -> bool:
        return self._cursor >= len(self.all_events())


# ---------------------------------------------------------------- replay from the race CSV

class ReplayEventSource(RaceEventSource):
    def __init__(self, event: str, driver: Optional[str] = None, speed: Optional[float] = 1.0, path: Path | str | None = None, feat_dir: Path | str | None = None, **kw: Any):
        super().__init__(speed=speed, **kw)
        from events import PROTO
        self.event = event
        self.driver = driver
        self.path = Path(path) if path else (Path(feat_dir) if feat_dir else PROTO / 'feat') / f'{event}_R.csv'
        if not self.path.exists():
            raise FileNotFoundError(f'no race file {self.path}')

    def _load(self) -> list[RaceEvent]:
        df = pd.read_csv(self.path)
        df['TrackStatus'] = df['TrackStatus'].astype(str)
        df['LapNumber'] = df['LapNumber'].astype(int)
        for c in ('pit_in', 'pit_out', 'deleted', 'IsAccurate', 'FreshTyre'):
            df[c] = df[c].astype(bool)
        df = df.sort_values(['Driver', 'LapNumber']).reset_index(drop=True)
        df['t_start'] = df['t_min'] * 60.0
        df['t_end'] = df['t_start'] + df['lap_s']
        df['position'] = df.groupby('LapNumber')['t_end'].rank(method='first').astype(int)
        df['label'] = df['TrackStatus'].map(_status_label)
        n_laps = int(df['LapNumber'].max())
        out: list[RaceEvent] = []
        # ---- race-level: track status changes and weather per lap (first car into the lap)
        sev = {'GREEN': 0, 'YELLOW': 1, 'VSC': 2, 'SC': 3, 'RED': 4}
        prev_label = None
        for lap_no, g in df.groupby('LapNumber'):
            label = max(g['label'], key=lambda x: sev[x])
            t_first = float(g['t_start'].min())
            if label != prev_label:
                out.append(RaceEvent('track_status', t_first, lap=int(lap_no), driver=None, payload=dict(status=label, codes=sorted(set(g['TrackStatus'])), lap=int(lap_no))))
                prev_label = label
            first = g.sort_values('t_start').iloc[0]
            out.append(RaceEvent('weather_update', t_first, lap=int(lap_no), driver=None, payload=dict(track_temp=first['track_temp'], rain=bool(first['rain']))))
        # ---- per driver
        ahead_prev: dict[str, set[str]] = {}
        order = {int(l): list(g.sort_values('t_end')['Driver']) for l, g in df.groupby('LapNumber')}
        drivers = [self.driver] if self.driver else sorted(df['Driver'].unique())
        for drv in drivers:
            x = df[df['Driver'] == drv]
            if x.empty:
                raise KeyError(f'{drv} has no laps in {self.path.name}')
            clean = x[x['IsAccurate'] & (x['label'] == 'GREEN') & ~x['pit_in'] & ~x['pit_out']]['lap_s']
            med = float(clean.median()) if len(clean) else float(x['lap_s'].median())
            prev_pos: Optional[int] = None
            prev_pit_in = False
            last = None
            for _, r in x.iterrows():
                lap = int(r['LapNumber'])
                t_end = float(r['t_end'])
                pos = int(r['position'])
                payload = dict(lap_s=r['lap_s'], s1=r['s1'], s2=r['s2'], s3=r['s3'], compound=r['Compound'], tyre_age=r['TyreLife'], stint=r['Stint'], fresh=bool(r['FreshTyre']),
                               track_status=r['label'], status_codes=r['TrackStatus'], traffic=r['traffic'], energy_MJ=r['energy_MJ'], e_lat=r['e_lat'], e_long=r['e_long'],
                               full_throttle=r['full_throttle'], track_temp=r['track_temp'], rain=bool(r['rain']), is_accurate=bool(r['IsAccurate']), deleted=bool(r['deleted']),
                               pos_distinct=r['pos_distinct'], stale_share=r['stale_share'], position=pos, pit_in=bool(r['pit_in']), pit_out=bool(r['pit_out']))
                out.append(RaceEvent('lap_completed', t_end, lap, drv, payload))
                out.append(RaceEvent('position_update', t_end, lap, drv, dict(position=pos)))
                ahead_now = set(order[lap][:pos - 1])
                if prev_pos is not None and pos < prev_pos:
                    passed = sorted((ahead_prev.get(drv, set()) - ahead_now) & set(order[lap]))
                    out.append(RaceEvent('overtake', t_end, lap, drv, dict(from_position=prev_pos, to_position=pos, passed=passed)))
                ahead_prev[drv] = ahead_now
                prev_pos = pos
                if bool(r['pit_in']):
                    out.append(RaceEvent('pit_entry', t_end, lap, drv, dict(compound_off=r['Compound'], tyre_age=r['TyreLife'])))
                is_out = bool(r['pit_out']) or (prev_pit_in and last is not None and lap == last + 1)
                if is_out:
                    excess = max(float(r['lap_s']) - med, 0.0)
                    out.append(RaceEvent('pit_exit', float(r['t_start']) + excess, lap, drv, dict(compound_on=r['Compound'], tyre_age=r['TyreLife'], fresh=bool(r['FreshTyre']))))
                if (r['pos_distinct'] < 100) or (pd.notna(r['stale_share']) and r['stale_share'] > 0.3) or not bool(r['IsAccurate']):
                    out.append(RaceEvent('feed_quality_warning', t_end, lap, drv, dict(pos_distinct=r['pos_distinct'], stale_share=r['stale_share'], is_accurate=bool(r['IsAccurate']))))
                prev_pit_in = bool(r['pit_in'])
                last = lap
            last_row = x.iloc[-1]
            if int(last_row['LapNumber']) < n_laps:
                out.append(RaceEvent('retirement', float(last_row['t_end'] + 1.5 * last_row['lap_s']), int(last_row['LapNumber']), drv,
                                     dict(last_lap=int(last_row['LapNumber']), declared_after_s=float(1.5 * last_row['lap_s']))))
        return out


# ---------------------------------------------------------------- recorded live (JSONL)

def read_recording(path: Path | str) -> list[RaceEvent]:
    out: list[RaceEvent] = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(RaceEvent.from_dict(json.loads(line)))
    return out


class RecordedLiveEventSource(RaceEventSource):
    """Replays a JSONL recording written by `record` (or by the Phase 1 live recorder) with the same pacing semantics."""

    def __init__(self, path: Path | str, speed: Optional[float] = 1.0, driver: Optional[str] = None, **kw: Any):
        super().__init__(speed=speed, **kw)
        self.path = Path(path)
        self.driver = driver
        if not self.path.exists():
            raise FileNotFoundError(f'no recording {self.path}')

    def _load(self) -> list[RaceEvent]:
        evs = read_recording(self.path)
        if self.driver:
            evs = [e for e in evs if e.driver in (None, self.driver)]
        return evs


# ---------------------------------------------------------------- live (stub)

class LiveEventSource(RaceEventSource):
    """Phase 1 adapter for a live timing feed. See LIVE_SOURCE_NOTE: FastF1's live-timing recorder is the free public
    source; this class will parse its stream into RaceEvents. Constructing it raises NotImplementedError."""

    def __init__(self, *a: Any, **k: Any):
        raise NotImplementedError(LIVE_SOURCE_NOTE)

    def _load(self) -> list[RaceEvent]:   # pragma: no cover
        raise NotImplementedError(LIVE_SOURCE_NOTE)


# ---------------------------------------------------------------- recording

def record(source: RaceEventSource, path: Path | str) -> int:
    """Write every event of `source` as JSONL (unpaced). The file carries nothing that names the source."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        for ev in source.iter_unpaced():
            f.write(json.dumps(ev.to_dict(), ensure_ascii=False, allow_nan=False) + '\n')
            n += 1
    tmp.replace(path)
    return n


__all__ = ['RaceEventSource', 'ReplayEventSource', 'RecordedLiveEventSource', 'LiveEventSource', 'record', 'read_recording', 'LIVE_SOURCE_NOTE']
