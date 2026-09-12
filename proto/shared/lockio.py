"""Lock I/O primitives for the Orb v1 lock v2 (roadmap v5 task 0.2).

    atomic_write_json(path, obj)   temp file in the same directory + fsync + os.replace: a reader never sees a partial lock
    canonical_json(obj)            sorted keys, no whitespace, no NaN/Infinity: the same content always gives the same bytes
    content_hash(obj)              'sha256:' + sha256(canonical_json(obj))
    forecast_hash(block)           content_hash of a pre_race_forecast block with its volatile top-level 'meta' removed
    sha256_file(path)              hex digest of a sidecar file
    sidecar_ref(path, root)        {'path': <posix path relative to root>, 'sha256': ..., 'bytes': ...}
    verify_sidecar(ref, root)      ('ok' | 'missing' | 'mismatch', message)

Sidecar paths are POSIX and relative to the lock root (proto/); absolute paths and '..' segments are rejected so a lock
stays portable between machines. Nothing here imports the schema module (schemas.lock_v2 imports this module).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

HASH_PREFIX = 'sha256:'
VOLATILE_KEYS = ('meta',)   # per-block provenance that must not change a content hash

# ---------------------------------------------------------------- JSON canonicalisation and hashing

def _jsonable(obj: Any) -> Any:
    """pydantic models -> JSON-mode dicts (by alias); numpy scalars -> python; everything else unchanged."""
    if hasattr(obj, 'model_dump'):
        return obj.model_dump(mode='json', by_alias=True)
    return obj


def _default(o: Any) -> Any:
    """json.dumps fallback for numpy scalars and Paths; NaN/inf are rejected by allow_nan=False, not silently written."""
    if hasattr(o, 'item'):             # numpy scalar
        return o.item()
    if isinstance(o, (Path, PurePosixPath)):
        return o.as_posix()
    if hasattr(o, 'model_dump'):
        return o.model_dump(mode='json', by_alias=True)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    raise TypeError(f'{type(o).__name__} is not JSON serialisable')


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, compact separators, UTF-8 characters kept, NaN and Infinity refused."""
    return json.dumps(_jsonable(obj), sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False, default=_default)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode('utf-8'))


