# Orb v1 scorecards (2026-09-12T23:44:41, git 230870bc9f27f281c515ac7c6108da2e55574688)

Two scorecards, never merged. Every reported performance estimate below carries its eligible n and a 90% percentile bootstrap band from whole-weekend resampling (2000 draws; never row resampling). Counts and fixed gate settings are metadata, not estimates. Missing bands are explicit.

## Ghost Strategy scorecard

Development pool: 64 weekends; 148 compound-weekends; sealed weekends excluded from every pool.

### Development aggregate

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0520 [90% CI 0.0425, 0.0626]; n=148 compound-weekends, 64 weekends |
| Naive MAE (s/lap per lap) | 0.1661 [90% CI 0.1492, 0.1837]; n=148 compound-weekends, 64 weekends |
| 90% predictive-band coverage | 86.5% [90% CI 82.1%, 90.8%]; n=148 compound-weekends, 64 weekends |
| Share issued | 56.8% [90% CI 49.3%, 63.6%]; n=148 compound-weekends, 64 weekends |
| Issued MAE | 0.0663 [90% CI 0.0501, 0.0830]; n=84 compound-weekends, 47 weekends |
| Fallback MAE | 0.0332 [90% CI 0.0274, 0.0400]; n=64 compound-weekends, 47 weekends |
| Calibration correlation | 0.2708 [90% CI 0.1036, 0.4178]; n=148 compound-weekends, 64 weekends |
| Share beating naive | 84.5% [90% CI 79.3%, 89.3%]; n=148 compound-weekends, 64 weekends |

### Hidden-stop response

| metric | Orb v1 | naive |
|---|---|---|
| next1 MAE (s) | 1.118 [90% CI 0.982, 1.281]; n=984 stops, 56 weekends | 1.442 [90% CI 1.348, 1.535]; n=984 stops, 56 weekends |
| next1 coverage90 | 80.6% [90% CI 76.1%, 85.1%]; n=984 stops, 56 weekends | |
| cum3 MAE (s) | 3.053 [90% CI 2.706, 3.459]; n=835 stops, 55 weekends | 3.960 [90% CI 3.710, 4.201]; n=835 stops, 55 weekends |
| cum3 coverage90 | 78.7% [90% CI 73.7%, 84.0%]; n=835 stops, 55 weekends | |
| cum5 MAE (s) | 4.827 [90% CI 4.240, 5.432]; n=665 stops, 49 weekends | 6.457 [90% CI 5.993, 6.889]; n=665 stops, 49 weekends |
| cum5 coverage90 | 78.2% [90% CI 72.2%, 84.3%]; n=665 stops, 49 weekends | |

### Strategy regret (held-out strategy replay under a post-race reference model)

| plan | mean regret (s) | median regret (s) | within 5 s |
|---|---|---|---|
| orb | 33.7 [90% CI 24.0, 44.4]; n=40 rows, 40 weekends | 20.7 [90% CI 10.0, 29.6]; n=40 rows, 40 weekends | 25.0% [90% CI 15.0%, 37.5%]; n=40 weekends, 40 weekends |
| naive | 40.4 [90% CI 30.4, 51.1]; n=43 rows, 43 weekends | 22.9 [90% CI 16.4, 33.0]; n=43 rows, 43 weekends | 11.6% [90% CI 4.7%, 20.9%]; n=43 weekends, 43 weekends |
| observed | 36.0 [90% CI 29.7, 42.7]; n=58 rows, 58 weekends | 27.6 [90% CI 20.3, 40.2]; n=58 rows, 58 weekends | 13.8% [90% CI 6.9%, 22.4%]; n=58 weekends, 58 weekends |
| default | 33.8 [90% CI 27.5, 40.1]; n=64 rows, 64 weekends | 22.6 [90% CI 15.3, 36.8]; n=64 rows, 64 weekends | 17.2% [90% CI 9.4%, 25.0%]; n=64 weekends, 64 weekends |
### circuit_class: permanent

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0537 [90% CI 0.0424, 0.0667]; n=105 compound-weekends, 45 weekends |
| Naive MAE (s/lap per lap) | 0.1611 [90% CI 0.1437, 0.1788]; n=105 compound-weekends, 45 weekends |
| 90% predictive-band coverage | 86.7% [90% CI 81.7%, 91.3%]; n=105 compound-weekends, 45 weekends |
| Share issued | 65.7% [90% CI 57.8%, 73.1%]; n=105 compound-weekends, 45 weekends |
| Issued MAE | 0.0640 [90% CI 0.0475, 0.0823]; n=69 compound-weekends, 37 weekends |
| Fallback MAE | 0.0338 [90% CI 0.0246, 0.0446]; n=36 compound-weekends, 29 weekends |
| Calibration correlation | 0.3427 [90% CI 0.1689, 0.5028]; n=105 compound-weekends, 45 weekends |
| Share beating naive | 81.9% [90% CI 74.8%, 88.2%]; n=105 compound-weekends, 45 weekends |

