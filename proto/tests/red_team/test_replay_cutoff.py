"""Replay live mode never sees lap k+1 while processing lap k (roadmap v5 task 0.0; Phase 0 acceptance 7).

Three layers: the pages' ReplayCursor (visible(k) is the only door), Workstream 8's LapFeed behind the leakage audit's
FeedProxy over a real LiveSession, and the audit's own self-test (inject=True plants a read of lap k+1 and must be caught)."""
from __future__ import annotations

import pytest

from rt_helpers import EVENT, DRIVER


@pytest.fixture(scope='module')
def cursor(race_csv, lock_v1_path):
    from app_v2.services import replay_service as RS
    return RS.ReplayCursor(EVENT, DRIVER)


@pytest.mark.parametrize('k', [1, 2, 7, 12, 25])
def test_replay_cursor_exposes_only_laps_through_k(cursor, k):
    cursor.seek(k)
    v = cursor.visible()
    assert cursor.lap == max(k, cursor.first_lap) and (v.empty or int(v['LapNumber'].max()) <= k)
    o = cursor.others_visible()
    assert o.empty or int(o['LapNumber'].max()) <= k
    row = cursor.lap_row()
    assert row is None or int(row['LapNumber']) <= k
    assert int(cursor.visible(k - 1)['LapNumber'].max()) <= k - 1 if k > cursor.first_lap else True


def test_replay_cursor_clamps_and_steps(cursor):
    cursor.seek(10 ** 6)
    assert cursor.lap == cursor.last_lap and cursor.at_end
    cursor.seek(-5)
    assert cursor.lap == cursor.first_lap
    cursor.step(3)
    assert cursor.lap == cursor.first_lap + 3
    assert int(cursor.visible()['LapNumber'].max()) <= cursor.lap      # <= : a red-flag lap may have no row


def test_live_session_never_reads_lap_k_plus_1(race_csv, lock_v2_path):
    from evaluation.red_team.leakage_audit import future_read_spy
    from live.lapfeed import LapFeed
    r = future_read_spy(EVENT, DRIVER, through_lap=12)
    assert r['status'] == 'PASS', r
    expected = sum(1 for k in LapFeed(EVENT).laps_of(DRIVER) if k <= 12)        # rows that exist through lap 12 (a red-flag lap may be missing)
    assert r['laps_processed'] == expected and r['feed_calls'] > 0 and not r['violations'] and not r['deny_list_hits'] and not r['estimator_errors'], r


def test_future_read_spy_catches_a_planted_leak(race_csv, lock_v2_path):
    """Deliberate violation: the proxy hands the estimator row k+1 while lap k is being produced."""
    from evaluation.red_team.leakage_audit import future_read_spy
    r = future_read_spy(EVENT, DRIVER, through_lap=3, inject=True)
    assert r['status'] == 'FAIL' and any('requested while producing lap' in v for v in r['violations']), r['violations'][:3]


def test_lapfeed_accessors_are_bounded_for_every_lap(proto):
    """Property over the whole synthetic mini race (3 drivers x 14 laps): for every driver and every k, through() never
    returns a lap beyond k, row() is lap k itself, and field_at() only uses laps completed at or before the cutoff."""
    from live.lapfeed import LapFeed
    csv = proto / 'fixtures' / 'mini_race' / 'Mini_R.csv'
    feed = LapFeed('Mini', path=csv)
    checked = 0
    for d in feed.drivers:
        for k in feed.laps_of(d):
            th = feed.through(d, k)
            assert int(th['LapNumber'].max()) <= k and len(th) == sum(1 for x in feed.laps_of(d) if x <= k)
            row = feed.row(d, k)
            assert row is not None and int(row['LapNumber']) == k
            cutoff = float(row['t_min']) * 60.0 + float(row['lap_s'])
            for car in feed.field_at(d, k):
                assert car.lap <= k and car.t_end_s <= cutoff + 1e-9 and car.projected == (car.lap < k), (d, k, car)
            assert feed.row(d, k + 1) is None or int(feed.row(d, k + 1)['LapNumber']) == k + 1   # asking for k+1 is a different k, never a side effect of k
            checked += 1
    assert checked == 3 * 14, checked


def test_lapfeed_guard_fires_on_a_tampered_frame(proto):
    """Deliberate violation: a per-driver frame whose boolean mask is ignored (a broken filter) must trip the guard in through()."""
    import pandas as pd
    from live.lapfeed import LapFeed, FutureDataError

    class NoFilter:
        """Looks like the per-driver frame but returns every row for a boolean mask."""
        def __init__(self, df):
            self.df = df
        def __getitem__(self, key):
            return self.df[key] if isinstance(key, str) else self.df
        def __getattr__(self, name):
            return getattr(self.df, name)

    feed = LapFeed('Mini', path=proto / 'fixtures' / 'mini_race' / 'Mini_R.csv')
    assert int(feed.through('ALP', 5)['LapNumber'].max()) <= 5
    feed._by_driver['ALP'] = NoFilter(feed._by_driver['ALP'])
    with pytest.raises(FutureDataError):
        feed.through('ALP', 5)
