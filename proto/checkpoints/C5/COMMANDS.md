# C5 command ledger

All Python commands run from the relevant checkout's `proto/` with `../.venv/bin/python`. Main checkout is `/Users/samuelmorningstar/Trackshift`; workstreams used isolated worktrees `/private/tmp/orb-c5-workstream{3,6,7}`. Only the lead integrated and committed.

## Build and focused verification (completed)

- `../.venv/bin/python -m evaluation.scorecards --quiet` — Workstream 3, exit 0; regenerated ghost/live/rolling-origin evidence.
- `../.venv/bin/python -m evaluation.risk_coverage --quiet` — Workstream 3, exit 0; 121 settings.
- `../.venv/bin/python -m pytest tests/evaluation -q` — Workstream 3, 65 passed.
- `../.venv/bin/python -m pytest tests/evaluation -q -p no:cacheprovider` — main, 65 passed in 3.27 s.
- `../.venv/bin/python -m pytest tests/ui -q -p no:cacheprovider` — Workstream 6, 63 passed.
- `ORB_BASE=http://localhost:8506 ../.venv/bin/python -m pytest tests/screenshots -q -p no:cacheprovider` — Workstream 6 final, 11 passed in 92.07 s, no skips; 19 routes × two viewports. Final raw report: independent_browser_acceptance.json.
- `../.venv/bin/python -m pytest tests/ui tests/evaluation -q -p no:cacheprovider` — main integration, 128 passed in 13.23 s.
- `../.venv/bin/python -m pytest tests/red_team/test_c5_audit_boundaries.py -q -p no:cacheprovider` — Workstream 7 final, 8 passed; tests real PDF extraction and fail-closed evidence boundaries.
- `../.venv/bin/python make_deck_figs.py --only push withheld strategy` then `../.venv/bin/python make_deck_figs.py --only strategy` — exit 0; only these figures rebuilt, no Madrid fit.
- `node deck_src/build_deck.js` — exit 0; 19 slides, 18 unused master content-type entries removed by builder.
- `../.venv/bin/python build_deck_v5.py` — exit 0; ten-slide ChallengeDay PDF.
- `../.venv/bin/python checkpoints/C5/review_tools/deck_refuter.py` — PASS, nine protected fingerprints, Q refresh provenance, four full hashes on both Madrid slides, all 20 proof-table cells, frozen numbers/labels/strategy.
- `../.venv/bin/python checkpoints/C5/review_tools/artifact_check.py` — PASS; lock 11/11, prefix 17/17, exact aggregate copy, risk 121×6, rolling 13 rounds/11 scored; reveal existence/size only.
- `../.venv/bin/python checkpoints/C5/review_tools/ui_refuter.py .` — PASS; 1,612 artifact mappings plus adversarial rounding/null-band/gate tests.
- `../.venv/bin/python evaluation/red_team/refute_c5_scorecards.py --source . --out evaluation/red_team/c5_scorecard_refutation.json` — PASS six independent checks, including 2,000-draw weekend bootstrap recomputation and temporal pool guards. Workstream 7 first ran the same script against Workstream 3's worktree; lead repeated against integrated main.
- `../.venv/bin/python inspect_presentation_package_integrity.py out/Orb_v1_Mentor_Briefing.pptx --fail-on-findings` — final PASS, zero findings.
- `../.venv/bin/python inspect_presentation_layout_geometry.py out/Orb_v1_Mentor_Briefing.pptx --expected-aspect 16:9 --expected-slide-count 19 --fail-on-findings` — final PASS, zero findings.
- `../.venv/bin/python build_control.py active-workstreams 3 6 7` — override set; completed C3 workstreams excluded from active-workstream gate.
- `../.venv/bin/python build_control.py summary` — regenerated previously stale summary.
- `../.venv/bin/python -m evaluation.red_team.consistency_probe` — main, 15 cases, 3,505 numbers, zero mismatches/load failures. 26 explicitly unhashed reproduced LIN values and ambiguous matches remain disclosed in report.

