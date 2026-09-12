"""DriverFeedbackAdapter (roadmap v5 task 0.10 / contract 7.3).

A feedback event is a timestamped observation with a confidence, entered or confirmed by the engineer. The adapter turns it
into a `FeedbackObservation` that shifts regime probabilities and the slope process noise of the live estimator. It never
adds seconds to a curve: `FeedbackObservation.slope_shift_s_per_lap` is always 0.0 and the estimator asserts it. The effect
decays lap by lap (REGIME_DECAY) unless the next laps of telemetry confirm it, and the estimator can be run with
feedback disabled, in which case the result reverts exactly (tests/live/test_feedback.py).

Regime-shift table (first matching row wins; magnitudes are multiplied by `strength`):

  row  condition                                                          regime shift              q multiplier  laps  other
  R1   sliding/oversteer/lack_of_grip, rear, traction/exit, sev>=3, worse  OVERHEATING +0.60         x2.0          3
  R2   sliding/oversteer/lack_of_grip, rear, sev>=3                        OVERHEATING +0.30         x1.5          3
  R3   overheating (any axle)                                              OVERHEATING +0.70         x2.0          3
  R4   graining (any axle)                                                 GRAINING +0.50 (sev>=3) / +0.30   x1.5  3
  R5   understeer, front/all, entry/mid                                    none                      x1.0          0     warm-up flag
  R6   vibration                                                           ANOMALY +0.40             x1.5          2
  R7   lack_of_grip, front/all                                             GRAINING +0.20, OVERHEATING +0.20  x1.25  2
  R8   anything else (mild reports)                                        half of R2                x1.0          0

  strength = severity/5 x driver_confidence x (1.0 if engineer_confirmed else 0.5) x trend factor
             (worsening 1.0, stable 0.7, unknown 0.7, improving 0.3)
  effective q multiplier = 1 + (multiplier - 1) x strength; regime shifts are added to the running regime probabilities,
  which decay by REGIME_DECAY per lap and are clipped to [0, 0.95]. A regime label from feedback needs p > 0.5: one
  maximal confirmed report (severity 5, confidence 1, worsening) flips the label, a moderate one raises the probability.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

AXLES = ('front', 'rear', 'all', 'unknown')
CORNER_PHASES = ('braking', 'entry', 'mid', 'exit', 'traction')
SYMPTOMS = ('understeer', 'oversteer', 'sliding', 'graining', 'overheating', 'vibration', 'lack_of_grip')
TRENDS = ('improving', 'stable', 'worsening', 'unknown')
UI_SOURCE_TO_SCHEMA = {'radio': 'team_radio', 'engineer': 'engineer_entry', 'debrief': 'other', 'manual': 'engineer_entry', 'team_radio': 'team_radio',
                       'engineer_entry': 'engineer_entry', 'simulated': 'simulated', 'other': 'other'}
TREND_FACTOR = {'worsening': 1.0, 'stable': 0.7, 'unknown': 0.7, 'improving': 0.3}
REGIME_DECAY = 0.7            # per lap, applied to the feedback-driven regime probabilities
REGIME_LABEL_THRESHOLD = 0.5  # p above which a feedback regime overrides NORMAL / ACCELERATING_WEAR
REGIME_PROB_CAP = 0.95


@dataclass
class FeedbackObservation:
    lap: int
    timestamp: str
    symptom: str
    axle: str
    corner_phase: str
    severity: int
    trend: str
    driver_confidence: float
    engineer_confirmed: bool
    source: str
    strength: float
    regime_shift: dict[str, float]
    noise_multiplier: float          # effective multiplier on the slope process noise q
    noise_laps: int
    warmup_flag: bool
    rule: str
    note: str
    raw_message: str = ''
    slope_shift_s_per_lap: float = 0.0   # invariant: feedback never adds seconds

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FeedbackLogEntry:
    """What the estimator keeps per report: the observation and whether the next laps of telemetry supported it."""
    observation: FeedbackObservation
    slope_at_report: Optional[float]
    slope_sd_at_report: Optional[float]
    telemetry_support: str = 'pending'     # pending | confirmed | weakened | not applicable
    laps_since: int = 0


def _strength(severity: int, driver_confidence: float, engineer_confirmed: bool, trend: str) -> float:
    s = (max(1, min(5, int(severity))) / 5.0) * max(0.0, min(1.0, float(driver_confidence))) * (1.0 if engineer_confirmed else 0.5) * TREND_FACTOR.get(trend, 0.7)
    return float(max(0.0, min(1.0, s)))


class DriverFeedbackAdapter:
    """parse(event) -> FeedbackObservation. Accepts the UI log rows (app_v2/state/feedback_events.jsonl) and contract 7.3 events."""

    table_doc = __doc__

    def parse(self, event: dict) -> FeedbackObservation:
        symptom = str(event.get('symptom', 'lack_of_grip'))
        axle = str(event.get('axle', 'unknown'))
        phase = str(event.get('corner_phase', 'mid'))
        severity = int(event.get('severity', 3))
        trend = str(event.get('trend', 'unknown'))
        conf = float(event.get('driver_confidence', 0.7))
        confirmed = bool(event.get('engineer_confirmed', False))
        source = UI_SOURCE_TO_SCHEMA.get(str(event.get('source', 'other')), 'other')
        if symptom not in SYMPTOMS or axle not in AXLES or phase not in CORNER_PHASES:
            raise ValueError(f'feedback vocabulary outside contract 7.3: {symptom} {axle} {phase}')
        if trend not in TRENDS:
            trend = 'unknown'
        strength = _strength(severity, conf, confirmed, trend)
        rear_grip = symptom in ('sliding', 'oversteer', 'lack_of_grip') and axle == 'rear'
        shift: dict[str, float] = {}
        mult, laps, warm, rule, note = 1.0, 0, False, 'R8', 'mild report: half of R2, no noise change'
        if rear_grip and phase in ('traction', 'exit') and severity >= 3 and trend == 'worsening':
            shift, mult, laps, rule, note = {'OVERHEATING': 0.6}, 2.0, 3, 'R1', 'rear traction loss worsening: overheating probability up, slope process noise x2'
        elif rear_grip and severity >= 3:
            shift, mult, laps, rule, note = {'OVERHEATING': 0.3}, 1.5, 3, 'R2', 'rear grip loss: overheating probability up, slope process noise x1.5'
        elif symptom == 'overheating':
            shift, mult, laps, rule, note = {'OVERHEATING': 0.7}, 2.0, 3, 'R3', 'overheating reported: overheating probability up, slope process noise x2'
        elif symptom == 'graining':
            shift, mult, laps, rule, note = {'GRAINING': 0.5 if severity >= 3 else 0.3}, 1.5, 3, 'R4', 'graining reported: graining probability up, slope process noise x1.5'
        elif symptom == 'understeer' and axle in ('front', 'all') and phase in ('entry', 'mid'):
            shift, mult, laps, warm, rule, note = {}, 1.0, 0, True, 'R5', 'front understeer: no slope change, warm-up flag'
        elif symptom == 'vibration':
            shift, mult, laps, rule, note = {'ANOMALY': 0.4}, 1.5, 2, 'R6', 'vibration: anomaly (flat spot / damage) probability up, slope process noise x1.5'
        elif symptom == 'lack_of_grip' and axle in ('front', 'all'):
            shift, mult, laps, rule, note = {'GRAINING': 0.2, 'OVERHEATING': 0.2}, 1.25, 2, 'R7', 'front / general grip loss: graining and overheating probability up, slope process noise x1.25'
        else:
            shift = {'OVERHEATING': 0.15} if rear_grip else {}
        shift = {k: round(v * strength, 6) for k, v in shift.items()}
        eff_mult = 1.0 + (mult - 1.0) * strength
        return FeedbackObservation(int(event.get('lap', 0)), str(event.get('timestamp', '')), symptom, axle, phase, severity, trend, conf, confirmed, source, strength,
                                   shift, float(eff_mult), int(laps if eff_mult > 1.0 else 0), warm, rule, note, str(event.get('raw_message', '') or ''), 0.0)

    @staticmethod
    def to_schema_event(event: dict, feedback_id: Optional[str] = None) -> dict:
        """UI log row -> contract 7.3 DriverFeedbackEvent dict (vocabulary mapped, extra UI keys dropped)."""
        trend = str(event.get('trend', 'unknown'))
        return dict(feedback_id=feedback_id, timestamp=str(event['timestamp']), lap=int(event['lap']), axle=str(event['axle']), corner_phase=str(event['corner_phase']),
                    symptom=str(event['symptom']), severity=int(event['severity']), trend=trend if trend in TRENDS else 'unknown', driver_confidence=float(event['driver_confidence']),
                    source=UI_SOURCE_TO_SCHEMA.get(str(event.get('source', 'other')), 'other'), raw_message=(str(event.get('raw_message')) or None), engineer_confirmed=bool(event.get('engineer_confirmed', False)))


def decay_regime_probs(probs: dict[str, float]) -> dict[str, float]:
    return {k: v * REGIME_DECAY for k, v in probs.items() if v * REGIME_DECAY > 1e-3}


def apply_shift(probs: dict[str, float], shift: dict[str, float]) -> dict[str, float]:
    out = dict(probs)
    for k, v in shift.items():
        out[k] = float(min(REGIME_PROB_CAP, max(0.0, out.get(k, 0.0) + v)))
    return out


__all__ = ['DriverFeedbackAdapter', 'FeedbackObservation', 'FeedbackLogEntry', 'decay_regime_probs', 'apply_shift', 'REGIME_DECAY', 'REGIME_LABEL_THRESHOLD',
           'UI_SOURCE_TO_SCHEMA', 'TREND_FACTOR', 'SYMPTOMS', 'AXLES', 'CORNER_PHASES', 'TRENDS']
