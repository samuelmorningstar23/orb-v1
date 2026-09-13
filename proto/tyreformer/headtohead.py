"""Head to head: Orb TyreFormer against the Orb v1 live estimator, on identical origins and targets.

The estimator's per-lap records come from tyreformer.baseline_kalman (the real LiveTyreStateEstimator, leave-one-out
pre-race priors). Scored origins are exactly prefix_eval.py's: laps where the estimator is anchored with at least one clean
observation. Targets at h: lap k+h of the same driver, kept by the estimator, same stint, tyre age = age_k + h.
Both models are scored only where both produced a forecast; any origin one model lacks is counted and reported.

Metrics (all in seconds of corrected lap time):
    next-h MAE       |forecast(k+h) - y(k+h)|, h = 1, 3, 5
    cum-h MAE        |sum_{j<=h} forecast - sum_{j<=h} y| where all h targets exist (TyreFormer: its cumulative head)
    coverage90       estimator: |err| <= 1.645 sd (its own predictive sd); TyreFormer: conformal q05..q95 band
    cliff Brier      prefix_eval.py's realised CLIFF rule within 3 / 5 laps (prior slope from the estimator's prior)
    prior-only       prefix_eval.py's baseline: pre-race slope, level re-estimated from the clean laps so far
Uncertainty: weekend-grouped bootstrap (2000 draws) of each MAE and of the paired difference; P(TyreFormer better).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from tyreformer import OUT
from tyreformer.data import SIGMA_Y

KALMAN = OUT / 'kalman'
Z90 = 1.6448536269514722


def load_kalman(race_ids: Iterable[str]) -> pd.DataFrame:
    parts = []
    for rid in race_ids:
        p = KALMAN / f'{rid}.parquet'
        if not p.exists():
            p = KALMAN / f'{rid}.csv.gz'
        if not p.exists():
            continue
        parts.append(pd.read_parquet(p) if p.suffix == '.parquet' else pd.read_csv(p))
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def _cliff_truth(kept: list[tuple[int, float, float, int]], k: int, stint: int, b0: float, h: int) -> Optional[int]:
    seq = [(lap, y, age) for (lap, y, age, s) in kept if s == stint and lap <= k + 5]
    future = [x for x in seq if x[0] <= k + h]
    if not future or future[-1][0] < k + 1:
        return None
    hist = [x for x in seq if x[0] <= k + h]
    for i in range(2, len(hist)):
        if hist[i][0] <= k:
            continue
        (l0, y0, a0), (l1, y1, a1), (l2, y2, a2) = hist[i - 2], hist[i - 1], hist[i]
        d1, d2 = (y1 - y0) / max(a1 - a0, 1), (y2 - y1) / max(a2 - a1, 1)
        if d1 > 0 and d2 > 0 and (y2 - y0) > max(2.0 * b0 * max(a2 - a0, 1), 2.0 * math.sqrt(2.0) * SIGMA_Y):
            return 1
    return 0


def origin_table(K: pd.DataFrame, horizons=(1, 2, 3, 4, 5)) -> pd.DataFrame:
    """One row per scored origin with the estimator's forecasts, the prior-only forecasts, the realised targets and cliff labels."""
    rows = []
    for (rid, drv), g in K.groupby(['race_id', 'driver'], sort=False):
        g = g.sort_values('lap').reset_index(drop=True)
        by_lap = {int(l): i for i, l in enumerate(g['lap'])}
        kept_mask = g['kept'].fillna(False).astype(bool).to_numpy()
        ok_err = g['error'].isna().to_numpy() if 'error' in g else np.ones(len(g), bool)
        y = g['y'].to_numpy(dtype=float)
        age = g['tyre_age'].to_numpy(dtype=float)
        stint = g['stint'].to_numpy()
        lapn = g['lap'].to_numpy()
        kept_list = [(int(lapn[i]), float(y[i]), float(age[i]), int(stint[i])) for i in range(len(g)) if kept_mask[i] and ok_err[i]]
        for i in range(len(g)):
            if not ok_err[i] or not bool(g.at[i, 'anchored']) or int(g.at[i, 'n_obs']) < 1:
                continue
            k = int(lapn[i])
            b0 = float(g.at[i, 'prior_mean'])
            # prior-only level: clean laps of the current state so far (same stint, kept, not after k); estimator state starts at the reset
            st_rows = [j for j in range(i + 1) if stint[j] == stint[i] and kept_mask[j] and ok_err[j]]
            level = float(np.mean([y[j] - b0 * age[j] for j in st_rows])) if st_rows else np.nan
            rec = dict(race_id=rid, driver=drv, lap=k, stint=int(stint[i]), compound=g.at[i, 'compound'], age=float(age[i]), n_obs=int(g.at[i, 'n_obs']), prior_mean=b0,
                       prior_sd=float(g.at[i, 'prior_sd']), cliff_p3_kalman=float(g.at[i, 'cliff_p3']), cliff_p5_kalman=float(g.at[i, 'cliff_p5']))
            for h in horizons:
                j = by_lap.get(k + h)
                valid = j is not None and kept_mask[j] and ok_err[j] and stint[j] == stint[i] and np.isfinite(age[j]) and age[j] == age[i] + h
                rec[f'y{h}'] = float(y[j]) if valid else np.nan
                rec[f'kal{h}'] = float(g.at[i, f'pred_h{h}'])
                rec[f'kal_sd{h}'] = float(g.at[i, f'sd_h{h}'])
                rec[f'prior{h}'] = level + b0 * (age[i] + h)
            for h in (3, 5):
                t = _cliff_truth(kept_list, k, int(stint[i]), b0, h)
                rec[f'cliff{h}'] = np.nan if t is None else float(t)
            rows.append(rec)
    return pd.DataFrame(rows)


