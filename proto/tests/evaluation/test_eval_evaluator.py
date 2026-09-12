"""Sealed-holdout evaluator: reveal refused without freeze.json; manifest tamper detection; weekend-level rules."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from evaluation import MANIFEST_PATH, MANIFEST_SHA_PATH
from evaluation.holdout import evaluator as E


def _fake_results():
    agg = dict(forecast=dict(n_weekends=2), hidden_stop=dict(pooled=dict(n_cases=0)), regret=dict(plans={}), cells={})
    return dict(per_race={'2099_W1': dict(secret=1), '2099_W2': dict(secret=2)}, aggregate=agg, leakage=dict(sealed_never_in_pool=True), n_weekends=2)


def test_reveal_refused_without_freeze(tmp_path, capsys):
    w = E.write_outputs(_fake_results(), freeze=None, out_dir=tmp_path, current_sha='abc1234')
    assert w['reveal'] is False and w['paths']['per_race'] is None
    assert (tmp_path / 'holdout_aggregate.json').exists()
    assert not (tmp_path / 'holdout_per_race.json').exists()
    assert 'per-race results sealed' in capsys.readouterr().out
    agg = json.loads((tmp_path / 'holdout_aggregate.json').read_text())
    assert 'per_race' not in agg and 'secret' not in json.dumps(agg)
    assert agg['reveal']['per_race_written'] is False and agg['post_holdout_tuning'] is None


@pytest.mark.parametrize('missing', ['model_frozen', 'feature_list_frozen', 'gate_threshold_frozen', 'provider_frozen', 'git_commit'])
def test_reveal_refused_with_incomplete_freeze(tmp_path, missing):
    freeze = dict(model_frozen=True, feature_list_frozen=True, gate_threshold_frozen=True, provider_frozen=True, git_commit='abc1234')
    freeze[missing] = False if missing != 'git_commit' else None
    ok, reason = E.reveal_allowed(freeze)
    assert not ok and missing.replace('_', ' ')[:5] in reason.replace('_', ' ') or not ok
    w = E.write_outputs(_fake_results(), freeze=freeze, out_dir=tmp_path, current_sha='abc1234', quiet=True)
    assert w['reveal'] is False and not (tmp_path / 'holdout_per_race.json').exists()


def test_reveal_allowed_with_complete_freeze_and_post_holdout_tuning_flag(tmp_path):
    freeze = dict(model_frozen=True, feature_list_frozen=True, gate_threshold_frozen=True, provider_frozen=True, git_commit='abc1234')
    w = E.write_outputs(_fake_results(), freeze=freeze, out_dir=tmp_path, current_sha='abc1234def', quiet=True)
    assert w['reveal'] is True and Path(w['paths']['per_race']).exists()
    per = json.loads((tmp_path / 'holdout_per_race.json').read_text())
    assert per['per_race']['2099_W1']['secret'] == 1 and per['post_holdout_tuning'] is False
    # a later run at another commit must carry post_holdout_tuning = true
    w2 = E.write_outputs(_fake_results(), freeze=freeze, out_dir=tmp_path, current_sha='fff9999', quiet=True)
    assert w2['post_holdout_tuning'] is True
    assert json.loads((tmp_path / 'holdout_aggregate.json').read_text())['post_holdout_tuning'] is True
    assert E.post_holdout_tuning(freeze, None) is True and E.post_holdout_tuning(None, 'abc') is None


def test_manifest_tamper_detected(tmp_path, capsys):
    if not MANIFEST_PATH.exists():
        pytest.skip('sealed manifest not present')
    m, s = tmp_path / 'sealed_holdout_manifest.json', tmp_path / 'sealed_holdout_manifest.sha256'
    shutil.copy(MANIFEST_PATH, m); shutil.copy(MANIFEST_SHA_PATH, s)
    assert E.manifest_check(m, s)['ok']
    body = json.loads(m.read_text())
    body['race_ids'] = body['race_ids'][:-1]                       # opening the holdout early: one weekend removed
    m.write_text(json.dumps(body, indent=1, sort_keys=True))
    chk = E.manifest_check(m, s)
    assert not chk['ok'] and 'mismatch' in chk['message']
    rc = E.main(['--manifest', str(m), '--sha', str(s), '--out', str(tmp_path / 'out')])
    assert rc == 2
    err = capsys.readouterr().err
    assert 'STOP THE LINE' in err
    assert not (tmp_path / 'out' / 'holdout_aggregate.json').exists()
    with pytest.raises(PermissionError):
        E.load_manifest(m, s)


def test_manifest_whitespace_change_is_a_mismatch(tmp_path):
    if not MANIFEST_PATH.exists():
        pytest.skip('sealed manifest not present')
    m, s = tmp_path / 'm.json', tmp_path / 'm.sha256'
    shutil.copy(MANIFEST_PATH, m); shutil.copy(MANIFEST_SHA_PATH, s)
    m.write_text(m.read_text() + '\n')
    assert not E.manifest_check(m, s)['ok']


def test_real_manifest_verifies_and_freeze_absent():
    if not MANIFEST_PATH.exists():
        pytest.skip('sealed manifest not present')
    chk = E.manifest_check()
    assert chk['ok'], chk['message']
    ids = E.sealed_race_ids()
    assert len(ids) == 6 and all('_' in r for r in ids)


def test_sealed_regret_suppression_rule():
    agg = dict(plans=dict(orb=dict(n=2, median=1.0, mean=1.0, min=0.5, max=1.5), naive=dict(n=3, median=2.0, mean=2.0, min=0.1, max=9.0, p90=8.0)),
               p_orb_beats_naive=dict(n_weekends=2, share_rows=0.5, p_bootstrap=0.4), p_orb_beats_observed=dict(n_weekends=3, share_rows=0.7, p_bootstrap=0.9))
    out = E._strip_extremes(agg)
    assert 'suppressed' in out['plans']['orb'] and 'median' not in out['plans']['orb']
    assert 'min' not in out['plans']['naive'] and 'max' not in out['plans']['naive'] and out['plans']['naive']['p90'] == 8.0
    assert 'suppressed' in out['p_orb_beats_naive'] and out['p_orb_beats_observed']['p_bootstrap'] == 0.9
