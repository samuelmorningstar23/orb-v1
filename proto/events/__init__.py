"""RaceEventSource (roadmap v5 task 0.9): one event interface, three sources, identical events.

    from events import RaceEvent, ReplayEventSource, RecordedLiveEventSource, LiveEventSource, record

    src = ReplayEventSource('Monza', driver='NOR', speed=10.0)      # from feat/Monza_R.csv, lap order, 10x real time
    for ev in src.events():                                          # paced generator (speed=None -> as fast as possible)
        ...
    record(src, 'out/monza_nor.jsonl')                               # write the same stream as JSONL (unpaced)
    src2 = RecordedLiveEventSource('out/monza_nor.jsonl', speed=1.0) # replays the recording; events compare equal

Event kinds: position_update, lap_completed, pit_entry, pit_exit, weather_update, track_status, overtake, retirement,
feed_quality_warning. Every event carries a session-time timestamp (seconds) and a payload dict; nothing on an event
names the source that produced it, so a consumer cannot tell which source is active (a test asserts this).

LiveEventSource is a documented stub: FastF1's live-timing recorder (`python -m fastf1.livetiming save <file>`, run
during the session) is the free public source; parsing its SignalR stream into these events is Phase 1. Until then the
Sunday-evening path is the recorded-live source fed from a saved recording.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROTO = Path(__file__).resolve().parents[1]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from events.model import RaceEvent, EVENT_KINDS, KIND_ORDER          # noqa: E402
from events.sources import (RaceEventSource, ReplayEventSource, RecordedLiveEventSource, LiveEventSource, record, read_recording,  # noqa: E402
                            LIVE_SOURCE_NOTE)

__all__ = ['RaceEvent', 'EVENT_KINDS', 'KIND_ORDER', 'RaceEventSource', 'ReplayEventSource', 'RecordedLiveEventSource', 'LiveEventSource', 'record',
           'read_recording', 'LIVE_SOURCE_NOTE', 'PROTO']
