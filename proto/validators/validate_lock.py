"""Validate an Orb v1 lock v2 file: schema (pydantic models), cross-block hash agreement, and every sidecar sha256 that exists.

Usage: python validators/validate_lock.py <lock.json> [--root DIR] [--strict] [--max-kb N] [--quiet]

  --root    directory that sidecar paths are relative to (default: proto/, the lock root)
  --strict  a missing sidecar file or an oversized lock is a failure instead of a warning
  --max-kb  warn (or fail with --strict) when the lock itself is larger than this (default 1024): large arrays belong in sidecars

Exit codes: 0 valid; 1 file or JSON error; 2 schema violation; 3 sidecar hash mismatch (or missing / oversized under --strict).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

PROTO = Path(__file__).resolve().parents[1]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from pydantic import ValidationError  # noqa: E402

from schemas.lock_v2 import LockV2, format_errors  # noqa: E402
from shared.lockio import iter_sidecar_refs, verify_sidecar  # noqa: E402

EXIT_OK, EXIT_FILE, EXIT_SCHEMA, EXIT_HASH = 0, 1, 2, 3


def validate(path: Path, root: Path, strict: bool = False, max_kb: int = 1024, quiet: bool = False) -> int:
    say = (lambda *_: None) if quiet else print
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f'FAIL {path}: file not found', file=sys.stderr)
        return EXIT_FILE
    except (OSError, json.JSONDecodeError) as e:
        print(f'FAIL {path}: cannot read as JSON: {e}', file=sys.stderr)
        return EXIT_FILE
    if isinstance(data, dict) and any(isinstance(data.get(k), list) for k in ('validation_rows',)) and 'shared' not in data:
        print(f'FAIL {path}: this looks like a v1 lock (keys {sorted(data)[:6]}...); run validators/adapt_v1.py first', file=sys.stderr)
        return EXIT_SCHEMA
    try:
        lock = LockV2.model_validate(data)
    except ValidationError as e:
        print(f'FAIL {path}: {e.error_count()} schema violation(s)\n{format_errors(e)}', file=sys.stderr)
        return EXIT_SCHEMA

    rc = EXIT_OK
    size_kb = path.stat().st_size / 1024
    if size_kb > max_kb:
        print(f'{"FAIL" if strict else "WARN"} {path}: lock is {size_kb:.0f} kB (> {max_kb} kB); move large arrays to sidecars', file=sys.stderr)
        if strict:
            rc = EXIT_HASH
    refs = list(iter_sidecar_refs(lock.model_dump(mode='json', by_alias=True)))
    counts = {'ok': 0, 'missing': 0, 'mismatch': 0}
    for json_path, ref in refs:
        status, msg = verify_sidecar(ref, root)
        counts[status] += 1
        if status == 'mismatch':
            print(f'FAIL sidecar {json_path}: {msg}', file=sys.stderr)
            rc = EXIT_HASH
        elif status == 'missing':
            print(f'{"FAIL" if strict else "WARN"} sidecar {json_path}: {msg}', file=sys.stderr)
            if strict:
                rc = EXIT_HASH
        else:
            say(f'  ok sidecar {json_path}: {msg}')
    blocks = sorted(lock.blocks()) + (['counterfactuals'] if lock.counterfactuals else [])
    verdict = 'OK' if rc == EXIT_OK else 'FAIL'
    say(f'{verdict} {path}: schema {lock.schema_version}, forecast {lock.shared.forecast_hash[:23]}..., blocks {blocks}, '
        f'sidecars {counts["ok"]} verified / {counts["missing"]} missing / {counts["mismatch"]} mismatched, {size_kb:.0f} kB')
    return rc


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('lock', help='path to a lock v2 JSON file')
    ap.add_argument('--root', default=str(PROTO), help='lock root for sidecar paths (default: proto/)')
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--max-kb', type=int, default=1024)
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    return validate(Path(a.lock), Path(a.root), strict=a.strict, max_kb=a.max_kb, quiet=a.quiet)


if __name__ == '__main__':
    sys.exit(main())
