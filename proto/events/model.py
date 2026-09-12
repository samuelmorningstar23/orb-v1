"""RaceEvent: the one event type every source emits and every consumer reads."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

EVENT_KINDS = ('position_update', 'lap_completed', 'pit_entry', 'pit_exit', 'weather_update', 'track_status', 'overtake', 'retirement', 'feed_quality_warning')
# order of events that share a timestamp: status and weather describe the lap the field is entering, then the completed lap, then its consequences
KIND_ORDER = {k: i for i, k in enumerate(('track_status', 'weather_update', 'lap_completed', 'position_update', 'overtake', 'pit_entry', 'pit_exit', 'feed_quality_warning', 'retirement'))}


def _clean(v: Any) -> Any:
    """JSON-safe payload values: numpy scalars -> python, NaN/inf -> None, nested containers cleaned."""
    if hasattr(v, 'item') and not isinstance(v, (str, bytes)):
        v = v.item()
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


@dataclass(frozen=True, order=False)
class RaceEvent:
    """kind: one of EVENT_KINDS; timestamp: session time in seconds (float); lap: the lap the event belongs to (None for
    race-level events without a lap); driver: three-letter code or None for race-level events; payload: JSON-safe dict;
    seq: position in the emitted stream (0-based), the same for every source of the same race."""
    kind: str
    timestamp: float
    lap: Optional[int] = None
    driver: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int = -1

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f'unknown event kind {self.kind!r}; expected one of {EVENT_KINDS}')
        object.__setattr__(self, 'timestamp', float(self.timestamp))
        object.__setattr__(self, 'lap', None if self.lap is None else int(self.lap))
        object.__setattr__(self, 'payload', _clean(dict(self.payload)))

    def to_dict(self) -> dict[str, Any]:
        return dict(seq=self.seq, kind=self.kind, timestamp=self.timestamp, lap=self.lap, driver=self.driver, payload=self.payload)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> 'RaceEvent':
        return cls(kind=d['kind'], timestamp=float(d['timestamp']), lap=d.get('lap'), driver=d.get('driver'), payload=dict(d.get('payload') or {}), seq=int(d.get('seq', -1)))

    def sort_key(self) -> tuple[float, int, str, int]:
        return (self.timestamp, KIND_ORDER.get(self.kind, 99), self.driver or '', self.lap or 0)


__all__ = ['RaceEvent', 'EVENT_KINDS', 'KIND_ORDER']
