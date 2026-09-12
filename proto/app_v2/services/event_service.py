"""RaceEventSource consumer stub (roadmap 0.9): replays a recorded race as lap_completed events at adjustable speed.

The dashboard polls `poll(now)` from a fragment; events are derived from the cursor's visible rows only, so the
source can never emit lap k+1 while the display shows lap k. The sequence of events is deterministic; only the
wall-clock pacing changes with `speed`. Workstream 2's Replay / Live / RecordedLive sources plug in behind `poll`.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Optional
from app_v2.services.replay_service import ReplayCursor

SPEEDS = (1, 2, 5, 10)


@dataclass(frozen=True)
class RaceEvent:
    kind: str            # lap_completed | pit_entry | pit_exit | track_status | feed_quality_warning
    lap: int
    t_emitted: float     # monotonic seconds
    detail: str = ''


@dataclass
class ReplayEventSource:
    cursor: ReplayCursor
    seconds_per_lap: float = 1.0          # at 1x: one recorded lap per second of wall clock
    speed: float = 1.0
    playing: bool = False
    _t0: Optional[float] = None
    _lap0: int = 0
    _last_emit: Optional[float] = None
    log: list = field(default_factory=list)
    source_name: str = 'replay (recorded race file)'

    def now(self) -> float:
        return time.monotonic()

    def start(self, now: Optional[float] = None) -> None:
        if self.cursor.at_end:
            self.cursor.seek(self.cursor.first_lap)
        self.playing, self._t0, self._lap0 = True, (now if now is not None else self.now()), self.cursor.lap

    def pause(self, now: Optional[float] = None) -> None:
        self.poll(now); self.playing = False

    def set_speed(self, speed: float, now: Optional[float] = None) -> None:
        self.poll(now); self.speed = float(speed)
        if self.playing:
            self._t0, self._lap0 = (now if now is not None else self.now()), self.cursor.lap

    def seek(self, lap: int, now: Optional[float] = None) -> None:
        self.cursor.seek(lap); self._t0, self._lap0 = (now if now is not None else self.now()), self.cursor.lap

    def target_lap(self, now: float) -> int:
        if not self.playing or self._t0 is None:
            return self.cursor.lap
        elapsed = max(now - self._t0, 0.0)
        return min(self._lap0 + int(elapsed * self.speed / self.seconds_per_lap), self.cursor.last_lap)

    def poll(self, now: Optional[float] = None) -> list[RaceEvent]:
        """Advance one lap at a time up to the wall-clock target, emitting events from each newly visible row."""
        now = now if now is not None else self.now(); out = []
        while self.playing and self.cursor.lap < self.target_lap(now):
            self.cursor.step(1)
            out.extend(self._events_for_current_lap(now))
        if self.playing and self.cursor.at_end:
            self.playing = False
        return out

    def _events_for_current_lap(self, now: float) -> list[RaceEvent]:
        row = self.cursor.lap_row()
        if row is None:
            return []
        lap = int(row['LapNumber']); ev = []
        if bool(row['pit_out']): ev.append(RaceEvent('pit_exit', lap, now, f"new {row['Compound'].lower()}"))
        if not bool(row['green']): ev.append(RaceEvent('track_status', lap, now, f"status {row['TrackStatus']}"))
        if bool(row['pit_in']): ev.append(RaceEvent('pit_entry', lap, now, 'box'))
        if row.get('pos_distinct', 0) < 100: ev.append(RaceEvent('feed_quality_warning', lap, now, f"position samples {int(row['pos_distinct'])}"))
        ev.append(RaceEvent('lap_completed', lap, now, f"{row['lap_s']:.3f} s"))
        self._last_emit = now; self.log.extend(ev)
        return ev

    def latency_s(self, now: Optional[float] = None) -> Optional[float]:
        """Seconds since the last emitted event (feed latency readout). None before the first event."""
        if self._last_emit is None:
            return None
        return max((now if now is not None else self.now()) - self._last_emit, 0.0)
