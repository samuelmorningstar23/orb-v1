# Orb v1 premium shell: performance and release-gate record

Measured 12 Sep 2026 21:38-21:46 IST (C4: Workstream 3 scorecards wired, sealed block revealed after the 21:37 freeze, pre-race
scenario in the explorer, red-team wording applied) with `tests/screenshots/capture.py` (Playwright 1.62, headless Chromium 151)
against `streamlit run app_v2/streamlit_app.py --server.port 8503 --server.headless true` on the build laptop (macOS 25.5,
Python 3.12, Streamlit 1.63, Plotly 7.0). Port 8503 was a verification instance with identical code; the lead's 8502 process
(started 16:54) does not reload edited modules and must be restarted to serve the C4 pages. Per-route table:
`tests/screenshots/golden/report.json`; scripted pass: `tests/screenshots/golden/scripted_pass.json`. C3 figures in brackets.

| Acceptance area (13.6 / 0.17) | Target | Measured (C4) | Status |
|---|---|---|---|
| Cold load (navigation start to page marker; cached lock, CSV, Workstream 8 session, Workstream 2 tables, Workstream 3 JSON, Workstream 4 assets) | < 2 s | worst 1103 ms (Live Predictor 1440x900, first Workstream 8 session build) [1021]; typical 860-950 ms; Landing 433-921 ms; 19 routes x 2 viewports | pass |
| Route switch via top navigation (assets cached) | < 600 ms | 148-246 ms (Landing -> Live Predictor 158-173 ms; Live -> Validation 151-245 ms) [132-157] | pass |
| Keyboard navigation across the top navigation | every route reachable, Enter activates | all 8 routes reached in 13 Tabs at both viewports; Enter on the focused link switches the route in 203-218 ms (marker attached) | pass |
| Live update without full-page flicker | fragment | hero is one `st.fragment(run_every=0.7 s)`; 6 s run advanced Lap 5 -> 10 at 1x with 0 console errors (both viewports) | pass |
| Scripted five-minute pass (0.17): Monza NOR replay lap 1 to the flag at 1x, then Ghost Strategy NOR lap 24 -> new MEDIUM, Validation, Generalisation via the top navigation | no console errors, no external requests | replay reached Lap 53/53 in 53.4 s (1 lap/s, samples every 5 s on schedule), page load 945 ms; Ghost switch 183 ms (player iframe present, audit banner, leave-one-driver-out reference, Workstream 3 hidden-stop/regret rows); Validation 164 ms (prefix eval, regret table); Generalisation 238 ms (sealed block, cells); 58.4 s of automation, about five minutes with the reading pauses; 0 console errors, 0 external requests, rejoin wording "not a position forecast" on screen | pass |
| Offline | no CDN / API / font | every non-localhost request aborted and logged: 0 attempted over 38 route loads + 2 replay runs + the scripted pass; Workstream 4's player is a self-contained iframe document; risk-coverage curve served from the local PNG | pass |
| Displays | 1440x900 and 1920x1080 | 38 golden PNGs (19 routes) at both sizes | pass |
| Layout | no horizontal scroll, no clipped labels | `scrollWidth <= innerWidth` on every route at both sizes | pass |
| Reliability | no console errors | 0 real console errors on 38 route loads, 2 replay runs and the scripted pass. Streamlit's client probes `<path>/_stcore/host-config` and `/health` on a deep link and logs the 404 before falling back to root (64 probes); classified separately, never on in-app navigation | pass |
| Degraded / out-of-support states | designed empty states | NO RACE FEED (Madrid), POSITION DATA UNAVAILABLE (Australia), POSITION FEED REFUSED (Hungary: 1 of 22 drivers pass the 100-points-per-lap gate, feed degraded at source), DEGRADED 7.1 quality on the Hungary live path (26 position samples per lap, band widened), OUT OF SUPPORT (wet scenario, no model-implied delta shown), NO COMPLETED RACE TO AUDIT (Madrid ghost), pending panels where no Workstream 2 scenario exists; each route's designed text is asserted by the gate (`expected_text_missing` empty on 19 routes) | pass |
| Presentation mode | one toggle, both hero routes | `?present=1` hides the sidebar (asserted: `sidebar_visible` false on presentation_live and presentation_ghost, true elsewhere) and engineering panels, enlarges KPI values, decision headline and the player | pass |
| Race Twin >= 30 FPS | React/canvas player | Workstream 4's player (114-121 FPS in the HUD at 1440x900, their replay/PERF.md 119-122); Plotly fallback on refused (Hungary) or missing (Australia, Madrid) assets | pass |
| Visual regression | goldens for all demo routes | 38 PNGs; goldens regenerated at C4 only for the 17 routes changed here plus the 2 new routes (prerace, offline_mode kept from C3: 1.5 % / 0.1 % drift from the 21:00 lock rebuild, within the 15 % gate); `capture.py --compare` diff share; gate `pytest tests/screenshots` 11/11 | pass |
| Accessibility | keyboard, focus, non-colour cues | keyboard pass above; `*:focus-visible` outline; compounds carry glyph letters, support chips carry glyphs and words; the player has its own keyboard map (space, arrows, PgUp/PgDn, 1/2/5/0) | pass |
| Determinism | same result every run | Workstream 8's session is stepped forward only and cached per (event, driver, feedback-log signature); Workstream 2 and Workstream 3 tables are hashed files read verbatim; the sealed block is revealed only by a `quotable: true` post-freeze evaluator run; replay state and decision timeline are pure functions of the visible laps (tests) | pass |
| Shared state | tests never write product state | the capture and the scripted pass no longer write `app_v2/state/feedback_events.jsonl` (Workstream 3's scorecards read it); a fixture log can be attached to a screenshot server with `ORB_FEEDBACK_LOG=<file>` (app_v2/services/paths.py; live/session.py still reads its own path) | pass |

Script-side cost (AppTest, no browser): `tests/ui` (51 tests, every page rendered at least twice, Workstream 8 sessions built for
Monza/NOR, Barcelona/PIA, Hungary/NOR) runs in about 7.5 s; Workstream 8's first session build for a driver costs 140-320 ms, then
~8 ms per lap; Workstream 3's five JSON files (about 540 kB) parse once per process and are cached by (path, mtime).

Re-run: `../.venv/bin/python tests/screenshots/capture.py --update [--routes a,b]` (goldens; a subset merges into report.json),
`--compare`, `--scripted [--speed 1|2|5|10]` (writes golden/scripted_pass.json), and `../.venv/bin/python -m pytest tests/screenshots -q`
for the gate (skips when the server is not up; `ORB_BASE` selects the server).

## C4 acceptance pass on the post-freeze data (12 Sep 22:00-22:30 IST, server restarted on 8502 at 22:09 and 22:20)

The goldens of 21:38-21:39 predate the lead's 21:49 `out/live` regeneration, the 21:52 second pre-race scenario and the 21:53
scorecards, so every route was re-measured against the data on disk now. `capture.py --compare` was run twice before any
rewrite: the two runs agreed to 3 decimals on every route (only `ghost_audit_fixed_context@1920x1080` moved, 0.000 % -> 0.001 %),
so the listed diffs are content, not rendering noise. Goldens were then rewritten for the 10 routes with a content cause and
for nothing else; after the rewrite every route compares at 0.000 % except the ghost-audit canvas (0.002-0.006 % jitter).

| route (both viewports) | diff vs golden before | content cause | golden rewritten | diff after |
|---|---|---|---|---|
| scenario_explorer | 0.665 % / 1.546 % | the fidelity control now selects the pre-race scenario and the rail names it | yes | 0.000 % |
| prerace | 1.454 % / 1.459 % | Madrid lock and frozen forecast of 21:33 (golden was from 16:56) | yes | 0.000 % |
| landing | 0.000 % / 0.267 % | sealed MAE at the quoted precision; 21:53 scorecard sha and timestamp | yes | 0.000 % |
| validation | 0.000 % / 0.179 % | identity table gained the two pre-race rows; 21:49 prefix-eval sha | yes | 0.000 % |
| offline_mode | 0.137 % / 0.087 % | Madrid forecast hash 66e3201e (golden was from 16:56) | yes | 0.000 % |
| presentation_ghost | 0.015 % / 0.184 % | audit rail lists both pre-race fidelities (`L24->M f, L24->M t`) | yes | 0.000 % |
| out_of_support | 0.000 % / 0.025 % | same rail line | yes | 0.000 % |
| ghost_audit | 0.016 % / 0.002 % | same rail line; Workstream 2 regeneration stamp 21:39 | yes | 0.006 % / 0.004 % (canvas jitter) |
| ghost_audit_fixed_context | 0.016 % / 0.000-0.001 % | same | yes | 0.002 % |
| generalisation | 0.008 % / 0.005 % | sealed block at the quoted precision (below the fold); 21:53 scorecard stamp | yes | 0.000 % |
| live_stable, live_after_feedback, decision_change, decision_board, presentation_live, feedback, missing_position, degraded_feed, position_refused | 0.000 % / 0.000 % | none: the live path computes in-process from the 21:33 lock, which did not move | **no** | 0.000 % |

19 of the 38 PNGs changed bytes (sha256 recorded before and after); the other 19 are byte-identical, `scripted_pass.json` was
re-run at 22:24 and `report.json` merged. `diff_ratio` counts pixels differing by more than 24 levels, so 0.000 % means no
visible pixel moved, not byte equality: `landing@1440x900` and `out_of_support@1440x900` reported 0.000 % yet their bytes
changed by a few antialiased pixels when rewritten.

Offline and reliability at both sizes after the rewrite: 0 external requests attempted over 38 route loads + 2 replay runs +
the scripted pass, 0 console errors, no horizontal overflow (`scrollWidth == innerWidth` on all 38), worst cold load 1103 ms,
route switches 145-163 ms. Race Twin on the Ghost route: player iframe present, 4926 frames for Monza/NOR from
`out/maps/Monza` (`assets_status` ok, 575 track points), 0 console errors at 1440x900 and 1920x1080.

New this pass: the Scenario Explorer's fidelity control picks between `out/counterfactual/pre_race/monza_nor_lap24_to_medium_new_fixed_context`
(-14.2 s) and `..._tyre_only` (-16.6 s) and states which one it is showing; the sealed-holdout MAE is printed at 4 decimals so
the dashboard and the lead's quotable headline read the same (0.0372 vs 0.1713 s/lap, 90 % coverage 100 %, 5 of 6 weekends,
9 compound-weekends); a Race Twin frame set whose finish delta disagrees with its scenario's `summary.json` by more than 1 s is
called out on the page (`monza_ver_lap20_to_hard_new_fixed_context`: frames -6.5 s, scenario +7.7 s — Workstream 4 must re-run
`replay.build_maps`). `tests/ui` is 56 tests (5 added) in about 9 s; `tests/ui` + `tests/screenshots` 67 in 101 s.


