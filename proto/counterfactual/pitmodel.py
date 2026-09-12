"""The standardised pit event as a distribution (roadmap v5 task 0.4).

A stop is booked over four laps of the counterfactual car:
    in-lap  L    : share_in x transit x f(L)
    out-lap L+1  : (1 - share_in) x transit x f(L+1) + stationary x g(L+1)
    lap     L+2  : compound out-lap penalty  (first kept lap of a stint vs the second)
    lap     L+3  : warm-up residual on the next lap (second kept lap vs the third)
with f = 1 under green / yellow, SC_FACTOR under SC or VSC (the field circulates slowly, so the pit lane costs less
relative to it), 0 under a red flag (the change happens during the stoppage; g likewise 0 under red, else 1).

Where each number comes from (all measured on fuel-corrected lap times y, field-relative, see racedata.py):
  transit loss      median over the race's green-flag stops of (in-lap excess + out-lap excess) minus the stationary
                    median 2.5 s. Requires MIN_STOPS green stops; below that the season pool over every race file on
                    disk is used (2026 pool: 205 stops, median 21.77 s, MAD 1.66 s) and a warning is recorded. The v1
                    lock's strategy assumption pit_loss = 21.0 s is reported alongside for comparison, never used
                    silently. Sampling: normal, sd = 1.4826 x MAD of the stops used (floor 0.8 s).
  share_in          median in-lap excess / median total excess of the stops used (about 0.2: most of the loss shows
                    on the out-lap in this timing convention), clamped to [0.05, 0.6].
  stationary        median 2.5 s, q10 2.1 s, q90 3.4 s (2026 pit-stop times: a routine stop is 2.2-2.8 s, a slow one
                    3-4 s); sampled from a split normal matching those three quantiles. Stated assumption.
  out-lap penalty   per compound: median over stints that start with a green pit-out lap of y(first kept lap) -
                    y(second kept lap); the kept laps are the first three clean consecutive green laps after the
                    out-lap. Falls back: race pooled over compounds -> season pool per compound -> season pooled.
  warm-up residual  y(second kept lap) - y(third kept lap), same stints, same fallbacks.
  SC factor         0.55 of the green transit loss by default (a stop under SC/VSC is commonly quoted at about half
                    a green stop). The race's own SC/VSC stops give a measured ratio which is reported; pass
                    sc_factor='measured' to use it.
Every fallback is written into `derivation` so the summary can show where each number came from.
"""
from __future__ import annotations

import glob
import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import numpy as np

from counterfactual import PROTO
from counterfactual.racedata import RaceData, load_race, COMPS

MIN_STOPS = 4                 # green-flag stops needed before a race's own transit loss is used
MIN_STINTS = 3                # stints needed per compound for an out-lap penalty
STATIONARY_Q = (2.1, 2.5, 3.4)
Z80 = 1.2815515655446004      # 90th percentile of the standard normal (for the q10/q90 split-normal match)
SC_FACTOR_DEFAULT = 0.55
LOCK_PIT_LOSS = 21.0          # strategy2.PIT_LOSS: the pre-race plan's total stop assumption (transit + stationary)
POOL_CACHE = PROTO / 'out' / 'counterfactual' / '_pit_pool_cache.json'


def _mad_sd(vals: np.ndarray, floor: float) -> float:
    v = np.asarray(vals, dtype=float)
    v = v[np.isfinite(v)]
    if v.size < 2:
        return floor
    return float(max(1.4826 * np.median(np.abs(v - np.median(v))), floor))


# ---------------------------------------------------------------- measurement on one race

def measure_stops(R: RaceData) -> list[dict[str, Any]]:
    """Green-flag stops (in-lap and out-lap both GREEN, measured) and SC/VSC stops, field-relative excesses."""
    out = []
    for drv in R.drivers:
        d = R.driver(drv)
        for s in d.stops:
            if s.free or not s.measured:
                continue
            kind = 'green' if (s.label_in == 'GREEN' and s.label_out == 'GREEN') else ('sc' if (s.label_in in ('SC', 'VSC') or s.label_out in ('SC', 'VSC')) else 'yellow')
            out.append(dict(event=R.event, driver=drv, in_lap=s.in_lap, kind=kind, meas_in=float(s.meas_in), meas_out=float(s.meas_out), total=float(s.meas_in + s.meas_out),
                            from_compound=s.from_compound, to_compound=s.to_compound))
    return out


def measure_outlaps(R: RaceData) -> list[dict[str, Any]]:
    """Stints that start with a green pit-out lap present: penalty = y(kept1) - y(kept2), warm-up = y(kept2) - y(kept3)."""
    out = []
    for drv in R.drivers:
        d = R.driver(drv)
        for st in d.stints[1:]:
            L = st.start_lap                       # the out-lap
            if L > d.n or not d.present[L - 1] or d.label[L - 1] != 'GREEN' or not d.pit_out[L - 1]:
                continue
            kept = [i for i in range(L, d.n) if d.ok[i]]        # 0-based indices of laps after the out-lap
            if len(kept) < 3 or kept[1] != kept[0] + 1 or kept[2] != kept[1] + 1:
                continue
            y = d.y
            out.append(dict(event=R.event, driver=drv, out_lap=L, compound=st.compound, first_kept_lap=kept[0] + 1,
                            penalty=float(y[kept[0]] - y[kept[1]]), warmup=float(y[kept[1]] - y[kept[2]])))
    return out


