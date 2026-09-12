"""Real cached geometry has provenance but never implies scenario availability."""
from pathlib import Path
import sys
from types import SimpleNamespace
import numpy as np
import pytest
from replay import geometry, io, sources
from replay.build_maps import main

MAPS = Path(__file__).resolve().parents[2] / 'out/maps'
EVENTS = ('Australia', 'Austria', 'Barcelona', 'Belgium', 'Japan', 'Netherlands')

@pytest.mark.parametrize('event', EVENTS)
def test_cached_geometry_only_assets(event):
    d = MAPS / event
    if not d.exists():
        pytest.skip('additional recorded geometry not installed')
    meta = io.load_json(d / 'meta.json')
    assert meta['status'] == 'ok'
    assert meta['capabilities'] == dict(canonical_geometry=True, driver_trajectories=False, scenario_replay=False)
    assert meta['drivers'] == {} and meta['frames'] == [] and meta['identity_check'] is None
    assert sorted(p.name for p in d.glob('*.npz')) == ['pitlane.npz', 'track.npz']
    for name in ('meta.json', 'track.npz', 'pitlane.npz'):
        assert io.verify(d / name)[0] == 'verified'
    source = meta['build']['source']
    assert source['offline'] is True and source['cached_source_sha256']
    assert any(p.endswith('/position_data.ff1pkl') for p in source['cached_source_sha256'])
    assert all(len(v) == 64 for v in source['cached_source_sha256'].values())
    track = geometry.TrackPath.load(d)
    assert 1000 < track.L < 10000 and np.isfinite(track.x).all() and np.isfinite(track.y).all()
    assert np.all(np.diff(track.s) > 0)
    assert track.meta['quality']['status'] == 'ok'
    assert track.meta['quality']['residual_rms_m'] < 2
    assert len(track.meta['quality']['drivers_passed']) >= 20


def test_offline_mode_set_after_cache_enable(monkeypatch, tmp_path):
    calls = []
    def session(*args):
        calls.append('session')
        raise LookupError('stop before actual session load')
    monkeypatch.setitem(sys.modules, 'fastf1', SimpleNamespace(
        Cache=SimpleNamespace(enable_cache=lambda p: calls.append('enable'),
                              offline_mode=lambda enabled: calls.append(('offline', enabled))),
        get_session=session))
    with pytest.raises(LookupError):
        sources.from_fastf1(2026, 'Austria', tmp_path, offline=True)
    assert calls == ['enable', ('offline', True), 'session']


def test_geometry_only_refuses_stale_replay_assets(tmp_path):
    d = tmp_path / 'Austria'; d.mkdir()
    (d / 'NOR.npz').write_bytes(b'existing trajectory')
    with pytest.raises(SystemExit) as e:
        main(['--event', 'Austria', '--cache', str(tmp_path), '--out', str(tmp_path), '--geometry-only'])
    assert e.value.code == 2


def test_zandvoort_dashboard_name_resolves_real_dutch_geometry():
    assert io.event_dir('Zandvoort') == io.event_dir('Netherlands')
    assert geometry.TrackPath.load(io.event_dir('Zandvoort')).L > 1000
