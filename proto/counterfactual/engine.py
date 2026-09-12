"""The single-car counterfactual (roadmap v5 task 0.4): Race Twin scenario compiler.

Decomposition of every actual lap:   Y = B + T_actual + P_actual + I_actual + e
    T = compound offset + reference slope x tyre age        (offsets: lock strategy[event].offsets, SOFT = 0)
    P = pit in-lap / out-lap / warm-up effects                (measured per stop, field-relative; racedata.py)
    I = traffic effect = beta_traffic x traffic share         (beta measured on the race; racedata.traffic_beta)
    B = everything else (driver, car, fuel, evolution, noise) = Y - T - P - I
Counterfactual lap:                   Y_cf = B + T_cf + P_cf + I_cf
so that                               Y_cf - Y = (T_cf - T_actual) + (P_cf - P_actual) + (I_cf - I_actual)
B cancels lap by lap: a contaminated actual lap (pit lap, SC/VSC lap, out-lap, missing row) is reconstructed from
its baseline (Y minus the measured stop loss, plus the counterfactual terms), never copied as-is. In single-car
modes the counterfactual car meets the actual car's traffic on every lap (paired replay), so I_cf = I_actual and the
traffic term is reported but cancels in the delta.

Modes
    tyre_only      the tyre-time delta as if the race were green throughout: tyre terms on every lap plus the
                   standardised pit events at green cost; no traffic term; no SC interaction (a stop under a red
                   flag is still free: that is a fact of the schedule, not a context effect).
    fixed_context  the observed race context held fixed: SC/VSC/red-flag laps are frozen (no tyre pace delta; tyre
                   age still advances), a stop whose in-lap or out-lap falls on an SC/VSC lap pays SC_FACTOR of the
                   green transit loss, a restart warm-up residual is applied on the first green lap after a frozen
                   block, contaminated laps keep their measured traffic contribution.
    frozen_field   NotImplementedError: rivals, following loss and position distributions are Workstream 5's
                   interaction/ package (Phase 1); this engine never claims positions.

Uncertainty: whole curves and parameters are sampled (never per-lap noise): reference slopes from their standard
errors (or from the 90% band width when a curve has no SE), compound offsets (sd OFFSET_SD), pit transit loss,
stationary time, out-lap penalty and warm-up residual (pitmodel.py). Every per-lap delta is linear in these
parameters, so a scenario is one coefficient matrix (laps x parameters) times a shared sample matrix; that is what
keeps a scenario well under 250 ms and makes a driver x lap x compound lattice cheap.

Standardised pit event: with `standardised_pit_event=True` (default) every stop, including the driver's own actual
stops, is booked at the standardised distribution; replaying the actual plan then yields a cumulative delta equal to
the stop replacement (standardised minus measured), reported as `stop_replacement_delta_s`. With it disabled, the
driver's own measured stop is moved verbatim and replaying the actual plan gives exactly zero.

The reference slope is post-race material (race-derived pace-loss reference, wording rule 9.2); by default it is
refitted with the target driver excluded. `curve_source='pre_race_forecast'` uses the frozen provider A curve
instead (model-implied, no race data). Either way the pre-race provenance is checked for leakage.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from counterfactual import PROTO
from counterfactual.provider import ProviderA, CurveDistribution, assert_pre_race, event_name, Z95
from counterfactual.racedata import RaceData, DriverLaps, StintRec, load_race, set_status_from_age, FROZEN_LABELS, COMPS
from counterfactual.pitmodel import PitEventModel, season_pool, SC_FACTOR_DEFAULT
from shared.lockio import content_hash

ENGINE_VERSION = 'counterfactual_engine_v1'
MODES = ('tyre_only', 'fixed_context', 'frozen_field')
CONTINUATIONS = ('as_actual', 'one_stop', 'two_stop')
SET_AGE = {'new': 1, 'scrubbed': 3, 'used': 6}      # stated assumptions: laps already on the set when fitted
OFFSET_SD = 0.15                                    # s, sd of a compound pace offset (practice medians over ~22 drivers)
MAX_SHIFT = 10                                      # 'auto' replaces the nearest actual stop within this many laps
MIN_STINT = 6                                       # strategy2.MIN_STINT, used by the two_stop optimiser
THIN_REFERENCE_LAPS = 50                            # a compound slope resting on fewer kept race laps is flagged in the warnings
# Default-curve decision (lead, 12 Sep): Historical Audit replays on the race-derived reference with the target driver
# excluded, labelled as below; Scenario Explorer uses the pre-race forecast only (curve_source='pre_race_forecast').
LODO_REFERENCE_LABEL = 'leave-one-driver-out Sunday reference'
IDENTITY_TOL = 1e-9
P_SLOPE = {'SOFT': 0, 'MEDIUM': 1, 'HARD': 2}
P_OFF = {'SOFT': 3, 'MEDIUM': 4, 'HARD': 5}
P_TRANSIT, P_STAT = 6, 7
P_PEN = {'SOFT': 8, 'MEDIUM': 9, 'HARD': 10}
P_WARM = {'SOFT': 11, 'MEDIUM': 12, 'HARD': 13}
N_PARAMS = 14
PARAM_NAMES = ['slope_SOFT', 'slope_MEDIUM', 'slope_HARD', 'offset_SOFT', 'offset_MEDIUM', 'offset_HARD', 'pit_transit', 'pit_stationary',
               'outlap_pen_SOFT', 'outlap_pen_MEDIUM', 'outlap_pen_HARD', 'warmup_SOFT', 'warmup_MEDIUM', 'warmup_HARD']
LAP_COLUMNS = ['lap', 'actual_lap_time', 'cf_lap_time_mean', 'cf_lap_time_q10', 'cf_lap_time_q90', 'lap_delta', 'cumulative_delta',
               'actual_compound', 'cf_compound', 'actual_tyre_age', 'cf_tyre_age', 'actual_traffic_effect', 'cf_traffic_effect',
               'pit_state', 'track_status', 'actual_position', 'cf_position_median', 'cf_position_q10', 'cf_position_q90']
EXTRA_COLUMNS = ['actual_lap_inferred', 'lap_delta_q10', 'lap_delta_q90', 'cumulative_delta_q10', 'cumulative_delta_q90', 'delta_tyre_mean', 'delta_pit_mean',
                 'actual_pit_state', 'frozen']


def _git_sha() -> str:
    try:
        out = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=PROTO, capture_output=True, text=True, timeout=5)
        sha = out.stdout.strip()
        if out.returncode == 0 and sha:
            return sha
    except Exception:
        pass
    return ''


_GIT_SHA = _git_sha()


class FrozenFieldNotAvailable(NotImplementedError):
    pass


# ---------------------------------------------------------------- scenario specification

@dataclass
class ScenarioSpec:
    event: str
    driver: str
    lap: int
    to_compound: str
    set_status: str = 'new'
    mode: str = 'fixed_context'
    continuation: str = 'as_actual'
    replace_stop: str | int = 'auto'            # 'auto' | 'none' | 1-based index of the actual stop to move
    curve_source: str = 'race_reference'       # 'race_reference' | 'pre_race_forecast'
    standardised_pit_event: bool = True
    exclude_target_driver: bool = True
    sc_factor: float | str = SC_FACTOR_DEFAULT
    set_age: Optional[int] = None              # overrides SET_AGE[set_status]
    n_samples: int = 500
    seed: int = 2026

    def __post_init__(self) -> None:
        self.to_compound = self.to_compound.upper()
        self.set_status = self.set_status.lower()
        if self.mode not in MODES:
            raise ValueError(f'mode must be one of {MODES}, got {self.mode!r}')
        if self.mode == 'frozen_field':
            raise FrozenFieldNotAvailable("simulation_mode 'frozen_field' is not available in this engine: rival trajectories, following loss and "
                                          "finish-position distributions are Workstream 5's interaction/ package (Phase 1). Use 'fixed_context' "
                                          "(observed context held fixed) or 'tyre_only'; neither claims track position.")
        if self.continuation not in CONTINUATIONS:
            raise ValueError(f'continuation must be one of {CONTINUATIONS}')
        if self.set_status not in SET_AGE:
            raise ValueError(f"set_status must be one of {tuple(SET_AGE)}")
        if self.to_compound not in COMPS:
            raise ValueError(f'to_compound must be a dry slick compound {COMPS} (no validated wet model)')
        if self.curve_source not in ('race_reference', 'pre_race_forecast'):
            raise ValueError("curve_source must be 'race_reference' or 'pre_race_forecast'")

    @property
    def start_age(self) -> int:
        return int(self.set_age) if self.set_age is not None else SET_AGE[self.set_status]

    @property
    def scenario_id(self) -> str:
        return f'{self.event.lower()}_{self.driver.lower()}_lap{self.lap}_to_{self.to_compound.lower()}_{self.set_status}_{self.mode}'


@dataclass
class CfStint:
    start_lap: int
    end_lap: int
    compound: str
    start_age: int
    set_status: str
    from_actual: Optional[int] = None        # index into DriverLaps.stints when the stint is an unchanged actual stint

    @property
    def n_laps(self) -> int:
        return self.end_lap - self.start_lap + 1


@dataclass
class CfStop:
    in_lap: int
    out_lap: int
    to_compound: str
    coincident_actual: Optional[int]         # index into DriverLaps.stops when the actual car stopped on the same in-lap
    free: bool


@dataclass
class CounterfactualResult:
    spec: ScenarioSpec
    table: pd.DataFrame
    scenario: dict[str, Any]                 # validates against schemas.lock_v2.CounterfactualScenario
    engine: dict[str, Any]                   # diagnostics and provenance beyond the schema
    events_actual: list[dict[str, Any]]
    events_cf: list[dict[str, Any]]
    deltas: np.ndarray                       # (n_laps, n_samples) sampled per-lap deltas
    timing_ms: float

    @property
    def cumulative_delta_mean(self) -> float:
        return float(self.table['cumulative_delta'].iloc[-1])

    @property
    def summary(self) -> dict[str, Any]:
        return self.scenario['summary']


# ---------------------------------------------------------------- the engine

class CounterfactualEngine:
    def __init__(self, provider: Optional[ProviderA] = None, feat_dir: Path | None = None, pool: Optional[dict[str, Any]] = None,
                 use_pool: bool = True, allow_sealed: bool = False):
        self.provider = provider or ProviderA()
        self.feat_dir = Path(feat_dir) if feat_dir else PROTO / 'feat'
        self._pool = pool
        self.use_pool = use_pool
        self.allow_sealed = allow_sealed
        self._pit: dict[tuple[str, Any], PitEventModel] = {}
        self._samples: dict[tuple[Any, ...], np.ndarray] = {}
        self._sealed: Optional[set[str]] = None
        self._event_ids: dict[str, str] = {}
        self.lock = self.provider.lock
        self.override_curves: Optional[dict[str, dict[str, float]]] = None    # tests: {compound: {slope, sd}} replaces the curve source

    # ---------------------------------------------------------------- cached inputs
    def race(self, event: str) -> RaceData:
        return load_race(event, str(self.feat_dir / f'{event}_R.csv'))

    def pool(self) -> dict[str, Any]:
        if self._pool is None:
            self._pool = season_pool(self.feat_dir) if self.use_pool else dict(stops=[], outlaps=[])
        return self._pool

    def pit_model(self, event: str, sc_factor: float | str = SC_FACTOR_DEFAULT) -> PitEventModel:
        key = (event, sc_factor)
        if key not in self._pit:
            self._pit[key] = PitEventModel.build(self.race(event), sc_factor=sc_factor, pool=self.pool(), use_pool=self.use_pool)
        return self._pit[key]

    def offsets(self, event: str) -> tuple[dict[str, float], dict[str, str]]:
        strat = self.lock.get('strategy', {}).get(event)
        if strat is None:
            raise KeyError(f'no strategy block (compound offsets) for {event} in the v1 lock')
        return {c: float(v) for c, v in strat['offsets'].items()}, dict(strat.get('offsets_source', {}))

    def curves(self, event: str, driver: str, source: str, exclude_target: bool) -> dict[str, Any]:
        """Per compound: slope, sd and provenance. race_reference -> refit (target driver excluded) with the lock's
        all-driver values as the check; pre_race_forecast -> provider A frozen curve (pre-race guard applied)."""
        R = self.race(event)
        out: dict[str, Any] = dict(source=source, by_compound={}, uses_post_race_reference=source == 'race_reference', target_driver_excluded=False)
        if self.override_curves is not None:
            out['by_compound'] = {c: dict(slope=float(v['slope']), sd=float(v.get('sd', 0.0)), sd_from='override') for c, v in self.override_curves.items()}
            out.update(source='override', label='TEST OVERRIDE curves', target_driver_excluded=True, uses_post_race_reference=False)
            return out
        if source == 'race_reference':
            ref = R.reference_slopes(driver if exclude_target else None)
            lock_ref = {}
            for c in COMPS:
                try:
                    lc = self.provider.reference_curve_post_race(event, c, (1, 2))
                    lock_ref[c] = dict(slope=lc.slope, se=lc.slope_se)
                except KeyError:
                    pass
            prep = R._prep if not exclude_target else R._prep[R._prep['Driver'] != driver]
            counts = prep['Compound'].value_counts().to_dict()
            for c, s in ref['slopes'].items():
                out['by_compound'][c] = dict(slope=float(s), sd=float(ref['se'][c]) if np.isfinite(ref['se'][c]) else 0.0, sd_from='standard_error',
                                             n_laps=int(counts.get(c, 0)), lock_all_driver=lock_ref.get(c))
            out.update(n_laps_used=ref['n_laps'], n_stints_used=ref['n_stints'], resid_sd=ref['resid_sd'], target_driver_excluded=bool(exclude_target),
                       label=(LODO_REFERENCE_LABEL if exclude_target else 'race-derived pace-loss reference (post-race), all drivers, stint fixed effects + per-compound slope on tyre age'),
                       intended_page='historical_audit')
        else:
            for c in self.provider.available_compounds(event):
                cv = assert_pre_race(self.provider.predict_curve(event, driver, c, None, (1, 2)))
                out['by_compound'][c] = dict(slope=cv.slope, sd=cv.sd_from_band, sd_from='band90_width', band=list(cv.band), issued=cv.provenance.get('issued'),
                                             forecast_hash=cv.provenance.get('forecast_hash'))
            out.update(target_driver_excluded=True, label='frozen pre-race forecast (provider A), model-implied; no race data', intended_page='scenario_explorer')
        return out

    @property
    def sealed_events(self) -> set[str]:
        if self._sealed is None:
            p = PROTO / 'evaluation' / 'holdout' / 'sealed_holdout_manifest.json'
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    self._sealed = set(json.load(f).get('race_ids', []))
            except (OSError, json.JSONDecodeError):
                self._sealed = set()
        return self._sealed

    def event_id(self, event: str) -> str:
        if event in self._event_ids:
            return self._event_ids[event]
        v2ev = None
        try:
            with open(self.provider.lock_v2_path, 'r', encoding='utf-8') as f:
                v2ev = json.load(f)['pre_race_forecast']['events'].get(event)
        except Exception:
            v2ev = None
        eid = v2ev['event_id'] if (v2ev and v2ev.get('event_id')) else f"{self.provider.lock_v2_meta.get('season') or 2026}_{event}"
        self._event_ids[event] = eid
        return eid

    def support_check(self, R: RaceData, plan: list[CfStint]) -> dict[str, Any]:
        """The reference is linear in age with no cliff term: a counterfactual stint longer than any stint driven on that
        compound in this race is outside the evidence and is flagged (warning + in_support=False), never silently scored."""
        longest = R.max_stint_laps()
        beyond = [dict(compound=s.compound, laps=s.n_laps, longest_observed=longest.get(s.compound, 0)) for s in plan if s.n_laps > longest.get(s.compound, 0)]
        return dict(in_support=not beyond, stints_beyond_support=beyond, longest_observed_stint_laps=longest,
                    rule='counterfactual stint length <= longest stint observed on that compound in this race (the linear reference has no cliff term)')

    # ---------------------------------------------------------------- plan construction
    def build_plan(self, dl: DriverLaps, spec: ScenarioSpec) -> tuple[list[CfStint], dict[str, Any]]:
        L, n = int(spec.lap), dl.n
        if not (1 <= L <= n - 1):
            raise ValueError(f'intervention lap must be between 1 and {n - 1} (driver completed {n} laps)')
        stints = dl.stints
        # which actual stop is replaced
        k: Optional[int] = None
        if isinstance(spec.replace_stop, int) or (isinstance(spec.replace_stop, str) and spec.replace_stop.isdigit()):
            k = int(spec.replace_stop) - 1
            if not (0 <= k < len(dl.stops)):
                raise ValueError(f'replace_stop {spec.replace_stop}: the driver made {len(dl.stops)} stop(s)')
        elif spec.replace_stop == 'auto':
            cands = [(abs(s.in_lap - L), i) for i, s in enumerate(dl.stops) if not s.free]
            if cands:
                dist, i = min(cands)
                if dist <= MAX_SHIFT:
                    k = i
        elif spec.replace_stop != 'none':
            raise ValueError("replace_stop must be 'auto', 'none' or a 1-based stop index")
        info: dict[str, Any] = dict(replaced_stop=None if k is None else dict(index=k + 1, in_lap=dl.stops[k].in_lap, to_compound=dl.stops[k].to_compound, free=dl.stops[k].free))
        cf: list[CfStint] = []
        if k is not None:
            head = stints[:k + 1]                       # stints up to and including the one that ended at the replaced stop
            for s in head[:-1]:
                if s.end_lap >= L:
                    raise ValueError(f'intervention lap {L} lies before the end of an earlier stint (lap {s.end_lap}); pick replace_stop explicitly')
                cf.append(CfStint(s.start_lap, s.end_lap, s.compound, s.start_age, s.set_status, from_actual=s.index))
            last = head[-1]
            if L < last.start_lap:
                raise ValueError(f'intervention lap {L} is before the start of the stint that ended at the replaced stop (lap {last.start_lap})')
            unchanged = L == last.end_lap
            cf.append(CfStint(last.start_lap, L, last.compound, last.start_age, last.set_status, from_actual=last.index if unchanged else None))
            later = stints[k + 2:]
        else:
            cur = next(s for s in stints if s.start_lap <= L <= s.end_lap)
            for s in stints:
                if s.end_lap < L:
                    cf.append(CfStint(s.start_lap, s.end_lap, s.compound, s.start_age, s.set_status, from_actual=s.index))
            unchanged = L == cur.end_lap
            cf.append(CfStint(cur.start_lap, L, cur.compound, cur.start_age, cur.set_status, from_actual=cur.index if unchanged else None))
            later = [s for s in stints if s.start_lap > L and s is not cur]
        later = [s for s in later if s.start_lap > L + 1]
        new = CfStint(L + 1, n, spec.to_compound, spec.start_age, spec.set_status if spec.set_age is None else set_status_from_age(spec.start_age), from_actual=None)
        if spec.continuation == 'one_stop':
            later = []
        elif spec.continuation == 'two_stop':
            later = later[:1]
        if later:
            new.end_lap = later[0].start_lap - 1
        cf.append(new)
        for s in later:
            cf.append(CfStint(s.start_lap, n if s is later[-1] else s.end_lap, s.compound, s.start_age, s.set_status, from_actual=s.index))
        if spec.continuation == 'two_stop' and not later:
            second = self._optimise_second_stop(dl, spec, new)
            if second is not None:
                new.end_lap = second['pit_lap']
                cf.append(CfStint(second['pit_lap'] + 1, n, second['compound'], 1, 'new', from_actual=None))
                info['second_stop_optimised'] = second
        # an unchanged copy of the actual stint keeps the actual identity (ages taken from the data)
        for s, a in zip(cf, stints):
            if s.from_actual is None and s.start_lap == a.start_lap and s.end_lap == a.end_lap and s.compound == a.compound and s.start_age == a.start_age:
                s.from_actual = a.index
        if any(s.n_laps < 1 for s in cf) or cf[0].start_lap != 1 or cf[-1].end_lap != n or any(b.start_lap != a.end_lap + 1 for a, b in zip(cf, cf[1:])):
            raise ValueError(f'internal: inconsistent counterfactual plan {cf}')
        return cf, info

    def _optimise_second_stop(self, dl: DriverLaps, spec: ScenarioSpec, new: CfStint) -> Optional[dict[str, Any]]:
        curves = self.curves(spec.event, spec.driver, spec.curve_source, spec.exclude_target_driver)['by_compound']
        offs, _ = self.offsets(spec.event)
        pm = self.pit_model(spec.event, spec.sc_factor)
        n = dl.n
        best = None
        for c2 in COMPS:
            if c2 not in curves or c2 not in offs:
                continue
            for a in range(new.start_lap + MIN_STINT - 1, n - MIN_STINT + 1):
                ages1 = np.arange(new.start_lap, a + 1) - new.start_lap + new.start_age
                ages2 = np.arange(1, n - a + 1)
                cost = (offs[new.compound] * len(ages1) + curves[new.compound]['slope'] * ages1.sum() + offs[c2] * len(ages2) + curves[c2]['slope'] * ages2.sum()
                        + pm.total_green_median + pm.outlap_pen.get(c2, 0.0) + pm.warmup.get(c2, 0.0))
                if best is None or cost < best[0]:
                    best = (cost, a, c2)
        if best is None:
            return None
        return dict(pit_lap=int(best[1]), compound=best[2], model_time_s=float(best[0]), rule='min over compound and lap of tyre time + standardised green stop, stints >= 6 laps')

    @staticmethod
    def actual_plan_dict(dl: DriverLaps) -> dict[str, Any]:
        return _plan_dict([CfStint(s.start_lap, s.end_lap, s.compound, s.start_age, s.set_status, s.index) for s in dl.stints], dl.n)

    # ---------------------------------------------------------------- samples
    def samples(self, event: str, spec: ScenarioSpec, curves: dict[str, Any], offs: dict[str, float], pm: PitEventModel) -> tuple[np.ndarray, np.ndarray]:
        """(theta_mean (14,), Theta (n_samples, 14)); cached per (event, curve source, settings, seed) so a lattice shares one draw."""
        key = (event, spec.driver if (spec.curve_source == 'race_reference' and spec.exclude_target_driver) else None, spec.curve_source, spec.sc_factor, spec.n_samples, spec.seed,
               None if self.override_curves is None else tuple(sorted((c, v['slope'], v.get('sd', 0.0)) for c, v in self.override_curves.items())))
        mean = np.zeros(N_PARAMS)
        sd = np.zeros(N_PARAMS)
        for c in COMPS:
            cv = curves['by_compound'].get(c)
            if cv is not None:
                mean[P_SLOPE[c]], sd[P_SLOPE[c]] = cv['slope'], cv['sd']
            if c in offs:
                mean[P_OFF[c]], sd[P_OFF[c]] = offs[c], (0.0 if c == 'SOFT' else OFFSET_SD)
            mean[P_PEN[c]], sd[P_PEN[c]] = pm.outlap_pen.get(c, 0.0), pm.outlap_pen_sd.get(c, 0.0)
            mean[P_WARM[c]], sd[P_WARM[c]] = pm.warmup.get(c, 0.0), pm.warmup_sd.get(c, 0.0)
        mean[P_TRANSIT], sd[P_TRANSIT] = pm.transit_med, pm.transit_sd
        mean[P_STAT], sd[P_STAT] = pm.stationary_med, 0.0
        if key not in self._samples:
            rng = np.random.default_rng(spec.seed)
            z = rng.standard_normal((spec.n_samples, N_PARAMS))
            theta = mean[None, :] + sd[None, :] * z
            theta[:, P_STAT] = pm.stationary_samples(rng, spec.n_samples)
            self._samples[key] = theta
        return mean, self._samples[key]

    # ---------------------------------------------------------------- compile
    def compile(self, spec: ScenarioSpec, build_table: bool = True, run_identity_check: bool = True) -> CounterfactualResult:
        t0 = time.perf_counter()
        event_id = self.event_id(spec.event)
        if event_id in self.sealed_events and not self.allow_sealed:
            raise PermissionError(f'{event_id} is in the sealed holdout; per-race counterfactuals are the blind evaluator\'s until freeze')
        R = self.race(spec.event)
        dl = R.driver(spec.driver)
        pm = self.pit_model(spec.event, spec.sc_factor)
        curves = self.curves(spec.event, spec.driver, spec.curve_source, spec.exclude_target_driver)
        offs, offs_src = self.offsets(spec.event)
        plan, plan_info = self.build_plan(dl, spec)
        warnings: list[str] = list(pm.warnings)
        for s in plan:
            for c in (s.compound,):
                if c not in curves['by_compound']:
                    raise KeyError(f'no {spec.curve_source} curve for {c} at {spec.event}; available {sorted(curves["by_compound"])}')
                if c not in offs:
                    raise KeyError(f'no compound offset for {c} at {spec.event}')
        if dl.retired:
            warnings.append(f'{spec.driver} completed {dl.n} of {R.n_laps} laps (retired); the counterfactual covers the completed laps only')
        support = self.support_check(R, plan)
        for c in sorted({s.compound for s in plan if s.from_actual is None}):
            cv = curves['by_compound'][c]
            if cv.get('n_laps') is not None and cv['n_laps'] < THIN_REFERENCE_LAPS:
                warnings.append(f'thin reference: the {c} slope rests on {cv["n_laps"]} race laps (SE {cv["sd"]:.4f} s/lap per lap); the sampled band carries that uncertainty')
        for b in support['stints_beyond_support']:
            warnings.append(f"OUT OF SUPPORT: counterfactual {b['compound']} stint of {b['laps']} laps exceeds the longest {b['compound']} stint driven in this race "
                            f"({b['longest_observed']} laps); the linear reference has no cliff term, so this delta is extrapolated")
        coef, const, cf_comp, cf_age, cf_state, act_state, frozen, cf_stops, notes = self._assemble(dl, plan, spec, pm)
        warnings.extend(notes)
        if any(s.free for s in cf_stops if s.coincident_actual is None):
            warnings.append('the counterfactual stop falls on a red-flag lap and is free (tyre change during the stoppage), as every car\'s was')
        theta_mean, Theta = self.samples(spec.event, spec, curves, offs, pm)
        D = coef @ Theta.T + const[:, None]                     # (n_laps, n_samples)
        theta_bar = Theta.mean(axis=0)                          # sample means: the mean path is linear, so it sums exactly
        mean_path = coef @ theta_bar + const
        tyre_part = coef[:, :6] @ theta_bar[:6]
        pit_part = mean_path - tyre_part
        totals = D.sum(axis=0)
        q10, q50, q90 = (float(v) for v in np.quantile(totals, [0.1, 0.5, 0.9]))
        p_gain = float(np.mean(totals < 0.0))
        # stop replacement: the standardised event on the actual stops minus their measured loss (mean over samples)
        stop_replacement = float(sum(v for v in notes_replacement(self, dl, spec, pm, theta_bar)))
        identity = 'not_run'
        identity_delta = None
        if run_identity_check:
            identity, identity_delta = self._identity_check(dl, spec, pm, curves, offs)
        leakage = self._leakage_check(spec, curves)
        n = dl.n
        table = None
        if build_table:
            table = self._table(dl, D, mean_path, tyre_part, pit_part, cf_comp, cf_age, cf_state, act_state, frozen, R, traffic_reported=spec.mode == 'fixed_context')
        new_stint = next(s for s in plan if s.start_lap == spec.lap + 1)
        # events (conservation test)
        events_cf = _stop_events(cf_stops, n)
        events_actual = _stop_events([CfStop(s.in_lap, s.out_lap, s.to_compound, i, s.free) for i, s in enumerate(dl.stops)], n)
        lap_from = dl.compound[spec.lap - 1]
        traffic_mode = 'paired_replay' if spec.mode == 'fixed_context' else 'clean_air'      # schema TrafficMode vocabulary
        sc_mode = 'fixed_observed_schedule' if spec.mode == 'fixed_context' else 'none'      # whether the observed periods act on the delta
        schedule = R.safety_car_schedule()       # the observed SC/VSC/RED periods in both modes; tyre_only reports them but does not apply them
        claim = _claim_scope(spec.mode)
        model_hash = content_hash(dict(engine=ENGINE_VERSION, provider=self.provider.model_version, curve_source=spec.curve_source, mode=spec.mode,
                                       sc_factor=pm.sc_factor, stationary_q=list(pm.stationary_q), offset_sd=OFFSET_SD, set_age=SET_AGE, n_samples=spec.n_samples, seed=spec.seed,
                                       standardised_pit_event=spec.standardised_pit_event, exclude_target_driver=spec.exclude_target_driver))
        data_cutoff = self.provider.lock_v2_meta.get('data_cutoff') or self.lock.get('generated_at')
        git_sha = _GIT_SHA or self.provider.lock_v2_meta.get('git_sha') or '0000000'
        split = 'sealed_holdout' if event_id in self.sealed_events else 'development_pool'
        scenario = dict(
            scenario_id=spec.scenario_id, schema_version='2.0.0', event_id=event_id, driver_id=spec.driver, simulation_mode=spec.mode, availability_mode='PUBLIC PROXY',
            forecast_hash=self.provider.forecast_hash, model_hash=model_hash, split_id=split, data_cutoff=data_cutoff,
            generated_at=dt.datetime.now().isoformat(timespec='seconds'), git_sha=git_sha,
            intervention=dict(lap=int(spec.lap), from_compound=lap_from, to_compound=spec.to_compound, set_status=new_stint.set_status, pit_stop=True),
            actual_plan=self.actual_plan_dict(dl), counterfactual_plan=_plan_dict(plan, n),
            summary=dict(elapsed_delta_median_s=q50, elapsed_delta_q10_s=q10, elapsed_delta_q90_s=q90, probability_of_gain=p_gain, oracle_regret_median_s=None,
                         estimated_finish_position_median=None, estimated_finish_position_q10=None, estimated_finish_position_q90=None),
            assumptions=dict(rivals_follow_observed_trajectories=True, rival_strategy_response='none', safety_car_mode=sc_mode, driver_baseline_preserved=True),
            claim_scope=claim, track_position_simulated=False, rival_interactions_simulated=False, traffic_mode=traffic_mode, safety_car_schedule=schedule,
            assets={},
            validation=dict(identity_test=identity, future_leakage_test=leakage, target_driver_excluded=bool(curves['target_driver_excluded']), sealed_holdout=split == 'sealed_holdout'),
            warnings=warnings)
        timing_ms = (time.perf_counter() - t0) * 1000.0
        engine = dict(
            engine_version=ENGINE_VERSION, provider=self.provider.model_version, mode=spec.mode, curve_source=spec.curve_source,
            uses_post_race_reference=bool(curves['uses_post_race_reference']), uses_future_data_for_pre_race_quantities=False,
            pre_race_forecast_hash=self.provider.forecast_hash,
            curves=curves, offsets=offs, offsets_source=offs_src, offset_sd=OFFSET_SD, pit_model=pm.to_dict(), plan_info=plan_info,
            standardised_pit_event=spec.standardised_pit_event, stop_replacement_delta_s=stop_replacement,
            elapsed_delta_mean_s=float(totals.mean()), elapsed_delta_sd_s=float(totals.std()), tyre_delta_mean_s=float(tyre_part.sum()), pit_delta_mean_s=float(pit_part.sum()),
            identity_check_delta_s=identity_delta, n_samples=spec.n_samples, seed=spec.seed, sampled_parameters=PARAM_NAMES,
            theta_mean=dict(zip(PARAM_NAMES, [float(v) for v in theta_mean])), theta_sample_mean=dict(zip(PARAM_NAMES, [float(v) for v in theta_bar])),
            n_laps=n, retired=dl.retired, timing_ms=timing_ms, support=support,
            frozen_laps=[int(i + 1) for i in np.flatnonzero(frozen)], cf_stops=[asdict(s) for s in cf_stops],
            actual_stops=[dict(in_lap=s.in_lap, out_lap=s.out_lap, free=s.free, measured=s.measured, meas_in=_f(s.meas_in), meas_out=_f(s.meas_out), label_in=s.label_in, label_out=s.label_out) for s in dl.stops])
        return CounterfactualResult(spec=spec, table=table, scenario=scenario, engine=engine, events_actual=events_actual, events_cf=events_cf, deltas=D, timing_ms=timing_ms)

    # ---------------------------------------------------------------- assembly of the linear model
    def _assemble(self, dl: DriverLaps, plan: list[CfStint], spec: ScenarioSpec, pm: PitEventModel):
        n = dl.n
        fixed = spec.mode == 'fixed_context'
        coef = np.zeros((n, N_PARAMS))
        const = np.zeros(n)
        notes: list[str] = []
        labels = dl.label
        frozen = np.array([fixed and (l in FROZEN_LABELS) for l in labels])
        # counterfactual compound and age per lap
        cf_comp = [''] * n
        cf_age = np.zeros(n)
        for s in plan:
            for lap in range(s.start_lap, s.end_lap + 1):
                i = lap - 1
                cf_comp[i] = s.compound
                cf_age[i] = dl.age[i] if s.from_actual is not None else s.start_age + (lap - s.start_lap)
        act_comp = dl.compound
        act_age = dl.age
        # tyre term
        for i in range(n):
            if frozen[i]:
                continue
            cc, ca = cf_comp[i], act_comp[i]
            if cc == ca and cf_age[i] == act_age[i]:
                continue
            coef[i, P_SLOPE[cc]] += cf_age[i]
            coef[i, P_SLOPE[ca]] -= act_age[i]
            coef[i, P_OFF[cc]] += 1.0
            coef[i, P_OFF[ca]] -= 1.0
        # restart warm-up (fixed_context): first unfrozen lap after a frozen block; cancels unless compounds differ
        if fixed:
            for i in range(1, n):
                if frozen[i - 1] and not frozen[i] and cf_comp[i] != act_comp[i]:
                    coef[i, P_WARM[cf_comp[i]]] += 1.0
                    coef[i, P_WARM[act_comp[i]]] -= 1.0

        def f_transit(i: int) -> float:
            l = labels[i]
            if l == 'RED':
                return 0.0
            if fixed and l in ('SC', 'VSC'):
                return pm.sc_factor
            return 1.0

        def g_stat(i: int) -> float:
            return 0.0 if labels[i] == 'RED' else 1.0

        # actual stops: their measured loss is in Y (subtract); unmeasured -> standardised mean as a constant
        act_state = ['run'] * n
        for s in dl.stops:
            i_in, i_out = s.in_lap - 1, s.out_lap - 1
            act_state[i_in] = 'free_change' if s.free else 'in_lap'
            if i_out < n:
                act_state[i_out] = 'free_change' if s.free else 'out_lap'
            if s.free:
                continue
            if s.measured:
                const[i_in] -= s.meas_in
                if i_out < n:
                    const[i_out] -= s.meas_out
            else:
                const[i_in] -= pm.share_in * pm.transit_med * f_transit(i_in)
                if i_out < n:
                    const[i_out] -= (1 - pm.share_in) * pm.transit_med * f_transit(i_out) + pm.stationary_med * g_stat(i_out)
                notes.append(f'actual stop on lap {s.in_lap} not measurable (missing or unclean neighbouring laps); standardised mean used for its loss')
        # counterfactual stops
        cf_stops: list[CfStop] = []
        cf_state = ['run'] * n
        by_in = {s.in_lap: i for i, s in enumerate(dl.stops)}
        own = next((s for s in dl.stops if s.measured and not s.free), None)
        for a, b in zip(plan, plan[1:]):
            L = a.end_lap
            i_in, i_out = L - 1, L
            coincident = by_in.get(L)
            free = labels[i_in] == 'RED' or (i_out < n and labels[i_out] == 'RED')
            cf_stops.append(CfStop(L, L + 1, b.compound, coincident, free))
            cf_state[i_in] = 'free_change' if free else 'in_lap'
            if i_out < n:
                cf_state[i_out] = 'free_change' if free else 'out_lap'
            if free:
                continue
            if spec.standardised_pit_event:
                coef[i_in, P_TRANSIT] += pm.share_in * f_transit(i_in)
                if i_out < n:
                    coef[i_out, P_TRANSIT] += (1 - pm.share_in) * f_transit(i_out)
                    coef[i_out, P_STAT] += g_stat(i_out)
                if i_out + 1 < n and not frozen[i_out + 1]:
                    coef[i_out + 1, P_PEN[b.compound]] += 1.0
                    if cf_state[i_out + 1] == 'run':
                        cf_state[i_out + 1] = 'warm_up_1'
                if i_out + 2 < n and not frozen[i_out + 2]:
                    coef[i_out + 2, P_WARM[b.compound]] += 1.0
                    if cf_state[i_out + 2] == 'run':
                        cf_state[i_out + 2] = 'warm_up_2'
            else:
                src = dl.stops[coincident] if (coincident is not None and dl.stops[coincident].measured and not dl.stops[coincident].free) else own
                if src is not None:
                    const[i_in] += src.meas_in
                    if i_out < n:
                        const[i_out] += src.meas_out
                    if src is not (dl.stops[coincident] if coincident is not None else None):
                        notes.append(f'standardised pit event disabled: the driver\'s own measured stop (lap {src.in_lap}, {src.meas_in + src.meas_out:.2f} s) moved verbatim to lap {L}')
                else:
                    const[i_in] += pm.share_in * pm.transit_med * f_transit(i_in)
                    if i_out < n:
                        const[i_out] += (1 - pm.share_in) * pm.transit_med * f_transit(i_out) + pm.stationary_med * g_stat(i_out)
                    notes.append(f'standardised pit event disabled but {spec.driver} has no measurable green stop; standardised mean used as a constant for the stop on lap {L}')
        return coef, const, cf_comp, cf_age, cf_state, act_state, frozen, cf_stops, notes

    def _identity_check(self, dl: DriverLaps, spec: ScenarioSpec, pm: PitEventModel, curves: dict[str, Any], offs: dict[str, float]) -> tuple[str, Optional[float]]:
        """Replay the actual plan with the standardised event disabled: the cumulative delta must be exactly zero."""
        if not dl.stops:
            return 'not_run', None
        plan = [CfStint(s.start_lap, s.end_lap, s.compound, s.start_age, s.set_status, s.index) for s in dl.stints]
        ispec = ScenarioSpec(spec.event, spec.driver, dl.stops[0].in_lap, dl.stops[0].to_compound, mode=spec.mode, curve_source=spec.curve_source,
                             standardised_pit_event=False, exclude_target_driver=spec.exclude_target_driver, sc_factor=spec.sc_factor, n_samples=spec.n_samples, seed=spec.seed)
        coef, const, *_ = self._assemble(dl, plan, ispec, pm)
        theta_mean, Theta = self.samples(spec.event, spec, curves, offs, pm)
        D = coef @ Theta.T + const[:, None]
        total = float(np.abs(D.sum(axis=0)).max())
        return ('pass' if total < IDENTITY_TOL else 'fail'), total

    def _leakage_check(self, spec: ScenarioSpec, curves: dict[str, Any]) -> str:
        """Pre-race quantities must come from the frozen forecast: provider A's curves carry the lock forecast hash and
        post_race=False; the race reference is post-race by design and is labelled so (uses_post_race_reference)."""
        try:
            for c in self.provider.available_compounds(spec.event):
                cv = self.provider.predict_curve(spec.event, spec.driver, c, None, (1, 2))
                assert_pre_race(cv)
                if cv.provenance.get('forecast_hash') != self.provider.forecast_hash:
                    return 'fail'
            if spec.curve_source == 'pre_race_forecast' and curves.get('uses_post_race_reference'):
                return 'fail'
            return 'pass'
        except Exception:
            return 'fail'

    # ---------------------------------------------------------------- per-lap table
    def _table(self, dl: DriverLaps, D: np.ndarray, mean_path: np.ndarray, tyre_part: np.ndarray, pit_part: np.ndarray, cf_comp: list[str], cf_age: np.ndarray,
               cf_state: list[str], act_state: list[str], frozen: np.ndarray, R: RaceData, traffic_reported: bool = True) -> pd.DataFrame:
        n = dl.n
        lap_q10, lap_q90 = np.quantile(D, 0.1, axis=1), np.quantile(D, 0.9, axis=1)
        cum = np.cumsum(D, axis=0)
        cum_q10, cum_q90 = np.quantile(cum, 0.1, axis=1), np.quantile(cum, 0.9, axis=1)
        beta = float(R.traffic['beta'])
        traffic = np.where(np.isfinite(dl.traffic), dl.traffic, 0.0) * beta if traffic_reported else np.zeros(n)
        t = pd.DataFrame({
            'lap': dl.lap.astype(int),
            'actual_lap_time': dl.lap_s,
            'cf_lap_time_mean': dl.lap_s + mean_path,
            'cf_lap_time_q10': dl.lap_s + lap_q10,
            'cf_lap_time_q90': dl.lap_s + lap_q90,
            'lap_delta': mean_path,
            'cumulative_delta': np.cumsum(mean_path),
            'actual_compound': dl.compound,
            'cf_compound': cf_comp,
            'actual_tyre_age': dl.age,
            'cf_tyre_age': cf_age,
            'actual_traffic_effect': traffic,
            'cf_traffic_effect': traffic,
            'pit_state': cf_state,
            'track_status': dl.label,
            'actual_position': [int(p) if np.isfinite(p) else None for p in dl.position],
            'cf_position_median': [None] * n,
            'cf_position_q10': [None] * n,
            'cf_position_q90': [None] * n,
            'actual_lap_inferred': dl.inferred,
            'lap_delta_q10': lap_q10,
            'lap_delta_q90': lap_q90,
            'cumulative_delta_q10': cum_q10,
            'cumulative_delta_q90': cum_q90,
            'delta_tyre_mean': tyre_part,
            'delta_pit_mean': pit_part,
            'actual_pit_state': act_state,
            'frozen': frozen,
        })
        return t

    # ---------------------------------------------------------------- lattice
    def lattice(self, event: str, mode: str = 'fixed_context', drivers: Optional[list[str]] = None, laps: Optional[list[int]] = None,
                compounds: Optional[list[str]] = None, set_status: str = 'new', continuation: str = 'as_actual', curve_source: str = 'race_reference',
                n_samples: int = 500, seed: int = 2026, **kw: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Driver x intervention lap x compound for one race; summaries only (no per-lap tables). Returns (rows, timing)."""
        R = self.race(event)
        t_all = time.perf_counter()
        self.pit_model(event, kw.get('sc_factor', SC_FACTOR_DEFAULT))
        t_pre = (time.perf_counter() - t_all) * 1000
        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        drivers = drivers or R.drivers
        compounds = compounds or COMPS
        times: list[float] = []
        for drv in drivers:
            dl = R.driver(drv)
            lap_list = laps or list(range(2, dl.n))
            for L in lap_list:
                if L >= dl.n:
                    continue
                for c in compounds:
                    spec = ScenarioSpec(event, drv, L, c, set_status=set_status, mode=mode, continuation=continuation, curve_source=curve_source, n_samples=n_samples, seed=seed, **kw)
                    t0 = time.perf_counter()
                    try:
                        res = self.compile(spec, build_table=False, run_identity_check=False)
                    except (ValueError, KeyError) as e:
                        errors.append(dict(driver=drv, lap=L, to_compound=c, error=str(e)))
                        continue
                    times.append((time.perf_counter() - t0) * 1000)
                    s = res.summary
                    new_stop = next((cs for cs in res.engine['cf_stops'] if cs['in_lap'] == L), None)
                    rows.append(dict(scenario_id=spec.scenario_id, driver=drv, lap=L, to_compound=c, set_status=set_status, mode=mode, plan=res.scenario['counterfactual_plan']['label'],
                                     n_stops_cf=len(res.scenario['counterfactual_plan']['pit_laps']), elapsed_delta_median_s=s['elapsed_delta_median_s'], elapsed_delta_q10_s=s['elapsed_delta_q10_s'],
                                     elapsed_delta_q90_s=s['elapsed_delta_q90_s'], probability_of_gain=s['probability_of_gain'], tyre_delta_mean_s=res.engine['tyre_delta_mean_s'],
                                     pit_delta_mean_s=res.engine['pit_delta_mean_s'], in_support=res.engine['support']['in_support'],
                                     free_stop=bool(new_stop['free']) if new_stop else False, stop_lap_status=dl.label[L - 1], compile_ms=times[-1]))
        total_ms = (time.perf_counter() - t_all) * 1000
        timing = dict(event=event, mode=mode, n_scenarios=len(rows), n_errors=len(errors), precompute_ms=t_pre, total_ms=total_ms,
                      per_scenario_ms_median=float(np.median(times)) if times else None, per_scenario_ms_max=float(np.max(times)) if times else None, errors=errors[:20])
        return pd.DataFrame(rows), timing


