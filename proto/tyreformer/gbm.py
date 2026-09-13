"""Gradient-boosted median experts for horizons 1..5, the second half of the Orb TyreFormer ensemble.

The ablation (tyreformer/gbm_ablation.py) showed trees on the same causal inputs beat the transformer's median at the
nearest horizons while the transformer wins further out; the blend of the two beats both (weights chosen on the 2023-2025
cross-validation only, tyreformer/blend.py). Same experiments and splits as tyreformer.train:
    cv          the identical 5 weekend-grouped folds of 2023-2025
    temporal    trained on 2023-2025, predicts 2026
    rolling     2026 in calendar order, trained on 2023-2025 plus the earlier 2026 races
    production  trained on every development weekend of 2023-2026 (models pickled)
Features: context vector + the last 6 lap tokens flattened. Loss: absolute error (median). Early stopping on 10 % of rows.

CLI:  python -m tyreformer.gbm --experiment cv|temporal|rolling|production [--samples samples_dev_v3.npz]
"""
from __future__ import annotations

import argparse
import pickle
import time
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from tyreformer import OUT
from tyreformer.data import SampleSet, CACHE
from tyreformer.train import PRED, MODELS

HORIZONS = (1, 2, 3, 4, 5)
LAST = 6
PARAMS = dict(loss='absolute_error', max_iter=400, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=80, l2_regularization=1.0, early_stopping=True, validation_fraction=0.1)


def features(S: SampleSet) -> np.ndarray:
    return np.concatenate([S.context, S.tokens[:, -LAST:, :].reshape(len(S), -1)], axis=1)


def fit_predict(args):
    Xtr, ytr, Xte, seed = args
    m = HistGradientBoostingRegressor(random_state=seed, **PARAMS)
    m.fit(Xtr, np.clip(ytr, -6, 12))
    return (m.predict(Xte) if Xte is not None else None), m


def _jobs(S_tr: SampleSet, S_te: SampleSet | None, seed: int):
    Xtr = features(S_tr)
    Xte = features(S_te) if S_te is not None else None
    for h in HORIZONS:
        m = S_tr.target_mask[:, h - 1]
        yield h, (Xtr[m], S_tr.target[m, h - 1], Xte, seed * 100 + h)


def run_split(S_tr: SampleSet, S_te: SampleSet | None, seed: int, workers: int = 5) -> tuple[dict[int, np.ndarray], dict[int, HistGradientBoostingRegressor]]:
    jobs = list(_jobs(S_tr, S_te, seed))
    preds, models = {}, {}
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for (h, _), (p, m) in zip(jobs, ex.map(fit_predict, [j for _, j in jobs])):
            preds[h] = p
            models[h] = m
    return preds, models


def frame(S: SampleSet, preds: dict[int, np.ndarray]) -> pd.DataFrame:
    out = S.meta[['race_id', 'season', 'event', 'session', 'driver', 'lap']].copy()
    for h, p in preds.items():
        out[f'h{h}_q50'] = S.anchor + p
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--experiment', required=True, choices=('cv', 'temporal', 'rolling', 'production'))
    ap.add_argument('--samples', default='samples_dev_v3.npz')
    ap.add_argument('--tag', default='final')
    ap.add_argument('--workers', type=int, default=5)
    a = ap.parse_args(argv)
    S = SampleSet.load(CACHE / a.samples)
    season = S.meta['season'].to_numpy()
    t0 = time.time()
    name = f'gbm_{a.experiment}_{a.tag}'
    if a.experiment == 'cv':
        D = S.subset(season <= 2025)
        rids = np.array(sorted(D.meta['race_id'].unique()))
        order = np.random.default_rng(2026).permutation(rids)          # identical fold assignment to tyreformer.train
        folds = {r: i % 5 for i, r in enumerate(order)}
        fold = D.meta['race_id'].map(folds).to_numpy()
        parts = []
        for f in range(5):
            tr, te = D.subset(fold != f), D.subset(fold == f)
            preds, _ = run_split(tr, te, seed=f, workers=a.workers)
            parts.append(frame(te, preds))
            print(f'fold {f} ({time.time() - t0:.0f} s)', flush=True)
        pd.concat(parts, ignore_index=True).to_parquet(PRED / f'{name}.parquet', index=False)
    elif a.experiment == 'temporal':
        tr, te = S.subset(season <= 2025), S.subset(season == 2026)
        preds, models = run_split(tr, te, seed=70, workers=a.workers)
        frame(te, preds).to_parquet(PRED / f'{name}.parquet', index=False)
        MODELS.mkdir(parents=True, exist_ok=True)
        (MODELS / f'{name}.pkl').write_bytes(pickle.dumps(dict(models=models, last=LAST, horizons=HORIZONS, params=PARAMS, train='2023-2025 development weekends')))
    elif a.experiment == 'rolling':
        from evaluation import CALENDAR_2026
        ev = S.meta['event'].to_numpy()
        parts = []
        for i, e in enumerate(CALENDAR_2026):
            te_m = (season == 2026) & (ev == e)
            if not te_m.any():
                continue
            tr_m = (season <= 2025) | ((season == 2026) & np.isin(ev, list(CALENDAR_2026[:i])))
            preds, _ = run_split(S.subset(tr_m), S.subset(te_m), seed=80 + i, workers=a.workers)
            parts.append(frame(S.subset(te_m), preds))
            print(f'rolling {e} ({time.time() - t0:.0f} s)', flush=True)
        pd.concat(parts, ignore_index=True).to_parquet(PRED / f'{name}.parquet', index=False)
    else:
        _, models = run_split(S, None, seed=90, workers=a.workers)
        MODELS.mkdir(parents=True, exist_ok=True)
        (MODELS / f'{name}.pkl').write_bytes(pickle.dumps(dict(models=models, last=LAST, horizons=HORIZONS, params=PARAMS, train='2023-2026 development weekends')))
    print(f'{name} done in {time.time() - t0:.0f} s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
