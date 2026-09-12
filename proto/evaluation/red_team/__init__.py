"""Orb v1 red team. Owns only proto/evaluation/red_team/ and proto/tests/red_team/.

    consistency_probe.py   every number the dashboard renders equals the lock or a hashed sidecar (exit 0/1/2)
    leakage_audit.py       import boundaries (static), future-read and deny-list spies, target-driver exclusion,
                           one forecast hash across modes (exit 0 / 1)
    identity_checks.py     independent re-run of the counterfactual identity, same-compound, zero-degradation and
                           time-accounting tests, pit-loss pool recomputation, batch-equals-replay (exit 0 / 1)
    claim_audit.py         forbidden or under-qualified wording and every deck number against the lock (exit 0 / 1)
    build_report.py        consolidates the four into red_team_report.json / .md and blocking_issues.json

Nothing here writes outside evaluation/red_team/ (reports) and the temp directory (tests).
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))
RT_DIR = PROTO / 'evaluation' / 'red_team'
LOCK_V1 = PROTO / 'out' / 'lock.json'
LOCK_V2 = PROTO / 'out' / 'lock_v2.json'

OWNER_BY_PATH = [   # release/README.md ownership map (lead decisions 12 Sep 14:55)
    ('schemas/', 'workstream 1'), ('fixtures/', 'workstream 1'), ('validators/', 'workstream 1'), ('shared/', 'workstream 1'), ('tests/contract/', 'workstream 1'),
    ('out/lock_v2.json', 'workstream 1'), ('out/lock_v2_sidecars/', 'workstream 1'),
    ('counterfactual/', 'workstream 2'), ('events/', 'workstream 2'), ('out/counterfactual/', 'workstream 2'),
    ('evaluation/red_team/', 'workstream 7'), ('evaluation/', 'workstream 3'), ('out/validation/', 'workstream 3'),
    ('replay/', 'workstream 4'), ('dashboard/components/', 'workstream 4'), ('out/maps/', 'workstream 4'), ('app_v2/components/race_twin/', 'workstream 4'),
    ('interaction/', 'workstream 5'),
    ('app_v2/', 'workstream 6'), ('ui/', 'workstream 6'), ('theme/', 'workstream 6'), ('views/', 'workstream 6'), ('tests/ui/', 'workstream 6'), ('tests/screenshots/', 'workstream 6'),
    ('live/', 'workstream 8'), ('decision/', 'workstream 8'), ('out/live/', 'workstream 8'),
    ('progress/', 'workstream 9'), ('checkpoints/', 'workstream 9'), ('release/', 'workstream 9'), ('tests/release/', 'workstream 9'), ('build_control.py', 'workstream 9'),
]


def owner_of(path: str) -> str:
    p = str(path).replace('\\', '/')
    for prefix, owner in OWNER_BY_PATH:
        if p.startswith(prefix):
            return owner
    return 'lead'


def now_iso() -> str:
    return datetime.now().isoformat(timespec='seconds')


def read_json(path: Path | str) -> Any:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path: Path | str, obj: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from shared.lockio import atomic_write_json
        return atomic_write_json(path, _clean(obj))
    except Exception:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(_clean(obj), f, indent=1, ensure_ascii=False)
            f.write('\n')
        return path


def _clean(obj: Any) -> Any:
    """JSON-safe: numpy scalars -> python, NaN / inf -> None, Paths -> str, sets -> sorted lists."""
    if hasattr(obj, 'item') and not isinstance(obj, (str, bytes)):
        try:
            obj = obj.item()
        except Exception:
            pass
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return sorted(_clean(v) for v in obj)
    if isinstance(obj, Path):
        return obj.as_posix()
    return obj


def numeric_leaves(obj: Any, path: str = '$') -> Iterator[tuple[str, float]]:
    """(json path, value) for every int / float leaf (bools excluded, NaN skipped)."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        if isinstance(obj, float) and not math.isfinite(obj):
            return
        yield path, float(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from numeric_leaves(v, f'{path}.{k}')
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from numeric_leaves(v, f'{path}[{i}]')


NUM_RE = re.compile(r'(?<![\w.])[-+−]?\d+(?:\.\d+)?(?![\w.])')
TIMESTAMP_RE = re.compile(r'\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?|\b\d{1,2}:\d{2}(?::\d{2})?\b')
HEX_RE = re.compile(r'\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{6,64}\b')


def find_numbers(text: str) -> list[tuple[float, int, str, int]]:
    """(value, decimals, context window after the number, position) for every number token in `text`.
    Timestamps and hex hashes are blanked first so their digits never count."""
    t = TIMESTAMP_RE.sub(' ', text)
    t = HEX_RE.sub(' ', t)
    out = []
    for m in NUM_RE.finditer(t):
        tok = m.group(0).replace('−', '-')
        dec = len(tok.split('.')[1]) if '.' in tok else 0
        try:
            v = float(tok)
        except ValueError:
            continue
        out.append((v, dec, t[m.end():m.end() + 14], m.start()))
    return out


__all__ = ['PROTO', 'RT_DIR', 'LOCK_V1', 'LOCK_V2', 'owner_of', 'now_iso', 'read_json', 'write_json', 'numeric_leaves', 'find_numbers']
