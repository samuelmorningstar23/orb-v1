"""Pre-race forecasts for any season directory: pipeline.py's leave-one-weekend-out logic with an explicit factor pool.

pipeline.py hard-codes feat/ (2026) and learns its transfer factors from all completed weekends. For 2023 to 2025 the
same estimator (model_v2: stint fixed effects + per-compound slope on tyre age, cleaned practice laps) must run on that
season's files, and a sealed weekend's race must never inform the factors used for ANY weekend. This module makes the
pool explicit:

    SeasonForecaster(feat_dir, season, sealed={...})
        .table                          one row per compound-weekend (pre-race fields + race-derived reference fields)
        .forecast(event, pool_events)   the pre-race forecast for `event` with factors from `pool_events` only
        .loo_forecasts(pool_events)     every weekend of the pool forecast with the pool minus itself
        .reference(event)               the race-derived pace-loss reference (obs, obs_se) for scoring only

Per compound of the target weekend (exactly pipeline.py's rules, constants imported from it):
    gate       'ok' when n_prac >= MIN_PRAC and clean >= MIN_SLOPE, else withheld
    factor k   median of the other (pool) weekends' race/practice ratio for the compound, applied only when >= 3 exist
               and a majority sit within +-50 % of the median (pipeline.agree_factor); prediction = clean x k
    fallback   withheld -> median race degradation of the pool's withheld cases (needs >= 2), band = their q10..q90
    band       issued -> pipeline.band (slope noise x factor resampling), then conformal widening: half-widths scaled by
               the 90th percentile of the standardised residuals |obs - pred| / half-width of the pool weekends, each
               of them forecast leave-one-out inside the pool (needs >= 5, else 1.0)
Every read of a pool weekend's race outcome goes through `_pool_rows`, which reports (target, source_event) to the
PoolSpy; tests assert that no sealed event is ever a source (leakage test by construction).
"""
from __future__ import annotations

import glob
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import numpy as np
import pandas as pd

from evaluation import PROTO, COMPS, race_id as _race_id

import model_v2 as M            # noqa: E402
import pipeline as P            # noqa: E402  (importing pipeline runs no pipeline: its main is guarded)
import strategy2 as S           # noqa: E402

warnings.filterwarnings('ignore', category=RuntimeWarning)
MIN_PRAC, MIN_SLOPE = int(P.MIN_PRAC), float(P.MIN_SLOPE)
PRACTICE_SESSIONS = ('FP1', 'FP2', 'FP3')


# ---------------------------------------------------------------- leakage spy

