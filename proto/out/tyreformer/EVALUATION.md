# Orb TyreFormer evaluation

Generated 2026-09-13T09:51:06. Seconds of corrected lap time. Sealed holdout weekends excluded from every set: 2023_Canada, 2024_Bahrain, 2024_Monza, 2024_SaudiArabia, 2024_Zandvoort, 2025_Qatar.

## Ablation ladder (5-fold weekend-grouped CV, 2023-2025, race and sprint origins)

| model | next-lap MAE | 3-lap | 5-lap | cum3 | cum5 | cov90 next | cliff-5 Brier (clim.) | cliff-5 AUC |
|---|---|---|---|---|---|---|---|---|
| persistence (current pace) | 0.339 | 0.448 | 0.524 | 0.983 | 1.716 | | | |
| gradient-boosted trees only | 0.281 | 0.375 | 0.438 | | | | | |
| transformer | 0.299 | 0.381 | 0.430 | 0.826 | 1.392 | 90.0% | 0.071 (0.073) | 0.672 |
| ensemble | 0.281 | 0.370 | 0.421 | 0.786 | 1.339 | 90.0% | 0.071 (0.073) | 0.672 |

## Head to head with the Orb v1 live estimator (identical race origins and targets)

### Cross-validation, 2023-2025

56 races, 42252 scored origins (origins without a TyreFormer forecast: 0)

| metric | n | Orb v1 estimator | Orb TyreFormer | prior-only | TF − estimator, 90% CI | P(TF better) | races TF better |
|---|---|---|---|---|---|---|---|
| next1 MAE (s) | 27684 | 0.337 [0.315, 0.361] | 0.279 [0.263, 0.298] | 0.517 | -0.065 to -0.051 | 1.00 | 55/56 |
| next3 MAE (s) | 24297 | 0.458 [0.422, 0.501] | 0.366 [0.340, 0.395] | 0.621 | -0.109 to -0.078 | 1.00 | 54/55 |
| next5 MAE (s) | 21259 | 0.548 [0.501, 0.603] | 0.415 [0.384, 0.450] | 0.703 | -0.159 to -0.111 | 1.00 | 53/55 |
| cum3 MAE (s) | 19654 | 0.988 [0.917, 1.071] | 0.776 [0.723, 0.837] | 1.536 | -0.241 to -0.186 | 1.00 | 55/55 |
| cum5 MAE (s) | 14240 | 1.729 [1.605, 1.878] | 1.315 [1.214, 1.434] | 2.655 | -0.478 to -0.358 | 1.00 | 54/55 |
| next1 90% coverage | 27684 | 93.3% | 89.9% | | | | |
| next3 90% coverage | 24297 | 90.3% | 90.1% | | | | |
| cliff3 Brier (1608 events) | 31707 | 0.129 | 0.047 | climatology 0.048 | -0.094 to -0.069 | 1.00 | 55/56 |
| cliff5 Brier (2495 events) | 32974 | 0.145 | 0.069 | climatology 0.070 | -0.088 to -0.064 | 1.00 | 55/56 |

### 2026, trained on 2023-2025 only (season never seen)

12 races, 9596 scored origins (origins without a TyreFormer forecast: 0)

| metric | n | Orb v1 estimator | Orb TyreFormer | prior-only | TF − estimator, 90% CI | P(TF better) | races TF better |
|---|---|---|---|---|---|---|---|
| next1 MAE (s) | 5960 | 0.421 [0.368, 0.476] | 0.353 [0.321, 0.385] | 0.462 | -0.099 to -0.043 | 1.00 | 12/12 |
| next3 MAE (s) | 5215 | 0.522 [0.445, 0.603] | 0.425 [0.380, 0.469] | 0.526 | -0.140 to -0.062 | 1.00 | 12/12 |
| next5 MAE (s) | 4562 | 0.593 [0.511, 0.676] | 0.456 [0.413, 0.498] | 0.565 | -0.189 to -0.091 | 1.00 | 11/11 |
| cum3 MAE (s) | 3819 | 1.160 [0.981, 1.352] | 0.923 [0.824, 1.017] | 1.212 | -0.352 to -0.147 | 1.00 | 12/12 |
| cum5 MAE (s) | 2502 | 1.958 [1.650, 2.304] | 1.512 [1.340, 1.690] | 1.909 | -0.647 to -0.284 | 1.00 | 11/11 |
| next1 90% coverage | 5960 | 87.6% | 85.2% | | | | |
| next3 90% coverage | 5215 | 85.5% | 87.3% | | | | |
| cliff3 Brier (662 events) | 7239 | 0.186 | 0.084 | climatology 0.085 | -0.135 to -0.070 | 1.00 | 12/12 |
| cliff5 Brier (1027 events) | 7625 | 0.206 | 0.118 | climatology 0.120 | -0.119 to -0.059 | 1.00 | 12/12 |

### 2026, deployment protocol (2023-2025 + earlier 2026 races only)

12 races, 9596 scored origins (origins without a TyreFormer forecast: 0)

| metric | n | Orb v1 estimator | Orb TyreFormer | prior-only | TF − estimator, 90% CI | P(TF better) | races TF better |
|---|---|---|---|---|---|---|---|
| next1 MAE (s) | 5960 | 0.421 [0.368, 0.476] | 0.351 [0.320, 0.382] | 0.462 | -0.099 to -0.046 | 1.00 | 12/12 |
| next3 MAE (s) | 5215 | 0.522 [0.445, 0.603] | 0.424 [0.378, 0.470] | 0.526 | -0.139 to -0.064 | 1.00 | 12/12 |
| next5 MAE (s) | 4562 | 0.593 [0.511, 0.676] | 0.453 [0.410, 0.497] | 0.565 | -0.191 to -0.091 | 1.00 | 11/11 |
| cum3 MAE (s) | 3819 | 1.160 [0.981, 1.352] | 0.903 [0.810, 0.997] | 1.212 | -0.362 to -0.167 | 1.00 | 12/12 |
| cum5 MAE (s) | 2502 | 1.958 [1.650, 2.304] | 1.478 [1.317, 1.649] | 1.909 | -0.672 to -0.318 | 1.00 | 11/11 |
| next1 90% coverage | 5960 | 87.6% | 87.8% | | | | |
| next3 90% coverage | 5215 | 85.5% | 89.5% | | | | |
| cliff3 Brier (662 events) | 7239 | 0.186 | 0.082 | climatology 0.085 | -0.138 to -0.072 | 1.00 | 12/12 |
| cliff5 Brier (1027 events) | 7625 | 0.206 | 0.114 | climatology 0.120 | -0.123 to -0.062 | 1.00 | 12/12 |
