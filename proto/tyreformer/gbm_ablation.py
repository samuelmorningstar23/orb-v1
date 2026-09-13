"""Ablation: is the sequence model needed? Gradient-boosted trees on the same inputs, flattened.

Features: the TyreFormer context vector plus the last 6 lap tokens flattened (the same causal inputs, without attention
over the full 24-lap window). One HistGradientBoostingRegressor (absolute-error / median loss) per horizon h = 1, 3, 5,
trained on the identical 5 weekend-grouped folds of 2023-2025 used by tyreformer.train (same seed, same assignment).
Writes out/tyreformer/predictions/gbm_cv.parquet (race_id, session, driver, lap, h1/h3/h5 medians).
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from tyreformer.data import SampleSet, CACHE
from tyreformer.train import PRED

LAST = 6


def features(S: SampleSet) -> np.ndarray:
    return np.concatenate([S.context, S.tokens[:, -LAST:, :].reshape(len(S), -1)], axis=1)


def main(samples: str = 'samples_dev_v3.npz') -> None:
    S = SampleSet.load(CACHE / samples)
    D = S.subset(S.meta['season'].to_numpy() <= 2025)
    rids = np.array(sorted(D.meta['race_id'].unique()))
    order = np.random.default_rng(2026).permutation(rids)
    folds = {r: i % 5 for i, r in enumerate(order)}
    fold = D.meta['race_id'].map(folds).to_numpy()
    X = features(D)
    out = D.meta[['race_id', 'session', 'driver', 'lap']].copy()
    t0 = time.time()
    for h in (1, 3, 5):
        pred = np.full(len(D), np.nan)
        for f in range(5):
            tr = (fold != f) & D.target_mask[:, h - 1]
            te = fold == f
            m = HistGradientBoostingRegressor(loss='absolute_error', max_iter=400, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=80, l2_regularization=1.0,
                                              early_stopping=True, validation_fraction=0.1, random_state=h * 10 + f)
            m.fit(X[tr], np.clip(D.target[tr, h - 1], -6, 12))
            pred[te] = D.anchor[te] + m.predict(X[te])
            print(f'h{h} fold {f} done ({time.time() - t0:.0f} s)', flush=True)
        out[f'h{h}_q50'] = pred
    out.to_parquet(PRED / 'gbm_cv.parquet', index=False)
    y = D.anchor[:, None] + D.target
    for h in (1, 3, 5):
        mk = D.target_mask[:, h - 1]
        print(f'GBM next{h} MAE {np.mean(np.abs(out[f"h{h}_q50"].to_numpy()[mk] - y[mk, h - 1])):.4f} (n={mk.sum()})')


if __name__ == '__main__':
    main()
