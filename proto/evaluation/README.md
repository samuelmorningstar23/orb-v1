# Blind evaluation: sealed holdout, hidden-stop-response, regret, scorecards

Roadmap v5 section 9 and task 0.1. Everything here scores the **frozen pre-race forecast** against post-race material and
reports weekend-grouped numbers; builders never see per-race sealed results. Run from `proto/` with the project venv:

```
python -m evaluation.holdout.evaluator          # sealed holdout -> out/validation/holdout_aggregate.json (aggregate only)
python -m evaluation.hidden_stop --seasons 2026 # hidden-stop-response on the development pool -> hidden_stop_<season>.json
python -m evaluation.regret --seasons 2026      # strategy regret on the development pool -> regret_<season>.json
python -m evaluation.risk_coverage              # abstention gate sweep -> risk_coverage.{csv,json,png}
python -m evaluation.scorecards                 # Ghost Strategy + Live Predictor scorecards, rolling-origin 2026 -> ghost_scorecard.json, live_scorecard.json, SCORECARDS.md
pytest proto/tests/evaluation -q                # 59 tests: reveal gate (every flag combination), dry-run flag, CLI end to end, tamper detection, leakage spy, synthetic truth recovery, oracle regret, grouped bootstrap
```

## Files

| file | computes |
|---|---|
| `forecast.py` | `SeasonForecaster`: pipeline.py's leave-one-weekend-out pre-race forecast on any season directory (`feat/`, `feat2025/`, ...) with an **explicit factor pool** and a `PoolSpy` that records every read of a pool weekend's race outcome as `(target race id, source race id, what)`. Sealed weekends are refused as pool members (`PermissionError`). Reproduces `out/lock.json` for 2026: predictions, factors and floors to 1e-4, band widening to Monte Carlo noise (tests). |
| `hidden_stop.py` | hidden-stop-response: for every real tyre change, predict the next 1, 3, 5 representative laps on the new tyre from laps before the stop plus the intervention; naive fresh-tyre baseline; by compound, circuit class, set status, stop regime, driver support. |
| `regret.py` | strategy regret: Orb v1 / naive / observed / default plans against the hindsight oracle under the race-derived reference. Output label: **"held-out strategy replay under a post-race reference model"**. |
| `risk_coverage.py` | abstention gate sweep (minimum laps 10 to 60, minimum slope 0 to 0.05): coverage vs error on issued cases and the fallback error; table and dark-theme PNG. |
| `scorecards.py` | Ghost Strategy scorecard (development pool, `by_season`, `lock_consistency_2026` against `out/lock.json`, sealed block only when `quotable`), Live Predictor scorecard (from Workstream 8's `out/live/prefix_eval.json`), rolling-origin 2026 series, driver-feedback ablation (runs only when feedback events exist in `app_v2/state/feedback_events.jsonl` or `out/live/*/driver_feedback.json`; otherwise says so plainly). |
| `common.py` | `weekend_bootstrap` (resample weekends, never rows), `paired_probability`, JSON output via `shared.lockio`. |
| `holdout/evaluator.py` | the sealed-holdout evaluator (below). `holdout/sealed_holdout_manifest.json` and `.sha256` are lead-only and frozen. |

## Data splits and pools

* **Development pool**: 2026 (all completed weekends in `feat/`) and the non-sealed completed weekends of 2023, 2024, 2025.
  Each weekend is forecast leave-one-weekend-out: transfer factors, fallback floor and band widening come from the other
  completed weekends **of the same season**, minus every sealed weekend. `loo_forecasts()` reproduces pipeline.py's
  widening exactly (the pool rows' standardised residuals are each obtained inside a pool that still contains the target's
  own race, a second-order effect on the band width only); the sealed evaluator and the rolling-origin series use the
  strict mode (`target_obs_in_widening=False`).
* **Sealed holdout**: the six weekends of the manifest (2023 Canada, 2024 Bahrain, 2024 Monza, 2024 Saudi Arabia,
  2024 Zandvoort, 2025 Qatar). Forecast from their own practice files with factors from the non-sealed weekends of their
  season. A sealed race never enters any pool, for any target, in any season: the spy asserts it and a test proves it.
* **Rolling origin (2026)**: round k forecast with factors from the completed rounds before k only (calendar order from
  `live/clock.py`); the first rounds carry factor 1.0 and no fallback (empty pool).
* Weekend-level abstention: pipeline.py issues no table for a weekend with fewer than 40 clean practice laps. One sealed
  weekend (a sprint weekend with FP1 only) falls under this rule and cannot be scored on any test; the aggregate says so.

## Exact formulas

Notation: `y = lap_s - 0.03 x fuel_kg` is the fuel-corrected lap time (model_v2: practice fuel `40 - 1.1 x (age - 1)` kg
minus the session's track-evolution term; race fuel `70 x (1 - (lap - 1) / n_laps)` kg). `offset[c]` is the compound pace
offset from qualifying (practice fallback, nominal 0.6 s per step) with SOFT = 0 (strategy2.offsets_from_sessions).

**Pre-race forecast** (per compound c of the target weekend, pipeline.py rules):

```
clean[c], se[c]   stint fixed effects + per-compound slope on tyre age, cleaned practice laps (model_v2.fit)
issued            n_prac >= 30 and clean >= 0.02 s/lap per lap
k                 median over pool weekends (same compound, issued) of obs/clean; applied only if >= 3 exist and a
                  majority lie within +-50 % of the median (pipeline.agree_factor), else k = 1
prediction        issued: clean x k ; withheld: floor = median race degradation of the pool's withheld cases (>= 2)
band (raw)        issued: pipeline.band (slope noise x factor resampling, 5th to 95th percentile)
                  withheld: q10..q90 of the pool's withheld race degradations (>= 3)
widening w        90th percentile over pool rows of |obs - pred| / half-width, each pool row forecast leave-one-out
                  inside the pool (>= 5 rows, else 1); band = prediction -/+ w x (prediction - lo, hi - prediction)
reference         obs[c], obs_se[c]: model_v2.fit on the race, all drivers ("race-derived pace-loss reference")
error / coverage  |prediction - obs| ; 1[lo <= obs <= hi]
```

**Hidden-stop-response** (`hidden_stop.py`), for a stop with in-lap L from compound c_old to c_new:

```
baseline laps     the last K = 5 (>= 3) clean laps of the old stint before L
                  (green, accurate, no pit in/out, not deleted, traffic <= 0.30, within 105 % of the best of them)
representative    clean laps in (L+1, L+1+8] inside the new stint, same rule; the h-th of them is horizon h
B_hat             mean_i ( y_i - offset[c_old] - s_pre[c_old] x age_i )        (driver level from the pre-race model)
y_hat(a)          B_hat + offset[c_new] + s_pre[c_new] x a                      (Orb v1)
y_naive(a)        mean_i(y_i) + offset[c_new] - offset[c_old]                   (fresh-tyre rule: no degradation, no age reset)
interval          y_hat +- 1.6449 x sqrt( sigma_y^2 + V_level + (a x sigma_s,new)^2 )
V_level           sigma_y^2 / K + (a_bar_pre x sigma_s,old)^2 + n_off x 0.15^2
                  sigma_y = 0.40 s (live/estimator.py), sigma_s,c = (hi - lo) / (2 x 1.6449) of c's pre-race band,
                  n_off = number of non-SOFT compounds among {c_old, c_new} when they differ (offset sd 0.15 s, stated)
h-lap cumulative  sum_{j<=h} y_hat_j +- 1.6449 x sqrt( h sigma_y^2 + h^2 V_level + (sum_j a_j)^2 sigma_s,new^2 )
metrics           next-lap MAE |y_hat_1 - y_1| ; cumulative MAE |sum_{j<=h}(y_hat_j - y_j)| for h = 3, 5 ;
                  90 % coverage of the next lap and of the 3- and 5-lap sums; naive MAE alongside
cells             compound_new, circuit_class (street / permanent), set_status (FreshTyre new / used),
                  stop_regime (green: in- and out-lap green or yellow; sc_vsc otherwise; red-flag stops excluded),
                  driver_support (driver seen in a pool weekend's race)
```

**Strategy regret** (`regret.py`), per weekend, race distance n:

```
cost(plan)        sum over stints ( offset[c] x L + s[c] x L (L + 1) / 2 ) + stops x 21 s        (strategy2.stint_time, PIT_LOSS)
oracle            exhaustive one- and two-stop search, every stint >= 6 laps, two distinct compounds, under the
                  reference slopes obs[c] over every compound with a reference and an offset
Orb v1 plan       strategy2.best_plans with the pre-race slopes over the compounds it had a forecast for
naive plan        strategy2.best_plans with the raw practice slopes (lap time vs age, no cleaning)
observed plan     most common slick compound sequence among classified finishers; median stint lengths (last stint absorbs rounding)
default plan      MEDIUM then HARD, one stop at n // 2 (else the two hardest reference compounds, softer first)
regret(plan)      cost(plan under obs) - cost(oracle)        [s over the race]
unscorable        a plan using a compound without a reference (reported, never dropped); Orb v1's regret therefore
                  includes the cost of a compound it could not forecast
report            median, mean, p90, mean of the worst decile, share within 2 / 5 / 10 s, P(Orb v1 beats naive) and
                  P(Orb v1 beats observed) as the share of weekends and as the weekend-bootstrap probability that the
                  mean regret is lower
```

**Weekend-grouped bootstrap** (`common.weekend_bootstrap`): draw weekends with replacement (a weekend drawn twice
contributes its rows twice), recompute the statistic on the concatenated rows, 2000 draws, seed 2026, 5th to 95th
percentile. No interval with fewer than two weekends.

**Risk-coverage** (`risk_coverage.py`): for each (min_laps, min_slope) the gate is re-derived, every development weekend is
forecast leave-one-out (point forecasts) and coverage = share issued, MAE issued, MAE fallback, MAE all are tabulated.

## The sealed-holdout evaluator

1. Verifies `sealed_holdout_manifest.json` against `sealed_holdout_manifest.sha256` (and that race_ids, metadata and
   holdout_count agree, prohibited_for_tuning is true). A mismatch prints a stop-the-line message and exits 2; nothing is
   evaluated. Writing `release/STOP_THE_LINE.json` is Workstream 9's.
2. Forecasts every sealed weekend in strict mode, scores forecast error and coverage, runs the hidden-stop test and the
   regret replay, and pools the results over the sealed weekends with weekend bootstraps.
3. Writes `out/validation/holdout_aggregate.json` **always** (aggregate only: cells with fewer than 3 weekends are
   suppressed, regret statistics resting on fewer than 3 scorable weekends are suppressed, min / max are dropped, no
   per-weekend value appears). `holdout_per_race.json` is written **only** when `evaluation/holdout/freeze.json` exists with
   `model_frozen`, `feature_list_frozen`, `gate_threshold_frozen`, `provider_frozen` all true and a `git_commit`;
   otherwise it prints `per-race results sealed` and exits 0.
4. `post_holdout_tuning` is true in every output produced at a git commit that differs from the freeze commit.
5. **Dry run before the freeze.** Every aggregate file carries two top-level flags, `dry_run_before_freeze` and `quotable`.
   Without a valid freeze (`freeze.json` missing, any of the four flags not `true`, or no `git_commit`) the evaluator still
   writes the aggregate but flags it `"dry_run_before_freeze": true, "quotable": false`, prints the warning to stderr and
   stores it in the file (`warning`, `quotable_rule`, `freeze_status`). **No number from a dry run is quoted anywhere**: lead
   decision of 12 Sep 2026 after the 16:55 aggregate was produced before the freeze (per-race results were withheld and the
   model rules are unchanged since the seal, but that run and every pre-freeze re-run are not quotable). `scorecards.py`
   copies the sealed block only when `quotable` is true; otherwise `ghost_scorecard.json` and `SCORECARDS.md` carry the
   dry-run statement and withhold the numbers. Under a valid freeze the flags are `"dry_run_before_freeze": false,
   "quotable": true` and `holdout_per_race.json` is written.

freeze.json format (lead writes it, once, at checkpoint C4; Workstream 3 never creates it):

```json
{"model_frozen": true, "feature_list_frozen": true, "gate_threshold_frozen": true, "provider_frozen": true, "git_commit": "<sha>", "frozen_at": "<ISO time>"}
```

### After the freeze: the exact command sequence (lead, checkpoint C4)

1. Write `evaluation/holdout/freeze.json` (format above) with `git_commit` = the commit at which the model, feature list,
   gate threshold and provider are frozen, and commit it. Then, from `proto/` **at that same commit**:

```
../.venv/bin/python -m evaluation.holdout.evaluator      # 1. sealed holdout under the freeze -> out/validation/holdout_aggregate.json
                                                         #    ("quotable": true, "dry_run_before_freeze": false) and holdout_per_race.json
../.venv/bin/python -m evaluation.scorecards             # 2. ghost_scorecard.json / live_scorecard.json / SCORECARDS.md copy the quotable
                                                         #    sealed aggregate (until then they carry the dry-run statement, no numbers)
../.venv/bin/python -m pytest tests/evaluation -q        # 3. freeze gate, dry-run flag, tamper detection, leakage and bootstrap tests
```

2. Check in `holdout_aggregate.json`: `git_sha` matches `freeze.git_commit` (otherwise `post_holdout_tuning` is true and the run
   is reported as post-freeze tuning), `quotable: true`, `reveal.per_race_written: true`, `leakage_check.sealed_never_in_pool: true`.
3. Quote the sealed result only from that run and only as **"sealed holdout, aggregate"**. The dry runs (16:55 and the
   flagged re-run of 12 Sep evening) are superseded and never quoted.

## Wording rules (roadmap 9.2, enforced in the output labels)

* Race estimates are **race-derived pace-loss references** (`reference`, `reference_slopes`, `obs`), never "truth".
* The regret table is a **held-out strategy replay under a post-race reference model**; it is never "observed race time
  saved" (the label is a constant, `regret.LABEL`, and a test asserts it).
* Counterfactual gains are **model-implied**; only actual-weather audits count as evidence; weather scenarios are never
  scored as accuracy.
* **Untouched** is reserved for the sealed holdout and the prospective race. The development pool is "leave-one-weekend-out".
* The live estimator's cliff probability is a model-implied rate proxy (Workstream 8's label is carried through, not rewritten).
* Two scorecards, never merged: `ghost_scorecard.json` (Ghost Strategy) and `live_scorecard.json` (Live Predictor).

## Outputs (`out/validation/`)

`holdout_aggregate.json`, `hidden_stop_<season>.json`, `regret_<season>.json`, `risk_coverage.{csv,json,png}`,
`ghost_scorecard.json`, `live_scorecard.json`, `SCORECARDS.md`, and `REVIEWS_workstream3.md` (in `evaluation/`: Workstream 3's reviews of
Workstream 2's counterfactual core and Workstream 8's live estimator, roadmap 14.4). Each JSON block carries `generated_at`, `git_sha`,
`data_cutoff` and `units`. No file under `out/validation/` contains a per-race sealed result unless `freeze.json` exists;
`holdout_aggregate.json` always states `dry_run_before_freeze` / `quotable`, and the scorecards quote the sealed block only
when `quotable` is true. `ghost_scorecard.json` also carries `by_season` blocks and a `lock_consistency_2026` block that
compares the 2026 leave-one-weekend-out numbers with `out/lock.json` (MAE naive / Orb v1 with fallback, calibration r,
wins over naive, calibrated band coverage); `SCORECARDS.md` prints the comparison. The other outputs (`hidden_stop_2026`,
`regret_2026`, `risk_coverage`) are computed from the feature files leave-one-weekend-out and do not read the lock.
