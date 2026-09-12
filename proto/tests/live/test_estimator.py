"""LiveTyreStateEstimator: data boundary, widening, reset, floor, regimes, batch == replay, contract validation."""
import copy
import math

import numpy as np
import pytest

from live import ESTIMATOR_LABEL
from live.estimator import (LiveTyreStateEstimator, batch_posterior, slope_sd_floor, WIDEN_STATUS, WIDEN_RAIN, WIDEN_TEMP, WIDEN_FEED, WIDEN_OOS, WIDEN_CAP, SCHEMA_REGIME)
from live.lapfeed import FutureDataError, LapFeed
from live.priors import POST_RACE_KEYS, load_priors
from schemas.lock_v2 import LiveTyreState
from live_helpers import mk_row, ctx_for, run_rows, PROTO


# ---- data boundary ----------------------------------------------------------------------------------------------------
def test_feeding_a_future_lap_raises(priors, clean_rows):
    est = LiveTyreStateEstimator()
    st = est.update(None, clean_rows[0], ctx_for(priors, 1))
    with pytest.raises(FutureDataError):
        est.update(st, clean_rows[2], ctx_for(priors, 2))        # lap 3 row while producing lap 2
    with pytest.raises(FutureDataError):
        est.update(None, clean_rows[1], ctx_for(priors, 1))      # lap 2 row while producing lap 1
    with pytest.raises(ValueError):
        est.update(st, clean_rows[0], ctx_for(priors, 1))        # lap 1 again: not later than the previous state


def test_every_state_is_flagged_online_safe(priors, clean_rows):
    for st in run_rows(LiveTyreStateEstimator(), clean_rows, priors):
        assert st.uses_future_data is False and st.uses_post_race_reference is False
        assert st.estimator == ESTIMATOR_LABEL
        assert st.timestamp


def test_lapfeed_never_exposes_a_later_lap(have_races):
    if not have_races:
        pytest.skip('race files not present')
    feed = LapFeed('Monza')
    v = feed.through('NOR', 20)
    assert int(v['LapNumber'].max()) <= 20 and feed.row('NOR', 21) is not None
    me = feed.row('NOR', 20)
    cutoff = me['t_min'] * 60 + me['lap_s']
    for car in feed.field_at('NOR', 20):
        assert car.lap <= 20 and car.t_end_s <= cutoff + 1e-9


def test_priors_never_expose_race_outcomes(have_races):
    if not have_races:
        pytest.skip('lock not present')
    p = load_priors('Monza')
    blob = repr(p)
    for key in POST_RACE_KEYS:
        assert f"'{key}'" not in blob
    assert 'obs' not in [k for c in p.compounds.values() for k in c.as_dict()]


# ---- widening triggers --------------------------------------------------------------------------------------------------
def _var_after_predict(priors, row, base_rows, **ctx_kw):
    """Slope variance after the predict step of `row` (made non-observable via unknown traffic) minus the prior state."""
    est = LiveTyreStateEstimator()
    states = run_rows(est, base_rows, priors)
    before = states[-1]
    row = dict(row, traffic=float('nan'))       # not an observation: only the predict step acts
    after = est.update(before, row, ctx_for(priors, row['LapNumber'], **ctx_kw))
    return before.slope_var, after.slope_var, after


@pytest.mark.parametrize('kw,factor,rule', [
    (dict(status='4'), WIDEN_STATUS, 'track status'),
    (dict(status='2'), WIDEN_STATUS, 'track status'),
    (dict(rain=True), WIDEN_RAIN, 'rain'),
    (dict(pos=60), WIDEN_FEED, 'feed quality'),
])
def test_widening_multiplies_the_slope_variance(priors, clean_rows, kw, factor, rule):
    base = clean_rows[:6]
    v0, v1, st = _var_after_predict(priors, mk_row(7, 7, 100.0, **kw), base)
    q = st.q
    assert v1 == pytest.approx(min((v0 + q) * factor, WIDEN_CAP * st.P0[1][1]), rel=1e-9)     # the multiplier, unless the cap binds
    assert any(rule in w.rule for w in st.widening) and all(w.applied >= 1.0 for w in st.widening)
    v0n, v1n, _ = _var_after_predict(priors, mk_row(7, 7, 100.0), base)
    assert v1n == pytest.approx(v0n + q, rel=1e-9)               # no trigger: process noise only


def test_temperature_shift_widens(priors, clean_rows):
    base = clean_rows[:6]                                           # temps 45 C, t_min 61.5 .. 69
    v0, v1, st = _var_after_predict(priors, mk_row(7, 7, 100.0, temp=49.0, t_min=70.5), base)
    assert v1 == pytest.approx((v0 + st.q) * WIDEN_TEMP, rel=1e-9)
    v0, v1, st = _var_after_predict(priors, mk_row(7, 7, 100.0, temp=47.0, t_min=70.5), base)      # 2 C: no trigger
    assert v1 == pytest.approx(v0 + st.q, rel=1e-9)
    v0, v1, st = _var_after_predict(priors, mk_row(7, 7, 100.0, temp=49.0, t_min=85.0), base)      # 4 C but 16 min later: no trigger
    assert v1 == pytest.approx(v0 + st.q, rel=1e-9)


