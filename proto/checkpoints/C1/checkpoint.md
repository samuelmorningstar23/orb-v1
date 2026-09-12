# C1: GO_WITH_REASSIGNMENT

Decision note: Foundation integrated: contract, adapter and forecast hash, premium shell and hero screens, build control. Provider A reproduction moved to the C2 entry gate as Workstream 2's first deliverable. Ownership warning is the mentor deck in the lead-owned out/ folder.

- at: 2026-09-12T15:42:02
- commit: 02f4c00 (branch main, 139 uncommitted paths)
- decided by: lead at 2026-09-12T15:45:28
- checks green: True
- previous green: C0 at 02f4c00
- active workstreams: [1, 6, 9]; missing heartbeats: none; stale: [9]

## Integration checks

| check | status | note |
|---|---|---|
| schema_validation | PASS |  |
| pytest | PASS |  |
| ownership_audit | WARN | 138 changed paths, 1 flagged: proto/out/Orb_v1_Mentor_Briefing.pptx |
| lock_dashboard_consistency | NOT_IMPLEMENTED | not implemented: Workstream 7 provides evaluation/red_team/consistency_probe.py (exit 0 = lock and dashboard agree) |
| sealed_holdout_integrity | PASS |  |

pytest: passed 218; test dirs ['contract', 'release', 'screenshots', 'ui']

## Artifact hashes (sha256[:16], compared with last green C0)

- out/lock.json: 74fcbc9f6dd1f340
- out/lock_v2.json: a0fb423b023d71b3 (new)
- evaluation/holdout/sealed_holdout_manifest.json: 37b85e762b2e03c0
- evaluation/holdout/sealed_holdout_manifest.sha256: 2f636dda347557ea (new)
- fixtures/lock_v2_fixture.json: 8b90eae85d2c385a (CHANGED)
- schemas/lock_v2_minimal.py: f2cf5dea71eff700 (new)
- ui/tokens.py: 714224d37e4d978c
- theme/base.css: f0b55603d5ed6e7b (new)

## Heartbeats

| workstream | status | age min | task | tests | eta | blockers |
|---|---|---|---|---|---|---|
| 1 | GREEN | 29.4 | contract_and_fixtures: lock v2 schema, l | 106/106 | 0 | - |
| 6 | GREEN | 2.4 | 0.14 design system + shell; 0.15 hero sc | 42/42 | 0 | - |
| 9 | AMBER (stale 41 min) | 41.7 | build_control_system (task 0.16) | 70/70 | 0 | - |

## Ownership audit

WARN: 138 changed paths, 1 flagged: proto/out/Orb_v1_Mentor_Briefing.pptx

merge queue before checkpoint: FROZEN
artifacts: checkpoints/C1/ (checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json, logs/)
