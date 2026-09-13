"""Final evaluation of Orb TyreFormer: ablation ladder, and head to head with the Orb v1 live estimator.

    cv_2023_2025      5-fold weekend-grouped CV (model selection happened here): persistence, trees only, transformer only,
                      ensemble; and the ensemble against the estimator on identical race origins
    test_2026_temporal  model trained on 2023-2025 only, every 2026 race (a season and regulation set never seen)
    test_2026_rolling   the deployment protocol: race r forecast by a model trained on 2023-2025 plus 2026 races before r
No 2026 number influenced any modelling choice (one early pipeline probe on 2026 is disclosed in the report); sealed
weekends are absent from every set here.

CLI:  python -m tyreformer.evaluate   -> out/tyreformer/evaluation.json, out/tyreformer/EVALUATION.md
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from tyreformer import OUT
from tyreformer.data import SampleSet, CACHE, sealed_ids
from tyreformer.blend import align
from tyreformer.headtohead import load_kalman, origin_table, attach_tyreformer, compare, per_race
from tyreformer.metrics import score
from tyreformer.train import PRED


def ladder(S: SampleSet, frames: dict[str, pd.DataFrame], margins: dict[str, dict], base: dict[str, float]) -> dict[str, Any]:
    out = {}
    for name, P in frames.items():
        out[name] = score(S, align(P, S), margins=margins.get(name), base_rate=base)
    return out


def h2h(S: SampleSet, P: pd.DataFrame, margins: dict[str, float], base: dict[str, float]) -> dict[str, Any]:
    rids = sorted(S.meta.loc[S.meta['session'] == 'R', 'race_id'].unique())
    K = load_kalman(rids)
    if K.empty:
        return dict(error='no estimator records found in out/tyreformer/kalman')
    missing = sorted(set(rids) - set(K['race_id'].unique()))
    O = origin_table(K)
    M = attach_tyreformer(O, P, margins)
    res = compare(M, bootstrap=True, base_rates=base)
    res['estimator_races_missing'] = missing
    res['per_race'] = per_race(M).round(4).to_dict(orient='records')
    return res


def md_table(title: str, r: dict[str, Any]) -> list[str]:
    L = [f'### {title}', '', f"{r.get('weekends')} races, {r.get('origins')} scored origins (origins without a TyreFormer forecast: {r.get('origins_without_tyreformer')})", '',
         '| metric | n | Orb v1 estimator | Orb TyreFormer | prior-only | TF − estimator, 90% CI | P(TF better) | races TF better |', '|---|---|---|---|---|---|---|---|']
    for k in ('next1', 'next3', 'next5', 'cum3', 'cum5'):
        d = r.get(k)
        if not d:
            continue
        ci = d.get('difference_ci90')
        L.append(f"| {k} MAE (s) | {d['n']} | {d['orb_v1_estimator']:.3f} [{d['orb_v1_estimator_ci90'][0]:.3f}, {d['orb_v1_estimator_ci90'][1]:.3f}] | "
                 f"{d['tyreformer']:.3f} [{d['tyreformer_ci90'][0]:.3f}, {d['tyreformer_ci90'][1]:.3f}] | {d.get('prior_only', float('nan')):.3f} | "
                 f"{ci[0]:+.3f} to {ci[1]:+.3f} | {d['p_tyreformer_better']:.2f} | {d['weekends_tyreformer_better']}/{d['weekends']} |")
    for k in ('next1', 'next3'):
        d = r.get(k)
        if d:
            L.append(f"| {k} 90% coverage | {d['n']} | {d.get('coverage90_orb_v1_estimator', float('nan')):.1%} | {d.get('coverage90_tyreformer', float('nan')):.1%} | | | | |")
    for k in ('cliff3', 'cliff5'):
        d = r.get(k)
        if d:
            L.append(f"| {k} Brier ({d['events']} events) | {d['n']} | {d['orb_v1_estimator_brier']:.3f} | {d['tyreformer_brier']:.3f} | climatology {d['climatology_train_rate']:.3f} | "
                     f"{d['difference_ci90'][0]:+.3f} to {d['difference_ci90'][1]:+.3f} | {d['p_tyreformer_better']:.2f} | {d['weekends_tyreformer_better']}/{d['weekends']} |")
    return L + ['']


def main(argv=None) -> int:
    t0 = time.time()
    S = SampleSet.load(CACHE / 'samples_dev_v3.npz')
    ens_cfg = json.loads((OUT / 'ensemble.json').read_text(encoding='utf-8'))
    margins, margins_tf, base = ens_cfg['conformal_margins'], ens_cfg['conformal_margins_transformer_only'], ens_cfg['cliff_base_rates_2023_2025']
    D = S.subset(S.meta['season'].to_numpy() <= 2025)
    T26 = S.subset(S.meta['season'].to_numpy() == 2026)
    report: dict[str, Any] = dict(generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'), sealed_excluded=sorted(sealed_ids()),
                                  data=dict(origins_by_season={str(k): int(v) for k, v in S.meta.groupby('season').size().items()},
                                            weekends_by_season={str(k): int(v) for k, v in S.meta.groupby('season')['race_id'].nunique().items()},
                                            horizon_targets=int(S.target_mask.sum())),
                                  ensemble=dict(weights=ens_cfg['weights'], cum_shift=ens_cfg['cum_shift'], conformal_margins=margins))
    # ablation ladder on CV (race and sprint origins)
    gbm_cv = pd.read_parquet(PRED / 'gbm_cv_final.parquet')
    persistence = D.meta[['race_id', 'session', 'driver', 'lap']].copy()
    for h in range(1, 11):
        for q in ('q05', 'q10', 'q25', 'q50', 'q75', 'q90', 'q95'):
            persistence[f'h{h}_{q}'] = D.anchor
    frames = dict(transformer=pd.read_parquet(PRED / 'cv_final.parquet'), ensemble=pd.read_parquet(PRED / 'cv_ensemble.parquet'))
    report['cv_2023_2025'] = dict(ladder=ladder(D, frames, dict(transformer=margins_tf, ensemble=margins), base))
    g = align(gbm_cv, D)
    y = D.anchor[:, None] + D.target
    report['cv_2023_2025']['ladder']['trees_only'] = {f'next{h}_mae': float(np.mean(np.abs(g[f'h{h}_q50'].to_numpy()[D.target_mask[:, h - 1]] - y[D.target_mask[:, h - 1], h - 1]))) for h in (1, 3, 5)}
    report['cv_2023_2025']['head_to_head'] = h2h(D, frames['ensemble'], margins, base)
    for exp in ('temporal', 'rolling'):
        p = PRED / f'{exp}_ensemble.parquet'
        if not p.exists():
            continue
        P = pd.read_parquet(p)
        report[f'test_2026_{exp}'] = dict(ensemble=score(T26, align(P, T26), margins=margins, base_rate=base), head_to_head=h2h(T26, P, margins, base))
    (OUT / 'evaluation.json').write_text(json.dumps(report, indent=1, default=float), encoding='utf-8')
    L = ['# Orb TyreFormer evaluation', '', f"Generated {report['generated_at']}. Seconds of corrected lap time. Sealed holdout weekends excluded from every set: {', '.join(report['sealed_excluded'])}.", '',
         '## Ablation ladder (5-fold weekend-grouped CV, 2023-2025, race and sprint origins)', '', '| model | next-lap MAE | 3-lap | 5-lap | cum3 | cum5 | cov90 next | cliff-5 Brier (clim.) | cliff-5 AUC |', '|---|---|---|---|---|---|---|---|---|']
    lad = report['cv_2023_2025']['ladder']
    e = lad['ensemble']
    L.append(f"| persistence (current pace) | {e['next1_mae_persistence']:.3f} | {e['next3_mae_persistence']:.3f} | {e['next5_mae_persistence']:.3f} | {e['cum3_mae_persistence']:.3f} | {e['cum5_mae_persistence']:.3f} | | | |")
    t = lad['trees_only']
    L.append(f"| gradient-boosted trees only | {t['next1_mae']:.3f} | {t['next3_mae']:.3f} | {t['next5_mae']:.3f} | | | | | |")
    for name in ('transformer', 'ensemble'):
        r = lad[name]
        L.append(f"| {name} | {r['next1_mae']:.3f} | {r['next3_mae']:.3f} | {r['next5_mae']:.3f} | {r['cum3_mae']:.3f} | {r['cum5_mae']:.3f} | {r['next1_cov90']:.1%} | {r['cliff5_brier']:.3f} ({r['cliff5_brier_climatology_train_rate']:.3f}) | {r['cliff5_auc']:.3f} |")
    L += ['', '## Head to head with the Orb v1 live estimator (identical race origins and targets)', '']
    L += md_table('Cross-validation, 2023-2025', report['cv_2023_2025']['head_to_head'])
    for exp, title in (('temporal', '2026, trained on 2023-2025 only (season never seen)'), ('rolling', '2026, deployment protocol (2023-2025 + earlier 2026 races only)')):
        if f'test_2026_{exp}' in report:
            L += md_table(title, report[f'test_2026_{exp}']['head_to_head'])
    (OUT / 'EVALUATION.md').write_text('\n'.join(L), encoding='utf-8')
    print('\n'.join(L))
    print(f'evaluation done in {time.time() - t0:.0f} s')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
