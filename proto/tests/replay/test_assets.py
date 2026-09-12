"""Built assets under proto/out/maps (skipped when not built): sidecars verify, Monza geometry sane, Hungary refused."""
import numpy as np
import pytest
from conftest import MAPS, geometry, timewarp, trajectory
from replay import io as rio

monza = pytest.mark.skipif(not (MAPS / 'Monza' / 'track.npz').exists(), reason='Monza assets not built')
hungary = pytest.mark.skipif(not (MAPS / 'Hungary' / 'meta.json').exists(), reason='Hungary meta not built')


@monza
def test_monza_track_and_pitlane():
    d = MAPS / 'Monza'
    for f in ('track.npz', 'pitlane.npz', 'meta.json'):
        assert rio.verify(d / f)[0] == 'verified', f
    tr = geometry.TrackPath.load(d); pl = geometry.PitLane.load(d)
    assert abs(tr.L - 5793) / 5793 < 0.03 and abs(tr.grid_m - 10) < 0.2 and np.all(np.diff(tr.s) > 0)
    assert tr.meta['quality']['status'] == 'ok' and len(tr.meta['quality']['drivers_passed']) >= 20 and tr.meta['quality']['residual_rms_m'] < 2.0
    assert pl.source == 'recorded' and 300 < pl.length < 1500 and 15 < pl.transit_time < 60 and pl.meta['n_stops'] >= 3
    assert tr.pit_entry_flag.sum() == 1 and tr.pit_exit_flag.sum() == 1


@monza
def test_monza_drivers_and_identity():
    meta = rio.load_json(MAPS / 'Monza' / 'meta.json')
    ok = [k for k, v in meta['drivers'].items() if v['status'] == 'ok']
    assert len(ok) >= 20
    for k in ok[:5]:
        assert rio.verify(MAPS / 'Monza' / f'{k}.npz')[0] == 'verified'
    dt = trajectory.DriverTrajectory.load(MAPS / 'Monza' / 'NOR.npz')
    assert dt.n_laps == 53 and np.all(np.diff(dt.S) >= 0) and dt.quality['median_distinct_per_lap'] >= 100
    ident = meta['identity_check']
    assert ident['within_one_sample'] and ident['max_abs_distance_m'] < 1.0 and ident['max_abs_time_s'] < 0.05


@monza
def test_monza_frames_ordered():
    files = sorted((MAPS / 'Monza').glob('frames_NOR_*.npz'))
    assert files
    fr = timewarp.Frames.load(files[0])
    assert rio.verify(files[0])[0] == 'verified' and fr.meta['source'] in ('workstream2', 'FIXTURE') and fr.meta['label']
    if fr.meta['source'] == 'workstream2':
        assert 'out/counterfactual/' in fr.meta['label'] and fr.meta['quantile_source'] == 'per-lap q10 / q90 delta curves'
    assert np.all(np.diff(fr['t']) > 0) and np.all(fr['S_cf_q10'] >= fr['S_cf']) and np.all(fr['S_cf_q90'] <= fr['S_cf'])
    assert fr.meta['finish_delta_s'] == pytest.approx(fr.meta['cumulative_delta_table_s'], abs=0.01)
    assert set(np.unique(fr['track_status'])) >= {1, 4}, 'the Monza race carried SC / VSC / red periods'


@hungary
def test_hungary_refused():
    meta = rio.load_json(MAPS / 'Hungary' / 'meta.json')
    assert meta['status'] == 'refused' and 'degraded at source' in meta['reason'] and meta['quality']['status'] == 'refused'
    assert not (MAPS / 'Hungary' / 'track.npz').exists()
    assert sum(1 for v in meta['quality']['per_driver'].values() if v['ok']) <= 2
