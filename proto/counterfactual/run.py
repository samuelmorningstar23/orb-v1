"""CLI for the counterfactual engine (roadmap v5 task 0.4).

One scenario:
    python -m counterfactual.run --event Monza --driver NOR --lap 24 --to MEDIUM --set NEW --mode fixed_context [--continuation as_actual|one_stop|two_stop]
        [--replace-stop auto|none|K] [--curve race_reference|pre_race_forecast] [--no-standardised-pit] [--sc-factor 0.55|measured]
        [--samples 500] [--seed 2026] [--out DIR]
    -> <out>/<scenario_id>/laps.csv, summary.json, lap_deltas.json, ghost_replay.json (+ sha256 sidecar refs inside summary.json)

A lattice (driver x intervention lap x compound, summaries only, with timing):
    python -m counterfactual.run --event Monza --lattice [--mode fixed_context] [--drivers NOR,VER] [--laps 10,20,30] [--compounds MEDIUM,HARD]
    -> <out>/lattice_<event>_<mode>.csv and .json

Run from anywhere: proto/ is put on sys.path by the package. Default --out is proto/out/counterfactual/.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from counterfactual import PROTO
from counterfactual.engine import IDENTITY_TOL, CounterfactualEngine, ScenarioSpec, CounterfactualResult, LAP_COLUMNS, EXTRA_COLUMNS, FrozenFieldNotAvailable
from shared.lockio import atomic_write_json, sidecar_ref, strip_nonfinite

DEFAULT_OUT = PROTO / 'out' / 'counterfactual'


def _root_for(out_dir: Path) -> Path:
    """Sidecar paths are relative to the lock root (proto/); an output directory outside proto/ is its own root."""
    try:
        out_dir.resolve().relative_to(PROTO.resolve())
        return PROTO
    except ValueError:
        return out_dir



def _missing_laps(event: str, driver: str) -> list[int]:
    """Lap numbers absent from a driver's race record, the usual reason the actual plan cannot be reproduced exactly."""
    try:
        import pandas as pd
        d = pd.read_csv(PROTO / 'feat' / f'{event}_R.csv')
        laps = sorted(int(x) for x in d[d.Driver == driver].LapNumber.dropna().unique())
        return [n for n in range(laps[0], laps[-1] + 1) if n not in set(laps)] if laps else []
    except Exception:
        return []

def write_scenario(result: CounterfactualResult, out_dir: Path | str | None = None, root: Path | str | None = None) -> dict[str, Any]:
    """Write laps.csv, lap_deltas.json, ghost_replay.json and summary.json for one scenario; returns the summary dict."""
    base = Path(out_dir) if out_dir else DEFAULT_OUT
    d = base / result.scenario['scenario_id']
    d.mkdir(parents=True, exist_ok=True)
    root = Path(root) if root else _root_for(base)
    t = result.table
    cols = [c for c in LAP_COLUMNS + EXTRA_COLUMNS if c in t.columns]
    laps_path = d / 'laps.csv'
    t[cols].to_csv(laps_path, index=False, float_format='%.6f')
    n = len(t)
    lap_deltas = dict(scenario_id=result.scenario['scenario_id'], n=n, records=[dict(lap=int(l), delta_s=float(v)) for l, v in zip(t['lap'], t['lap_delta'])])
    ghost = dict(event_id=result.scenario['event_id'], driver=result.scenario['driver_id'], n=n, note='actual elapsed from the race file (missing rows inferred from session-time gaps); ghost = actual + mean counterfactual delta',
                 records=[dict(lap=int(l), actual_elapsed_s=float(a), ghost_elapsed_s=float(a + c), ghost_elapsed_q10_s=float(a + c10), ghost_elapsed_q90_s=float(a + c90))
                          for l, a, c, c10, c90 in zip(t['lap'], np.cumsum(t['actual_lap_time'].values), t['cumulative_delta'], t['cumulative_delta_q10'], t['cumulative_delta_q90'])])
    from shared.lockio import write_sidecar_json
    refs = {
        'laps': sidecar_ref(laps_path, root, format='csv', description='per-lap counterfactual table (mandatory columns first)'),
        'lap_deltas': write_sidecar_json(lap_deltas, d / 'lap_deltas.json', root, description='per-lap counterfactual minus actual lap time (s), model-implied, mean over sampled curves'),
        'ghost_replay': write_sidecar_json(ghost, d / 'ghost_replay.json', root, description='actual vs ghost elapsed time per lap for the Race Twin scrubber'),
    }
    scenario = dict(result.scenario)
    scenario['assets'] = refs
    summary = dict(scenario=scenario, engine=strip_nonfinite(result.engine), events=dict(actual=result.events_actual, counterfactual=result.events_cf),
                   sidecar_root=root.resolve().as_posix())
    atomic_write_json(d / 'summary.json', summary)
    summary['paths'] = dict(dir=d.as_posix(), laps=laps_path.as_posix(), summary=(d / 'summary.json').as_posix())
    return summary


