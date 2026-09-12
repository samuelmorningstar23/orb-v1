# C6: GO

release candidate: offline run, release gate 326/326, five-minute rehearsal 303 s 12/12, fresh-clone pipeline under network deny, README and 109 pinned requirements; product blockers from the 01:42 browser audit repaired and verified in-browser; import boundary and presentation offline notice fixed

Decision note: offline run, release gate 326/326, five-minute rehearsal 303 s with 12/12 steps and 0 external requests, fresh-clone pipeline under network deny reproducing the lock, README and 109 pinned requirements; the 01:42 browser-audit blockers repaired and re-verified in-browser; import-boundary and presentation offline-notice faults fixed; suite 551 passed, 1 skipped, 1 xfailed; WARN is three lead-only README/requirements files

- at: 2026-09-13T02:22:17
- commit: d2d0e73 (branch main, 243 uncommitted paths)
- decided by: lead at 2026-09-13T02:22:47
- checks green: True
- previous green: C5 at 230870b
- active workstreams: [3, 6, 7]; missing heartbeats: none; stale: [1, 2, 3, 4, 6, 7, 8, 9]

## Integration checks

| check | status | note |
|---|---|---|
| schema_validation | PASS |  |
| pytest | PASS |  |
| ownership_audit | WARN | 241 changed paths, 3 flagged: README.md, proto/README.md, proto/requirements.txt |
| lock_dashboard_consistency | PASS |  |
| sealed_holdout_integrity | PASS |  |

pytest: passed 582, skipped 1, xfailed 1; test dirs ['contract', 'counterfactual', 'evaluation', 'live', 'red_team', 'release', 'replay', 'screenshots', 'ui']

## Artifact hashes (sha256[:16], compared with last green C5)

- out/lock.json: 6e0d69d64ca7da64
- out/lock_v2.json: 233f4e8c356758a1
- evaluation/holdout/sealed_holdout_manifest.json: 37b85e762b2e03c0
- evaluation/holdout/sealed_holdout_manifest.sha256: 2f636dda347557ea
- fixtures/lock_v2_fixture.json: 57825e9ff6ad7a04
- schemas/lock_v2_minimal.py: f2cf5dea71eff700
- ui/tokens.py: 714224d37e4d978c
- theme/base.css: f0b55603d5ed6e7b

## Heartbeats

| workstream | status | age min | task | tests | eta | blockers |
|---|---|---|---|---|---|---|
| 1 | AMBER (stale 592 min) | 592.2 | contract_and_fixtures: lock v2 schema, l | 109/109 | 0 | - |
| 2 | AMBER (stale 582 min) | 582.3 | 0.3 PreRaceCurveProvider (provider A); 0 | 53/53 | 0 | - |
| 3 | AMBER (stale 48 min) | 48.1 | C6 timed five-minute rehearsal and indep | 5/5 | 0 | - |
| 4 | AMBER (stale 574 min) | 574.3 | 0.5 track geometry, trajectory, time war | 30/30 | 0 | - |
| 6 | AMBER (stale 59 min) | 59.4 | C6 release UI acceptance and independent | 20/20 | 0 | - |
| 7 | AMBER (stale 48 min) | 48.2 | C6 red-team release/rehearsal gates, REA | 16/16 | 0 | - |
| 8 | AMBER (stale 592 min) | 592.3 | live intelligence: 0.8 replay estimator, | 31/31 | 0 | - |
| 9 | AMBER (stale 582 min) | 582.5 | build_control_system (task 0.16) | 83/83 | 0 | - |

## Ownership audit

WARN: 241 changed paths, 3 flagged: README.md, proto/README.md, proto/requirements.txt

merge queue before checkpoint: FROZEN
artifacts: checkpoints/C6/ (checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json, logs/)
