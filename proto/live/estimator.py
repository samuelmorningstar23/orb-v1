"""LiveTyreStateEstimator (roadmap v5 task 0.8, contract 7.1). Estimator of record: linear-Gaussian with fixed regime rules.

Model, per stint. State theta = (intercept a, slope b) of the corrected lap time y = a + b x age; y = lap_s - 0.03 x fuel_kg
(race fuel 70 kg over n_laps) - evolution x t_min (race evolution is 0: the lock carries none). Observations are the clean
laps of the stint (pit, SC/VSC/yellow/red, deleted, inaccurate, unknown-or-heavy-traffic laps and laps slower than 105 % of
the stint's best so far are dropped). Measurement noise sigma_y = 0.40 s (the median within-stint residual of the development
races is 0.35 s; 0.40 gives nominal 90 % coverage in the prefix evaluation at the same MAE; fixed, documented). Prior slope b0 ~ N(prediction, sd^2) with sd = (band90[1] - band90[0]) / (2 x 1.6449) from the
frozen pre-race forecast of the compound; the intercept prior is diffuse (sd 5 s) centred on the first clean lap's corrected
time under the prior slope (anchor). Every lap of the stint adds process noise q = (0.0025 s/lap/lap)^2 to the slope
variance (random-walk slope), so the band never collapses: it is bounded below by q and by the measurement-noise floor
(the slope precision a full-race-length stint at sigma_y could reach), and the predictive band of any lap always contains
sigma_y^2. A pit stop (new stint, new compound, out-lap) resets the state to the compound's prior.

Widening rules multiply the slope variance in the predict step of the lap on which they fire; implemented additively
(P_bb += (F - 1) P_bb) so the batch conditioning of the same Gaussian model equals the sequential filter exactly:
    track status not '1' (SC / VSC / yellow / red)            x2 per lap
    rain flag on the lap                                       x4 per lap
    track temperature change > 3 C within 10 minutes           x2 per lap
    feed quality degraded (pos_distinct < 100 on the lap)      x2 per lap
    out-of-support flag from the context                       x2, applied to the compound prior at the reset
    driver feedback (live/feedback.py table)                   q x(1..2) for 2 to 3 laps
The slope variance never grows beyond WIDEN_CAP x the prior variance (2 x the pre-race band width) and never falls below
the floor. Widening only ever adds variance; it is never negative.

Regime rules, fixed and documented (label: 'linear-Gaussian with fixed regime rules'); precedence top to bottom:
    CLIFF              the last two laps' loss exceeds twice the posterior slope: both lap-over-lap increments positive, each
                       at least 20 % of their mean (the loss is spread over both laps, not one outlier), and
                       y[-1] - y[-3] > max(2 x b_post x (age[-1] - age[-3]), 2 sqrt(2) sigma_y)   (needs three kept laps)
    ANOMALY            the latest residual exceeds three predictive sigmas (the lap is still used: linear-Gaussian, no gating)
    OVERHEATING /      only through driver feedback: running feedback regime probability > 0.5
    GRAINING
    ACCELERATING_WEAR  posterior slope mean > prior q90 (mean + 1.2816 sd)
    WARMUP             first two laps of a stint (tyre age <= 2), or a front-understeer warm-up flag within the first 4 laps
    NORMAL             otherwise
Contract 7.1 vocabulary lacks ACCELERATING_WEAR and ANOMALY: they map to 'normal' (+ trend_vs_pre_race) and
'damage_suspected'; the full label travels in confidence_effect and in the estimator trace (open question for Workstream 1).

Derived quantities. useful_laps: laps until the predicted loss crosses the same-age crossover to the best available
alternative compound (lock offsets, lock forecast slopes; strategy2.crossover), sampled from the slope posterior, capped at
the laps remaining (no crossover -> laps remaining). cliff_probability_h = P[the slope path exceeds twice the pre-race
slope (floor 0.05 s/lap per lap) within h laps] under the sampled posterior with the random-walk drift; 0.8 floor while
the CLIFF rule is active; nested in h by construction. The crossover probability is reported as a component only
(cliff_components.p_cross): reaching the compound crossover is a strategy fact, not a cliff. trend_vs_pre_race = b_post / b_prior - 1. confidence = share
of the prior slope variance removed by live observations (0 when widened back to the prior), x0.8 on a degraded feed.
thermal_stress_index / performance_wear_index are PUBLIC PROXY demand proxies (lap energy vs the driver's own laps so
far and track temperature; share of the median useful life consumed), never physical wear.

Data boundary: `update(prior_state, telemetry, context)` produces the state for lap k = context.lap and accepts only the
telemetry row of lap k (LapNumber == k). A later row raises FutureDataError; an earlier or repeated lap raises ValueError.
Every state carries data_cutoff (the completion timestamp of lap k), uses_future_data = False and
uses_post_race_reference = False. Priors come from live/priors.py, which strips every race-derived field.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import numpy as np

from live import ESTIMATOR_LABEL, MODEL_VERSION
from live.clock import SessionClock
from live.feedback import DriverFeedbackAdapter, FeedbackLogEntry, FeedbackObservation, REGIME_LABEL_THRESHOLD, apply_shift, decay_regime_probs
from live.lapfeed import BEST_RATIO, FutureDataError, base_clean, corrected_time, is_green
from live.priors import CompoundPrior, EventPriors, Z90, Z_Q90

SIGMA_Y = 0.40                 # s, measurement noise of a clean corrected lap (0.35 = median within-stint residual of the development races; 0.40 chosen for 90 % coverage, see PREFIX_EVAL.md)
SIGMA_TRAFFIC = 0.60           # s, noise of a lap driven in traffic (traffic_mode 'inflate': kept with this noise instead of dropped)
TRAFFIC_MODE = 'drop'          # 'drop' (lock rule: traffic > 30 % or unknown is not an observation) | 'inflate'
Q_SLOPE = 0.0025 ** 2          # (s/lap per lap)^2 added to the slope variance every lap of a stint
INTERCEPT_SD = 5.0             # s, diffuse intercept prior around the anchor
WIDEN_CAP = 4.0                # slope variance never exceeds WIDEN_CAP x prior variance (2 x the band width)
WIDEN_STATUS, WIDEN_RAIN, WIDEN_TEMP, WIDEN_FEED, WIDEN_OOS = 2.0, 4.0, 2.0, 2.0, 2.0
TEMP_SHIFT_C, TEMP_WINDOW_MIN = 3.0, 10.0
FEED_MIN_POS_DISTINCT = 100
CLIFF_MIN_RATE = 0.05          # s/lap per lap, floor of the forward cliff threshold (2 x pre-race slope)
CLIFF_PROB_FLOOR = 0.8         # while the CLIFF rule is active
WARMUP_LAPS = 2
N_SAMPLES = 4000
SEED = 8
REGIMES = ('WARMUP', 'NORMAL', 'OVERHEATING', 'GRAINING', 'ACCELERATING_WEAR', 'CLIFF', 'ANOMALY')
SCHEMA_REGIME = {'WARMUP': 'warm_up', 'NORMAL': 'normal', 'OVERHEATING': 'overheating', 'GRAINING': 'graining', 'ACCELERATING_WEAR': 'normal', 'CLIFF': 'cliff', 'ANOMALY': 'damage_suspected'}
PUBLIC_CHANNELS = ('lap_time', 'sector_times', 'car_telemetry', 'position_xy', 'weather', 'team_radio')
PRIVATE_CHANNELS = ('tyre_pressure', 'tyre_surface_temp', 'tyre_carcass_temp', 'tread_depth')


@dataclass
class LiveContext:
    """Per-lap context handed to the estimator. `lap` is the lap being produced; nothing else may exceed it."""
    event: str
    driver: str
    lap: int
    n_laps: int
    priors: EventPriors
    clock: Optional[SessionClock] = None
    evolution_s_per_min: float = 0.0
    out_of_support: bool = False
    support_status: str = 'IN SUPPORT'
    support_reason: str = ''
    source_latency_s: float = 3.0
    feedback_enabled: bool = True
    available_compounds: Optional[list[str]] = None
    sensor_mode: str = 'PUBLIC PROXY'


@dataclass
class LapRecord:
    lap: int
    age: int
    lap_s: float
    t_min: float
    y: float
    kept: bool
    reason: str
    track_status: str
    resid: Optional[float] = None       # innovation before the update (kept laps)
    pred_sd: Optional[float] = None     # predictive sd before the update
    anomaly: bool = False
    sigma: Optional[float] = None       # observation noise used for this lap (kept laps)


@dataclass
class WideningEvent:
    lap: int
    rule: str
    factor: float           # requested multiplier
    applied: float          # effective multiplier after the cap


@dataclass
class TyreStateDistribution:
    """Posterior over (intercept, slope) of the current stint plus everything the outputs need. Online-safe by construction."""
    event: str
    driver: str
    lap: int
    stint: int
    compound: str
    tyre_age: int
    timestamp: str                                   # data_cutoff: completion time of `lap`
    m: list[float]                                   # [a, b]; a is NaN until the anchor
    P: list[list[float]]
    prior: dict[str, Any]                            # compound prior (mean, sd, band90, q90, issued, basis, source)
    m0: list[float]                                  # prior mean at the reset (a anchored later)
    P0: list[list[float]]                            # prior covariance at the reset (out-of-support widening included)
    sigma_y: float
    q: float
    q_schedule: list[list[float]] = field(default_factory=list)   # [[lap, q_total]] per stint lap, in order
    laps: list[LapRecord] = field(default_factory=list)
    stint_best_s: Optional[float] = None
    n_obs: int = 0
    anchored: bool = False
    regime: str = 'WARMUP'
    regime_probs: dict[str, float] = field(default_factory=dict)
    widening: list[WideningEvent] = field(default_factory=list)          # this lap
    widening_log: list[WideningEvent] = field(default_factory=list)      # whole stint
    temps: list[list[float]] = field(default_factory=list)               # [[t_min, track_temp]] seen so far (driver's own laps)
    fb_noise_mult: float = 1.0
    fb_noise_laps_left: int = 0
    warmup_flag_until_age: int = 0
    feedback_log: list[FeedbackLogEntry] = field(default_factory=list)
    feedback_this_lap: list[FeedbackObservation] = field(default_factory=list)
    compounds_used: list[str] = field(default_factory=list)
    stops_done: int = 0
    stint_first_lap: int = 0
    quality: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)
    derived: dict[str, Any] = field(default_factory=dict)
    changes: list[str] = field(default_factory=list)                     # observations that moved the state this lap
    support_status: str = 'IN SUPPORT'
    support_reason: str = ''
    n_laps: int = 0
    uses_future_data: bool = False
    uses_post_race_reference: bool = False
    estimator: str = ESTIMATOR_LABEL
    model_version: str = MODEL_VERSION

    # ---- posterior accessors ------------------------------------------------------------------------------------
    @property
    def slope(self) -> float:
        return float(self.m[1])

    @property
    def slope_var(self) -> float:
        return float(self.P[1][1])

    @property
    def slope_sd(self) -> float:
        return math.sqrt(max(self.slope_var, 0.0))

    @property
    def intercept(self) -> Optional[float]:
        return None if not self.anchored else float(self.m[0])

    @property
    def slope_band90(self) -> tuple[float, float]:
        return (self.slope - Z90 * self.slope_sd, self.slope + Z90 * self.slope_sd)

    @property
    def kept(self) -> list[LapRecord]:
        return [r for r in self.laps if r.kept]

    @property
    def prior_slope(self) -> float:
        return float(self.prior['mean'])

    @property
    def prior_sd(self) -> float:
        return float(self.prior['sd'])

    def predict(self, age: float, laps_ahead: int = 0) -> tuple[float, float]:
        """Predictive (mean, sd) of the corrected lap time at tyre age `age`, `laps_ahead` laps after the current one."""
        if not self.anchored:
            return math.nan, math.nan
        P = np.array(self.P, dtype=float)
        h = np.array([1.0, float(age)])
        var = float(h @ P @ h) + self.sigma_y ** 2 + max(0, laps_ahead) * self.q * float(age) ** 2
        return float(h @ np.array(self.m, dtype=float)), math.sqrt(max(var, self.sigma_y ** 2))

    def loss_at(self, age: float) -> float:
        return self.slope * float(age)

    def project(self, horizons=(1, 3, 5, 10)) -> list[dict]:
        out = []
        for h in horizons:
            age = self.tyre_age + h
            mean, sd = self.predict(age, h)
            loss = self.loss_at(age)
            lsd = math.sqrt(max(self.slope_var + h * self.q, 0.0)) * age
            out.append(dict(h=h, age=age, loss=loss, lo=loss - Z90 * lsd, hi=loss + Z90 * lsd, time=mean, time_lo=mean - Z90 * sd if math.isfinite(mean) else math.nan, time_hi=mean + Z90 * sd if math.isfinite(mean) else math.nan))
        return out

    def as_trace(self) -> dict[str, Any]:
        d = dict(event=self.event, driver=self.driver, lap=self.lap, stint=self.stint, compound=self.compound, tyre_age=self.tyre_age, data_cutoff=self.timestamp,
                 intercept=self.intercept, slope=self.slope, slope_sd=self.slope_sd, slope_band90=list(self.slope_band90), prior=self.prior, n_obs=self.n_obs,
                 regime=self.regime, regime_probs=self.regime_probs, widening=[asdict(w) for w in self.widening], q_total_this_lap=(self.q_schedule[-1][1] if self.q_schedule else None),
                 flags=self.flags, quality=self.quality, derived=self.derived, changes=self.changes, feedback_this_lap=[f.as_dict() for f in self.feedback_this_lap],
                 fb_noise_mult=self.fb_noise_mult, fb_noise_laps_left=self.fb_noise_laps_left, compounds_used=self.compounds_used, stops_done=self.stops_done,
                 support_status=self.support_status, uses_future_data=self.uses_future_data, uses_post_race_reference=self.uses_post_race_reference,
                 estimator=self.estimator, model_version=self.model_version,
                 laps=[asdict(r) for r in self.laps])
        return _finite(d)


def _finite(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _finite(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_finite(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        return _finite(float(obj))
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def slope_sd_floor(sigma_y: float, n_laps: int) -> float:
    """Measurement-noise floor: slope sd of an OLS fit over a full-race-length stint at sigma_y (ages 1..N)."""
    n = max(int(n_laps), 3)
    return sigma_y * math.sqrt(12.0 / (n ** 3 - n))


class LiveTyreStateEstimator:
    """update(prior_state, telemetry, context, driver_feedback=None, sensor_data=None) -> TyreStateDistribution."""

    label = ESTIMATOR_LABEL

    def __init__(self, sigma_y: float = SIGMA_Y, q: float = Q_SLOPE, intercept_sd: float = INTERCEPT_SD, widen_cap: float = WIDEN_CAP,
                 adapter: Optional[DriverFeedbackAdapter] = None, n_samples: int = N_SAMPLES, seed: int = SEED, traffic_mode: str = TRAFFIC_MODE, sigma_traffic: float = SIGMA_TRAFFIC):
        self.sigma_y, self.q, self.intercept_sd, self.widen_cap = float(sigma_y), float(q), float(intercept_sd), float(widen_cap)
        self.traffic_mode, self.sigma_traffic = str(traffic_mode), float(sigma_traffic)
        self.adapter = adapter or DriverFeedbackAdapter()
        self.n_samples, self.seed = int(n_samples), int(seed)

    # ---- reset -------------------------------------------------------------------------------------------------------
    def reset(self, row: dict, context: LiveContext, previous: Optional[TyreStateDistribution]) -> TyreStateDistribution:
        compound = str(row['Compound'])
        pr: CompoundPrior = context.priors.prior_for(compound)
        var_b = pr.var * (WIDEN_OOS if context.out_of_support else 1.0)
        floor = slope_sd_floor(self.sigma_y, context.n_laps) ** 2
        var_b = max(var_b, floor)
        P0 = [[self.intercept_sd ** 2, 0.0], [0.0, var_b]]
        used = list(previous.compounds_used) if previous else []
        if compound not in used:
            used.append(compound)
        stops = (previous.stops_done if previous else 0) + (1 if previous is not None and (int(row['Stint']) != previous.stint or bool(row.get('pit_out'))) else 0)
        st = TyreStateDistribution(event=context.event, driver=context.driver, lap=int(row['LapNumber']), stint=int(row['Stint']), compound=compound, tyre_age=int(row['TyreLife']) if row.get('TyreLife') is not None and math.isfinite(float(row['TyreLife'])) else 0,
                                   timestamp='', m=[math.nan, pr.mean], P=[[P0[0][0], 0.0], [0.0, P0[1][1]]], prior=dict(pr.as_dict(), q90=pr.q90, var_used=var_b, out_of_support=bool(context.out_of_support)),
                                   m0=[math.nan, pr.mean], P0=P0, sigma_y=self.sigma_y, q=self.q, temps=list(previous.temps) if previous else [], compounds_used=used, stops_done=stops,
                                   stint_first_lap=int(row['LapNumber']), n_laps=int(context.n_laps), regime_probs={}, feedback_log=[])
        if context.out_of_support:
            st.widening_log.append(WideningEvent(int(row['LapNumber']), 'out_of_support (prior)', WIDEN_OOS, WIDEN_OOS))
        if previous is not None:
            st.changes.append(f"pit reset: new {compound.lower()} (stint {st.stint}), prior slope {pr.mean:+.4f} +- {pr.sd:.4f} s/lap per lap restored")
        return st

    # ---- widening --------------------------------------------------------------------------------------------------
    def _widening_factor(self, st: TyreStateDistribution, row: dict, context: LiveContext) -> tuple[float, list[tuple[str, float]]]:
        rules: list[tuple[str, float]] = []
        status = str(row.get('TrackStatus', '1'))
        if not is_green(status):
            rules.append((f'track status {status}', WIDEN_STATUS))
        if bool(row.get('rain', False)):
            rules.append(('rain flag', WIDEN_RAIN))
        temp, t_min = row.get('track_temp'), row.get('t_min')
        if temp is not None and t_min is not None and math.isfinite(float(temp)) and math.isfinite(float(t_min)):
            recent = [tt for (tm, tt) in st.temps if float(t_min) - tm <= TEMP_WINDOW_MIN and tm < float(t_min)]
            if recent and max(abs(float(temp) - tt) for tt in recent) > TEMP_SHIFT_C:
                rules.append((f'track temperature shift {float(temp) - recent[-1]:+.1f} C within {TEMP_WINDOW_MIN:.0f} min', WIDEN_TEMP))
        pos = row.get('pos_distinct')
        if pos is not None and math.isfinite(float(pos)) and float(pos) < FEED_MIN_POS_DISTINCT:
            rules.append((f'feed quality degraded ({int(float(pos))} position samples)', WIDEN_FEED))
        f = 1.0
        for _, x in rules:
            f *= x
        return f, rules

    # ---- clean rule --------------------------------------------------------------------------------------------------
    def _clean(self, st: TyreStateDistribution, row: dict) -> tuple[bool, str, float]:
        """(kept, reason, observation noise). traffic_mode 'inflate' keeps traffic laps as noisier observations."""
        ok, reason = base_clean(row)
        sigma = self.sigma_y
        if not ok:
            if self.traffic_mode == 'inflate' and reason.startswith('traffic'):
                ok, sigma, reason = True, self.sigma_traffic, f'kept in traffic (noise {self.sigma_traffic:.2f} s): ' + reason
            else:
                return False, reason, sigma
        lap_s = float(row['lap_s'])
        best = lap_s if st.stint_best_s is None else min(st.stint_best_s, lap_s)
        st.stint_best_s = best
        if lap_s > BEST_RATIO * best:
            return False, f'slower than 105 % of the stint best so far ({best:.3f} s)', sigma
        return True, reason if reason != 'kept' else 'kept', sigma

    # ---- update ------------------------------------------------------------------------------------------------------
    def update(self, prior_state: Optional[TyreStateDistribution], telemetry: dict, context: LiveContext, driver_feedback: Optional[list[dict]] = None,
               sensor_data: Optional[dict] = None) -> TyreStateDistribution:
        row = dict(telemetry)
        k = int(row['LapNumber'])
        if k > int(context.lap):
            raise FutureDataError(f'telemetry of lap {k} offered while producing lap {context.lap}: future data')
        if k != int(context.lap):
            raise ValueError(f'telemetry lap {k} is not the lap being produced ({context.lap})')
        if prior_state is not None and k <= prior_state.lap:
            raise ValueError(f'lap {k} is not later than the previous state lap {prior_state.lap}')
        if sensor_data is not None and context.sensor_mode == 'PUBLIC PROXY':
            sensor_data = None          # private channels are not allowed under PUBLIC PROXY; Phase 1 team adapter
        new_stint = prior_state is None or int(row['Stint']) != prior_state.stint or bool(row.get('pit_out')) or str(row['Compound']) != prior_state.compound
        st = self.reset(row, context, prior_state) if new_stint else copy.deepcopy(prior_state)
        st.lap, st.tyre_age, st.widening, st.changes, st.feedback_this_lap = k, int(row['TyreLife']) if row.get('TyreLife') is not None and math.isfinite(float(row['TyreLife'])) else st.tyre_age + 1, [], (st.changes if new_stint else []), []
        st.n_laps = int(context.n_laps)
        st.support_status, st.support_reason = context.support_status, context.support_reason
        st.timestamp = context.clock.lap_end_iso(row['t_min'], row['lap_s']) if context.clock is not None and row.get('t_min') is not None else f'lap-{k}'
        pos = row.get('pos_distinct')
        degraded = pos is not None and math.isfinite(float(pos)) and float(pos) < FEED_MIN_POS_DISTINCT
        st.quality = dict(pos_distinct=(int(float(pos)) if pos is not None and math.isfinite(float(pos)) else None), degraded=bool(degraded), stale_share=row.get('stale_share'), n_tel=row.get('n_tel'))
        st.flags = dict(green=is_green(row.get('TrackStatus', '1')), track_status=str(row.get('TrackStatus', '1')), rain=bool(row.get('rain', False)), pit_in=bool(row.get('pit_in')), pit_out=bool(row.get('pit_out')),
                        out_of_support=bool(context.out_of_support), feed_degraded=bool(degraded), track_temp=row.get('track_temp'))
        # 1. predict: process noise (feedback multiplier) then widening, additive, capped, never negative
        P = np.array(st.P, dtype=float)
        q_total = self.q * (st.fb_noise_mult if st.fb_noise_laps_left > 0 else 1.0)
        if st.fb_noise_laps_left > 0:
            st.fb_noise_laps_left -= 1
            if st.fb_noise_laps_left == 0:
                st.fb_noise_mult = 1.0
        P[1, 1] += q_total
        F, rules = self._widening_factor(st, row, context)
        if F > 1.0:
            cap_mult = max(1.0, self.widen_cap * float(st.P0[1][1]) / P[1, 1])
            F_eff = min(F, cap_mult)
            add = (F_eff - 1.0) * P[1, 1]
            P[1, 1] += add
            q_total += add
            for rule, f in rules:
                st.widening.append(WideningEvent(k, rule, f, F_eff if len(rules) == 1 else f * (F_eff / F)))
            st.widening_log.extend(st.widening)
            st.changes.append('band widened x%.2f (%s)' % (F_eff, '; '.join(r for r, _ in rules)))
        st.q_schedule.append([k, float(q_total)])
        if row.get('track_temp') is not None and row.get('t_min') is not None and math.isfinite(float(row['track_temp'])) and math.isfinite(float(row['t_min'])):
            st.temps.append([float(row['t_min']), float(row['track_temp'])])
        # 2. observation
        kept, reason, sigma_obs = self._clean(st, row)
        y = corrected_time(row['lap_s'], k, context.n_laps, row.get('t_min') or 0.0, context.evolution_s_per_min) if row.get('lap_s') is not None and math.isfinite(float(row['lap_s'])) else math.nan
        age = float(st.tyre_age)
        rec = LapRecord(k, int(age), float(row['lap_s']) if math.isfinite(y) else math.nan, float(row.get('t_min') or 0.0), float(y), bool(kept), reason, str(row.get('TrackStatus', '1')))
        m = np.array(st.m, dtype=float)
        if kept:
            if not st.anchored:
                m[0] = y - m[1] * age
                st.m0[0] = float(m[0])
                st.anchored = True
            H = np.array([1.0, age])
            S = float(H @ P @ H) + sigma_obs ** 2
            resid = float(y - H @ m)
            K = (P @ H) / S
            m = m + K * resid
            IKH = np.eye(2) - np.outer(K, H)
            P = IKH @ P @ IKH.T + np.outer(K, K) * sigma_obs ** 2
            rec.resid, rec.pred_sd, rec.anomaly, rec.sigma = resid, math.sqrt(S), abs(resid) > 3.0 * math.sqrt(S), float(sigma_obs)
            st.n_obs += 1
            prev_slope = float(st.m[1])
            st.changes.append(f'clean lap {k} (age {int(age)}, {y:.3f} s corrected, residual {resid:+.2f} s) moved the slope {prev_slope:+.4f} -> {float(m[1]):+.4f}')
        # floor: the slope variance never collapses below the measurement-noise floor
        floor = slope_sd_floor(self.sigma_y, context.n_laps) ** 2
        if P[1, 1] < floor:
            P[1, 1] = floor
        st.m, st.P = [float(m[0]), float(m[1])], [[float(P[0, 0]), float(P[0, 1])], [float(P[1, 0]), float(P[1, 1])]]
        st.laps.append(rec)
        # 3. driver feedback (regime probabilities and process noise only; never seconds)
        st.regime_probs = decay_regime_probs(st.regime_probs)
        for e in st.feedback_log:
            e.laps_since += 1
        if driver_feedback and context.feedback_enabled:
            for evt in driver_feedback:
                obs = self.adapter.parse(evt)
                assert obs.slope_shift_s_per_lap == 0.0, 'feedback must never add seconds to the curve'
                st.regime_probs = apply_shift(st.regime_probs, obs.regime_shift)
                if obs.noise_multiplier > 1.0 and obs.noise_laps > 0:
                    st.fb_noise_mult = max(st.fb_noise_mult if st.fb_noise_laps_left > 0 else 1.0, obs.noise_multiplier)
                    st.fb_noise_laps_left = max(st.fb_noise_laps_left, obs.noise_laps)
                if obs.warmup_flag:
                    st.warmup_flag_until_age = max(st.warmup_flag_until_age, min(st.tyre_age + 1, 4))
                st.feedback_log.append(FeedbackLogEntry(obs, st.slope, st.slope_sd, 'pending' if obs.regime_shift else 'not applicable', 0))
                st.feedback_this_lap.append(obs)
                st.changes.append(f"driver feedback lap {obs.lap}: {obs.symptom} {obs.axle} {obs.corner_phase} severity {obs.severity}/5 {obs.trend} ({obs.rule}: {obs.note})")
        for e in st.feedback_log:
            if e.telemetry_support == 'pending' and e.laps_since >= 2 and e.slope_at_report is not None and st.n_obs >= 1:
                moved = st.slope - e.slope_at_report
                e.telemetry_support = 'confirmed' if moved > 0.5 * max(e.slope_sd_at_report or 0.0, 1e-6) else ('weakened' if e.laps_since >= 4 else 'pending')
        # 4. regime rules and derived outputs
        st.regime = self._regime(st)
        st.derived = self._derived(st, context, row)
        return st

    # ---- regime rules ------------------------------------------------------------------------------------------------
    def _regime(self, st: TyreStateDistribution) -> str:
        kept = st.kept
        cliff = False
        if len(kept) >= 3:
            a, b, c = kept[-3], kept[-2], kept[-1]
            d1 = (b.y - a.y) / max(b.age - a.age, 1)
            d2 = (c.y - b.y) / max(c.age - b.age, 1)
            span = max(c.age - a.age, 1)
            spread = min(d1, d2) >= 0.2 * (d1 + d2) / 2.0       # the loss is spread over both laps, not a single outlier
            cliff = d1 > 0 and d2 > 0 and spread and (c.y - a.y) > max(2.0 * st.slope * span, 2.0 * math.sqrt(2.0) * self.sigma_y)
        if cliff:
            return 'CLIFF'
        if kept and kept[-1].lap == st.lap and kept[-1].anomaly:
            return 'ANOMALY'
        fb = {r: p for r, p in st.regime_probs.items() if r in ('OVERHEATING', 'GRAINING') and p > REGIME_LABEL_THRESHOLD}
        if fb:
            return max(fb, key=fb.get)
        if st.regime_probs.get('ANOMALY', 0.0) > REGIME_LABEL_THRESHOLD:
            return 'ANOMALY'
        if st.n_obs >= 1 and st.slope > float(st.prior['q90']):
            return 'ACCELERATING_WEAR'
        if st.tyre_age <= WARMUP_LAPS or st.tyre_age <= st.warmup_flag_until_age:
            return 'WARMUP'
        return 'NORMAL'

    # ---- derived outputs ---------------------------------------------------------------------------------------------
    def _derived(self, st: TyreStateDistribution, context: LiveContext, row: dict) -> dict[str, Any]:
        priors = context.priors
        remaining = max(int(context.n_laps) - st.lap, 0)
        rng = np.random.default_rng(self.seed * 100003 + st.lap * 101 + st.stint)
        b = rng.normal(st.slope, st.slope_sd, self.n_samples)
        comps = context.available_compounds or [c for c in ('SOFT', 'MEDIUM', 'HARD') if priors.has(c) and c in priors.offsets]
        o_c = priors.offsets.get(st.compound, 0.0)
        life_raw = np.full(self.n_samples, np.inf)       # laps to the same-age crossover, uncapped (inf: no crossover)
        alt_used = None
        for d in comps:
            if d == st.compound or d not in priors.offsets or not priors.has(d):
                continue
            o_d, b_d = priors.offsets[d], priors.prior_for(d).mean
            if o_d <= o_c:
                continue                      # the alternative is faster when fresh: no same-age crossover limits this tyre's life
            with np.errstate(divide='ignore', invalid='ignore'):
                age_star = np.where(b > b_d, (o_d - o_c) / (b - b_d), np.inf)
            life = np.maximum(age_star - st.tyre_age, 0.0)
            if alt_used is None or np.median(life) < np.median(life_raw):
                alt_used = d
            life_raw = np.minimum(life_raw, life)
        useful = np.clip(life_raw, 0.0, float(remaining))   # operational useful laps cannot exceed the laps remaining
        q10, q50, q90 = (float(x) for x in np.quantile(useful, [0.1, 0.5, 0.9]))
        # cliff probabilities: crossover within h laps (uncapped: the chequered flag is not a cliff), or the slope path
        # exceeding twice the pre-race slope within h laps
        thr = max(2.0 * st.prior_slope, CLIFF_MIN_RATE)
        drift = np.cumsum(rng.normal(0.0, math.sqrt(self.q), (self.n_samples, 5)), axis=1)
        path = b[:, None] + drift
        p_rate3, p_rate5 = float(np.mean((path[:, :3] > thr).any(axis=1))), float(np.mean((path[:, :5] > thr).any(axis=1)))
        p_cross3, p_cross5 = float(np.mean(life_raw <= 3.0)), float(np.mean(life_raw <= 5.0))
        p3, p5 = p_rate3, p_rate5           # the crossover (p_cross) is reported as a component, not counted as a cliff
        if st.regime == 'CLIFF':
            p3, p5 = max(p3, CLIFF_PROB_FLOOR), max(p5, CLIFF_PROB_FLOOR)
        p5 = max(p5, p3)
        p3, p5 = min(max(p3, 0.0), 1.0), min(max(p5, 0.0), 1.0)
        # trend, confidence, indices
        trend = (st.slope / st.prior_slope - 1.0) if abs(st.prior_slope) > 1e-6 else 0.0
        conf = 1.0 - st.slope_sd / max(st.prior_sd, 1e-9)
        conf = min(max(conf, 0.0), 1.0) * (0.8 if st.quality.get('degraded') else 1.0)
        kept = st.kept
        loss_now = (kept[-1].y - st.intercept) if kept and st.anchored else st.loss_at(st.tyre_age)
        wear = st.tyre_age / max(st.tyre_age + q50, 1e-9) if remaining > 0 else 1.0
        e = row.get('energy_MJ')
        own = [float(r) for r in st.derived.get('_energy_hist', [])] if st.derived else []
        if e is not None and math.isfinite(float(e)):
            own.append(float(e))
        e_ref = float(np.quantile(own, 0.95)) if own else None
        temp = row.get('track_temp')
        t_part = min(max((float(temp) - 20.0) / 40.0, 0.0), 1.0) if temp is not None and math.isfinite(float(temp)) else 0.5
        e_part = min(max(float(e) / e_ref, 0.0), 1.0) if (e is not None and e_ref and math.isfinite(float(e))) else 0.5
        tsi = 0.5 * e_part + 0.5 * t_part + 0.2 * st.regime_probs.get('OVERHEATING', 0.0)
        tsi = min(max(tsi, 0.0), 1.0)
        return dict(useful_laps_q10=q10, useful_laps_q50=q50, useful_laps_q90=q90, useful_life_alternative=alt_used, remaining_laps=remaining,
                    cliff_probability_3_laps=p3, cliff_probability_5_laps=p5, cliff_components=dict(p_cross3=p_cross3, p_cross5=p_cross5, p_rate3=p_rate3, p_rate5=p_rate5, threshold=thr),
                    trend_vs_pre_race=float(trend), confidence=float(conf), corrected_pace_loss=float(loss_now), thermal_stress_index=float(tsi), performance_wear_index=float(min(max(wear, 0.0), 1.0)),
                    projection=st.project(), slope_band90=list(st.slope_band90), _energy_hist=own[-60:])

    # ---- contract 7.1 record -----------------------------------------------------------------------------------------
    def to_live_tyre_state(self, st: TyreStateDistribution, context: LiveContext) -> dict[str, Any]:
        d = st.derived
        avail = {c: True for c in PUBLIC_CHANNELS}
        avail['car_telemetry'] = not bool(st.quality.get('degraded'))
        avail['position_xy'] = not bool(st.quality.get('degraded'))
        avail['weather'] = st.flags.get('track_temp') is not None
        avail['team_radio'] = bool(context.feedback_enabled)
        for c in PRIVATE_CHANNELS:
            avail[c] = False
        missing = sorted(k for k, v in avail.items() if not v)
        widen = '; '.join(f'{w.rule} x{w.applied:.2f}' for w in st.widening) or 'none'
        effect = (f'{ESTIMATOR_LABEL}; regime {st.regime}; PUBLIC PROXY: no tyre pressures or temperatures are observed, thermal_stress_index and performance_wear_index are '
                  f'demand-based proxies; slope posterior {st.slope:+.4f} +- {st.slope_sd:.4f} s/lap per lap from {st.n_obs} clean laps (prior {st.prior_slope:+.4f} +- {st.prior_sd:.4f}); '
                  f'widening this lap: {widen}')
        return _finite(dict(lap=int(st.lap), timestamp=st.timestamp, compound=st.compound, tyre_age=int(st.tyre_age), state_regime=SCHEMA_REGIME[st.regime],
                            corrected_pace_loss=float(d['corrected_pace_loss']), degradation_rate=float(st.slope), thermal_stress_index=float(d['thermal_stress_index']),
                            performance_wear_index=float(d['performance_wear_index']), useful_laps_q10=float(d['useful_laps_q10']), useful_laps_q50=float(d['useful_laps_q50']),
                            useful_laps_q90=float(d['useful_laps_q90']), cliff_probability_3_laps=float(d['cliff_probability_3_laps']), cliff_probability_5_laps=float(d['cliff_probability_5_laps']),
                            trend_vs_pre_race=float(d['trend_vs_pre_race']), confidence=float(d['confidence']), sensor_mode=context.sensor_mode, support_status=st.support_status,
                            sensor_availability=avail, source_latency=float(context.source_latency_s), missing_channels=missing,
                            quality_status='DEGRADED' if st.quality.get('degraded') else 'OK', confidence_effect=effect, team_sensor=None))


# ---- batch conditioning (the same Gaussian model solved at once) -------------------------------------------------------
def batch_posterior(st: TyreStateDistribution) -> tuple[np.ndarray, np.ndarray]:
    """Posterior (m, P) of the stint state at the last lap from the prior at the reset, the per-lap process-noise schedule
    and every kept observation, by joint-Gaussian conditioning (no recursion). Equals the sequential filter to 1e-9:
    tests/live/test_estimator.py::test_batch_equals_replay."""
    m0 = np.array(st.m0, dtype=float)
    P0 = np.array(st.P0, dtype=float)
    laps = [int(l) for l, _ in st.q_schedule]
    qs = np.array([q for _, q in st.q_schedule], dtype=float)
    cum = np.cumsum(qs)                                   # cumulative slope process noise through each stint lap
    idx = {lap: i for i, lap in enumerate(laps)}
    obs = [r for r in st.laps if r.kept and r.lap in idx]
    T = len(laps) - 1
    PT = P0 + np.diag([0.0, cum[T]]) if T >= 0 else P0.copy()
    if not obs:
        return m0, PT
    H = np.array([[1.0, float(r.age)] for r in obs])
    y = np.array([r.y for r in obs])
    ti = np.array([idx[r.lap] for r in obs])
    n = len(obs)
    Vy = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            c = cum[min(ti[i], ti[j])]
            Vy[i, j] = H[i] @ (P0 + np.diag([0.0, c])) @ H[j]
    Vy += np.diag([(r.sigma if r.sigma else st.sigma_y) ** 2 for r in obs])
    Cty = np.zeros((2, n))
    for i in range(n):
        Cty[:, i] = (P0 + np.diag([0.0, cum[ti[i]]])) @ H[i]
    G = np.linalg.solve(Vy, (y - H @ m0))
    m = m0 + Cty @ G
    P = PT - Cty @ np.linalg.solve(Vy, Cty.T)
    floor = slope_sd_floor(st.sigma_y, st.n_laps) ** 2
    if P[1, 1] < floor:
        P[1, 1] = floor
    return m, P


__all__ = ['LiveTyreStateEstimator', 'TyreStateDistribution', 'LiveContext', 'LapRecord', 'WideningEvent', 'batch_posterior', 'slope_sd_floor', 'SCHEMA_REGIME', 'REGIMES',
           'SIGMA_Y', 'Q_SLOPE', 'INTERCEPT_SD', 'WIDEN_CAP', 'WIDEN_STATUS', 'WIDEN_RAIN', 'WIDEN_TEMP', 'WIDEN_FEED', 'WIDEN_OOS', 'TEMP_SHIFT_C', 'TEMP_WINDOW_MIN',
           'FEED_MIN_POS_DISTINCT', 'CLIFF_PROB_FLOOR', 'ESTIMATOR_LABEL']
