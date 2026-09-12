# C6 command ledger

Main checkout: /Users/samuelmorningstar/Trackshift. All commands use the relevant checkout's proto/ working directory and ../.venv/bin/python unless an external executable is named. Workstreams use /private/tmp/orb-c6-workstream3, workstream6, workstream7 with the canonical coordination directory in main. No workstream commits.

## Lead setup and reproduction

- Read INSTRUCTIONS.md, coordination/PROTOCOL.md, coordination/NOTES_A.md, coordination/NOTES_B.md in order; git status clean; git log -5 HEADd2d0e73, C5GO132d333. Read progress/SUMMARY.md, release/README.md, workstreams6/7 reports and WORKSTREAMS.md.
- ../.venv/bin/python -m pip freeze initially failed: pip absent in the existing environment. ../.venv/bin/python -m ensurepip installed bundled pip25.0.1 successfully. No package used by the product was upgraded.
- ../.venv/bin/python -m pip freeze > /private/tmp/orb-c6-requirements.txt; copied exact output to requirements.txt:109 pinned distributions. A command-v uv probe was absent; pipeline stopped before writing, then resumed with pip. No uv fallback was used.
- ../.venv/bin/python -m pip check: No broken requirements found. Exact freeze-to-file equality independently checked.
- git clone --no-hardlinks .. /private/tmp/orb-c6-fresh-clone:PASS; fresh clone atC5hand-offd2d0e73. Copied candidate requirements.txt and69cached feature CSVs (7,745,063bytes); created an independent venv with ../.venv/bin/python -m venv /private/tmp/orb-c6-fresh-clone/.venv.
- /private/tmp/orb-c6-fresh-clone/.venv/bin/python -m pip install --disable-pip-version-check -r /private/tmp/orb-c6-fresh-clone/proto/requirements.txt:exit0, all109 installed. Log fresh_install.txt. This is a new environment, not a symlink to main.
- From cloneproto: ../.venv/bin/python -m pip check:PASS. /usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)' ../.venv/bin/python pipeline.py:exit0. Log fresh_pipeline.txt. Parsed output lock equals main lock in every field except generated_at. Input hashes in fresh_clone_report.json. No pipeline run in main.
- Independent denial control using the same sandbox profile: socket.create_connection(('127.0.0.1',9),timeout=1) raised PermissionError, proving network denial; log network_denial_proof.txt.
- From cloneproto: ../.venv/bin/streamlit run app_v2/streamlit_app.py --server.port 8510 --server.headless true --browser.gatherUsageStats false. New-venv Playwright checked health200 and Landing plus Live/MonzaNORlap30 readiness with0Streamlit exceptions,0pageerrors,0external HTTP requests. Clone server terminated after check. Report fresh_clone_report.json. Copied cached inputs are independent files; no model/forecast/holdout outputs copied back.

## Independent reviews and focused tests

- Workstream6 release gate script againstmain8502: initial322checksPASS; strengthened every keyboard destination; definitive324/324PASS,19routes×2viewports.18 policy regression testsPASS. Exact command and timing details in app_v2/PERF.md and tests/screenshots/c6_release_report.json.
- Workstream6 independently checked README:109pins match pipfreeze,8questions,6references exist,4Madrid digests, corrected transfer-factor/fallback distinction and refresh start/publication timestamps. Independently recomputed69feature input hashes and compared freshclone actual lock exceptgenerated_at. Script preserved under review_tools/readme_refuter.py.
- Workstream7 ../.venv/bin/python -m evaluation.red_team.refute_c6_release --source /private/tmp/orb-c6-workstream6/proto --out evaluation/red_team/c6_release_refutation.json:PASS38matrixcases+11hostileorigin cases. Report/source hashes retained.
- Workstream7 C6 focused regressions:13passed, including realMonzaNORlap32feedback and exclusion of laterlap40feedback.
- Workstream3 tests/evaluation/test_rehearsal_runner.py:4passed before definitive rehearsal. Runner records actual300s timeline, allnumericobservations andprefixevidence, oneauthorizedfeedbackevent, exactCASlogrestoration, RaceTwinHUD/frameproof, rawDOM/screenshots, networkerrors.

