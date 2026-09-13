# Orb TyreFormer: model card

A learned, probabilistic tyre model. At the end of every lap it forecasts the car's next 1 to 10 fuel-corrected lap times on the
current tyres, with calibrated 90 % bands, the 3- and 5-lap time loss, and the probability of a pace cliff within 3 and 5 laps.
It learns from every race and sprint stint of four seasons of public timing and telemetry-derived data, and it is scored against
the Orb v1 live estimator on exactly the laps and targets that estimator is scored on.

## Why it exists

The Orb v1 estimator of record is linear-Gaussian with fixed regime rules. Its own evaluation (out/live/PREFIX_EVAL.md) records
two limits: its cliff probabilities score worse than climatology in every race, and at Austria the pre-race prior alone beats it
at 3 and 5 laps because the slope moves inside the stint. A model that has seen thousands of stints can learn warm-up, fuel,
traffic, track evolution and non-linear wear directly instead of assuming them.

## Data

- Forecast origins by season: 2023: 15,430, 2024: 15,591, 2025: 16,165, 2026: 11,383; weekends by season: 2023: 20, 2024: 20, 2025: 21, 2026: 13; 280,282 horizon targets.
- Sealed holdout weekends excluded from every training and selection set: 2023_Canada, 2024_Bahrain, 2024_Monza, 2024_SaudiArabia, 2024_Zandvoort, 2025_Qatar.
- Per lap (token): lap time against the current level, clean flag, tyre age, race progress, traffic share, track status, pit and
  deletion flags, compound, tyre-energy, lateral and longitudinal energy, full-throttle share, sector losses against the stint best,
  feed quality, and a causal field signal (how the rest of the field's laps just changed).
- Per forecast (context): stint and tyre-set state, track temperature and its change since practice, rain, season, sprint flag,
  the weekend's Orb v1 pre-race forecast for every compound (strict leave-one-out), compound pace offsets, and the Pirelli
  C-number nomination (procured and verified for 82 of 82 weekends, tyreformer/data/SOURCES.md).
- Lap arithmetic and the clean-lap rule are the live estimator's own; tests assert the flags and cliff labels are identical.

## Model

- Transformer over the last 24 laps plus one context token: d=96, 3 pre-norm layers, 4 heads, 468,278 parameters; a circuit embedding
  dropped to "unknown" half the time in training, so unseen circuits (Madrid 2026) are handled; monotone quantile heads for
  10 horizons x 7 quantiles, cumulative 3- and 5-lap heads, and cliff heads.
- Gradient-boosted median experts for 1 to 5 laps ahead on the same causal inputs (an ablation showed trees win at the nearest
  horizons, the transformer further out).
- Ensemble: median = w x trees + (1 - w) x transformer per horizon, w = {'h1': 0.8, 'h2': 0.7, 'h3': 0.6, 'h4': 0.5, 'h5': 0.4}; the transformer's quantiles move with the
  median; split-conformal margins widen the bands to 90 % coverage. Weights and margins were chosen on 2023-2025 cross-validation only.

## Protocol

- Model selection: 5-fold cross-validation grouped by weekend, 2023-2025 only.
- Temporal test: trained on 2023-2025, scored on every 2026 race (new cars, new tyres, never seen).
- Deployment protocol: race r of 2026 forecast by a model trained on 2023-2025 plus the 2026 races before r.
- One early one-seed probe was scored on 2026 to check the pipeline before any tuning; no modelling choice used a 2026 number.
- The estimator baseline is the real LiveTyreStateEstimator, reproducing out/live/prefix_eval.json exactly with the product priors.

## Results

### Ablation ladder, 2023-2025 cross-validation (race and sprint origins)

| model | next lap | 3 laps | 5 laps | 5-lap cumulative | next-lap 90 % coverage |
|---|---|---|---|---|---|
| current pace (persistence) | 0.339 | 0.448 | 0.524 | 1.716 | |
| gradient-boosted trees | 0.281 | 0.375 | 0.438 | | |
| transformer | 0.299 | 0.381 | 0.430 | 1.392 | 90.0% |
| ensemble | 0.281 | 0.370 | 0.421 | 1.339 | 90.0% |

### Head to head, 2023-2025 cross-validation

56 races; 42252 scored origins.

| metric | n | Orb v1 estimator (s) | Orb TyreFormer (s) | change | difference, 90 % CI | P(TyreFormer better) | races better |
|---|---|---|---|---|---|---|---|
| next-lap error | 27684 | 0.337 | 0.279 | -17 % | -0.065 to -0.051 | 1.00 | 55/56 |
| 3 laps ahead | 24297 | 0.458 | 0.366 | -20 % | -0.109 to -0.078 | 1.00 | 54/55 |
| 5 laps ahead | 21259 | 0.548 | 0.415 | -24 % | -0.159 to -0.111 | 1.00 | 53/55 |
| 3-lap cumulative | 19654 | 0.988 | 0.776 | -21 % | -0.241 to -0.186 | 1.00 | 55/55 |
| 5-lap cumulative | 14240 | 1.729 | 1.315 | -24 % | -0.478 to -0.358 | 1.00 | 54/55 |

90 % band coverage, next lap: estimator 93.3%, TyreFormer 89.9%.
Cliff within 5 laps (prefix_eval.py rule, 2495 events in 32974 origins): Brier estimator 0.145, TyreFormer 0.069, constant training base rate 0.070.

### Head to head, 2026 deployment protocol (trained on 2023-2025 and earlier 2026 races only)

12 races; 9596 scored origins.

| metric | n | Orb v1 estimator (s) | Orb TyreFormer (s) | change | difference, 90 % CI | P(TyreFormer better) | races better |
|---|---|---|---|---|---|---|---|
| next-lap error | 5960 | 0.421 | 0.351 | -17 % | -0.099 to -0.046 | 1.00 | 12/12 |
| 3 laps ahead | 5215 | 0.522 | 0.424 | -19 % | -0.139 to -0.064 | 1.00 | 12/12 |
| 5 laps ahead | 4562 | 0.593 | 0.453 | -24 % | -0.191 to -0.091 | 1.00 | 11/11 |
| 3-lap cumulative | 3819 | 1.160 | 0.903 | -22 % | -0.362 to -0.167 | 1.00 | 12/12 |
| 5-lap cumulative | 2502 | 1.958 | 1.478 | -25 % | -0.672 to -0.318 | 1.00 | 11/11 |

90 % band coverage, next lap: estimator 87.6%, TyreFormer 87.8%.
Cliff within 5 laps (prefix_eval.py rule, 1027 events in 7625 origins): Brier estimator 0.206, TyreFormer 0.114, constant training base rate 0.120.

### Head to head, 2026 strict temporal test (trained on 2023-2025 only)

12 races; 9596 scored origins.

| metric | n | Orb v1 estimator (s) | Orb TyreFormer (s) | change | difference, 90 % CI | P(TyreFormer better) | races better |
|---|---|---|---|---|---|---|---|
| next-lap error | 5960 | 0.421 | 0.353 | -16 % | -0.099 to -0.043 | 1.00 | 12/12 |
| 3 laps ahead | 5215 | 0.522 | 0.425 | -19 % | -0.140 to -0.062 | 1.00 | 12/12 |
| 5 laps ahead | 4562 | 0.593 | 0.456 | -23 % | -0.189 to -0.091 | 1.00 | 11/11 |
| 3-lap cumulative | 3819 | 1.160 | 0.923 | -20 % | -0.352 to -0.147 | 1.00 | 12/12 |
| 5-lap cumulative | 2502 | 1.958 | 1.512 | -23 % | -0.647 to -0.284 | 1.00 | 11/11 |

90 % band coverage, next lap: estimator 87.6%, TyreFormer 85.2%.
Cliff within 5 laps (prefix_eval.py rule, 1027 events in 7625 origins): Brier estimator 0.206, TyreFormer 0.118, constant training base rate 0.120.

### Sealed holdout, aggregate only (freeze 2026-09-13T06:17:12+05:30)

5 races; 4289 scored origins.

| metric | n | Orb v1 estimator (s) | Orb TyreFormer (s) | change | difference, 90 % CI | P(TyreFormer better) | races better |
|---|---|---|---|---|---|---|---|
| next-lap error | 3007 | 0.289 | 0.243 | -16 % | -0.055 to -0.037 | 1.00 | 5/5 |
| 3 laps ahead | 2685 | 0.367 | 0.305 | -17 % | -0.076 to -0.053 | 1.00 | 5/5 |
| 5 laps ahead | 2389 | 0.437 | 0.347 | -21 % | -0.113 to -0.068 | 1.00 | 5/5 |
| 3-lap cumulative | 2236 | 0.820 | 0.649 | -21 % | -0.198 to -0.148 | 1.00 | 5/5 |
| 5-lap cumulative | 1680 | 1.428 | 1.110 | -22 % | -0.373 to -0.278 | 1.00 | 5/5 |

90 % band coverage, next lap: estimator 94.3%, TyreFormer 90.1%.
Cliff within 5 laps (prefix_eval.py rule, 282 events in 3460 origins): Brier estimator 0.111, TyreFormer 0.072, constant training base rate 0.075.

## Companion: learned practice-to-race transfer (tyreformer/prerace.py)

A small regularised model (huber_obs) predicts the race-derived degradation slope per compound-weekend from practice, the Orb v1 forecast,
the Pirelli C-number and strictly earlier seasons of the same circuit. Selected on protocol A only. Full table: out/tyreformer/prerace/PRERACE.md.

| protocol | rows / weekends | Orb v1 MAE | learned MAE | Orb v1 r | learned r |
|---|---|---|---|---|---|
| A: leave one weekend out, 2023-2026 | 148 / 64 | 0.0520 | 0.0299 | 0.27 | 0.40 |
| B: trained 2023-2025, tested 2026 | 29 / 11 | 0.0227 | 0.0285 | 0.78 | 0.58 |

Reading: across four seasons it beats Orb v1 (most of the gain is shrinkage toward typical degradation, and it also beats that constant);
on 2026 alone it does not beat Orb v1, whose in-season factor is strong there. It is a second opinion for pre-race curves, not a replacement.

## Limits

- Public data only: no tyre temperatures, pressures or wear are observed; the model learns them through lap times and energy proxies.
- The cliff label (prefix_eval.py rule) is dominated by lap-to-lap noise; the learned probability is calibrated but its skill over a constant
  base rate is small. It is shown as a risk, not a prediction of an event.
- 2026 is a distribution shift (new regulations); bands calibrated on 2023-2025 can under-cover there, and the numbers above say by how much.
- The estimator baseline's 2026 priors are leave-one-out within the season, so they include later 2026 weekends: a small edge to the estimator.
- Not the estimator of record in the shipping dashboard unless the lead integrates it; replay forecasts are exported for that.

## Use

```
python -m tyreformer.data --out out/tyreformer/cache/samples_dev_v3.npz      # 58k origins in seconds
python -m tyreformer.train --experiment cv|temporal|rolling|production ...    # see out/tyreformer/logs/train_*.json for the exact flags
python -m tyreformer.gbm --experiment cv|temporal|rolling|production
python -m tyreformer.blend && python -m tyreformer.evaluate && python -m tyreformer.figures
python -m tyreformer.sealed freeze | verify | score                             # one-shot, aggregate only
python -m tyreformer.export                                                     # out/tyreformer/live/2026_<event>.parquet for the dashboard
```

Live API: `tyreformer.infer.TyreFormerLive(model).forecast(season, event, laps_so_far, driver, n_laps, priors)`; refuses any lap completed after the forecast moment.

Freeze: tyreformer/FREEZE.json, 16 files hashed at 2026-09-13T06:17:12+05:30.