### circuit_class: street

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0479 [90% CI 0.0320, 0.0664]; n=43 compound-weekends, 19 weekends |
| Naive MAE (s/lap per lap) | 0.1784 [90% CI 0.1416, 0.2151]; n=43 compound-weekends, 19 weekends |
| 90% predictive-band coverage | 86.0% [90% CI 75.6%, 95.0%]; n=43 compound-weekends, 19 weekends |
| Share issued | 34.9% [90% CI 21.6%, 46.7%]; n=43 compound-weekends, 19 weekends |
| Issued MAE | 0.0767 [90% CI 0.0353, 0.1129]; n=15 compound-weekends, 10 weekends |
| Fallback MAE | 0.0325 [90% CI 0.0256, 0.0399]; n=28 compound-weekends, 18 weekends |
| Calibration correlation | -0.1482 [90% CI -0.3020, 0.0039]; n=43 compound-weekends, 19 weekends |
| Share beating naive | 90.7% [90% CI 83.3%, 97.6%]; n=43 compound-weekends, 19 weekends |

### weather_regime: cool

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0604 [90% CI 0.0412, 0.0821]; n=17 compound-weekends, 7 weekends |
| Naive MAE (s/lap per lap) | 0.1466 [90% CI 0.0942, 0.1918]; n=17 compound-weekends, 7 weekends |
| 90% predictive-band coverage | 82.4% [90% CI 58.8%, 100.0%]; n=17 compound-weekends, 7 weekends |
| Share issued | 47.1% [90% CI 21.4%, 66.7%]; n=17 compound-weekends, 7 weekends |
| Issued MAE | 0.0609 [90% CI 0.0484, 0.0718]; n=8 compound-weekends, 4 weekends |
| Fallback MAE | 0.0601 [90% CI 0.0337, 0.0972]; n=9 compound-weekends, 6 weekends |
| Calibration correlation | 0.2019 [90% CI -0.1239, 0.5805]; n=17 compound-weekends, 7 weekends |
| Share beating naive | 70.6% [90% CI 43.8%, 94.1%]; n=17 compound-weekends, 7 weekends |

### weather_regime: hot

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0563 [90% CI 0.0370, 0.0778]; n=50 compound-weekends, 22 weekends |
| Naive MAE (s/lap per lap) | 0.1547 [90% CI 0.1283, 0.1835]; n=50 compound-weekends, 22 weekends |
| 90% predictive-band coverage | 86.0% [90% CI 79.2%, 92.3%]; n=50 compound-weekends, 22 weekends |
| Share issued | 68.0% [90% CI 56.2%, 79.2%]; n=50 compound-weekends, 22 weekends |
| Issued MAE | 0.0690 [90% CI 0.0400, 0.0998]; n=34 compound-weekends, 18 weekends |
| Fallback MAE | 0.0291 [90% CI 0.0184, 0.0395]; n=16 compound-weekends, 13 weekends |
| Calibration correlation | 0.3349 [90% CI -0.0704, 0.5981]; n=50 compound-weekends, 22 weekends |
| Share beating naive | 82.0% [90% CI 72.5%, 90.6%]; n=50 compound-weekends, 22 weekends |

### weather_regime: mild

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0473 [90% CI 0.0334, 0.0631]; n=51 compound-weekends, 23 weekends |
| Naive MAE (s/lap per lap) | 0.1842 [90% CI 0.1549, 0.2150]; n=51 compound-weekends, 23 weekends |
| 90% predictive-band coverage | 90.2% [90% CI 83.7%, 96.2%]; n=51 compound-weekends, 23 weekends |
| Share issued | 51.0% [90% CI 38.6%, 62.7%]; n=51 compound-weekends, 23 weekends |
| Issued MAE | 0.0646 [90% CI 0.0407, 0.0880]; n=26 compound-weekends, 16 weekends |
| Fallback MAE | 0.0294 [90% CI 0.0233, 0.0370]; n=25 compound-weekends, 18 weekends |
| Calibration correlation | 0.2684 [90% CI -0.0179, 0.5983]; n=51 compound-weekends, 23 weekends |
| Share beating naive | 88.2% [90% CI 81.6%, 94.4%]; n=51 compound-weekends, 23 weekends |

