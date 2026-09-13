"""Model selection by 5-fold weekend-grouped cross-validation on 2023-2025 only (2026 is the untouched temporal test).

CLI:  python -m tyreformer.sweep --configs A,B,C [--seeds 1]
Writes out/tyreformer/predictions/cv_<name>.parquet and appends one JSON line per config to out/tyreformer/logs/sweep.jsonl.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, replace

import numpy as np
import pandas as pd

from tyreformer import OUT
from tyreformer.data import SampleSet, CACHE
from tyreformer.metrics import score, fmt, conformal_margins
from tyreformer.train import Config, run, PRED

CONFIGS = {
    'A': Config(),
    'B': Config(d=64, layers=2, dropout=0.2, circuit_dropout=0.3, weight_decay=0.1),
    'C': Config(d=96, layers=3, dropout=0.2, circuit_dropout=0.5, lr=1e-3),
    'D': Config(d=64, layers=2, dropout=0.2, circuit_dropout=1.0, weight_decay=0.1),
    'E': Config(d=64, layers=2, dropout=0.2, circuit_dropout=0.3, weight_decay=0.1, w_cliff=1.0),
    'F': Config(d=128, layers=4, dropout=0.3, circuit_dropout=0.5, lr=7e-4, weight_decay=0.1),
    'G': Config(d=64, layers=2, dropout=0.3, circuit_dropout=0.5, weight_decay=0.2, lr=1e-3, batch=512),
    'C2': Config(d=96, layers=3, dropout=0.2, circuit_dropout=0.5, lr=5e-4, epochs=60, patience=8),
    'C3': Config(d=96, layers=3, dropout=0.2, circuit_dropout=0.5, lr=1e-3, horizon_weighting='inv_sqrt'),
    'C4': Config(d=128, layers=3, dropout=0.25, circuit_dropout=0.5, lr=1e-3),
}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--configs', default='A,B,C')
    ap.add_argument('--seeds', type=int, default=1)
    ap.add_argument('--samples', default='samples_dev.npz')
    ap.add_argument('--prefix', default='')
    a = ap.parse_args(argv)
    S = SampleSet.load(CACHE / a.samples)
    D = S.subset(S.meta['season'].to_numpy() <= 2025)
    base = dict(cliff3=float(D.cliff[D.cliff_mask[:, 0], 0].mean()), cliff5=float(D.cliff[D.cliff_mask[:, 1], 1].mean()))
    for name in a.configs.split(','):
        cfg = CONFIGS[name]
        t0 = time.time()
        tag = a.prefix + name
        run('cv', a.seeds, cfg, quiet=True, tag=tag, samples=a.samples)
        P = pd.read_parquet(PRED / f'cv_{tag}.parquet')
        key = D.meta[['race_id', 'session', 'driver', 'lap']].astype(str).agg('|'.join, axis=1)
        pk = P[['race_id', 'session', 'driver', 'lap']].astype(str).agg('|'.join, axis=1)
        P = P.set_index(pk).loc[key].reset_index(drop=True)
        r = score(D, P, base_rate=base)
        margins = conformal_margins(D, P)
        rc = score(D, P, margins=margins, base_rate=base)
        line = dict(config=tag, samples=a.samples, params=asdict(cfg), seeds=a.seeds, seconds=round(time.time() - t0, 1), raw=r, conformal=dict(margins=margins, next1_cov90=rc['next1_cov90'], next3_cov90=rc['next3_cov90'], cum5_cov90=rc['cum5_cov90']))
        (OUT / 'logs').mkdir(parents=True, exist_ok=True)
        with (OUT / 'logs' / 'sweep.jsonl').open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(line, default=str) + '\n')
        print(f'{tag} ({time.time() - t0:.0f} s): {fmt(r)}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
