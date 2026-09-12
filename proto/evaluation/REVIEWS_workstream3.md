# Reviews by Workstream 3 (blind evaluation), roadmap v5 14.4

Reviewer duty: Workstream 2's counterfactual core and Workstream 8's live estimator. Everything below was run or read by Workstream 3
on 12 Sep 2026 between 21:10 and 21:35 IST at HEAD `cdb1a45` (C3 GO), with `out/lock.json` generated 21:03:51 and
`out/lock_v2.json` forecast hash `sha256:3b5497c6abc4ec17…`. Commands run from `proto/` with `../.venv/bin/python`.
No sealed-holdout number appears in this file (the current `holdout_aggregate.json` is a dry run before the freeze).

Verdict scale: ACCEPT / ACCEPT WITH NOTES / REJECT.

## 1. Workstream 2: counterfactual core (tasks 0.3 provider A, 0.4 counterfactual core, 0.9 event sources)

**Verdict: ACCEPT WITH NOTES** (nothing blocking; five notes for C4, N1 and N2 first).

### Acceptance tests, run independently

| command | result | when |
|---|---|---|
| `python -m pytest tests/counterfactual -q -p no:cacheprovider` | 53 passed in 0.73 s | 21:14 IST |

53 is the count in Workstream 2's heartbeat (16:40) and inside the C2 total (335 passed at b0b924c, `checkpoints/C2/test_report.json`);
C3 (`checkpoints/C3`, 21:06) ran the same suite inside its 377 passed / 1 skipped. Tests cover identity (three drivers, both modes),
stop replacement, free red-flag stops, same-compound swap, zero degradation, determinism, time accounting, round trip through the
artefacts, event conservation, contaminated-lap reconstruction, target-driver exclusion, no-future-data flags, schema validation
inside the full lock, frozen-field refusal, support guard, timing, provider A == lock, and the event sources.

### Identity test (actual-plan counterfactual must be zero), replicated outside the engine's own check

Script: scratchpad `cf_reproduce.py` (result `cf_reproduce_result.json`). For NOR and VER, both modes, the actual plan was
re-assembled from `DriverLaps.stints` with the standardised pit event **off** and the full sampled delta matrix (500 samples)
formed with `engine._assemble` + `engine.samples`:

| driver / mode | engine `identity_check_delta_s` | my max abs total delta | my max abs per-lap delta |
|---|---|---|---|
| NOR / fixed_context | 0.0 (pass) | 0.0 | 0.0 |
| NOR / tyre_only | 0.0 (pass) | 0.0 | 0.0 |
| VER / fixed_context | 0.0 (pass) | 0.0 | 0.0 |
| VER / tyre_only | 0.0 (pass) | 0.0 | 0.0 |

Exactly zero, not "below tolerance". With the standardised event **on**, the same compound at the driver's own stop gives, as the
README states, exactly `engine.stop_replacement_delta_s`: NOR (stop under the lap-3 red flag, free) 0.0 s in both modes; VER mean
delta −5.6065 s = stop replacement −5.6065 s (fixed_context) and +3.1077 s = +3.1077 s (tyre_only). All four on-disk summaries
carry `validation.identity_test: pass`, `identity_check_delta_s: 0.0`. The red team's `identity_checks_report.json` (20:59:50,
Monza + Austria, NOR + VER) is 39 / 39 PASS.

### On-disk scenarios reproduce (the NOR lap-24 scenario shown on the Ghost page included)

Each scenario was recompiled from the spec recorded in its own `summary.json` (mode, curve source, set status, sc_factor,
standardised event, target-driver exclusion, n_samples, seed) with the current engine and lock:

