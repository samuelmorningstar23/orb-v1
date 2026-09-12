"""Replay one driver's race through the live slice and write the online-safe records.

    python live/replay_run.py --event Monza --driver NOR [--feedback app_v2/state/feedback_events.jsonl] [--no-feedback] [--out out/live]

Writes out/live/<event>_<driver>/: states.jsonl (one contract 7.1 LiveTyreState per lap), recommendations.jsonl (one line
per lap: {lap, issued_at, actions:[LiveRecommendation...]}), estimator_trace.jsonl (full posterior, widening, regime and
feedback log per lap), driver_feedback.json (contract 7.3 events consumed), live_predictor.json (a validated
LivePredictor block for the last lap, ready for Workstream 1 to promote), summary.json, and a .sha256 sidecar for each file
(shared.lockio.sha256_file; the format app_v2/services/asset_repository.py verifies). All records are validated against
schemas/lock_v2.py before they are written; the run aborts on the first invalid record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

PROTO = Path(__file__).resolve().parents[1]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from live import ESTIMATOR_LABEL, MODEL_VERSION                                    # noqa: E402
from live.feedback import DriverFeedbackAdapter                                    # noqa: E402
from live.session import LiveSession, LapResult                                    # noqa: E402
from schemas.lock_v2 import DriverFeedbackEvent, LivePredictor, LivePrior, LiveRecommendation, LiveTyreState, SCHEMA_VERSION  # noqa: E402
from shared.lockio import atomic_write_json, atomic_write_text, sha256_file        # noqa: E402

OUT_ROOT = PROTO / 'out' / 'live'


def git_sha() -> str:
    try:
        return subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, cwd=PROTO, timeout=5).stdout.strip() or '0000000'
    except Exception:
        return '0000000'


def model_hash() -> str:
    h = hashlib.sha256()
    for name in ('live/estimator.py', 'live/feedback.py', 'live/lapfeed.py', 'live/priors.py', 'decision/optimizer.py'):
        h.update((PROTO / name).read_bytes())
    return 'sha256:' + h.hexdigest()


def write_with_sidecar(path: Path, text: str) -> dict[str, Any]:
    atomic_write_text(path, text)
    digest = sha256_file(path)
    atomic_write_text(path.with_suffix(path.suffix + '.sha256'), f'{digest}  {path.name}\n')
    try:
        rel = path.relative_to(PROTO).as_posix()          # POSIX, relative to the lock root (proto/)
    except ValueError:
        rel = path.name                                    # written outside the lock root (tests): bare file name
    return dict(path=rel, sha256=digest, bytes=path.stat().st_size)


def live_predictor_block(session: LiveSession, results: list[LapResult], generated_at: str, git: str, mhash: str, state_ref: Optional[dict] = None) -> dict[str, Any]:
    last = results[-1]
    st = last.state
    pr = session.priors.prior_for(st.compound)
    plan = session.priors.plan
    prior = dict(forecast_hash=session.priors.forecast_hash or ('sha256:' + '0' * 64), event_id=session.priors.event_id, driver=session.driver, compound=st.compound, degradation_rate=pr.mean, band90=list(pr.band90),
                 useful_laps_q10=None, useful_laps_q50=None, useful_laps_q90=None, planned_plan=(plan.plan if plan else None),
                 planned_pit_window=([plan.pit_laps[0] - 2, plan.pit_laps[0] + 2] if plan and plan.pit_laps else None),
                 basis=f'pre-race forecast for {session.event} {st.compound} ({pr.basis}), frozen before the race; source {pr.source}')
    fb = [DriverFeedbackAdapter.to_schema_event(e, f'fb-{i + 1:04d}') for i, e in enumerate(f for r in results for f in r.feedback)]
    meta = dict(schema_version=SCHEMA_VERSION, generated_at=generated_at, data_cutoff=st.timestamp, git_sha=git, model_version=MODEL_VERSION, model_hash=mhash,
                provenance=f'live/replay_run.py: {ESTIMATOR_LABEL}; {session.event} {session.driver} replay through lap {st.lap} from feat/{session.event}_R.csv and the frozen forecast ({session.priors.source})')
    block = dict(meta=meta, event_id=session.priors.event_id, driver=session.driver, session='R', source='replay', data_cutoff=st.timestamp, lap=int(st.lap), n_laps=int(session.n_laps),
                 uses_future_data=False, uses_post_race_reference=False, feedback_enabled=bool(session.feedback_enabled), prior=prior, posterior=last.tyre_state,
                 recommendations=last.ranked.actions, driver_feedback=fb, state_history=state_ref, recommendation_history=None)
    return LivePredictor.model_validate(block).model_dump(mode='json', by_alias=True)


def run(event: str, driver: str, out_root: Path = OUT_ROOT, feedback_path: Optional[Path] = None, feedback_enabled: bool = True, quiet: bool = False) -> dict[str, Any]:
    session = LiveSession.open(event, driver, feedback_path=feedback_path, feedback_enabled=feedback_enabled)
    out_dir = out_root / f'{event}_{driver}'
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().isoformat(timespec='seconds')
    git, mhash = git_sha(), model_hash()
    states, recs, trace, results = [], [], [], []
    changes, regimes, widen_laps = [], {}, 0
    for res in session.run():
        LiveTyreState.model_validate(res.tyre_state)
        for a in res.ranked.actions:
            LiveRecommendation.model_validate(a)
        for f in res.feedback:
            DriverFeedbackEvent.model_validate(DriverFeedbackAdapter.to_schema_event(f))
        states.append(res.tyre_state)
        recs.append(dict(lap=res.lap, issued_at=res.ranked.issued_at, estimator=ESTIMATOR_LABEL, baseline=res.ranked.baseline, actions=res.ranked.actions))
        trace.append(res.state.as_trace())
        results.append(res)
        regimes[res.state.regime] = regimes.get(res.state.regime, 0) + 1
        widen_laps += 1 if res.state.widening else 0
        top = res.ranked.top
        if top and top['changed_since_last_update']:
            changes.append(dict(lap=res.lap, to=StrategyHeadline(top), reason=top['change_reason']))
        if not quiet:
            gain = f"gain {top['expected_gain_median']:+6.1f} p={top['probability_of_gain']:.2f}" if top else 'no action'
            print(f"lap {res.lap:>2} {res.state.compound:<6} age {res.state.tyre_age:>2} {res.state.regime:<17} slope {res.state.slope:+.4f} +- {res.state.slope_sd:.4f} | {StrategyHeadline(top):<32} {gain}" + ("  <- " + top['change_reason'][:80] if top and top['changed_since_last_update'] else ''))
    if not results:
        raise SystemExit(f'no laps for {driver} in {event}')
    files = {}
    files['states'] = write_with_sidecar(out_dir / 'states.jsonl', ''.join(json.dumps(s, ensure_ascii=False, allow_nan=False) + '\n' for s in states))
    files['recommendations'] = write_with_sidecar(out_dir / 'recommendations.jsonl', ''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in recs))
    files['estimator_trace'] = write_with_sidecar(out_dir / 'estimator_trace.jsonl', ''.join(json.dumps(t, ensure_ascii=False, allow_nan=False) + '\n' for t in trace))
    fb_events = [DriverFeedbackAdapter.to_schema_event(f, f'fb-{i + 1:04d}') for i, f in enumerate(x for r in results for x in r.feedback)]
    files['driver_feedback'] = write_with_sidecar(out_dir / 'driver_feedback.json', json.dumps(fb_events, indent=1, ensure_ascii=False) + '\n')
    state_ref = dict(path=files['states']['path'], sha256=files['states']['sha256'], bytes=files['states']['bytes'], format='jsonl', description='per-lap LiveTyreState records (online-safe)')
    block = live_predictor_block(session, results, generated_at, git, mhash, state_ref)
    files['live_predictor'] = write_with_sidecar(out_dir / 'live_predictor.json', json.dumps(block, indent=1, ensure_ascii=False) + '\n')
    last = results[-1]
    summary = dict(event=event, driver=driver, event_id=session.priors.event_id, n_laps=session.n_laps, laps_processed=len(results), first_lap=results[0].lap, last_lap=last.lap,
                   data_cutoff=last.state.timestamp, generated_at=generated_at, git_sha=git, model_version=MODEL_VERSION, model_hash=mhash, estimator=ESTIMATOR_LABEL,
                   forecast_hash=session.priors.forecast_hash, forecast_source=session.priors.source, feedback_enabled=session.feedback_enabled, feedback_events_consumed=len(fb_events),
                   uses_future_data=False, uses_post_race_reference=False, sensor_mode='PUBLIC PROXY', support_status=last.state.support_status,
                   stints=[dict(stint=s, compound=c, first_lap=fl, last_lap=ll, laps=n) for s, c, fl, ll, n in _stints(results)],
                   regime_laps=regimes, laps_with_widening=widen_laps, recommendation_changes=changes, n_recommendation_changes=len(changes),
                   final=dict(compound=last.state.compound, tyre_age=last.state.tyre_age, regime=last.state.regime, slope=last.state.slope, slope_sd=last.state.slope_sd, prior_slope=last.state.prior_slope,
                              trend_vs_pre_race=last.tyre_state['trend_vs_pre_race'], useful_laps=[last.tyre_state['useful_laps_q10'], last.tyre_state['useful_laps_q50'], last.tyre_state['useful_laps_q90']],
                              top_action=StrategyHeadline(last.ranked.top)),
                   files=files)
    summary_path = out_dir / 'summary.json'
    atomic_write_json(summary_path, summary)
    atomic_write_text(summary_path.with_suffix('.json.sha256'), f'{sha256_file(summary_path)}  summary.json\n')
    if not quiet:
        print(f'wrote {out_dir.relative_to(PROTO)}: {len(states)} states, {len(recs)} recommendation sets, {len(changes)} top-action changes, feedback events {len(fb_events)}')
    return summary


def StrategyHeadline(a: Optional[dict]) -> str:
    from decision.optimizer import StrategyOptimizer
    return StrategyOptimizer.headline(a)


def _stints(results: list[LapResult]):
    out = []
    for r in results:
        if out and out[-1][0] == r.state.stint:
            s, c, fl, ll, n = out[-1]
            out[-1] = (s, c, fl, r.lap, n + 1)
        else:
            out.append((r.state.stint, r.state.compound, r.lap, r.lap, 1))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--event', required=True)
    ap.add_argument('--driver', required=True, help='three-letter code, e.g. NOR; "ALL" runs every driver in the race file')
    ap.add_argument('--feedback', type=Path, default=None, help='feedback jsonl (default app_v2/state/feedback_events.jsonl)')
    ap.add_argument('--no-feedback', action='store_true', help='disable driver feedback (the result reverts to telemetry only)')
    ap.add_argument('--out', type=Path, default=OUT_ROOT)
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    if a.driver.upper() == 'ALL':
        from live.lapfeed import LapFeed
        for d in LapFeed(a.event).drivers:
            run(a.event, d, a.out, a.feedback, not a.no_feedback, quiet=True)
            print('done', a.event, d)
        return 0
    run(a.event, a.driver.upper(), a.out, a.feedback, not a.no_feedback, quiet=a.quiet)
    return 0


if __name__ == '__main__':
    sys.exit(main())
