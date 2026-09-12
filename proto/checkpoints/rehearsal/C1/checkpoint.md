# C1: REHEARSAL

Workstream 9 tooling acceptance run; C1 substantive gate (provider A reproduces v1, both modes read one forecast hash) not assessed here

- at: 2026-09-12T14:54:24
- commit: 02f4c00 (branch main, 54 uncommitted paths)
- decided by: none (rehearsal; nothing decided)
- checks green: True
- previous green: C0 at 02f4c00
- active workstreams: [1, 6, 9]; missing heartbeats: none; stale: none

## Integration checks

| check | status | note |
|---|---|---|
| schema_validation | PASS |  |
| pytest | PASS |  |
| ownership_audit | WARN | 54 changed paths, 2 flagged: proto/out/lock_v2.json, proto/out/lock_v2_sidecars/validation_rows.json |
| lock_dashboard_consistency | NOT_IMPLEMENTED | not implemented: Workstream 7 provides evaluation/red_team/consistency_probe.py (exit 0 = lock and dashboard agree) |
| sealed_holdout_integrity | PASS |  |

pytest: passed 57; test dirs ['contract', 'release', 'screenshots', 'ui']

## Artifact hashes (sha256[:16], compared with last green C0)

- out/lock.json: 74fcbc9f6dd1f340
- out/lock_v2.json: 726b11de8873f714 (new)
- evaluation/holdout/sealed_holdout_manifest.json: 37b85e762b2e03c0
- evaluation/holdout/sealed_holdout_manifest.sha256: 2f636dda347557ea (new)
- fixtures/lock_v2_fixture.json: 8038a4879a5b854a
- schemas/lock_v2_minimal.py: f2cf5dea71eff700 (new)
- ui/tokens.py: 714224d37e4d978c
- theme/base.css: f0b55603d5ed6e7b (new)

## Heartbeats

| workstream | status | age min | task | tests | eta | blockers |
|---|---|---|---|---|---|---|
| 1 | AMBER | 10.1 | contract_and_fixtures: lock v2 schema, l | 0/0 | 120 | - |
| 6 | AMBER | 9.1 | 0.14 design system + shell; 0.15 hero sc | 0/0 | 150 | - |
| 9 | GREEN | 1.4 | build_control_system (task 0.16) | 57/57 | 20 | - |

## Ownership audit

WARN: 54 changed paths, 2 flagged: proto/out/lock_v2.json, proto/out/lock_v2_sidecars/validation_rows.json

merge queue before checkpoint: OPEN
artifacts: checkpoints/rehearsal/C1/ (checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json, logs/)
