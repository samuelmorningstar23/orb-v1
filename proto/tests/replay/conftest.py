"""Workstream 4 replay tests: proto/ on sys.path; shared mini-race fixtures (fixtures/mini_race, no FastF1 needed)."""
import sys
from pathlib import Path

import pytest

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from replay import sources, geometry, trajectory, timewarp   # noqa: E402

MINI = PROTO / 'fixtures' / 'mini_race'
MAPS = PROTO / 'out' / 'maps'


@pytest.fixture(scope='session')
def mini_source():
    return sources.from_mini_race(MINI)


@pytest.fixture(scope='session')
def mini_track(mini_source):
    tr = geometry.build_track(mini_source)
    pl = geometry.build_pitlane(mini_source, tr)
    return geometry.attach_pit_flags(tr, pl), pl


@pytest.fixture(scope='session')
def mini_traj(mini_source, mini_track):
    tr, pl = mini_track
    return trajectory.build_trajectory(mini_source, 'ALP', tr, pl)


@pytest.fixture(scope='session')
def mini_frames(mini_traj, mini_track):
    tr, pl = mini_track
    cf = timewarp.fixture_laps(mini_traj, 9, 'HARD')
    return timewarp.build_frames(mini_traj, tr, pl, cf), cf
