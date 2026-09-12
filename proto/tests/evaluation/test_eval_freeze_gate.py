"""Freeze gate and dry-run flag (lead decision, 12 Sep 2026): holdout_per_race.json is never written without a valid freeze
(all four flags true plus a git_commit); every aggregate carries dry_run_before_freeze / quotable; the dry-run warning is
printed; manifest tamper detection (body, metadata and sidecar variants)."""
from __future__ import annotations

import itertools
import json
import shutil
from pathlib import Path

import pytest

from evaluation import MANIFEST_PATH, MANIFEST_SHA_PATH, PROTO
from evaluation.holdout import evaluator as E

VALID = dict(model_frozen=True, feature_list_frozen=True, gate_threshold_frozen=True, provider_frozen=True, git_commit='cdb1a45')
FLAG_COMBOS = [c for c in itertools.product([True, False], repeat=4) if not all(c)]


def _results():
    agg = dict(weekends=dict(sealed=2, forecast=2, weekend_level_abstention=0), forecast=dict(n_weekends=2), hidden_stop=dict(pooled=dict(n_cases=0)), regret=dict(plans={}), cells={})
    return dict(per_race={'2099_W1': dict(secret='SECRET-W1'), '2099_W2': dict(secret='SECRET-W2')}, aggregate=agg, leakage=dict(sealed_never_in_pool=True), n_weekends=2)


def _agg(tmp_path):
    return json.loads((tmp_path / 'holdout_aggregate.json').read_text(encoding='utf-8'))


# ---------------------------------------------------------------- (a) never without a valid freeze

@pytest.mark.parametrize('combo', FLAG_COMBOS)
def test_per_race_never_written_with_any_flag_unset(tmp_path, combo):
    freeze = dict(zip(E.FREEZE_FLAGS, combo), git_commit='cdb1a45')
    ok, reason = E.reveal_allowed(freeze)
    assert not ok and 'does not assert' in reason
    w = E.write_outputs(_results(), freeze, tmp_path, 'cdb1a45', quiet=True)
    assert w['reveal'] is False and w['paths']['per_race'] is None and w['dry_run_before_freeze'] is True and w['quotable'] is False
    assert not (tmp_path / 'holdout_per_race.json').exists()
    agg = _agg(tmp_path)
    assert agg['dry_run_before_freeze'] is True and agg['quotable'] is False and agg['reveal']['per_race_written'] is False
    assert 'SECRET' not in json.dumps(agg) and 'per_race' not in agg


@pytest.mark.parametrize('commit', [None, '', '   ', 7, True, ['cdb1a45']])
def test_per_race_never_written_without_git_commit(tmp_path, commit):
    freeze = dict(VALID, git_commit=commit)
    ok, reason = E.reveal_allowed(freeze)
    assert not ok and 'git_commit' in reason
    w = E.write_outputs(_results(), freeze, tmp_path, 'cdb1a45', quiet=True)
    assert w['reveal'] is False and not (tmp_path / 'holdout_per_race.json').exists()
    assert _agg(tmp_path)['quotable'] is False and _agg(tmp_path)['dry_run_before_freeze'] is True


def test_per_race_never_written_when_git_commit_key_is_absent(tmp_path):
    freeze = {k: True for k in E.FREEZE_FLAGS}
    w = E.write_outputs(_results(), freeze, tmp_path, 'cdb1a45', quiet=True)
    assert w['reveal'] is False and not (tmp_path / 'holdout_per_race.json').exists() and _agg(tmp_path)['quotable'] is False


@pytest.mark.parametrize('value', [1, 'true', 'True', 'yes'])
def test_truthy_non_boolean_flags_do_not_count_as_frozen(tmp_path, value):
    freeze = dict(VALID, model_frozen=value)
    w = E.write_outputs(_results(), freeze, tmp_path, 'cdb1a45', quiet=True)
    assert w['reveal'] is False and not (tmp_path / 'holdout_per_race.json').exists()


def test_no_freeze_at_all(tmp_path):
    w = E.write_outputs(_results(), None, tmp_path, 'cdb1a45', quiet=True)
    assert w['reveal'] is False and w['dry_run_before_freeze'] is True and w['quotable'] is False
    assert not (tmp_path / 'holdout_per_race.json').exists() and (tmp_path / 'holdout_aggregate.json').exists()


# ---------------------------------------------------------------- (b) with a valid freeze it is written

def test_per_race_written_under_valid_freeze(tmp_path, capsys):
    w = E.write_outputs(_results(), VALID, tmp_path, 'cdb1a45', quiet=False)
    assert w['reveal'] is True and w['dry_run_before_freeze'] is False and w['quotable'] is True and w['post_holdout_tuning'] is False
    per = json.loads((tmp_path / 'holdout_per_race.json').read_text(encoding='utf-8'))
    assert per['per_race']['2099_W1']['secret'] == 'SECRET-W1' and per['quotable'] is True and per['dry_run_before_freeze'] is False
    agg = _agg(tmp_path)
    assert agg['dry_run_before_freeze'] is False and agg['quotable'] is True and 'warning' not in agg and agg['reveal']['per_race_written'] is True
    out = capsys.readouterr()
    assert 'revealed under freeze' in out.out and 'WARNING' not in out.err
    # the freeze commit may be short or long; a run at the full SHA of the same commit is not post-holdout tuning
    w2 = E.write_outputs(_results(), VALID, tmp_path, 'cdb1a45' + 'e' * 33, quiet=True)
    assert w2['reveal'] is True and w2['post_holdout_tuning'] is False and w2['quotable'] is True


