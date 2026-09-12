# Red team report for C6

generated 2026-09-13T01:40:56 · lock 2026-09-12T21:33:10 · forecast hash sha256:66e3201e860b19e...

## Verdict: GO

Red team verdict for C6: GO. Blocking list: 0 open, 1 resolved (RT-BLK-1 closed at the live_bridge boundary with guarding tests). Acceptance suite tests/red_team: 78 passed, 0 failed, 1 xfailed in 2.48 s. Consistency probe: PASS (3505 rendered numbers, 0 mismatches). Leakage audit PASS (5 of 5 checks pass); identity checks PASS {'passed': 41, 'failed': 0}. Hashed forecast out/forecast_Madrid_2026.json: PASS (issued 2026-09-12T21:33:14+05:30 from sessions ['FP1', 'FP2', 'FP3', 'Q']; pointers resolve {'lock_v2_forecast_hash': True, 'lock_sha256': True, 'lock_v2_sha256': True}). Forecast-hash provenance: PASS (runtime readers agree: True; stale sidecars: 0; content-only proof: the hash changes with the per-event data_cutoff stamp alone). Madrid anchors: PASS (0 stated times that did not happen as written). Wording flags outstanding: 0 (owners: []).

## Checks

| check | status | detail |
|---|---|---|
| consistency_probe | PASS | 3505 numbers, 0 mismatches, 26 unhashed live values; failing routes [] |
| leakage_audit | PASS | {'static_imports': 'PASS', 'import_closure': 'PASS', 'future_read_and_deny_list_spy': 'PASS', 'target_driver_exclusion': 'PASS', 'one_forecast_hash': 'PASS'} |
| identity_checks | PASS | {'passed': 41, 'failed': 0}  |
| claim_audit | PASS | {'verified': 21, 'exceeds_evidence': 5, 'unverifiable': 5, 'mismatch': 6}; survivors [] |
| acceptance_suite | PASS | {'passed': 78, 'failed': 0, 'errors': 0, 'skipped': 0, 'xfailed': 1, 'xpassed': 0} in 2.48 s; not green: ['test_forecast_hash_is_content_only XFAIL (documented defect)'] |
| forecast_file_audit | PASS | out/forecast_Madrid_2026.json issued 2026-09-12T21:33:14+05:30 sessions ['FP1', 'FP2', 'FP3', 'Q'] pointers {'lock_v2_forecast_hash': True, 'lock_sha256': True, 'lock_v2_sha256': True}; problems [] |
| hash_provenance | PASS | runtime readers agree True; stale sidecars [] |
| madrid_anchors | PASS | FP3 refresh landed 18:11 IST; qualifying refresh attempts ['21:03', '21:32'] (session not run yet at ['21:03'], imported at ['21:32']); hashed forecast published at ['21:32'] (current file issued 2026-09-12T21:33:14+05:30 from sessions ['FP1', 'FP2', 'FP3', 'Q']); stale statements [] |
| blocking | PASS | open [] resolved ['RT-BLK-1'] observations ['RT-OBS-1', 'RT-OBS-2', 'RT-OBS-3', 'RT-OBS-4'] |
| browser_consistency | PASS |  |
| readme_evidence | PASS | frozen README facts verified |
| release_gate | PASS | complete release matrix PASS |
| five_minute_rehearsal | PASS | 302.51102354202885s, 12 samples, 4823 numbers; [] |

## Wording flags outstanding (owner)

- none

## Blocking issues

open: []

- resolved RT-BLK-1: closed at the page boundary (lead decision 20:58): every live page builds its view model through app_v2/services/live_bridge.build, whose _strip_post_race replaces forecast.observed / observed_se / err / n_race with None; the raw builders (app_v2/services/view_models.build_live, live/viewmodel.build
- observation RT-OBS-1 (LOW): lock-metadata support chip on the live pages uses the whole-session race rain flag — owner ['workstream 6']
- observation RT-OBS-2 (LOW): the dashboard process on port 8502 predates the 22:01 reword of live/viewmodel.py and decision/optimizer.py — owner ['lead']
- observation RT-OBS-3 (LOW): claim_audit now distinguishes a bare claim from the same number stated with its required qualification (reclassification logged, not silent) — owner ['workstream 7']
- observation RT-OBS-4 (LOW): live_position_claim still flags app_v2/services/live_bridge.py:99 - assessed as a false positive, rule deliberately left strict — owner ['workstream 6', 'lead']

## Inputs

leakage: 2026-09-13T01:40:48, claims: 2026-09-13T01:40:53, identity: 2026-09-13T01:40:51, probe: 2026-09-13T01:35:53
