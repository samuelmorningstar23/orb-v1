# Orb v1 build status at 2026-09-12T16:39:50

Merge queue: **OPEN** (C2 GO). Stop-the-line: none. Last checkpoint: C2 GO at 2026-09-12T16:37:49 (commit b0b924c). Last green: C2 at commit b0b924c.

Active workstreams: [1, 2, 3, 4, 5, 6, 7, 8, 9]. Stale threshold 40 min.

| Workstream | Light | Status | Age (min) | Task | Tests | ETA (min) | Blockers | Needs review from |
|---|---|---|---|---|---|---|---|---|
| 1 | GREEN | GREEN | 9.8 | contract_and_fixtures: lock v2 schema, lockio, a | 109/109 | 0 | - | 7 |
| 2 | GREEN | GREEN | -0.2 | 0.3 PreRaceCurveProvider (provider A); 0.4 count | 53/53 | 0 | - | 3, 7 |
| 3 | GREEN | GREEN (clock ahead 5 min) | -5.2 | blind evaluation: sealed-holdout evaluator, hidd | 0/0 | 180 | - | lead, 7 |
| 4 | GREEN | GREEN (clock ahead 8 min) | -8.2 | 0.5 track geometry, trajectory, time warp, brows | 30/30 | 0 | - | 6 |
| 5 | MISSING | MISSING (no heartbeat) | - |  | 0/0 | ? | - | - |
| 6 | AMBER | AMBER (stale 60 min) | 60.2 | 0.14 design system + shell; 0.15 hero screens; 0 | 42/42 | 0 | - | 4, 8, 7 |
| 7 | GREEN | GREEN | 4.8 | red team: consistency probe, leakage audit, iden | 0/0 | 180 | - | lead |
| 8 | GREEN | GREEN | 9.8 | live intelligence: 0.8 replay estimator, 0.10 fe | 31/31 | 0 | - | 3, 7 |
| 9 | GREEN | GREEN | 0.0 | build_control_system (task 0.16) | 83/83 | 0 | - | lead |

## Notes for the lead

- Workstream 5: no heartbeat file (progress/workstream_5.json) although active; Workstream 9 cannot message workstreams, lead to ping.
- Workstream 6: heartbeat stale (60 min > 40); lead to ping.
- Workstream 3: updated_at is 5 min in the future (clock ahead); the workstream should stamp real local time or staleness cannot be detected.
- Workstream 4: updated_at is 8 min in the future (clock ahead); the workstream should stamp real local time or staleness cannot be detected.
