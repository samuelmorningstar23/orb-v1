# Orb v1 premium shell: performance and release-gate record

Measured 12 Sep 2026 15:32 IST with `tests/screenshots/capture.py` (Playwright 1.62, headless Chromium 151) against
`streamlit run app_v2/streamlit_app.py --server.port 8502 --server.headless true` on the build laptop (macOS 25.5, Python 3.12,
Streamlit 1.63, Plotly 7.0). The full per-route table is in `tests/screenshots/golden/report.json`.

| Acceptance area (13.6) | Target | Measured | Status |
|---|---|---|---|
| Cold load (navigation start to page marker, cached lock and CSV) | < 2 s | worst 931 ms over 16 routes x 2 viewports; typical 680-900 ms; Landing 350-430 ms | pass |
| Route switch via top navigation (assets cached) | < 600 ms | 130-192 ms (Landing -> Live Predictor 191/192 ms; Live -> Validation 135/130 ms) | pass |
| Live update without full-page flicker | fragment | KPI strip, chart, decision card and lower rail live in one `st.fragment(run_every=0.7 s)`; a 6 s replay run advanced Lap 5 -> 10 at 1x with 0 console errors | pass |
| Offline | no CDN / API / font | every non-localhost request aborted and logged: 0 attempted; Inter not installed so the system stack renders | pass |
| Displays | 1440x900 and 1920x1080 | golden set captured at both | pass |
| Layout | no horizontal scroll, no clipped labels | `scrollWidth <= innerWidth` on every route at both sizes; labels re-checked after the polish pass | pass |
| Reliability | no console errors | 0 real console errors on 32 route loads and 2 replay runs. Streamlit's client probes `<path>/_stcore/host-config` and `<path>/_stcore/health` on a deep link and logs the 404 before falling back to root (60 such probes); they are classified separately and do not occur on in-app navigation | pass (see note) |
| Visual regression | goldens for all demo routes | 32 PNGs in `tests/screenshots/golden/`; `capture.py --compare` reports changed-pixel share | pass |
| Accessibility | keyboard, focus, non-colour cues | Tab reaches the top navigation and controls; `*:focus-visible` outline from base.css; compounds carry glyph letters, support chips carry glyphs and words | pass (manual) |
| Failure modes | designed degraded states | NO LOCK, NO RACE FEED (Madrid), NO COMPLETED RACE TO AUDIT, POSITION DATA UNAVAILABLE, OUT OF SUPPORT (wet scenario), pending-workstream states | pass |
| Presentation mode | one toggle | sidebar toggle or `?present=1`: hides sidebar and engineering panels, enlarges KPI values and the decision headline | pass |
| Determinism | same result every run | replay state and decision timeline are pure functions of the visible laps (`tests/ui/test_pages.py::test_replay_state_is_deterministic`, `::test_decision_timeline_is_pure`) | pass |
| Race Twin >= 30 FPS | React player | pending Workstream 4; the Plotly fallback redraws per lap step (0.6 s at 1x) | pending |

Script-side cost (AppTest, no browser): the whole `tests/ui` suite (34 tests, every page rendered twice) runs in about 3.7 s,
so a page render is well under 200 ms; the lock (`st.cache_data`) and race CSV loads are cached per process.

Re-run: `../.venv/bin/python tests/screenshots/capture.py --update` (goldens) or `--compare`, and
`../.venv/bin/python -m pytest tests/screenshots -q` for the gate (skips when the server is not up).