def test_out_of_support_doubles_the_prior_variance_at_reset(priors, clean_rows):
    est = LiveTyreStateEstimator()
    a = est.update(None, dict(clean_rows[0], traffic=float('nan')), ctx_for(priors, 1))
    b = est.update(None, dict(clean_rows[0], traffic=float('nan')), ctx_for(priors, 1, out_of_support=True))
    assert b.P0[1][1] == pytest.approx(a.P0[1][1] * WIDEN_OOS, rel=1e-9)
    assert b.slope_var == pytest.approx(a.slope_var - a.P0[1][1] + a.P0[1][1] * WIDEN_OOS, rel=1e-9)
    assert any('out_of_support' in w.rule for w in b.widening_log)


def test_combined_triggers_multiply_and_the_cap_holds(priors, clean_rows):
    base = clean_rows[:6]
    v0, v1, st = _var_after_predict(priors, mk_row(7, 7, 100.0, status='4', rain=True, pos=50), base)
    expected = min((v0 + st.q) * WIDEN_STATUS * WIDEN_RAIN * WIDEN_FEED, WIDEN_CAP * st.P0[1][1])
    assert v1 == pytest.approx(expected, rel=1e-9)
    assert v1 <= WIDEN_CAP * st.P0[1][1] + 1e-12
    # widening never reduces the variance, however many laps it runs
    est = LiveTyreStateEstimator()
    st = None
    prev = None
    for k in range(1, 15):
        st = est.update(st, mk_row(k, k, 100.0, status='4', traffic=float('nan')), ctx_for(priors, k))
        if prev is not None:
            assert st.slope_var >= prev - 1e-15
        prev = st.slope_var
    # the widening multiplier is capped; only the per-lap process noise q keeps accumulating above the cap
    assert WIDEN_CAP * st.P0[1][1] <= st.slope_var <= WIDEN_CAP * st.P0[1][1] + 14 * st.q + 1e-12


def test_band_never_collapses_below_the_floor(priors):
    rng = np.random.default_rng(3)
    rows = [mk_row(k, k, 90.0 + 0.05 * k + rng.normal(0, 0.05)) for k in range(1, 50)]
    est = LiveTyreStateEstimator()
    floor = slope_sd_floor(est.sigma_y, priors.n_laps) ** 2
    for st in run_rows(est, rows, priors):
        assert st.slope_var >= floor - 1e-15
        mean, sd = st.predict(st.tyre_age + 1, 1)
        assert sd >= est.sigma_y - 1e-12


# ---- reset at pit stops ---------------------------------------------------------------------------------------------------
def test_pit_reset_restores_the_compound_prior(priors, clean_rows):
    est = LiveTyreStateEstimator()
    states = run_rows(est, clean_rows[:12], priors)
    before = states[-1]
    assert before.n_obs == 12 and before.slope_var < before.P0[1][1]
    pit_in = mk_row(13, 13, 110.0, pit_in=True)
    out_lap = mk_row(14, 1, 105.0, stint=2, compound='HARD', pit_out=True)
    st = est.update(before, pit_in, ctx_for(priors, 13))
    assert st.stint == 1 and st.n_obs == 12
    st = est.update(st, out_lap, ctx_for(priors, 14))
    hard = priors.prior_for('HARD')
    assert st.stint == 2 and st.compound == 'HARD' and st.n_obs == 0 and not st.anchored
    assert st.slope == pytest.approx(hard.mean) and st.P0[1][1] == pytest.approx(hard.var, rel=1e-9)
    assert st.stops_done == 1 and st.compounds_used == ['MEDIUM', 'HARD']
    assert any(c.startswith('pit reset') for c in st.changes)
    st = est.update(st, mk_row(15, 2, 92.0, stint=2, compound='HARD'), ctx_for(priors, 15))
    assert st.anchored and st.n_obs == 1 and st.regime == 'WARMUP'


# ---- batch == replay ------------------------------------------------------------------------------------------------------
def test_batch_equals_replay_synthetic(priors, clean_rows):
    est = LiveTyreStateEstimator()
    rows = clean_rows[:8] + [mk_row(9, 9, 100.0, status='4', traffic=float('nan')), mk_row(10, 10, 95.0, traffic=float('nan'))] + [mk_row(k, k, 90.5 + 0.06 * k + 0.03 * 70 * (1 - (k - 1) / 50), pos=(50 if k == 13 else 300)) for k in range(11, 18)]
    st = run_rows(est, rows, priors)[-1]
    m, P = batch_posterior(st)
    assert abs(m[0] - st.m[0]) < 1e-9 and abs(m[1] - st.m[1]) < 1e-9
    assert np.max(np.abs(P - np.array(st.P))) < 1e-9


