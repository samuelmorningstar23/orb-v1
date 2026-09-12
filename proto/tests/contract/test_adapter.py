"""validators/adapt_v1.py: the output validates, the v1 validation numbers survive untouched, and nothing post-race leaks into the forecast."""
import json
import shutil

import pytest

from schemas.lock_v2 import LockV2, compute_forecast_hash
from shared.lockio import sha256_file, strip_nonfinite
from validators import adapt_v1, validate_lock

POST_RACE_KEYS = {'obs', 'obs_se', 'obs_push', 'err_naive', 'err_clean', 'err_cs', 'err_push', 'ratio', 'z', 'n_race', 'completed', 'cost_under_truth_vs_best_s', 'best_under_truth'}


@pytest.fixture(scope='module')
def adapted(tmp_path_factory, v1_lock_path):
    root = tmp_path_factory.mktemp('lockroot')
    out = root / 'out' / 'lock_v2.json'
    model = adapt_v1.adapt(v1_lock_path, out, root, now='2026-09-12T16:00:00')
    return dict(root=root, out=out, model=model, data=json.loads(out.read_text(encoding='utf-8')), v1=strip_nonfinite(json.loads(v1_lock_path.read_text(encoding='utf-8'))))


def test_output_validates_against_the_models_and_the_cli(adapted):
    lock = LockV2.model_validate(adapted['data'])
    assert lock.live_predictor is None and lock.ghost_strategy is None and lock.counterfactuals == []
    assert sorted(lock.blocks()) == ['driver_profile', 'input_availability', 'pre_race_forecast', 'shared', 'validation']
    assert validate_lock.validate(adapted['out'], adapted['root'], strict=True, quiet=True) == 0


def test_validation_numbers_are_copied_exactly(adapted):
    v1_val = adapted['v1']['validation']
    out_val = adapted['data']['validation']
    for key, value in v1_val.items():
        assert out_val[key] == value, f'validation.{key} differs from v1'
    m = adapted['model'].validation
    assert m.mae_all_with_fallback.naive == v1_val['mae_all_with_fallback']['naive']
    assert m.mae_all_with_fallback.clearstint == v1_val['mae_all_with_fallback']['clearstint']
    assert m.calibration.all_with_fallback.r == v1_val['calibration']['all_with_fallback']['r']
    assert m.push_diagnostic.energy_trend_issued.p50 == v1_val['push_diagnostic']['energy_trend_issued']['50%']


def test_documented_headline_numbers(adapted):
    if adapted['v1']['generated_at'] != '2026-09-12T14:31:34':
        pytest.skip('v1 lock regenerated since the documented numbers were recorded')
    m = adapted['model'].validation
    assert round(m.mae_all_with_fallback.naive, 4) == 0.1371
    assert round(m.mae_all_with_fallback.clearstint, 4) == 0.0227
    assert round(m.calibration.all_with_fallback.r, 3) == 0.781


def test_no_post_race_quantity_enters_the_forecast(adapted):
    for ev, e in adapted['data']['pre_race_forecast']['events'].items():
        for c in e['compounds'].values():
            assert not (set(c) & POST_RACE_KEYS), f'{ev} {c["compound"]} carries post-race keys'
        if e['strategy']:
            assert not (set(e['strategy']) & POST_RACE_KEYS)
    text = json.dumps(adapted['data']['pre_race_forecast'])
    assert '"obs"' not in text and 'under_truth' not in text


def test_prospective_event_matches_the_v1_live_block(adapted):
    v1 = adapted['v1']
    events = adapted['data']['pre_race_forecast']['events']
    for ev, live in v1['live'].items():
        assert events[ev]['status'] == 'prospective'
        for c in live['compounds']:
            got = events[ev]['compounds'][c['compound']]
            assert got['prediction'] == c['prediction'] and got['band90'] == c['band90'] and got['basis'] == c['basis'] and got['issued'] == c['issued']
    scored = [ev for ev, e in events.items() if e['status'] == 'leave_one_weekend_out']
    assert set(scored) == {r['event'] for r in v1['validation_rows']} - set(v1['live'])
    snap = adapted['data']['shared']['forecast_snapshot']
    if v1['live']:
        assert snap['kind'] == 'prospective' and snap['event'] in v1['live'] and snap['event_id'] == f"2026_{snap['event']}"