## Development issues and corrections

Lead added explicit ownership of README.md/requirements.txt and rootREADME.md, retaining flagged lead-only status. Existing ownership fixture expected rootREADME unowned; assertion and category count updated and an unknown-root-file check added. Combined main command ../.venv/bin/python -m pytest tests/release tests/red_team/test_c6_evidence.py -q -p no:cacheprovider passed95 and failed1 because dynamic capture import could not resolve network_guard. Release tests83 passed in that combined run; Workstream7 is correcting static route discovery so it does not execute capture.py or depend on collection order. No release check was waived.

README reviewer corrections applied in source: transfer-factor disagreement means factor1 on an issued curve, not withheld fallback; qualifying refresh began21:32:31 and published21:33:14; training wording narrowed to compound transfer-factor fitting. RootREADME now links the current guide instead of preserving stale launch commands. Full final audit/checkpoint commands and outcomes will be recorded below and in coordination/NOTES_B.md before completion.

## Stop-line and stricter release interpretation

Main focused integration: ../.venv/bin/python -m pytest tests/release tests/red_team/test_c6_evidence.py tests/screenshots/test_release_gate.py -q -p no:cacheprovider =>115passed2.28s after AST-onlyrouteinventory fixed the import issue. Mainreadme_refuter andrefute_c6_release commands exited0.

First definitive rehearsal:184seconds,7checkpoints/716numericobservations,0numericmismatch/unclassified; failed on Frames.to_dict (actualAPIto_player_dict),10rawdeep-link404console/network errors, andpost-feedbackreplayremaininglap32. Feedbackrestoredexactly. Failed report preserved. ../.venv/bin/python build_control.py stop-the-line "C6 rehearsal incomplete: Race Twin harness serialization, deep-navigation request failures, and post-feedback replay not advancing; feedback log restored; repair and rerun required." --by "lead" recordedqueueFROZEN. Workstream7correctlyrejectsreport. NoGOoverride.

Independent review found initial324PASSreleasegate filtered health/host-config404console entries. Userrequiresrawzero; that run is retained asinitial_release_report_filtered.json, not accepted asfinalC6proof. Workstream6mustuseproperinternalnavigation andfailrawerrors, thenrerun; Workstream3repairsharnessandrehearsal, no numericalwaivers.

## Corrected gate and focused rehearsal evidence

Workstream6 definitive raw-zero capture326/326PASS,38route/viewports, rawconsoleerrors[],rawnetworkfailures[],legacyprobes[],externalrequests[]. Worstcold1192ms; click211–272ms;16keyboard102–255ms;4238localHTTP/38localWS; maxgoldendifference1.142%, no goldenupdates. Workstream7independentrawmatrix+11hostileoriginchecksPASS. Mainfocused gate+C6tests35passed0.52s.

Workstream3focusedrepair provedlive32→53 withPlaywrighteventpumping androot+internalnavigation; no productfixneeded. ActualFrameAPIto_player_dict used. Textnodeboundaries prevent concatenatedLap/clocktokens; quantilelabels havetypedreferences. TwinMutationObserverprobe62HUDupdates in5s:allrecordednumbersstrictmatched,frozenembeddedframepayloadexact,rawconsole/HTTP/externalerrorszero. Mainrunner+C6tests20passed0.48s.

Workstream7finalruntimehook uses typed session.n_laps and7.1record-schema references before generalnumericmatches; this fixes coincidental sourceattribution without exemptions. Maincopied anearlierhookonce, causingexpectedKeyError n_laps testfailure (34pass/1fail); copiedmatchinghook,testspassed35. Finala4fdac871c56hook15C6testspassed0.69s, frozenbeforedefinitiverehearsal. Workstream7broaderisolatedredteamsuite76pass/1expectedxfail/1freshnessfailure because copieddocsnewerthaninheritedC5map; finalmainclaimauditwillrefreshevidence afteralldocs. No freshnessgate relaxed.