### weather_regime: wet_affected

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0480 [90% CI 0.0288, 0.0682]; n=30 compound-weekends, 12 weekends |
| Naive MAE (s/lap per lap) | 0.1654 [90% CI 0.1276, 0.2000]; n=30 compound-weekends, 12 weekends |
| 90% predictive-band coverage | 83.3% [90% CI 74.2%, 92.6%]; n=30 compound-weekends, 12 weekends |
| Share issued | 53.3% [90% CI 37.9%, 68.6%]; n=30 compound-weekends, 12 weekends |
| Issued MAE | 0.0660 [90% CI 0.0338, 0.1009]; n=16 compound-weekends, 9 weekends |
| Fallback MAE | 0.0275 [90% CI 0.0200, 0.0346]; n=14 compound-weekends, 10 weekends |
| Calibration correlation | 0.2416 [90% CI -0.0613, 0.5273]; n=30 compound-weekends, 12 weekends |
| Share beating naive | 90.0% [90% CI 80.6%, 97.0%]; n=30 compound-weekends, 12 weekends |

### Season 2023 (leave-one-weekend-out inside season)

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0546 [90% CI 0.0371, 0.0754]; n=40 compound-weekends, 17 weekends |
| Naive MAE (s/lap per lap) | 0.1943 [90% CI 0.1648, 0.2216]; n=40 compound-weekends, 17 weekends |
| 90% predictive-band coverage | 85.0% [90% CI 77.5%, 92.5%]; n=40 compound-weekends, 17 weekends |
| Share issued | 50.0% [90% CI 34.1%, 65.0%]; n=40 compound-weekends, 17 weekends |
| Issued MAE | 0.0821 [90% CI 0.0546, 0.1145]; n=20 compound-weekends, 11 weekends |
| Fallback MAE | 0.0271 [90% CI 0.0212, 0.0330]; n=20 compound-weekends, 13 weekends |
| Calibration correlation | 0.3758 [90% CI -0.0209, 0.6115]; n=40 compound-weekends, 17 weekends |
| Share beating naive | 87.5% [90% CI 79.5%, 95.0%]; n=40 compound-weekends, 17 weekends |

### Season 2024 (leave-one-weekend-out inside season)

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0760 [90% CI 0.0526, 0.0990]; n=39 compound-weekends, 18 weekends |
| Naive MAE (s/lap per lap) | 0.1644 [90% CI 0.1270, 0.2045]; n=39 compound-weekends, 18 weekends |
| 90% predictive-band coverage | 89.7% [90% CI 82.5%, 97.1%]; n=39 compound-weekends, 18 weekends |
| Share issued | 61.5% [90% CI 47.2%, 73.8%]; n=39 compound-weekends, 18 weekends |
| Issued MAE | 0.0884 [90% CI 0.0540, 0.1262]; n=24 compound-weekends, 13 weekends |
| Fallback MAE | 0.0561 [90% CI 0.0390, 0.0745]; n=15 compound-weekends, 13 weekends |
| Calibration correlation | 0.0677 [90% CI -0.2053, 0.3480]; n=39 compound-weekends, 18 weekends |
| Share beating naive | 69.2% [90% CI 55.3%, 82.1%]; n=39 compound-weekends, 18 weekends |

### Season 2025 (leave-one-weekend-out inside season)

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0472 [90% CI 0.0334, 0.0621]; n=40 compound-weekends, 18 weekends |
| Naive MAE (s/lap per lap) | 0.1606 [90% CI 0.1317, 0.1888]; n=40 compound-weekends, 18 weekends |
| 90% predictive-band coverage | 85.0% [90% CI 76.3%, 92.9%]; n=40 compound-weekends, 18 weekends |
| Share issued | 60.0% [90% CI 46.3%, 72.1%]; n=40 compound-weekends, 18 weekends |
| Issued MAE | 0.0602 [90% CI 0.0408, 0.0861]; n=24 compound-weekends, 14 weekends |
| Fallback MAE | 0.0279 [90% CI 0.0206, 0.0369]; n=16 compound-weekends, 12 weekends |
| Calibration correlation | 0.3095 [90% CI -0.0204, 0.6355]; n=40 compound-weekends, 18 weekends |
| Share beating naive | 87.5% [90% CI 80.0%, 94.9%]; n=40 compound-weekends, 18 weekends |