## C5 scorecard acceptance (12 Sep 2026)

Validation and Generalisation now share `ui/scorecard_evidence.py`: estimates, 90% weekend-bootstrap intervals, eligible metric denominators and independent-weekend counts come directly from Workstream 3 JSON. Generalisation retains expandable season/circuit/weather/driver cells. Rolling-origin rows identify the unavailable single-weekend interval; no zero-width interval is invented. Validation's duplicated legacy performance panels were removed after independent review found missing weekend intervals; the lock-agreement result and scenario identity/leakage audit remain. The sealed card shows only the approved aggregate MAEs, coverage and counts, with source intervals.

Final Workstream 3 input sync: ghost `8a83d6e8`, live `70c8e607`, SCORECARDS `7ff3ec51`, risk JSON `fbb73ad8`. The isolated Streamlit server was restarted on port 8506 after that sync. No feedback log was written and the main 8502 server was untouched.

`../.venv/bin/python -m pytest tests/ui -q -p no:cacheprovider`: 63 passed in 9.81 s after the final source and input sync. Seven new regression checks cover eligible n instead of bootstrap-record count, unavailable single-weekend intervals, no replacement of missing intervals with bare estimates, source-bound forecast/live bands, identical route evidence, and restriction of sealed extras.

`../.venv/bin/python tests/screenshots/capture.py --base http://localhost:8506 --compare --out /private/tmp/orb-c5-workstream6-captures-before`: all 19 routes at 1440x900 and 1920x1080; worst cold load 1051 ms; route switches 142-180 ms; zero console errors, zero external requests, no horizontal overflow. The compare mode writes its own temporary directory and ignores --out. Captures were inspected before golden updates.

