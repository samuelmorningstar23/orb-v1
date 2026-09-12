"""Resolves sidecar / artifact paths and verifies sha256 digests.

Every number on a page must trace to the lock, a labelled fixture or a hashed asset; this module is the
'hashed asset' half of that rule. Digests are cached by (path, mtime, size) so a cold load stays cheap.
"""
from __future__ import annotations
import hashlib, json, os
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path
from typing import Optional
from app_v2.services import paths as P


@dataclass(frozen=True)
class Asset:
    path: str
    exists: bool
    sha256: Optional[str]
    size: int
    sidecar_status: str          # 'verified' | 'mismatch' | 'unsigned' | 'missing'

    @property
    def short_hash(self) -> str:
        return self.sha256[:6] if self.sha256 else '------'

    def as_dict(self) -> dict:
        return asdict(self)


@lru_cache(maxsize=256)
def _digest(path: str, mtime_ns: int, size: int) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sha256_of(path: Path | str) -> Optional[str]:
    p = Path(path)
    if not p.exists():
        return None
    st = p.stat()
    return _digest(str(p), st.st_mtime_ns, st.st_size)


def resolve(path: Path | str) -> Asset:
    """Describe an artifact and verify it against a `<file>.sha256` sidecar when one exists."""
    p = Path(path)
    if not p.exists():
        return Asset(str(p), False, None, 0, 'missing')
    digest = sha256_of(p)
    sidecar = p.with_suffix(p.suffix + '.sha256')
    status = 'unsigned'
    if sidecar.exists():
        expected = sidecar.read_text().strip().split()[0].lower()
        status = 'verified' if expected == digest else 'mismatch'
    return Asset(str(p), True, digest, p.stat().st_size, status)


def resolve_sidecar_by_hash(digest: str, directory: Path | str = P.OUT_DIR) -> Optional[Path]:
    """Lock v2 stores large arrays as sidecars named by hash: out/<prefix>/<hash>.json or out/<hash>.json."""
    digest = digest.replace('sha256:', '')
    for cand in (Path(directory) / f'{digest}.json', Path(directory) / 'sidecars' / f'{digest}.json'):
        if cand.exists():
            return cand
    return None


def load_json_asset(path: Path | str) -> tuple[Optional[dict], Asset]:
    a = resolve(path)
    if not a.exists:
        return None, a
    with open(a.path) as f:
        return json.load(f), a


def race_csv_asset(event: str) -> Asset:
    return resolve(P.race_csv(event))


def available_race_events() -> list[str]:
    return sorted(p.name[:-len('_R.csv')] for p in P.FEAT_DIR.glob('*_R.csv'))
