"""fixtures/: the mini race loads with pandas and is internally consistent; golden Monza hashes match; fixture sidecars verify."""
import json
import math

import numpy as np
import pandas as pd
import pytest

from shared.lockio import iter_sidecar_refs, sha256_file, sha256_text, verify_sidecar

FEAT_COLUMNS = ['event', 'session', 'Driver', 'LapNumber', 'Stint', 'Compound', 'TyreLife', 'FreshTyre', 'lap_s', 's1', 's2', 's3', 't_min', 'TrackStatus', 'IsAccurate',
                'pit_in', 'pit_out', 'deleted', 'energy_MJ', 'e_lat', 'e_long', 'traffic', 'full_throttle', 'n_tel', 'pos_distinct', 'stale_share', 'track_temp', 'rain']


@pytest.fixture(scope='module')
def mini(proto_dir):
    d = proto_dir / 'fixtures' / 'mini_race'
    return dict(dir=d, laps=pd.read_csv(d / 'Mini_R.csv'), pos=pd.read_csv(d / 'Mini_positions.csv'), manifest=json.loads((d / 'manifest.json').read_text(encoding='utf-8')))


def test_mini_race_loads_in_the_feat_layout(mini):
    laps = mini['laps']
    assert list(laps.columns) == FEAT_COLUMNS
    assert len(laps) == 42 and sorted(laps.Driver.unique()) == ['ALP', 'BRV', 'CHR']
    for drv, g in laps.groupby('Driver'):
        assert list(g.LapNumber) == list(range(1, 15)), drv
        assert g.pit_in.sum() == 1 and g.pit_out.sum() == 1, drv
        pit_lap = int(g.loc[g.pit_in, 'LapNumber'].iloc[0])
        assert int(g.loc[g.pit_out, 'LapNumber'].iloc[0]) == pit_lap + 1 == mini['manifest']['pit_laps'][drv] + 1
        assert list(g.Stint.unique()) == [1.0, 2.0] and g.loc[g.LapNumber > pit_lap, 'Stint'].eq(2.0).all()
        assert float(g.loc[g.pit_out, 'TyreLife'].iloc[0]) == 1.0 and g.Compound.nunique() == 2
        assert g.loc[g.LapNumber == pit_lap, 'lap_s'].iloc[0] > g.lap_s.median() + 10
    assert laps.lap_s.gt(0).all() and set(laps.Compound) <= {'SOFT', 'MEDIUM', 'HARD'} and (laps.TrackStatus == 1).all()
    assert laps.dtypes['pit_in'] == bool and laps.dtypes['IsAccurate'] == bool and laps.dtypes['rain'] == bool
    ok = laps.LapNumber > 1
    assert np.allclose(laps.loc[ok, 's1'] + laps.loc[ok, 's2'] + laps.loc[ok, 's3'], laps.loc[ok, 'lap_s'], atol=2e-3)
    assert laps.loc[laps.LapNumber == 1, 's1'].isna().all()
    assert np.allclose(laps.e_lat + laps.e_long, laps.energy_MJ, atol=1e-3)


def test_mini_positions_are_4hz_on_the_loop_and_match_lap_starts(mini):
    pos, laps, man = mini['pos'], mini['laps'], mini['manifest']
    assert list(pos.columns) == ['Driver', 'SessionTime_s', 'X', 'Y']
    track = man['track']
    a, r = track['straight_m'], track['radius_m']
    for drv, g in pos.groupby('Driver'):
        assert np.allclose(np.diff(g.SessionTime_s.values), 0.25), drv
        assert g.SessionTime_s.iloc[0] == 0.0 and (g.X.iloc[0], g.Y.iloc[0]) == (0.0, 0.0)
        on_straight = np.isclose(g.Y, 0.0, atol=0.02) | np.isclose(g.Y, 2 * r, atol=0.02)
        on_arc = np.isclose(np.hypot(g.X - a, g.Y - r), r, atol=0.05) | np.isclose(np.hypot(g.X, g.Y - r), r, atol=0.05)
        assert (on_straight | on_arc).all(), f'{drv}: samples off the loop'
        lg = laps[laps.Driver == drv]
        starts, durations = lg.t_min.values * 60.0, lg.lap_s.values
        times = g.SessionTime_s.values
        for t0, dur in zip(starts, durations):
            j = int(np.searchsorted(times, t0 - 1e-9))                     # first sample at or after the lap start
            travel = track['length_m'] / dur * (times[j] - t0)               # metres covered since crossing the line
            assert math.hypot(g.X.iloc[j], g.Y.iloc[j]) <= travel + 0.05, f'{drv}: sample after lap start {t0:.2f}s is not just past the start line'
        assert len(g) == int(math.ceil((starts[-1] + durations[-1]) * 4)), drv


def test_mini_manifest_matches_files(mini):
    man = mini['manifest']
    for name, digest in man['sha256'].items():
        assert sha256_file(mini['dir'] / name) == digest, name
    assert man['columns']['laps'] == FEAT_COLUMNS and man['n_laps'] == 14 and man['sample_rate_hz'] == 4


def test_golden_race_layout_and_hashes(proto_dir, mini):
    golden = json.loads((proto_dir / 'fixtures' / 'golden_race.json').read_text(encoding='utf-8'))
    assert golden['columns'] == FEAT_COLUMNS == list(mini['laps'].columns)
    assert golden['header_sha256'] == sha256_text(','.join(golden['columns']))
    assert set(golden['files']) == {'FP1', 'FP2', 'FP3', 'Q', 'R'} and golden['event_id'] == '2026_Monza'
    paths = {s: proto_dir / f['path'] for s, f in golden['files'].items()}
    if not all(p.exists() for p in paths.values()):
        pytest.skip('feat/Monza_*.csv not present on this machine (gitignored)')
    for s, f in golden['files'].items():
        p = paths[s]
        assert sha256_file(p) == f['sha256'], f'{s}: golden hash mismatch'
        assert p.stat().st_size == f['bytes']
        with p.open('rb') as fh:
            assert sum(1 for _ in fh) - 1 == f['rows']
    assert paths['R'].open(encoding='utf-8').readline().rstrip('\n').split(',') == FEAT_COLUMNS


def test_fixture_sidecars_verify(fixture_lock, proto_dir):
    refs = dict(iter_sidecar_refs(fixture_lock))
    assert len(refs) >= 5
    for where, ref in refs.items():
        status, msg = verify_sidecar(ref, proto_dir)
        assert status == 'ok', f'{where}: {msg}'


def test_fixture_generator_is_deterministic_and_matches_disk(fixture_lock):
    from fixtures import make_fixtures
    first, second = make_fixtures.build_lock(), make_fixtures.build_lock()
    assert first == second == fixture_lock, 'fixtures/lock_v2_fixture.json is out of step with make_fixtures.py: regenerate it'
    laps1, pos1, man1 = make_fixtures.build_mini_race()
    laps2, pos2, man2 = make_fixtures.build_mini_race()
    pd.testing.assert_frame_equal(laps1, laps2)
    pd.testing.assert_frame_equal(pos1, pos2)
    assert man1 == man2
