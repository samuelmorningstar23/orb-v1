"""Strategy regret: zero for the oracle plan, non-negative inside the search space, label rule."""
from __future__ import annotations

import numpy as np
import pytest

from evaluation.forecast import SeasonForecaster
from evaluation.regret import oracle_plan, plan_cost, top_plan, weekend_regret, aggregate, LABEL, PIT_LOSS
from counterfactual.racedata import load_race
from synth_eval import SLOPES, OFFSETS


def test_oracle_plan_has_zero_regret_and_is_optimal():
    n = 50
    o = oracle_plan(OFFSETS, SLOPES, n)
    assert o is not None and sum(o['stints']) == n
    assert abs(plan_cost(o['seq'], o['stints'], OFFSETS, SLOPES) - o['cost']) < 1e-9
    # every one- and two-stop plan on the grid costs at least the oracle
    rng = np.random.default_rng(1)
    for _ in range(200):
        k = int(rng.integers(2, 4)); seq = list(rng.choice(list(SLOPES), size=k))
        if len(set(seq)) < 2:
            continue
        cuts = sorted(rng.choice(np.arange(6, n - 6), size=k - 1, replace=False))
        stints = np.diff([0, *cuts, n]).tolist()
        if min(stints) < 6:
            continue
        assert plan_cost(seq, stints, OFFSETS, SLOPES) - o['cost'] >= -1e-9
    # the production optimiser (strategy2.best_plans, step-2 grid for two stops) is never better than the oracle
    t = top_plan(OFFSETS, SLOPES, n)
    assert plan_cost(t['seq'], t['stints'], OFFSETS, SLOPES) - o['cost'] >= -1e-9


def test_weekend_regret_zero_when_forecast_equals_reference(synthetic_season):
    season, d, events = synthetic_season['season'], synthetic_season['dir'], synthetic_season['events']
    F = SeasonForecaster(d, season)
    fc = F.loo_forecasts()[events[1]]
    ref = F.reference(events[1])
    race = load_race(events[1], str(F.race_path(events[1])))
    r = weekend_regret(fc, ref, race)
    assert r['label'] == LABEL and r['oracle'] is not None
    assert all(abs(fc.slopes()[c] - ref[c]['obs']) < 1e-6 for c in ref)
    # forecast == reference: the recommended plan is the oracle up to the optimiser's grid; the oracle itself scores 0
    assert 0.0 <= r['regret_orb'] < 1.0
    o = r['oracle']
    assert abs(plan_cost(o['seq'], o['stints'], r['offsets'], {c: v for c, v in r['reference_slopes'].items()}) - o['cost']) < 1e-9
    for name in ('observed', 'default'):
        assert r[f'regret_{name}'] is None or r[f'regret_{name}'] >= -1e-9 or r['plans'][name]['stops'] > 2
    agg = aggregate([r], bootstrap=False)
    assert agg['label'] == LABEL and agg['plans']['orb']['n'] == 1
    assert 'observed race time saved' not in LABEL.lower()