| Route | Difference at 1440x900 | Difference at 1920x1080 | Content reason |
|---|---:|---:|---|
| landing | 0.002% | 0.109% | Regenerated scorecards and corrected prefix pooled metrics/provenance |
| generalisation | 7.664% | 9.187% | Shared uncertainty and denominator tables; limited sealed card |
| validation | 8.102% | 7.876% | Same scorecard tables replace unbanded legacy summaries |

Only these three routes' six PNGs are regenerated. Other routes remain unchanged; Ghost canvas jitter was at most 0.004%.

`../.venv/bin/python tests/screenshots/capture.py --base http://localhost:8506 --update --routes landing,generalisation,validation` regenerated those six PNGs. Its optional route-switch timing observed 606 ms once at 1920x1080 (600 ms budget); the golden update report retains that observation. No timing threshold was changed.

Final gate: `ORB_BASE=http://localhost:8506 ../.venv/bin/python -m pytest tests/screenshots -q -p no:cacheprovider` returned **11 passed in 92.07 s**, no skips. All 19 routes at both resolutions: worst cold load 985 ms; route switches 145-180 ms; zero errors, zero external requests, no overflow; maximum golden difference 0.00694% (Ghost canvas jitter). Raw final gate capture: `/private/tmp/orb-c5-workstream6-final-report.json`. This final full gate is separate from the preceding subset golden-update observation.