class PoolSpy:
    """Records every (target, source, what) triple where a source weekend's race outcome entered a forecast.
    Targets and sources are race ids ('2024_Monza'), so one spy can serve several seasons without name collisions."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, str]] = []

    def record(self, target: str, sources: Iterable[str], what: str) -> None:
        for s in sources:
            self.records.append((str(target), str(s), what))

    def sources_for(self, target: str) -> set[str]:
        return {s for t, s, _ in self.records if t == target}

    def all_sources(self) -> set[str]:
        return {s for _, s, _ in self.records}


# ---------------------------------------------------------------- loading and per-weekend fits (directory-aware model_v2.load_event)

def load_event_dir(feat_dir: Path | str, ev: str) -> Optional[pd.DataFrame]:
    """model_v2.load_event on a given feature directory (same columns, same derived fields)."""
    fs = sorted(glob.glob(str(Path(feat_dir) / f'{ev}_*.csv')))
    if not fs:
        return None
    d = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    d['clean'] = d['IsAccurate'] & (d['TrackStatus'].astype(str) == '1') & ~d['pit_in'] & ~d['pit_out'] & d['energy_MJ'].notna() & d['Compound'].isin(list(COMPS)) & (~d['deleted'])
    d['stint_id'] = d['session'] + '_' + d['Driver'] + '_' + d['Stint'].fillna(0).astype(int).astype(str)
    d = d.sort_values(['stint_id', 'LapNumber'])
    d['e_fill'] = d['energy_MJ'].fillna(d.groupby('stint_id')['energy_MJ'].transform('median'))
    d['cum_E'] = d.groupby('stint_id')['e_fill'].cumsum() - d['e_fill']
    return d


def events_in(feat_dir: Path | str, require: str = 'FP1') -> list[str]:
    return sorted({os.path.basename(f).split('_')[0] for f in glob.glob(str(Path(feat_dir) / f'*_{require}.csv'))})


def weekend_rows(feat_dir: Path | str, ev: str) -> Optional[tuple[pd.DataFrame, dict[str, Any]]]:
    """pipeline.weekend on a directory: (rows per compound, meta). None when too few clean practice laps."""
    d = load_event_dir(feat_dir, ev)
    if d is None:
        return None
    sessions = sorted(d['session'].unique())
    has_race = 'R' in sessions
    p, evo = M.prep_practice(d)
    r = M.prep_race(d) if has_race else d.iloc[0:0]
    if len(p) < 40:
        return None
    A, A_se, A_rs, _ = M.fit(p, 'TyreLife')
    A3, A3_se, beta_p, beta_p_se = P.fit_push(p)
    pn = p.dropna(subset=['TyreLife', 'lap_s'])
    naive = {c: float(np.polyfit(pn.loc[pn.Compound == c, 'TyreLife'], pn.loc[pn.Compound == c, 'lap_s'], 1)[0]) for c in COMPS if (pn.Compound == c).sum() >= 8}
    race: dict[str, Any] = {}
    race_unusable = bool(has_race and len(r) < 80)
    if has_race and len(r) >= 80:
        RA, RA_se, RA_rs, _ = M.fit(r, 'TyreLife')
        tel_ok = r['energy_source'].iloc[0] == 'telemetry'
        race = dict(obs=RA, obs_se=RA_se, resid_sd=float(RA_rs), n=int(len(r)), stints=int(r.stint_id.nunique()), telemetry=('telemetry' if tel_ok else 'degraded: energy pace-estimated'),
                    reference_all={c: dict(obs=float(RA[c]), obs_se=float(RA_se[c]), n_race=int((r.Compound == c).sum())) for c in RA})
    rows = []
    for c in COMPS:
        if c not in A:
            continue
        n = int((p.Compound == c).sum())
        rows.append(dict(event=ev, compound=c, n_prac=n, naive=naive.get(c, np.nan), clean=A[c], clean_se=A_se[c], push_adj=A3.get(c, np.nan), push_adj_se=A3_se.get(c, np.nan),
                         energy_trend=P.energy_trend(p, c), obs=race['obs'].get(c, np.nan) if race else np.nan, obs_se=race['obs_se'].get(c, np.nan) if race else np.nan,
                         n_race=int((r.Compound == c).sum()) if len(r) else 0))
    race_df = d[d['session'] == 'R']
    offs, offs_src = S.offsets_from_sessions(d)
    meta = dict(event=ev, sessions=sessions, format=('sprint' if ('S' in sessions or 'SQ' in sessions or 'SS' in sessions) else 'conventional'), completed=bool(race), race_unusable=race_unusable,
                practice_laps_clean=int(len(p)), practice_runs=int(p.stint_id.nunique()), practice_resid_sd=float(A_rs), evolution_s_per_min={k: float(v) for k, v in evo.items()},
                n_laps=(int(race_df['LapNumber'].max()) if len(race_df) else None), offsets=offs, offsets_source=offs_src,
                track_temp={s: float(d.loc[d.session == s, 'track_temp'].iloc[0]) for s in sessions if (d.session == s).any()},
                rain={s: bool(d.loc[d.session == s, 'rain'].iloc[0]) for s in sessions if (d.session == s).any()},
                race=({k: v for k, v in race.items() if k in ('n', 'stints', 'telemetry', 'resid_sd')} if race else None),
                reference_all=(race.get('reference_all', {}) if race else {}),
                drivers_race=(sorted(race_df['Driver'].unique().tolist()) if len(race_df) else []))
    return pd.DataFrame(rows), meta


# ---------------------------------------------------------------- the forecaster

@dataclass
class CompoundForecast:
    """Pre-race fields only (what the live path and the hidden-stop test may see)."""
    compound: str
    n_prac: int
    naive: float
    clean: float
    clean_se: float
    gate: str
    issued: bool
    factor: float
    factor_applied: bool
    factor_from_n_weekends: int
    floor: Optional[float]
    prediction: Optional[float]
    band90_raw: Optional[list[float]]
    band90: Optional[list[float]]
    widen: float
    basis: str
    push_adj: Optional[float] = None
    energy_trend: Optional[float] = None

    def as_dict(self) -> dict[str, Any]:
        return {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in self.__dict__.items()}

    @property
    def slope_sd(self) -> Optional[float]:
        """Normal sd implied by the 90 % band: (hi - lo) / (2 x 1.6449)."""
        if not self.band90 or any(v is None or not np.isfinite(v) for v in self.band90):
            return None
        return float((self.band90[1] - self.band90[0]) / (2.0 * 1.6448536269514722))


@dataclass
class WeekendForecast:
    season: int
    event: str
    race_id: str
    n_laps: Optional[int]
    offsets: dict[str, float]
    offsets_source: dict[str, str]
    compounds: dict[str, CompoundForecast]
    pool_events: list[str]
    meta: dict[str, Any] = field(default_factory=dict)

    def slopes(self) -> dict[str, float]:
        """Point forecast per compound (issued x factor, or the fallback floor); compounds without a prediction are absent."""
        return {c: float(f.prediction) for c, f in self.compounds.items() if f.prediction is not None and np.isfinite(f.prediction)}

    def naive_slopes(self) -> dict[str, float]:
        return {c: float(f.naive) for c, f in self.compounds.items() if f.naive is not None and np.isfinite(f.naive)}

    def as_dict(self) -> dict[str, Any]:
        return dict(season=self.season, event=self.event, race_id=self.race_id, n_laps=self.n_laps, offsets=self.offsets, offsets_source=self.offsets_source,
                    compounds={c: f.as_dict() for c, f in self.compounds.items()}, pool_events=list(self.pool_events), pool_n=len(self.pool_events))


class SeasonForecaster:
    """All weekends of one season directory; forecasts with an explicit factor pool; a spy on every pool read."""

    def __init__(self, feat_dir: Path | str, season: int, sealed: Iterable[str] = (), spy: Optional[PoolSpy] = None,
                 min_prac: int = MIN_PRAC, min_slope: float = MIN_SLOPE, events: Optional[Iterable[str]] = None):
        self.feat_dir = Path(feat_dir)
        self.season = int(season)
        self.sealed = {s.split('_', 1)[1] if '_' in s and s.split('_', 1)[0].isdigit() else s for s in sealed}    # event names of this season's sealed weekends
        self.sealed_ids = {s for s in sealed}
        self.spy = spy or PoolSpy()
        self.min_prac, self.min_slope = int(min_prac), float(min_slope)
        self.metas: dict[str, dict[str, Any]] = {}
        tables = []
        for ev in (list(events) if events is not None else events_in(self.feat_dir)):
            w = weekend_rows(self.feat_dir, ev)
            if w is None:
                continue
            t, meta = w
            tables.append(t)
            self.metas[ev] = meta
        self.table = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame(columns=['event', 'compound', 'n_prac', 'naive', 'clean', 'clean_se', 'push_adj', 'push_adj_se', 'energy_trend', 'obs', 'obs_se', 'n_race'])
        self.table['completed'] = self.table['event'].map(lambda e: bool(self.metas[e]['completed']))
        self._z_cache: dict[tuple[str, ...], pd.Series] = {}
        self.set_gate(self.min_prac, self.min_slope)

    def set_gate(self, min_prac: int, min_slope: float) -> None:
        """Re-derive the abstention gate (issued / gate / ratio columns) for a threshold sweep; caches are cleared."""
        self.min_prac, self.min_slope = int(min_prac), float(min_slope)
        t = self.table
        t['issued'] = (t['n_prac'] >= self.min_prac) & (t['clean'] >= self.min_slope)
        t['gate'] = np.where(t['n_prac'] < self.min_prac, 'too few clean practice laps', np.where(t['clean'] < self.min_slope, 'no positive degradation signal in cleaned practice', 'ok'))
        t['ratio'] = np.where(t['issued'] & t['completed'], t['obs'] / t['clean'], np.nan)
        self._z_cache = {}

    # ------------------------------------------------------------ pools
    @property
    def events(self) -> list[str]:
        return sorted(self.metas)

    @property
    def completed_events(self) -> list[str]:
        return sorted(e for e, m in self.metas.items() if m['completed'])

    @property
    def development_events(self) -> list[str]:
        """Completed weekends that are not sealed: the only weekends whose race outcomes may ever enter a factor pool."""
        return [e for e in self.completed_events if e not in self.sealed]

    def scorable(self, pool_events: Iterable[str]) -> pd.DataFrame:
        pool = set(pool_events)
        bad = pool & self.sealed
        if bad:
            raise PermissionError(f'sealed weekends offered as a factor pool: {sorted(bad)}')
        V = self.table[self.table['completed'] & self.table['obs'].notna() & self.table['event'].isin(pool)]
        return V

    def rid(self, event: str) -> str:
        return _race_id(self.season, event)

    def _pool_rows(self, target: str, pool_events: Iterable[str], what: str, compound: Optional[str] = None, issued: Optional[bool] = None) -> pd.DataFrame:
        """Rows of the pool (never the target, never a sealed weekend) whose race outcome is about to be read."""
        V = self.scorable(pool_events)
        V = V[V['event'] != target]
        if compound is not None:
            V = V[V['compound'] == compound]
        if issued is not None:
            V = V[V['issued'] == issued]
        self.spy.record(self.rid(target), [self.rid(e) for e in V['event'].unique().tolist()], what)
        return V

    # ------------------------------------------------------------ forecasts
    def _raw_forecast(self, target: str, pool_events: list[str], compute_band: bool = True) -> dict[str, CompoundForecast]:
        rows = self.table[self.table['event'] == target]
        out: dict[str, CompoundForecast] = {}
        for _, row in rows.iterrows():
            c = row['compound']
            issued = bool(row['issued'])
            others = self._pool_rows(target, pool_events, 'ratio', compound=c, issued=True)['ratio'].dropna()
            k, applied = P.agree_factor(others)
            wh = self._pool_rows(target, pool_events, 'withheld_obs', issued=False)['obs'].dropna()
            floor = float(wh.median()) if len(wh) >= 2 else None
            if issued:
                pred = float(row['clean'] * k)
                lo_hi = P.band(float(row['clean']), float(row['clean_se']), others, applied) if compute_band else None
                basis = 'cleaned Friday curve x season transfer factor' if applied else 'cleaned Friday curve (weekends disagree on the factor)'
            else:
                pred = floor
                lo_hi = [float(wh.quantile(0.1)), float(wh.quantile(0.9))] if len(wh) >= 3 else None
                basis = f'low-degradation fallback: median race degradation of the {int(len(wh))} withheld cases in the pool' if floor is not None else 'no forecast: fewer than 2 withheld cases in the pool'
            out[c] = CompoundForecast(compound=c, n_prac=int(row['n_prac']), naive=float(row['naive']), clean=float(row['clean']), clean_se=float(row['clean_se']), gate=str(row['gate']), issued=issued,
                                      factor=float(k), factor_applied=bool(applied), factor_from_n_weekends=int(others.notna().sum()), floor=floor, prediction=pred,
                                      band90_raw=(list(lo_hi) if lo_hi is not None else None), band90=(list(lo_hi) if lo_hi is not None else None), widen=1.0, basis=basis,
                                      push_adj=float(row['push_adj']) if np.isfinite(row['push_adj']) else None, energy_trend=float(row['energy_trend']) if np.isfinite(row['energy_trend']) else None)
        return out

    def pool_z(self, pool_events: list[str]) -> pd.Series:
        """Standardised residual of every pool row forecast leave-one-out inside the pool (no widening): |obs - pred| / half-width."""
        key = tuple(sorted(pool_events))
        if key in self._z_cache:
            return self._z_cache[key]
        V = self.scorable(pool_events)
        z = {}
        for ev in sorted(V['event'].unique()):
            others = [e for e in pool_events if e != ev]
            fc = self._raw_forecast(ev, others)
            for _, row in V[V['event'] == ev].iterrows():
                f = fc.get(row['compound'])
                if f is None or f.prediction is None or f.band90_raw is None:
                    continue
                half = (f.band90_raw[1] - f.band90_raw[0]) / 2.0
                z[(ev, row['compound'])] = abs(float(row['obs']) - f.prediction) / half if half > 0 else np.nan
        s = pd.Series(z, dtype=float)
        self._z_cache[key] = s
        return s

    def forecast(self, event: str, pool_events: Iterable[str], target_obs_in_widening: bool = False) -> WeekendForecast:
        """The pre-race forecast for `event` with factors, fallback floor and widening learned from `pool_events` only.

        target_obs_in_widening=True reproduces pipeline.py for a completed development weekend: the pool rows'
        standardised residuals are each obtained leave-one-out inside a pool that still contains the target's own
        race (a second-order effect on the band width only). The sealed evaluator and the rolling-origin series use
        the strict default (False): nothing about the target's race touches its forecast, and a sealed weekend is
        refused as a member of any z pool."""
        if event not in self.metas:
            raise KeyError(f'{event}: no weekend table in {self.feat_dir.name} (too few clean practice laps or no files)')
        pool = [e for e in pool_events if e != event]
        bad = set(pool) & self.sealed
        if bad:
            raise PermissionError(f'sealed weekends offered as a factor pool for {event}: {sorted(bad)}')
        comps = self._raw_forecast(event, pool)
        if target_obs_in_widening:
            if event in self.sealed or not self.metas[event]['completed']:
                raise PermissionError(f'{event}: its own race outcome may not inform the widening (sealed or not completed)')
            z = self.pool_z(sorted(pool + [event]))
        else:
            z = self.pool_z(pool)
        z_other = z[[k for k in z.index if k[0] != event]].dropna() if len(z) else z
        self.spy.record(self.rid(event), sorted({self.rid(k[0]) for k in z_other.index}), 'widening_z')
        w = float(np.percentile(z_other, 90)) if len(z_other) >= 5 else 1.0
        for c, f in comps.items():
            f.widen = w
            if f.prediction is not None and f.band90_raw is not None:
                lo, hi = f.band90_raw
                f.band90 = [f.prediction - w * (f.prediction - lo), f.prediction + w * (hi - f.prediction)]
        meta = self.metas[event]
        return WeekendForecast(season=self.season, event=event, race_id=_race_id(self.season, event), n_laps=meta['n_laps'], offsets=dict(meta['offsets']), offsets_source=dict(meta['offsets_source']),
                               compounds=comps, pool_events=sorted(pool), meta=meta)

    def loo_forecasts(self, pool_events: Optional[Iterable[str]] = None, pipeline_widening: bool = True) -> dict[str, WeekendForecast]:
        """Every weekend of the pool forecast with the pool minus itself (the development-pool scoring). With
        pipeline_widening (default) the band widening is exactly pipeline.py's (see forecast()); never for sealed weekends."""
        pool = list(pool_events) if pool_events is not None else self.development_events
        return {ev: self.forecast(ev, [e for e in pool if e != ev], target_obs_in_widening=pipeline_widening) for ev in pool}

    # ------------------------------------------------------------ the post-race reference (scoring only)
    def reference(self, event: str) -> dict[str, dict[str, float]]:
        """Race-derived pace-loss reference (model_v2.fit on the race, all drivers) for every compound the race fit carries,
        including compounds without a practice row: {compound: {obs, obs_se, n_race}}. Post-race material, scoring only."""
        return {c: dict(v) for c, v in self.metas[event].get('reference_all', {}).items()}

    def race_path(self, event: str) -> Path:
        return self.feat_dir / f'{event}_R.csv'


