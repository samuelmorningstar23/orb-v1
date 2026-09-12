"""Compressed float32 .npz and JSON assets with sha256 sidecars.

Sidecar convention (shared with app_v2/services/asset_repository.resolve): `<file>.sha256` next to the file, first token the
hex digest, second the file name (`sha256sum` format). JSON is written atomically through shared.lockio.
Unicode 0-d arrays carry small JSON documents inside an .npz (np.load works with allow_pickle=False).
"""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np

PROTO_ROOT = Path(__file__).resolve().parents[1]
if str(PROTO_ROOT) not in sys.path:               # `replay` is imported both as a package from proto/ and from tests
    sys.path.insert(0, str(PROTO_ROOT))
from shared.lockio import atomic_write_bytes, atomic_write_json, sha256_file, sha256_bytes  # noqa: E402

MAPS_DIR = PROTO_ROOT / 'out' / 'maps'


def sidecar_path(path: str | os.PathLike) -> Path:
    p = Path(path)
    return p.with_name(p.name + '.sha256')


def write_sidecar(path: str | os.PathLike) -> str:
    p = Path(path)
    digest = sha256_file(p)
    atomic_write_bytes(sidecar_path(p), f'{digest}  {p.name}\n'.encode('utf-8'))
    return digest


def verify(path: str | os.PathLike) -> tuple[str, str]:
    """('verified' | 'unsigned' | 'mismatch' | 'missing', message)."""
    p = Path(path)
    if not p.exists():
        return 'missing', f'{p} not found'
    sc = sidecar_path(p)
    if not sc.exists():
        return 'unsigned', f'{p.name}: no sidecar'
    expected = sc.read_text().split()[0].lower()
    actual = sha256_file(p)
    return ('verified', f'{p.name}: sha256 verified') if expected == actual else ('mismatch', f'{p.name}: sha256 {actual[:12]} != sidecar {expected[:12]}')


def _as_saveable(v: Any) -> np.ndarray:
    if isinstance(v, (dict, list, str)):
        return np.array(json.dumps(v, allow_nan=False) if not isinstance(v, str) else v)
    a = np.asarray(v)
    if a.dtype == np.float64:
        a = a.astype(np.float32)
    return a


def save_npz(path: str | os.PathLike, **arrays: Any) -> str:
    """np.savez_compressed with float64 -> float32, dict/list -> JSON string, atomic write, sidecar. Returns the digest."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    np.savez_compressed(buf, **{k: _as_saveable(v) for k, v in arrays.items()})
    data = buf.getvalue()
    atomic_write_bytes(p, data)
    digest = sha256_bytes(data)
    atomic_write_bytes(sidecar_path(p), f'{digest}  {p.name}\n'.encode('utf-8'))
    return digest


def load_npz(path: str | os.PathLike, verify_hash: bool = True) -> dict[str, Any]:
    """Arrays as numpy (0-d unicode arrays decoded to JSON objects when they parse as JSON, else str)."""
    p = Path(path)
    if verify_hash:
        status, msg = verify(p)
        if status == 'mismatch':
            raise ValueError(msg)
    out: dict[str, Any] = {}
    with np.load(p, allow_pickle=False) as z:
        for k in z.files:
            a = z[k]
            if a.dtype.kind == 'U' and a.ndim == 0:
                s = str(a)
                try:
                    out[k] = json.loads(s)
                except ValueError:
                    out[k] = s
            else:
                out[k] = a
    return out


def save_json(path: str | os.PathLike, obj: Any) -> str:
    atomic_write_json(path, obj, indent=1)
    return write_sidecar(path)


def load_json(path: str | os.PathLike, verify_hash: bool = True) -> Any:
    p = Path(path)
    if verify_hash:
        status, msg = verify(p)
        if status == 'mismatch':
            raise ValueError(msg)
    with open(p, 'r', encoding='utf-8') as f:
        return json.load(f)


def event_dir(event: str, root: str | os.PathLike | None = None) -> Path:
    return Path(root) / event if root else MAPS_DIR / event


__all__ = ['MAPS_DIR', 'PROTO_ROOT', 'sidecar_path', 'write_sidecar', 'verify', 'save_npz', 'load_npz', 'save_json', 'load_json', 'event_dir']