def write_lattice(rows: pd.DataFrame, timing: dict[str, Any], event: str, mode: str, out_dir: Path | str | None = None) -> dict[str, Any]:
    base = Path(out_dir) if out_dir else DEFAULT_OUT
    base.mkdir(parents=True, exist_ok=True)
    root = _root_for(base)
    csv_path = base / f'lattice_{event}_{mode}.csv'
    rows.to_csv(csv_path, index=False, float_format='%.6f')
    meta = dict(timing=timing, csv=sidecar_ref(csv_path, root, format='csv', description='driver x intervention lap x compound summaries'))
    atomic_write_json(base / f'lattice_{event}_{mode}.json', meta)
    meta['paths'] = dict(csv=csv_path.as_posix(), json=(base / f'lattice_{event}_{mode}.json').as_posix())
    return meta


def _parse_list(s: Optional[str]) -> Optional[list[str]]:
    return [x.strip() for x in s.split(',') if x.strip()] if s else None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--event', required=True)
    p.add_argument('--driver')
    p.add_argument('--lap', type=int)
    p.add_argument('--to', dest='to_compound')
    p.add_argument('--set', dest='set_status', default='new', help='NEW | SCRUBBED | USED (start age 1 / 3 / 6 laps; --set-age overrides)')
    p.add_argument('--set-age', type=int, default=None)
    p.add_argument('--mode', default='fixed_context', choices=['tyre_only', 'fixed_context', 'frozen_field'])
    p.add_argument('--continuation', default='as_actual', choices=['as_actual', 'one_stop', 'two_stop'])
    p.add_argument('--replace-stop', default='auto', help="auto | none | 1-based index of the actual stop the intervention replaces")
    p.add_argument('--curve', default='race_reference', choices=['race_reference', 'pre_race_forecast'],
                   help="race_reference = the Historical Audit default (leave-one-driver-out Sunday reference); pre_race_forecast = the Scenario Explorer's only curve")
    p.add_argument('--no-standardised-pit', action='store_true', help="move the driver's own measured stop verbatim instead of the standardised event")
    p.add_argument('--include-target-driver', action='store_true', help='keep the target driver in the race reference fit (default: excluded)')
    p.add_argument('--sc-factor', default='0.55', help="fraction of the green transit loss paid under SC/VSC, or 'measured'")
    p.add_argument('--samples', type=int, default=500)
    p.add_argument('--seed', type=int, default=2026)
    p.add_argument('--out', default=None, help='output directory (default proto/out/counterfactual)')
    p.add_argument('--lattice', action='store_true')
    p.add_argument('--drivers', default=None, help='lattice: comma-separated driver codes (default all)')
    p.add_argument('--laps', default=None, help='lattice: comma-separated intervention laps (default every lap 2..n-1)')
    p.add_argument('--compounds', default=None, help='lattice: comma-separated compounds (default SOFT,MEDIUM,HARD)')
    p.add_argument('--allow-sealed', action='store_true', help='evaluator only: compile a sealed-holdout race')
    p.add_argument('--quiet', action='store_true')
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    sc_factor: float | str = 'measured' if args.sc_factor == 'measured' else float(args.sc_factor)
    engine = CounterfactualEngine(allow_sealed=args.allow_sealed)
    say = (lambda *a, **k: None) if args.quiet else print
    if args.lattice:
        if args.mode == 'frozen_field':
            print(FrozenFieldNotAvailable.__doc__ or 'frozen_field is not available', file=sys.stderr)
            return 2
        laps = [int(x) for x in _parse_list(args.laps)] if args.laps else None
        rows, timing = engine.lattice(args.event, mode=args.mode, drivers=_parse_list(args.drivers), laps=laps, compounds=_parse_list(args.compounds),
                                      set_status=args.set_status.lower(), continuation=args.continuation, curve_source=args.curve, n_samples=args.samples, seed=args.seed,
                                      sc_factor=sc_factor, standardised_pit_event=not args.no_standardised_pit, exclude_target_driver=not args.include_target_driver,
                                      replace_stop=args.replace_stop, set_age=args.set_age)
        meta = write_lattice(rows, timing, args.event, args.mode, args.out)
        say(f"lattice {args.event} {args.mode}: {timing['n_scenarios']} scenarios ({timing['n_errors']} skipped) in {timing['total_ms']:.0f} ms "
            f"(precompute {timing['precompute_ms']:.0f} ms, median {timing['per_scenario_ms_median']:.2f} ms, max {timing['per_scenario_ms_max']:.2f} ms per scenario)")
        say(f"wrote {meta['paths']['csv']}")
        if len(rows):
            ok = rows[rows['in_support'] & ~rows['free_stop']]
            say(f"{int(rows['in_support'].sum())} of {len(rows)} scenarios in support (stint lengths within what this race saw); {int(rows['free_stop'].sum())} are free red-flag changes")
            say('best in-support, non-free scenarios (model-implied; single-car, rivals on their observed trajectories):')
            best = ok.sort_values('elapsed_delta_median_s').head(5)
            say(best[['driver', 'lap', 'to_compound', 'plan', 'elapsed_delta_median_s', 'elapsed_delta_q10_s', 'elapsed_delta_q90_s', 'probability_of_gain']].to_string(index=False))
        return 0
    if not (args.driver and args.lap and args.to_compound):
        print('a scenario needs --driver, --lap and --to (or use --lattice)', file=sys.stderr)
        return 2
    try:
        spec = ScenarioSpec(args.event, args.driver.upper(), args.lap, args.to_compound, set_status=args.set_status, mode=args.mode, continuation=args.continuation,
                            replace_stop=args.replace_stop, curve_source=args.curve, standardised_pit_event=not args.no_standardised_pit,
                            exclude_target_driver=not args.include_target_driver, sc_factor=sc_factor, set_age=args.set_age, n_samples=args.samples, seed=args.seed)
    except FrozenFieldNotAvailable as e:
        print(f'not available: {e}', file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    result = engine.compile(spec)
    t_first = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    engine.compile(spec)
    t_second = (time.perf_counter() - t0) * 1000
    if result.scenario['validation']['identity_test'] == 'fail':
        # The identity property is the engine's own correctness guarantee: replaying the actual plan must cost exactly
        # nothing. A scenario that fails it would be displayed as a working simulation, so refuse to write it.
        delta = result.engine.get('identity_check_delta_s')
        gaps = _missing_laps(args.event, args.driver.upper())
        why = f"; the driver's race record is missing lap(s) {gaps}" if gaps else ''
        print(f"refused: {spec.scenario_id} fails the identity test (replaying the actual plan moves the clock by "
              f"{delta:+.4f} s, tolerance {IDENTITY_TOL}){why}. No scenario written.", file=sys.stderr)
        return 4
    summary = write_scenario(result, args.out)
    s = result.summary
    say(f"{spec.scenario_id}: {result.scenario['actual_plan']['label']} -> {result.scenario['counterfactual_plan']['label']} "
        f"(pit laps {result.scenario['counterfactual_plan']['pit_laps']}); elapsed delta median {s['elapsed_delta_median_s']:+.2f} s "
        f"[q10 {s['elapsed_delta_q10_s']:+.2f}, q90 {s['elapsed_delta_q90_s']:+.2f}], P(gain) {s['probability_of_gain']:.2f}; "
        f"tyre {result.engine['tyre_delta_mean_s']:+.2f} s, stops {result.engine['pit_delta_mean_s']:+.2f} s; "
        f"compile {t_first:.1f} ms first call (incl. race precompute), {t_second:.1f} ms warm")
    for w in result.scenario['warnings']:
        say(f'  warning: {w}')
    say(f"wrote {summary['paths']['dir']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