# ---------------------------------------------------------------- scoring helpers

def score_forecast(fc: WeekendForecast, reference: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    """One record per compound with a reference: forecast error, naive error, band coverage (post-race scoring)."""
    out = []
    for c, f in fc.compounds.items():
        ref = reference.get(c)
        if ref is None:
            continue
        obs = ref['obs']
        pred = f.prediction
        lo, hi = (f.band90 if f.band90 else (None, None))
        out.append(dict(race_id=fc.race_id, season=fc.season, event=fc.event, compound=c, issued=f.issued, gate=f.gate, n_prac=f.n_prac, naive=f.naive, clean=f.clean, prediction=pred,
                        band90=([lo, hi] if lo is not None else None), obs=obs, obs_se=ref['obs_se'], n_race=ref['n_race'],
                        err=(abs(pred - obs) if pred is not None else None), err_naive=(abs(f.naive - obs) if np.isfinite(f.naive) else None),
                        err_clean=(abs(f.clean - obs) if f.issued else None), covered=((lo <= obs <= hi) if lo is not None else None), widen=f.widen,
                        factor=f.factor, factor_applied=f.factor_applied, pool_n=len(fc.pool_events)))
    return out


__all__ = ['PoolSpy', 'SeasonForecaster', 'WeekendForecast', 'CompoundForecast', 'weekend_rows', 'load_event_dir', 'events_in', 'score_forecast', 'MIN_PRAC', 'MIN_SLOPE']