# ---------------------------------------------------------------- season pool (every race file on disk), cached

def _race_files(feat_dir: Path) -> list[Path]:
    return sorted(Path(p) for p in glob.glob(str(feat_dir / '*_R.csv')))


def season_pool(feat_dir: Path | None = None, cache_path: Path | None = None) -> dict[str, Any]:
    """{'stops': [...], 'outlaps': [...], 'files': {name: mtime}} over all race files; cached on disk by file mtimes."""
    feat_dir = feat_dir or PROTO / 'feat'
    cache_path = cache_path or POOL_CACHE
    files = _race_files(feat_dir)
    key = {f.name: os.path.getmtime(f) for f in files}
    if cache_path.exists():
        try:
            with open(cache_path, 'r', encoding='utf-8') as fh:
                cached = json.load(fh)
            if cached.get('files') == key:
                return cached
        except (OSError, json.JSONDecodeError):
            pass
    stops, outlaps = [], []
    for f in files:
        ev = f.name[:-len('_R.csv')]
        try:
            R = load_race(ev, str(f))
        except Exception:                       # a malformed file must not poison the pool
            continue
        stops.extend(measure_stops(R))
        outlaps.extend(measure_outlaps(R))
    pool = dict(files=key, stops=stops, outlaps=outlaps)
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        from shared.lockio import atomic_write_json
        atomic_write_json(cache_path, pool)
    except Exception:
        pass
    return pool


# ---------------------------------------------------------------- the model

