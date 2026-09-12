"""Replay of a recorded race one lap at a time, computing ONLY display quantities.

Boundary rule (roadmap 3, acceptance test 7): while displaying lap k the service never reads lap k+1.
`ReplayCursor.visible()` is the single accessor for lap rows and asserts the bound; nothing else touches the frame.
Corrections are the ones the lock documents (rules.fuel_s_per_kg x rules.fuel_prior_kg_per_lap; track evolution only
when the lock carries a value for the session). The posterior here is a labelled PLACEHOLDER: a precision-weighted
combination of the lock prior and the running OLS slope of the current stint, widened by the lock's conformal factor
for three laps after a flag or pit. Workstream 8's LiveTyreStateEstimator replaces it through the same view model.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
from app_v2.services import paths as P
from app_v2.services import asset_repository as A

try:
    import streamlit as st
    _cache = st.cache_data(show_spinner=False)
except Exception:  # pragma: no cover
    def _cache(fn):
        return fn

COMPOUND_LETTER = {'SOFT': 'S', 'MEDIUM': 'M', 'HARD': 'H', 'INTERMEDIATE': 'I', 'WET': 'W'}
Z90 = 1.6449
WIDEN_LAPS = 3            # laps of widening after a non-green lap or a pit event
MIN_FIT_LAPS = 3          # kept laps before the running slope is used at all
POSTERIOR_LABEL = 'PLACEHOLDER posterior: precision-weighted lock prior x running OLS slope of the current stint (Workstream 8 LiveTyreStateEstimator pending)'


@_cache
def _read_race(path: str, mtime: float) -> pd.DataFrame:
    df = pd.read_csv(path)
    df['TrackStatus'] = df['TrackStatus'].astype(str)
    df['LapNumber'] = df['LapNumber'].astype(int)
    df['Stint'] = df['Stint'].fillna(0).astype(int)
    df['TyreLife'] = df['TyreLife'].astype(float)
    for c in ('pit_in', 'pit_out', 'deleted', 'IsAccurate'):
        df[c] = df[c].astype(bool)
    df['green'] = df['TrackStatus'] == '1'
    return df.sort_values(['Driver', 'LapNumber']).reset_index(drop=True)


def load_race(event: str) -> Optional[pd.DataFrame]:
    p = P.race_csv(event)
    if not p.exists():
        return None
    return _read_race(str(p), p.stat().st_mtime)


def drivers_for(event: str) -> list[str]:
    df = load_race(event)
    if df is None:
        return []
    counts = df.groupby('Driver')['LapNumber'].max().sort_values(ascending=False)
    return list(counts.index)


@dataclass(frozen=True)
class Corrections:
    fuel_s_per_kg: float
    fuel_kg_per_lap: float
    evolution_s_per_min: Optional[float]      # None -> not in lock for this session, not applied
    traffic_max: float
    widen_factor: float                        # lock band_coverage.widening_factor_median

    @property
    def fuel_s_per_lap(self) -> float:
        return self.fuel_s_per_kg * self.fuel_kg_per_lap


@dataclass(frozen=True)
class Prior:
    compound: str
    slope: Optional[float]
    band90: tuple[Optional[float], Optional[float]]
    source: str

    @property
    def sd(self) -> Optional[float]:
        lo, hi = self.band90
        if lo is None or hi is None:
            return None
        return max((hi - lo) / (2 * Z90), 1e-6)


@dataclass
class StintState:
    lap: int
    stint: int
    compound: str
    tyre_age: int
    laps_in_stint: int
    kept_laps: int
    ages: list[float]                 # kept laps: tyre age
    losses: list[float]               # kept laps: corrected pace loss vs fitted fresh tyre (s)
    all_ages: list[float]             # every lap in the stint (kept or not), for hollow markers
    all_losses: list[float]
    all_kept: list[bool]
    fitted_intercept: Optional[float]
    ols_slope: Optional[float]
    ols_se: Optional[float]
    post_slope: Optional[float]
    post_sd: Optional[float]
    widened: bool
    widen_reason: str
    trend_vs_prior: Optional[float]   # post_slope / prior slope
    pace_loss_now: Optional[float]
    events_in_stint: list[dict]       # {'lap','kind','detail'}
    estimator_label: str = POSTERIOR_LABEL

    @property
    def band90(self) -> tuple[Optional[float], Optional[float]]:
        if self.post_slope is None or self.post_sd is None:
            return (None, None)
        return (self.post_slope - Z90 * self.post_sd, self.post_slope + Z90 * self.post_sd)

    def project(self, horizons=(1, 3, 5, 10)) -> list[dict]:
        out = []
        if self.post_slope is None:
            return out
        for h in horizons:
            age = self.tyre_age + h
            loss = (self.fitted_intercept or 0.0) * 0 + self.post_slope * age
            half = Z90 * (self.post_sd or 0.0) * age
            out.append(dict(h=h, age=age, loss=loss, lo=loss - half, hi=loss + half))
        return out


class ReplayCursor:
    """Owns a single driver's recorded laps; exposes rows only through visible(k)."""

    def __init__(self, event: str, driver: str, n_laps_lock: Optional[int] = None):
        df = load_race(event)
        if df is None:
            raise FileNotFoundError(P.race_csv(event))
        self.event, self.driver = event, driver
        self._df = df[df['Driver'] == driver].sort_values('LapNumber').reset_index(drop=True)
        if self._df.empty:
            raise KeyError(f'{driver} not in {event} race file')
        self.first_lap = int(self._df['LapNumber'].min())
        self.last_lap = int(self._df['LapNumber'].max())
        self.n_laps = int(n_laps_lock or self.last_lap)
        self.lap = self.first_lap
        self.asset = A.race_csv_asset(event)

    def seek(self, lap: int) -> 'ReplayCursor':
        self.lap = int(min(max(lap, self.first_lap), self.last_lap))
        return self

    def step(self, n: int = 1) -> 'ReplayCursor':
        return self.seek(self.lap + n)

    @property
    def at_end(self) -> bool:
        return self.lap >= self.last_lap

    def visible(self, lap: Optional[int] = None) -> pd.DataFrame:
        k = self.lap if lap is None else int(lap)
        out = self._df[self._df['LapNumber'] <= k]
        assert out.empty or int(out['LapNumber'].max()) <= k, 'replay boundary violated: a lap beyond k was exposed'
        return out

    def lap_row(self, lap: Optional[int] = None) -> Optional[pd.Series]:
        v = self.visible(lap)
        return None if v.empty else v.iloc[-1]

    def others_visible(self, lap: Optional[int] = None) -> pd.DataFrame:
        """Other drivers' laps through k (online-safe: same bound), for faint comparable traces."""
        k = self.lap if lap is None else int(lap)
        df = load_race(self.event)
        out = df[(df['Driver'] != self.driver) & (df['LapNumber'] <= k)]
        assert out.empty or int(out['LapNumber'].max()) <= k
        return out


