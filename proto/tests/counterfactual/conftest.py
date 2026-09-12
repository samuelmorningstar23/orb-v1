"""Tests for the counterfactual core and the event sources. Run: pytest proto/tests/counterfactual -q"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

EVENT = 'Monza'


@pytest.fixture(scope='session')
def proto_dir() -> Path:
    return PROTO


@pytest.fixture(scope='session')
def monza_csv() -> Path:
    p = PROTO / 'feat' / f'{EVENT}_R.csv'
    if not p.exists():
        pytest.skip('feat/Monza_R.csv not present')
    return p


@pytest.fixture(scope='session')
def v1_lock() -> dict:
    p = PROTO / 'out' / 'lock.json'
    if not p.exists():
        pytest.skip('out/lock.json not present')
    return json.loads(p.read_text(encoding='utf-8'))


@pytest.fixture(scope='session')
def v2_lock() -> dict:
    p = PROTO / 'out' / 'lock_v2.json'
    if not p.exists():
        pytest.skip('out/lock_v2.json not present')
    return json.loads(p.read_text(encoding='utf-8'))


@pytest.fixture(scope='session')
def provider(v1_lock, v2_lock):
    from counterfactual.provider import ProviderA
    return ProviderA()


@pytest.fixture(scope='session')
def engine(monza_csv, v1_lock, v2_lock):
    from counterfactual.engine import CounterfactualEngine
    return CounterfactualEngine()


@pytest.fixture(scope='session')
def race(engine):
    return engine.race(EVENT)
