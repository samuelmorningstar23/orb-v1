"""View-model adapter for Workstream 6's dashboard (app_v2/services/view_models.py::build_live).

    build_live(lock, event, driver, cursor, latency_text='—') -> dict      keys of VM.LiveVM + 'orb_live'
    build_live_vm(lock, event, driver, cursor, latency_text='—') -> VM.LiveVM   instance, with `.orb_live` attached

Same signature as VM.build_live, so the wiring on Workstream 6's side is one line in app_v2/pages/live_predictor.py and
decision_board.py:  `vm = VM.build_live(...)`  ->  `vm = live_viewmodel.build_live_vm(...)`.

Key mapping (LiveVM field <- source):
    event, driver, lap, n_laps        <- cursor (Workstream 6 ReplayCursor: lap, n_laps, asset)
    state    RS.StintState            <- live posterior: post_slope = slope, post_sd = slope sd, fitted_intercept = anchor,
                                         ages/losses = kept laps (y - intercept), all_* = every lap of the stint, widened /
                                         widen_reason = this lap's widening rules, trend_vs_prior = slope / prior,
                                         events_in_stint from the feed rows <= k, estimator_label = the Phase 0 label
    prior    RS.Prior                 <- live/priors (lock_v2 pre_race_forecast; never a race outcome)
    forecast Forecast                 <- lock.forecast_for (Workstream 6 object, unchanged)
    corrections RS.Corrections        <- VM.corrections_for (lock rules)
    decision DS.Decision              <- top ranked action (0.12): action PIT | STAY OUT, pit_lap = window start,
                                         expected_gain_s = median, downside_q10_s = q10, probability_of_gain, rejoin text,
                                         reasons, alternatives = the other ranked actions, change_reason, rule_label
    history  list[DS.Decision]        <- laps on which the top action changed (no recommendation changes silently)
    kpis     list[VM.KPI]             <- LIVE DEGRADATION, USEFUL LIFE, CLIFF RISK, PIT WINDOW, RECOMMENDED TYRE (real values)
    comparable, feed, feedback, temp_history_lock, temp_series, crossover, plan, support, asset  <- Workstream 6 services (online-safe)
    fixture_reco = None, fixture_label = 'live/estimator + decision/optimizer', evolution_applied = False
    orb_live (namespaced, new)        <- tyre_state (7.1 record), recommendations (7.2 records), regime, regime_probs,
                                         estimator_label, widening, changes, feedback_log (telemetry support), projection,
                                         live_crossover, prior, useful life and cliff numbers, data_cutoff
The adapter reads Workstream 6's modules; it never writes to app_v2/.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from live import ESTIMATOR_LABEL
from live.session import FEEDBACK_LOG, LapResult, LiveSession, read_feedback
from decision.optimizer import StrategyOptimizer

PROTO = Path(__file__).resolve().parents[1]
LETTER = {'SOFT': 'S', 'MEDIUM': 'M', 'HARD': 'H', 'INTERMEDIATE': 'I', 'WET': 'W'}
RULE_LABEL = f'{ESTIMATOR_LABEL} (live/estimator.py); ranked actions from decision/optimizer.py re-run from the current lap; gains vs the pre-race plan'
_cache: dict[tuple, 'SessionCache'] = {}


@dataclass
class SessionCache:
    session: LiveSession
    results: list[LapResult]
    signature: tuple


def _feedback_signature(event: str, driver: str) -> tuple:
    try:
        st = os.stat(FEEDBACK_LOG)
        return (event, driver, st.st_mtime_ns, st.st_size)
    except OSError:
        return (event, driver, 0, 0)


def results_through(event: str, driver: str, lap: int, feedback_enabled: bool = True) -> tuple[LiveSession, list[LapResult]]:
    """Lap results through `lap`, stepping the cached session forward (never backward: earlier laps are already there)."""
    sig = _feedback_signature(event, driver) + (feedback_enabled,)
    c = _cache.get((event, driver, feedback_enabled))
    if c is None or c.signature != sig:
        c = SessionCache(LiveSession.open(event, driver, feedback_enabled=feedback_enabled), [], sig)
        _cache[(event, driver, feedback_enabled)] = c
    done = c.results[-1].lap if c.results else None
    if done is None or done < lap:
        state = c.results[-1].state if c.results else None
        prev = c.results[-1].ranked if c.results else None
        for k in c.session.laps():
            if (done is not None and k <= done) or k > lap:
                continue
            res = c.session.step(state, k, prev)
            if res is None:
                continue
            c.results.append(res)
            state, prev = res.state, res.ranked
    return c.session, [r for r in c.results if r.lap <= lap]


def _ols(x: np.ndarray, y: np.ndarray) -> tuple[Optional[float], Optional[float]]:
    if len(x) < 3:
        return None, None
    xm, ym = x.mean(), y.mean()
    sxx = ((x - xm) ** 2).sum()
    if sxx <= 0:
        return None, None
    b = ((x - xm) * (y - ym)).sum() / sxx
    r = y - (ym - b * xm + b * x)
    s2 = (r ** 2).sum() / max(len(x) - 2, 1)
    return float(b), float(math.sqrt(s2 / sxx)) if s2 > 0 else 1e-4


def _stint_state(RS, session: LiveSession, res: LapResult):
    st = res.state
    a = st.intercept
    kept = st.kept
    ages = [float(r.age) for r in kept]
    losses = [float(r.y - a) for r in kept] if a is not None else []
    all_ages = [float(r.age) for r in st.laps]
    all_losses = [float(r.y - a) if (a is not None and math.isfinite(r.y)) else float('nan') for r in st.laps]
    all_kept = [bool(r.kept) for r in st.laps]
    b, se = _ols(np.array(ages), np.array(losses)) if losses else (None, None)
    rows = session.feed.through(session.driver, res.lap)
    rows = rows[rows['Stint'] == st.stint]
    events = []
    for _, r in rows.iterrows():
        if bool(r['pit_out']):
            events.append(dict(lap=int(r['LapNumber']), kind='pit_exit', detail=f"new {str(r['Compound']).lower()}"))
        if bool(r['pit_in']):
            events.append(dict(lap=int(r['LapNumber']), kind='pit_entry', detail='box'))
        if str(r['TrackStatus']) != '1':
            events.append(dict(lap=int(r['LapNumber']), kind='track_status', detail=f"status {r['TrackStatus']}"))
    widen_reason = ', '.join(f'{w.rule} x{w.applied:.2f}' for w in st.widening)
    d = st.derived
    label = f"{ESTIMATOR_LABEL}: posterior slope {st.slope:+.4f} +- {st.slope_sd:.4f} s/lap per lap from {st.n_obs} clean laps; regime {st.regime}"
    return RS.StintState(lap=res.lap, stint=st.stint, compound=st.compound, tyre_age=st.tyre_age, laps_in_stint=len(st.laps), kept_laps=st.n_obs, ages=ages, losses=losses,
                         all_ages=all_ages, all_losses=all_losses, all_kept=all_kept, fitted_intercept=a, ols_slope=b, ols_se=se, post_slope=st.slope, post_sd=st.slope_sd,
                         widened=bool(st.widening), widen_reason=widen_reason, trend_vs_prior=(st.slope / st.prior_slope if abs(st.prior_slope) > 1e-6 else None),
                         pace_loss_now=float(d.get('corrected_pace_loss', 0.0)), events_in_stint=events, estimator_label=label)


def _alternative(a: dict, current: str, k: int, n_laps: int, top_gain: float) -> dict:
    letters = [LETTER.get(current, current[0])]
    stints, prev = [], k
    w = a.get('pit_window')
    if a['action'] != 'STAY_OUT' and w:
        letters.append(LETTER.get(a['target_compound'], '?'))
        stints.append(int(w[0]))
        prev = int(w[0])
        second = next((r for r in a.get('reasons', []) if r.startswith('second stop lap')), None)
        if second:
            j2 = int(second.split('lap ')[1].split(' ')[0])
            letters.append(LETTER.get(second.split('new ')[-1].upper(), '?'))
            stints.append(j2 - prev)
            prev = j2
    stints.append(n_laps - prev)
    return dict(plan='-'.join(letters), stints=stints, stops=len(stints) - 1, delta_to_best_s=max(0.0, top_gain - float(a['expected_gain_median'])),
                action=a['action'], pit_window=w, target_compound=a.get('target_compound'), expected_gain_median=a['expected_gain_median'], expected_gain_q10=a['expected_gain_q10'],
                expected_gain_q90=a['expected_gain_q90'], probability_of_gain=a['probability_of_gain'])


def _status(res: LapResult) -> str:
    st = res.state
    lo, hi = float(st.prior['band90'][0]), float(st.prior['band90'][1])
    if st.feedback_this_lap:
        return 'DRIVER REPORT'
    if st.regime in ('CLIFF', 'ANOMALY', 'OVERHEATING', 'GRAINING'):
        return f'REGIME {st.regime}'
    if st.n_obs >= 1 and st.slope > hi:
        return 'ABOVE FORECAST BAND'
    if st.n_obs >= 1 and st.slope < lo:
        return 'BELOW FORECAST BAND'
    return 'HOLD PLAN'


def _decision(DS, lock, event: str, res: LapResult, n_laps: int):
    top = res.ranked.top
    st = res.state
    plan = lock.primary_plan(event)
    if top is None:
        return DS.Decision(res.lap, 'NO PLAN', 'NO PLAN', None, None, plan.plan if plan else None, 'decision/optimizer.py', None, None, None, None, 'not available', ['no legal action'], [], '', False, (None, None), RULE_LABEL)
    action = 'STAY OUT' if top['action'] == 'STAY_OUT' else 'PIT'
    w = top.get('pit_window')
    rj = top['rejoin_context']
    # Red team wording rule live_position_claim: outside frozen-field mode a projected rejoin P-number is a position
    # claim the model cannot support, so the live path states the observed gap structure only (same rule as
    # app_v2/services/live_bridge.rejoin_text). projected_rejoin_position stays in the 7.2 record, rendered only in frozen_field mode.
    rejoin = (f"P{rj['position_now']} now, gap ahead {_gap_s(rj.get('gap_ahead_s'))}, behind {_gap_s(rj.get('gap_behind_s'))}, "   # observed position; no projected P outside frozen_field mode
              f"{rj['cars_within_pit_loss']} cars within pit loss, traffic {rj['traffic_density']} · {NOT_POSITION_FORECAST}"
              if rj.get('position_now') is not None else rj.get('note', 'not available'))
    alts = [_alternative(a, st.compound, res.lap, n_laps, float(top['expected_gain_median'])) for a in res.ranked.actions[1:4]]
    d = DS.Decision(res.lap, action, _status(res), int(w[0]) if w else None, top.get('target_compound'), plan.plan if plan else None, 'decision/optimizer.py (live posterior + lock offsets, pit loss, forecast slopes)',
                    float(top['expected_gain_median']), 'pre-race plan remaining schedule', float(top['probability_of_gain']), float(top['expected_gain_q10']), rejoin, list(top['reasons']), alts,
                    top.get('change_reason') or '', bool(top['changed_since_last_update']), (None, None), RULE_LABEL)
    return d


def _kpis(VM, res: LapResult):
    st, ts, top = res.state, res.tyre_state, res.ranked.top
    try:
        from app_v2.theme.tokens import fmt
        spl = lambda v: fmt(v, 'seconds_per_lap')
    except Exception:
        spl = lambda v: f'{v:+.3f}'
    pct = ts['trend_vs_pre_race'] * 100
    tone = 'critical' if st.regime in ('CLIFF', 'ACCELERATING_WEAR', 'ANOMALY') else ('live' if st.n_obs >= 3 else 'neutral')
    deg = VM.KPI('LIVE DEGRADATION', spl(st.slope), f'{pct:+.0f}% vs forecast {spl(st.prior_slope)} · {st.n_obs} clean laps · {st.regime.lower().replace("_", " ")}', tone, 'live/estimator', 's/lap')
    useful = VM.KPI('USEFUL LIFE', f"{ts['useful_laps_q50']:.0f} laps", f"q10 {ts['useful_laps_q10']:.0f} · q90 {ts['useful_laps_q90']:.0f} · crossover to {st.derived.get('useful_life_alternative') or 'none (laps remaining)'}", 'live', 'live/estimator', 'laps')
    p3 = ts['cliff_probability_3_laps']
    cliff = VM.KPI('CLIFF RISK', f'{p3:.0%}', f"within 3 laps · {ts['cliff_probability_5_laps']:.0%} within 5 · regime {st.regime.lower().replace('_', ' ')}", 'critical' if p3 >= 0.3 else 'neutral', 'live/estimator')
    if top is None:
        pit = VM.KPI('PIT WINDOW', '—', 'no legal action', 'neutral', 'decision/optimizer')
        tyre = VM.KPI('RECOMMENDED TYRE', '—', '', 'neutral', 'decision/optimizer')
    elif top['action'] == 'STAY_OUT':
        pit = VM.KPI('PIT WINDOW', 'no stop', f"stay out · gain vs plan {top['expected_gain_median']:+.1f} s (q10 {top['expected_gain_q10']:+.1f})", 'decision' if top['changed_since_last_update'] else 'neutral', 'decision/optimizer')
        tyre = VM.KPI('RECOMMENDED TYRE', '—', 'no further stop', 'neutral', 'decision/optimizer')
    else:
        w = top['pit_window']
        pit = VM.KPI('PIT WINDOW', f'lap {w[0]}' if w[0] == w[1] else f'laps {w[0]}-{w[1]}', f"{top['action'].replace('_', ' ').lower()} · gain {top['expected_gain_median']:+.1f} s (q10 {top['expected_gain_q10']:+.1f})", 'decision' if top['changed_since_last_update'] else 'live', 'decision/optimizer')
        tyre = VM.KPI('RECOMMENDED TYRE', f"new {top['target_compound'].lower()}", f"probability of gain {top['probability_of_gain']:.0%}", 'live', 'decision/optimizer')
    return [deg, useful, cliff, pit, tyre]


NOT_POSITION_FORECAST = 'observed gap structure, not a position forecast'   # red-team wording rule live_position_claim


def _gap_s(v) -> str:
    return '—' if v is None else f'{float(v):.1f} s'


def build_live(lock, event: str, driver: str, cursor, latency_text: str = '—') -> dict[str, Any]:
    """Dict with exactly the keys of app_v2.services.view_models.LiveVM plus 'orb_live'."""
    from app_v2.services import view_models as VM
    from app_v2.services import replay_service as RS
    from app_v2.services import feedback_service as FS
    from app_v2.services import decision_service as DS
    from app_v2.services import support_service as SS
    lap = int(cursor.lap)
    session, results = results_through(event, driver, lap)
    res = results[-1] if results else None
    corr = VM.corrections_for(lock, event)
    row = cursor.lap_row()
    compound = res.state.compound if res else (str(row['Compound']) if row is not None else (lock.compounds_for(event) or ['MEDIUM'])[0])
    pr = session.priors.prior_for(compound) if session.priors.has(compound) else None
    prior = RS.Prior(compound, pr.mean if pr else None, tuple(pr.band90) if pr else (None, None), f'{pr.source}' if pr else 'none')
    forecast = lock.forecast_for(event, compound)
    state = _stint_state(RS, session, res) if res else None
    decision = _decision(DS, lock, event, res, session.n_laps) if res else DS.Decision(lap, 'NO PLAN', 'NO PLAN', None, None, None, 'none', None, None, None, None, 'not available', ['no laps yet'], [], '', False, (None, None), RULE_LABEL)
    history = [_decision(DS, lock, event, r, session.n_laps) for r in results if r.ranked.top and (r.ranked.top['changed_since_last_update'] or r is results[0])]
    plan = lock.primary_plan(event)
    support = SS.support_for(lock, event, driver, compound)
    feedback = FS.for_session(event, driver, through_lap=lap)
    kpis = _kpis(VM, res) if res else []
    orb = None
    if res:
        st = res.state
        orb = dict(tyre_state=res.tyre_state, recommendations=res.ranked.actions, baseline=res.ranked.baseline, regime=st.regime, regime_probs=st.regime_probs, estimator_label=ESTIMATOR_LABEL,
                   model_version=st.model_version, widening=[dict(lap=w.lap, rule=w.rule, factor=w.factor, applied=w.applied) for w in st.widening], changes=list(st.changes),
                   feedback_log=[dict(lap=e.observation.lap, symptom=e.observation.symptom, axle=e.observation.axle, corner_phase=e.observation.corner_phase, severity=e.observation.severity, rule=e.observation.rule,
                                      note=e.observation.note, regime_shift=e.observation.regime_shift, noise_multiplier=e.observation.noise_multiplier, telemetry_support=e.telemetry_support, laps_since=e.laps_since) for e in st.feedback_log],
                   projection=st.derived.get('projection', []), prior=dict(st.prior), slope=st.slope, slope_sd=st.slope_sd, slope_band90=list(st.slope_band90), n_obs=st.n_obs, data_cutoff=st.timestamp,
                   support_status=st.support_status, support_reason=st.support_reason, top_headline=StrategyOptimizer.headline(res.ranked.top), uses_future_data=False, uses_post_race_reference=False)
    return dict(event=event, driver=driver, lap=lap, n_laps=cursor.n_laps, state=state, prior=prior, forecast=forecast, corrections=corr, decision=decision, history=history, kpis=kpis,
                comparable=RS.comparable_traces(cursor, compound, corr), feed=RS.feed_quality(row), feedback=feedback, temp_history_lock=lock.track_temp_history(event),
                temp_series=RS.track_temp_series(cursor), crossover=(plan.crossover if plan else {}), plan=plan, support=support, asset=cursor.asset, fixture_reco=None,
                fixture_label='live/estimator + decision/optimizer', evolution_applied=False, orb_live=orb)


def build_live_vm(lock, event: str, driver: str, cursor, latency_text: str = '—'):
    """A VM.LiveVM instance (drop-in for VM.build_live) with the namespaced extras attached as `.orb_live`."""
    from app_v2.services import view_models as VM
    d = build_live(lock, event, driver, cursor, latency_text)
    orb = d.pop('orb_live')
    vm = VM.LiveVM(**d)
    vm.orb_live = orb
    return vm


__all__ = ['build_live', 'build_live_vm', 'results_through', 'RULE_LABEL']
