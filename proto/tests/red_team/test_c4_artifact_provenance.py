"""C4 artifact provenance (roadmap v5 task 0.13 / stop-the-line conditions 14.3).

Two acceptance conditions that the C4 re-run checks by hand but no test pinned:

1. Every hashed artifact on disk points at the CURRENT lock's forecast hash. At 21:42 the leakage audit's
   `one_forecast_hash` check failed because `out/live/*/summary.json` still carried the pre-qualifying hash
   e126...; the records were regenerated at 21:49. The audit walks a fixed list of paths, so a sidecar in a
   directory it does not enumerate (the Scenario Explorer's `out/counterfactual/pre_race/*`, added 21:39-21:52)
   could go stale unnoticed. This test walks the trees instead of a list.

2. The sealed holdout manifest still matches its recorded `.sha256`. `tests/evaluation` and `tests/release`
   prove the tamper-detection mechanism works, but only inside `tmp_path`; nothing asserted that the real
   `evaluation/holdout/sealed_holdout_manifest.json` is unaltered, which is a 14.3 stop-the-line condition.

Both checks carry the suite's self-test convention: a deliberate violation is planted in a temp copy and the
scanner must flag it. Neither test writes into another workstream's files."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from rt_helpers import PROTO

HASHED_TREES = ('out/live', 'out/counterfactual')
MANIFEST = PROTO / 'evaluation' / 'holdout' / 'sealed_holdout_manifest.json'
MANIFEST_SHA = PROTO / 'evaluation' / 'holdout' / 'sealed_holdout_manifest.sha256'
REGEN = {
    'out/live': 'Workstream 8: ../.venv/bin/python -m live.run (regenerate out/live/* after every lock rebuild)',
    'out/counterfactual': 'Workstream 2: ../.venv/bin/python -m counterfactual.run ... (regenerate each scenario after every lock rebuild)',
}


def _forecast_hash_fields(obj, path: str = '$'):
    """Yield (json path, value) for every key whose name ends in `forecast_hash`, at any depth."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.endswith('forecast_hash') and isinstance(v, str):
                yield f'{path}.{k}', v
            yield from _forecast_hash_fields(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _forecast_hash_fields(v, f'{path}[{i}]')


def _scan_for_stale_hashes(root: Path, trees, want: str) -> tuple[list[str], int]:
    """Return (stale descriptions, number of forecast_hash fields seen) over every JSON under `trees`."""
    stale, seen = [], 0
    for tree in trees:
        base = root / tree
        if not base.exists():
            continue
        for p in sorted(base.rglob('*.json')):
            try:
                obj = json.loads(p.read_text(encoding='utf-8'))
            except (OSError, ValueError) as e:
                stale.append(f'{p.relative_to(root)}: unreadable ({type(e).__name__})')
                continue
            for jpath, val in _forecast_hash_fields(obj):
                seen += 1
                if val.replace('sha256:', '') != want:
                    stale.append(f'{p.relative_to(root)} {jpath} = {val.replace("sha256:", "")[:8]} (lock is {want[:8]}) -> {REGEN.get(tree, tree)}')
    return stale, seen


def test_every_on_disk_sidecar_carries_the_lock_forecast_hash(lock_v2):
    want = lock_v2['shared']['forecast_hash'].replace('sha256:', '')
    stale, seen = _scan_for_stale_hashes(PROTO, HASHED_TREES, want)
    assert seen > 0, f'no forecast_hash field found under {HASHED_TREES}: the scan is vacuous, check the paths'
    assert not stale, (
        f'{len(stale)} of {seen} hashed fields point at a superseded forecast. These are provenance pointers: the numbers may '
        f'still reproduce, but a jury checking the hash sees a mismatch. Report to the owning workstream, do not hand-edit:\n  ' + '\n  '.join(stale))


def test_stale_hash_scan_flags_a_planted_pointer(tmp_path, lock_v2):
    """Self-test: the scan must fail loudly on a sidecar that points at an earlier forecast."""
    want = lock_v2['shared']['forecast_hash'].replace('sha256:', '')
    d = tmp_path / 'out' / 'live' / 'Planted_XXX'
    d.mkdir(parents=True)
    (d / 'summary.json').write_text(json.dumps({'forecast_hash': 'sha256:' + 'e126' + '0' * 60}), encoding='utf-8')
    (d / 'live_predictor.json').write_text(json.dumps({'prior': {'forecast_hash': 'sha256:' + want}}), encoding='utf-8')
    stale, seen = _scan_for_stale_hashes(tmp_path, ('out/live',), want)
    assert seen == 2 and len(stale) == 1, (seen, stale)
    assert 'Planted_XXX/summary.json' in stale[0] and 'e1260000' in stale[0], stale


def test_scan_reaches_the_pre_race_scenario_directory(lock_v2):
    """The Scenario Explorer's pre-race scenarios live one level deeper than the audit's enumerated paths."""
    pre = PROTO / 'out' / 'counterfactual' / 'pre_race'
    if not pre.exists():
        pytest.skip('out/counterfactual/pre_race not generated (Workstream 2 CLI, --curve-source pre_race_forecast)')
    found = {str(p.relative_to(PROTO)) for p in pre.rglob('*.json') if any(True for _ in _forecast_hash_fields(json.loads(p.read_text(encoding='utf-8'))))}
    assert found, f'{pre.relative_to(PROTO)} exists but no file under it records a forecast_hash: the pre-race scenarios would be unpinned'


def test_sealed_holdout_manifest_matches_its_recorded_hash():
    """Stop-the-line condition 14.3: the sealed holdout manifest must never be altered after the seal."""
    assert MANIFEST.exists() and MANIFEST_SHA.exists(), f'sealed manifest or its sidecar is missing ({MANIFEST.exists()}, {MANIFEST_SHA.exists()})'
    recorded = MANIFEST_SHA.read_text(encoding='utf-8').split()[0]
    actual = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    assert actual == recorded, (
        f'STOP THE LINE: evaluation/holdout/sealed_holdout_manifest.json hashes {actual[:16]} but its sidecar records {recorded[:16]}. '
        'The sealed holdout is lead-only and frozen at C0; a changed manifest invalidates every holdout number. Do not re-seal to make this pass.')


def test_manifest_check_flags_an_altered_copy(tmp_path):
    """Self-test: the same comparison on a tampered copy must fail."""
    m, s = tmp_path / 'sealed_holdout_manifest.json', tmp_path / 'sealed_holdout_manifest.sha256'
    shutil.copy2(MANIFEST, m)
    s.write_text(hashlib.sha256(m.read_bytes()).hexdigest() + '  sealed_holdout_manifest.json\n', encoding='utf-8')
    assert hashlib.sha256(m.read_bytes()).hexdigest() == s.read_text().split()[0]
    d = json.loads(m.read_text(encoding='utf-8'))
    d['__planted__'] = 'one extra key'
    m.write_text(json.dumps(d), encoding='utf-8')
    assert hashlib.sha256(m.read_bytes()).hexdigest() != s.read_text().split()[0], 'the manifest comparison does not notice an added key'
