"""Canonical closed track path and pit-lane polyline from pooled race position samples (roadmap v5 task 0.5).

Track path
    1. gate drivers on feed quality (median distinct points per lap >= 100) and keep clean laps (accurate, green, no pit flags)
    2. drop stale repeats (step < 1 m), pick a seed lap (best-sampled among the fastest quartile), resample it at 2 m
    3. project every pooled sample onto the seed, take the median x/y per ~10 m arc-length bin, smooth circularly,
       re-parametrise by arc length onto a uniform grid s in [0, L) with step L / round(L / 10)  (10 m nominal); iterate once
    4. roll the path so s = 0 is the median position at the timing lap start; sector boundaries are the median positions at the
       sector-1 and sector-2 session times (fallback: sector time fractions); pit flags mark the entry / exit junctions
Pit lane
    from in-lap + out-lap pairs: the run of samples more than 4 m off the path around the pit-in time, pooled the same way,
    with the median recorded transit profile s_pit(tau). Without any recorded excursion a SCHEMATIC offset chord is built and
    labelled so the dashboard can say so.
Coordinates are metres in the feed frame (FastF1 X/Y / 10). Nothing here is a racing-line model: the path is the consensus of
where the cars actually drove, which is what the ghost must be drawn on.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from replay import io as rio
from replay.sources import PositionSource, MIN_DISTINCT_PER_LAP, STALE_STEP_M, gate_drivers

GRID_M = 10.0                 # nominal arc-length grid of the track path
SEED_STEP_M = 2.0             # fine resampling of the seed lap for the first projection
PIT_GRID_M = 5.0              # arc-length grid of the pit-lane polyline
PIT_OFFPATH_M = 4.0           # a sample further than this from the path during a stop is on the pit lane
MIN_DRIVERS_FOR_PATH = 3      # a canonical path needs at least this many clean drivers
MIN_CLEAN_LAPS = 5
MIN_BIN_POINTS = 4
SMOOTH_WINDOW = 3             # circular moving-average window (grid points); 3 keeps 100 m-radius arcs within 0.2 m


class QualityRefusal(RuntimeError):
    """Raised when the position feed cannot support a canonical path; carries the meta to write."""

    def __init__(self, reason: str, meta: dict):
        super().__init__(reason)
        self.reason, self.meta = reason, meta


# ---------------------------------------------------------------- polyline primitives

def drop_stale(xy: np.ndarray, step_m: float = STALE_STEP_M) -> np.ndarray:
    """Keep a sample only if it moved at least step_m from the previously kept sample (mask)."""
    n = len(xy)
    keep = np.zeros(n, dtype=bool)
    if n == 0:
        return keep
    keep[0] = True
    last = xy[0]
    for i in range(1, n):
        if math.hypot(xy[i, 0] - last[0], xy[i, 1] - last[1]) >= step_m:
            keep[i] = True
            last = xy[i]
    return keep


def cumulative_length(xy: np.ndarray, closed: bool = False) -> np.ndarray:
    d = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    s = np.concatenate([[0.0], np.cumsum(d)])
    if closed:
        s = np.append(s, s[-1] + math.hypot(xy[0, 0] - xy[-1, 0], xy[0, 1] - xy[-1, 1]))
    return s


def resample_by_arclength(xy: np.ndarray, step: float, closed: bool) -> tuple[np.ndarray, np.ndarray, float]:
    """(s_grid, xy_grid, L). Closed: L is the loop length and the grid covers [0, L) with exactly round(L/step) points."""
    if closed:
        pts = np.vstack([xy, xy[:1]])
    else:
        pts = xy
    s = cumulative_length(pts)
    L = float(s[-1])
    if L <= 0:
        raise ValueError('degenerate polyline')
    n = max(int(round(L / step)), 4)
    grid = np.arange(n) * (L / n) if closed else np.linspace(0.0, L, n + 1)
    x = np.interp(grid, s, pts[:, 0]); y = np.interp(grid, s, pts[:, 1])
    return grid, np.column_stack([x, y]), L


def smooth_circular(xy: np.ndarray, window: int = SMOOTH_WINDOW) -> np.ndarray:
    if window <= 1 or len(xy) < window * 2:
        return xy
    k = np.ones(window) / window
    pad = window // 2
    out = np.empty_like(xy)
    for j in range(2):
        v = np.concatenate([xy[-pad:, j], xy[:, j], xy[:pad, j]])
        out[:, j] = np.convolve(v, k, mode='valid')
    return out


def circular_median(values: np.ndarray, L: float) -> float:
    """Median of values living on a circle of length L (cluster assumed narrower than L/2)."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return float('nan')
    ref = v[0]
    for _ in range(2):
        rel = np.mod(v - ref + L / 2, L) - L / 2
        ref = (ref + float(np.median(rel))) % L
    return float(ref)