| scenario | on disk generated (git, forecast hash) | median / q10 / q90 / P(gain) on disk | recompiled | equal to 1e-6 |
|---|---|---|---|---|
| monza_nor_lap24_to_medium_new_fixed_context | 21:08:03 (cdb1a45, 3b5497c6…) | −5.635 / −15.240 / +3.764 / 0.784 | same | yes |
| monza_nor_lap24_to_medium_new_tyre_only | 16:26:23 (ccae5d9, e1262561…) | −7.795 / −17.580 / +2.164 / 0.838 | same | yes |
| monza_ver_lap28_to_soft_new_fixed_context | 16:26:24 (ccae5d9, e1262561…) | −37.221 / −46.190 / −29.195 / 1.00 | same | yes |
| monza_ver_lap20_to_hard_new_fixed_context | 20:57:58 (b0b924c, 9123e203…) | +7.741 / +3.336 / +12.136 / 0.01 | same | yes |

Also equal: `engine.elapsed_delta_mean_s` and `stop_replacement_delta_s`; sidecar sha256 of `laps.csv`, `lap_deltas.json`,
`ghost_replay.json` match `scenario.assets` (checked on the VER lap-20 directory); `sum(lap_delta) == cumulative_delta[-1] ==
engine.elapsed_delta_mean_s` to the CSV's 6-decimal rounding (differences ≤ 3e-6 s). The non-reproduction the red team found
earlier today on `monza_ver_lap20…` (coordination/NOTES_A.md) is resolved by the 20:57:58 regeneration.

**Comparison with the C2 green artefacts.** `git show b0b924c:proto/out/counterfactual/monza_nor_lap24_to_medium_new_fixed_context/summary.json`
(generated 16:26:23 at ccae5d9, forecast hash e1262561…) carries median −5.635, q10 −15.240, q90 +3.764, P(gain) 0.784, mean
−5.7375 s: identical to today's regeneration; only provenance (generated_at, git_sha, forecast_hash, data_cutoff) changed, as it
should after the FP3 / qualifying lock rebuilds (the Monza rows of the lock are unchanged).

### Leakage and labels

* `validation.future_leakage_test: pass` in all four; `engine.uses_post_race_reference: true` with the race-reference curve
  (Historical Audit), labelled `leave-one-driver-out Sunday reference`, `target_driver_excluded: true`.
* A `curve_source='pre_race_forecast'` compile (NOR lap 24, fixed_context) gives `uses_post_race_reference: false`, leakage pass,
  identity pass, label `frozen pre-race forecast (provider A), model-implied; no race data`, `intended_page: scenario_explorer`,
  forecast hash = the current lock v2 hash. Provider A's `reference_curve_post_race` is fenced (`assert_pre_race`, tested).
* Red team `leakage_audit_report.json` (16:56): static imports, import closure, future-read and deny-list spy, target-driver
  exclusion, one forecast hash: 5 / 5 PASS.

### Notes (for Workstream 2 / the lead at C4)

* **N1 (do first). `scenario_id` omits `curve_source`, so the Historical Audit and Scenario Explorer runs of the same
  intervention overwrite each other.** Evidence: at 21:06:56 the on-disk `monza_nor_lap24_to_medium_new_fixed_context/summary.json`
  carried model hash 152fbd57…, median −14.219 / q10 −60.685 / q90 +40.862 / P(gain) 0.62, which is exactly what a
  `--curve pre_race_forecast` compile of that intervention returns; the 21:08:03 race-reference run restored the audit scenario.
  The Ghost page's audit table and the pending Scenario Explorer run (ghost_strategy.py line 58) would clobber each other.
  Fix: put the curve source in the scenario id or the output directory (e.g. `…_fixed_context_prerace`) and say so in the README.
* **N2. The sealed-race refusal keys on lock-v2 event ids, so a `feat_dir` override bypasses it.**
  `CounterfactualEngine(feat_dir=PROTO/'feat2024').compile(ScenarioSpec('Monza', 'NOR', 20, 'HARD'))` compiles sealed 2024 Monza
  without `PermissionError`: `event_id('Monza')` resolves to `2026_Monza` from lock v2 and the compound offsets come from the 2026
  lock, so the run is also mislabelled. Not reachable from the product (the dashboard uses the default engine on `feat/`) and the
  blind evaluator never uses the engine, but no test covers the refusal. Fix: derive the season from `feat_dir` (or refuse
  `feat_dir` outside `feat/` unless `allow_sealed=True`) and add the test.
