# Race Twin geometry and player: performance and quality record

Measured 12 Sep 2026 16:25 IST on the build laptop (macOS 25.5, Python 3.12, numpy 2.5, scipy 1.18, Playwright headless
Chromium via the venv Workstream 6 installed) with `replay/perf_harness.py`.

## Player frame rate (acceptance 13.6: at least 30 FPS)

| Page | Frames | HTML | Ready | 1x | 2x | 5x | 10x | Console errors | External requests |
|---|---|---|---|---|---|---|---|---|---|
| Monza 2026, NOR, Workstream 2 scenario monza_nor_lap24_to_medium_new_tyre_only, 1440x900 | 4926 | 429 kB | 55 ms | 120 | – | – | 120 | 0 | 0 |
| Monza 2026, NOR, FIXTURE scenario, 1440x900 | 4937 | 433 kB | 57 ms | 119–120 FPS | 119–120 | 120–122 | 120 | 0 | 0 |
| Mini race fixture (ALP), 1440x900 | 689 | 77 kB | 35 ms | 120 | – | – | 119–120 | 0 | 0 |

FPS is `requestAnimationFrame` callbacks per second while playing, sampled once a second for 6 s per speed
(`window.__orbTwin.fps`, also `data-fps` on the root). Draw calls per second equal the callback rate (the canvas is
redrawn every frame while playing; when paused it redraws only on seek). Headless Chromium on this Mac runs rAF at the
120 Hz display rate, so the ceiling is 120; the venue laptop at 60 Hz would show 60. The per-frame cost is well below the
8 ms budget: one closed polyline (575 points), the pit lane, the halo segment, two blips and a HUD update throttled to
every 80 ms. Keyboard shortcuts verified in the same run (`arrow_right_2 = 2.0 s`, digits 5/0 -> 5x/10x, space
plays/pauses, PgUp -> lap 2, Home -> 0). No horizontal overflow at 1440 px.

Re-run: `../.venv/bin/python replay/perf_harness.py --event Monza --driver NOR --seconds 6 --speeds 1,2,5,10`
(or `--mini` for the fixture). The report is JSON on stdout (`--out file.json`).

## Geometry and trajectory quality (Monza 2026 race, FastF1 cache)

- Position-feed gate: 22 of 22 drivers pass (median 318–437 distinct points per lap, threshold 100).
- Canonical path: 575 grid points, step 10.001 m, L = 5750.6 m (official 5793 m, −0.7 %: the 10 m grid and the
  3-point circular smoother cut the two chicanes and Ascari slightly). Pooled-sample residual RMS 0.51 m, 98 % of
  samples within 5 m. Start/finish from 890 timing lap starts (median absolute deviation 3.9 m). Sectors from the
  sector-1 / sector-2 session times projected on the path.
- Pit lane: recorded from 9 normal stops (offpath threshold 4 m), 760 m between junctions, median transit 34.0 s.
- Trajectories: timing residual (S at the timing lap start minus (k−1)L) median 1.7–7.9 m per driver; the maxima
  (143–310 m) are lap 1 (the timing "Started" stamp comes a few seconds after lights-out, cars already 140–240 m past
  the line) and lap 4 (restart from the pit lane after the red flag). All other laps are within ±12 m.
- Red flag: the standstill (session 3773 s to 5545 s) is removed from the race clock; frames straddling it jump up to
  223 m (the cars rolled out of the pit lane before the "Started" stamp).
- Identity overlay (actual plan replayed as the counterfactual): max |S_cf − S_actual| = 0.11 m, max |gap| = 0.001 s
  over the whole race (ALB, two stops incl. the red-flag pit visit). Requirement: within one 1 Hz sample.
- Build time: 4.5 s for the whole event (22 trajectories, 4 Workstream 2 frame sets + 1 FIXTURE set with 64 whole-curve samples).
- Workstream 2 scenarios (out/counterfactual/, 16:26): finish deltas reproduced within 1 ms of the tables (NOR tyre_only −7.675 s,
  NOR fixed_context −5.737 s, VER lap20→hard −6.466 s, VER lap28→soft −37.457 s); no kappa warnings (their 22 s pit loss
  against the 34 s junction-to-junction recorded transit gives kappa ≈ 0.9).

Hungary 2026 race: refused. 21 of 22 drivers deliver 26 distinct points per lap (feed degraded at source); BOT is the only
clean feed (341/lap, retired mid-race). `out/maps/Hungary/meta.json` carries the reason; the dashboard shows the
POSITION DATA UNAVAILABLE state.

## Time-warp conventions

- `t_cf(S) = t_actual(S) + Delta(S)`, lap delta spread uniformly in lap-time fraction within the lap (a constant relative
  pace offset). Cumulative deltas are exact at every lap boundary and at the flag (tested).
- Future: tyre-demand-weighted spread — distribute each lap's delta in proportion to the per-sector tyre demand index
  (Workstream 2's `e_lat`/`e_long` split or the lock's sector weights) so the ghost loses more time in the high-load corners
  than on the straights. The frame contract does not change; only `ghost_curve` needs a sector-weighted profile.
- Counterfactual stop: the ghost leaves the path at the recorded entry junction, follows the driver's own recorded
  transit (time-shifted; the event median when the driver has no normal stop) and rejoins at the exit junction; the
  on-track time of the in/out lap pair is scaled by `kappa` so the pair's total equals Workstream 2's deltas exactly.
  `kappa` outside 0.6–1.6 is reported as a warning (the deltas do not carry a plausible pit loss).
- Quantiles: whole-curve samples when Workstream 2 provides them (per-frame 10th/90th percentile of ghost distance, 64 samples
  used at build time), else the q10/q90 lap-delta columns as two curves; ordering enforced, violations counted.

## Open items

- A bidirectional component (lap position back to Streamlit) is optional in the roadmap and not built; the player runs
  self-contained in its iframe. If Workstream 6 needs the scrubbed lap in `st.session_state`, a `streamlit-component-lib`
  build would be the next step.
- Sector boundaries at 10 m resolution; the halo is drawn along the path even while the ghost is in the pit lane.