Initial development UI check returned 55 passed / 1 failed because a required separation label moved into a caption not collected by the legacy HTML assertion. The label was retained in the evidence HTML; subsequent runs returned 63 passed, including the final source/input run. The local server needed an approved sandbox escalation to bind port 8506; no main server was restarted.


## C6 release gate (13 Sep 2026)

The durable command is `../.venv/bin/python tests/screenshots/release_gate.py --base http://localhost:8502 --out /private/tmp/orb-c6-ui-final-capture --report tests/screenshots/c6_release_report.json`, run from `proto/`. It exits nonzero on an unavailable server, incomplete evidence, missing goldens or any failed gate; it never updates goldens. The report stores every check and the complete raw browser evidence.

The network monitor now checks the exact application origin for HTTP and WebSocket traffic, rejects prefix/credential/port tricks and remote WebSockets, and blocks service workers. It records each route's HTTP count, WebSocket URLs and external attempts. Browser-local data/blob resources are allowed; they do not contact a host. All external attempts would be aborted and fail the gate. Every route must also display its offline notice.

Keyboard coverage now activates all eight navigation destinations using actual Tab/Enter from a different route, at both resolutions. A focused-link record and measured transition accompany each activation. The existing 600 ms transition limit also applies to these keyboard transitions. Existing 2000 ms cold-load and 15% golden-pixel limits are unchanged. Refusal/degraded labels, presentation-mode sidebar behavior, replay polling, console errors, response errors and horizontal overflow are checked independently.

Initial filtered run (superseded; **not raw-zero acceptance**): **324/324 checks PASS**, 19 routes at 1440x900 and 1920x1080 (38 route/viewport cells); 4216 local HTTP requests and 38 app-origin WebSockets; zero external attempts or horizontal overflows, but 72 base-path HTTP 404s and their console errors were excluded by inherited capture filtering. This invalidated the zero-error claim and reopened C6. Worst cold load **948 ms**; click route transitions **217-296 ms**; all 16 keyboard activations **193-240 ms**. Largest golden difference **1.122%**, on Ghost audit fixed context at 1920x1080, below the existing 15% threshold. No product files or goldens changed for C6; the main 8502 server was never restarted by Workstream 6.

`../.venv/bin/python -m pytest tests/screenshots/test_release_gate.py -q -p no:cacheprovider` returned **18 passed in 0.03 s**. These tests cover origin-trick rejection, browser-local resources, missing matrix/golden/network evidence, refusal labels, exact timing boundaries, unavailable-dashboard failure reporting and all-destination keyboard activation. An earlier 322-check browser preflight also passed before the keyboard coverage was expanded; that report is preserved as `tests/screenshots/c6_release_report_initial_filtered.json`; it is historical failed acceptance evidence.

The initial browser was closed before handing main 8502 to the independent five-minute rehearsal. Source/runtime model boundaries and all frozen files remained untouched.

### Definitive C6 raw-error acceptance

The independent review found 72 HTTP 404 probes excluded from the initial report. The capture now bootstraps each case at the root URL with its query, then activates the actual application navigation link. This prevents the incorrect Streamlit deep base path. Console errors are never filtered; all HTTP statuses >=400 are retained. Global `raw_console_errors` and `raw_network_failures` arrays span routes, keyboard navigation and replay, and both must be empty. The legacy probe array also must be empty. Missing raw evidence fails closed.

`../.venv/bin/python tests/screenshots/release_gate.py --base http://localhost:8502 --out /private/tmp/orb-c6-ui-raw-zero-capture --report tests/screenshots/c6_release_report.json` returned **326/326 PASS**. All 38 route/viewport cells: **zero raw console errors, zero HTTP errors, zero probe 404s, zero external attempts**, no overflow. Recorded 4238 local HTTP requests and 38 app-origin WebSockets. Worst cold load **1192 ms**; click switches **211–272 ms**; all 16 keyboard activations **102–255 ms**. Maximum golden difference **1.142%**, below unchanged 15% threshold. Report SHA256: `8a6843409139310119b5ad0d94053b745275252d4f8f65722c1b8b040683ba85`.

`../.venv/bin/python -m pytest tests/screenshots/test_release_gate.py -q -p no:cacheprovider` returned **20 passed in 0.03 s**, including regressions that inject a probe 404, raw console/HTTP failures and absent raw evidence. No product or golden files changed; all contexts closed before releasing main 8502 to Workstream 3's definitive rehearsal. Workstream 3 independently reproduced lap 32→53 using browser-pumped waits, supporting a rehearsal transport-wait issue; this is Workstream 3's observation, not a product-test claim by this gate.
