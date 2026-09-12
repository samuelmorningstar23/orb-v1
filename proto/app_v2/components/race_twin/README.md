# Race Twin player — integration notes for Workstream 6

Everything the player needs is a hashed asset under `proto/out/maps/<event>/` (built by `python -m replay.build_maps`,
run from `proto/`). Nothing here trains, calls a model or touches the network; the page embeds the frame arrays as JSON
inside a self-contained HTML document rendered through `streamlit.components.v1.html`.

## The call

```python
from app_v2.components.race_twin import race_twin_player, load_assets, assets_status, race_twin_animation
from app_v2.ui import empty_states

status = assets_status(ev)                      # {'status': 'ok' | 'refused' | 'missing', 'reason': ..., 'drivers': [...], 'frames': [...]}
if status['status'] != 'ok':
    empty_states.missing_position()            # or empty(status['reason']) — Hungary 2026 is 'refused': feed degraded at source
else:
    frames, track, pitlane = load_assets(ev, driver)            # first frames file of the driver; scenario_id=... to pick one
    if frames is None:
        ...  # trajectory exists but no frames were built for this driver: see "frames at runtime" below
    race_twin_player(frames, track, pitlane, height=520, presentation=ctx.presentation, autoplay=False, speed=1, start_t=0.0,
                     title=f'{vm.replacement.lower()} from lap {ilap}', show_fps=not ctx.presentation)
```

`race_twin_player(frames, track, pitlane, height=520, presentation=False, autoplay=False, speed=1, start_t=0.0, title=None,
show_fps=True, key=None)` renders an iframe of `height` px (canvas = height − 128 px of HUD and controls; 480–600 px works
in the centre column). `frames`, `track`, `pitlane` accept the replay dataclasses (`replay.timewarp.Frames`,
`replay.geometry.TrackPath` / `PitLane`), their dict exports, or paths. `player_html(...)` returns the HTML string if you
need it elsewhere (tests, static export). Because it is an iframe, `st.session_state` cannot drive it after render: pass
`start_t` / `autoplay` / `speed` when the page reruns (the URL/query-state lap can be turned into `start_t` with
`frames['t'][first index where lap_actual == lap]`). The player is self-contained: the Play/Pause, speed, lap scrubber,
time bar and keyboard live inside it, so the Streamlit fragment that steps `glap` every 0.6 s is not needed for this
component (keep it for the Plotly fallback only).

Keyboard (click the map first; the root has `tabindex=0` and a visible focus ring): `space` play/pause, `← →` 1 s
(`shift` 10 s), `PgUp/PgDn` one lap, `↑ ↓` speed, `1 2 5 0` = 1x 2x 5x 10x, `Home/End`. Non-colour cues: compound
badges carry the glyph letter and name, SC/VSC/red carry text chips, ghost vs actual carry `G` / `A` letters and a dashed
vs solid ring.

What the player shows: the canonical path (consensus of where the cars drove, 10 m grid), the pit lane (dotted; the HUD
says `recorded` or `schematic`), S/F and sector ticks, the actual car `A` (compound colour, white ring) and the ghost `G`
(compound colour, dashed ring) with a translucent 10–90 % halo along the path, gap readout in seconds (`+` = ghost behind)
and metres, LAP a/n and race clock, compound + age + lap badges for both cars, SC / VSC / red chips and shading (also as
bands on the time bar), pit-lane chips while either car is in the lane, an FPS readout (engineering; hidden in
presentation mode) and a `FIXTURE deltas` chip when the deltas are synthetic.

## Assets and provenance