# ---------------------------------------------------------------- helpers

def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if np.isfinite(v) else None
    except TypeError:
        return None


def _plan_dict(stints: list[CfStint], n: int) -> dict[str, Any]:
    ends, acc = [], 0
    for s in stints[:-1]:
        acc += s.n_laps
        ends.append(acc)
    return dict(label='-'.join(s.compound[0] for s in stints), stints=[dict(compound=s.compound, laps=int(s.n_laps), set_status=s.set_status) for s in stints], pit_laps=ends, n_laps=int(n))


def _stop_events(stops: list[CfStop], n: int) -> list[dict[str, Any]]:
    ev: list[dict[str, Any]] = []
    for s in stops:
        ev.append(dict(kind='pit_entry', lap=s.in_lap, compound=s.to_compound, free=s.free))
        ev.append(dict(kind='stationary', lap=s.out_lap, compound=s.to_compound, free=s.free))
        ev.append(dict(kind='pit_exit', lap=s.out_lap, compound=s.to_compound, free=s.free))
        ev.append(dict(kind='age_reset', lap=s.out_lap, compound=s.to_compound, free=s.free))
        ev.append(dict(kind='warm_up', lap=s.out_lap + 1, compound=s.to_compound, free=s.free))
    return ev


def _claim_scope(mode: str) -> str:
    try:
        from schemas.lock_v2 import CLAIM_SCOPE_BY_MODE
        return CLAIM_SCOPE_BY_MODE[mode]
    except Exception:
        return 'Model-implied tyre-time delta only. Track position, traffic and rival strategy responses are not simulated.'