* **N3. Provenance chain.** Three of the four summaries carry forecast hashes of superseded lock v2 files (e1262561… twice from
  16:26, 9123e203… from 20:57); the current hash is 3b5497c6…. Numbers are unchanged, the chain is not. Regenerate all four
  scenarios and both lattices at C4 after the freeze so every artefact chains to one lock hash.
* **N4. Lattice files carry no provenance.** `lattice_Monza_*.json` hold `timing` and `csv` only (no generated_at, git_sha,
  forecast_hash, model_hash); `timing.n_errors` is 3 of 3,024 with no error list. Add the scenario-level provenance block and the
  error reasons.
* **N5. `out/counterfactual/_pit_pool_cache.json` is a git-tracked cache** (keys `files`, `stops`, `outlaps`). It is keyed by
  the feature files, which is fine; state in the README that the pool derivation is recomputed when the files change and that the
  cache is safe to delete (it rebuilds in ~1 s).

## 2. Workstream 8: live estimator (tasks 0.8 replay estimator, 0.10 feedback adapter, 0.12 action engine, prefix evaluation, view-model)

**Verdict: ACCEPT WITH NOTES** (nothing blocking; N1 and N2 for C4).

### Acceptance tests, run independently

| command | result | when |
|---|---|---|
| `python -m pytest tests/live -q -p no:cacheprovider` | 31 passed in 1.63 s | 21:14 IST |

31 is the count in Workstream 8's heartbeat (16:30) and inside the C2 and C3 totals. The suite includes the online-safety tests
(`test_feeding_a_future_lap_raises`, `test_lapfeed_never_exposes_a_later_lap`, `test_priors_never_expose_race_outcomes`,
`test_every_state_is_flagged_online_safe`), the widening rules and cap / floor, pit reset, batch == sequential filter on synthetic
and real races, the feedback adapter (`test_feedback_shifts_regime_and_noise_never_seconds`, `test_disabling_feedback_reverts_exactly`,
`test_feedback_from_log_is_matched_by_lap_and_reverts_when_disabled`), the optimiser ordering and hysteresis, replay outputs
validating against the contract, and the view-model keys.

### `out/live/prefix_eval.json` (generated 16:27:48, `live_estimator_lg_v0.1`; sidecar sha256 64643e51… verified; byte-identical to the C2 version at b0b924c)

Three races (Monza, Austria, Barcelona), 66 drivers, 3,563 laps; only data through lap k is revealed; realised laps score only.

| metric | estimator | prior-only baseline | reading |
|---|---|---|---|
| next-lap MAE, pooled | 0.380 s | 0.426 s | beats |
| next-lap MAE per race | Monza 0.297, Austria 0.360, Barcelona 0.466 | 0.336, 0.374, 0.555 | beats in every race |
| 3-lap cumulative MAE | 1.045 s | 1.122 s | beats (Austria 0.972 vs 0.947 does not) |
| 5-lap cumulative MAE | 1.845 s | 1.796 s | does not beat (Austria 1.735 vs 1.476; Monza and Barcelona beat) |
| 90 % coverage next lap | 89 % (Barcelona 85 %) | 91 % | below nominal at Barcelona, stated |
| cliff-3 Brier | 0.164 | climatology 0.091 | worse than climatology |
| cliff-5 Brier | 0.195 | climatology 0.126 | worse in every race (0.101 vs 0.053; 0.175 vs 0.142; 0.294 vs 0.157) |
| accelerating-wear detection / lead | 79 % of 33 true stints / median 8.5 laps | | 0.08 false episodes per stint |
| recommendation change rate | 9 % | | after 1.0 s hysteresis |

