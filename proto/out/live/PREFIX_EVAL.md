# Live-prefix evaluation (2026-09-12T21:49:21)

Estimator: linear-Gaussian with fixed regime rules (live_estimator_lg_v0.1). Feedback: disabled (no recorded feedback for these races). Only data through lap k is revealed to the estimator; realised laps are used to score only.

| race | drivers | laps | next-lap MAE | prior-only | 3-lap cum MAE | prior-only | 5-lap cum MAE | prior-only | cov90 next | prior-only | cov90 +3 | cliff-5 Brier (events) | AW detect / lead | false alerts per stint | reco change rate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Monza | 22 | 992 | 0.297 | 0.336 | 0.708 | 0.802 | 1.112 | 1.203 | 92% | 97% | 92% | 0.101 (35/630) | 100% of 2 / 5.5 laps | 0.05 (19 stints) | 6% |
| Austria | 22 | 1338 | 0.360 | 0.374 | 0.972 | 0.947 | 1.735 | 1.476 | 90% | 95% | 88% | 0.175 (157/919) | 20% of 5 / 7.0 laps | 0.09 (44 stints) | 11% |
| Barcelona | 22 | 1233 | 0.466 | 0.555 | 1.390 | 1.575 | 2.550 | 2.645 | 85% | 82% | 78% | 0.294 (154/788) | 88% of 26 / 9.0 laps | 0.06 (16 stints) | 10% |
| pooled | 66 | 3563 | 0.380 | 0.426 | 1.045 | 1.122 | 1.845 | 1.796 | 89% | 91% | 86% | 0.195 (346/2337) | 79% of 33 / 8.5 laps | 0.08 (79 stints) | 9% |

Parameter policy (decisions taken on these three races, 12 Sep 2026; no other race was opened)

* Traffic laps (> 30 % of the lap within 60 m of a car, or unknown) are dropped, as in the lock: keeping them as noisier observations (sigma 0.60 s) made next-lap MAE worse at Monza (0.359 vs 0.299 on the enlarged target set) and changed nothing at Barcelona; the lock definition stays.
* sigma_y = 0.40 s: at 0.35 s (the median within-stint residual) next-lap coverage was 0.91 / 0.88 / 0.82 (Monza / Austria / Barcelona); at 0.40 s it is 0.92 / 0.90 / 0.85 with the same MAE (0.297 / 0.360 / 0.466); at 0.45 s coverage reaches 0.94 / 0.91 / 0.87 but accelerating-wear detection at Monza halves.
* Cliff probabilities are the slope-path component only; counting the compound crossover as a cliff gave Brier 0.455 at Barcelona against a 0.17 climatology.
* Recommendation hysteresis 1.0 s and a full-range first stop for two-stop conversions: the Austria change rate fell from 46 % to 13 %.

Reading the table: the estimator beats the prior-only baseline on next-lap MAE in every race and on cumulative error at Monza and Barcelona; at Austria the prior alone is a better 3- and 5-lap predictor (the slope moves within the stint). Coverage at Barcelona stays below nominal (85 %): the residual noise there is above the fixed 0.40 s. Cliff Brier scores are worse than climatology everywhere: the linear-Gaussian model has no cliff mechanism, the probability is a model-implied rate proxy and must be shown as such. Accelerating-wear alerts detect 79 % of the stints whose realised slope exceeds the prior q90, a median 8.5 laps before the stint ends, with 0.08 false episodes per stint.

Definitions

```
Live-prefix evaluation (roadmap v5 section 9, 'Live Predictor scorecard').

For every completed race in EVENTS, every driver and every lap k: reveal data through k, update the estimator, predict
the corrected lap time of laps k+1, k+3, k+5 (same stint, tyre age k+h, clean laps only are scored), the useful-life
range and the recommendation, then step forward. Reported per race and pooled, against a 'prior only' baseline that
keeps the pre-race slope and only re-estimates the level of the stint (intercept = mean of y - b_prior x age over the
clean laps so far):
    next-lap MAE                       |yhat(k+1) - y(k+1)|
    3- and 5-lap cumulative MAE        |sum_{j<=h} yhat(k+j) - sum_{j<=h} y(k+j)| over windows where all h laps are clean
    90 % interval coverage             share of y(k+1) (and y(k+3)) inside the predictive 90 % band
    cliff Brier score                  (p_h(k) - 1[cliff within h laps])^2, cliff = the CLIFF rule realised on the clean laps
                                       of (k, k+h] (both increments positive, y[j] - y[j-2] > max(2 b_prior span, 2 sqrt2 sigma))
    alert lead time / false alerts     ACCELERATING_WEAR alerts vs the stint's realised slope (post-hoc OLS over all its clean
                                       laps) exceeding the prior q90; lead = laps between the first alert and the stint end
    recommendation stability           share of laps whose top action changed vs the previous lap (changed_since_last_update)
Writes out/live/prefix_eval.json and out/live/PREFIX_EVAL.md. Everything the estimator sees is online-safe; the
post-hoc quantities (realised y, realised stint slope) are used only to score, never fed back.
```
