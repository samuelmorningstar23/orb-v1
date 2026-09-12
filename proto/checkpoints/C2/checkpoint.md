# C2: GO

Decision note: Wave two integrated: counterfactual core and events, geometry and player, live estimator and decision engine; schema at 2.1.0. Ownership warnings are new test directories not yet in the map plus lead-owned extractor edits.

- at: 2026-09-12T16:36:03
- commit: ccae5d9 (branch main, 202 uncommitted paths)
- decided by: lead at 2026-09-12T16:36:24
- checks green: True
- previous green: C1 at ccae5d9
- active workstreams: [1, 2, 4, 6, 8, 9]; missing heartbeats: none; stale: [6, 9]

## Integration checks

| check | status | note |
|---|---|---|
| schema_validation | PASS |  |
| pytest | PASS |  |
| ownership_audit | WARN | 201 changed paths, 20 flagged: proto/cleanup_pass.sh, proto/extract_seasons.py, proto/out/Orb_v1_Mentor_Briefing.pptx, proto/tests/counterfactual/conftest.py, proto/tests/counterfactual/test_cf_cli.py, proto/tests/counterfactual/test_cf_engine.py, proto/tests/counterfactual/test_cf_events.py, proto/tests/counterfactual/test_cf_provider.py, proto/tests/live/conftest.py, proto/tests/live/live_helpers.py, proto/tests/live/test_estimator.py, proto/tests/live/test_feedback.py, proto/tests/live/test_optimizer.py, proto/tests/live/test_replay.py, proto/tests/replay/conftest.py, proto/tests/replay/test_assets.py, proto/tests/replay |
| lock_dashboard_consistency | NOT_IMPLEMENTED | not implemented: Workstream 7 provides evaluation/red_team/consistency_probe.py (exit 0 = lock and dashboard agree) |
| sealed_holdout_integrity | PASS |  |

pytest: passed 335; test dirs ['contract', 'counterfactual', 'evaluation', 'live', 'red_team', 'release', 'replay', 'screenshots', 'ui']

## Artifact hashes (sha256[:16], compared with last green C1)

- out/lock.json: 74fcbc9f6dd1f340
- out/lock_v2.json: a0fb423b023d71b3
- evaluation/holdout/sealed_holdout_manifest.json: 37b85e762b2e03c0
- evaluation/holdout/sealed_holdout_manifest.sha256: 2f636dda347557ea
- fixtures/lock_v2_fixture.json: 57825e9ff6ad7a04 (CHANGED)
- schemas/lock_v2_minimal.py: f2cf5dea71eff700
- ui/tokens.py: 714224d37e4d978c
- theme/base.css: f0b55603d5ed6e7b

## Heartbeats

| workstream | status | age min | task | tests | eta | blockers |
|---|---|---|---|---|---|---|
| 1 | GREEN | 6.0 | contract_and_fixtures: lock v2 schema, l | 109/109 | 0 | - |
| 2 | GREEN | -4.0 | 0.3 PreRaceCurveProvider (provider A); 0 | 53/53 | 0 | - |
| 3 | GREEN | -8.9 | blind evaluation: sealed-holdout evaluat | 0/0 | 180 | - |
| 4 | GREEN | -11.9 | 0.5 track geometry, trajectory, time war | 30/30 | 0 | - |
| 6 | AMBER (stale 56 min) | 56.5 | 0.14 design system + shell; 0.15 hero sc | 42/42 | 0 | - |
| 7 | GREEN | 1.1 | red team: consistency probe, leakage aud | 0/0 | 180 | - |
| 8 | GREEN | 6.0 | live intelligence: 0.8 replay estimator, | 31/31 | 0 | - |
| 9 | AMBER (stale 95 min) | 95.7 | build_control_system (task 0.16) | 70/70 | 0 | - |

## Ownership audit

WARN: 201 changed paths, 20 flagged: proto/cleanup_pass.sh, proto/extract_seasons.py, proto/out/Orb_v1_Mentor_Briefing.pptx, proto/tests/counterfactual/conftest.py, proto/tests/counterfactual/test_cf_cli.py, proto/tests/counterfactual/test_cf_engine.py, proto/tests/counterfactual/test_cf_events.py, proto/tests/counterfactual/test_cf_provider.py, proto/tests/live/conftest.py, proto/tests/live/live_helpers.py, proto/tests/live/test_estimator.py, proto/tests/live/test_feedback.py, proto/tests/live/test_optimizer.py, proto/tests/live/test_replay.py, proto/tests/replay/conftest.py, proto/tests/replay/test_assets.py, proto/tests/replay

merge queue before checkpoint: FROZEN
artifacts: checkpoints/C2/ (checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json, logs/)