def sha256_file(path: str | os.PathLike, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()


def content_hash(obj: Any) -> str:
    """'sha256:' + sha256 of the canonical JSON of obj (key order and whitespace do not matter)."""
    return HASH_PREFIX + sha256_text(canonical_json(obj))


def forecast_hash(block: Any) -> str:
    """Hash of a pre_race_forecast block with its top-level 'meta' (generated_at, git_sha, provenance...) removed,
    so regenerating the same forecast at a later time or commit reproduces the same hash. Hash the *validated* block
    (schemas.lock_v2.compute_forecast_hash) when producing a lock, so defaults are materialised identically."""
    d = _jsonable(block)
    if isinstance(d, dict):
        d = {k: v for k, v in d.items() if k not in VOLATILE_KEYS}
    return content_hash(d)


def strip_nonfinite(obj: Any) -> Any:
    """Recursively replace NaN / +-inf floats by None and numpy scalars by python scalars (v1 lock.json can carry NaN)."""
    if hasattr(obj, 'item') and not isinstance(obj, (str, bytes)):
        obj = obj.item()
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: strip_nonfinite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [strip_nonfinite(v) for v in obj]
    return obj

# ---------------------------------------------------------------- atomic writes

def atomic_write_bytes(path: str | os.PathLike, data: bytes) -> Path:
    """Write data to a temp file next to `path`, fsync, then os.replace it into place. On any failure the temp file
    is removed and the previous file (if any) is left untouched."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        mask = os.umask(0)                      # mkstemp creates 0600; give the lock the caller's normal file mode
        os.umask(mask)
        os.chmod(tmp, 0o666 & ~mask)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return path


def atomic_write_text(path: str | os.PathLike, text: str, encoding: str = 'utf-8') -> Path:
    return atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(path: str | os.PathLike, obj: Any, indent: int | None = 1, sort_keys: bool = False) -> Path:
    """Serialise first (a non-serialisable object or a NaN fails before any file is touched), then write atomically."""
    text = json.dumps(_jsonable(obj), indent=indent, sort_keys=sort_keys, ensure_ascii=False, allow_nan=False, default=_default) + '\n'
    return atomic_write_text(path, text)


def read_json(path: str | os.PathLike) -> Any:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

# ---------------------------------------------------------------- sidecars

def check_relative_posix(path: str) -> str:
    """A sidecar path must be POSIX, relative, without '..' segments or backslashes. Returns the path unchanged."""
    if not isinstance(path, str) or not path:
        raise ValueError('sidecar path must be a non-empty string')
    if '\\' in path:
        raise ValueError(f'sidecar path must use POSIX separators: {path!r}')
    if path.startswith('/') or (len(path) > 1 and path[1] == ':'):
        raise ValueError(f'sidecar path must be relative to the lock root: {path!r}')
    if any(seg in ('..', '.', '') for seg in path.split('/')):      # raw segments: pathlib would silently drop './' and '//'
        raise ValueError(f"sidecar path must be canonical: no '.', '..' or empty segments: {path!r}")
    return path


def resolve_sidecar(ref_path: str, root: str | os.PathLike) -> Path:
    return Path(root) / PurePosixPath(check_relative_posix(ref_path))


def sidecar_ref(path: str | os.PathLike, root: str | os.PathLike, **extra: Any) -> dict[str, Any]:
    """Reference {path, sha256, bytes} for an existing file, path expressed relative to root (POSIX)."""
    abs_path = Path(path).resolve()
    rel = abs_path.relative_to(Path(root).resolve()).as_posix()
    check_relative_posix(rel)
    ref = {'path': rel, 'sha256': sha256_file(abs_path), 'bytes': abs_path.stat().st_size}
    ref.update(extra)
    return ref


def write_sidecar_json(obj: Any, path: str | os.PathLike, root: str | os.PathLike, **extra: Any) -> dict[str, Any]:
    """Atomically write a JSON sidecar and return its reference (format='json' unless overridden)."""
    atomic_write_json(path, obj)
    extra.setdefault('format', 'json')
    return sidecar_ref(path, root, **extra)


def verify_sidecar(ref: dict[str, Any], root: str | os.PathLike) -> tuple[str, str]:
    """('ok' | 'missing' | 'mismatch', human-readable message) for one {path, sha256} reference."""
    try:
        target = resolve_sidecar(ref['path'], root)
    except (KeyError, ValueError) as e:
        return 'mismatch', f'invalid sidecar reference {ref!r}: {e}'
    if not target.exists():
        return 'missing', f'{ref["path"]}: not found under {Path(root)}'
    expected = str(ref.get('sha256', '')).removeprefix(HASH_PREFIX).lower()
    actual = sha256_file(target)
    if actual != expected:
        return 'mismatch', f'{ref["path"]}: sha256 {actual[:16]}... does not match recorded {expected[:16]}...'
    return 'ok', f'{ref["path"]}: sha256 verified'


def iter_sidecar_refs(obj: Any, path: str = '$') -> Iterable[tuple[str, dict[str, Any]]]:
    """Yield (json_path, ref) for every {path, sha256} dict anywhere inside a (plain, JSON-like) structure."""
    if hasattr(obj, 'model_dump'):
        obj = obj.model_dump(mode='json', by_alias=True)
    if isinstance(obj, dict):
        if isinstance(obj.get('path'), str) and isinstance(obj.get('sha256'), str):
            yield path, obj
            return
        for k, v in obj.items():
            yield from iter_sidecar_refs(v, f'{path}.{k}')
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_sidecar_refs(v, f'{path}[{i}]')


__all__ = ['HASH_PREFIX', 'VOLATILE_KEYS', 'canonical_json', 'content_hash', 'forecast_hash', 'sha256_bytes', 'sha256_text', 'sha256_file',
           'strip_nonfinite', 'atomic_write_bytes', 'atomic_write_text', 'atomic_write_json', 'read_json', 'check_relative_posix',
           'resolve_sidecar', 'sidecar_ref', 'write_sidecar_json', 'verify_sidecar', 'iter_sidecar_refs']