# ---------------------------------------------------------------- (c) dry-run flag logic

def test_dry_run_without_freeze_prints_warning_and_flags_the_file(tmp_path, capsys):
    w = E.write_outputs(_results(), None, tmp_path, 'cdb1a45')
    out = capsys.readouterr()
    assert 'WARNING' in out.err and 'DRY RUN' in out.err and 'quotable=false' in out.err
    assert 'per-race results sealed' in out.out
    agg = _agg(tmp_path)
    assert agg['dry_run_before_freeze'] is True and agg['quotable'] is False
    assert agg['warning'] == E.DRY_RUN_WARNING and agg['quotable_rule'] == E.QUOTABLE_RULE and 'no freeze.json' in agg['freeze_status']
    assert agg['freeze'] is None and agg['post_holdout_tuning'] is None
    assert w['dry_run_before_freeze'] is True and w['quotable'] is False


def test_dry_run_flags_helper():
    assert E.dry_run_flags(None)['dry_run_before_freeze'] is True and E.dry_run_flags(None)['quotable'] is False
    assert E.dry_run_flags(dict(VALID, provider_frozen=False))['quotable'] is False
    assert E.dry_run_flags(dict(VALID, git_commit=None))['quotable'] is False
    f = E.dry_run_flags(VALID)
    assert f['dry_run_before_freeze'] is False and f['quotable'] is True and f['freeze_status'] == 'frozen at commit cdb1a45'


def test_quiet_suppresses_the_print_but_never_the_file_flag(tmp_path, capsys):
    E.write_outputs(_results(), None, tmp_path, 'cdb1a45', quiet=True)
    out = capsys.readouterr()
    assert out.err == '' and out.out == ''
    agg = _agg(tmp_path)
    assert agg['dry_run_before_freeze'] is True and agg['quotable'] is False and agg['warning'] == E.DRY_RUN_WARNING


def test_main_end_to_end_dry_run_then_freeze(tmp_path, synthetic_season, monkeypatch, capsys):
    """The CLI on a synthetic sealed weekend: dry run (no per-race file, flags true/false), then under a freeze at the current
    commit (per-race written, flags false/true, post_holdout_tuning false), then at another commit (post_holdout_tuning true)."""
    season, d, events = synthetic_season['season'], synthetic_season['dir'], synthetic_season['events']
    rid = f'{season}_{events[4]}'
    manifest = dict(race_ids=[rid], holdout_count=1, prohibited_for_tuning=True, holdout_version='synthetic-test',
                    metadata={rid: dict(circuit_class='permanent', degradation_class='high', temperature_regime='mild', sc_or_vsc=False)})
    m, s = tmp_path / 'manifest.json', tmp_path / 'manifest.sha256'
    m.write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding='utf-8')
    s.write_text(E.sha256_of(m) + '  manifest.json\n', encoding='utf-8')
    monkeypatch.setattr(E, 'SEASON_DIRS', {season: d})
    monkeypatch.setattr(E, 'git_sha', lambda *a, **k: 'cdb1a45feedface')
    out = tmp_path / 'out'
    fz = tmp_path / 'freeze.json'
    args = ['--manifest', str(m), '--sha', str(s), '--freeze', str(fz), '--out', str(out), '--no-bootstrap']
    assert E.main(args) == 0
    cap = capsys.readouterr()
    assert 'DRY RUN' in cap.err and 'DRY RUN BEFORE FREEZE' in cap.out and 'per-race results sealed' in cap.out
    agg = json.loads((out / 'holdout_aggregate.json').read_text(encoding='utf-8'))
    assert agg['dry_run_before_freeze'] is True and agg['quotable'] is False and agg['freeze'] is None and agg['warning'] == E.DRY_RUN_WARNING
    assert not (out / 'holdout_per_race.json').exists()
    assert 'per_race' not in agg and 'forecast_rows' not in json.dumps(agg) and agg['leakage_check']['sealed_never_in_pool'] is True
    # the lead writes freeze.json at the current commit
    fz.write_text(json.dumps(dict(VALID, git_commit='cdb1a45', frozen_at='2026-09-13T00:00:00')), encoding='utf-8')
    assert E.main(args) == 0
    cap = capsys.readouterr()
    assert 'WARNING' not in cap.err and 'quotable=true' in cap.out and 'revealed under freeze' in cap.out
    agg2 = json.loads((out / 'holdout_aggregate.json').read_text(encoding='utf-8'))
    assert agg2['dry_run_before_freeze'] is False and agg2['quotable'] is True and agg2['post_holdout_tuning'] is False and 'warning' not in agg2
    per = json.loads((out / 'holdout_per_race.json').read_text(encoding='utf-8'))
    assert rid in per['per_race'] and 'forecast_rows' in per['per_race'][rid] and per['quotable'] is True
    # a later run at another commit keeps the reveal but is flagged as post-holdout tuning
    monkeypatch.setattr(E, 'git_sha', lambda *a, **k: 'deadbeef')
    assert E.main(args) == 0
    agg3 = json.loads((out / 'holdout_aggregate.json').read_text(encoding='utf-8'))
    assert agg3['post_holdout_tuning'] is True and agg3['quotable'] is True and agg3['dry_run_before_freeze'] is False


