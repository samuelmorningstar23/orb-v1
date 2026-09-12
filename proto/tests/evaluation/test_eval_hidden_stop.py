"""Hidden-stop metrics on a synthetic race with known degradation recover the truth."""
from __future__ import annotations

import numpy as np
import pytest

from evaluation.forecast import SeasonForecaster
from evaluation.hidden_stop import stop_cases, aggregate, SIGMA_Y
from counterfactual.racedata import load_race
from synth_eval import SLOPES, OFFSETS


def _cases(season_fixture, ev_index=0):
    season, d, events = season_fixture['season'], season_fixture['dir'], season_fixture['events']
    F = SeasonForecaster(d, season)
    fc = F.loo_forecasts()[events[ev_index]]
    race = load_race(events[ev_index], str(F.race_path(events[ev_index])))
    return F, fc, stop_cases(race, fc, fc.race_id)


def test_noise_free_race_is_predicted_exactly(synthetic_season):
    F, fc, (cases, skipped) = _cases(synthetic_season)
    assert cases, skipped
    for c in fc.compounds.values():                              # the pre-race forecast is the truth (k = 1, offsets from Q)
        assert abs(c.prediction - SLOPES[c.compound]) < 1e-6 and c.factor_applied
    assert all(abs(fc.offsets[c] - OFFSETS[c]) < 1e-9 for c in OFFSETS)
    for case in cases:
        assert case['err1'] < 1e-6 and case['cov1'] is True
        assert case['err3'] is None or case['err3'] < 1e-6
        assert case['err5'] is None or case['err5'] < 1e-6
        assert abs(case['B_hat'] - {'AAA': 90.0, 'BBB': 90.3, 'CCC': 90.6, 'DDD': 90.9, 'EEE': 91.2, 'FFF': 91.5}[case['driver']]) < 1e-6
        assert case['err1_naive'] > 0.05                         # the naive fresh-tyre rule is wrong on a degrading tyre
    agg = aggregate(cases, bootstrap=False)
    assert agg['pooled']['next1_mae'] < 1e-6 and agg['pooled']['cum5_mae'] < 1e-6 and agg['pooled']['next1_coverage90'] == 1.0
    assert agg['pooled']['next1_mae_naive'] > agg['pooled']['next1_mae']
    assert set(agg['by']['compound_new']) <= {'SOFT', 'MEDIUM', 'HARD'} and 'green' in agg['by']['stop_regime']


def test_noisy_race_metrics_match_the_noise(noisy_season):
    F, fc, (cases, skipped) = _cases(noisy_season)
    assert len(cases) >= 4
    agg = aggregate(cases, bootstrap=False)['pooled']
    assert agg['next1_mae'] < 0.15                                # noise sd 0.05 in laps and in the baseline
    assert agg['next1_coverage90'] >= 0.9                         # the interval carries sigma_y = 0.40 >> noise
    assert agg['next1_mae'] < agg['next1_mae_naive']


def test_interval_width_formula(synthetic_season):
    F, fc, (cases, _) = _cases(synthetic_season)
    case = cases[0]
    K = case['n_pre']
    sd1 = np.sqrt(SIGMA_Y ** 2 + case['sd_level'] ** 2 + (case['ages_post'][0] * case['slope_new_sd']) ** 2)
    assert abs(case['sd1'] - sd1) < 1e-9
    assert case['sd_level'] >= SIGMA_Y / np.sqrt(K)
