import json
import numpy as np
import pytest
from conftest import PROTO, geometry, timewarp
from replay import io as rio


def rises(flag):
    f = np.asarray(flag).astype(int)
    return int(((f[1:] == 1) & (f[:-1] == 0)).sum() + (f[0] == 1))


def test_identity_overlay_within_one_sample(mini_traj, mini_track):
    tr, pl = mini_track
    fr = timewarp.build_frames(mini_traj, tr, pl, timewarp.identity_laps(mini_traj))
    one_sample = float(np.diff(mini_traj.S).max())
    dist = np.abs(fr['S_cf'] - fr['S_actual'])
    assert dist.max() <= one_sample and dist.max() < 0.05
    assert np.abs(fr['time_delta_s']).max() < 0.01 and np.abs(fr['distance_delta_m']).max() < 0.05
    assert fr.meta['identity'] is True and fr.meta['finish_delta_s'] == pytest.approx(0.0, abs=0.01)
    assert np.array_equal(fr['compound_cf'], fr['compound_actual']) and np.array_equal(fr['tyre_age_cf'], fr['tyre_age_actual'])


def test_pit_lane_switch_exactly_once_per_stop(mini_traj, mini_track, mini_frames):
    tr, pl = mini_track
    fr, cf = mini_frames
    assert cf.cf_pit_laps == [6, 9] and cf.actual_pit_laps == [6]
    # the mini race has no recorded pit-lane geometry: the actual car never leaves the path, the added stop uses the lane once
    assert rises(fr['act_pit']) == 0 and rises(fr['cf_pit']) == 1
    prog = fr['cf_pit_progress'][fr['cf_pit'] == 1]
    assert np.isfinite(prog).all() and np.all(np.diff(prog) >= -1e-6) and prog[-1] >= 0.9 * pl.length
    assert sum(1 for row in fr.meta['lap_table'] if row['kind'] == 'pit_pair') == 1
    # two added stops -> two switches
    cf2 = timewarp.from_table([dict(lap=k, lap_delta=0.5, cumulative_delta=0.5 * k, pit_state='none') for k in range(1, 15)], cf.actual_stints,
                              [dict(compound='SOFT', first_lap=1, last_lap=6), dict(compound='MEDIUM', first_lap=7, last_lap=9), dict(compound='HARD', first_lap=10, last_lap=12), dict(compound='SOFT', first_lap=13, last_lap=14)],
                              scenario_id='two_stops', actual_pit_laps=[6], cf_pit_laps=[6, 9, 12])
    fr2 = timewarp.build_frames(mini_traj, tr, pl, cf2)
    assert rises(fr2['cf_pit']) == 2 and fr2.meta['finish_delta_s'] == pytest.approx(7.0, abs=0.02)


def test_frames_finite_ordered_and_ranged(mini_frames, mini_traj):
    fr, cf = mini_frames
    for k, a in fr.arrays.items():
        if k.endswith('pit_progress'):
            continue
        assert np.isfinite(a.astype(float)).all(), k
    assert np.all(np.diff(fr['t']) > 0) and np.all(np.diff(fr['S_actual']) >= 0) and np.all(np.diff(fr['S_cf']) >= 0)
    assert np.all(fr['S_cf_q10'] >= fr['S_cf']) and np.all(fr['S_cf_q90'] <= fr['S_cf']), 'q10 (fast) ahead of the median, q90 (slow) behind'
    assert fr.meta['quantile_order_violations'] == 0 and fr.meta['quantile_source'].startswith('whole-curve sampling')
    for k in ('lap_actual', 'lap_cf', 'lap_timing'):
        assert fr[k].min() >= 1 and fr[k].max() <= mini_traj.n_laps
    assert set(np.unique(fr['compound_cf'])) <= {1, 2, 3} and fr['tyre_age_cf'].min() >= 1
    assert np.allclose(fr['s_actual'], np.mod(np.maximum(fr['S_actual'], 0), fr.meta['L']), atol=0.05)   # meta L is rounded to 1 mm


def test_lap_deltas_are_exact_at_every_lap_boundary(mini_frames):
    fr, cf = mini_frames
    assert fr.meta['finish_delta_s'] == pytest.approx(float(cf.cumulative_delta[-1]), abs=0.01)
    cum = {int(k): float(v) for k, v in zip(cf.lap, cf.cumulative_delta)}
    for row in fr.meta['lap_table']:
        if row.get('t_start_cf') is not None and row['lap'] > 1:
            assert row['t_start_cf'] - row['t_start_actual'] == pytest.approx(cum[row['lap'] - 1], abs=0.01), row


def test_fixture_is_labelled_and_deterministic(mini_traj, mini_frames):
    fr, cf = mini_frames
    assert cf.source == 'FIXTURE' and 'FIXTURE' in cf.label and fr.meta['source'] == 'FIXTURE' and 'FIXTURE' in fr.meta['label']
    again = timewarp.fixture_laps(mini_traj, 9, 'HARD')
    assert np.allclose(again.lap_delta, cf.lap_delta) and np.allclose(again.samples, cf.samples)


def test_from_table_reads_workstream1_sidecar_and_lock_plans():
    rec = json.loads((PROTO / 'fixtures' / 'sidecars' / 'cf_monza_nor_lap_deltas.json').read_text())['records']
    lock = json.loads((PROTO / 'fixtures' / 'lock_v2_fixture.json').read_text())
    sc = lock['counterfactuals'][0]
    cf = timewarp.from_table(rec, sc['actual_plan'], sc['counterfactual_plan'], scenario_id=sc['scenario_id'])
    assert cf.actual_pit_laps == [19] and cf.cf_pit_laps == [23] and cf.n_laps == 53
    assert cf.cumulative_delta[-1] == pytest.approx(sum(r['delta_s'] for r in rec), abs=1e-6)
    assert cf.cf_stints[0] == dict(compound='MEDIUM', first_lap=1, last_lap=23) and cf.cf_stints[1]['compound'] == 'HARD'
    assert timewarp.stints_to_lap_map(cf.cf_stints, 53)[1][24] == 1


def test_frames_save_load_and_player_dict(mini_frames, tmp_path):
    fr, _ = mini_frames
    p = tmp_path / 'frames_ALP_test.npz'
    fr.save(p)
    assert rio.verify(p)[0] == 'verified'
    fr2 = timewarp.Frames.load(p)
    assert fr2.n == fr.n and np.allclose(fr2['S_cf'], fr['S_cf'], atol=0.05) and fr2.meta['scenario_id'] == fr.meta['scenario_id']
    d = fr2.to_player_dict()
    json.dumps(d, allow_nan=False)
    assert len(d['t']) == fr.n and d['meta']['L'] == fr.meta['L']