### Season 2026 (leave-one-weekend-out inside season)

| metric | estimate, 90% interval and support |
|---|---|
| Orb v1 MAE (s/lap per lap) | 0.0227 [90% CI 0.0172, 0.0281]; n=29 compound-weekends, 11 weekends |
| Naive MAE (s/lap per lap) | 0.1371 [90% CI 0.1054, 0.1742]; n=29 compound-weekends, 11 weekends |
| 90% predictive-band coverage | 86.2% [90% CI 72.4%, 96.8%]; n=29 compound-weekends, 11 weekends |
| Share issued | 55.2% [90% CI 40.0%, 70.0%]; n=29 compound-weekends, 11 weekends |
| Issued MAE | 0.0226 [90% CI 0.0146, 0.0290]; n=16 compound-weekends, 9 weekends |
| Fallback MAE | 0.0229 [90% CI 0.0138, 0.0327]; n=13 compound-weekends, 9 weekends |
| Calibration correlation | 0.7806 [90% CI 0.3732, 0.8886]; n=29 compound-weekends, 11 weekends |
| Share beating naive | 96.6% [90% CI 90.3%, 100.0%]; n=29 compound-weekends, 11 weekends |

### Lock consistency

11 values compared with out/lock.json; all_match=True. Counts exact; floats within 0.0005. The 2026 performance estimates and intervals are in the season table above.

### sealed holdout, aggregate only

sealed holdout, aggregate only: 6 weekends / 9 compound-weekends.

Orb v1 MAE 0.0372 [90% CI 0.0252, 0.0457]; n=9 rows, 5 weekends; naive MAE 0.1713 [90% CI 0.0952, 0.2252]; n=9 rows, 5 weekends s/lap.
Coverage 100.0% [90% CI 100.0%, 100.0%]; n=9 rows, 5 weekends. Frozen post-freeze aggregate copied verbatim; no per-race data read.

### Rolling origin, 2026

Only earlier completed rounds enter each forecast. A single-round point estimate has no weekend bootstrap interval: n=1 weekend is insufficient.

| round | event | earlier pool | issued / compounds | no forecast | MAE Orb v1 | MAE naive | coverage90 |
|---|---|---|---|---|---|---|---|
| 1 | Australia | 0 | 1 / 3 | 2 | 0.0406; 90% CI unavailable (insufficient weekends or undefined statistic); n=1 compound-weekends, 1 weekends | 0.1008; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 100.0%; 90% CI unavailable (insufficient weekends or undefined statistic); n=1 compound-weekends, 1 weekends |
| 2 | Japan | 1 | 1 / 2 | 0 | 0.0080; 90% CI unavailable (insufficient weekends or undefined statistic); n=2 compound-weekends, 1 weekends | 0.1507; 90% CI unavailable (insufficient weekends or undefined statistic); n=2 compound-weekends, 1 weekends | 100.0%; 90% CI unavailable (insufficient weekends or undefined statistic); n=1 compound-weekends, 1 weekends |
| 3 | Miami | 2 | 2 / 3 | 0 | 0.0082; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 0.1881; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 66.7%; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends |
| 4 | Canada | 3 | 0 / 2 | 0 | 0.0302; 90% CI unavailable (insufficient weekends or undefined statistic); n=2 compound-weekends, 1 weekends | 0.0677; 90% CI unavailable (insufficient weekends or undefined statistic); n=2 compound-weekends, 1 weekends | 0.0%; 90% CI unavailable (insufficient weekends or undefined statistic); n=2 compound-weekends, 1 weekends |
| 5 | Monaco | 4 | — | — | no scored race (live weekend or race unusable) | | |
| 6 | Barcelona | 4 | 2 / 3 | 0 | 0.0877; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 0.1492; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 33.3%; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends |
| 7 | Austria | 5 | 3 / 3 | 0 | 0.0461; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 0.1482; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 100.0%; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends |
| 8 | Britain | 6 | 0 / 1 | 0 | 0.0161; 90% CI unavailable (insufficient weekends or undefined statistic); n=1 compound-weekends, 1 weekends | 0.0246; 90% CI unavailable (insufficient weekends or undefined statistic); n=1 compound-weekends, 1 weekends | 100.0%; 90% CI unavailable (insufficient weekends or undefined statistic); n=1 compound-weekends, 1 weekends |
| 9 | Belgium | 7 | 2 / 3 | 0 | 0.0351; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 0.0934; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 100.0%; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends |
| 10 | Hungary | 8 | 3 / 3 | 0 | 0.0401; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 0.2975; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 100.0%; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends |
| 11 | Zandvoort | 9 | 1 / 3 | 0 | 0.0188; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 0.0774; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 100.0%; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends |
| 12 | Monza | 10 | 1 / 3 | 0 | 0.0033; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 0.1173; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends | 100.0%; 90% CI unavailable (insufficient weekends or undefined statistic); n=3 compound-weekends, 1 weekends |
| 13 | Madrid | 11 | — | — | no scored race (live weekend or race unusable) | | |

