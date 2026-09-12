"""PreRaceCurveProvider (roadmap v5 section 7, task 0.3): the interface and provider A.

    TyreCurveProvider.predict_curve(event_id, driver_id, compound, context, tyre_age_range) -> CurveDistribution

Provider A reproduces the v1 lock (out/lock.json) exactly; it never fits anything:
  * completed weekend  -> validation_rows[event, compound]: slope = pred_clearstint, band = [lo, hi]
  * live weekend       -> live[event].compounds[compound]: slope = prediction, band = band90
  loss(age) = slope * age; q10 / q90 are the band edges times age (the v1 band is a conformal 90% band, so the
  edges are the 5th and 95th percentiles: using them as q10/q90 is conservative, and documented here rather than
  re-derived); q50 = mean; cliff_probability is identically zero (provider A has no cliff model).

The race-derived reference slope (validation_rows.obs, obs_se) is exposed ONLY through `reference_curve_post_race`,
whose provenance carries post_race=True and uses_post_race_reference=True. Pre-race code paths must never call it;
`assert_pre_race(curve)` is the guard consumers use.

Provenance on every curve: model_version 'provider_A_v2', forecast_hash = out/lock_v2.json shared.forecast_hash,
the lock generated_at, the lock row it came from, and the numbers used.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

from counterfactual import PROTO

MODEL_VERSION = 'provider_A_v2'
Z95 = 1.6448536269514722          # 95th percentile of the standard normal: the v1 band is a 90% band
COMPOUNDS = ('SOFT', 'MEDIUM', 'HARD')


class CurveUnavailable(KeyError):
    """The lock carries no curve for this event / compound (e.g. a compound never run in practice)."""


@dataclass(frozen=True)
class CurveDistribution:
    """Pace loss vs tyre age (s/lap), arrays aligned with `ages`. Negative loss = the tyre gets faster with age
    (the lower band edge of a low-degradation weekend can be negative in v1; kept verbatim)."""
    ages: np.ndarray
    mean_loss_s: np.ndarray
    q10_loss_s: np.ndarray
    q50_loss_s: np.ndarray
    q90_loss_s: np.ndarray
    cliff_probability: np.ndarray
    provenance: dict[str, Any]
    slope: float                      # s/lap per lap
    band: tuple[float, float]         # [low, high] slope band the quantiles come from
    slope_se: Optional[float] = None  # standard error when the lock carries one (post-race reference only)

    @property
    def sd_from_band(self) -> float:
        """Normal sd implied by a 90% band: (hi - lo) / (2 z95). Used when no SE exists."""
        return float((self.band[1] - self.band[0]) / (2.0 * Z95))

    @property
    def sampling_sd(self) -> float:
        return float(self.slope_se) if self.slope_se is not None and np.isfinite(self.slope_se) else self.sd_from_band

    @property
    def post_race(self) -> bool:
        return bool(self.provenance.get('post_race', False))


def assert_pre_race(curve: CurveDistribution) -> CurveDistribution:
    """Guard for pre-race code paths: refuse a curve derived from race data."""
    if curve.post_race or curve.provenance.get('uses_post_race_reference'):
        raise ValueError(f"post-race reference curve used on a pre-race path: {curve.provenance.get('source')}")
    return curve


class TyreCurveProvider(ABC):
    """PreRaceCurveProvider contract. `context` is a free dict (set_status, track_temp, ...); provider A ignores it
    and says so in the provenance. `driver_id` is accepted for the interface; provider A has no driver term."""

    model_version: str = 'abstract'

    @abstractmethod
    def predict_curve(self, event_id: str, driver_id: Optional[str], compound: str, context: Optional[dict[str, Any]] = None,
                      tyre_age_range: Iterable[int] | tuple[int, int] = (1, 40)) -> CurveDistribution: ...

    @abstractmethod
    def available_compounds(self, event_id: str) -> list[str]: ...


def _ages(tyre_age_range: Iterable[int] | tuple[int, int]) -> np.ndarray:
    if isinstance(tyre_age_range, tuple) and len(tyre_age_range) == 2 and all(isinstance(v, (int, np.integer)) for v in tyre_age_range):
        lo, hi = int(tyre_age_range[0]), int(tyre_age_range[1])
        if lo < 0 or hi < lo:
            raise ValueError(f'bad tyre_age_range {tyre_age_range}')
        return np.arange(lo, hi + 1, dtype=float)
    a = np.asarray(list(tyre_age_range), dtype=float)
    if a.size == 0 or (a < 0).any():
        raise ValueError('tyre ages must be non-negative')
    return a


def event_name(event_id: str) -> str:
    """'2026_Monza' -> 'Monza'; 'Monza' -> 'Monza'."""
    return event_id.split('_', 1)[1] if '_' in event_id and event_id.split('_', 1)[0].isdigit() else event_id


class ProviderA(TyreCurveProvider):
    """The v1 ClearStint estimator as a curve provider. Reads out/lock.json (numbers) and out/lock_v2.json (hash)."""

    model_version = MODEL_VERSION

    def __init__(self, lock_path: Path | str | None = None, lock_v2_path: Path | str | None = None):
        self.lock_path = Path(lock_path) if lock_path else PROTO / 'out' / 'lock.json'
        self.lock_v2_path = Path(lock_v2_path) if lock_v2_path else PROTO / 'out' / 'lock_v2.json'
        with open(self.lock_path, 'r', encoding='utf-8') as f:
            self.lock: dict[str, Any] = json.load(f)
        self.forecast_hash: Optional[str] = None
        self.lock_v2_meta: dict[str, Any] = {}
        if self.lock_v2_path.exists():
            with open(self.lock_v2_path, 'r', encoding='utf-8') as f:
                v2 = json.load(f)
            self.forecast_hash = v2['shared']['forecast_hash']
            self.lock_v2_meta = dict(v2['shared'].get('meta', {}))
        self._rows: dict[tuple[str, str], dict[str, Any]] = {(r['event'], r['compound']): r for r in self.lock.get('validation_rows', [])}
        self._live: dict[str, dict[str, Any]] = dict(self.lock.get('live', {}))

    # ---------------------------------------------------------------- lookup
    def _record(self, event: str, compound: str) -> tuple[str, dict[str, Any]]:
        """('validation_rows' | 'live', record). Completed weekends come from validation_rows, live ones from live[]."""
        row = self._rows.get((event, compound))
        if row is not None and row.get('completed'):
            return 'validation_rows', row
        live = self._live.get(event)
        if live is not None:
            for c in live.get('compounds', []):
                if c['compound'] == compound:
                    return 'live', c
        if row is not None:                                   # a validation row of a weekend flagged not completed
            return 'validation_rows', row
        raise CurveUnavailable(f'{event}/{compound}: no curve in {self.lock_path.name} (validation_rows or live)')

    def available_compounds(self, event_id: str) -> list[str]:
        ev = event_name(event_id)
        out = [c for c in COMPOUNDS if (ev, c) in self._rows]
        if not out and ev in self._live:
            out = [c['compound'] for c in self._live[ev].get('compounds', [])]
        return out

    def is_completed(self, event_id: str) -> bool:
        ev = event_name(event_id)
        return any(r.get('completed') for (e, _), r in self._rows.items() if e == ev)

    def _provenance(self, event: str, compound: str, source: str, rec: dict[str, Any], **extra: Any) -> dict[str, Any]:
        base = dict(model_version=MODEL_VERSION, forecast_hash=self.forecast_hash, lock_generated_at=self.lock.get('generated_at'),
                    lock_path=self.lock_path.as_posix(), event=event, compound=compound, source=source,
                    context_used=False, driver_term=False, post_race=False, uses_post_race_reference=False,
                    quantile_rule='q10/q90 = 90%-band edges x age (5th/95th percentiles, conservative); q50 = mean = slope x age')
        base.update(extra)
        return base

    # ---------------------------------------------------------------- the pre-race curve
    def predict_curve(self, event_id: str, driver_id: Optional[str], compound: str, context: Optional[dict[str, Any]] = None,
                      tyre_age_range: Iterable[int] | tuple[int, int] = (1, 40)) -> CurveDistribution:
        ev = event_name(event_id)
        source, rec = self._record(ev, compound)
        if source == 'validation_rows':
            slope, lo, hi = float(rec['pred_clearstint']), float(rec['lo']), float(rec['hi'])
            detail = dict(issued=bool(rec['issued']), gate=rec['gate'], clean=rec.get('clean'), clean_se=rec.get('clean_se'),
                          factor=rec.get('k'), factor_applied=rec.get('k_applied'), floor=rec.get('floor'), widen=rec.get('widen'))
        else:
            slope, lo, hi = float(rec['prediction']), float(rec['band90'][0]), float(rec['band90'][1])
            detail = dict(issued=bool(rec['issued']), gate=rec['gate'], clean=rec.get('clean'), clean_se=rec.get('clean_se'),
                          factor=rec.get('factor'), factor_applied=rec.get('factor_applied'), basis=rec.get('basis'))
        if not (lo - 1e-12 <= slope <= hi + 1e-12):
            raise ValueError(f'{ev}/{compound}: lock prediction {slope} outside its band [{lo}, {hi}]')
        ages = _ages(tyre_age_range)
        prov = self._provenance(ev, compound, source, rec, slope=slope, band=[lo, hi], **detail)
        return CurveDistribution(ages=ages, mean_loss_s=slope * ages, q10_loss_s=lo * ages, q50_loss_s=slope * ages, q90_loss_s=hi * ages,
                                 cliff_probability=np.zeros_like(ages), provenance=prov, slope=slope, band=(lo, hi), slope_se=None)

    # ---------------------------------------------------------------- the post-race reference (never pre-race)
    def reference_curve_post_race(self, event_id: str, compound: str, tyre_age_range: Iterable[int] | tuple[int, int] = (1, 40)) -> CurveDistribution:
        """RACE-DERIVED PACE-LOSS REFERENCE (wording rule 9.2): validation_rows.obs with its standard error.
        Post-race by construction; only Ghost Strategy / Race Twin audit code may call it."""
        ev = event_name(event_id)
        row = self._rows.get((ev, compound))
        if row is None or not row.get('completed') or row.get('obs') is None:
            raise CurveUnavailable(f'{ev}/{compound}: no race-derived reference (weekend not completed)')
        slope, se = float(row['obs']), float(row['obs_se']) if row.get('obs_se') is not None else float('nan')
        lo, hi = slope - Z95 * se, slope + Z95 * se
        ages = _ages(tyre_age_range)
        prov = self._provenance(ev, compound, 'validation_rows.obs', row, slope=slope, slope_se=se, n_race=row.get('n_race'),
                                post_race=True, uses_post_race_reference=True, label='race-derived pace-loss reference (post-race)',
                                quantile_rule='q10/q90 = (obs -/+ z95 x obs_se) x age; all-driver race fit from the v1 lock')
        return CurveDistribution(ages=ages, mean_loss_s=slope * ages, q10_loss_s=lo * ages, q50_loss_s=slope * ages, q90_loss_s=hi * ages,
                                 cliff_probability=np.zeros_like(ages), provenance=prov, slope=slope, band=(lo, hi), slope_se=se)

    def reference_curve(self, *a: Any, **k: Any) -> CurveDistribution:
        """Alias kept for the roadmap wording; identical to reference_curve_post_race (post-race, audit only)."""
        return self.reference_curve_post_race(*a, **k)


__all__ = ['TyreCurveProvider', 'ProviderA', 'CurveDistribution', 'CurveUnavailable', 'assert_pre_race', 'event_name', 'MODEL_VERSION', 'Z95', 'COMPOUNDS']
