import json
import numpy as np
import pytest
from conftest import MINI, geometry, sources
from replay import io as rio


def stadium_distance(x, y, straight=373.009, R=120.0):
    """Distance to the analytic centreline of the fixture's stadium (start (0,0) heading +x, counter-clockwise)."""
    out = []
    for xi, yi in zip(x, y):
        c = [abs(np.hypot(xi - straight, yi - R) - R), abs(np.hypot(xi, yi - R) - R)]
        if 0 <= xi <= straight:
            c += [abs(yi), abs(yi - 2 * R)]
        out.append(min(c))
    return np.array(out)


def test_path_closed_uniform_and_monotonic(mini_track):
    tr, _ = mini_track
    manifest = json.loads((MINI / 'manifest.json').read_text())
    assert tr.s[0] == 0.0 and np.all(np.diff(tr.s) > 0)
    steps = np.diff(tr.s)
    assert np.allclose(steps, tr.grid_m, atol=1e-6) and abs(tr.grid_m - 10.0) < 0.5
    assert tr.s[-1] < tr.L
    closure = np.hypot(tr.x[0] - tr.x[-1], tr.y[0] - tr.y[-1])
    assert abs(closure - tr.grid_m) < 0.25 * tr.grid_m, 'the last grid point must sit one step before the first'
    assert abs(tr.L - manifest['track']['length_m']) / manifest['track']['length_m'] < 0.01
    assert tr.n_points == len(tr.x) == len(tr.y) == len(tr.sector)


def test_path_matches_recorded_line(mini_track):
    tr, _ = mini_track
    assert stadium_distance(tr.x, tr.y).max() < 1.0
    q = tr.meta['quality']
    assert q['status'] == 'ok' and q['share_within_5m'] == 1.0 and q['residual_rms_m'] < 1.0
    assert q['start_line_median_abs_dev_m'] < 1.0


def test_projection_round_trip(mini_track):
    tr, _ = mini_track
    rng = np.random.default_rng(1)
    s_q = rng.uniform(0, tr.L, 300)
    xy = tr.xy_at(s_q)
    s_p, d = tr.project(xy[:, 0], xy[:, 1])
    wrap = np.mod(s_p - s_q + tr.L / 2, tr.L) - tr.L / 2
    assert np.abs(wrap).max() < 0.01 and d.max() < 1e-6
    # normal offsets of 0.5 m must not move the arc-length coordinate by more than a grid fraction
    tan = tr.polyline.tangent_at(s_q); normal = np.column_stack([-tan[:, 1], tan[:, 0]])
    xy2 = xy + 0.5 * normal
    s_p2, d2 = tr.project(xy2[:, 0], xy2[:, 1])
    wrap2 = np.mod(s_p2 - s_q + tr.L / 2, tr.L) - tr.L / 2
    assert np.abs(wrap2).max() < 0.5 and np.abs(d2 - 0.5).max() < 0.05


def test_sectors_and_pit_flags(mini_track):
    tr, pl = mini_track
    assert set(np.unique(tr.sector)) == {0, 1, 2}
    assert np.all(np.diff(tr.sector.astype(int)) >= 0), 'sector index must be non-decreasing along s'
    f1, f2 = tr.sector_fractions()
    assert 0 < f1 < f2 < 1
    assert tr.pit_entry_flag.sum() == 1 and tr.pit_exit_flag.sum() == 1
    assert abs(tr.s[tr.pit_entry_flag][0] - pl.entry_s) <= tr.grid_m and abs(tr.s[tr.pit_exit_flag][0] - pl.exit_s) <= tr.grid_m


def test_pitlane_schematic_fallback_is_labelled(mini_track):
    _, pl = mini_track
    assert pl.source == 'schematic' and pl.meta['source'] == 'schematic' and 'offset chord' in pl.meta['note']
    assert pl.length > 100 and pl.transit_time > 5 and 0 < pl.s_line < pl.length
    assert np.all(np.diff(pl.transit_s) >= 0) and pl.transit_s[-1] == pytest.approx(pl.length)
    assert pl.entry_s > pl.exit_s, 'the lane wraps around the start/finish line'


def test_quality_refusal_on_degraded_feed(mini_source, tmp_path):
    bad = sources.degrade(mini_source, points_per_lap=26)
    passing, records = sources.gate_drivers(bad)
    assert passing == [] and all(r['median_distinct_per_lap'] < 100 for r in records)
    with pytest.raises(geometry.QualityRefusal) as ei:
        geometry.build_track(bad)
    assert 'degraded at source' in str(ei.value) and '0 of 3 drivers' in str(ei.value)
    path = geometry.write_refusal(tmp_path / 'Mini', ei.value)
    meta = rio.load_json(path)
    assert meta['status'] == 'refused' and meta['quality']['status'] == 'refused' and rio.verify(path)[0] == 'verified'
    assert not (tmp_path / 'Mini' / 'track.npz').exists()


def test_save_load_and_sidecars(mini_track, tmp_path):
    tr, pl = mini_track
    tr.save(tmp_path); pl.save(tmp_path)
    for name in ('track.npz', 'pitlane.npz'):
        assert rio.verify(tmp_path / name)[0] == 'verified'
    tr2 = geometry.TrackPath.load(tmp_path); pl2 = geometry.PitLane.load(tmp_path)
    assert np.allclose(tr2.x, tr.x, atol=1e-3) and tr2.L == pytest.approx(tr.L) and np.array_equal(tr2.sector, tr.sector)
    assert pl2.source == pl.source and np.allclose(pl2.transit_s, pl.transit_s, atol=1e-2)
    with open(tmp_path / 'track.npz', 'r+b') as f:
        f.seek(40); f.write(b'\x00\x01')
    assert rio.verify(tmp_path / 'track.npz')[0] == 'mismatch'
    with pytest.raises(ValueError):
        geometry.TrackPath.load(tmp_path)