def test_leave_one_out_rows_map_field_by_field(adapted):
    events = adapted['data']['pre_race_forecast']['events']
    for r in adapted['v1']['validation_rows']:
        if r['event'] in adapted['v1']['live']:
            continue
        c = events[r['event']]['compounds'][r['compound']]
        assert (c['prediction'], c['band90'], c['factor'], c['factor_applied'], c['clean'], c['issued']) == (r['pred_clearstint'], [r['lo'], r['hi']], r['k'], bool(r['k_applied']), r['clean'], bool(r['issued']))


def test_forecast_hash_is_stable_across_runs_and_time(adapted, tmp_path, v1_lock_path):
    again = adapt_v1.adapt(v1_lock_path, tmp_path / 'out' / 'lock_v2.json', tmp_path, now='2027-01-01T00:00:00')
    assert again.shared.forecast_hash == adapted['model'].shared.forecast_hash
    assert again.pre_race_forecast.meta.generated_at != adapted['model'].pre_race_forecast.meta.generated_at
    assert compute_forecast_hash(adapted['data']['pre_race_forecast']) == adapted['data']['shared']['forecast_hash']


def test_rows_sidecar_is_written_and_hashed(adapted):
    ref = adapted['data']['validation']['rows']
    path = adapted['root'] / ref['path']
    assert path.exists() and sha256_file(path) == ref['sha256'] and path.stat().st_size == ref['bytes']
    payload = json.loads(path.read_text(encoding='utf-8'))
    assert payload['n_rows'] == len(adapted['v1']['validation_rows']) == len(payload['rows'])
    assert adapted['out'].stat().st_size < 256 * 1024, 'the lock must stay small'


def test_corrupted_copies_are_rejected(adapted, tmp_path):
    root = tmp_path / 'root'
    shutil.copytree(adapted['root'], root)
    sidecar = root / adapted['data']['validation']['rows']['path']
    sidecar.write_text(sidecar.read_text(encoding='utf-8').replace('"n_rows"', '"n_rows_x"', 1), encoding='utf-8')
    assert validate_lock.validate(root / 'out' / 'lock_v2.json', root, quiet=True) == validate_lock.EXIT_HASH
    bad = json.loads(adapted['out'].read_text(encoding='utf-8'))
    bad['validation']['mae_all_with_fallback']['tread_wear_pct'] = 12
    (root / 'out' / 'bad.json').write_text(json.dumps(bad), encoding='utf-8')
    assert validate_lock.validate(root / 'out' / 'bad.json', root, quiet=True) == validate_lock.EXIT_SCHEMA
    sidecar.unlink()
    assert validate_lock.validate(root / 'out' / 'lock_v2.json', root, quiet=True) == 0            # missing sidecar: warning by default
    assert validate_lock.validate(root / 'out' / 'lock_v2.json', root, strict=True, quiet=True) == validate_lock.EXIT_HASH
    assert validate_lock.validate(root / 'out' / 'nope.json', root, quiet=True) == validate_lock.EXIT_FILE


def test_input_availability_is_public_proxy(adapted):
    ia = adapted['model'].input_availability
    assert ia.sensor_mode == 'PUBLIC PROXY'
    assert all(not c.available for c in ia.channels.values() if c.visibility == 'private')
    assert ia.missing_channels == sorted(k for k, c in ia.channels.items() if not c.available)
    assert 'tyre_pressure' in ia.missing_channels and ia.channels['tyre_demand_index'].available
    assert adapted['model'].driver_profile.status == 'stub'


def test_meta_on_every_block(adapted):
    lock = adapted['model']
    for name, block in lock.blocks().items():
        assert block.meta.git_sha and block.meta.model_hash.startswith('sha256:') and block.meta.data_cutoff == adapted['v1']['generated_at'], name
        assert block.meta.generated_at == '2026-09-12T16:00:00'


def test_cli_entry_point(tmp_path, v1_lock_path, capsys):
    rc = adapt_v1.main(['--in', str(v1_lock_path), '--out', str(tmp_path / 'lock_v2.json'), '--root', str(tmp_path)])
    assert rc == 0 and 'forecast_hash sha256:' in capsys.readouterr().out
    assert validate_lock.main([str(tmp_path / 'lock_v2.json'), '--root', str(tmp_path), '--quiet']) == 0