def corrected_loss(rows: pd.DataFrame, corr: Corrections) -> np.ndarray:
    """lap_s with the fuel prior and (when present in the lock) session evolution removed. Display quantity only."""
    y = rows['lap_s'].to_numpy(dtype=float) + corr.fuel_s_per_lap * (rows['LapNumber'].to_numpy(dtype=float) - 1.0)
    if corr.evolution_s_per_min is not None:
        t = rows['t_min'].to_numpy(dtype=float)
        t = np.where(np.isfinite(t), t, 0.0)
        y = y - corr.evolution_s_per_min * t
    return y


def kept_mask(rows: pd.DataFrame, corr: Corrections) -> np.ndarray:
    """The lock's lap rules, applied causally: 105 % of the stint best *so far*."""
    base = (rows['green'] & rows['IsAccurate'] & ~rows['pit_in'] & ~rows['pit_out'] & ~rows['deleted']).to_numpy()
    traffic = rows['traffic'].to_numpy(dtype=float)
    base &= np.where(np.isfinite(traffic), traffic <= corr.traffic_max, False)
    base &= np.isfinite(rows['TyreLife'].to_numpy(dtype=float))
    base &= rows['Compound'].notna().to_numpy()
    lap_s = rows['lap_s'].to_numpy(dtype=float)
    best = np.minimum.accumulate(np.where(base, lap_s, np.inf))
    with np.errstate(invalid='ignore'):
        base &= lap_s <= 1.05 * best
    return base


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    n = len(x); xm, ym = x.mean(), y.mean(); sxx = ((x - xm) ** 2).sum()
    if n < MIN_FIT_LAPS or sxx <= 0:
        return math.nan, math.nan, math.nan
    b = ((x - xm) * (y - ym)).sum() / sxx; a = ym - b * xm
    resid = y - (a + b * x); s2 = (resid ** 2).sum() / max(n - 2, 1)
    return a, b, math.sqrt(s2 / sxx) if s2 > 0 else 1e-4