@dataclass
class PitEventModel:
    event: str
    transit_med: float
    transit_sd: float
    share_in: float
    stationary_q: tuple[float, float, float]
    outlap_pen: dict[str, float]
    outlap_pen_sd: dict[str, float]
    warmup: dict[str, float]
    warmup_sd: dict[str, float]
    sc_factor: float
    sc_factor_measured: Optional[float]
    derivation: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def stationary_med(self) -> float:
        return self.stationary_q[1]

    @property
    def total_green_median(self) -> float:
        """Median total loss of a standardised green stop before out-lap penalty and warm-up."""
        return self.transit_med + self.stationary_med

    def stationary_samples(self, rng: np.random.Generator, n: int) -> np.ndarray:
        """Split normal: median m, lower sd from q10, upper sd from q90."""
        q10, m, q90 = self.stationary_q
        sd_lo, sd_hi = (m - q10) / Z80, (q90 - m) / Z80
        z = rng.standard_normal(n)
        return m + np.where(z < 0, sd_lo, sd_hi) * z

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d['stationary_q'] = list(self.stationary_q)
        d['total_green_median'] = self.total_green_median
        d['lock_pit_loss_for_comparison'] = LOCK_PIT_LOSS
        return d

    @classmethod
    def build(cls, R: RaceData, sc_factor: float | str = SC_FACTOR_DEFAULT, pool: Optional[dict[str, Any]] = None, use_pool: bool = True,
              min_stops: int = MIN_STOPS, min_stints: int = MIN_STINTS) -> 'PitEventModel':
        warnings: list[str] = []
        deriv: dict[str, Any] = {}
        stops = measure_stops(R)
        green = [s for s in stops if s['kind'] == 'green']
        sc = [s for s in stops if s['kind'] == 'sc']
        deriv['race_green_stops'] = [dict(driver=s['driver'], in_lap=s['in_lap'], in_excess_s=round(s['meas_in'], 3), out_excess_s=round(s['meas_out'], 3), total_s=round(s['total'], 3)) for s in green]
        deriv['race_sc_stops'] = [dict(driver=s['driver'], in_lap=s['in_lap'], total_s=round(s['total'], 3)) for s in sc]
        pool = pool if pool is not None else (season_pool() if use_pool else dict(stops=[], outlaps=[]))
        pool_green = [s for s in pool.get('stops', []) if s['kind'] == 'green']
        pool_tot = np.array([s['total'] for s in pool_green]) if pool_green else np.array([])
        deriv['season_pool'] = dict(n_green_stops=int(len(pool_green)), n_races=len({s['event'] for s in pool_green}),
                                    median_total_s=float(np.median(pool_tot)) if pool_tot.size else None, mad_s=float(np.median(np.abs(pool_tot - np.median(pool_tot)))) if pool_tot.size else None)
        # ---- transit
        if len(green) >= min_stops:
            tot = np.array([s['total'] for s in green])
            ins = np.array([s['meas_in'] for s in green])
            transit_med = float(np.median(tot)) - STATIONARY_Q[1]
            transit_sd = _mad_sd(tot, 0.8)
            share_in = float(np.median(ins) / np.median(tot)) if np.median(tot) > 0 else 0.2
            deriv['transit'] = dict(source='race', n=len(green), median_total_s=float(np.median(tot)), stationary_subtracted_s=STATIONARY_Q[1], transit_s=transit_med, sd_s=transit_sd)
        elif pool_tot.size >= min_stops:
            ins = np.array([s['meas_in'] for s in pool_green])
            transit_med = float(np.median(pool_tot)) - STATIONARY_Q[1]
            transit_sd = _mad_sd(pool_tot, 0.8)
            share_in = float(np.median(ins) / np.median(pool_tot))
            deriv['transit'] = dict(source='season_pool', n=int(pool_tot.size), median_total_s=float(np.median(pool_tot)), stationary_subtracted_s=STATIONARY_Q[1], transit_s=transit_med, sd_s=transit_sd,
                                    race_measured_but_too_few=[round(s['total'], 2) for s in green])
            warnings.append(f'pit transit loss: only {len(green)} green-flag stop(s) measurable in {R.event} (< {min_stops}); season pool of {int(pool_tot.size)} stops used (median total {float(np.median(pool_tot)):.2f} s)')
        else:
            transit_med, transit_sd, share_in = LOCK_PIT_LOSS - STATIONARY_Q[1], 1.5, 0.2
            deriv['transit'] = dict(source='lock_pit_loss', n=0, transit_s=transit_med, sd_s=transit_sd)
            warnings.append(f'pit transit loss: no measurable stops; v1 lock pit_loss {LOCK_PIT_LOSS} s used')
        share_in = float(min(max(share_in, 0.05), 0.6))
        # ---- out-lap penalty and warm-up
        ol = measure_outlaps(R)
        pool_ol = pool.get('outlaps', [])
        deriv['race_outlap_stints'] = [dict(driver=o['driver'], out_lap=o['out_lap'], compound=o['compound'], penalty_s=round(o['penalty'], 3), warmup_s=round(o['warmup'], 3)) for o in ol]
        pen, pen_sd, warm, warm_sd = {}, {}, {}, {}
        src: dict[str, dict[str, Any]] = {}
        for c in COMPS:
            for label, rows in (('race_compound', [o for o in ol if o['compound'] == c]), ('race_pooled_compounds', ol),
                                ('season_pool_compound', [o for o in pool_ol if o['compound'] == c]), ('season_pool_pooled', pool_ol)):
                if len(rows) >= min_stints:
                    p = np.array([o['penalty'] for o in rows])
                    w = np.array([o['warmup'] for o in rows])
                    pen[c], pen_sd[c] = float(np.median(p)), _mad_sd(p, 0.15)
                    warm[c], warm_sd[c] = float(np.median(w)), _mad_sd(w, 0.10)
                    src[c] = dict(source=label, n=len(rows))
                    break
            else:
                pen[c], pen_sd[c], warm[c], warm_sd[c] = 0.3, 0.3, 0.05, 0.15
                src[c] = dict(source='assumption', n=0)
                warnings.append(f'out-lap penalty for {c}: no stints measurable anywhere; assumption 0.3 s (+/- 0.3) and warm-up 0.05 s used')
            if src[c]['source'] != 'race_compound':
                warnings.append(f'out-lap penalty for {c}: {src[c]["source"]} (n={src[c]["n"]}) used, fewer than {min_stints} green pit-out stints on {c} in {R.event}')
        deriv['outlap_sources'] = src
        # ---- SC factor
        measured = None
        if sc and transit_med > 0:
            measured = float(np.median([s['total'] for s in sc]) - STATIONARY_Q[1]) / transit_med
            deriv['sc_factor_measured'] = dict(ratio=measured, n_sc_stops=len(sc), note='(median SC/VSC stop total - stationary) / green transit; SC laps are field-relative already')
        if sc_factor == 'measured':
            if measured is None:
                warnings.append(f'sc_factor=measured requested but {R.event} has no SC/VSC stops; default {SC_FACTOR_DEFAULT} used')
                factor = SC_FACTOR_DEFAULT
            else:
                factor = float(min(max(measured, 0.1), 1.0))
        else:
            factor = float(sc_factor)
        deriv['sc_factor'] = dict(used=factor, default=SC_FACTOR_DEFAULT, rule='transit loss x factor when the in-lap or out-lap falls on an SC/VSC lap; 0 under red flag')
        deriv['stationary'] = dict(q10=STATIONARY_Q[0], median=STATIONARY_Q[1], q90=STATIONARY_Q[2], source='stated assumption (2026 stop times), split-normal sampling')
        return cls(event=R.event, transit_med=transit_med, transit_sd=transit_sd, share_in=share_in, stationary_q=STATIONARY_Q, outlap_pen=pen, outlap_pen_sd=pen_sd,
                   warmup=warm, warmup_sd=warm_sd, sc_factor=factor, sc_factor_measured=measured, derivation=deriv, warnings=warnings)


__all__ = ['PitEventModel', 'measure_stops', 'measure_outlaps', 'season_pool', 'MIN_STOPS', 'MIN_STINTS', 'STATIONARY_Q', 'SC_FACTOR_DEFAULT', 'LOCK_PIT_LOSS']
