# Orb v1 lock v2: the contract in one page

`schemas/lock_v2.py` (pydantic v2) is the single source of truth; `schemas/lock_v2.schema.json` is exported from it
(`python proto/schemas/lock_v2.py export`, checked by a test). Numbers reach screens only through a lock that
`validators/validate_lock.py` accepts. Workstream 1 owns this contract; Workstream 7 reviews; changes land as PRs to `schemas/`.

## Namespaces

| block | who writes it | what it holds |
|---|---|---|
| `shared` | adapter / lead | `forecast_snapshot`, `model_version`, `forecast_hash`, `training_cutoff`, `support_definition` |
| `pre_race_forecast` | Workstream 1 adapter (from v1 `pipeline.py`) | per event, per compound: `naive, clean, clean_se, gate, issued, factor, factor_applied, prediction, band90, basis, energy_trend, push_adj, second_opinion` plus the pre-race plan. **Never** a race outcome. |
| `validation` | Workstream 1 adapter, later Workstream 3 | the v1 leave-one-weekend-out numbers copied verbatim; `rows` and `sealed_holdout` as hashed sidecars |
| `live_predictor` | Workstream 8 | `data_cutoff`, `prior`, `posterior` (a `LiveTyreState`, roadmap 7.1), `recommendations[]` (7.2), `driver_feedback[]` (7.3); `uses_future_data` and `uses_post_race_reference` are literally `false` |
| `ghost_strategy` | Workstream 2 / 3 | `mode`, `event`, `driver`, `weather_context`, `forecast_snapshot_hash`, `race_reference`, `counterfactual`, `generalisation_status` (the seven support fields), `model_implied: true`, `claim_scope`, `evidence_grade` |
| `counterfactuals[]` | Workstream 2 (frozen field: Workstream 5) | one self-describing Race Twin scenario per item: intervention, plans, summary distribution, assumptions, claim scope, assets, validation flags, warnings |
| `input_availability` | adapter / Workstream 8 | channel table (source, unit, rate, latency, availability, public/private, online-safe, missingness, quality, ablation) and `sensor_mode` |
| `driver_profile` | Phase 2 | typed stub (`status: stub`) |
| `extensions` | anyone | free dict, see below |

Vocabularies are `Literal`s exported from `lock_v2.py` (`Compound`, `SensorMode`, `SupportStatus`, `StateRegime`, `Action`,
`Symptom`, ...) so screens render them verbatim. `CLAIM_SCOPE_BY_MODE` gives the canonical claim-scope sentences per simulation mode.

## Meta on every block

Every dict-shaped block carries `meta`: `schema_version`, `generated_at`, `data_cutoff` (latest input timestamp used),
`git_sha`, `model_version`, `model_hash`, `provenance` (which code, from which inputs), `units`. `counterfactuals[]` items
carry the same information as top-level fields (`schema_version`, `forecast_hash`, `model_hash`, `data_cutoff`, `git_sha`).
Timestamps are ISO-8601 strings; within a block use either all-naive or all-aware values (mixing is an error).

## Rules the models enforce (not documentation)

* Stable blocks: `extra='forbid'` (`additionalProperties: false`), no NaN/Infinity, ordered quantiles, probabilities in [0, 1].
* `shared.forecast_hash == compute_forecast_hash(pre_race_forecast)`, and `ghost_strategy.forecast_snapshot_hash`,
  `live_predictor.prior.forecast_hash` and every `counterfactuals[].forecast_hash` equal it: one frozen forecast for both modes.
* Live: every `posterior`, recommendation and feedback timestamp is `<= live_predictor.data_cutoff`; `PUBLIC PROXY` forbids
  `team_sensor` channels; `PIT`/`PIT_NOW` need a `pit_window` and `target_compound`; a changed recommendation needs `change_reason`.
* Ghost: `model_implied` and `live_estimator_disabled` are `true`; non-actual weather is `evidence_grade: model_implied_scenario`;
  `OUT OF SUPPORT, FORECAST WITHHELD` needs an `abstention_reason` and carries no counterfactual; `ghost_strategy.counterfactual`
  must equal the referenced scenario in `counterfactuals[]` (map equals numbers).
* Counterfactuals: `tyre_only` cannot simulate track position, rivals or traffic; finish positions only in `frozen_field` and only
  as q10/median/q90; `rival_strategy_response` is `none`; plans must sum to `n_laps` with `pit_laps` at the stint ends.

## Sidecar policy

The lock stays small (the validator warns above 1 MB). Anything array-like (per-lap states, traces, validation rows, scorecard
tables, ghost replays) goes to a file referenced as `{path, sha256[, bytes, format, description]}` (`SidecarRef`).
`path` is POSIX and relative to the lock root `proto/` (e.g. `out/lock_v2_sidecars/validation_rows.json`,
`feat/Monza_R.csv`); absolute paths and `..` are rejected. Use `shared.lockio.write_sidecar_json` / `sidecar_ref` to produce
references and `atomic_write_json` for the lock itself (temp file + fsync + `os.replace`; a reader never sees a partial lock).
`validate_lock.py` verifies every sidecar sha256 that exists (mismatch = exit 3; missing = warning, or failure with `--strict`).

## Hash policy

`forecast_hash = 'sha256:' + sha256(canonical_json(block without its top-level meta))`, computed on the *validated* block
(`schemas.lock_v2.compute_forecast_hash`) so defaults are materialised identically by every producer. Re-running the adapter
at another time or commit on the same forecast reproduces the hash; any change to a forecast number changes it.
`canonical_json` = sorted keys, compact separators, UTF-8, NaN refused.

## Extending the contract

1. Put new material under `extensions.<workstream_or_topic>` (free-form) and ship; the lock still validates.
2. When the shape is stable, open a PR against `schemas/lock_v2.py`: add the model (extra forbidden, units documented), regenerate
   `lock_v2.schema.json` and the fixture (`python proto/fixtures/make_fixtures.py`), add a contract test, bump `SCHEMA_VERSION`
   (minor for additive fields, major for renames/removals).
3. Workstream 1 promotes the block; consumers switch from `extensions.x` to the stable path. Never edit a stable block's shape
   without the version bump: schema drift that breaks another workstream stops the line.

## Tooling

```
python proto/validators/adapt_v1.py                 # out/lock.json (v1) -> out/lock_v2.json + out/lock_v2_sidecars/
python proto/validators/validate_lock.py <lock>     # exit 0 valid | 1 file/JSON | 2 schema | 3 sidecar hash
python proto/schemas/lock_v2.py export              # regenerate lock_v2.schema.json
python proto/fixtures/make_fixtures.py              # regenerate fixtures (deterministic; a test checks disk == generator)
pytest proto/tests/contract -q
```

Fixtures: `fixtures/lock_v2_fixture.json` (every namespace, Monza 2026 replay/audit + Madrid prospective), `fixtures/sidecars/`,
`fixtures/mini_race/` (synthetic 3-driver, 14-lap race in the feat layout with a 4 Hz position trace and `manifest.json`),
`fixtures/golden_race.json` (the real Monza 2026 feature files by path with sha256; `feat/` is gitignored, tests skip the byte
check when absent). `fixtures/seed_v1_snapshot.json` is the frozen v1 excerpt the generator reads. `lock_v2_minimal.py` is the
superseded C0 stub kept for reference.