def missing_tyre_fields(row: Optional[pd.Series]) -> list[str]:
    """Missing current-lap metadata; never fill it from another lap or stint."""
    missing = []
    compound = row.get('Compound') if row is not None else None
    age = row.get('TyreLife') if row is not None else None
    if not isinstance(compound, str) or not compound.strip():
        missing.append('tyre compound')
    if age is None or not math.isfinite(float(age)) or float(age) < 0:
        missing.append('tyre age')
    return missing



def prediction_unavailable_reason(cursor: ReplayCursor) -> str:
    """The live estimator requires complete tyre metadata in the visible prefix."""
    missing = missing_tyre_fields(cursor.lap_row())
    if missing:
        return ('Prediction unavailable: ' + ' and '.join(missing)
                + ' missing from this recorded lap. Select another driver or scrub to a lap with tyre data.')
    for _, row in cursor.visible().iterrows():
        missing = missing_tyre_fields(row)
        if missing:
            return ('Prediction unavailable: ' + ' and '.join(missing)
                    + f" missing from earlier lap {int(row['LapNumber'])}. Select another driver or rewind before that lap.")
    return ''


def stint_state(cursor: ReplayCursor, prior: Prior, corr: Corrections, lap: Optional[int] = None) -> Optional[StintState]:
    v = cursor.visible(lap)
    if v.empty:
        return None
    last = v.iloc[-1]
    if missing_tyre_fields(last):
        return None
    stint = int(last['Stint'])
    s = v[v['Stint'] == stint]
    kept = kept_mask(s, corr)
    y = corrected_loss(s, corr); age = s['TyreLife'].to_numpy(dtype=float)
    events = []
    for _, r in s.iterrows():
        if r['pit_out']:
            compound = r['Compound']
            detail = f'new {compound.lower()}' if isinstance(compound, str) and compound.strip() else 'tyre compound unavailable'
            events.append(dict(lap=int(r['LapNumber']), kind='pit_exit', detail=detail))
        if r['pit_in']: events.append(dict(lap=int(r['LapNumber']), kind='pit_entry', detail='box'))
        if not r['green']: events.append(dict(lap=int(r['LapNumber']), kind='track_status', detail=f"status {r['TrackStatus']}"))
    xk, yk = age[kept], y[kept]
    a, b, se = _ols(xk, yk) if kept.sum() >= MIN_FIT_LAPS else (math.nan, math.nan, math.nan)
    # intercept: fitted fresh-tyre value; with too few laps anchor on the first kept lap using the prior slope
    if math.isnan(a):
        # too few kept laps for a fit: anchor the fresh-tyre value on the best corrected lap so far under the prior slope
        if kept.sum() >= 1:
            a = float(np.min(yk - (prior.slope or 0.0) * xk))
        elif np.any(np.isfinite(y) & np.isfinite(age)):
            finite = np.isfinite(y) & np.isfinite(age)
            a = float(np.min(y[finite] - (prior.slope or 0.0) * age[finite]))
        else:
            a = None
    losses = (y - a) if a is not None else y * math.nan
    # PLACEHOLDER posterior: precision-weighted prior and OLS slope
    post, post_sd = prior.slope, prior.sd
    if not math.isnan(b) and prior.slope is not None and prior.sd:
        w0, w1 = 1 / prior.sd ** 2, 1 / max(se, 1e-4) ** 2
        post = (prior.slope * w0 + b * w1) / (w0 + w1); post_sd = math.sqrt(1 / (w0 + w1))
    elif not math.isnan(b):
        post, post_sd = b, se
    k = int(last['LapNumber'])
    recent = [e for e in events if k - e['lap'] < WIDEN_LAPS]
    widened = bool(recent) and post_sd is not None
    if widened:
        post_sd = post_sd * corr.widen_factor
    reason = ', '.join(sorted({f"{e['kind']} lap {e['lap']}" for e in recent}))
    trend = (post / prior.slope) if (post is not None and prior.slope) else None
    return StintState(lap=k, stint=stint, compound=str(last['Compound']), tyre_age=int(last['TyreLife']), laps_in_stint=len(s), kept_laps=int(kept.sum()),
                      ages=list(map(float, xk)), losses=list(map(float, losses[kept])) if a is not None else [], all_ages=list(map(float, age)), all_losses=list(map(float, losses)) if a is not None else [],
                      all_kept=list(map(bool, kept)), fitted_intercept=a, ols_slope=None if math.isnan(b) else float(b), ols_se=None if math.isnan(se) else float(se),
                      post_slope=post, post_sd=post_sd, widened=widened, widen_reason=reason, trend_vs_prior=trend,
                      pace_loss_now=float(losses[-1]) if a is not None and len(losses) else None, events_in_stint=events)


