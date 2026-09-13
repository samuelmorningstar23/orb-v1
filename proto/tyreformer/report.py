"""Render out/tyreformer/MODEL_CARD.md from the evaluation outputs (never hand-typed numbers).

Reads out/tyreformer/evaluation.json (required), out/tyreformer/sealed_holdout_aggregate.json and
out/tyreformer/prerace/prerace_eval.json (optional), out/tyreformer/ensemble.json and the frozen model file.
CLI:  python -m tyreformer.report
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tyreformer import OUT, PROTO
from tyreformer.data import TOKEN_FEATURES, CONTEXT_FEATURES, W, H


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def _n_params() -> int | None:
    try:
        from tyreformer.train import load_models
        models, _ = load_models('temporal_final')
        return int(sum(p.numel() for p in models[0].parameters()))
    except Exception:
        return None


def _row(name: str, d: dict, key: str) -> str:
    if not d or key not in d:
        return ''
    x = d[key]
    ci = x.get('difference_ci90') or [float('nan'), float('nan')]
    return (f"| {name} | {x['n']} | {x['orb_v1_estimator']:.3f} | {x['tyreformer']:.3f} | {100 * (x['tyreformer'] / x['orb_v1_estimator'] - 1):+.0f} % | "
            f"{ci[0]:+.3f} to {ci[1]:+.3f} | {x['p_tyreformer_better']:.2f} | {x['weekends_tyreformer_better']}/{x['weekends']} |")


def h2h_block(title: str, h: dict | None) -> list[str]:
    if not h or 'next1' not in h:
        return [f'### {title}', '', 'Not available.', '']
    L = [f'### {title}', '', f"{h['weekends']} races; {h['origins']} scored origins.", '',
         '| metric | n | Orb v1 estimator (s) | Orb TyreFormer (s) | change | difference, 90 % CI | P(TyreFormer better) | races better |', '|---|---|---|---|---|---|---|---|']
    for k, name in (('next1', 'next-lap error'), ('next3', '3 laps ahead'), ('next5', '5 laps ahead'), ('cum3', '3-lap cumulative'), ('cum5', '5-lap cumulative')):
        r = _row(name, h, k)
        if r:
            L.append(r)
    c1 = h.get('next1', {})
    if 'coverage90_tyreformer' in c1:
        L += ['', f"90 % band coverage, next lap: estimator {c1.get('coverage90_orb_v1_estimator', float('nan')):.1%}, TyreFormer {c1['coverage90_tyreformer']:.1%}."]
    cl = h.get('cliff5')
    if cl:
        L += [f"Cliff within 5 laps (prefix_eval.py rule, {cl['events']} events in {cl['n']} origins): Brier estimator {cl['orb_v1_estimator_brier']:.3f}, "
              f"TyreFormer {cl['tyreformer_brier']:.3f}, constant training base rate {cl['climatology_train_rate']:.3f}."]
    return L + ['']


def main(argv=None) -> int:
    ev = _load(OUT / 'evaluation.json')
    if ev is None:
        raise SystemExit('run python -m tyreformer.evaluate first')
    sealed = _load(OUT / 'sealed_holdout_aggregate.json')
    pre = _load(OUT / 'prerace' / 'prerace_eval.json')
    ens = _load(OUT / 'ensemble.json') or {}
    freeze = _load(PROTO / 'tyreformer' / 'FREEZE.json')
    n_params = _n_params()
    data = ev['data']
    lad = ev['cv_2023_2025']['ladder']
    L = ['# Orb TyreFormer: model card', '',
         'A learned, probabilistic tyre model. At the end of every lap it forecasts the car\'s next 1 to 10 fuel-corrected lap times on the',
         'current tyres, with calibrated 90 % bands, the 3- and 5-lap time loss, and the probability of a pace cliff within 3 and 5 laps.',
         'It learns from every race and sprint stint of four seasons of public timing and telemetry-derived data, and it is scored against',
         'the Orb v1 live estimator on exactly the laps and targets that estimator is scored on.', '',
         '## Why it exists', '',
         'The Orb v1 estimator of record is linear-Gaussian with fixed regime rules. Its own evaluation (out/live/PREFIX_EVAL.md) records',
         'two limits: its cliff probabilities score worse than climatology in every race, and at Austria the pre-race prior alone beats it',
         'at 3 and 5 laps because the slope moves inside the stint. A model that has seen thousands of stints can learn warm-up, fuel,',
         'traffic, track evolution and non-linear wear directly instead of assuming them.', '',
         '## Data', '',
         f"- Forecast origins by season: {', '.join(f'{k}: {v:,}' for k, v in data['origins_by_season'].items())}; weekends by season: "
         f"{', '.join(f'{k}: {v}' for k, v in data['weekends_by_season'].items())}; {data['horizon_targets']:,} horizon targets.",
         f"- Sealed holdout weekends excluded from every training and selection set: {', '.join(ev['sealed_excluded'])}.",
         '- Per lap (token): lap time against the current level, clean flag, tyre age, race progress, traffic share, track status, pit and',
         '  deletion flags, compound, tyre-energy, lateral and longitudinal energy, full-throttle share, sector losses against the stint best,',
         '  feed quality, and a causal field signal (how the rest of the field\'s laps just changed).',
         '- Per forecast (context): stint and tyre-set state, track temperature and its change since practice, rain, season, sprint flag,',
         '  the weekend\'s Orb v1 pre-race forecast for every compound (strict leave-one-out), compound pace offsets, and the Pirelli',
         '  C-number nomination (procured and verified for 82 of 82 weekends, tyreformer/data/SOURCES.md).',
         '- Lap arithmetic and the clean-lap rule are the live estimator\'s own; tests assert the flags and cliff labels are identical.', '',
         '## Model', '',
         f"- Transformer over the last {W} laps plus one context token: d=96, 3 pre-norm layers, 4 heads{f', {n_params:,} parameters' if n_params else ''}; a circuit embedding",
         '  dropped to "unknown" half the time in training, so unseen circuits (Madrid 2026) are handled; monotone quantile heads for',
         f"  {H} horizons x 7 quantiles, cumulative 3- and 5-lap heads, and cliff heads.",
         '- Gradient-boosted median experts for 1 to 5 laps ahead on the same causal inputs (an ablation showed trees win at the nearest',
         '  horizons, the transformer further out).',
         f"- Ensemble: median = w x trees + (1 - w) x transformer per horizon, w = {ens.get('weights')}; the transformer's quantiles move with the",
         '  median; split-conformal margins widen the bands to 90 % coverage. Weights and margins were chosen on 2023-2025 cross-validation only.', '',
         '## Protocol', '',
         '- Model selection: 5-fold cross-validation grouped by weekend, 2023-2025 only.',
         '- Temporal test: trained on 2023-2025, scored on every 2026 race (new cars, new tyres, never seen).',
         '- Deployment protocol: race r of 2026 forecast by a model trained on 2023-2025 plus the 2026 races before r.',
         '- One early one-seed probe was scored on 2026 to check the pipeline before any tuning; no modelling choice used a 2026 number.',
         '- The estimator baseline is the real LiveTyreStateEstimator, reproducing out/live/prefix_eval.json exactly with the product priors.', '',
         '## Results', '', '### Ablation ladder, 2023-2025 cross-validation (race and sprint origins)', '',
         '| model | next lap | 3 laps | 5 laps | 5-lap cumulative | next-lap 90 % coverage |', '|---|---|---|---|---|---|']
    e = lad['ensemble']
    L.append(f"| current pace (persistence) | {e['next1_mae_persistence']:.3f} | {e['next3_mae_persistence']:.3f} | {e['next5_mae_persistence']:.3f} | {e['cum5_mae_persistence']:.3f} | |")
    L.append(f"| gradient-boosted trees | {lad['trees_only']['next1_mae']:.3f} | {lad['trees_only']['next3_mae']:.3f} | {lad['trees_only']['next5_mae']:.3f} | | |")
    for name in ('transformer', 'ensemble'):
        r = lad[name]
        L.append(f"| {name} | {r['next1_mae']:.3f} | {r['next3_mae']:.3f} | {r['next5_mae']:.3f} | {r['cum5_mae']:.3f} | {r['next1_cov90']:.1%} |")
    L.append('')
    L += h2h_block('Head to head, 2023-2025 cross-validation', ev['cv_2023_2025'].get('head_to_head'))
    L += h2h_block('Head to head, 2026 deployment protocol (trained on 2023-2025 and earlier 2026 races only)', (ev.get('test_2026_rolling') or {}).get('head_to_head'))
    L += h2h_block('Head to head, 2026 strict temporal test (trained on 2023-2025 only)', (ev.get('test_2026_temporal') or {}).get('head_to_head'))
    if sealed:
        L += h2h_block(f"Sealed holdout, aggregate only (freeze {sealed['freeze']['frozen_at']})", sealed.get('head_to_head'))
    else:
        L += ['### Sealed holdout', '', 'Not yet scored.', '']
    if pre:
        sel = pre['selection']['chosen_model']
        L += ['## Companion: learned practice-to-race transfer (tyreformer/prerace.py)', '',
              f"A small regularised model ({sel}) predicts the race-derived degradation slope per compound-weekend from practice, the Orb v1 forecast,",
              'the Pirelli C-number and strictly earlier seasons of the same circuit. Selected on protocol A only. Full table: out/tyreformer/prerace/PRERACE.md.', '',
              '| protocol | rows / weekends | Orb v1 MAE | learned MAE | Orb v1 r | learned r |', '|---|---|---|---|---|---|']
        for key, name in (('A', 'A: leave one weekend out, 2023-2026'), ('B', 'B: trained 2023-2025, tested 2026')):
            pm = pre['protocols'][key]['metrics']
            o, l = pm.get('orb_v1', {}), pm.get(sel, {})
            f = lambda d, k: '—' if d.get(k) is None else f"{d[k]:.4f}"
            g = lambda d, k: '—' if d.get(k) is None else f"{d[k]:.2f}"
            L.append(f"| {name} | {pre['protocols'][key]['n_rows']} / {pre['protocols'][key]['n_weekends']} | {f(o, 'mae')} | {f(l, 'mae')} | {g(o, 'pearson_r')} | {g(l, 'pearson_r')} |")
        L += ['', 'Reading: across four seasons it beats Orb v1 (most of the gain is shrinkage toward typical degradation, and it also beats that constant);',
              'on 2026 alone it does not beat Orb v1, whose in-season factor is strong there. It is a second opinion for pre-race curves, not a replacement.', '']
    L += ['## Limits', '',
          '- Public data only: no tyre temperatures, pressures or wear are observed; the model learns them through lap times and energy proxies.',
          '- The cliff label (prefix_eval.py rule) is dominated by lap-to-lap noise; the learned probability is calibrated but its skill over a constant',
          '  base rate is small. It is shown as a risk, not a prediction of an event.',
          '- 2026 is a distribution shift (new regulations); bands calibrated on 2023-2025 can under-cover there, and the numbers above say by how much.',
          '- The estimator baseline\'s 2026 priors are leave-one-out within the season, so they include later 2026 weekends: a small edge to the estimator.',
          '- Not the estimator of record in the shipping dashboard unless the lead integrates it; replay forecasts are exported for that.', '',
          '## Use', '', '```',
          'python -m tyreformer.data --out out/tyreformer/cache/samples_dev_v3.npz      # 58k origins in seconds',
          'python -m tyreformer.train --experiment cv|temporal|rolling|production ...    # see out/tyreformer/logs/train_*.json for the exact flags',
          'python -m tyreformer.gbm --experiment cv|temporal|rolling|production',
          'python -m tyreformer.blend && python -m tyreformer.evaluate && python -m tyreformer.figures',
          'python -m tyreformer.sealed freeze | verify | score                             # one-shot, aggregate only',
          'python -m tyreformer.export                                                     # out/tyreformer/live/2026_<event>.parquet for the dashboard',
          '```', '', 'Live API: `tyreformer.infer.TyreFormerLive(model).forecast(season, event, laps_so_far, driver, n_laps, priors)`; refuses any lap completed after the forecast moment.', '']
    if freeze:
        L += [f"Freeze: tyreformer/FREEZE.json, {len(freeze['files'])} files hashed at {freeze['frozen_at']}.", '']
    (OUT / 'MODEL_CARD.md').write_text('\n'.join(L), encoding='utf-8')
    print(f"wrote {OUT / 'MODEL_CARD.md'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
