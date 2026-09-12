"""Shared evaluation helpers: weekend-grouped bootstrap, summary statistics, JSON output.

Every interval in the scorecards comes from `weekend_bootstrap`: whole weekends are resampled with replacement and the
statistic is recomputed on the concatenated rows; rows are never resampled individually (roadmap 9: "every metric
weekend-grouped"). tests/evaluation/test_bootstrap.py asserts the grouping.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from shared.lockio import atomic_write_json, strip_nonfinite

SEED = 2026
N_BOOT = 2000


def finite(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def mae(values: Iterable[Any]) -> Optional[float]:
    v = np.array([x for x in (finite(a) for a in values) if x is not None], dtype=float)
    return float(np.mean(np.abs(v))) if v.size else None


def share(values: Iterable[Any]) -> Optional[float]:
    v = [x for x in values if x is not None and x == x]
    return float(np.mean([bool(x) for x in v])) if v else None


def weekend_bootstrap(df: pd.DataFrame, stat: Callable[[pd.DataFrame], Optional[float]], weekend_col: str = 'race_id', n: int = N_BOOT, seed: int = SEED,
                      ci: tuple[float, float] = (5.0, 95.0)) -> dict[str, Any]:
    """Point estimate on all rows plus a weekend-grouped bootstrap interval of `stat`.

    Weekends (distinct values of weekend_col) are drawn with replacement; a weekend drawn twice contributes its rows
    twice. Returns {estimate, ci90: [lo, hi], n_weekends, n_rows, method}; the interval is null when fewer than 2
    weekends exist or the statistic is undefined on the resamples."""
    if df is None or len(df) == 0:
        return dict(estimate=None, ci90=None, n_weekends=0, n_rows=0, method='weekend-grouped bootstrap')
    weekends = sorted(df[weekend_col].dropna().unique().tolist())
    est = stat(df)
    est = finite(est)
    if len(weekends) < 2:
        return dict(estimate=est, ci90=None, n_weekends=len(weekends), n_rows=int(len(df)), method='weekend-grouped bootstrap (fewer than 2 weekends: no interval)')
    rng = np.random.default_rng(seed)
    groups = {w: df[df[weekend_col] == w] for w in weekends}
    stats = []
    for _ in range(n):
        draw = rng.choice(weekends, size=len(weekends), replace=True)
        sample = pd.concat([groups[w] for w in draw], ignore_index=True)
        s = finite(stat(sample))
        if s is not None:
            stats.append(s)
    if len(stats) < max(10, n // 10):
        return dict(estimate=est, ci90=None, n_weekends=len(weekends), n_rows=int(len(df)), method='weekend-grouped bootstrap (statistic undefined on most resamples)')
    lo, hi = np.percentile(stats, ci)
    return dict(estimate=est, ci90=[float(lo), float(hi)], n_weekends=len(weekends), n_rows=int(len(df)), n_boot=len(stats), method='weekend-grouped bootstrap (resample weekends, never rows)')


def weekend_mean_bootstrap(df: pd.DataFrame, value_col: str, weight_col: Optional[str] = None,
                           n: int = N_BOOT, seed: int = SEED, n_unit: str = 'rows') -> dict[str, Any]:
    """Exact cluster bootstrap for a (possibly weighted) mean via weekend sums.

    Sufficient sums avoid rebuilding thousands of DataFrames. Only whole weekends
    are sampled; duplicating a weekend duplicates its numerator and denominator.
    n counts eligible observations, while n_rows counts input summary rows.
    """
    if df is None or df.empty:
        return dict(estimate=None, ci90=None, n=0, n_unit=n_unit, n_rows=0, n_weekends=0,
                    method='weekend-grouped bootstrap (no eligible observations)')
    d = df[['race_id', value_col] + ([weight_col] if weight_col else [])].copy()
    d['_value'] = pd.to_numeric(d[value_col], errors='coerce')
    d['_weight'] = pd.to_numeric(d[weight_col], errors='coerce') if weight_col else 1.0
    d = d[np.isfinite(d['_value']) & np.isfinite(d['_weight']) & (d['_weight'] > 0)].dropna(subset=['race_id'])
    if d.empty:
        return weekend_mean_bootstrap(None, value_col, n_unit=n_unit)
    d['_num'] = d['_value'] * d['_weight']
    g = d.groupby('race_id', sort=True)[['_num', '_weight']].sum()
    a, w = g['_num'].to_numpy(), g['_weight'].to_numpy()
    out = dict(estimate=float(a.sum() / w.sum()), ci90=None, n=int(w.sum()), n_unit=n_unit,
               n_rows=int(len(d)), n_weekends=int(len(g)), method='weekend-grouped bootstrap (fewer than 2 weekends: no interval)')
    if len(g) < 2:
        return out
    draws = np.random.default_rng(seed).choice(len(g), size=(n, len(g)), replace=True)
    stats = a[draws].sum(axis=1) / w[draws].sum(axis=1)
    out.update(ci90=np.percentile(stats, [5, 95]).tolist(), n_boot=n,
               method='weekend-grouped bootstrap (resample weekends, never rows)')
    return out


def paired_probability(df: pd.DataFrame, a_col: str, b_col: str, weekend_col: str = 'race_id', n: int = N_BOOT, seed: int = SEED) -> dict[str, Any]:
    """P(mean(a) < mean(b)) under the weekend bootstrap plus the raw share of rows where a < b (ties count half)."""
    d = df.dropna(subset=[a_col, b_col])
    if len(d) == 0:
        return dict(p_bootstrap=None, share_rows=None, n_rows=0, n_weekends=0)
    wins = float(np.mean((d[a_col] < d[b_col]).astype(float) + 0.5 * (d[a_col] == d[b_col]).astype(float)))
    weekends = sorted(d[weekend_col].unique().tolist())
    if len(weekends) < 2:
        return dict(p_bootstrap=None, share_rows=wins, n_rows=int(len(d)), n_weekends=len(weekends))
    rng = np.random.default_rng(seed)
    groups = {w: d[d[weekend_col] == w] for w in weekends}
    diffs = []
    for _ in range(n):
        draw = rng.choice(weekends, size=len(weekends), replace=True)
        s = pd.concat([groups[w] for w in draw], ignore_index=True)
        diffs.append(float((s[b_col] - s[a_col]).mean()))
    diffs = np.array(diffs)
    d = d.copy()
    d['_win'] = (d[a_col] < d[b_col]).astype(float) + 0.5 * (d[a_col] == d[b_col]).astype(float)
    return dict(p_bootstrap=float(np.mean(diffs > 0) + 0.5 * np.mean(diffs == 0)), share_rows=wins, n_rows=int(len(d)), n_weekends=len(weekends),
                share_rows_bootstrap=weekend_mean_bootstrap(d.rename(columns={weekend_col: 'race_id'}) if weekend_col != 'race_id' else d, '_win', n=n, seed=seed))


def describe(values: Sequence[float]) -> dict[str, Any]:
    v = np.array([x for x in (finite(a) for a in values) if x is not None], dtype=float)
    if v.size == 0:
        return dict(n=0)
    return dict(n=int(v.size), mean=float(v.mean()), median=float(np.median(v)), p10=float(np.percentile(v, 10)), p90=float(np.percentile(v, 90)), min=float(v.min()), max=float(v.max()))


def write_json(path, obj: Any) -> None:
    """Atomic JSON write with NaN/inf replaced by null (shared.lockio)."""
    atomic_write_json(path, strip_nonfinite(obj))


__all__ = ['SEED', 'N_BOOT', 'finite', 'mae', 'share', 'weekend_bootstrap', 'weekend_mean_bootstrap', 'paired_probability', 'describe', 'write_json']