def attach_tyreformer(O: pd.DataFrame, P: pd.DataFrame, margins: dict[str, float]) -> pd.DataFrame:
    """Join TyreFormer forecasts (race sessions only) onto the origin table by (race_id, driver, lap)."""
    P = P[P['session'] == 'R']
    keep = ['race_id', 'driver', 'lap', 'cliff_p3', 'cliff_p5'] + [c for c in P.columns if c.startswith(('h1_', 'h2_', 'h3_', 'h4_', 'h5_', 'cum3_', 'cum5_', 'tf_h', 'gbm_h', 'tf_cum'))]
    keep += [c for c in ('anchor',) if c in P.columns]
    M = O.merge(P[keep], on=['race_id', 'driver', 'lap'], how='left')
    for h in range(1, 6):
        c = margins.get(f'h{h}', 0.0)
        M[f'tf_lo{h}'] = M[f'h{h}_q05'] - c
        M[f'tf_hi{h}'] = M[f'h{h}_q95'] + c
    for h in (3, 5):
        c = margins.get(f'cum{h}', 0.0)
        M[f'tf_cum_lo{h}'] = M[f'cum{h}_q05'] - c
        M[f'tf_cum_hi{h}'] = M[f'cum{h}_q95'] + c
    return M


def _errors(M: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per-metric long frames with columns race_id, err_tf, err_kal, err_prior (absolute errors) on rows where all exist."""
    out = {}
    have_tf = M['h1_q50'].notna()
    for h in (1, 3, 5):
        m = M[f'y{h}'].notna() & have_tf & M[f'kal{h}'].notna()
        d = M[m]
        out[f'next{h}'] = pd.DataFrame(dict(race_id=d['race_id'], err_tf=(d[f'h{h}_q50'] - d[f'y{h}']).abs(), err_kal=(d[f'kal{h}'] - d[f'y{h}']).abs(),
                                            err_prior=(d[f'prior{h}'] - d[f'y{h}']).abs(),
                                            cov_tf=((d[f'y{h}'] >= d[f'tf_lo{h}']) & (d[f'y{h}'] <= d[f'tf_hi{h}'])).astype(float),
                                            cov_kal=((d[f'kal{h}'] - d[f'y{h}']).abs() <= Z90 * d[f'kal_sd{h}']).astype(float)))
    for h in (3, 5):
        ys = [f'y{j}' for j in range(1, h + 1)]
        m = M[ys].notna().all(axis=1) & have_tf & M[[f'kal{j}' for j in range(1, h + 1)]].notna().all(axis=1)
        d = M[m]
        ysum = d[ys].sum(axis=1)
        out[f'cum{h}'] = pd.DataFrame(dict(race_id=d['race_id'], err_tf=(d[f'cum{h}_q50'] - ysum).abs(), err_kal=(d[[f'kal{j}' for j in range(1, h + 1)]].sum(axis=1) - ysum).abs(),
                                           err_prior=(d[[f'prior{j}' for j in range(1, h + 1)]].sum(axis=1) - ysum).abs(),
                                           cov_tf=((ysum >= d[f'tf_cum_lo{h}']) & (ysum <= d[f'tf_cum_hi{h}'])).astype(float), cov_kal=np.nan))
    for h in (3, 5):
        m = M[f'cliff{h}'].notna() & have_tf
        d = M[m]
        o = d[f'cliff{h}']
        out[f'cliff{h}'] = pd.DataFrame(dict(race_id=d['race_id'], err_tf=(d[f'cliff_p{h}'] - o) ** 2, err_kal=(d[f'cliff_p{h}_kalman'] - o) ** 2, err_prior=np.nan, cov_tf=np.nan, cov_kal=np.nan, event=o))
    return out


def _group_stats(d: pd.DataFrame, cols: tuple[str, ...]) -> tuple[np.ndarray, dict[str, np.ndarray], np.ndarray]:
    g = d.groupby('race_id', sort=True)
    rids = np.array(list(g.groups.keys()))
    sums = {c: g[c].sum().to_numpy(dtype=float) for c in cols}
    counts = g.size().to_numpy(dtype=float)
    return rids, sums, counts


def _boot_draws(n_groups: int, n: int = 2000, seed: int = 11) -> np.ndarray:
    """[n, n_groups] resample counts of whole weekends (multinomial bootstrap)."""
    rng = np.random.default_rng(seed)
    return np.stack([np.bincount(rng.integers(0, n_groups, n_groups), minlength=n_groups) for _ in range(n)]).astype(float)


def compare(M: pd.DataFrame, bootstrap: bool = True, base_rates: Optional[dict[str, float]] = None) -> dict[str, Any]:
    E = _errors(M)
    res: dict[str, Any] = dict(origins=int(len(M)), origins_without_tyreformer=int(M['h1_q50'].isna().sum()), weekends=int(M['race_id'].nunique()))
    for k, d in E.items():
        if not len(d):
            continue
        r = dict(n=int(len(d)), weekends=int(d['race_id'].nunique()), tyreformer=float(d['err_tf'].mean()), orb_v1_estimator=float(d['err_kal'].mean()))
        if d['err_prior'].notna().any():
            r['prior_only'] = float(d['err_prior'].mean())
        if d['cov_tf'].notna().any():
            r['coverage90_tyreformer'] = float(d['cov_tf'].mean())
        if d['cov_kal'].notna().any():
            r['coverage90_orb_v1_estimator'] = float(d['cov_kal'].mean())
        if k.startswith('cliff'):
            o = d['event']
            br = (base_rates or {}).get(k, float(o.mean()))
            r['events'] = int(o.sum())
            r['climatology_train_rate'] = float(((br - o) ** 2).mean())
            r['climatology_oracle'] = float(((o.mean() - o) ** 2).mean())
            r.update(tyreformer_brier=r.pop('tyreformer'), orb_v1_estimator_brier=r.pop('orb_v1_estimator'))
        if bootstrap:
            a, b = ('tyreformer_brier', 'orb_v1_estimator_brier') if k.startswith('cliff') else ('tyreformer', 'orb_v1_estimator')
            rids, sums, counts = _group_stats(d, ('err_tf', 'err_kal'))
            Wd = _boot_draws(len(rids))
            n_w = Wd @ counts
            tf_b = (Wd @ sums['err_tf']) / n_w
            ka_b = (Wd @ sums['err_kal']) / n_w
            r[f'{a}_ci90'] = [float(np.percentile(tf_b, 5)), float(np.percentile(tf_b, 95))]
            r[f'{b}_ci90'] = [float(np.percentile(ka_b, 5)), float(np.percentile(ka_b, 95))]
            diff = tf_b - ka_b
            r['difference_ci90'] = [float(np.percentile(diff, 5)), float(np.percentile(diff, 95))]
            r['p_tyreformer_better'] = float(np.mean(diff < 0))
            r['weekends_tyreformer_better'] = int(np.sum(sums['err_tf'] / counts < sums['err_kal'] / counts))
        res[k] = r
    return res


def per_race(M: pd.DataFrame) -> pd.DataFrame:
    E = _errors(M)
    rows = []
    for rid in sorted(M['race_id'].unique()):
        rec = dict(race_id=rid)
        for k in ('next1', 'next3', 'next5', 'cum3', 'cum5', 'cliff5'):
            d = E[k][E[k]['race_id'] == rid]
            rec[f'{k}_n'] = len(d)
            rec[f'{k}_tf'] = d['err_tf'].mean() if len(d) else np.nan
            rec[f'{k}_kal'] = d['err_kal'].mean() if len(d) else np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


__all__ = ['load_kalman', 'origin_table', 'attach_tyreformer', 'compare', 'per_race']