```
out/maps/Monza/track.npz        s, x, y, sector, pit_entry_flag, pit_exit_flag, L, meta      (+ .sha256)
out/maps/Monza/pitlane.npz      s, x, y, entry_s, exit_s, length, s_line, transit_tau, transit_s, source
out/maps/Monza/<DRV>.npz        t (race clock, 1 Hz), t_session, S (unwrapped m), lap, in_pit, pit_progress, status, lap table, stops, quality
out/maps/Monza/frames_<DRV>_<scenario_id>.npz   the animation arrays (below) + meta
out/maps/Monza/meta.json        L, n_points, grid, quality (per-driver gate), pit lane, race-clock cuts, drivers, frames, identity check
out/maps/Hungary/meta.json      status 'refused' + reason (position feed degraded at source: 26 distinct points per lap)
```
Every file has a `<file>.sha256` sidecar in the same format `asset_repository.resolve` verifies (`sha256sum` style), so the
"race file <hash>" badge pattern applies: `assets_status(ev)['sidecar']` is the meta verification, `list_frames(ev)` gives
per-file sidecar status. Frame arrays (float32, 1 Hz): `t, t_session, S_actual, s_actual, lap_actual, lap_timing, S_cf,
s_cf_median, lap_cf, S_cf_q10, s_cf_q10, S_cf_q90, s_cf_q90, compound_actual, tyre_age_actual, compound_cf, tyre_age_cf,
time_delta_s, distance_delta_m, act_pit, act_pit_progress, cf_pit, cf_pit_progress, track_status`. Compound codes:
0 unknown, 1 soft, 2 medium, 3 hard, 4 intermediate, 5 wet. `q10/q90` name the elapsed-delta quantiles (Workstream 2's
convention, negative = faster), so `S_cf_q10 >= S_cf >= S_cf_q90` along the track. `meta.source` is `workstream2`, `FIXTURE`
or `identity`; `meta.label` says where the deltas came from; `meta.warnings` lists laps where the deltas do not carry a
plausible pit loss (`kappa`). Red-flag standstills are removed from the race clock (`meta.cuts_session_s`).

Currently built (12 Sep 16:45): Monza 2026, all 22 drivers (LEC retired lap 2; ALO/STR retired mid-race). Frames from
Workstream 2's `out/counterfactual/` scenarios (source `workstream2`, halo from the cumulative q10/q90 columns, finish deltas equal
to the tables within 1 ms): `NOR monza_nor_lap24_to_medium_new_tyre_only`, `NOR monza_nor_lap24_to_medium_new_fixed_context`,
`VER monza_ver_lap20_to_hard_new_fixed_context`, `VER monza_ver_lap28_to_soft_new_fixed_context`; plus `PIA` with a
**FIXTURE** scenario (stop on lap 23 to HARD, synthetic toy-model deltas) as the labelled placeholder pattern. Hungary
2026: refused (documented in its meta.json). Pick a scenario with `load_assets(ev, driver, scenario_id)`; `list_frames(ev)`
enumerates them and `assets_status(ev)['frames']` carries source, mode, label, finish delta and Workstream 2's summary.

## Frames at runtime (when Workstream 2's laps table is present)

```python
from replay.trajectory import DriverTrajectory
from replay.timewarp import from_table, build_frames
traj = DriverTrajectory.load(f'out/maps/{ev}/{driver}.npz')
cf = from_table(laps_table, scenario['actual_plan'], scenario['counterfactual_plan'], scenario_id=scenario['scenario_id'],
                source='workstream2', label='lock_v2 counterfactuals[i]', samples=None)     # laps_table: lap, lap_delta, cumulative_delta, pit_state (+ lap_delta_q10/q90)
frames = build_frames(traj, track, pitlane, cf)                                          # ~0.1 s with q10/q90 columns; +~1.5 s with 64 whole-curve samples
```
`from_table` also reads the fixture sidecar records (`delta_s`) and lock-style plans (`{stints: [{compound, laps}], pit_laps}`).
Cache the result with `st.cache_data` keyed on (event, driver, scenario_id, forecast_hash). `build_maps.py` picks up every
scenario directory under `out/counterfactual/` (`summary.json` with the scenario block + `laps.csv`) that names the event,
builds `frames_<DRV>_<scenario_id>.npz` labelled `workstream2`, and adds a FIXTURE only for `--frames-drivers` without one.
Re-run it after Workstream 2 regenerates scenarios: `../.venv/bin/python -m replay.build_maps --event Monza --year 2026 --cache ~/Trackshift/cache --frames-drivers PIA` (4-5 s).

## Fallback

`race_twin_animation(frames, track, pitlane, step_s=5, height=470, presentation=False)` animates the same frames with
Plotly frames (play 10x / pause / time slider); `race_twin_map(...)` keeps its original signature and gains optional
`track=` / `pitlane=` so the lap-scrubbed fallback draws the canonical path instead of the synthetic loop. Use the
fallback when `components.html` is unavailable or on the `missing_position` route.

## Performance and tests

`replay/PERF.md`: 119–122 FPS at 1x–10x in headless Chromium (1440x900), ready in ~60 ms, 433 kB HTML for a 4937-frame
race, 0 console errors, 0 external requests, no horizontal overflow. `pytest tests/replay -q` (30 tests): path closure and
monotonic arc length, projection round trip, identity overlay within one sample, pit-lane switch once per stop, frames
finite and ordered, quality refusal on a degraded feed, sidecars, headless player run, built-asset checks.
