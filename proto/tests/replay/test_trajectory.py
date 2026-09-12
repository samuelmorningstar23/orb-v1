import numpy as np
import pandas as pd
import pytest
from conftest import geometry, sources, trajectory


def test_frames_grid_monotone_and_lap_numbers(mini_traj, mini_track):
    tr, _ = mini_track
    dt = mini_traj
    assert np.array_equal(dt.t, np.arange(len(dt.t), dtype=float))
    assert np.all(np.diff(dt.S) >= 0) and np.all(np.diff(dt.lap) >= 0)
    assert dt.lap.min() == 1 and dt.lap.max() == 14 == dt.n_laps
    assert abs(dt.S_end - 14 * tr.L) < 0.01 * tr.L
    assert dt.quality['status'] == 'ok' and dt.quality['n_implausible_steps'] == 0


def test_timing_reconciliation(mini_traj):
    q = mini_traj.quality
    assert q['timing_residual_median_abs_m'] < 2.0 and q['timing_residual_max_abs_m'] < 5.0 and q['n_timing_anchors'] == 14


def test_inverse_round_trip(mini_traj):
    dt = mini_traj
    t = np.array([10.0, 100.5, 400.0, 600.25])
    assert np.allclose(dt.t_of_S(dt.S_of_t(t)), t, atol=1e-6)


def test_first_arrival_inverse_keeps_standstills():
    S = np.array([0.0, 10.0, 10.0, 10.0, 30.0]); t = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    Sk, tk = trajectory.first_arrival_inverse(S, t)
    assert np.interp(10.0, Sk, tk) == pytest.approx(1.0)          # first arrival at the plateau value
    assert np.interp(20.0, Sk, tk) == pytest.approx(3.5, abs=1e-5)  # beyond it: from the moment the car moved again


def test_driver_refused_on_degraded_feed(mini_source, mini_track):
    tr, pl = mini_track
    bad = sources.degrade(mini_source, points_per_lap=26)
    with pytest.raises(geometry.QualityRefusal) as ei:
        trajectory.build_trajectory(bad, 'ALP', tr, pl)
    assert 'median 26 distinct position points per lap < 100' in str(ei.value)
    assert ei.value.meta['status'] == 'refused' and ei.value.meta['driver'] == 'ALP'


def test_race_clock_cuts_red_flag(mini_source):
    """Synthetic red flag: the standstill is removed from the race clock, the drive to the standstill is kept."""
    src = mini_source
    t_a, t_r = 200.0, 500.0
    laps = src.laps.copy()
    positions = {}
    for drv, p in src.positions.items():
        t = p['t'].to_numpy(float); x = p['x'].to_numpy(float); y = p['y'].to_numpy(float)
        stop = t >= t_a + 20.0                                  # every car stops 20 s after the abort ...
        x2 = np.where(stop, x[np.searchsorted(t, t_a + 20.0)], x); y2 = np.where(stop, y[np.searchsorted(t, t_a + 20.0)], y)
        shift = t >= t_r                                        # ... and the trace after the restart is what it was
        positions[drv] = pd.DataFrame(dict(t=np.where(shift, t + (t_r - t_a - 20.0), t), x=np.where(shift, x, x2), y=np.where(shift, y, y2))).sort_values('t').drop_duplicates('t')
    ss = pd.DataFrame(dict(t=[0.0, t_a, t_r, 9999.0], status=['Started', 'Aborted', 'Started', 'Finished']))
    src2 = sources.PositionSource(event='Mini', year=2026, session='R', n_laps=14, laps=laps, positions=positions, track_status=src.track_status, session_status=ss)
    cuts = trajectory.race_clock_cuts(src2)
    assert len(cuts) == 1
    a, b = cuts[0]
    assert t_a <= a <= t_a + 40.0 and b == pytest.approx(t_r, abs=1.0)
    rc = trajectory.make_race_clock(0.0, cuts)
    assert rc(b) == pytest.approx(rc(a)) and rc(b + 10.0) - rc(b) == pytest.approx(10.0) and rc(a) == pytest.approx(a)
