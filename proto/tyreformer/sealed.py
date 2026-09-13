"""One-shot sealed-holdout scoring of Orb TyreFormer, aggregate only, behind its own freeze record.

    python -m tyreformer.sealed freeze     writes tyreformer/FREEZE.json: sha256 of the frozen transformer and tree models
                                           (both trained on 2023-2025 development weekends only), the ensemble weights and
                                           conformal margins (chosen on 2023-2025 cross-validation), the sample file and
                                           every source file of the package. An existing freeze is never overwritten.
    python -m tyreformer.sealed score      verifies every hash against the freeze (refuses on any mismatch), then scores the
                                           six sealed weekends of evaluation/holdout/sealed_holdout_manifest.json:
                                           TyreFormer ensemble and the Orb v1 live estimator (leave-one-out priors from the
                                           non-sealed weekends) on identical origins. Writes out/tyreformer/sealed_holdout_aggregate.json
                                           with pooled numbers only (no per-weekend value); per-race working files live in
                                           the caller's scratch directory and are deleted afterwards.
The Orb v1 freeze (evaluation/holdout/freeze.json) and the sealed manifest pair are read, never written.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from tyreformer import OUT, PROTO
from tyreformer.data import SampleSet, CACHE, build_all, sealed_ids
from tyreformer.train import MODELS, load_models, predict, predictions_frame

FREEZE = PROTO / 'tyreformer' / 'FREEZE.json'
AGG = OUT / 'sealed_holdout_aggregate.json'
LABEL = 'sealed holdout, aggregate only'


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


MODEL_CODE = ('__init__.py', 'data.py', 'model.py', 'train.py', 'gbm.py', 'blend.py', 'metrics.py', 'headtohead.py', 'sealed.py', 'baseline_kalman.py')


def frozen_files() -> list[Path]:
    files = [PROTO / 'tyreformer' / f for f in MODEL_CODE]
    files += [MODELS / 'temporal_final.pt', MODELS / 'gbm_temporal_final.pkl', OUT / 'ensemble.json', OUT / 'conformal_margins.json', CACHE / 'samples_dev_v3.npz',
              PROTO / 'tyreformer' / 'data' / 'pirelli_compounds.csv']
    return files


def freeze(note: str) -> dict:
    if FREEZE.exists():
        raise PermissionError(f'{FREEZE} exists: a stamped freeze is never overwritten')
    rec = dict(model='Orb TyreFormer ensemble (transformer temporal_final + gradient-boosted median experts gbm_temporal_final)', frozen_at=time.strftime('%Y-%m-%dT%H:%M:%S+05:30'),
               frozen_by='lead', training_data='2023-2025 development weekends only (sealed weekends refused by tyreformer.data)',
               selection='architecture, hyperparameters, ensemble weights and conformal margins chosen on 5-fold weekend-grouped cross-validation of 2023-2025; '
                         'no sealed weekend was loaded before this freeze', sealed_race_ids=sorted(sealed_ids()),
               orb_v1_freeze_sha256=_sha(PROTO / 'evaluation' / 'holdout' / 'freeze.json'), note=note,
               files={str(p.relative_to(PROTO)): _sha(p) for p in frozen_files()})
    FREEZE.write_text(json.dumps(rec, indent=1), encoding='utf-8')
    return rec


def verify() -> dict:
    if not FREEZE.exists():
        raise PermissionError('no tyreformer/FREEZE.json: the sealed holdout is not scored before a freeze')
    rec = json.loads(FREEZE.read_text(encoding='utf-8'))
    bad = [f for f, h in rec['files'].items() if not (PROTO / f).exists() or _sha(PROTO / f) != h]
    if bad:
        raise PermissionError(f'files changed since the freeze: {bad}')
    return rec


def gbm_predict(S: SampleSet, name: str = 'gbm_temporal_final') -> pd.DataFrame:
    from tyreformer.gbm import features
    blob = pickle.loads((MODELS / f'{name}.pkl').read_bytes())
    X = features(S)
    out = S.meta[['race_id', 'season', 'event', 'session', 'driver', 'lap']].copy()
    for h, m in blob['models'].items():
        out[f'h{h}_q50'] = S.anchor + m.predict(X)
    return out


def score_weekends(race_ids: list[str], workdir: Path, allow_sealed: bool) -> dict:
    """TyreFormer ensemble (frozen temporal models) and the Orb v1 estimator on the given race weekends, pooled only."""
    from tyreformer.blend import apply
    from tyreformer.headtohead import origin_table, attach_tyreformer, compare
    from tyreformer.metrics import score
    from tyreformer import baseline_kalman as BK
    ens = json.loads((OUT / 'ensemble.json').read_text(encoding='utf-8'))
    seasons = sorted({int(r.split('_', 1)[0]) for r in race_ids})
    parts = []
    for season in seasons:
        evs = [r.split('_', 1)[1] for r in race_ids if r.startswith(f'{season}_')]
        S_s = build_all([season], sessions=('R',), allow_sealed=allow_sealed, only_sealed=allow_sealed, quiet=True, workers=1)
        parts.append(S_s.subset(S_s.meta['event'].isin(evs).to_numpy()))
    S = SampleSet.concat(parts)
    assert set(S.meta['race_id']) <= set(race_ids), 'samples outside the requested weekends'
    models, _ = load_models('temporal_final')
    tf = predictions_frame(S, predict(models, S), 'tyreformer_temporal_final')
    P = apply(tf, gbm_predict(S), ens['weights'], ens['cum_shift'])
    for season in seasons:
        evs = [r.split('_', 1)[1] for r in race_ids if r.startswith(f'{season}_')]
        BK.run([season], events=evs, include_sealed=allow_sealed, out_dir=workdir, quiet=True, workers=1)
    K = pd.concat([BK.read_frame(workdir / f'{r}.parquet') for r in race_ids if (workdir / f'{r}.parquet').exists()], ignore_index=True)
    K = K[K['race_id'].isin(race_ids)]
    M = attach_tyreformer(origin_table(K), P, ens['conformal_margins'])
    return dict(weekends_requested=len(race_ids), weekends_scored=int(M['race_id'].nunique()), estimator_races=int(K['race_id'].nunique()),
                head_to_head=compare(M, bootstrap=True, base_rates=ens['cliff_base_rates_2023_2025']),
                tyreformer_all_origins=score(S, P, margins=ens['conformal_margins'], base_rate=ens['cliff_base_rates_2023_2025']))


def score_sealed(workdir: Path) -> dict:
    rec = verify()
    sealed = sorted(sealed_ids())
    res = score_weekends(sealed, workdir, allow_sealed=True)
    out = dict(label=LABEL, quotable=True, generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'), freeze=dict(path=str(FREEZE.relative_to(PROTO)), frozen_at=rec['frozen_at'], sha256=_sha(FREEZE)),
               sealed_weekends=len(sealed), **res,
               rules='pooled over the sealed weekends only; weekend-grouped bootstrap; no per-weekend value is written; per-race working files deleted after scoring')
    AGG.write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('action', choices=('freeze', 'verify', 'score'))
    ap.add_argument('--note', default='')
    a = ap.parse_args(argv)
    if a.action == 'freeze':
        r = freeze(a.note)
        print(f"frozen {len(r['files'])} files at {r['frozen_at']} -> {FREEZE}")
    elif a.action == 'verify':
        verify()
        print('freeze verified: every frozen file matches')
    else:
        work = Path(tempfile.mkdtemp(prefix='tyreformer_sealed_'))
        try:
            out = score_sealed(work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        h = out['head_to_head']
        for k in ('next1', 'next3', 'next5', 'cum3', 'cum5'):
            if k in h:
                d = h[k]
                print(f"{LABEL}: {k} MAE Orb v1 estimator {d['orb_v1_estimator']:.3f} vs TyreFormer {d['tyreformer']:.3f} (n={d['n']}, {d['weekends']} weekends; P(TF better) {d['p_tyreformer_better']:.2f})")
        for k in ('cliff5',):
            if k in h:
                d = h[k]
                print(f"{LABEL}: {k} Brier estimator {d['orb_v1_estimator_brier']:.3f} vs TyreFormer {d['tyreformer_brier']:.3f} (climatology {d['climatology_train_rate']:.3f})")
        print(f'wrote {AGG}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
