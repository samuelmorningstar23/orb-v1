"""Provider A reproduces the v1 lock exactly; the post-race reference is fenced off."""
from __future__ import annotations

import numpy as np
import pytest

from counterfactual.provider import ProviderA, CurveUnavailable, assert_pre_race, event_name, MODEL_VERSION

TOL = 1e-9


def test_event_name_forms():
    assert event_name('2026_Monza') == 'Monza'
    assert event_name('Monza') == 'Monza'


def test_completed_weekends_equal_validation_rows(provider, v1_lock):
    ages = np.arange(1, 31, dtype=float)
    n = 0
    for row in v1_lock['validation_rows']:
        if not row.get('completed'):
            continue
        cv = provider.predict_curve(row['event'], 'NOR', row['compound'], None, (1, 30))
        assert abs(cv.slope - row['pred_clearstint']) < TOL
        assert abs(cv.band[0] - row['lo']) < TOL and abs(cv.band[1] - row['hi']) < TOL
        assert np.allclose(cv.mean_loss_s, row['pred_clearstint'] * ages, atol=TOL)
        assert np.allclose(cv.q50_loss_s, cv.mean_loss_s, atol=TOL)
        assert np.allclose(cv.q10_loss_s, row['lo'] * ages, atol=TOL)
        assert np.allclose(cv.q90_loss_s, row['hi'] * ages, atol=TOL)
        assert (cv.cliff_probability == 0).all()
        assert cv.provenance['source'] == 'validation_rows' and cv.provenance['post_race'] is False
        n += 1
    assert n >= 20


def test_live_weekend_equals_live_block(provider, v1_lock):
    ages = np.arange(0, 41, dtype=float)
    for event, live in v1_lock['live'].items():
        for c in live['compounds']:
            cv = provider.predict_curve(event, None, c['compound'], {'ignored': True}, (0, 40))
            assert abs(cv.slope - c['prediction']) < TOL
            assert abs(cv.band[0] - c['band90'][0]) < TOL and abs(cv.band[1] - c['band90'][1]) < TOL
            assert np.allclose(cv.mean_loss_s, c['prediction'] * ages, atol=TOL)
            assert cv.provenance['source'] == 'live' and cv.provenance['context_used'] is False


def test_provenance_carries_model_version_and_lock_v2_hash(provider, v2_lock):
    cv = provider.predict_curve('2026_Monza', 'NOR', 'SOFT')
    assert cv.provenance['model_version'] == MODEL_VERSION == 'provider_A_v2'
    assert cv.provenance['forecast_hash'] == v2_lock['shared']['forecast_hash']
    assert provider.forecast_hash.startswith('sha256:')


def test_agrees_with_lock_v2_pre_race_forecast(provider, v2_lock):
    for event, ev in v2_lock['pre_race_forecast']['events'].items():
        for c, cf in ev['compounds'].items():
            cv = provider.predict_curve(event, None, c)
            assert abs(cv.slope - cf['prediction']) < TOL, (event, c)
            assert abs(cv.band[0] - cf['band90'][0]) < TOL and abs(cv.band[1] - cf['band90'][1]) < TOL


def test_unavailable_compound_raises(provider):
    with pytest.raises(CurveUnavailable):
        provider.predict_curve('Madrid', None, 'HARD')
    with pytest.raises(CurveUnavailable):
        provider.predict_curve('Nowhere', None, 'SOFT')


def test_reference_curve_is_post_race_and_fenced(provider, v1_lock):
    row = next(r for r in v1_lock['validation_rows'] if r['event'] == 'Monza' and r['compound'] == 'MEDIUM')
    ref = provider.reference_curve_post_race('Monza', 'MEDIUM', (1, 10))
    assert abs(ref.slope - row['obs']) < TOL and abs(ref.slope_se - row['obs_se']) < TOL
    assert ref.post_race and ref.provenance['uses_post_race_reference'] is True
    with pytest.raises(ValueError):
        assert_pre_race(ref)
    pre = provider.predict_curve('Monza', None, 'MEDIUM')
    assert assert_pre_race(pre) is pre and not pre.post_race
    with pytest.raises(CurveUnavailable):
        provider.reference_curve_post_race('Madrid', 'SOFT')      # live weekend: no race yet


def test_sampling_sd_rules(provider):
    pre = provider.predict_curve('Monza', None, 'SOFT')
    assert pre.slope_se is None and abs(pre.sampling_sd - (pre.band[1] - pre.band[0]) / (2 * 1.6448536269514722)) < TOL
    ref = provider.reference_curve_post_race('Monza', 'SOFT')
    assert abs(ref.sampling_sd - ref.slope_se) < TOL
