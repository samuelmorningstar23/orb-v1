# C3: GO

hero screens end to end: Workstream 6 C3 integration, Workstream 3 evaluation, Workstream 7 red team; lock rebuilt after FP3, lock v2 re-adapted

Decision note: hero screens end to end: Live Predictor, Decision board, Driver feedback via live_bridge (post-race fields stripped, tested); Ghost Strategy with Race Twin player and counterfactual evidence; Validation with prefix eval; 368+8 tests green after lock v2 re-adaptation; WARN is stale heartbeats (workstreams paused at 17:00, resumed 21:05)

- at: 2026-09-12T21:06:31
- commit: b0b924c (branch main, 130 uncommitted paths)
- decided by: lead at 2026-09-12T21:07:20
- checks green: True
- previous green: C2 at b0b924c
- active workstreams: [1, 2, 3, 4, 5, 6, 7, 8, 9]; missing heartbeats: [5]; stale: [1, 2, 3, 4, 6, 7, 8, 9]

## Integration checks

| check | status | note |
|---|---|---|
| schema_validation | PASS |  |
| pytest | PASS |  |
| ownership_audit | WARN | 128 changed paths, 14 flagged: scheduled_tasks.lock, .gitignore, proto/build_forecast.py, proto/deck_src/README.md, proto/deck_src/build_deck.js, proto/deck_src/package.json, proto/out/Orb_v1_ChallengeDay.pdf, proto/out/excluded_Madrid.csv, proto/out/forecast_Madrid_2026.json, proto/out/forecast_Madrid_2026.pdf, proto/out/forecast_Madrid_2026.sha256, proto/out/lock.json, proto/out/results.csv, proto/refresh.sh |
| lock_dashboard_consistency | PASS |  |
| sealed_holdout_integrity | PASS |  |

pytest: passed 377, skipped 1; test dirs ['contract', 'counterfactual', 'evaluation', 'live', 'red_team', 'release', 'replay', 'screenshots', 'ui']

## Artifact hashes (sha256[:16], compared with last green C2)

- out/lock.json: a469d1904ebd3cbb (CHANGED)
- out/lock_v2.json: 63a39a4e96c987a0 (CHANGED)
- evaluation/holdout/sealed_holdout_manifest.json: 37b85e762b2e03c0
- evaluation/holdout/sealed_holdout_manifest.sha256: 2f636dda347557ea
- fixtures/lock_v2_fixture.json: 57825e9ff6ad7a04
- schemas/lock_v2_minimal.py: f2cf5dea71eff700
- ui/tokens.py: 714224d37e4d978c
- theme/base.css: f0b55603d5ed6e7b

## Heartbeats

| workstream | status | age min | task | tests | eta | blockers |
|---|---|---|---|---|---|---|
| 1 | AMBER (stale 276 min) | 276.5 | contract_and_fixtures: lock v2 schema, l | 109/109 | 0 | - |
| 2 | AMBER (stale 266 min) | 266.5 | 0.3 PreRaceCurveProvider (provider A); 0 | 53/53 | 0 | - |
| 3 | AMBER (stale 248 min) | 248.5 | blind evaluation: sealed-holdout evaluat | 0/0 | 120 | - |
| 4 | AMBER (stale 258 min) | 258.5 | 0.5 track geometry, trajectory, time war | 30/30 | 0 | - |
| 5 | MISSING (no heartbeat) | - |  | 0/0 | None | - |
| 6 | AMBER (stale 247 min) | 247.1 | C3 integration: hero screens end to end  | 49/49 | 0 | - |
| 7 | AMBER (stale 261 min) | 261.5 | red team: consistency probe, leakage aud | 0/0 | 150 | - |
| 8 | AMBER (stale 276 min) | 276.5 | live intelligence: 0.8 replay estimator, | 31/31 | 0 | - |
| 9 | AMBER (stale 266 min) | 266.7 | build_control_system (task 0.16) | 83/83 | 0 | - |

## Ownership audit

WARN: 128 changed paths, 14 flagged: scheduled_tasks.lock, .gitignore, proto/build_forecast.py, proto/deck_src/README.md, proto/deck_src/build_deck.js, proto/deck_src/package.json, proto/out/Orb_v1_ChallengeDay.pdf, proto/out/excluded_Madrid.csv, proto/out/forecast_Madrid_2026.json, proto/out/forecast_Madrid_2026.pdf, proto/out/forecast_Madrid_2026.sha256, proto/out/lock.json, proto/out/results.csv, proto/refresh.sh

merge queue before checkpoint: FROZEN
artifacts: checkpoints/C3/ (checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json, logs/)
