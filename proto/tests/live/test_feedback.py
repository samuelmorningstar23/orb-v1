"""DriverFeedbackAdapter: regime-shift table, no seconds added, reversibility when disabled."""
import pytest

from live.estimator import LiveTyreStateEstimator
from live.feedback import DriverFeedbackAdapter, REGIME_DECAY
from schemas.lock_v2 import DriverFeedbackEvent
from live_helpers import mk_row, run_rows


def fb(lap, symptom='sliding', axle='rear', phase='traction', severity=4, trend='worsening', conf=0.8, confirmed=True, source='radio'):
    return dict(timestamp='2026-09-06T15:20:00', event='Synthetic', driver='SYN', lap=lap, axle=axle, corner_phase=phase, symptom=symptom, severity=severity, trend=trend,
                driver_confidence=conf, source=source, raw_message='rears are going', engineer_confirmed=confirmed)


def test_table_rows():
    ad = DriverFeedbackAdapter()
    o = ad.parse(fb(10))
    assert o.rule == 'R1' and o.regime_shift['OVERHEATING'] == pytest.approx(0.6 * 0.8 * 0.8) and o.noise_multiplier == pytest.approx(1 + 1.0 * 0.64) and o.noise_laps == 3
    assert o.slope_shift_s_per_lap == 0.0
    assert ad.parse(fb(10, symptom='graining', axle='front', phase='mid')).rule == 'R4'
    o = ad.parse(fb(10, symptom='understeer', axle='front', phase='entry'))
    assert o.rule == 'R5' and o.warmup_flag and o.regime_shift == {} and o.noise_multiplier == 1.0 and o.noise_laps == 0
    assert ad.parse(fb(10, symptom='vibration')).rule == 'R6' and 'ANOMALY' in ad.parse(fb(10, symptom='vibration')).regime_shift
    assert ad.parse(fb(10, symptom='overheating')).rule == 'R3'
    assert ad.parse(fb(10, symptom='lack_of_grip', axle='front', phase='mid')).rule == 'R7'
    mild = ad.parse(fb(10, severity=2))
    assert mild.rule == 'R8' and mild.noise_multiplier == 1.0
    # confidence and confirmation scale the effect; improving trend nearly cancels it
    weak = ad.parse(fb(10, conf=0.4, confirmed=False))
    assert weak.regime_shift['OVERHEATING'] == pytest.approx(0.6 * 0.8 * 0.4 * 0.5)
    assert ad.parse(fb(10, trend='improving')).strength == pytest.approx(0.8 * 0.8 * 0.3)
    with pytest.raises(ValueError):
        ad.parse(fb(10, symptom='wobble'))


def test_schema_mapping():
    e = DriverFeedbackAdapter.to_schema_event(fb(12, source='radio'), 'fb-0001')
    m = DriverFeedbackEvent.model_validate(e)
    assert m.source == 'team_radio' and m.lap == 12 and m.severity == 4
    assert DriverFeedbackAdapter.to_schema_event(fb(1, source='manual'))['source'] == 'engineer_entry'


def test_feedback_shifts_regime_and_noise_never_seconds(priors, clean_rows):
    est = LiveTyreStateEstimator()
    with_fb = run_rows(est, clean_rows, priors, feedback={10: [fb(10)]})
    without = run_rows(LiveTyreStateEstimator(), clean_rows, priors)
    s10, n10 = with_fb[9], without[9]
    assert s10.regime_probs.get('OVERHEATING', 0) > 0 and s10.fb_noise_laps_left == 3 and s10.fb_noise_mult > 1.0
    assert s10.slope == n10.slope and s10.slope_var == n10.slope_var          # the lap of the report: posterior mean and variance untouched
    assert s10.feedback_log[-1].observation.slope_shift_s_per_lap == 0.0
    # the next laps carry more process noise (wider), the mean moves only through observations
    assert with_fb[10].slope_var > without[10].slope_var
    assert with_fb[10].q_schedule[-1][1] == pytest.approx(est.q * s10.fb_noise_mult)
    assert with_fb[13].fb_noise_laps_left == 0 and with_fb[13].q_schedule[-1][1] == pytest.approx(est.q)
    # regime probability decays
    assert with_fb[11].regime_probs['OVERHEATING'] == pytest.approx(s10.regime_probs['OVERHEATING'] * REGIME_DECAY ** 2)
    # a strong confirmed report labels the regime OVERHEATING; telemetry support is assessed after two laps
    strong = run_rows(LiveTyreStateEstimator(), clean_rows, priors, feedback={10: [fb(10, severity=5, conf=1.0)]})
    assert strong[9].regime == 'OVERHEATING' and strong[9].regime_probs['OVERHEATING'] > 0.5
    assert strong[12].feedback_log[-1].telemetry_support in ('confirmed', 'weakened', 'pending')


def test_disabling_feedback_reverts_exactly(priors, clean_rows):
    events = {10: [fb(10)], 14: [fb(14, symptom='graining', axle='front', phase='mid', severity=5)]}
    enabled = run_rows(LiveTyreStateEstimator(), clean_rows, priors, feedback=events, feedback_enabled=True)
    disabled = run_rows(LiveTyreStateEstimator(), clean_rows, priors, feedback=events, feedback_enabled=False)
    none = run_rows(LiveTyreStateEstimator(), clean_rows, priors)
    for d, n in zip(disabled, none):
        assert d.m == n.m and d.P == n.P and d.regime == n.regime and d.regime_probs == n.regime_probs and d.q_schedule == n.q_schedule
        assert d.derived['useful_laps_q50'] == n.derived['useful_laps_q50'] and d.derived['cliff_probability_3_laps'] == n.derived['cliff_probability_3_laps']
        assert d.feedback_log == [] and d.feedback_this_lap == []
    assert enabled[-1].P != none[-1].P and enabled[9].feedback_log