# ---------------------------------------------------------------- (d) manifest tamper detection

def _copies(tmp_path):
    if not MANIFEST_PATH.exists():
        pytest.skip('sealed manifest not present')
    m, s = tmp_path / 'sealed_holdout_manifest.json', tmp_path / 'sealed_holdout_manifest.sha256'
    shutil.copy(MANIFEST_PATH, m); shutil.copy(MANIFEST_SHA_PATH, s)
    assert E.manifest_check(m, s)['ok']
    return m, s


def test_metadata_tamper_detected(tmp_path, capsys):
    m, s = _copies(tmp_path)
    body = json.loads(m.read_text(encoding='utf-8'))
    rid = body['race_ids'][0]
    body['metadata'][rid]['circuit_class'] = 'edited'            # a single metadata value changed
    m.write_text(json.dumps(body, indent=1, sort_keys=True), encoding='utf-8')
    chk = E.manifest_check(m, s)
    assert not chk['ok'] and 'mismatch' in chk['message']
    assert E.main(['--manifest', str(m), '--sha', str(s), '--out', str(tmp_path / 'out')]) == 2
    assert 'STOP THE LINE' in capsys.readouterr().err and not (tmp_path / 'out').exists()


def test_sidecar_tamper_detected(tmp_path, capsys):
    m, s = _copies(tmp_path)
    s.write_text('0' * 64 + '  sealed_holdout_manifest.json\n', encoding='utf-8')       # the recorded hash edited
    chk = E.manifest_check(m, s)
    assert not chk['ok'] and 'mismatch' in chk['message']
    assert E.main(['--manifest', str(m), '--sha', str(s), '--out', str(tmp_path / 'out')]) == 2
    assert 'STOP THE LINE' in capsys.readouterr().err
    s.write_text('', encoding='utf-8')                                                    # emptied sidecar
    assert not E.manifest_check(m, s)['ok']
    s.unlink()                                                                            # missing sidecar
    assert not E.manifest_check(m, s)['ok'] and 'missing' in E.manifest_check(m, s)['message']


def test_rehashed_but_inconsistent_manifest_is_refused(tmp_path):
    """Re-hashing after opening the holdout does not help: race_ids, metadata, holdout_count and prohibited_for_tuning must agree."""
    m, s = _copies(tmp_path)
    body = json.loads(m.read_text(encoding='utf-8'))
    body['race_ids'] = body['race_ids'][:-1]
    m.write_text(json.dumps(body, indent=1, sort_keys=True), encoding='utf-8')
    s.write_text(E.sha256_of(m) + '  sealed_holdout_manifest.json\n', encoding='utf-8')
    chk = E.manifest_check(m, s)
    assert not chk['ok'] and 'inconsistent' in chk['message'] and 'race_ids and metadata keys differ' in chk['message']
    body['metadata'] = {k: v for k, v in body['metadata'].items() if k in body['race_ids']}
    m.write_text(json.dumps(body, indent=1, sort_keys=True), encoding='utf-8'); s.write_text(E.sha256_of(m) + '  x\n', encoding='utf-8')
    assert 'holdout_count differs' in E.manifest_check(m, s)['message']
    body['holdout_count'] = len(body['race_ids']); body['prohibited_for_tuning'] = False
    m.write_text(json.dumps(body, indent=1, sort_keys=True), encoding='utf-8'); s.write_text(E.sha256_of(m) + '  x\n', encoding='utf-8')
    assert 'prohibited_for_tuning' in E.manifest_check(m, s)['message']


def test_real_manifest_unchanged_since_last_green_checkpoint():
    """The sealed manifest's sha256 equals the one recorded by the newest checkpoint's artifact_hashes.json."""
    if not MANIFEST_PATH.exists():
        pytest.skip('sealed manifest not present')
    recs = sorted((PROTO / 'checkpoints').glob('C*/artifact_hashes.json'))
    if not recs:
        pytest.skip('no checkpoint artifact hashes')
    recorded = json.loads(recs[-1].read_text(encoding='utf-8')).get('evaluation/holdout/sealed_holdout_manifest.json')
    if not recorded:
        pytest.skip('checkpoint does not record the manifest hash')
    chk = E.manifest_check()
    assert chk['ok'] and chk['sha256'].startswith(recorded), (recs[-1], chk['sha256'][:16], recorded)