def notes_replacement(engine: CounterfactualEngine, dl: DriverLaps, spec: ScenarioSpec, pm: PitEventModel, theta_mean: np.ndarray) -> list[float]:
    """Per actual stop: E[standardised event] - measured loss, in the laps' schedule context (fixed_context) or green (tyre_only).
    With the standardised event disabled the replacement is zero by construction."""
    out: list[float] = []
    if not spec.standardised_pit_event:
        return [0.0]
    fixed = spec.mode == 'fixed_context'
    n = dl.n
    for s in dl.stops:
        if s.free:
            continue
        def f(i: int) -> float:
            l = dl.label[i]
            return 0.0 if l == 'RED' else (pm.sc_factor if (fixed and l in ('SC', 'VSC')) else 1.0)
        i_in, i_out = s.in_lap - 1, s.out_lap - 1
        std = pm.share_in * theta_mean[P_TRANSIT] * f(i_in)
        if i_out < n:
            std += (1 - pm.share_in) * theta_mean[P_TRANSIT] * f(i_out) + theta_mean[P_STAT] * (0.0 if dl.label[i_out] == 'RED' else 1.0)
        c = s.to_compound
        if i_out + 1 < n and not (fixed and dl.label[i_out + 1] in FROZEN_LABELS):
            std += theta_mean[P_PEN[c]]
        if i_out + 2 < n and not (fixed and dl.label[i_out + 2] in FROZEN_LABELS):
            std += theta_mean[P_WARM[c]]
        meas = (s.meas_in + s.meas_out) if s.measured else std
        out.append(float(std - meas))
    return out


__all__ = ['CounterfactualEngine', 'ScenarioSpec', 'CounterfactualResult', 'CfStint', 'CfStop', 'FrozenFieldNotAvailable', 'ENGINE_VERSION', 'MODES', 'CONTINUATIONS',
           'SET_AGE', 'OFFSET_SD', 'MAX_SHIFT', 'LAP_COLUMNS', 'EXTRA_COLUMNS', 'PARAM_NAMES']
