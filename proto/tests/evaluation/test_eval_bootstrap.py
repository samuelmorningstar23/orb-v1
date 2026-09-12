"""The bootstrap resamples whole weekends, never rows."""
from __future__ import annotations

import numpy as np
import pandas as pd

from evaluation.common import weekend_bootstrap, paired_probability


def test_bootstrap_is_grouped_by_weekend():
    # two weekends: A has 30 rows all equal to 1, B has 30 rows all equal to 0. Resampling weekends gives means in {0, 0.5, 1}
    # only; resampling rows would give a continuum around 0.5.
    df = pd.DataFrame(dict(race_id=['A'] * 30 + ['B'] * 30, v=[1.0] * 30 + [0.0] * 30))
    b = weekend_bootstrap(df, lambda d: float(d['v'].mean()), n=400, seed=3)
    assert b['estimate'] == 0.5 and b['n_weekends'] == 2 and b['n_rows'] == 60
    assert b['ci90'] == [0.0, 1.0]
    # replicate the draw to inspect every resample value
    rng = np.random.default_rng(3)
    vals = set()
    for _ in range(400):
        draw = rng.choice(['A', 'B'], size=2, replace=True)
        vals.add(float(pd.concat([df[df.race_id == w] for w in draw])['v'].mean()))
    assert vals <= {0.0, 0.5, 1.0} and {0.0, 1.0} <= vals


def test_bootstrap_weights_weekends_by_their_rows():
    # a weekend drawn twice contributes its rows twice: with unequal sizes the resample mean is a rows-weighted mean
    df = pd.DataFrame(dict(race_id=['A'] * 10 + ['B'] * 30, v=[1.0] * 10 + [0.0] * 30))
    b = weekend_bootstrap(df, lambda d: float(d['v'].mean()), n=300, seed=5)
    assert b['estimate'] == 0.25 and b['ci90'][0] >= 0.0 and b['ci90'][1] <= 1.0


def test_single_weekend_has_no_interval():
    df = pd.DataFrame(dict(race_id=['A'] * 5, v=[1, 2, 3, 4, 5.0]))
    b = weekend_bootstrap(df, lambda d: float(d['v'].mean()))
    assert b['estimate'] == 3.0 and b['ci90'] is None


def test_paired_probability_groups_by_weekend():
    df = pd.DataFrame(dict(race_id=['A'] * 4 + ['B'] * 4, a=[1, 1, 1, 1, 3, 3, 3, 3.0], b=[2, 2, 2, 2, 2, 2, 2, 2.0]))
    p = paired_probability(df, 'a', 'b', n=500, seed=1)
    assert p['n_weekends'] == 2 and p['share_rows'] == 0.5
    assert 0.2 < p['p_bootstrap'] < 0.8                          # draws AA (a<b), BB (a>b), AB (tie) -> 0.25 + 0.5 x 0.5 = 0.5