The cliff probability is described as a **model-implied rate proxy** in `PREFIX_EVAL.md` ("the linear-Gaussian model has no
cliff mechanism, the probability is a model-implied rate proxy and must be shown as such"), carried through unchanged into
`live_scorecard.json` / `SCORECARDS.md` (row "cliff-5 Brier (model-implied rate proxy)") and shown by the dashboard through
`app_v2/services/live_bridge.py` `CLIFF_LABEL = 'model-implied rate proxy (no cliff mechanism in the linear model)'`.
`PREFIX_EVAL.md` states the 5-lap and Austria results plainly and records the parameter policy (traffic laps dropped as in the
lock, sigma_y 0.40 s, slope-path-only cliffs, hysteresis) with the alternatives it rejected, on the same three races.

Per-run outputs (`out/live/{Monza,Austria,Barcelona}_NOR/summary.json`, 16:27:29): `uses_future_data: false`,
`uses_post_race_reference: false`, `feedback_events_consumed: 0`, sidecars present. Feedback was disabled in the prefix evaluation
because no event was recorded; the driver-feedback ablation therefore cannot run (see SCORECARDS.md).

### Notes (for Workstream 8 / Workstream 1 / the lead at C4)

* **N1. The "rate proxy" label is prose-only.** `prefix_eval.json`, `live_predictor.json` and `summary.json` carry no
  machine-readable label (`grep proxy` finds 0 hits in the JSON); the wording lives in `PREFIX_EVAL.md`, in Workstream 3's scorecard row
  and in the UI bridge constant. Add a `cliff_probability_label` (in `prefix_eval.json` `definitions` and in the LivePredictor record;
  Workstream 1's schema may need the field) so any consumer inherits the wording.
* **N2. Provenance chain.** The three replay runs and `prefix_eval.json` carry forecast hash e1262561… (the C1-era lock v2); the
  current lock v2 hash is 3b5497c6…. The Monza / Austria / Barcelona forecast rows are unchanged by the Madrid rebuilds, so the numbers
  stand, but re-run `live/replay_run.py` and `live/prefix_eval.py` at C4 after the freeze so the artefacts chain to one hash.
* **N3. Claim scope.** Only next-lap MAE (every race) and pooled 3-lap cumulative MAE beat the prior-only baseline; the 5-lap
  cumulative error and the next-3 / next-5 point errors do not. The claim map must not say "beats the baseline" without that
  qualifier.
* **N4. Feedback ablation** stays "not run": 0 recorded events in `app_v2/state/feedback_events.jsonl` and in all three
  `out/live/*/driver_feedback.json`; the experiment is defined in `evaluation/scorecards.py` and runs from the scorecard build
  as soon as events exist. It was exercised once by accident at 21:27: the lead's screenshot gate (`tests/screenshots/capture.py`)
  wrote a Monza NOR row into the real UI log while the scorecard build ran, the ablation replayed that one pair (differences
  between the arms of at most 0.03 s) and the row was cleared seconds later; the live scorecard and SCORECARDS.md were regenerated
  on the empty log at 21:29 and carry the "not run" statement. The code path works; the input was a test artefact, not evidence.
* **N5. The live replay reads the UI feedback log by default, so a UI or screenshot session running at the same time changes
  test results.** `tests/live/test_replay.py::test_replay_outputs_validate` errored at 21:28 ("driver feedback timestamped after
  data_cutoff", the LivePredictor validator doing its job on a wall-clock-stamped row that the screenshot gate had just written to
  `app_v2/state/feedback_events.jsonl`); the same suite passed 31 / 31 at 21:14 and 21:25 with the log empty. Recommend: the
  replay tests pass an explicit temporary `feedback_path`, and the UI / screenshot tests write through a temporary log path
  (`feedback_service.log_path()` has no override today, Workstream 6). Design question for Workstream 8: feedback entered during a replay
  is stamped with wall-clock time, later than the race's `data_cutoff`, so a replay with real feedback can never validate as it
  stands; the timestamp rule or the replay clock needs a decision.

## 3. Cross-cutting note for the lead (not Workstream 3's files)

`app_v2/services/validation_repository.py` reveals the sealed block when `freeze` is non-null. Since 21:15 `holdout_aggregate.json`
carries `dry_run_before_freeze` / `quotable`; a freeze file that exists but is invalid (a flag false, no git_commit) would make
`freeze` non-null while `quotable` stays false. Gate the UI on `quotable is True`.