All scored rounds: MAE Orb v1 0.0315 [90% CI 0.0190, 0.0448]; n=27 compound-weekends, 11 weekends; naive 0.1371 [90% CI 0.1054, 0.1742]; n=29 compound-weekends, 11 weekends; coverage90 80.8% [90% CI 63.6%, 96.3%]; n=26 compound-weekends, 11 weekends.

At least 3 earlier rounds in pool: MAE Orb v1 0.0367 [90% CI 0.0217, 0.0523]; n=21 compound-weekends, 8 weekends; naive 0.1338 [90% CI 0.0941, 0.1815]; n=21 compound-weekends, 8 weekends; coverage90 81.0% [90% CI 57.9%, 100.0%]; n=21 compound-weekends, 8 weekends.

## Live Predictor scorecard

Source: out/live/prefix_eval.json; frozen prefix evaluation; source point-estimate agreement: True.
Only data through lap k enters the predictor; realised future outcomes are scoring targets only. Alert lead is the median over detected true stints, recomputed from source per-stint alerts. Climatology Brier uses the pooled event rate on each whole-weekend resample.

| metric | estimate, 90% interval and support |
|---|---|
| next1_mae | 0.380 [90% CI 0.325, 0.427]; n=1890 scored windows, 3 weekends |
| next1_mae_prior_only | 0.426 [90% CI 0.353, 0.494]; n=1890 scored windows, 3 weekends |
| cum3_mae | 1.045 [90% CI 0.824, 1.233]; n=1315 scored windows, 3 weekends |
| cum3_mae_prior_only | 1.122 [90% CI 0.866, 1.362]; n=1315 scored windows, 3 weekends |
| cum5_mae | 1.845 [90% CI 1.384, 2.243]; n=943 scored windows, 3 weekends |
| cum5_mae_prior_only | 1.796 [90% CI 1.322, 2.241]; n=943 scored windows, 3 weekends |
| coverage90_next1 | 0.890 [90% CI 0.869, 0.915]; n=1890 scored windows, 3 weekends |
| coverage90_next1_prior_only | 0.913 [90% CI 0.863, 0.962]; n=1890 scored windows, 3 weekends |
| coverage90_next3 | 0.860 [90% CI 0.819, 0.905]; n=1683 scored windows, 3 weekends |
| cliff3_brier | 0.164 [90% CI 0.108, 0.214]; n=2231 scored windows, 3 weekends |
| cliff5_brier | 0.195 [90% CI 0.132, 0.250]; n=2337 scored windows, 3 weekends |
| cliff5_brier_climatology | 0.126 [90% CI 0.093, 0.152]; n=2337 scored windows, 3 weekends |
| recommendation_change_rate | 0.093 [90% CI 0.075, 0.107]; n=3497 lap pairs, 3 weekends |
| aw_false_alert_episodes_per_stint | 0.076 [90% CI 0.056, 0.087]; n=79 stints, 3 weekends |
| aw_detection_rate | 0.788 [90% CI 0.333, 0.900]; n=33 stints, 3 weekends |
| Median alert lead (laps) | 8.500 [90% CI 7.000, 9.000]; n=26 detected true stints, 3 weekends |
| cliff3_brier_climatology | 0.091 [90% CI 0.066, 0.112]; n=2231 scored windows, 3 weekends |

Driver-feedback ablation: not run; Driver-feedback ablation NOT RUN: no driver-feedback event has been recorded (the UI log is empty and every replay run consumed 0 events). It is a defined experiment, not a pre-written result; it runs from python -m evaluation.scorecards as soon as events exist.

Risk-coverage threshold sweep: see risk_coverage.json and risk_coverage.csv. Each table row includes eligible n and whole-weekend 90% bands for coverage and every MAE. The production gate is frozen; the development sweep is diagnostic and does not select a new gate.
