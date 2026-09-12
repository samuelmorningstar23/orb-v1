# C4: GO

Lead takeover: C4 decision engine, feedback and animation end to end. Active workstreams 3, 6, 7; others completed or unstarted by design. Post-freeze sealed holdout, aggregate only: MAE 0.0372 vs naive 0.1713 s/lap, coverage 1.00, 5 weekends / 9 compound-weekends. Frozen Madrid forecast preserved; scenarios and live sidecars aligned with post-qualifying lock; documents rebuilt by previous lead. Ordered probes rerun: 1692 numbers, 0 mismatches; claims empty; red team GO, 9/9 PASS; recorded leakage 5/5 and identity 41/41.

Decision note: Acting lead: reviewed checkpoint.md; schema, pytest (484 passed / 1 skipped / 1 xfailed including screenshots), consistency and sealed integrity PASS. Ownership WARN accepted as expected: 15 lead-only, 0 unowned. No failed checks or override. Active workstreams 3/6/7 reflect C4 contributors; stale historical heartbeats retained without impersonation. Red team 9/9 PASS, no required rewords; frozen artefacts unchanged.

- at: 2026-09-12T23:10:09
- commit: cdb1a45 (branch main, 151 uncommitted paths)
- decided by: lead at 2026-09-12T23:10:35
- checks green: True
- previous green: C3 at b0b924c
- active workstreams: [3, 6, 7]; missing heartbeats: none; stale: [1, 2, 3, 4, 7, 8, 9]

## Integration checks

| check | status | note |
|---|---|---|
| schema_validation | PASS |  |
| pytest | PASS |  |
| ownership_audit | WARN | 149 changed paths, 15 flagged: proto/build_case.py, proto/build_manual.py, proto/deck_src/build_deck.js, proto/out/JURY_QUESTIONS.md, proto/out/Orb_v1_ChallengeDay.pdf, proto/out/Orb_v1_Mentor_Briefing.pptx, proto/out/Orb_v1_Roadmap_and_Manual.pdf, proto/out/Orb_v1_The_Case.pdf, proto/out/ROADMAP.md, proto/out/THE_CASE.md, proto/out/forecast_Madrid_2026.json, proto/out/forecast_Madrid_2026.pdf, proto/out/forecast_Madrid_2026.sha256, proto/out/lock.json, proto/out/talk_track.md |
| lock_dashboard_consistency | PASS |  |
| sealed_holdout_integrity | PASS |  |

pytest: passed 484, skipped 1, xfailed 1; test dirs ['contract', 'counterfactual', 'evaluation', 'live', 'red_team', 'release', 'replay', 'screenshots', 'ui']

## Artifact hashes (sha256[:16], compared with last green C3)

- out/lock.json: 6e0d69d64ca7da64 (CHANGED)
- out/lock_v2.json: 233f4e8c356758a1 (CHANGED)
- evaluation/holdout/sealed_holdout_manifest.json: 37b85e762b2e03c0
- evaluation/holdout/sealed_holdout_manifest.sha256: 2f636dda347557ea
- fixtures/lock_v2_fixture.json: 57825e9ff6ad7a04
- schemas/lock_v2_minimal.py: f2cf5dea71eff700
- ui/tokens.py: 714224d37e4d978c
- theme/base.css: f0b55603d5ed6e7b

## Heartbeats

| workstream | status | age min | task | tests | eta | blockers |
|---|---|---|---|---|---|---|
| 1 | AMBER (stale 400 min) | 400.1 | contract_and_fixtures: lock v2 schema, l | 109/109 | 0 | - |
| 2 | AMBER (stale 390 min) | 390.1 | 0.3 PreRaceCurveProvider (provider A); 0 | 53/53 | 0 | - |
| 3 | AMBER (stale 99 min) | 99.2 | blind evaluation: sealed-holdout evaluat | 59/59 | 0 | - |
| 4 | AMBER (stale 382 min) | 382.1 | 0.5 track geometry, trajectory, time war | 30/30 | 0 | - |
| 6 | GREEN | 39.6 | C4 task 2 acceptance pass on the post-fr | 67/67 | 0 | - |
| 7 | AMBER (stale 53 min) | 53.4 | red team C4 re-run: four probes against  | 53/53 | 0 | - |
| 8 | AMBER (stale 400 min) | 400.1 | live intelligence: 0.8 replay estimator, | 31/31 | 0 | - |
| 9 | AMBER (stale 390 min) | 390.3 | build_control_system (task 0.16) | 83/83 | 0 | - |

## Ownership audit

WARN: 149 changed paths, 15 flagged: proto/build_case.py, proto/build_manual.py, proto/deck_src/build_deck.js, proto/out/JURY_QUESTIONS.md, proto/out/Orb_v1_ChallengeDay.pdf, proto/out/Orb_v1_Mentor_Briefing.pptx, proto/out/Orb_v1_Roadmap_and_Manual.pdf, proto/out/Orb_v1_The_Case.pdf, proto/out/ROADMAP.md, proto/out/THE_CASE.md, proto/out/forecast_Madrid_2026.json, proto/out/forecast_Madrid_2026.pdf, proto/out/forecast_Madrid_2026.sha256, proto/out/lock.json, proto/out/talk_track.md

merge queue before checkpoint: FROZEN
artifacts: checkpoints/C4/ (checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json, logs/)
