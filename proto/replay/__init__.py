"""Orb v1 Race Twin geometry and animation (roadmap v5 task 0.5).

    sources     PositionSource: one plain container for laps, positions, track and session status (FastF1 or fixture)
    geometry    canonical closed track path on a uniform ~10 m arc-length grid, sectors, pit flags, pit-lane polyline
    trajectory  per-driver unwrapped race distance S(t) at 1 Hz with lap numbers, pit excursions and a quality gate
    timewarp    counterfactual ghost t_cf(S) = t_actual(S) + Delta(S), inverted to s(t), pit-lane switch, 1 Hz frames
    io          compressed float32 .npz and JSON with sha256 sidecars (same '<file>.sha256' convention as app_v2)
    build_maps  CLI that builds proto/out/maps/<event>/ for a cached FastF1 race; perf_harness measures the player

Nothing in this package imports app_v2, a model or the lock; the dashboard component
(app_v2/components/race_twin) consumes the saved assets only.
"""
from replay.sources import PositionSource, MIN_DISTINCT_PER_LAP
from replay.geometry import TrackPath, PitLane, QualityRefusal, build_track, build_pitlane, attach_pit_flags
from replay.trajectory import DriverTrajectory, build_trajectory
from replay.timewarp import CounterfactualLaps, Frames, build_frames, from_table, fixture_laps, identity_laps

__all__ = ['PositionSource', 'MIN_DISTINCT_PER_LAP', 'TrackPath', 'PitLane', 'QualityRefusal', 'build_track', 'build_pitlane', 'attach_pit_flags',
           'DriverTrajectory', 'build_trajectory', 'CounterfactualLaps', 'Frames', 'build_frames', 'from_table', 'fixture_laps', 'identity_laps']
