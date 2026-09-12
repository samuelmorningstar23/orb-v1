"""shared/lockio.py: atomic writes never leave a partial file; canonical JSON and forecast_hash ignore key order."""
import hashlib
import json
import os
import stat

import pytest

from schemas.lock_v2 import PreRaceForecast, compute_forecast_hash
from shared import lockio


def _only(dirpath, name):
    return sorted(p.name for p in dirpath.iterdir()) == [name]


def test_atomic_write_serialisation_failure_touches_nothing(tmp_path):
    target = tmp_path / 'lock.json'
    target.write_text('{"old": true}', encoding='utf-8')
    with pytest.raises(TypeError):
        lockio.atomic_write_json(target, {'bad': object()})
    with pytest.raises(ValueError):
        lockio.atomic_write_json(target, {'bad': float('nan')})
    assert target.read_text(encoding='utf-8') == '{"old": true}'
    assert _only(tmp_path, 'lock.json'), 'no temp file may be left behind'


def test_atomic_write_replace_failure_leaves_no_partial_file(tmp_path, monkeypatch):
    target = tmp_path / 'lock.json'
    target.write_text('{"old": true}', encoding='utf-8')

    def boom(src, dst):
        raise OSError('simulated disk failure during rename')

    monkeypatch.setattr(lockio.os, 'replace', boom)
    with pytest.raises(OSError):
        lockio.atomic_write_json(target, {'new': True})
    assert target.read_text(encoding='utf-8') == '{"old": true}'
    assert _only(tmp_path, 'lock.json')


def test_atomic_write_write_failure_leaves_no_partial_file(tmp_path, monkeypatch):
    target = tmp_path / 'sub' / 'lock.json'

    def boom(fd):
        raise OSError('simulated fsync failure')

    monkeypatch.setattr(lockio.os, 'fsync', boom)
    with pytest.raises(OSError):
        lockio.atomic_write_json(target, {'new': True})
    assert not target.exists() and list(target.parent.iterdir()) == []


def test_atomic_write_succeeds_and_honours_umask(tmp_path):
    target = tmp_path / 'nested' / 'lock.json'
    lockio.atomic_write_json(target, {'b': 1, 'a': [1.5, None]})
    assert json.loads(target.read_text(encoding='utf-8')) == {'b': 1, 'a': [1.5, None]}
    assert _only(target.parent, 'lock.json')
    mask = os.umask(0)
    os.umask(mask)
    assert stat.S_IMODE(target.stat().st_mode) == (0o666 & ~mask)
    lockio.atomic_write_json(target, {'second': 2})
    assert json.loads(target.read_text(encoding='utf-8')) == {'second': 2}


def test_canonical_json_is_sorted_compact_and_refuses_nan():
    assert lockio.canonical_json({'b': 1, 'a': {'d': 2.5, 'c': [3, 'x', None, True]}}) == '{"a":{"c":[3,"x",null,true],"d":2.5},"b":1}'
    assert lockio.canonical_json({'u': 'caf\u00e9'}) == '{"u":"caf\u00e9"}'
    with pytest.raises(ValueError):
        lockio.canonical_json({'x': float('inf')})


def test_forecast_hash_stable_across_key_order_and_meta():
    a = {'meta': {'generated_at': '2026-09-12T14:00:00', 'git_sha': 'abc1234'}, 'events': {'Madrid': {'compounds': {'SOFT': {'prediction': 0.0976, 'band90': [-0.0956, 0.3001]}}}}}
    b = {'events': {'Madrid': {'compounds': {'SOFT': {'band90': [-0.0956, 0.3001], 'prediction': 0.0976}}}}, 'meta': {'git_sha': 'fffffff', 'generated_at': '2027-01-01T00:00:00'}}
    assert lockio.forecast_hash(a) == lockio.forecast_hash(b)
    assert lockio.forecast_hash(a) == lockio.forecast_hash(json.loads(json.dumps(b)))
    assert lockio.forecast_hash(a).startswith('sha256:') and len(lockio.forecast_hash(a)) == 7 + 64
    c = json.loads(json.dumps(a))
    c['events']['Madrid']['compounds']['SOFT']['prediction'] = 0.0977
    assert lockio.forecast_hash(c) != lockio.forecast_hash(a)
    assert lockio.content_hash(a) != lockio.content_hash(b), 'content_hash keeps meta; only forecast_hash strips it'


def test_compute_forecast_hash_materialises_defaults(fixture_lock):
    block = fixture_lock['pre_race_forecast']
    stripped = json.loads(json.dumps(block))
    for c in stripped['events']['Monza']['compounds'].values():
        c.pop('factor_from_n_weekends')          # optional field with default None
    assert lockio.forecast_hash(stripped) != lockio.forecast_hash(block), 'raw dicts differ...'
    assert compute_forecast_hash(stripped) == compute_forecast_hash(block) == fixture_lock['shared']['forecast_hash'], '...but the validated hash is the same'
    model = PreRaceForecast.model_validate(block)
    assert compute_forecast_hash(model) == fixture_lock['shared']['forecast_hash']


def test_sha256_file_and_sidecar_refs(tmp_path):
    root = tmp_path
    f = root / 'out' / 'thing.json'
    f.parent.mkdir()
    f.write_bytes(b'{"x": 1}\n')
    assert lockio.sha256_file(f) == hashlib.sha256(b'{"x": 1}\n').hexdigest()
    ref = lockio.sidecar_ref(f, root, format='json')
    assert ref == {'path': 'out/thing.json', 'sha256': lockio.sha256_file(f), 'bytes': 9, 'format': 'json'}
    assert lockio.verify_sidecar(ref, root)[0] == 'ok'
    assert lockio.verify_sidecar({**ref, 'sha256': 'sha256:' + ref['sha256']}, root)[0] == 'ok'
    f.write_bytes(b'{"x": 2}\n')
    assert lockio.verify_sidecar(ref, root)[0] == 'mismatch'
    f.unlink()
    assert lockio.verify_sidecar(ref, root)[0] == 'missing'
    assert lockio.verify_sidecar({'path': '../x', 'sha256': ref['sha256']}, root)[0] == 'mismatch'
    ref2 = lockio.write_sidecar_json({'rows': [1, 2, 3]}, root / 'out' / 'rows.json', root)
    assert ref2['path'] == 'out/rows.json' and ref2['format'] == 'json' and lockio.verify_sidecar(ref2, root)[0] == 'ok'


@pytest.mark.parametrize('bad', ['/abs.json', '../up.json', 'a/../b.json', './x.json', 'a\\b.json', 'C:/x.json', ''])
def test_relative_posix_rules(bad):
    with pytest.raises(ValueError):
        lockio.check_relative_posix(bad)
    assert lockio.check_relative_posix('out/lock_v2_sidecars/rows.json') == 'out/lock_v2_sidecars/rows.json'


def test_iter_sidecar_refs_finds_nested_references(fixture_lock):
    found = dict(lockio.iter_sidecar_refs(fixture_lock))
    assert {'$.validation.rows', '$.validation.sealed_holdout', '$.live_predictor.state_history', '$.ghost_strategy.ghost_replay', '$.counterfactuals[0].assets.lap_deltas'} <= set(found)
    assert all(len(r['sha256']) == 64 for r in found.values())


def test_strip_nonfinite():
    assert lockio.strip_nonfinite({'a': float('nan'), 'b': [1.0, float('-inf'), {'c': 2}]}) == {'a': None, 'b': [1.0, None, {'c': 2}]}