class Polyline:
    """Projection helper for an open or closed polyline: nearest point, arc length, interpolation."""

    def __init__(self, xy: np.ndarray, closed: bool):
        self.xy = np.asarray(xy, dtype=float)
        self.closed = closed
        self.n = len(self.xy)
        nxt = np.roll(self.xy, -1, axis=0) if closed else self.xy[1:]
        base = self.xy if closed else self.xy[:-1]
        self.seg = nxt - base
        self.seg_len = np.hypot(self.seg[:, 0], self.seg[:, 1])
        self.s_vertex = np.concatenate([[0.0], np.cumsum(self.seg_len)])   # length n+1 (closed) or n (open)
        self.L = float(self.s_vertex[-1])
        self.tree = cKDTree(self.xy)

    def project(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(s, distance) of the nearest point on the polyline for each query point."""
        q = np.column_stack([np.asarray(x, dtype=float), np.asarray(y, dtype=float)])
        _, j = self.tree.query(q)
        nseg = len(self.seg)
        best_s = np.full(len(q), np.nan); best_d = np.full(len(q), np.inf)
        for cand in (j - 1, j):
            if self.closed:
                c = np.mod(cand, nseg)
            else:
                c = np.clip(cand, 0, nseg - 1)
            base = self.xy[c]; seg = self.seg[c]; ln = self.seg_len[c]
            rel = q - base
            t = np.where(ln > 0, (rel * seg).sum(1) / np.maximum(ln, 1e-12) ** 2, 0.0)
            t = np.clip(t, 0.0, 1.0)
            foot = base + seg * t[:, None]
            d = np.hypot(q[:, 0] - foot[:, 0], q[:, 1] - foot[:, 1])
            better = d < best_d
            best_d[better] = d[better]
            best_s[better] = self.s_vertex[c[better]] + t[better] * ln[better]
        if self.closed:
            best_s = np.mod(best_s, self.L)
        return best_s, best_d

    def xy_at(self, s: np.ndarray) -> np.ndarray:
        s = np.asarray(s, dtype=float)
        if self.closed:
            s = np.mod(s, self.L)
            pts = np.vstack([self.xy, self.xy[:1]])
        else:
            s = np.clip(s, 0.0, self.L)
            pts = self.xy
        return np.column_stack([np.interp(s, self.s_vertex, pts[:, 0]), np.interp(s, self.s_vertex, pts[:, 1])])

    def tangent_at(self, s: np.ndarray) -> np.ndarray:
        eps = 1.0
        a = self.xy_at(np.asarray(s, dtype=float) - eps); b = self.xy_at(np.asarray(s, dtype=float) + eps)
        t = b - a
        n = np.hypot(t[:, 0], t[:, 1])
        return t / np.maximum(n, 1e-9)[:, None]


# ---------------------------------------------------------------- data classes

@dataclass
class TrackPath:
    s: np.ndarray
    x: np.ndarray
    y: np.ndarray
    L: float
    sector: np.ndarray
    pit_entry_flag: np.ndarray
    pit_exit_flag: np.ndarray
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        self._poly = Polyline(np.column_stack([self.x, self.y]), closed=True)

    @property
    def n_points(self) -> int:
        return len(self.s)

    @property
    def grid_m(self) -> float:
        return float(self.L / len(self.s))

    @property
    def polyline(self) -> Polyline:
        return self._poly

    def project(self, x, y) -> tuple[np.ndarray, np.ndarray]:
        return self._poly.project(np.atleast_1d(x), np.atleast_1d(y))

    def xy_at(self, s) -> np.ndarray:
        return self._poly.xy_at(np.atleast_1d(s))

    def sector_fractions(self) -> tuple[float, float]:
        return float(self.meta.get('sector1_end_s', np.nan) / self.L), float(self.meta.get('sector2_end_s', np.nan) / self.L)

    def save(self, directory: str | Path) -> str:
        d = Path(directory); d.mkdir(parents=True, exist_ok=True)
        return rio.save_npz(d / 'track.npz', s=self.s, x=self.x, y=self.y, sector=self.sector.astype(np.int8),
                            pit_entry_flag=self.pit_entry_flag.astype(np.uint8), pit_exit_flag=self.pit_exit_flag.astype(np.uint8), L=np.float64(self.L), meta=self.meta)

    @classmethod
    def load(cls, directory: str | Path) -> 'TrackPath':
        z = rio.load_npz(Path(directory) / 'track.npz')
        return cls(s=z['s'].astype(float), x=z['x'].astype(float), y=z['y'].astype(float), L=float(z['L']), sector=z['sector'].astype(np.int8),
                   pit_entry_flag=z['pit_entry_flag'].astype(bool), pit_exit_flag=z['pit_exit_flag'].astype(bool), meta=z.get('meta') or {})

    def to_dict(self, ndigits: int = 2) -> dict:
        return dict(L=round(self.L, 3), grid_m=round(self.grid_m, 4), x=np.round(self.x, ndigits).tolist(), y=np.round(self.y, ndigits).tolist(),
                    sector=self.sector.astype(int).tolist(), pit_entry_s=self.meta.get('pit_entry_s'), pit_exit_s=self.meta.get('pit_exit_s'),
                    sector1_end_s=self.meta.get('sector1_end_s'), sector2_end_s=self.meta.get('sector2_end_s'), event=self.meta.get('event'), quality=self.meta.get('quality', {}).get('status'))


@dataclass
class PitLane:
    s: np.ndarray                 # arc length along the pit lane from the entry junction (m)
    x: np.ndarray
    y: np.ndarray
    entry_s: float                # track s where the lane leaves the path
    exit_s: float                 # track s where the lane rejoins
    length: float
    s_line: float                 # pit-lane arc length where the start/finish line is crossed
    transit_tau: np.ndarray       # median recorded transit: seconds from the entry junction
    transit_s: np.ndarray         # ... and pit-lane arc length at those seconds
    source: str                   # 'recorded' | 'schematic'
    meta: dict = field(default_factory=dict)

    def __post_init__(self):
        self._poly = Polyline(np.column_stack([self.x, self.y]), closed=False)

    @property
    def polyline(self) -> Polyline:
        return self._poly

    @property
    def transit_time(self) -> float:
        return float(self.transit_tau[-1]) if len(self.transit_tau) else float('nan')

    def project(self, x, y) -> tuple[np.ndarray, np.ndarray]:
        return self._poly.project(np.atleast_1d(x), np.atleast_1d(y))

    def xy_at(self, s_pit) -> np.ndarray:
        return self._poly.xy_at(np.atleast_1d(s_pit))

    def save(self, directory: str | Path) -> str:
        d = Path(directory); d.mkdir(parents=True, exist_ok=True)
        return rio.save_npz(d / 'pitlane.npz', s=self.s, x=self.x, y=self.y, entry_s=np.float64(self.entry_s), exit_s=np.float64(self.exit_s), length=np.float64(self.length),
                            s_line=np.float64(self.s_line), transit_tau=self.transit_tau, transit_s=self.transit_s, source=self.source, meta=self.meta)

    @classmethod
    def load(cls, directory: str | Path) -> 'PitLane':
        z = rio.load_npz(Path(directory) / 'pitlane.npz')
        return cls(s=z['s'].astype(float), x=z['x'].astype(float), y=z['y'].astype(float), entry_s=float(z['entry_s']), exit_s=float(z['exit_s']), length=float(z['length']),
                   s_line=float(z['s_line']), transit_tau=z['transit_tau'].astype(float), transit_s=z['transit_s'].astype(float), source=str(z['source']), meta=z.get('meta') or {})

    def to_dict(self, ndigits: int = 2) -> dict:
        return dict(x=np.round(self.x, ndigits).tolist(), y=np.round(self.y, ndigits).tolist(), s=np.round(self.s, 2).tolist(), entry_s=round(self.entry_s, 2), exit_s=round(self.exit_s, 2),
                    length=round(self.length, 2), s_line=round(self.s_line, 2), transit_time=round(self.transit_time, 2), source=self.source)


# ---------------------------------------------------------------- clean laps

def clean_lap_rows(source: PositionSource, drivers: list[str]) -> pd.DataFrame:
    l = source.laps
    m = l['driver'].isin(drivers) & l['accurate'] & l['green'] & ~l['pit_in'] & ~l['pit_out'] & np.isfinite(l['lap_time']) & np.isfinite(l['t_start']) & np.isfinite(l['t_end'])
    return l[m].sort_values(['driver', 'lap']).reset_index(drop=True)


def lap_samples(source: PositionSource, driver: str, t0: float, t1: float, stale_step_m: float = STALE_STEP_M) -> tuple[np.ndarray, np.ndarray]:
    """(t, xy) of the driver's non-stale samples in [t0, t1)."""
    p = source.positions[driver]
    t = p['t'].to_numpy(dtype=float)
    m = (t >= t0) & (t < t1)
    xy = np.column_stack([p['x'].to_numpy(dtype=float)[m], p['y'].to_numpy(dtype=float)[m]])
    keep = drop_stale(xy, stale_step_m)
    return t[m][keep], xy[keep]


def position_at(source: PositionSource, driver: str, t_query: float, max_gap_s: float = 2.0) -> Optional[np.ndarray]:
    """Linear interpolation of the driver's position at a session time; None when the neighbours are too far apart."""
    p = source.positions[driver]
    t = p['t'].to_numpy(dtype=float)
    if not np.isfinite(t_query) or t_query < t[0] or t_query > t[-1]:
        return None
    j = int(np.searchsorted(t, t_query))
    if j == 0:
        return p[['x', 'y']].to_numpy(dtype=float)[0]
    ta, tb = t[j - 1], t[j]
    if tb - ta > max_gap_s:
        return None
    w = 0.0 if tb == ta else (t_query - ta) / (tb - ta)
    xy = p[['x', 'y']].to_numpy(dtype=float)
    return xy[j - 1] * (1 - w) + xy[j] * w


# ---------------------------------------------------------------- track path

def _consensus(seed_xy: np.ndarray, pooled: np.ndarray, grid_m: float, closed: bool, min_bin: int = MIN_BIN_POINTS, seed_step: float = SEED_STEP_M) -> np.ndarray:
    """Median x/y of the pooled samples per arc-length bin along the seed; seed points fill empty bins."""
    _, seed_fine, L = resample_by_arclength(seed_xy, seed_step, closed)
    poly = Polyline(seed_fine, closed)
    s, d = poly.project(pooled[:, 0], pooled[:, 1])
    ok = d < 25.0                                   # pooled outliers (other lines, garbage) do not vote
    n_bins = max(int(round(L / grid_m)), 4)
    edges = np.linspace(0.0, L, n_bins + 1)
    idx = np.clip(np.searchsorted(edges, s[ok], side='right') - 1, 0, n_bins - 1)
    out = np.empty((n_bins, 2))
    centres = poly.xy_at(0.5 * (edges[:-1] + edges[1:]))
    px, py = pooled[ok, 0], pooled[ok, 1]
    order = np.argsort(idx, kind='stable'); idx_sorted = idx[order]
    bounds = np.searchsorted(idx_sorted, np.arange(n_bins + 1))
    for b in range(n_bins):
        sel = order[bounds[b]:bounds[b + 1]]
        if len(sel) >= min_bin:
            out[b] = (np.median(px[sel]), np.median(py[sel]))
        else:
            out[b] = centres[b]
    return out


def build_track(source: PositionSource, grid_m: float = GRID_M, min_distinct: int = MIN_DISTINCT_PER_LAP, min_drivers: int = MIN_DRIVERS_FOR_PATH,
                max_pooled: int = 400_000, seed: int = 2026) -> TrackPath:
    """Canonical closed path for the race in `source`. Raises QualityRefusal with a meta record when the feed is unusable."""
    passing, records = gate_drivers(source, min_distinct)
    quality = dict(status='ok', min_distinct_per_lap=min_distinct, drivers_passed=passing, drivers_refused=[r['driver'] for r in records if not r['ok']],
                   per_driver={r['driver']: dict(median=r['median_distinct_per_lap'], min=r['min_distinct_per_lap'], ok=r['ok']) for r in records})
    base_meta = dict(event=source.event, event_id=source.event_id, year=source.year, session=source.session, n_laps=source.n_laps, grid_m_nominal=grid_m, quality=quality)
    if len(passing) < min_drivers:
        reasons = [r['reason'] for r in records if not r['ok']]
        med = sorted(r['median_distinct_per_lap'] for r in records)
        reason = (f'{source.event_id}: {len(passing)} of {len(records)} drivers pass the position-feed gate (median distinct points per lap >= {min_distinct}); '
                  f'need {min_drivers}. Medians: {med[:3]}...{med[-3:]}. Refused: the feed is degraded at source.')
        quality.update(status='refused', reason=reason, refusal_details=reasons[:5])
        raise QualityRefusal(reason, base_meta)
    clean = clean_lap_rows(source, passing)
    if len(clean) < MIN_CLEAN_LAPS:
        reason = f'{source.event_id}: only {len(clean)} clean laps (need {MIN_CLEAN_LAPS})'
        quality.update(status='refused', reason=reason)
        raise QualityRefusal(reason, base_meta)
    # per-lap polylines
    lap_polys: list[tuple[np.ndarray, float, str, int]] = []
    for _, r in clean.iterrows():
        _, xy = lap_samples(source, r['driver'], r['t_start'], r['t_end'])
        if len(xy) >= min_distinct:
            lap_polys.append((xy, float(r['lap_time']), str(r['driver']), int(r['lap'])))
    if len(lap_polys) < MIN_CLEAN_LAPS:
        reason = f'{source.event_id}: only {len(lap_polys)} clean laps with >= {min_distinct} distinct points'
        quality.update(status='refused', reason=reason)
        raise QualityRefusal(reason, base_meta)
    # seed: best-sampled lap among the fastest quartile
    times = np.array([p[1] for p in lap_polys]); q = np.quantile(times, 0.25)
    cand = [i for i, p in enumerate(lap_polys) if p[1] <= q] or list(range(len(lap_polys)))
    seed_i = max(cand, key=lambda i: len(lap_polys[i][0]))
    seed_xy = lap_polys[seed_i][0]
    pooled = np.vstack([p[0] for p in lap_polys])
    if len(pooled) > max_pooled:
        rng = np.random.default_rng(seed)
        pooled = pooled[np.sort(rng.choice(len(pooled), size=max_pooled, replace=False))]
    # two passes of consensus + smoothing + arc-length re-parametrisation
    path = seed_xy
    for _ in range(2):
        cons = _consensus(path, pooled, grid_m, closed=True)
        cons = smooth_circular(cons, SMOOTH_WINDOW)
        _, path, L = resample_by_arclength(cons, grid_m, closed=True)
    poly = Polyline(path, closed=True)
    # start/finish: median projected position at the timing lap start
    starts = []
    for _, r in clean.iterrows():
        xy = position_at(source, r['driver'], r['t_start'])
        if xy is not None:
            starts.append(poly.project(xy[:1], xy[1:])[0][0])
    s0 = circular_median(np.array(starts), L) if starts else 0.0
    n = len(path)
    grid = np.arange(n) * (L / n)
    xy0 = poly.xy_at(s0 + grid)
    poly = Polyline(xy0, closed=True)
    grid, xy0, L = resample_by_arclength(xy0, grid_m, closed=True)      # exact uniform grid after the roll
    poly = Polyline(xy0, closed=True)
    # sectors: positions at the sector session times (fallback: time fractions of the lap)
    def _boundary(col: str, frac_default: float) -> tuple[float, str]:
        vals = []
        if col in clean.columns and np.isfinite(clean[col]).any():
            for _, r in clean.iterrows():
                if np.isfinite(r[col]):
                    xy = position_at(source, r['driver'], r[col])
                    if xy is not None:
                        vals.append(poly.project(xy[:1], xy[1:])[0][0])
        if len(vals) >= 3:
            return circular_median(np.array(vals), L), 'positions at sector session times'
        return frac_default * L, 'time-fraction fallback'
    s1_end, s1_src = _boundary('s1_end', 1 / 3)
    s2_end, s2_src = _boundary('s2_end', 2 / 3)
    if not (0 < s1_end < s2_end < L):
        s1_end, s2_end, s1_src = L / 3, 2 * L / 3, 'thirds fallback (sector order inconsistent)'
    sector = np.where(grid < s1_end, 0, np.where(grid < s2_end, 1, 2)).astype(np.int8)
    # quality of fit
    sproj, dproj = poly.project(pooled[:, 0], pooled[:, 1])
    rms = float(np.sqrt(np.mean(np.minimum(dproj, 25.0) ** 2)))
    within5 = float((dproj <= 5.0).mean())
    start_spread = float(np.median(np.abs(np.mod(np.array(starts) - s0 + L / 2, L) - L / 2))) if starts else float('nan')
    quality.update(n_clean_laps=len(lap_polys), n_pooled_points=int(len(pooled)), seed_lap=dict(driver=lap_polys[seed_i][2], lap=lap_polys[seed_i][3], n_points=int(len(seed_xy)), lap_time=lap_polys[seed_i][1]),
                   residual_rms_m=round(rms, 3), share_within_5m=round(within5, 4), start_line_median_abs_dev_m=round(start_spread, 2), n_start_samples=len(starts),
                   closure='closed by construction (consensus bins along a closed seed)', grid_m=round(L / len(grid), 4))
    meta = dict(base_meta, L=round(L, 3), n_points=len(grid), grid_m=round(L / len(grid), 4), sector1_end_s=round(float(s1_end), 2), sector2_end_s=round(float(s2_end), 2),
                sector_source=dict(s1=s1_src, s2=s2_src), sector_fractions=[round(float(s1_end / L), 4), round(float(s2_end / L), 4)],
                units='metres, feed frame (FastF1 X/Y / 10)', pit_entry_s=None, pit_exit_s=None, quality=quality)
    return TrackPath(s=grid, x=xy0[:, 0], y=xy0[:, 1], L=L, sector=sector, pit_entry_flag=np.zeros(len(grid), dtype=bool), pit_exit_flag=np.zeros(len(grid), dtype=bool), meta=meta)


def attach_pit_flags(track: TrackPath, pitlane: PitLane) -> TrackPath:
    """Mark the grid points nearest to the pit entry and exit junctions and record them in the meta."""
    i_in = int(np.argmin(np.abs(np.mod(track.s - pitlane.entry_s + track.L / 2, track.L) - track.L / 2)))
    i_out = int(np.argmin(np.abs(np.mod(track.s - pitlane.exit_s + track.L / 2, track.L) - track.L / 2)))
    track.pit_entry_flag = np.zeros(track.n_points, dtype=bool); track.pit_entry_flag[i_in] = True
    track.pit_exit_flag = np.zeros(track.n_points, dtype=bool); track.pit_exit_flag[i_out] = True
    track.meta.update(pit_entry_s=round(float(pitlane.entry_s), 2), pit_exit_s=round(float(pitlane.exit_s), 2), pit_entry_index=i_in, pit_exit_index=i_out, pitlane_source=pitlane.source)
    return track


# ---------------------------------------------------------------- pit lane

def pit_excursions(source: PositionSource, driver: str, track: TrackPath, offpath_m: float = PIT_OFFPATH_M) -> list[dict]:
    """Recorded pit-lane runs of one driver: for each in-lap/out-lap pair the samples further than offpath_m from the path
    around the pit-in time, extended by one on-path sample on each side. Session times."""
    laps = source.driver_laps(driver)
    p = source.positions.get(driver)
    if p is None or p.empty:
        return []
    t_all = p['t'].to_numpy(dtype=float); xy_all = p[['x', 'y']].to_numpy(dtype=float)
    out = []
    for i, r in laps.iterrows():
        if not bool(r['pit_in']) or not np.isfinite(r['t_start']):
            continue
        nxt = laps[laps['lap'] == r['lap'] + 1]
        t_hi = float(nxt['t_end'].iloc[0]) if len(nxt) and np.isfinite(nxt['t_end'].iloc[0]) else float(r['t_end']) + 120.0
        if not np.isfinite(t_hi):
            continue
        m = (t_all >= r['t_start']) & (t_all <= t_hi)
        if m.sum() < 10:
            continue
        t = t_all[m]; xy = xy_all[m]
        keep = drop_stale(xy, STALE_STEP_M) | (np.arange(len(xy)) == 0)
        s_tr, d = track.project(xy[:, 0], xy[:, 1])
        off = d > offpath_m
        # runs of off-path samples (ignoring stale repeats inside a run)
        runs = []
        j = 0
        while j < len(off):
            if off[j]:
                k = j
                while k + 1 < len(off) and (off[k + 1] or not keep[k + 1]):
                    k += 1
                runs.append((j, k)); j = k + 1
            else:
                j += 1
        if not runs:
            continue
        t_pit = float(r['t_pit_in']) if np.isfinite(r['t_pit_in']) else float(r['t_end'])
        def _score(run):
            a, b = run
            inside = t[a] - 5.0 <= t_pit <= t[b] + 5.0
            return (0 if inside else 1, -(b - a))
        a, b = min(runs, key=_score)
        a = max(a - 1, 0); b = min(b + 1, len(t) - 1)
        if b - a < 5:
            continue
        span = float(np.mod(s_tr[b] - s_tr[a], track.L))
        out.append(dict(driver=driver, lap_in=int(r['lap']), t=t[a:b + 1], xy=xy[a:b + 1], s_track=s_tr[a:b + 1], dist=d[a:b + 1],
                        t_entry=float(t[a]), t_exit=float(t[b]), s_entry=float(s_tr[a]), s_exit=float(s_tr[b]), duration=float(t[b] - t[a]), span_m=span,
                        t_pit_in=float(r['t_pit_in']) if np.isfinite(r['t_pit_in']) else None))
    return out


def schematic_pitlane(track: TrackPath, offset_m: float = 14.0, entry_back_m: float = 450.0, exit_ahead_m: float = 250.0, limit_mps: float = 22.2, stop_s: float = 2.5) -> PitLane:
    """Offset chord on the inside of the start/finish straight, labelled 'schematic'. Used when no recorded stop leaves the path."""
    L = track.L
    entry_s = (L - min(entry_back_m, 0.15 * L)) % L
    exit_s = min(exit_ahead_m, 0.1 * L)
    span = (exit_s - entry_s) % L
    n = max(int(round(span / PIT_GRID_M)), 8)
    s_rel = np.linspace(0.0, span, n + 1)
    s_abs = (entry_s + s_rel) % L
    base = track.xy_at(s_abs); tan = track.polyline.tangent_at(s_abs)
    normal = np.column_stack([-tan[:, 1], tan[:, 0]])
    centroid = np.array([track.x.mean(), track.y.mean()])
    inward = np.sign(((centroid - base[0]) * normal[0]).sum()) or 1.0
    ramp = np.clip(np.minimum(s_rel, span - s_rel) / 80.0, 0.0, 1.0)
    xy = base + inward * offset_m * ramp[:, None] * normal
    s_pit = cumulative_length(xy)
    length = float(s_pit[-1])
    # start/finish crossing inside the lane: where the base s wraps past L
    s_line = float(np.interp(L - entry_s, s_rel, s_pit)) if entry_s > exit_s else 0.0
    box_s = s_line
    tau = np.arange(0.0, length / limit_mps + stop_s + 1.0, 0.5)
    prog = np.minimum(tau * limit_mps, box_s)
    after = np.maximum(tau - box_s / limit_mps - stop_s, 0.0) * limit_mps
    transit_s = np.minimum(prog + after, length)
    tau = tau[: int(np.searchsorted(transit_s, length - 1e-6)) + 1]; transit_s = transit_s[: len(tau)]
    meta = dict(source='schematic', note='no recorded pit excursion in the position feed: offset chord inside the start/finish straight; transit = 80 km/h limit + 2.5 s stop',
                offset_m=offset_m, n_stops=0)
    return PitLane(s=s_pit, x=xy[:, 0], y=xy[:, 1], entry_s=float(entry_s), exit_s=float(exit_s), length=length, s_line=s_line, transit_tau=tau, transit_s=transit_s, source='schematic', meta=meta)


def build_pitlane(source: PositionSource, track: TrackPath, drivers: Optional[list[str]] = None, grid_m: float = PIT_GRID_M, max_duration_s: float = 90.0) -> PitLane:
    """Pooled pit-lane polyline and median transit profile from recorded stops; schematic fallback when none exist."""
    drivers = drivers or track.meta.get('quality', {}).get('drivers_passed') or source.drivers
    exc = []
    for d in drivers:
        exc.extend(pit_excursions(source, d, track))
    usable = [e for e in exc if e['span_m'] >= 100.0 and e['duration'] <= max_duration_s and e['duration'] >= 8.0]
    if not usable:
        pl = schematic_pitlane(track)
        pl.meta.update(n_excursions_seen=len(exc))
        return pl
    seed = max(usable, key=lambda e: len(e['xy']))
    seed_xy = seed['xy'][drop_stale(seed['xy'], STALE_STEP_M)]
    pooled = np.vstack([e['xy'] for e in usable])
    path = seed_xy
    for _ in range(2):
        cons = _consensus(path, pooled, grid_m, closed=False, min_bin=2, seed_step=1.0)
        cons = smooth_circular(cons, 3) if len(cons) > 8 else cons
        # smoothing an open polyline circularly bends the ends: restore them
        cons[0], cons[-1] = path[0], path[-1]
        _, path, _ = resample_by_arclength(cons, grid_m, closed=False)
    L = track.L
    entry_s = circular_median(np.array([e['s_entry'] for e in usable]), L)
    exit_s = circular_median(np.array([e['s_exit'] for e in usable]), L)
    # anchor the lane to the path at the junctions
    xy = np.vstack([track.xy_at(entry_s), path, track.xy_at(exit_s)])
    s_pit = cumulative_length(xy)
    length = float(s_pit[-1])
    poly = Polyline(xy, closed=False)
    # start/finish crossing: pit-lane arc length nearest to the track point s = 0
    sf = track.xy_at(0.0)
    s_line = float(poly.project(sf[:, 0], sf[:, 1])[0][0])
    # transit profile: s_pit(tau) per stop, median across stops on a 0.5 s grid
    durations = np.array([e['duration'] for e in usable])
    D = float(np.median(durations))
    tau = np.arange(0.0, D + 0.5, 0.5)
    profiles = []
    for e in usable:
        sp, _ = poly.project(e['xy'][:, 0], e['xy'][:, 1])
        sp = np.maximum.accumulate(sp)
        tt = e['t'] - e['t_entry']
        profiles.append(np.interp(tau, tt, sp, left=0.0, right=length))
    transit_s = np.median(np.vstack([np.minimum(p, length) for p in profiles]), axis=0)
    transit_s = np.maximum.accumulate(transit_s); transit_s[-1] = length
    stops_meta = [dict(driver=e['driver'], lap_in=e['lap_in'], duration_s=round(e['duration'], 2), span_m=round(e['span_m'], 1), n_points=int(len(e['xy']))) for e in usable]
    meta = dict(source='recorded', n_stops=len(usable), n_excursions_seen=len(exc), median_transit_s=round(D, 2), transit_iqr_s=[round(float(np.quantile(durations, q)), 2) for q in (0.25, 0.75)],
                entry_s=round(float(entry_s), 2), exit_s=round(float(exit_s), 2), stops=stops_meta[:40], offpath_threshold_m=PIT_OFFPATH_M)
    return PitLane(s=s_pit, x=xy[:, 0], y=xy[:, 1], entry_s=float(entry_s), exit_s=float(exit_s), length=length, s_line=s_line, transit_tau=tau, transit_s=transit_s, source='recorded', meta=meta)


def write_refusal(directory: str | Path, refusal: QualityRefusal) -> Path:
    d = Path(directory); d.mkdir(parents=True, exist_ok=True)
    meta = dict(refusal.meta, status='refused', reason=refusal.reason)
    rio.save_json(d / 'meta.json', meta)
    return d / 'meta.json'


__all__ = ['GRID_M', 'PIT_GRID_M', 'PIT_OFFPATH_M', 'MIN_DRIVERS_FOR_PATH', 'QualityRefusal', 'Polyline', 'TrackPath', 'PitLane', 'drop_stale', 'cumulative_length',
           'resample_by_arclength', 'circular_median', 'clean_lap_rows', 'lap_samples', 'position_at', 'build_track', 'attach_pit_flags', 'pit_excursions',
           'schematic_pitlane', 'build_pitlane', 'write_refusal']
