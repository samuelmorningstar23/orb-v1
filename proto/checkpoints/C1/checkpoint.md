# C1: GO

committed at ccae5d9; wave two starts

- at: 2026-09-12T15:46:46
- commit: ccae5d9 (branch main, 3 uncommitted paths)
- decided by: lead
- checks green: True
- previous green: C1 at 02f4c00
- active workstreams: [1, 2, 4, 6, 8, 9]; missing heartbeats: [2, 4, 8]; stale: [9]

## Integration checks

| check | status | note |
|---|---|---|
| schema_validation | PASS |  |
| pytest | PASS |  |
| ownership_audit | PASS | 2 changed paths, 0 flagged |
| lock_dashboard_consistency | NOT_IMPLEMENTED | not implemented: Workstream 7 provides evaluation/red_team/consistency_probe.py (exit 0 = lock and dashboard agree) |
| sealed_holdout_integrity | PASS |  |

pytest: passed 218; test dirs ['contract', 'release', 'screenshots', 'ui']

## Artifact hashes (sha256[:16], compared with last green C1)

- out/lock.json: 74fcbc9f6dd1f340
- out/lock_v2.json: a0fb423b023d71b3
- evaluation/holdout/sealed_holdout_manifest.json: 37b85e762b2e03c0
- evaluation/holdout/sealed_holdout_manifest.sha256: 2f636dda347557ea
- fixtures/lock_v2_fixture.json: 8b90eae85d2c385a
- schemas/lock_v2_minimal.py: f2cf5dea71eff700
- ui/tokens.py: 714224d37e4d978c
- theme/base.css: f0b55603d5ed6e7b

## Heartbeats

| workstream | status | age min | task | tests | eta | blockers |
|---|---|---|---|---|---|---|
| 1 | GREEN | 34.2 | contract_and_fixtures: lock v2 schema, l | 106/106 | 0 | - |
| 2 | MISSING (no heartbeat) | - |  | 0/0 | None | - |
| 4 | MISSING (no heartbeat) | - |  | 0/0 | None | - |
| 6 | GREEN | 7.2 | 0.14 design system + shell; 0.15 hero sc | 42/42 | 0 | - |
| 8 | MISSING (no heartbeat) | - |  | 0/0 | None | - |
| 9 | AMBER (stale 46 min) | 46.4 | build_control_system (task 0.16) | 70/70 | 0 | - |

## Ownership audit

PASS: 2 changed paths, 0 flagged

merge queue before checkpoint: OPEN
artifacts: checkpoints/C1/ (checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json, logs/)
