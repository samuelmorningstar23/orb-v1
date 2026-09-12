# C5: GO

Scorecards with whole-weekend bands and n; 68 browser checks/15072 numbers/0 mismatches; independent refuters PASS; Madrid frozen; red team 10/10 PASS.

Decision note: 506 passed/1 known skip/1 expected xfail; 68 browser checks and 15072 numbers with zero mismatches; red team 10/10 PASS; 5 lead-only ownership flags, zero unowned; frozen sources unchanged.

- at: 2026-09-13T00:44:41
- commit: 230870b (branch main, 80 uncommitted paths)
- decided by: lead at 2026-09-13T00:45:16
- checks green: True
- previous green: C4 at 295ebc9
- active workstreams: [3, 6, 7]; missing heartbeats: none; stale: [1, 2, 3, 4, 6, 7, 8, 9]

## Integration checks

| check | status | note |
|---|---|---|
| schema_validation | PASS |  |
| pytest | PASS |  |
| ownership_audit | WARN | 78 changed paths, 5 flagged: proto/build_deck_v5.py, proto/deck_src/build_deck.js, proto/make_deck_figs.py, proto/out/Orb_v1_ChallengeDay.pdf, proto/out/Orb_v1_Mentor_Briefing.pptx |
| lock_dashboard_consistency | PASS |  |
| sealed_holdout_integrity | PASS |  |

pytest: passed 506, skipped 1, xfailed 1; test dirs ['contract', 'counterfactual', 'evaluation', 'live', 'red_team', 'release', 'replay', 'screenshots', 'ui']

## Artifact hashes (sha256[:16], compared with last green C4)

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
| 1 | AMBER (stale 494 min) | 494.6 | contract_and_fixtures: lock v2 schema, l | 109/109 | 0 | - |
| 2 | AMBER (stale 484 min) | 484.7 | 0.3 PreRaceCurveProvider (provider A); 0 | 53/53 | 0 | - |
| 3 | AMBER (stale 56 min) | 56.5 | C5 evaluation scorecards: eligible n and | 65/65 | 0 | - |
| 4 | AMBER (stale 476 min) | 476.7 | 0.5 track geometry, trajectory, time war | 30/30 | 0 | - |
| 6 | AMBER (stale 49 min) | 49.8 | C5 shared scorecard evidence on Validati | 74/74 | 0 | - |
| 7 | AMBER (stale 55 min) | 56.0 | C5 red-team tooling and independent Agen | 8/8 | 0 | - |
| 8 | AMBER (stale 494 min) | 494.7 | live intelligence: 0.8 replay estimator, | 31/31 | 0 | - |
| 9 | AMBER (stale 484 min) | 484.9 | build_control_system (task 0.16) | 83/83 | 0 | - |

## Ownership audit

WARN: 78 changed paths, 5 flagged: proto/build_deck_v5.py, proto/deck_src/build_deck.js, proto/make_deck_figs.py, proto/out/Orb_v1_ChallengeDay.pdf, proto/out/Orb_v1_Mentor_Briefing.pptx

merge queue before checkpoint: FROZEN
artifacts: checkpoints/C5/ (checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json, logs/)
