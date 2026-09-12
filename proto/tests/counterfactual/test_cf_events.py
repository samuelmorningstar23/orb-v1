"""Event sources: replay from the race file, recording round trip, interchangeability, pacing without sleeping."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from events import RaceEvent, EVENT_KINDS, ReplayEventSource, RecordedLiveEventSource, LiveEventSource, RaceEventSource, record, read_recording

EVENT = 'Monza'


@pytest.fixture(scope='module')
def nor_events(monza_csv):
    return ReplayEventSource(EVENT, driver='NOR', speed=None).all_events()


def test_replay_single_driver_stream(monza_csv, nor_events):
    df = pd.read_csv(monza_csv)
    n_rows = int((df['Driver'] == 'NOR').sum())
    kinds = [e.kind for e in nor_events]
    assert set(kinds) <= set(EVENT_KINDS)
    assert kinds.count('lap_completed') == n_rows
    assert kinds.count('position_update') == n_rows
    assert kinds.count('pit_entry') == 1 and [e.lap for e in nor_events if e.kind == 'pit_entry'] == [3]
    assert kinds.count('retirement') == 0
    ts = [e.timestamp for e in nor_events]
    assert ts == sorted(ts)
    assert [e.seq for e in nor_events] == list(range(len(nor_events)))
    statuses = [e.payload['status'] for e in nor_events if e.kind == 'track_status']
    assert 'RED' in statuses and 'VSC' in statuses and statuses[0] == 'GREEN'
    lap2 = next(e for e in nor_events if e.kind == 'lap_completed' and e.lap == 2)
    assert lap2.driver == 'NOR' and lap2.payload['compound'] == 'MEDIUM' and lap2.payload['position'] == 6
    assert all(v is None or isinstance(v, (int, float, str, bool, list, dict)) for e in nor_events for v in e.payload.values())


def test_replay_whole_field(monza_csv):
    src = ReplayEventSource(EVENT, speed=None)
    evs = src.all_events()
    kinds = [e.kind for e in evs]
    assert kinds.count('retirement') >= 3                                   # LEC, ALO, STR ... did not finish
    assert any(e.kind == 'overtake' and e.payload['passed'] for e in evs)
    assert kinds.count('pit_exit') >= 11
    weather = [e for e in evs if e.kind == 'weather_update']
    assert len(weather) == pd.read_csv(monza_csv)['LapNumber'].nunique()          # laps 4-5 have no rows at all (red flag)
    ret = next(e for e in evs if e.kind == 'retirement' and e.driver == 'ALO')
    last = max((e for e in evs if e.kind == 'lap_completed' and e.driver == 'ALO'), key=lambda e: e.timestamp)
    assert ret.lap == 23 and ret.timestamp > last.timestamp


def test_record_and_recorded_live_are_identical(monza_csv, tmp_path):
    src = ReplayEventSource(EVENT, driver='NOR', speed=None)
    path = tmp_path / 'monza_nor.jsonl'
    n = record(src, path)
    assert n == len(src) and path.exists()
    rec = RecordedLiveEventSource(path, speed=None)
    assert rec.all_events() == src.all_events()                            # dataclass equality, field by field
    assert read_recording(path) == src.all_events()
    lines = path.read_text(encoding='utf-8').splitlines()
    assert len(lines) == n and all('source' not in json.loads(l) for l in lines)
    assert 'replay' not in path.read_text(encoding='utf-8').lower()


def test_consumer_cannot_tell_the_source(monza_csv, tmp_path):
    src = ReplayEventSource(EVENT, driver='VER', speed=None)
    path = tmp_path / 'ver.jsonl'
    record(src, path)
    rec = RecordedLiveEventSource(path, speed=None)

    def consume(source: RaceEventSource) -> list[tuple]:
        seen = []
        for ev in source.events():
            assert type(ev) is RaceEvent
            assert not any('source' in f or 'origin' in f for f in ev.__dataclass_fields__)
            seen.append((ev.seq, ev.kind, ev.timestamp, ev.lap, ev.driver, json.dumps(ev.payload, sort_keys=True)))
        return seen

    assert consume(src) == consume(rec)
    assert isinstance(src, RaceEventSource) and isinstance(rec, RaceEventSource)
    assert set(dir(RaceEventSource)) >= {'events', 'poll', 'start', 'pause', 'seek', 'set_speed', 'all_events'}


def test_poll_pacing_with_fake_clock(monza_csv):
    src = ReplayEventSource(EVENT, driver='NOR', speed=10.0, clock=lambda: 0.0)
    evs = src.all_events()
    assert src.poll(0.0) == []                                              # not started
    src.start(now=100.0)
    first = src.poll(100.0)
    assert first and all(e.timestamp <= evs[0].timestamp for e in first)
    span = evs[-1].timestamp - evs[0].timestamp
    later = src.poll(100.0 + span / 20)                                     # 10x speed: 5% of the race has passed
    limit = evs[0].timestamp + (span / 20) * 10
    assert later and all(e.timestamp <= limit for e in later)
    assert all(e.timestamp > limit for e in evs[src._cursor:])              # nothing beyond the current session time
    src.set_speed(None, now=100.0 + span / 20)                              # unpaced: everything is due
    rest = src.poll(100.0 + span / 20)
    assert rest and src.at_end and not src.playing
    assert first + later + rest == evs


def test_events_generator_uses_injected_sleep(monza_csv):
    sleeps = []
    src = ReplayEventSource(EVENT, driver='NOR', speed=100.0, sleep=sleeps.append)
    evs = list(src.events())
    assert evs == src.all_events()
    assert sleeps and abs(sum(sleeps) - (evs[-1].timestamp - evs[0].timestamp) / 100.0) < 1e-6
    sleeps.clear()
    list(src.events(paced=False))
    assert sleeps == []


def test_live_source_is_a_documented_stub():
    with pytest.raises(NotImplementedError) as e:
        LiveEventSource()
    assert 'fastf1.livetiming' in str(e.value).lower() and 'RecordedLiveEventSource' in str(e.value)


def test_mini_race_fixture_replays(proto_dir):
    p = proto_dir / 'fixtures' / 'mini_race' / 'Mini_R.csv'
    if not p.exists():
        pytest.skip('mini_race fixture absent')
    src = ReplayEventSource('Mini', speed=None, path=p)
    evs = src.all_events()
    assert sum(e.kind == 'pit_entry' for e in evs) == 3 and sum(e.kind == 'lap_completed' for e in evs) == 42


def test_bad_event_kind_rejected():
    with pytest.raises(ValueError):
        RaceEvent('teleport', 0.0)