def comparable_traces(cursor: ReplayCursor, compound: str, corr: Corrections, lap: Optional[int] = None, max_traces: int = 8) -> list[dict]:
    """Other drivers' stints on the same compound through lap k, as faint traces (loss vs their own first kept lap)."""
    o = cursor.others_visible(lap)
    out = []
    for (drv, stint), s in o[o['Compound'] == compound].groupby(['Driver', 'Stint']):
        s = s.sort_values('LapNumber')
        kept = kept_mask(s, corr)
        if kept.sum() < MIN_FIT_LAPS:
            continue
        y = corrected_loss(s, corr)[kept]; age = s['TyreLife'].to_numpy(dtype=float)[kept]
        out.append(dict(driver=drv, ages=list(map(float, age)), losses=list(map(float, y - y[0])), n=int(kept.sum())))
        if len(out) >= max_traces:
            break
    return out


def feed_quality(row: Optional[pd.Series]) -> dict:
    if row is None:
        return dict(status='NO FEED', telemetry_ok=False, pos_distinct=None, stale_share=None, n_tel=None, missing_channels=['tyre pressure', 'tyre temperature', 'brake temperature'])
    ok = bool(row.get('pos_distinct', 0) >= 100)
    return dict(status='OK' if ok else 'DEGRADED', telemetry_ok=ok, pos_distinct=int(row['pos_distinct']) if pd.notna(row.get('pos_distinct')) else None,
                stale_share=float(row['stale_share']) if pd.notna(row.get('stale_share')) else None, n_tel=int(row['n_tel']) if pd.notna(row.get('n_tel')) else None,
                missing_channels=['tyre pressure', 'tyre temperature', 'brake temperature'])


def race_stints(event: str, driver: str) -> list[dict]:
    """Actual strategy of a driver from the recorded race (post-race information: Ghost Strategy only)."""
    df = load_race(event)
    if df is None:
        return []
    d = df[df['Driver'] == driver]
    out = []
    for stint, s in d.groupby('Stint'):
        out.append(dict(stint=int(stint), compound=str(s['Compound'].iloc[0]), first_lap=int(s['LapNumber'].min()), last_lap=int(s['LapNumber'].max()), laps=int(len(s))))
    return out


def track_temp_series(cursor: ReplayCursor, lap: Optional[int] = None) -> list[tuple[int, float]]:
    v = cursor.visible(lap)
    return [(int(r['LapNumber']), float(r['track_temp'])) for _, r in v.iterrows() if pd.notna(r['track_temp'])]
