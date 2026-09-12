"""Contract tests for the Orb v1 lock v2. Run from the repo root: pytest proto/tests/contract -q"""
import json
import sys
from pathlib import Path

import pytest

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))


@pytest.fixture(scope='session')
def proto_dir() -> Path:
    return PROTO


@pytest.fixture(scope='session')
def fixture_path() -> Path:
    return PROTO / 'fixtures' / 'lock_v2_fixture.json'


@pytest.fixture
def fixture_lock(fixture_path) -> dict:
    """A fresh copy per test: tests mutate it to build invalid variants."""
    return json.loads(fixture_path.read_text(encoding='utf-8'))


@pytest.fixture(scope='session')
def v1_lock_path() -> Path:
    p = PROTO / 'out' / 'lock.json'
    if not p.exists():
        pytest.skip('v1 out/lock.json not present')
    return p
