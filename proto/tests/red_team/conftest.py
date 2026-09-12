"""Red-team acceptance suite (roadmap v5 task 0.0). Run from proto/:

    ../.venv/bin/python -m pytest tests/red_team -q

The suite is the automated form of the Phase 0 acceptance tests: import boundaries, data cutoff on the live path,
identity and conservation of the counterfactual core, one forecast hash across modes, replay-cannot-see-lap-k+1.
Every test carries an in-suite self-test that plants a deliberate violation (in a temp dir, a proxy or a monkeypatch,
never in another workstream's files) and asserts the check fails loudly. Budget: the whole directory runs in well under 20 s.

No __init__.py here on purpose (a `tests.red_team` package would shadow proto/evaluation/red_team on sys.path)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from rt_helpers import PROTO, EVENT, DRIVER, LAP  # noqa: E402,F401  (also puts proto/ on sys.path)


@pytest.fixture(scope='session')
def proto() -> Path:
    return PROTO


@pytest.fixture(scope='session')
def lock_v1_path() -> Path:
    p = PROTO / 'out' / 'lock.json'
    if not p.exists():
        pytest.skip('out/lock.json not present')
    return p


@pytest.fixture(scope='session')
def lock_v2_path() -> Path:
    p = PROTO / 'out' / 'lock_v2.json'
    if not p.exists():
        pytest.skip('out/lock_v2.json not present')
    return p


@pytest.fixture(scope='session')
def lock_v2(lock_v2_path) -> dict:
    return json.loads(lock_v2_path.read_text(encoding='utf-8'))


@pytest.fixture(scope='session')
def race_csv() -> Path:
    p = PROTO / 'feat' / f'{EVENT}_R.csv'
    if not p.exists():
        pytest.skip(f'feat/{EVENT}_R.csv not present (feat/ is gitignored)')
    return p


@pytest.fixture(scope='session')
def lock_view(lock_v1_path, lock_v2_path):
    from app_v2.services import lock_repository as LR
    lk = LR.load_lock()
    if lk is None:
        pytest.skip('LockView could not load the lock')
    return lk


@pytest.fixture
def fresh_live_cache():
    """The live view model caches a stepped session per (event, driver): clear it so a spy sees every feed call."""
    from live import viewmodel as LV
    LV._cache.clear()
    yield
    LV._cache.clear()