## Visual verification

Bundled headless LibreOffice command (no desktop application):

```sh
soffice -env:UserInstallation=file:///private/tmp/orb-c5-lo-profile --headless --convert-to pdf --outdir /private/tmp/orb-c5-decks out/Orb_v1_Mentor_Briefing.pptx
pdftoppm -f 15 -l 19 -scale-to 1000 -png /private/tmp/orb-c5-decks/Orb_v1_Mentor_Briefing.pdf /private/tmp/orb-c5-decks/last-mentor
```

Successful rendering; final changed slides inspected. The last methods-table correction was rerendered with `-f 15 -l 15` and output prefix `/private/tmp/orb-c5-decks/fixed-methods`. All ten ChallengeDay pages inspected via Poppler renders; chart labels corrected before final review. No final visible clipping found in changed slides. Fontconfig warnings did not prevent rendering.

## Development findings resolved before checkpoint

Initial claim audit failed because fitz was absent; extraction now uses installed pypdf, with failure-path tests. A generic PDF withheld sentence triggered the claim rule; builder wording corrected, no gate relaxed. An inherited 18-entry unused slide-master package defect failed initial package inspection; builder now removes only orphan overrides after checking relationships. Slide 5 and methods slide 15 clipping corrected in source, rebuilt and rendered. Earlier screenshot golden-update switch time 606 ms is preserved in that report; final full unchanged-threshold acceptance passed (145–180 ms). Shell `ps` was denied in sandbox, then succeeded under authorized escalation; no product check was bypassed.

Final audit/checkpoint commands and exact outcomes are in NOTES_B.md and the adjacent generated logs. No pipeline, refresh, forecast generation, sealed evaluator, or per-race reveal reader ran in this phase.

## Authorized correction after stopped audit

User explicitly requested correction and commit. Independent `counterfactual_repository.verify_assets` identified ghost_replay SHA-256 `685860b5ff60c9fccd17fb940d7665c5c76e1239ed6fa2712f82735d452a3b0a`, verified against summary. Its six-character display was incorrectly treated as a metric. Both Ghost asset lists now say `sha256` before the prefix; matcher thresholds are unchanged. The failed 68-case report is preserved in browser_consistency_failed_before_fix.json.

`../.venv/bin/python -m pytest tests/red_team/test_c5_audit_boundaries.py -q -p no:cacheprovider`: 9 passed in 0.81s after completing the new test stub's event/driver fields (initial stub raised AttributeError, repaired). The regression uses the real page formatter and requires an identically valued performance number to remain a mismatch. `git diff --check` found one trailing space in make_deck_figs.py, removed.

The first full rerun still saw stale labels in the already-running Streamlit process (same two failures). After verifying the listener command, the lead restarted only the dashboard on8502 using `../.venv/bin/streamlit run app_v2/streamlit_app.py --server.port 8502 --server.headless true --browser.gatherUsageStats false`; health returned200. Independent targeted `browser_consistency.run(routes=['acceptance/ghost_audit_fixed_context'], out='checkpoints/C5/fixed_route_probe.json')` then passed both resolutions:248 numbers,0mismatches,0load failures. Full rerun follows this restart. No numeric threshold or matcher was relaxed.

## Final C5 release results

Final browser68checks/15072numbers:0mismatches,0load failures. Claim audit exit0 and must_reword empty; leakage5/5; identity41/41; build_report --checkpoint C5 --rerun claims:GO10/10PASS. `PYTEST_ADDOPTS=-ra bash release/run_checkpoint.sh C5 AUTO "Scorecards with whole-weekend bands and n; 68 browser checks/15072 numbers/0 mismatches; independent refuters PASS; Madrid frozen; red team 10/10 PASS."`: allgreen,506passed/1knownskip/1expectedxfail in114.29s, screenshot tests executed; AUTOexit3pending. Exact subsequent GO command, status and limitations are inNOTES_B.md. Ownership5lead-only/0unowned; no check override. Protected and final tested source fingerprints unchanged.
