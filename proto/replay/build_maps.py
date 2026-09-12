"""Build proto/out/maps/<event>/ for a cached FastF1 race.

    python -m replay.build_maps --event Monza --year 2026 --cache ~/Trackshift/cache --frames-drivers NOR --intervention 23 --to HARD
    python -m replay.build_maps --event Hungary --year 2026 --cache ~/Trackshift/cache          # expected: refused, meta.json says why

Writes track.npz, pitlane.npz, <driver>.npz for every driver passing the quality gate, frames_<driver>_<scenario>.npz for
every Workstream 2 scenario directory under out/counterfactual/ that names the event (summary.json + laps.csv), plus a FIXTURE
scenario (labelled as such) for each --frames-drivers driver without one, and meta.json; every file has a sha256 sidecar.
Run from proto/.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

import numpy as np

PROTO = Path(__file__).resolve().parents[1]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from replay import io as rio                                   # noqa: E402
from replay import sources, geometry, trajectory, timewarp    # noqa: E402


def find_workstream2_scenarios(event: str, root: Path = PROTO / 'out' / 'counterfactual') -> list[dict]:
    """Workstream 2 scenario directories for this event: out/counterfactual/<scenario>/{summary.json, laps.csv[, lap_deltas.json]}.
    summary.json carries the lock-style scenario block (scenario_id, event_id, driver_id, actual_plan, counterfactual_plan,
    simulation_mode); laps.csv the per-lap table (lap, lap_delta, cumulative_delta, pit_state, cumulative_delta_q10/q90, ...)."""
    out = []
    if not root.exists():
        return out
    import pandas as pd
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        sm, lc = d / 'summary.json', d / 'laps.csv'
        if not (sm.exists() and lc.exists()):
            continue
        try:
            blk = json.loads(sm.read_text())
        except Exception:
            continue
        sc = blk.get('scenario', blk)
        ev = str(sc.get('event_id') or sc.get('event') or '')
        if event.lower() not in ev.lower() or 'actual_plan' not in sc or 'counterfactual_plan' not in sc:
            continue
        out.append(dict(scenario=sc, table=pd.read_csv(lc), dir=d, driver=str(sc.get('driver_id') or sc.get('driver') or '').upper(), scenario_id=str(sc.get('scenario_id') or d.name),
                        mode=str(sc.get('simulation_mode', ''))))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--event', required=True); ap.add_argument('--year', type=int, default=2026); ap.add_argument('--cache', required=True)
    ap.add_argument('--out', default=str(PROTO / 'out' / 'maps')); ap.add_argument('--drivers', default='ALL', help='comma list or ALL')
    ap.add_argument('--frames-drivers', default='', help='comma list of drivers to build FIXTURE/Workstream-2 frames for')
    ap.add_argument('--intervention', type=int, default=None, help='FIXTURE intervention lap (default: ~40 percent of the race)')
    ap.add_argument('--to', default='HARD', help='FIXTURE replacement compound')
    ap.add_argument('--max-samples', type=int, default=64)
    a = ap.parse_args(argv)
    t0 = time.time()
    out_dir = Path(a.out) / a.event
    src = sources.from_fastf1(a.year, a.event, a.cache)
    print(f'loaded {src.event_id}: {len(src.drivers)} drivers, {src.n_laps} laps, {time.time() - t0:.1f} s')
    try:
        track = geometry.build_track(src)
    except geometry.QualityRefusal as e:
        path = geometry.write_refusal(out_dir, e)
        print(f'REFUSED: {e.reason}\nwritten {path}')
        return 0
    pitlane = geometry.build_pitlane(src, track)
    track = geometry.attach_pit_flags(track, pitlane)
    h_track = track.save(out_dir); h_pit = pitlane.save(out_dir)
    print(f'track L={track.L:.1f} m, {track.n_points} pts, residual rms {track.meta["quality"]["residual_rms_m"]} m; pit lane {pitlane.source} {pitlane.length:.0f} m, transit {pitlane.transit_time:.1f} s ({pitlane.meta.get("n_stops", 0)} stops)')
    cuts = trajectory.race_clock_cuts(src)
    drivers = src.drivers if a.drivers.upper() == 'ALL' else [d.strip().upper() for d in a.drivers.split(',') if d.strip()]
    driver_meta = {}
    trajs = {}
    for d in drivers:
        try:
            tr = trajectory.build_trajectory(src, d, track, pitlane, cuts=cuts)
        except geometry.QualityRefusal as e:
            driver_meta[d] = dict(status='refused', reason=e.reason)
            print(f'  {d}: REFUSED {e.reason}')
            continue
        digest = tr.save(out_dir)
        trajs[d] = tr
        q = tr.quality
        driver_meta[d] = dict(status='ok', file=f'{d}.npz', sha256=digest, bytes=(out_dir / f'{d}.npz').stat().st_size, n_frames=q['n_frames'], median_distinct_per_lap=q['median_distinct_per_lap'],
                              timing_residual_median_abs_m=q['timing_residual_median_abs_m'], timing_residual_max_abs_m=q['timing_residual_max_abs_m'], n_stops=q['n_stops'],
                              stops=[dict(lap_in=s['lap_in'], duration=round(s['duration'], 1), normal=s['normal'], red_flag=s.get('red_flag', False)) for s in tr.stops], n_reprojected=q['n_reprojected'])
        print(f'  {d}: {q["n_frames"]} frames, {q["median_distinct_per_lap"]} pts/lap, timing resid med {q["timing_residual_median_abs_m"]} m max {q["timing_residual_max_abs_m"]} m, stops {[(s["lap_in"], round(s["duration"], 1)) for s in tr.stops]}')
    frames_meta = []
    scenarios = find_workstream2_scenarios(a.event)
    want = [x.strip().upper() for x in a.frames_drivers.split(',') if x.strip()]
    have_workstream2 = set()
    for sc in scenarios:
        d = sc['driver']
        if d not in trajs:
            print(f'  frames {d} {sc["scenario_id"]}: no trajectory'); continue
        tr = trajs[d]
        try:
            cf = timewarp.from_table(sc['table'], sc['scenario']['actual_plan'], sc['scenario']['counterfactual_plan'], scenario_id=sc['scenario_id'], source='workstream2',
                                     label=f"Workstream 2 {sc['mode']} scenario from out/counterfactual/{sc['dir'].name} (laps.csv, cumulative q10/q90)", n_laps=tr.n_laps)
        except Exception as e:                                   # a malformed table must not stop the build
            print(f'  frames {d} {sc["scenario_id"]}: cannot read Workstream 2 table ({e})'); continue
        have_workstream2.add(d)
        t1 = time.time()
        fr = timewarp.build_frames(tr, track, pitlane, cf, max_samples=a.max_samples)
        fpath = out_dir / f'frames_{d}_{cf.scenario_id}.npz'
        digest = fr.save(fpath)
        frames_meta.append(dict(driver=d, scenario_id=cf.scenario_id, source=cf.source, mode=sc['mode'], label=cf.label, file=fpath.name, sha256=digest, bytes=fpath.stat().st_size, n_frames=fr.n,
                                finish_delta_s=fr.meta['finish_delta_s'], table_cumulative_delta_s=fr.meta['cumulative_delta_table_s'], summary=sc['scenario'].get('summary'), quantile_source=fr.meta['quantile_source'],
                                warnings=fr.meta['warnings'], cf_pit_laps=fr.meta['cf_pit_laps'], actual_pit_laps=fr.meta['actual_pit_laps'], build_seconds=round(time.time() - t1, 2)))
        print(f'  frames {d} {cf.scenario_id} (workstream2 {sc["mode"]}): {fr.n} frames, finish delta {fr.meta["finish_delta_s"]} s (table {fr.meta["cumulative_delta_table_s"]}), {time.time() - t1:.1f} s, warnings {fr.meta["warnings"][:2]}')
    for d in want:
        if d not in trajs:
            print(f'  frames {d}: no trajectory'); continue
        if d in have_workstream2:
            continue
        tr = trajs[d]
        p = a.intervention or max(2, int(round(0.4 * tr.n_laps)))
        cf = timewarp.fixture_laps(tr, p, a.to)
        t1 = time.time()
        fr = timewarp.build_frames(tr, track, pitlane, cf, max_samples=a.max_samples)
        fpath = out_dir / f'frames_{d}_{cf.scenario_id}.npz'
        digest = fr.save(fpath)
        frames_meta.append(dict(driver=d, scenario_id=cf.scenario_id, source=cf.source, mode='fixture', label=cf.label, file=fpath.name, sha256=digest, bytes=fpath.stat().st_size, n_frames=fr.n,
                                finish_delta_s=fr.meta['finish_delta_s'], quantile_source=fr.meta['quantile_source'], warnings=fr.meta['warnings'], cf_pit_laps=fr.meta['cf_pit_laps'], actual_pit_laps=fr.meta['actual_pit_laps'],
                                build_seconds=round(time.time() - t1, 2)))
        print(f'  frames {d} {cf.scenario_id} (FIXTURE): {fr.n} frames, finish delta {fr.meta["finish_delta_s"]} s, {time.time() - t1:.1f} s, warnings {fr.meta["warnings"][:2]}')
    # identity check on the first trajectory (acceptance: actual-plan ghost overlays the driver)
    identity = None
    if trajs:
        d0 = next(iter(trajs)); tr = trajs[d0]
        fr = timewarp.build_frames(tr, track, pitlane, timewarp.identity_laps(tr))
        one_sample_m = float(np.diff(tr.S).max())     # the distance covered in one 1 Hz frame at the fastest point
        identity = dict(driver=d0, max_abs_distance_m=round(float(np.abs(fr['S_cf'] - fr['S_actual']).max()), 3), max_abs_time_s=round(float(np.abs(fr['time_delta_s']).max()), 3), one_sample_m=round(one_sample_m, 1),
                        within_one_sample=bool(np.abs(fr['S_cf'] - fr['S_actual']).max() <= one_sample_m and np.abs(fr['time_delta_s']).max() <= 1.0))
    meta = dict(track.meta, status='ok', pitlane=dict(source=pitlane.source, length_m=round(pitlane.length, 1), entry_s=round(pitlane.entry_s, 1), exit_s=round(pitlane.exit_s, 1), transit_s=round(pitlane.transit_time, 1), s_line=round(pitlane.s_line, 1), meta=pitlane.meta),
                race_clock_cuts_session_s=cuts, race_start_session_s=src.race_start(), drivers=driver_meta, frames=frames_meta, identity_check=identity,
                files=dict(track=dict(file='track.npz', sha256=h_track, bytes=(out_dir / 'track.npz').stat().st_size), pitlane=dict(file='pitlane.npz', sha256=h_pit, bytes=(out_dir / 'pitlane.npz').stat().st_size)),
                build=dict(generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'), seconds=round(time.time() - t0, 1), source=src.meta, tool='replay/build_maps.py'))
    rio.save_json(out_dir / 'meta.json', meta)
    total = sum(p.stat().st_size for p in out_dir.glob('*.npz'))
    print(f'wrote {out_dir} ({len(list(out_dir.glob("*.npz")))} npz, {total / 1e6:.2f} MB) in {time.time() - t0:.1f} s; identity {identity}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
