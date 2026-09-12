"""Blind-evaluation tests. Run from the repo root: pytest proto/tests/evaluation -q

No __init__.py here on purpose: a `tests.evaluation` package would shadow proto/evaluation on sys.path."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from synth_eval import make_season, SLOPES, OFFSETS  # noqa: E402


@pytest.fixture(scope='session')
def synthetic_season(tmp_path_factory):
    """Five noise-free synthetic weekends (W1..W5): practice and race share the true slopes, so k = 1 exactly."""
    d = tmp_path_factory.mktemp('feat_synth')
    events = [f'W{i}' for i in range(1, 6)]
    make_season(d, events, noise=0.0)
    return dict(dir=d, events=events, season=2099)


@pytest.fixture(scope='session')
def noisy_season(tmp_path_factory):
    d = tmp_path_factory.mktemp('feat_noisy')
    events = [f'N{i}' for i in range(1, 6)]
    make_season(d, events, noise=0.05, seed=7)
    return dict(dir=d, events=events, season=2098)


@pytest.fixture(scope='session')
def real_data_available():
    return (PROTO / 'feat' / 'Monza_R.csv').exists() and (PROTO / 'out' / 'lock.json').exists()
