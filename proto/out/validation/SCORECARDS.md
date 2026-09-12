# Orb v1 scorecards (2026-09-12T21:53:14, git cdb1a45a2f7b7bc7e94b8dfe342630eed208ec8e)

Two scorecards, never merged (roadmap v5 9.0.1). Intervals: weekend-grouped bootstrap, 90 %.

## Ghost Strategy scorecard

Development pool: 64 weekends, 148 compound-weekends (84 issued, 64 withheld); sealed weekends excluded from every pool.

| metric | Orb v1 | naive / baseline |
|---|---|---|
| pre-race degradation MAE (s/lap per lap) | 0.0520 [0.0425, 0.0626] | 0.1661 [0.1492, 0.1837] |
| 90 % band coverage | 86% [82%, 91%] | nominal 90 % |
| P(Orb v1 beats naive), weekend bootstrap | 1.0 | |
| abstention: share issued | 0.57 | MAE issued 0.0663, fallback 0.0332 |
| hidden-stop next-lap MAE (s), 984 stops | 1.118 [0.982, 1.281] | naive 1.442 [1.348, 1.535] |
| hidden-stop 3-lap cumulative MAE (s) | 3.053 [2.709, 3.434] | naive 3.960 [3.718, 4.198] |
| hidden-stop 5-lap cumulative MAE (s) | 4.827 [4.247, 5.422] | naive 6.457 [6.015, 6.877] |
| hidden-stop 90 % coverage next / +3 / +5 | 81% [76%, 85%] / 79% [73%, 84%] / 78% [72%, 84%] | nominal 90 % |
| strategy regret, orb plan (s; held-out strategy replay under a post-race reference model), n=40 | median 20.7, mean 33.7 [24.0, 44.4] | p90 94.2; within 2/5/10 s 10%/25%/38% |
| strategy regret, naive plan (s; held-out strategy replay under a post-race reference model), n=43 | median 22.9, mean 40.4 [30.4, 51.1] | p90 108.2; within 2/5/10 s 12%/12%/21% |
| strategy regret, observed plan (s; held-out strategy replay under a post-race reference model), n=58 | median 27.6, mean 36.0 [29.7, 42.7] | p90 76.8; within 2/5/10 s 12%/14%/22% |
| strategy regret, default plan (s; held-out strategy replay under a post-race reference model), n=64 | median 22.6, mean 33.8 [27.5, 40.1] | p90 80.9; within 2/5/10 s 8%/17%/25% |
| p orb beats naive | share of weekends 0.58 | bootstrap P 0.8785 (n=39) |
| p orb beats observed | share of weekends 0.61 | bootstrap P 0.9655 (n=36) |

### By cell (development pool)

| cell | weekends | pre-race MAE Orb v1 | naive | cov90 | hidden-stop next-lap MAE | naive | regret Orb v1 median (n) |
|---|---|---|---|---|---|---|---|
| circuit_class=permanent | 45 | 0.0537 | 0.1611 | 87% | 1.057 | 1.483 | 20.7 (30) |
| circuit_class=street | 19 | 0.0479 | 0.1784 | 86% | 1.339 | 1.291 | 16.1 (10) |
| weather_regime=cool | 7 | 0.0604 | 0.1466 | 82% | 0.995 | 1.473 | 22.0 (6) |
| weather_regime=hot | 22 | 0.0563 | 0.1547 | 86% | 1.126 | 1.485 | 15.0 (13) |
| weather_regime=mild | 23 | 0.0473 | 0.1842 | 90% | 1.032 | 1.411 | 26.7 (12) |
| weather_regime=wet_affected | 12 | 0.0480 | 0.1654 | 83% | 1.279 | 1.400 | 9.7 (9) |
| driver_support=seen | — | — | — | — | 1.118 | 1.442 | — |
| driver_support=unseen | — | — | — | — | 0.962 | 1.632 | — |

### By season (development pool, leave-one-weekend-out inside the season)

| season | weekends | compound-weekends (issued / withheld) | MAE Orb v1 | MAE naive | cov90 | wins over naive | calibration r |
|---|---|---|---|---|---|---|---|
| 2023 | 17 | 40 (20 / 20) | 0.0546 [0.0371, 0.0754] | 0.1943 [0.1648, 0.2216] | 85% [78%, 92%] | 35 of 40 | 0.38 |
| 2024 | 18 | 39 (24 / 15) | 0.0760 [0.0526, 0.0990] | 0.1644 [0.1270, 0.2045] | 90% [82%, 97%] | 27 of 39 | 0.07 |
| 2025 | 18 | 40 (24 / 16) | 0.0472 [0.0334, 0.0621] | 0.1606 [0.1317, 0.1888] | 85% [76%, 93%] | 35 of 40 | 0.31 |
| 2026 | 11 | 29 (16 / 13) | 0.0227 [0.0172, 0.0281] | 0.1371 [0.1054, 0.1742] | 86% [72%, 97%] | 28 of 29 | 0.78 |

### Lock consistency: 2026 leave-one-weekend-out vs out/lock.json (generated 2026-09-12T21:33:10)

| metric | scorecard | lock | match |
|---|---|---|---|
| n_weekends | 11 | 11 | yes |
| n_compound_weekends | 29 | 29 | yes |
| n_issued | 16 | 16 | yes |
| n_withheld | 13 | 13 | yes |
| mae_naive_all | 0.1371 | 0.1371 | yes |
| mae_orb_v1_all | 0.0227 | 0.0227 | yes |
| mae_naive_issued | 0.1627 | 0.1627 | yes |
| mae_orb_v1_issued | 0.0226 | 0.0226 | yes |
| calibration_r_all | 0.7806 | 0.7806 | yes |
| wins_orb_over_naive | 28 | 28 | yes |
| band_coverage90_all | 0.8621 | 0.8621 | yes |

