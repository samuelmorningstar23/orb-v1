# Orb v1 premium shell: performance and release-gate record

Measured 12 Sep 2026 16:56 IST (C3, hero screens integrated end to end) with `tests/screenshots/capture.py`
(Playwright 1.62, headless Chromium 151) against `streamlit run app_v2/streamlit_app.py --server.port 8502 --server.headless true`
on the build laptop (macOS 25.5, Python 3.12, Streamlit 1.63, Plotly 7.0). Per-route table: `tests/screenshots/golden/report.json`.

| Acceptance area (13.6) | Target | Measured (C3) | Status |
|---|---|---|---|
| Cold load (navigation start to page marker, cached lock, CSV, Workstream 8 session, Workstream 2 tables, Workstream 4 assets) | < 2 s | worst 1021 ms (Live Predictor 1440x900, first Workstream 8 session build); typical 800-900 ms; Landing / offline / decision board 360-430 ms; 17 routes x 2 viewports | pass |
| Route switch via top navigation (assets cached) | < 600 ms | 132-157 ms (Landing -> Live Predictor 157/136 ms; Live -> Validation 132/155 ms) | pass |
| Live update without full-page flicker | fragment | the hero (KPI strip, chart, decision card, lower rail) is one `st.fragment(run_every=0.7 s)`; Workstream 8's session steps ~8 ms per lap; a 6 s replay run advanced Lap 5 -> 10 at 1x with 0 console errors | pass |
| Offline | no CDN / API / font | every non-localhost request aborted and logged: 0 attempted; the Race Twin player is a self-contained HTML document in an iframe | pass |
| Displays | 1440x900 and 1920x1080 | 34 golden PNGs at both sizes | pass |
| Layout | no horizontal scroll, no clipped labels | `scrollWidth <= innerWidth` on every route at both sizes | pass |
| Reliability | no console errors | 0 real console errors on 34 route loads and 2 replay runs. Streamlit's client probes `<path>/_stcore/host-config` and `/health` on a deep link and logs the 404 before falling back to root (64 probes); classified separately, never on in-app navigation. A "page not found" toast can appear on the very first deep link within ~5 s of a server start (cold-start race); it did not recur in the capture | pass (see notes) |
| Race Twin >= 30 FPS | React/canvas player | Workstream 4's player reports 114-121 FPS in the HUD at 1440x900 (their replay/PERF.md: 119-122 FPS); Plotly fallback on refused (Hungary) or missing (Australia, Madrid) assets | pass |
| Visual regression | goldens for all demo routes | 34 PNGs in `tests/screenshots/golden/`; `capture.py --compare` reports changed-pixel share; gate `pytest tests/screenshots` 8/8 | pass |
| Accessibility | keyboard, focus, non-colour cues | Tab reaches the top navigation and controls; `*:focus-visible` outline; compounds carry glyph letters, support chips carry glyphs and words; the player has its own keyboard map (space, arrows, PgUp/PgDn, 1/2/5/0) | pass (manual) |
| Failure modes | designed degraded states | NO LOCK, NO RACE FEED (Madrid), NO COMPLETED RACE TO AUDIT, POSITION FEED REFUSED (Hungary), POSITION DATA UNAVAILABLE (no maps), NO FRAMES FOR THIS SCENARIO, OUT OF SUPPORT (wet), pending panels when no full Workstream 2 scenario exists | pass |
| Presentation mode | one toggle | sidebar toggle or `?present=1`: hides sidebar and engineering panels, enlarges KPI values, decision headline and the player | pass |
| Determinism | same result every run | Workstream 8's session is stepped forward only and cached per (event, driver, feedback-log signature); Workstream 2's tables are hashed files; replay state and decision timeline are pure functions of the visible laps (tests) | pass |

Script-side cost (AppTest, no browser): `tests/ui` (41 tests, every page rendered at least twice, Workstream 8 sessions built for
Monza/NOR, Barcelona/PIA) runs in about 4.5 s; Workstream 8's first session build for a driver costs 140-320 ms, then ~8 ms per lap.

Re-run: `../.venv/bin/python tests/screenshots/capture.py --update` (goldens) or `--compare`, and
`../.venv/bin/python -m pytest tests/screenshots -q` for the gate (skips when the server is not up).