def test_batch_equals_replay_with_traffic_inflation(priors, clean_rows):
    est = LiveTyreStateEstimator(traffic_mode='inflate')
    rows = [dict(r, traffic=(0.6 if r['LapNumber'] % 3 == 0 else 0.1)) for r in clean_rows]
    st = run_rows(est, rows, priors)[-1]
    assert any(r.sigma == est.sigma_traffic for r in st.kept)
    m, P = batch_posterior(st)
    assert abs(m[1] - st.m[1]) < 1e-9 and np.max(np.abs(P - np.array(st.P))) < 1e-9


def test_batch_equals_replay_real_race(have_races):
    if not have_races:
        pytest.skip('race files not present')
    from live.session import LiveSession
    for ev in ('Austria', 'Barcelona', 'Monza'):
        feed = LapFeed(ev)
        drv = max(feed.drivers, key=lambda d: len(feed.laps_of(d)))      # the driver with the most recorded laps
        s = LiveSession.open(ev, drv, feedback_enabled=False)
        st, n = None, 0
        for k in s.laps():
            row = s.feed.row(drv, k)
            st = s.estimator.update(st, row, s.context_for(k, row))
            if st.n_obs >= 1:
                m, P = batch_posterior(st)
                assert abs(m[1] - st.m[1]) < 1e-9 and abs(P[1, 1] - st.P[1][1]) < 1e-9 and abs(m[0] - st.m[0]) < 1e-9
                n += 1
        assert n > 20


# ---- regime rules ----------------------------------------------------------------------------------------------------------
def test_regime_rules(priors, clean_rows):
    est = LiveTyreStateEstimator()
    states = run_rows(est, clean_rows, priors)
    assert states[0].regime == 'WARMUP' and states[1].regime == 'WARMUP' and states[5].regime == 'NORMAL'
    # accelerating wear: slope well above the prior q90 (0.05 + 1.28 x 0.024 = 0.081)
    fast = [mk_row(k, k, 90.0 + 0.16 * k + 0.03 * 70 * (1 - (k - 1) / 50)) for k in range(1, 16)]
    st = run_rows(LiveTyreStateEstimator(), fast, priors)[-1]
    assert st.regime == 'ACCELERATING_WEAR' and st.slope > priors.prior_for('MEDIUM').q90 and st.derived['trend_vs_pre_race'] > 1.0
    # cliff: two consecutive laps losing far more than twice the posterior slope
    cliff = clean_rows[:12] + [mk_row(13, 13, clean_rows[11]['lap_s'] + 1.0), mk_row(14, 14, clean_rows[11]['lap_s'] + 2.2)]
    st = run_rows(LiveTyreStateEstimator(), cliff, priors)[-1]
    assert st.regime == 'CLIFF' and st.derived['cliff_probability_3_laps'] >= 0.8 and st.derived['cliff_probability_5_laps'] >= st.derived['cliff_probability_3_laps']
    # anomaly: a single lap far outside the predictive band
    anom = clean_rows[:12] + [mk_row(13, 13, clean_rows[11]['lap_s'] + 3.0)]
    st = run_rows(LiveTyreStateEstimator(), anom, priors)[-1]
    assert st.regime == 'ANOMALY' and st.kept[-1].anomaly


def test_contract_record_validates_and_maps_the_regime(priors, clean_rows):
    est = LiveTyreStateEstimator()
    st = None
    for r in clean_rows:
        ctx = ctx_for(priors, r['LapNumber'])
        st = est.update(st, r, ctx)
        rec = est.to_live_tyre_state(st, ctx)
        model = LiveTyreState.model_validate(rec)
        assert model.state_regime == SCHEMA_REGIME[st.regime]
        assert model.useful_laps_q10 <= model.useful_laps_q50 <= model.useful_laps_q90 <= priors.n_laps - st.lap + 1e-9
        assert model.cliff_probability_3_laps <= model.cliff_probability_5_laps
        assert model.sensor_mode == 'PUBLIC PROXY' and model.team_sensor is None and 'tyre_pressure' in model.missing_channels
        assert ESTIMATOR_LABEL in (model.confidence_effect or '')
    assert st.derived['confidence'] > 0.3 and abs(st.slope - 0.06) < 0.02


def test_deep_copy_isolation(priors, clean_rows):
    est = LiveTyreStateEstimator()
    a = est.update(None, clean_rows[0], ctx_for(priors, 1))
    snapshot = copy.deepcopy(a.as_trace())
    est.update(a, clean_rows[1], ctx_for(priors, 2))
    assert a.as_trace() == snapshot          # the prior state is never mutated by the next update
