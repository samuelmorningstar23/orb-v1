"""The Orb TyreFormer ensemble: transformer distribution re-centred on a blended median.

For horizons 1..5 the median is  w_h x GBM + (1 - w_h) x transformer; every transformer quantile of that horizon moves by
the same shift, and the 3- and 5-lap cumulative quantiles move by the sum of the shifts of their laps (only when the CV
shows that helps; otherwise the cumulative head is kept). Horizons 6..10 and the cliff head are the transformer's.
Weights and the conformal margins are chosen on the 2023-2025 cross-validation out-of-fold predictions only.

CLI:  python -m tyreformer.blend      (fits weights and margins on CV, writes *_ensemble.parquet for cv/temporal/rolling)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from tyreformer import OUT
from tyreformer.data import SampleSet, CACHE, H
from tyreformer.metrics import conformal_margins, score, fmt
from tyreformer.model import QUANTILES
from tyreformer.train import PRED

KEY = ['race_id', 'session', 'driver', 'lap']
QCOLS = [f'q{int(round(q * 100)):02d}' for q in QUANTILES]
GRID = np.round(np.arange(0.0, 1.01, 0.1), 2)


def align(P: pd.DataFrame, S: SampleSet) -> pd.DataFrame:
    key = S.meta[KEY].astype(str).agg('|'.join, axis=1)
    pk = P[KEY].astype(str).agg('|'.join, axis=1)
    return P.set_index(pk).loc[key].reset_index(drop=True)


def apply(tf: pd.DataFrame, gbm: pd.DataFrame, weights: dict[str, float], cum_shift: dict[str, bool]) -> pd.DataFrame:
    g = gbm.set_index(KEY)
    out = tf.copy()
    idx = pd.MultiIndex.from_frame(out[KEY])
    shifts = {}
    for h in range(1, 6):
        w = float(weights.get(f'h{h}', 0.0))
        gm = g[f'h{h}_q50'].reindex(idx).to_numpy()
        out[f'tf_h{h}_q50'] = out[f'h{h}_q50']
        out[f'gbm_h{h}_q50'] = gm
        sh = np.where(np.isfinite(gm), w * (gm - out[f'h{h}_q50'].to_numpy()), 0.0)
        shifts[h] = sh
        for q in QCOLS:
            out[f'h{h}_{q}'] = out[f'h{h}_{q}'] + sh
    for hh in (3, 5):
        out[f'tf_cum{hh}_q50'] = out[f'cum{hh}_q50']
        if cum_shift.get(f'cum{hh}', False):
            tot = np.sum([shifts[h] for h in range(1, hh + 1)], axis=0)
            for q in QCOLS:
                out[f'cum{hh}_{q}'] = out[f'cum{hh}_{q}'] + tot
    out['model'] = 'orb_tyreformer_ensemble'
    return out


def fit_weights(S: SampleSet, tf: pd.DataFrame, gbm: pd.DataFrame) -> tuple[dict[str, float], dict[str, bool], dict]:
    y = S.anchor[:, None] + S.target
    weights, table = {}, {}
    for h in range(1, 6):
        m = S.target_mask[:, h - 1] & np.isfinite(gbm[f'h{h}_q50'].to_numpy())
        t, gg, yy = tf[f'h{h}_q50'].to_numpy()[m], gbm[f'h{h}_q50'].to_numpy()[m], y[m, h - 1]
        maes = {float(w): float(np.mean(np.abs(w * gg + (1 - w) * t - yy))) for w in GRID}
        best = min(maes, key=maes.get)
        weights[f'h{h}'] = best
        table[f'h{h}'] = maes
    cum_shift = {}
    trial = apply(tf, gbm, weights, {'cum3': True, 'cum5': True})
    for i, hh in enumerate((3, 5)):
        m = S.cum_mask[:, i]
        yy = hh * S.anchor[m] + S.cum[m, i]
        keep = float(np.mean(np.abs(tf[f'cum{hh}_q50'].to_numpy()[m] - yy)))
        shifted = float(np.mean(np.abs(trial[f'cum{hh}_q50'].to_numpy()[m] - yy)))
        cum_shift[f'cum{hh}'] = shifted < keep
        table[f'cum{hh}'] = dict(transformer_head=keep, shifted_by_blend=shifted)
    return weights, cum_shift, table


def main(argv=None) -> int:
    S = SampleSet.load(CACHE / 'samples_dev_v3.npz')
    D = S.subset(S.meta['season'].to_numpy() <= 2025)
    tf_cv = align(pd.read_parquet(PRED / 'cv_final.parquet'), D)
    gbm_cv = pd.read_parquet(PRED / 'gbm_cv_final.parquet')
    weights, cum_shift, table = fit_weights(D, tf_cv, align(gbm_cv, D))
    ens_cv = apply(tf_cv, gbm_cv, weights, cum_shift)
    margins = conformal_margins(D, ens_cv)
    margins_tf = conformal_margins(D, tf_cv)
    base = dict(cliff3=float(D.cliff[D.cliff_mask[:, 0], 0].mean()), cliff5=float(D.cliff[D.cliff_mask[:, 1], 1].mean()))
    cfg = dict(weights=weights, cum_shift=cum_shift, weight_table=table, conformal_margins=margins, conformal_margins_transformer_only=margins_tf, cliff_base_rates_2023_2025=base,
               chosen_on='5-fold weekend-grouped cross-validation, 2023-2025 development weekends (no 2026 race, no sealed weekend)')
    (OUT / 'ensemble.json').write_text(json.dumps(cfg, indent=1), encoding='utf-8')
    (OUT / 'conformal_margins.json').write_text(json.dumps(margins, indent=1), encoding='utf-8')
    ens_cv.to_parquet(PRED / 'cv_ensemble.parquet', index=False)
    print('weights', weights, 'cum shift', cum_shift)
    print('CV transformer:', fmt(score(D, tf_cv, margins=margins_tf, base_rate=base)))
    print('CV ensemble:   ', fmt(score(D, ens_cv, margins=margins, base_rate=base)))
    T26 = S.subset(S.meta['season'].to_numpy() == 2026)
    for exp in ('temporal', 'rolling'):
        tfp, gp = PRED / f'{exp}_final.parquet', PRED / f'gbm_{exp}_final.parquet'
        if tfp.exists() and gp.exists():
            ens = apply(align(pd.read_parquet(tfp), T26), pd.read_parquet(gp), weights, cum_shift)
            ens.to_parquet(PRED / f'{exp}_ensemble.parquet', index=False)
            print(f'2026 {exp} ensemble:', fmt(score(T26, ens, margins=margins, base_rate=base)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
