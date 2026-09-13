"""Scoring helpers shared by cross-validation, the temporal test and the head-to-head against the Orb v1 estimator.

Point forecast = the median (optimal under absolute error). Cumulative h-lap error uses the model's own cumulative head
(the median of the sum), falling back to the sum of per-lap medians only when asked. The 90 % band is q05..q95, widened
by a conformal margin per horizon when one is supplied (split-conformal on out-of-fold development predictions).
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from tyreformer.data import SampleSet, H

Z90 = 1.6448536269514722


def _col(P: pd.DataFrame, name: str) -> np.ndarray:
    return P[name].to_numpy(dtype=float)


def conformal_margins(S: SampleSet, P: pd.DataFrame, level: float = 0.90) -> dict[str, float]:
    """Conformalised quantile regression margins: the `level` quantile of max(lo - y, y - hi) per horizon and per cumulative head."""
    out = {}
    y_all = S.anchor[:, None] + S.target
    for h in range(1, H + 1):
        m = S.target_mask[:, h - 1]
        if m.sum() < 50:
            continue
        y = y_all[m, h - 1]
        s = np.maximum(_col(P, f'h{h}_q05')[m] - y, y - _col(P, f'h{h}_q95')[m])
        n = len(s)
        out[f'h{h}'] = float(np.quantile(s, min(1.0, np.ceil((n + 1) * level) / n)))
    for i, hh in enumerate((3, 5)):
        m = S.cum_mask[:, i]
        if m.sum() < 50:
            continue
        y = hh * S.anchor[m] + S.cum[m, i]
        s = np.maximum(_col(P, f'cum{hh}_q05')[m] - y, y - _col(P, f'cum{hh}_q95')[m])
        n = len(s)
        out[f'cum{hh}'] = float(np.quantile(s, min(1.0, np.ceil((n + 1) * level) / n)))
    return out


def brier(p: np.ndarray, o: np.ndarray) -> float:
    return float(np.mean((p - o) ** 2))


def score(S: SampleSet, P: pd.DataFrame, margins: Optional[dict[str, float]] = None, base_rate: Optional[dict[str, float]] = None, mask: Optional[np.ndarray] = None) -> dict[str, Any]:
    """Metrics on the origins of S (optionally restricted by mask). base_rate: training-set cliff rates for a fair climatology."""
    if mask is not None:
        S = S.subset(mask)
        P = P[mask].reset_index(drop=True)
    margins = margins or {}
    r: dict[str, Any] = dict(origins=int(len(S)), weekends=int(S.meta['race_id'].nunique()))
    y_all = S.anchor[:, None] + S.target
    for h in (1, 2, 3, 5, 10):
        m = S.target_mask[:, h - 1]
        y = y_all[m, h - 1]
        med = _col(P, f'h{h}_q50')[m]
        r[f'next{h}_mae'] = float(np.mean(np.abs(med - y))) if m.any() else None
        r[f'next{h}_mae_persistence'] = float(np.mean(np.abs(S.anchor[m] - y))) if m.any() else None
        r[f'next{h}_n'] = int(m.sum())
        c = margins.get(f'h{h}', 0.0)
        lo, hi = _col(P, f'h{h}_q05')[m] - c, _col(P, f'h{h}_q95')[m] + c
        r[f'next{h}_cov90'] = float(np.mean((y >= lo) & (y <= hi))) if m.any() else None
        r[f'next{h}_width90'] = float(np.mean(hi - lo)) if m.any() else None
    for i, hh in enumerate((3, 5)):
        m = S.cum_mask[:, i]
        y = hh * S.anchor[m] + S.cum[m, i]
        med = _col(P, f'cum{hh}_q50')[m]
        sum_med = np.sum([_col(P, f'h{h}_q50')[m] for h in range(1, hh + 1)], axis=0)
        r[f'cum{hh}_mae'] = float(np.mean(np.abs(med - y))) if m.any() else None
        r[f'cum{hh}_mae_summed_medians'] = float(np.mean(np.abs(sum_med - y))) if m.any() else None
        r[f'cum{hh}_mae_persistence'] = float(np.mean(np.abs(hh * S.anchor[m] - y))) if m.any() else None
        r[f'cum{hh}_n'] = int(m.sum())
        c = margins.get(f'cum{hh}', 0.0)
        lo, hi = _col(P, f'cum{hh}_q05')[m] - c, _col(P, f'cum{hh}_q95')[m] + c
        r[f'cum{hh}_cov90'] = float(np.mean((y >= lo) & (y <= hi))) if m.any() else None
    for i, hh in enumerate((3, 5)):
        m = S.cliff_mask[:, i]
        if not m.any():
            continue
        o = S.cliff[m, i].astype(float)
        p = _col(P, f'cliff_p{hh}')[m]
        br = (base_rate or {}).get(f'cliff{hh}', float(o.mean()))
        r[f'cliff{hh}_n'] = int(m.sum())
        r[f'cliff{hh}_events'] = int(o.sum())
        r[f'cliff{hh}_brier'] = brier(p, o)
        r[f'cliff{hh}_brier_climatology_train_rate'] = brier(np.full_like(o, br), o)
        r[f'cliff{hh}_brier_climatology_oracle'] = brier(np.full_like(o, o.mean()), o)
        r[f'cliff{hh}_mean_p'] = float(p.mean())
        try:
            from sklearn.metrics import roc_auc_score
            r[f'cliff{hh}_auc'] = float(roc_auc_score(o, p)) if 0 < o.sum() < len(o) else None
        except Exception:
            r[f'cliff{hh}_auc'] = None
    return r


def fmt(r: dict[str, Any]) -> str:
    f = lambda k: '—' if r.get(k) is None else f'{r[k]:.3f}'
    return (f"n={r['origins']} wk={r['weekends']} | next1 {f('next1_mae')} (pers {f('next1_mae_persistence')}) next3 {f('next3_mae')} next5 {f('next5_mae')} | "
            f"cum3 {f('cum3_mae')} (summed {f('cum3_mae_summed_medians')}) cum5 {f('cum5_mae')} | cov90 h1 {f('next1_cov90')} h3 {f('next3_cov90')} cum5 {f('cum5_cov90')} | "
            f"cliff5 brier {f('cliff5_brier')} clim {f('cliff5_brier_climatology_train_rate')} auc {f('cliff5_auc')}")


__all__ = ['score', 'conformal_margins', 'fmt', 'brier']
