# Counterfactual core: Race Twin scenarios

Roadmap v5 tasks 0.3 (PreRaceCurveProvider), 0.4 (counterfactual core) and, in `proto/events/`, 0.9 (RaceEventSource).

## Default-curve decision (lead, 12 Sep)

* **Historical Audit** replays on the race-derived reference **with the target driver excluded**, labelled
  **'leave-one-driver-out Sunday reference'** (`curve_source='race_reference'`, `exclude_target_driver=True`, the CLI default).
  It is post-race material (wording rule 9.2: a "race-derived pace-loss reference"); the scenario carries
  `validation.target_driver_excluded=true` and `engine.uses_post_race_reference=true`.
* **Scenario Explorer** uses the **pre-race forecast only** (`curve_source='pre_race_forecast'`, `--curve pre_race_forecast`):
  provider A's frozen curve, no race data, `engine.uses_post_race_reference=false`, provenance carrying the lock's forecast hash.
* `engine.curves.intended_page` names the page each curve source is for; the label is rendered, not paraphrased.

## Modules

| file | what |
|---|---|
| `provider.py` | `TyreCurveProvider.predict_curve(event_id, driver_id, compound, context, tyre_age_range) -> CurveDistribution`; `ProviderA` reproduces `out/lock.json` exactly (completed weekend: `validation_rows` pred_clearstint / lo / hi; live weekend: `live[event].compounds` prediction / band90); `reference_curve_post_race` is the only way to the race-derived slope and is refused by `assert_pre_race`. |
| `racedata.py` | race file loading, RED / SC / VSC / YELLOW labels, red-flag gap fill, positions from lap order, field-relative stop measurement, reference refit (all drivers reproduces the lock `obs`; target driver excludable). |
| `pitmodel.py` | the standardised pit event as a distribution and where each number comes from (`derivation`). |
| `engine.py` | `Y = B + T + P + I + e`; modes `tyre_only` and `fixed_context`; `frozen_field` raises `NotImplementedError`; whole-curve sampling as one coefficient matrix times a shared sample matrix; identity and leakage checks; schema-valid summary; support guard. |
| `run.py` | CLI: one scenario or a driver x lap x compound lattice. |

## Decomposition and modes

`Y_cf - Y = (T_cf - T_actual) + (P_cf - P_actual) + (I_cf - I_actual)` with `T = offset[compound] + slope[compound] x age`
(offsets from `lock.strategy[event].offsets`, SOFT = 0), `P` the pit in-lap / out-lap / warm-up effects, `I = beta_traffic x traffic share`.
`B` cancels lap by lap; a contaminated actual lap (pit lap, SC / VSC lap, out-lap, missing row) is reconstructed as
`Y - P_measured + counterfactual terms`, never copied.

* `tyre_only`: the tyre-time delta as if the race were green throughout; standardised stops at green cost; `traffic_mode='clean_air'`;
  the observed SC periods are reported but `assumptions.safety_car_mode='none'`.
* `fixed_context`: SC / VSC / red-flag laps frozen (no tyre pace delta, age still advances), SC factor on a stop whose in-lap or out-lap
  falls on an SC / VSC lap, restart warm-up on the first green lap after a frozen block, traffic paired lap by lap:
  `traffic_mode='paired_replay'`, `assumptions.safety_car_mode='fixed_observed_schedule'`, `safety_car_schedule` = the observed periods.
* Both: `track_position_simulated=false`, `rival_interactions_simulated=false`, `claim_scope` from `CLAIM_SCOPE_BY_MODE`.

Uncertainty samples whole curves and parameters, never per-lap noise: slopes from their SE (race reference) or the 90% band width
(pre-race forecast), compound offsets (sd 0.15 s, stated), pit transit, stationary time, out-lap penalty, warm-up residual.
The reported `lap_delta` is the sample mean, so `sum(lap_delta) == cumulative_delta[-1] == engine.elapsed_delta_mean_s` exactly.

## Standardised pit event (Monza 2026 numbers)

* Transit loss: median over a race's green-flag stops of (in-lap excess + out-lap excess) minus the stationary median 2.5 s; needs 4 stops.
  Monza has only 2 measurable green stops (ALB lap 46: 28.1 s, LAW lap 12: 35.5 s; the other changes were free under the lap-3 red flag or
  under the VSC), so the **2026 season pool** is used: 225 green stops over 13 race files, median 21.98 s (MAD 1.86) -> transit 19.48 s,
  sd 2.76, 17.7% of it on the in-lap. The v1 lock's strategy assumption (21.0 s) is reported alongside.
* Stationary: median 2.5 s, q10 2.1, q90 3.4 (stated assumption, split normal).
* Out-lap penalty (first kept lap minus second) and warm-up residual (second minus third): per compound from the pool
  (SOFT -0.11 / MEDIUM +0.07 / HARD -0.13 s; warm-up -0.24 / -0.21 / -0.08 s): no measurable warm-up beyond the out-lap in 2026 data.
* SC factor: 0.55 of the green transit loss by default (stated); Monza's seven VSC stops measure 0.93, reported in `pit_model.sc_factor_measured`.
* Stops under a red flag are free (the change happens during the stoppage).
* With `standardised_pit_event=False` the driver's own measured stop is moved verbatim (identity replay gives exactly zero);
  with it enabled (default) an identity replay gives exactly `engine.stop_replacement_delta_s`.

## Support and honesty flags

`engine.support`: a counterfactual stint longer than any stint driven on that compound in the race is `OUT OF SUPPORT` (the linear reference
has no cliff term); a compound slope resting on fewer than 50 kept race laps is a `thin reference` warning; free red-flag stops are flagged;
retired drivers are scored over their completed laps only. The sealed-holdout races (evaluation/holdout manifest) are refused unless
`allow_sealed=True` (Workstream 3's evaluator).

## CLI and outputs

```
python -m counterfactual.run --event Monza --driver NOR --lap 24 --to MEDIUM --set NEW --mode fixed_context [--continuation as_actual|one_stop|two_stop]
    [--replace-stop auto|none|K] [--curve race_reference|pre_race_forecast] [--no-standardised-pit] [--sc-factor 0.55|measured] [--out DIR]
python -m counterfactual.run --event Monza --lattice [--mode ...] [--drivers NOR,VER] [--laps 10,20] [--compounds MEDIUM,HARD]
```

`out/counterfactual/<scenario_id>/`: `laps.csv` (mandatory columns first: lap, actual_lap_time, cf_lap_time_mean/q10/q90, lap_delta, cumulative_delta,
actual/cf compound and tyre age, traffic effects, pit_state, track_status, actual_position, cf_position_* null), `summary.json`
(`scenario` validates against `schemas.lock_v2.CounterfactualScenario`, `engine` diagnostics, `events` for the conservation test),
`lap_deltas.json` and `ghost_replay.json` in the fixture formats the dashboard reads. Sidecar refs (sha256) sit in `scenario.assets`,
relative to `proto/`. `validators/validate_lock.py` accepts a lock carrying the item (a test does this).

Timing: a scenario compiles in about 2 ms warm (about 125 ms on the first call for a race, including the cached precompute);
the Monza lattice (3,024 scenarios) takes about 1 s.

## Tests

`pytest proto/tests/counterfactual -q`: identity, same-compound, zero-degradation, round trip, time accounting, event conservation,
no-future-data flags, provider A == lock, schema validation (item and inside the full lock, reference validator), sources interchangeable, timing.