All 11 compared values match: True (floats within 0.0005, counts exact). the lock is pipeline.py's own leave-one-weekend-out validation over the completed 2026 weekends; the scorecard recomputes it with evaluation.forecast (pool = the other completed 2026 weekends; no 2026 weekend is sealed); the prospective weekend has no race file and enters neither.

### Sealed holdout (aggregate only)

6 sealed weekends, 9 compound-weekends; per-race results revealed (frozen at commit cdb1a45a2f7b7bc7e94b8dfe342630eed208ec8e); post_holdout_tuning=False.

| metric | Orb v1 | naive |
|---|---|---|
| pre-race degradation MAE | 0.0372 [0.0252, 0.0457] | 0.1713 [0.0952, 0.2252] |
| 90 % band coverage | 100% [100%, 100%] | |
| hidden-stop next-lap / 3-lap / 5-lap MAE (31 stops) | 1.254 / 4.245 / 7.626 | 1.312 / 3.809 / 6.735 |
| regret orb | n=2 suppressed | |
| regret naive | n=2 suppressed | |
| regret observed | n=5: median 19.5 s, mean 17.9 s, within 5 s 20% | |
| regret default | n=5: median 12.9 s, mean 10.4 s, within 5 s 40% | |

### Rolling origin, 2026

| round | event | pool | compounds | issued | no forecast | MAE Orb v1 | MAE naive | cov90 |
|---|---|---|---|---|---|---|---|---|
| 1 | Australia | 0 | 3 | 1 | 2 | 0.0406 | 0.1008 | 1.00 |
| 2 | Japan | 1 | 2 | 1 | 0 | 0.0080 | 0.1507 | 1.00 |
| 3 | Miami | 2 | 3 | 2 | 0 | 0.0082 | 0.1881 | 0.67 |
| 4 | Canada | 3 | 2 | 0 | 0 | 0.0302 | 0.0677 | 0.00 |
| 5 | Monaco | 4 | — | — | — | no scored race (live weekend or race unusable) | | |
| 6 | Barcelona | 4 | 3 | 2 | 0 | 0.0877 | 0.1492 | 0.33 |
| 7 | Austria | 5 | 3 | 3 | 0 | 0.0461 | 0.1482 | 1.00 |
| 8 | Britain | 6 | 1 | 0 | 0 | 0.0161 | 0.0246 | 1.00 |
| 9 | Belgium | 7 | 3 | 2 | 0 | 0.0351 | 0.0934 | 1.00 |
| 10 | Hungary | 8 | 3 | 3 | 0 | 0.0401 | 0.2975 | 1.00 |
| 11 | Zandvoort | 9 | 3 | 1 | 0 | 0.0188 | 0.0774 | 1.00 |
| 12 | Monza | 10 | 3 | 1 | 0 | 0.0033 | 0.1173 | 1.00 |
| 13 | Madrid | 11 | — | — | — | no scored race (live weekend or race unusable) | | |
pooled over 11 rounds: MAE Orb v1 0.0315 vs naive 0.1371; from a pool of >= 3 rounds (8 rounds): 0.0367 vs 0.1338

## Live Predictor scorecard

Source: out/live/prefix_eval.json (linear-Gaussian with fixed regime rules, live_estimator_lg_v0.1, generated 2026-09-12T21:49:21); races Monza, Austria, Barcelona; race-grouped laps-weighted bootstrap.

| metric | estimator | prior-only baseline |
|---|---|---|
| next-lap MAE (s) | 0.380 [0.325, 0.427] | 0.426 [0.353, 0.494] |
| 3-lap cumulative MAE (s) | 1.045 [0.824, 1.233] | 1.122 [0.866, 1.362] |
| 5-lap cumulative MAE (s) | 1.845 [1.384, 2.243] | 1.796 [1.322, 2.241] |
| 90 % coverage next lap | 89% [87%, 92%] | 91% [86%, 96%] |
| cliff-5 Brier (model-implied rate proxy) | 0.195 [0.132, 0.250] | climatology 0.123 [0.090, 0.151] |
| accelerating-wear detection rate / lead (laps) | 79% [33%, 90%] / 8.5 [6.3, 8.9] | |
| false alert episodes per stint | 0.08 [0.06, 0.09] | |
| recommendation change rate | 9% [7%, 11%] | |

**Driver-feedback ablation NOT RUN: no driver-feedback event has been recorded (the UI log is empty and every replay run consumed 0 events). It is a defined experiment, not a pre-written result; it runs from python -m evaluation.scorecards as soon as events exist.**

Sources checked: `app_v2/state/feedback_events.jsonl` (0 events); `out/live/Austria_NOR/driver_feedback.json` (0 events); `out/live/Barcelona_NOR/driver_feedback.json` (0 events); `out/live/Monza_NOR/driver_feedback.json` (0 events).

Design (runs automatically once events exist): for every (event, driver) pair with recorded feedback: replay the race prefix-by-prefix with feedback disabled (telemetry only) and enabled (telemetry + structured feedback through live.feedback.DriverFeedbackAdapter); report next-lap MAE, 3- and 5-lap cumulative MAE, 90 % coverage, accelerating-wear detection rate and lead, false alert episodes per stint and recommendation change rate for both arms.
