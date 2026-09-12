"""Orb v1 lock v2 contract (pydantic v2). Roadmap v5 sections 6 and 7; Workstream 1 owns this file, Workstream 7 reviews.

Namespaces (each a *stable* block, extra properties forbidden, NaN/inf refused, every block carries `meta: Meta`):
    shared              forecast_snapshot, model_version, forecast_hash, training_cutoff, support_definition
    pre_race_forecast   per event, per compound: the frozen Friday forecast; NEVER carries race outcomes
    validation          copy of the v1 validation numbers; rows and the sealed-holdout manifest as hashed sidecars
    live_predictor      data_cutoff, prior, posterior (LiveTyreState), recommendations[], driver_feedback[]; online-safe only
    ghost_strategy      post-race audit / scenario explorer / generalisation scorecard; model_implied is always true
    counterfactuals[]   Race Twin scenarios (each item is self-describing: schema_version, hashes, data_cutoff, split)
    input_availability  channel table with sensor_mode ('PUBLIC PROXY' | 'TEAM SENSOR')
    driver_profile      Phase 2 stub
    extensions          free dict: other workstreams put new material here until Workstream 1 promotes it into a stable block

Sidecar policy: anything array-like (per-lap states, traces, validation rows) lives in a file referenced as
SidecarRef {path, sha256[, bytes, format]} with `path` POSIX-relative to the lock root (proto/).
Hash policy: shared.forecast_hash == compute_forecast_hash(pre_race_forecast) and every other forecast hash in the
lock (ghost_strategy.forecast_snapshot_hash, live_predictor.prior.forecast_hash, counterfactuals[].forecast_hash) must
equal it: one frozen forecast powers both modes.

CLI:  python schemas/lock_v2.py export          -> schemas/lock_v2.schema.json
      python schemas/lock_v2.py validate <lock>  -> exit 0 if the file validates (sidecars are checked by validators/validate_lock.py)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, model_validator

_PROTO = Path(__file__).resolve().parents[1]
if str(_PROTO) not in sys.path:               # lets `python schemas/lock_v2.py` run from anywhere
    sys.path.insert(0, str(_PROTO))
from shared.lockio import check_relative_posix, forecast_hash as _forecast_hash  # noqa: E402

SCHEMA_VERSION = '2.1.0'   # 2.1.0: StateRegime += accelerating_wear, anomaly; TrafficMode / safety_car_schedule forms
SCHEMA_JSON_PATH = Path(__file__).with_name('lock_v2.schema.json')

# ---------------------------------------------------------------- vocabularies (import these; do not paraphrase them on screens)
Compound = Literal['SOFT', 'MEDIUM', 'HARD', 'INTERMEDIATE', 'WET']
SensorMode = Literal['PUBLIC PROXY', 'TEAM SENSOR']
SupportStatus = Literal['IN SUPPORT', 'NEAR TRAINING SUPPORT', 'OUT OF SUPPORT, FORECAST WITHHELD']
StateRegime = Literal['warm_up', 'normal', 'accelerating_wear', 'overheating', 'graining', 'cliff', 'damage_suspected', 'cooling', 'anomaly', 'unknown']
QualityStatus = Literal['OK', 'DEGRADED', 'STALE', 'OFFLINE']
GhostMode = Literal['historical_audit', 'scenario_explorer', 'generalisation_scorecard']
WeatherContext = Literal['actual_historical', 'pre_race_snapshot', 'cooler_dry', 'baseline_dry', 'hotter_dry', 'damp']   # wet: no validated wet model
EvidenceGrade = Literal['observed_outcome_audit', 'model_implied_scenario']
SimulationMode = Literal['tyre_only', 'fixed_context', 'frozen_field']
SplitId = Literal['development_pool', 'sealed_holdout', 'prospective']
TestStatus = Literal['pass', 'fail', 'not_run']
Action = Literal['PIT_NOW', 'PIT', 'STAY_OUT', 'EXTEND', 'MANAGE', 'HOLD']
SetStatus = Literal['new', 'scrubbed', 'used']
Axle = Literal['front', 'rear', 'all', 'unknown']
CornerPhase = Literal['braking', 'entry', 'mid', 'exit', 'traction']
Symptom = Literal['understeer', 'oversteer', 'sliding', 'graining', 'overheating', 'vibration', 'lack_of_grip']
Trend = Literal['improving', 'stable', 'worsening', 'unknown']
FeedbackSource = Literal['team_radio', 'engineer_entry', 'simulated', 'other']
EventSource = Literal['replay', 'live', 'recorded_live']
TrafficMode = Literal['clean_air', 'paired_replay', 'frozen_field']          # no traffic | observed traffic replayed as fixed context | traffic against a frozen field
SafetyCarScheduleMode = Literal['historical_fixed', 'observed_fixed']       # SC/VSC periods fixed as observed, not enumerated; or give the period list
SafetyCarMode = Literal['fixed_observed_schedule', 'none']
ForecastStatus = Literal['prospective', 'leave_one_weekend_out']
CircuitGeneralisation = Literal['seen', 'seen_circuit_new_season', 'never_seen']

SUPPORT_WITHHELD: SupportStatus = 'OUT OF SUPPORT, FORECAST WITHHELD'
CLAIM_SCOPE_BY_MODE: dict[str, str] = {
    'tyre_only': 'Model-implied tyre-time delta only. Track position, traffic and rival strategy responses are not simulated.',
    'fixed_context': 'Model-implied race-time delta with the observed race context held fixed (SC schedule, traffic, rivals on their observed trajectories). Rival strategy responses are not simulated.',
    'frozen_field': 'Model-implied race-time and finish-position distribution against a frozen field: rivals follow their observed trajectories and never respond strategically.',
}
PUBLIC_DISPLAY_RULES = [
    'Public mode never displays physical tread remaining, physical wear percentages or per-tyre structural health.',
    'Public mode displays performance_loss, operational useful laps remaining, thermal_stress_index and performance_wear_index.',
    'Every output carries sensor_availability, source_latency, missing_channels, quality_status and confidence_effect.',
    'sensor_mode and claim_scope are rendered verbatim, never paraphrased.',
]
DEFAULT_UNITS: dict[str, str] = {'pace_loss': 's/lap', 'degradation_rate': 's/lap per lap', 'time': 's', 'laps': 'lap', 'temperature': 'degC',
                                 'probability': 'fraction 0-1', 'index': 'fraction 0-1', 'latency': 's', 'energy': 'MJ'}

HASH_RE = r'^sha256:[0-9a-f]{64}$'
HEX64_RE = r'^[0-9a-f]{64}$'
GIT_RE = r'^[0-9a-f]{7,40}$'
DRIVER_RE = r'^[A-Z]{3}$'
EVENT_ID_RE = r'^\d{4}_[A-Za-z0-9]+$'
SEMVER_RE = r'^\d+\.\d+\.\d+$'
PLAN_RE = r'^[SMHIW](-[SMHIW])*$'

# ---------------------------------------------------------------- scalar helpers

def parse_ts(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f'not an ISO-8601 timestamp: {value!r}')


def _check_ts(value: str) -> str:
    parse_ts(value)
    return value


def ts_le(a: str, b: str) -> bool:
    """a <= b for two ISO timestamps; mixing naive and timezone-aware values is an error, not a guess."""
    da, db = parse_ts(a), parse_ts(b)
    if (da.tzinfo is None) != (db.tzinfo is None):
        raise ValueError(f'mixed naive and timezone-aware timestamps: {a!r} vs {b!r}')
    return da <= db


def _check_sidecar_path(value: str) -> str:
    return check_relative_posix(value)


Timestamp = Annotated[str, AfterValidator(_check_ts), Field(description='ISO-8601 timestamp', examples=['2026-09-13T15:04:05'])]
HashStr = Annotated[str, Field(pattern=HASH_RE, description="'sha256:' + 64 hex characters")]
Hex64 = Annotated[str, Field(pattern=HEX64_RE)]
GitSha = Annotated[str, Field(pattern=GIT_RE)]
DriverId = Annotated[str, Field(pattern=DRIVER_RE, examples=['NOR'])]
EventId = Annotated[str, Field(pattern=EVENT_ID_RE, examples=['2026_Monza'])]
SemVer = Annotated[str, Field(pattern=SEMVER_RE)]
Unit = Annotated[float, Field(ge=0.0, le=1.0)]
Pair = Annotated[list[float], Field(min_length=2, max_length=2)]
LapPair = Annotated[list[int], Field(min_length=2, max_length=2)]


def _ordered(*vals: Optional[float], names: tuple[str, ...]) -> None:
    present = [(n, v) for n, v in zip(names, vals) if v is not None]
    for (n1, v1), (n2, v2) in zip(present, present[1:]):
        if v1 > v2:
            raise ValueError(f'quantiles must be ordered: {n1}={v1} > {n2}={v2}')


class Strict(BaseModel):
    """Stable-block base: unknown keys rejected, NaN/inf rejected, aliases and field names both accepted on input."""
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, populate_by_name=True, validate_default=True)


# ---------------------------------------------------------------- common pieces

class Meta(Strict):
    """Provenance carried by every namespaced block."""
    schema_version: SemVer = SCHEMA_VERSION
    generated_at: Timestamp
    data_cutoff: Timestamp = Field(description='latest timestamp of any input this block was computed from')
    git_sha: GitSha
    model_version: str = Field(min_length=1)
    model_hash: HashStr
    provenance: str = Field(min_length=1, description='which code produced the block, from which inputs')
    units: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_UNITS))


class SidecarRef(Strict):
    """A large artifact kept out of the lock: path relative to the lock root (proto/), sha256 of the file bytes."""
    path: Annotated[str, AfterValidator(_check_sidecar_path)]
    sha256: Hex64
    bytes: Optional[int] = Field(default=None, ge=0)
    format: Optional[str] = None
    description: Optional[str] = None


# ---------------------------------------------------------------- shared

class ForecastSnapshot(Strict):
    snapshot_id: str = Field(min_length=1)
    kind: Literal['prospective', 'historical_only']
    event: Optional[str] = None
    event_id: Optional[EventId] = None
    season: Optional[int] = Field(default=None, ge=1950)
    issued_at: Timestamp
    sessions_used: list[str] = Field(default_factory=list)
    race_laps: Optional[int] = Field(default=None, ge=1)
    tyre_nomination: Optional[str] = None
    note: Optional[str] = None

    @model_validator(mode='after')
    def _prospective_needs_event(self) -> 'ForecastSnapshot':
        if self.kind == 'prospective' and not (self.event and self.event_id):
            raise ValueError('a prospective snapshot must name its event and event_id')
        return self


class SupportDefinition(Strict):
    definition: str = Field(min_length=1)
    tracks_seen: list[str] = Field(default_factory=list)
    drivers_seen: list[DriverId] = Field(default_factory=list)
    seasons_seen: list[int] = Field(default_factory=list)
    weather: list[str] = Field(default_factory=list)
    compounds: list[Compound] = Field(default_factory=list)
    track_temp_range_c: Optional[Pair] = None
    n_training_weekends: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode='after')
    def _range(self) -> 'SupportDefinition':
        if self.track_temp_range_c and self.track_temp_range_c[0] > self.track_temp_range_c[1]:
            raise ValueError('track_temp_range_c must be [low, high]')
        return self


class Shared(Strict):
    meta: Meta
    forecast_snapshot: ForecastSnapshot
    model_version: str = Field(min_length=1)
    forecast_hash: HashStr
    training_cutoff: Timestamp
    support_definition: SupportDefinition


# ---------------------------------------------------------------- pre_race_forecast

class SecondOpinion(Strict):
    prediction: float
    factor: float
    factor_applied: bool
    basis: str = Field(min_length=1)


class CompoundForecast(Strict):
    """One compound of one weekend, exactly the v1 per-compound record minus every post-race quantity."""
    compound: Compound
    n_prac: int = Field(ge=0, description='clean practice laps on this compound')
    naive: Optional[float] = Field(default=None, description='raw lap-time slope vs tyre age (s/lap per lap)')
    clean: float = Field(description='cleaned Friday slope (s/lap per lap)')
    clean_se: float = Field(ge=0.0)
    gate: str = Field(min_length=1, description="'ok' or the reason the curve was withheld")
    issued: bool
    factor: float = Field(description='season transfer factor applied to the clean slope (1.0 when not applied)')
    factor_applied: bool
    factor_from_n_weekends: Optional[int] = Field(default=None, ge=0)
    prediction: float = Field(description='race degradation forecast (s/lap per lap)')
    band90: Pair = Field(description='[5th, 95th] percentile after conformal widening')
    basis: str = Field(min_length=1)
    energy_trend: Optional[float] = None
    push_adj: Optional[float] = None
    second_opinion: Optional[SecondOpinion] = None

    @model_validator(mode='after')
    def _band(self) -> 'CompoundForecast':
        lo, hi = self.band90
        if lo > hi:
            raise ValueError(f'band90 must be [low, high], got {self.band90}')
        if not (lo - 1e-9 <= self.prediction <= hi + 1e-9):
            raise ValueError(f'prediction {self.prediction} lies outside band90 {self.band90}')
        if self.issued != (self.gate == 'ok'):
            raise ValueError("issued must be true exactly when gate == 'ok'")
        return self


class PlanAlternative(Strict):
    plan: Annotated[str, Field(pattern=PLAN_RE)]
    stops: int = Field(ge=0)
    stints: list[int] = Field(min_length=1)
    time_s: float
    delta_to_best_s: float = Field(ge=0.0)


class PreRacePlan(Strict):
    """The pre-race plan for the point forecast (v1 strategy view 'Orb v1'); cost-under-truth fields are validation, not forecast."""
    plan: Annotated[str, Field(pattern=PLAN_RE)]
    stints: list[int] = Field(min_length=1)
    stops: int = Field(ge=0)
    n_laps: int = Field(ge=1)
    pit_loss_s: float = Field(ge=0.0)
    crossover: dict[str, float] = Field(default_factory=dict)
    alternatives: list[PlanAlternative] = Field(default_factory=list, max_length=8)
    offsets_s: dict[Compound, float] = Field(default_factory=dict, description='compound pace offsets, SOFT = 0')
    offsets_source: dict[Compound, str] = Field(default_factory=dict)
    band_low_plan: Optional[Annotated[str, Field(pattern=PLAN_RE)]] = None
    band_high_plan: Optional[Annotated[str, Field(pattern=PLAN_RE)]] = None

    @model_validator(mode='after')
    def _consistent(self) -> 'PreRacePlan':
        if self.stops != len(self.stints) - 1:
            raise ValueError('stops must equal len(stints) - 1')
        if sum(self.stints) != self.n_laps:
            raise ValueError(f'stints {self.stints} do not sum to n_laps {self.n_laps}')
        if len(self.plan.split('-')) != len(self.stints):
            raise ValueError('plan label and stints disagree on the number of stints')
        return self


class EventForecast(Strict):
    event: str = Field(min_length=1)
    event_id: EventId
    season: int = Field(ge=1950)
    status: ForecastStatus
    data_cutoff: Timestamp
    format: Literal['conventional', 'sprint']
    sessions_used: list[str] = Field(default_factory=list)
    race_laps: Optional[int] = Field(default=None, ge=1)
    practice_laps_clean: int = Field(ge=0)
    practice_runs: int = Field(ge=0)
    track_temp_practice_c: Optional[float] = None
    rain_in_practice: bool = False
    tyre_nomination: Optional[str] = None
    compounds: dict[Compound, CompoundForecast] = Field(min_length=1)
    strategy: Optional[PreRacePlan] = None
    note: Optional[str] = None

    @model_validator(mode='after')
    def _keys(self) -> 'EventForecast':
        for k, c in self.compounds.items():
            if c.compound != k:
                raise ValueError(f'compounds[{k}].compound is {c.compound}')
        if self.strategy and self.race_laps and self.strategy.n_laps != self.race_laps:
            raise ValueError('strategy.n_laps must equal race_laps')
        return self


class PreRaceForecast(Strict):
    meta: Meta
    events: dict[str, EventForecast] = Field(min_length=1)

    @model_validator(mode='after')
    def _keys(self) -> 'PreRaceForecast':
        for k, e in self.events.items():
            if e.event != k:
                raise ValueError(f'events[{k}].event is {e.event}')
        return self


def compute_forecast_hash(block: PreRaceForecast | dict[str, Any]) -> str:
    """forecast_hash over the validated block (defaults materialised, aliases applied, meta removed)."""
    model = block if isinstance(block, PreRaceForecast) else PreRaceForecast.model_validate(block)
    return _forecast_hash(model.model_dump(mode='json', by_alias=True))


# ---------------------------------------------------------------- validation (v1 numbers, copied exactly)

class MaeIssued(Strict):
    naive: float
    clean: float
    clearstint: float
    push_adjusted: Optional[float] = None


class MaeAll(Strict):
    naive: float
    clearstint: float


class Calib(Strict):
    slope: float
    r: float
    n: int = Field(ge=0)


class Calibration(Strict):
    naive: Calib
    clean: Calib
    clearstint: Calib
    all_with_fallback: Calib


class ByCompound(Strict):
    n: int = Field(ge=0)
    mae_naive: Optional[float] = None
    mae_clearstint: Optional[float] = None
    k_median: Optional[float] = None


class WithheldCase(Strict):
    event: str
    compound: Compound
    gate: str
    clean: Optional[float] = None
    obs: Optional[float] = None
    floor: Optional[float] = None


class Describe3(Strict):
    min: Optional[float] = None
    p50: Optional[float] = Field(default=None, alias='50%')
    max: Optional[float] = None


class BetaPair(Strict):
    event: str
    practice: Optional[float] = None
    race: Optional[float] = None


class PushDiagnostic(Strict):
    energy_trend_withheld: Describe3
    energy_trend_issued: Describe3
    beta_practice_vs_race: list[BetaPair] = Field(default_factory=list)


class PathB(Strict):
    n_withheld_with_push_signal: int = Field(ge=0)
    mae_fallback: Optional[float] = None
    mae_push_adjusted: Optional[float] = None
    k3_medians: dict[Compound, Optional[float]] = Field(default_factory=dict)


class BandCoverage(Strict):
    raw_all: Unit
    calibrated_issued: Unit
    calibrated_fallback: Unit
    calibrated_all: Unit
    nominal: Unit
    widening_factor_median: float = Field(ge=0.0)
    widening_issued: float = Field(ge=0.0)
    widening_fallback: float = Field(ge=0.0)
    method: str = Field(min_length=1)


class ValidationBlock(Strict):
    """The v1 leave-one-weekend-out scorecard (out/lock.json 'validation'), copied exactly, plus hashed sidecars."""
    meta: Meta
    source: str = Field(min_length=1)
    n_weekends: int = Field(ge=0)
    n_compound_weekends: int = Field(ge=0)
    n_issued: int = Field(ge=0)
    n_withheld: int = Field(ge=0)
    mae_issued: MaeIssued
    mae_all_with_fallback: MaeAll
    ci90_mae_clearstint_all: Pair
    p_clearstint_beats_clean_issued: Unit
    p_clearstint_beats_naive_all: Unit
    calibration: Calibration
    by_compound: dict[Compound, ByCompound]
    withheld_cases: list[WithheldCase] = Field(default_factory=list)
    push_diagnostic: PushDiagnostic
    path_b_push_adjusted: PathB
    band_coverage: BandCoverage
    wins_clearstint_over_naive: int = Field(ge=0)
    wins_clearstint_over_clean_issued: int = Field(ge=0)
    rows: Optional[SidecarRef] = Field(default=None, description='validation_rows sidecar (one record per compound-weekend)')
    sealed_holdout: Optional[SidecarRef] = Field(default=None, description='sealed_holdout_manifest.json reference; never opened before freeze')

    @model_validator(mode='after')
    def _counts(self) -> 'ValidationBlock':
        if self.n_issued + self.n_withheld != self.n_compound_weekends:
            raise ValueError('n_issued + n_withheld must equal n_compound_weekends')
        if len(self.withheld_cases) != self.n_withheld:
            raise ValueError('withheld_cases length must equal n_withheld')
        if self.ci90_mae_clearstint_all[0] > self.ci90_mae_clearstint_all[1]:
            raise ValueError('ci90_mae_clearstint_all must be [low, high]')
        return self


# ---------------------------------------------------------------- live_predictor

class LivePrior(Strict):
    """What the live estimator starts from: the frozen forecast for this car, nothing else."""
    forecast_hash: HashStr
    event_id: EventId
    driver: DriverId
    compound: Compound
    degradation_rate: float = Field(description='pre-race forecast (s/lap per lap)')
    band90: Pair
    useful_laps_q10: Optional[float] = Field(default=None, ge=0.0)
    useful_laps_q50: Optional[float] = Field(default=None, ge=0.0)
    useful_laps_q90: Optional[float] = Field(default=None, ge=0.0)
    planned_plan: Optional[Annotated[str, Field(pattern=PLAN_RE)]] = None
    planned_pit_window: Optional[LapPair] = None
    basis: str = Field(min_length=1)

    @model_validator(mode='after')
    def _ordered(self) -> 'LivePrior':
        if self.band90[0] > self.band90[1]:
            raise ValueError('band90 must be [low, high]')
        _ordered(self.useful_laps_q10, self.useful_laps_q50, self.useful_laps_q90, names=('useful_laps_q10', 'useful_laps_q50', 'useful_laps_q90'))
        if self.planned_pit_window and self.planned_pit_window[0] > self.planned_pit_window[1]:
            raise ValueError('planned_pit_window must be [first, last]')
        return self


class TeamSensorChannels(Strict):
    """Private channels; only allowed under sensor_mode 'TEAM SENSOR'. Keys are wheel positions FL/FR/RL/RR."""
    tyre_surface_temp_c: Optional[dict[str, float]] = None
    tyre_carcass_temp_c: Optional[dict[str, float]] = None
    pressure_bar: Optional[dict[str, float]] = None
    tread_remaining_mm: Optional[dict[str, float]] = None


class LiveTyreState(Strict):
    """Roadmap 7.1. Every value is online-safe: computed from data with timestamp <= live_predictor.data_cutoff."""
    lap: int = Field(ge=0)
    timestamp: Timestamp
    compound: Compound
    tyre_age: int = Field(ge=0, description='laps on this set')
    state_regime: StateRegime
    corrected_pace_loss: float = Field(description='pace loss vs fresh-tyre reference after fuel, evolution and traffic correction (s/lap)')
    degradation_rate: float = Field(description='current posterior degradation rate (s/lap per lap)')
    thermal_stress_index: Unit
    performance_wear_index: Unit
    useful_laps_q10: float = Field(ge=0.0)
    useful_laps_q50: float = Field(ge=0.0)
    useful_laps_q90: float = Field(ge=0.0)
    cliff_probability_3_laps: Unit
    cliff_probability_5_laps: Unit
    trend_vs_pre_race: float = Field(description='fractional deviation of degradation_rate from the pre-race forecast (+0.31 = 31% faster)')
    confidence: Unit
    sensor_mode: SensorMode
    support_status: SupportStatus
    sensor_availability: dict[str, bool] = Field(default_factory=dict)
    source_latency: float = Field(ge=0.0, description='seconds between event time and receipt')
    missing_channels: list[str] = Field(default_factory=list)
    quality_status: QualityStatus
    confidence_effect: Optional[str] = None
    team_sensor: Optional[TeamSensorChannels] = None

    @model_validator(mode='after')
    def _rules(self) -> 'LiveTyreState':
        _ordered(self.useful_laps_q10, self.useful_laps_q50, self.useful_laps_q90, names=('useful_laps_q10', 'useful_laps_q50', 'useful_laps_q90'))
        if self.cliff_probability_3_laps > self.cliff_probability_5_laps + 1e-12:
            raise ValueError('cliff_probability_3_laps cannot exceed cliff_probability_5_laps')
        if self.sensor_mode == 'PUBLIC PROXY' and self.team_sensor is not None:
            raise ValueError("team_sensor channels are not allowed under sensor_mode 'PUBLIC PROXY'")
        unavailable = {k for k, v in self.sensor_availability.items() if not v}
        if not unavailable.issubset(set(self.missing_channels)):
            raise ValueError(f'channels marked unavailable must be listed in missing_channels: {sorted(unavailable - set(self.missing_channels))}')
        return self


class TyreSet(Strict):
    set_id: Optional[str] = None
    compound: Compound
    status: SetStatus
    age_laps: int = Field(default=0, ge=0)


class RejoinContext(Strict):
    """Phase 0: the observed gap structure; Phase 1: live rejoin and traffic estimation. Rival responses are never simulated."""
    basis: Literal['observed_gap_structure', 'live_rejoin_estimate']
    position_now: Optional[int] = Field(default=None, ge=1)
    projected_rejoin_position: Optional[int] = Field(default=None, ge=1)
    gap_ahead_s: Optional[float] = Field(default=None, ge=0.0)
    gap_behind_s: Optional[float] = Field(default=None, ge=0.0)
    cars_within_pit_loss: Optional[int] = Field(default=None, ge=0)
    traffic_density: Optional[Literal['clear', 'light', 'dense']] = None
    note: Optional[str] = None


class LiveRecommendation(Strict):
    """Roadmap 7.2. Ranked action; gain in seconds (positive = gain), q10 is the downside."""
    rank: int = Field(ge=1)
    lap: int = Field(ge=0)
    issued_at: Timestamp
    action: Action
    pit_window: Optional[LapPair] = None
    target_compound: Optional[Compound] = None
    target_set: Optional[TyreSet] = None
    expected_gain_median: float
    expected_gain_q10: float
    expected_gain_q90: float
    probability_of_gain: Unit
    rejoin_context: RejoinContext
    reasons: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    changed_since_last_update: bool
    change_reason: Optional[str] = None

    @model_validator(mode='after')
    def _rules(self) -> 'LiveRecommendation':
        _ordered(self.expected_gain_q10, self.expected_gain_median, self.expected_gain_q90, names=('expected_gain_q10', 'expected_gain_median', 'expected_gain_q90'))
        if self.action in ('PIT', 'PIT_NOW'):
            if self.pit_window is None:
                raise ValueError(f'action {self.action} requires a pit_window')
            if self.target_compound is None:
                raise ValueError(f'action {self.action} requires a target_compound')
        if self.pit_window and self.pit_window[0] > self.pit_window[1]:
            raise ValueError('pit_window must be [first, last]')
        if self.target_set and self.target_compound and self.target_set.compound != self.target_compound:
            raise ValueError('target_set.compound must equal target_compound')
        if self.changed_since_last_update and not self.change_reason:
            raise ValueError('a changed recommendation must carry a change_reason')
        return self


class DriverFeedbackEvent(Strict):
    """Roadmap 7.3. A timestamped observation with a confidence; it shifts regime probabilities, never seconds."""
    feedback_id: Optional[str] = None
    timestamp: Timestamp
    lap: int = Field(ge=0)
    axle: Axle
    corner_phase: CornerPhase
    symptom: Symptom
    severity: int = Field(ge=1, le=5)
    trend: Trend
    driver_confidence: Unit
    source: FeedbackSource
    raw_message: Optional[str] = None
    engineer_confirmed: bool


class LivePredictor(Strict):
    meta: Meta
    event_id: EventId
    driver: DriverId
    session: str = 'R'
    source: EventSource
    data_cutoff: Timestamp = Field(description='latest event timestamp the estimator has consumed')
    lap: int = Field(ge=0, description='last completed lap consumed')
    n_laps: int = Field(ge=1)
    uses_future_data: Literal[False] = False
    uses_post_race_reference: Literal[False] = False
    feedback_enabled: bool = True
    prior: LivePrior
    posterior: LiveTyreState
    recommendations: list[LiveRecommendation] = Field(default_factory=list)
    driver_feedback: list[DriverFeedbackEvent] = Field(default_factory=list)
    state_history: Optional[SidecarRef] = Field(default=None, description='per-lap LiveTyreState records')
    recommendation_history: Optional[SidecarRef] = None

    @model_validator(mode='after')
    def _online_safe(self) -> 'LivePredictor':
        if self.lap > self.n_laps:
            raise ValueError('lap cannot exceed n_laps')
        if self.posterior.lap > self.lap:
            raise ValueError('posterior.lap cannot be later than the last consumed lap')
        if not ts_le(self.posterior.timestamp, self.data_cutoff):
            raise ValueError('posterior.timestamp is later than data_cutoff (future data)')
        for r in self.recommendations:
            if not ts_le(r.issued_at, self.data_cutoff):
                raise ValueError(f'recommendation rank {r.rank} issued after data_cutoff')
            if r.lap > self.lap:
                raise ValueError(f'recommendation rank {r.rank} refers to lap {r.lap} beyond the last consumed lap {self.lap}')
        for f in self.driver_feedback:
            if not ts_le(f.timestamp, self.data_cutoff):
                raise ValueError('driver feedback timestamped after data_cutoff')
        ranks = [r.rank for r in self.recommendations]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError(f'recommendation ranks must be 1..n in order, got {ranks}')
        if self.prior.driver != self.driver or self.prior.event_id != self.event_id:
            raise ValueError('prior must describe the same event and driver')
        return self


# ---------------------------------------------------------------- ghost_strategy

class RaceReference(Strict):
    """Race-derived pace-loss reference (wording rule 9.2). The target driver is excluded for generalisation claims."""
    kind: Literal['race-derived pace-loss reference'] = 'race-derived pace-loss reference'
    by_compound: dict[Compound, float] = Field(min_length=1, description='observed race degradation (s/lap per lap)')
    by_compound_se: Optional[dict[Compound, float]] = None
    n_laps_used: Optional[int] = Field(default=None, ge=0)
    n_stints_used: Optional[int] = Field(default=None, ge=0)
    target_driver_excluded: bool
    source: str = Field(min_length=1)


class SupportFields(Strict):
    """Support fields on every Ghost Strategy result (roadmap 7.0)."""
    track_seen_during_training: bool
    driver_seen_during_training: bool
    weather_in_training_range: bool
    compound_support: bool
    season_support: bool
    circuit_generalisation: Optional[CircuitGeneralisation] = None
    overall_support_status: SupportStatus
    abstention_reason: Optional[str] = None

    @model_validator(mode='after')
    def _abstention(self) -> 'SupportFields':
        if self.overall_support_status == SUPPORT_WITHHELD and not self.abstention_reason:
            raise ValueError('a withheld forecast must state its abstention_reason')
        if self.overall_support_status == 'IN SUPPORT' and not (self.track_seen_during_training and self.weather_in_training_range and self.compound_support):
            raise ValueError("'IN SUPPORT' requires track seen, weather in range and compound support")
        return self


class Intervention(Strict):
    lap: int = Field(ge=1, description='lap on which the counterfactual diverges')
    from_compound: Compound
    to_compound: Compound
    set_status: SetStatus
    pit_stop: bool


class Stint(Strict):
    compound: Compound
    laps: int = Field(ge=1)
    set_status: SetStatus = 'new'


class Plan(Strict):
    label: Annotated[str, Field(pattern=PLAN_RE)]
    stints: list[Stint] = Field(min_length=1)
    pit_laps: list[int] = Field(default_factory=list, description='lap numbers on which the car pits (end of each stint but the last)')
    n_laps: int = Field(ge=1)

    @model_validator(mode='after')
    def _consistent(self) -> 'Plan':
        if sum(s.laps for s in self.stints) != self.n_laps:
            raise ValueError('stint laps must sum to n_laps')
        ends = []
        acc = 0
        for s in self.stints[:-1]:
            acc += s.laps
            ends.append(acc)
        if self.pit_laps != ends:
            raise ValueError(f'pit_laps {self.pit_laps} must equal cumulative stint ends {ends}')
        if '-'.join(s.compound[0] for s in self.stints) != self.label:
            raise ValueError('label must spell the stint compounds (e.g. M-H)')
        return self


class CounterfactualSummary(Strict):
    """Negative elapsed delta = the counterfactual is faster. Finish positions only in frozen_field mode, only as distributions."""
    elapsed_delta_median_s: float
    elapsed_delta_q10_s: float
    elapsed_delta_q90_s: float
    probability_of_gain: Unit
    oracle_regret_median_s: Optional[float] = None
    estimated_finish_position_median: Optional[float] = Field(default=None, ge=1)
    estimated_finish_position_q10: Optional[float] = Field(default=None, ge=1)
    estimated_finish_position_q90: Optional[float] = Field(default=None, ge=1)

    @model_validator(mode='after')
    def _ordered(self) -> 'CounterfactualSummary':
        _ordered(self.elapsed_delta_q10_s, self.elapsed_delta_median_s, self.elapsed_delta_q90_s, names=('elapsed_delta_q10_s', 'elapsed_delta_median_s', 'elapsed_delta_q90_s'))
        pos = (self.estimated_finish_position_q10, self.estimated_finish_position_median, self.estimated_finish_position_q90)
        if any(p is not None for p in pos) and not all(p is not None for p in pos):
            raise ValueError('finish position needs all three quantiles or none')
        _ordered(*pos, names=('estimated_finish_position_q10', 'estimated_finish_position_median', 'estimated_finish_position_q90'))
        return self

    @property
    def has_positions(self) -> bool:
        return self.estimated_finish_position_median is not None


class CounterfactualRef(Strict):
    scenario_id: str = Field(min_length=1)
    simulation_mode: SimulationMode
    summary: CounterfactualSummary


class GhostStrategy(Strict):
    meta: Meta
    mode: GhostMode
    event: str = Field(min_length=1)
    event_id: EventId
    driver: DriverId
    weather_context: WeatherContext
    forecast_snapshot_hash: HashStr
    race_reference: RaceReference
    counterfactual: Optional[CounterfactualRef] = None
    generalisation_status: SupportFields
    model_implied: Literal[True] = True
    live_estimator_disabled: Literal[True] = True
    claim_scope: str = Field(min_length=1)
    evidence_grade: EvidenceGrade
    ghost_replay: Optional[SidecarRef] = None

    @model_validator(mode='after')
    def _claims(self) -> 'GhostStrategy':
        if self.weather_context != 'actual_historical' and self.evidence_grade != 'model_implied_scenario':
            raise ValueError('only actual-weather audits count as evidence: evidence_grade must be model_implied_scenario')
        if self.mode == 'scenario_explorer' and self.evidence_grade != 'model_implied_scenario':
            raise ValueError('scenario_explorer results are model-implied scenarios, never evidence')
        if self.generalisation_status.overall_support_status == SUPPORT_WITHHELD and self.counterfactual is not None:
            raise ValueError('a withheld forecast cannot carry a counterfactual result')
        return self


# ---------------------------------------------------------------- counterfactuals[]

class Assumptions(Strict):
    rivals_follow_observed_trajectories: bool
    rival_strategy_response: Literal['none'] = 'none'
    safety_car_mode: SafetyCarMode
    driver_baseline_preserved: bool


class SafetyCarPeriod(Strict):
    kind: Literal['SC', 'VSC', 'RED']
    start_lap: int = Field(ge=1)
    end_lap: int = Field(ge=1)

    @model_validator(mode='after')
    def _span(self) -> 'SafetyCarPeriod':
        if self.end_lap < self.start_lap:
            raise ValueError('end_lap must be >= start_lap')
        return self


class CounterfactualValidation(Strict):
    identity_test: TestStatus = Field(description='the actual plan replayed as a counterfactual gives zero delta')
    future_leakage_test: TestStatus = Field(description='no input carries data after data_cutoff for pre-race quantities')
    target_driver_excluded: bool
    sealed_holdout: bool


class CounterfactualScenario(Strict):
    """One Race Twin scenario. Self-describing (schema_version, hashes, cutoff, split) so a list item can travel alone."""
    scenario_id: str = Field(min_length=1)
    schema_version: SemVer = SCHEMA_VERSION
    event_id: EventId
    driver_id: DriverId
    simulation_mode: SimulationMode
    availability_mode: SensorMode
    forecast_hash: HashStr
    model_hash: HashStr
    split_id: SplitId
    data_cutoff: Timestamp
    generated_at: Optional[Timestamp] = None
    git_sha: Optional[GitSha] = None
    intervention: Intervention
    actual_plan: Plan
    counterfactual_plan: Plan
    summary: CounterfactualSummary
    assumptions: Assumptions
    claim_scope: str = Field(min_length=1)
    track_position_simulated: bool
    rival_interactions_simulated: bool
    traffic_mode: TrafficMode
    safety_car_schedule: Union[SafetyCarScheduleMode, list[SafetyCarPeriod]] = Field(
        description="'historical_fixed' / 'observed_fixed' (periods fixed as observed) or the observed SC/VSC periods themselves")
    assets: dict[str, SidecarRef] = Field(default_factory=dict)
    validation: CounterfactualValidation
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def _mode_bounds(self) -> 'CounterfactualScenario':
        m = self.simulation_mode
        if m == 'tyre_only' and (self.track_position_simulated or self.rival_interactions_simulated or self.traffic_mode == 'frozen_field'):
            raise ValueError('tyre_only scenarios cannot simulate track position, rival interactions or frozen-field traffic')
        if m == 'fixed_context' and self.track_position_simulated:
            raise ValueError('fixed_context scenarios do not simulate track position')
        if self.summary.has_positions and not (m == 'frozen_field' and self.track_position_simulated):
            raise ValueError('finish positions are allowed only in frozen_field mode with track position simulated')
        if self.validation.sealed_holdout != (self.split_id == 'sealed_holdout'):
            raise ValueError("validation.sealed_holdout must be true exactly when split_id == 'sealed_holdout'")
        if self.actual_plan.n_laps != self.counterfactual_plan.n_laps:
            raise ValueError('actual and counterfactual plans must cover the same number of laps')
        if self.intervention.lap > self.actual_plan.n_laps:
            raise ValueError('intervention lap beyond race distance')
        return self


# ---------------------------------------------------------------- input_availability

class Channel(Strict):
    """Parameter policy 9.1: source, unit, sample rate, latency, availability, public or private, online-safe, missingness, quality, ablation."""
    source: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    sample_rate_hz: Optional[float] = Field(default=None, ge=0.0)
    latency_s: Optional[float] = Field(default=None, ge=0.0)
    available: bool
    visibility: Literal['public', 'private']
    online_safe: bool
    missingness: Optional[Unit] = Field(default=None, description='share of laps/samples missing in the current feed')
    quality_score: Optional[Unit] = None
    ablation_value: Optional[float] = Field(default=None, description='held-out improvement when the channel is included; null until measured')
    description: Optional[str] = None


class InputAvailability(Strict):
    meta: Meta
    sensor_mode: SensorMode
    event_id: Optional[EventId] = None
    channels: dict[str, Channel] = Field(min_length=1)
    missing_channels: list[str] = Field(default_factory=list)
    confidence_effect: str = Field(min_length=1)
    public_display_rules: list[str] = Field(default_factory=lambda: list(PUBLIC_DISPLAY_RULES))

    @model_validator(mode='after')
    def _rules(self) -> 'InputAvailability':
        missing = sorted(k for k, c in self.channels.items() if not c.available)
        if sorted(self.missing_channels) != missing:
            raise ValueError(f'missing_channels must list exactly the unavailable channels: {missing}')
        private_available = [k for k, c in self.channels.items() if c.visibility == 'private' and c.available]
        if self.sensor_mode == 'PUBLIC PROXY' and private_available:
            raise ValueError(f"'PUBLIC PROXY' cannot have private channels available: {private_available}")
        if self.sensor_mode == 'TEAM SENSOR' and not private_available:
            raise ValueError("'TEAM SENSOR' requires at least one private channel available")
        return self


# ---------------------------------------------------------------- driver_profile (Phase 2 stub)

class PopulationPrior(Strict):
    residual_mean_s_per_lap: float
    residual_sd_s_per_lap: Optional[float] = Field(default=None, ge=0.0)
    note: str = Field(min_length=1)


class DriverProfileEntry(Strict):
    driver: DriverId
    style_profile: dict[str, float] = Field(default_factory=dict)
    outcome_residual_s_per_lap: Optional[float] = None
    interval90: Optional[Pair] = None
    evidence_count: int = Field(ge=0)
    shrinkage: Optional[str] = None
    teammate_reference: Optional[DriverId] = None
    cross_track: bool = False


class DriverProfileBlock(Strict):
    meta: Meta
    status: Literal['stub', 'population_prior_only', 'available']
    population_prior: Optional[PopulationPrior] = None
    drivers: dict[str, DriverProfileEntry] = Field(default_factory=dict)
    note: Optional[str] = None

    @model_validator(mode='after')
    def _stub(self) -> 'DriverProfileBlock':
        if self.status == 'stub' and self.drivers:
            raise ValueError('a stub profile block carries no driver entries')
        for k, d in self.drivers.items():
            if d.driver != k:
                raise ValueError(f'drivers[{k}].driver is {d.driver}')
        return self


# ---------------------------------------------------------------- root

class LockV2(Strict):
    schema_version: SemVer = SCHEMA_VERSION
    shared: Shared
    pre_race_forecast: Optional[PreRaceForecast] = None
    validation: Optional[ValidationBlock] = None
    live_predictor: Optional[LivePredictor] = None
    ghost_strategy: Optional[GhostStrategy] = None
    counterfactuals: list[CounterfactualScenario] = Field(default_factory=list)
    input_availability: Optional[InputAvailability] = None
    driver_profile: Optional[DriverProfileBlock] = None
    extensions: dict[str, Any] = Field(default_factory=dict, description='free namespace for material not yet promoted to a stable block')

    def blocks(self) -> dict[str, BaseModel]:
        return {k: v for k, v in (('shared', self.shared), ('pre_race_forecast', self.pre_race_forecast), ('validation', self.validation),
                                  ('live_predictor', self.live_predictor), ('ghost_strategy', self.ghost_strategy),
                                  ('input_availability', self.input_availability), ('driver_profile', self.driver_profile)) if v is not None}

    @model_validator(mode='after')
    def _cross_block(self) -> 'LockV2':
        major = self.schema_version.split('.')[0]
        for name, block in self.blocks().items():
            if block.meta.schema_version.split('.')[0] != major:
                raise ValueError(f'{name}.meta.schema_version {block.meta.schema_version} is not major version {major}')
        fh = self.shared.forecast_hash
        if self.pre_race_forecast is not None:
            computed = compute_forecast_hash(self.pre_race_forecast)
            if computed != fh:
                raise ValueError(f'shared.forecast_hash {fh[:19]}... does not match the pre_race_forecast block ({computed[:19]}...)')
        if self.ghost_strategy is not None and self.ghost_strategy.forecast_snapshot_hash != fh:
            raise ValueError('ghost_strategy.forecast_snapshot_hash differs from shared.forecast_hash')
        if self.live_predictor is not None and self.live_predictor.prior.forecast_hash != fh:
            raise ValueError('live_predictor.prior.forecast_hash differs from shared.forecast_hash')
        ids = [c.scenario_id for c in self.counterfactuals]
        if len(ids) != len(set(ids)):
            raise ValueError('counterfactual scenario_ids must be unique')
        for c in self.counterfactuals:
            if c.forecast_hash != fh:
                raise ValueError(f'counterfactual {c.scenario_id}: forecast_hash differs from shared.forecast_hash')
        if self.ghost_strategy is not None and self.ghost_strategy.counterfactual is not None and self.counterfactuals:
            ref = self.ghost_strategy.counterfactual
            match = [c for c in self.counterfactuals if c.scenario_id == ref.scenario_id]
            if not match:
                raise ValueError(f'ghost_strategy.counterfactual.scenario_id {ref.scenario_id!r} is not in counterfactuals[]')
            c = match[0]
            if c.simulation_mode != ref.simulation_mode or c.summary != ref.summary:
                raise ValueError(f'ghost_strategy.counterfactual disagrees with counterfactuals[{ref.scenario_id!r}] (map must equal numbers)')
        if self.live_predictor is not None and self.input_availability is not None and self.live_predictor.posterior.sensor_mode != self.input_availability.sensor_mode:
            raise ValueError('live_predictor.posterior.sensor_mode differs from input_availability.sensor_mode')
        return self


def load_lock(path: str | Path) -> LockV2:
    with open(path, 'r', encoding='utf-8') as f:
        return LockV2.model_validate(json.load(f))


def json_schema() -> dict[str, Any]:
    return LockV2.model_json_schema()


def export_schema(path: str | Path = SCHEMA_JSON_PATH) -> Path:
    from shared.lockio import atomic_write_json
    return atomic_write_json(path, json_schema(), indent=1, sort_keys=True)


def format_errors(err: ValidationError) -> str:
    lines = []
    for e in err.errors():
        loc = '.'.join(str(p) for p in e['loc']) or '<root>'
        lines.append(f'  {loc}: {e["msg"]}')
    return '\n'.join(lines)


__all__ = ['SCHEMA_VERSION', 'SCHEMA_JSON_PATH', 'LockV2', 'Meta', 'SidecarRef', 'Shared', 'ForecastSnapshot', 'SupportDefinition', 'PreRaceForecast',
           'EventForecast', 'CompoundForecast', 'SecondOpinion', 'PreRacePlan', 'PlanAlternative', 'ValidationBlock', 'LivePredictor', 'LivePrior',
           'LiveTyreState', 'LiveRecommendation', 'DriverFeedbackEvent', 'TyreSet', 'RejoinContext', 'TeamSensorChannels', 'GhostStrategy',
           'RaceReference', 'SupportFields', 'CounterfactualRef', 'CounterfactualScenario', 'CounterfactualSummary', 'CounterfactualValidation',
           'Intervention', 'Plan', 'Stint', 'Assumptions', 'SafetyCarPeriod', 'InputAvailability', 'Channel', 'DriverProfileBlock',
           'DriverProfileEntry', 'PopulationPrior', 'compute_forecast_hash', 'load_lock', 'json_schema', 'export_schema', 'format_errors', 'parse_ts', 'ts_le',
           'Compound', 'SensorMode', 'SupportStatus', 'StateRegime', 'QualityStatus', 'GhostMode', 'WeatherContext', 'SimulationMode', 'SplitId',
           'Action', 'SetStatus', 'Axle', 'CornerPhase', 'Symptom', 'Trend', 'FeedbackSource', 'EventSource', 'TrafficMode', 'SafetyCarScheduleMode', 'CLAIM_SCOPE_BY_MODE',
           'PUBLIC_DISPLAY_RULES', 'DEFAULT_UNITS', 'SUPPORT_WITHHELD']

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'export'
    if cmd == 'export':
        out = export_schema(sys.argv[2] if len(sys.argv) > 2 else SCHEMA_JSON_PATH)
        print(f'wrote {out}')
    elif cmd == 'validate':
        try:
            lock = load_lock(sys.argv[2])
        except ValidationError as e:
            print(f'INVALID {sys.argv[2]}\n{format_errors(e)}')
            sys.exit(2)
        print(f'valid: schema {lock.schema_version}, forecast {lock.shared.forecast_hash[:19]}..., blocks {sorted(lock.blocks())}')
    else:
        print(__doc__)
        sys.exit(1)
