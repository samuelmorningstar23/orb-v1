"""Live-slice tests. Run from the repo root: pytest proto/tests/live -q

No __init__.py here on purpose: a `tests.live` package would shadow proto/live on sys.path."""
import sys
from pathlib import Path

import pytest

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from live_helpers import mk_row, synthetic_priors  # noqa: E402


@pytest.fixture
def priors():
    return synthetic_priors()


@pytest.fixture
def clean_rows():
    """20 clean laps on MEDIUM, true slope 0.06, deterministic noise."""
    import numpy as np
    rng = np.random.default_rng(1)
    return [mk_row(k, k, 90.0 + 0.06 * k + 0.03 * 70 * (1 - (k - 1) / 50) + rng.normal(0, 0.2)) for k in range(1, 21)]


@pytest.fixture(scope='session')
def have_races():
    return all((PROTO / 'feat' / f'{ev}_R.csv').exists() for ev in ('Monza', 'Austria', 'Barcelona')) and (PROTO / 'out' / 'lock_v2.json').exists()
