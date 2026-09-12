"""PLACEHOLDER decision rules until Workstream 8's StrategyOptimizer (0.12) is wired through the same view model.

Everything numeric here is read from the lock (plan, stint lengths, alternatives, delta_to_best, band edges).
The only logic is the selection rule, which is labelled on screen: the recommendation is the lock plan, and its
status changes when the placeholder posterior leaves the lock's 90 % band for two consecutive kept laps or when a
severity >= 4 driver report arrives. No recommendation changes silently: every change has a reason and a lap.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from app_v2.services.lock_repository import LockView, PlanView
from app_v2.services.replay_service import ReplayCursor, Prior, Corrections, StintState, stint_state

RULE_LABEL = 'PLACEHOLDER decision rule: lock plan; status moves when the placeholder posterior leaves the lock band for 2 kept laps or on a severity >= 4 report (Workstream 8 StrategyOptimizer pending)'
LETTER = {'S': 'SOFT', 'M': 'MEDIUM', 'H': 'HARD'}


@dataclass
class Decision:
    lap: int
    action: str                       # PIT | STAY OUT | REVIEW | NO PLAN
    status: str                       # HOLD PLAN | ABOVE FORECAST BAND | BELOW FORECAST BAND | DRIVER REPORT
    pit_lap: Optional[int]
    target_compound: Optional[str]
    plan: Optional[str]
    plan_source: str
    expected_gain_s: Optional[float]  # lock: delta_to_best of the best distinct alternative
    gain_vs: Optional[str]
    probability_of_gain: Optional[float]
    downside_q10_s: Optional[float]
    rejoin_context: str
    reasons: list[str] = field(default_factory=list)
    alternatives: list[dict] = field(default_factory=list)
    change_reason: str = ''
    changed_since_last_update: bool = False
    band_edge_laps: tuple[Optional[int], Optional[int]] = (None, None)
    rule_label: str = RULE_LABEL

    @property
    def headline(self) -> str:
        if self.action == 'PIT' and self.pit_lap:
            return f'PIT LAP {self.pit_lap}, NEW {self.target_compound}'
        if self.action == 'STAY OUT':
            return 'STAY OUT TO THE FLAG'
        if self.action == 'REVIEW':
            return f'REVIEW PLAN: PIT LAP {self.pit_lap}' if self.pit_lap else 'REVIEW PLAN'
        return 'NO PLAN IN LOCK'


def _next_stop(plan: PlanView, lap: int) -> tuple[Optional[int], Optional[str]]:
    for i, pit in enumerate(plan.pit_laps):
        if pit >= lap:
            return pit, plan.compounds[i + 1]
    return None, None


def _alternatives(plan: PlanView, n: int = 3) -> list[dict]:
    out, seen = [], {plan.plan}
    for alt in plan.alternatives:
        key = alt['plan']
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(plan=alt['plan'], stints=list(alt['stints']), stops=alt['stops'], delta_to_best_s=alt.get('delta_to_best')))
        if len(out) >= n:
            break
    return out


def decide(lock: LockView, event: str, lap: int, state: Optional[StintState], prior: Prior, prev_state: Optional[StintState], feedback: list[dict]) -> Decision:
    plan = lock.primary_plan(event)
    if plan is None:
        return Decision(lap, 'NO PLAN', 'NO PLAN', None, None, None, 'none', None, None, None, None, 'not simulated in Phase 0', ['no strategy block in the lock for this event'])
    pit_lap, target = _next_stop(plan, lap)
    alts = _alternatives(plan)
    costly = [a for a in alts if (a.get('delta_to_best_s') or 0) > 0]
    gain = costly[0]['delta_to_best_s'] if costly else (alts[0]['delta_to_best_s'] if alts else None)
    gain_vs = costly[0]['plan'] if costly else (alts[0]['plan'] if alts else None)
    views = lock.plan_views(event)
    lo_v, hi_v = views.get('Orb v1, band low'), views.get('Orb v1, band high')
    edges = (lo_v.pit_laps[0] if lo_v and lo_v.pit_laps else None, hi_v.pit_laps[0] if hi_v and hi_v.pit_laps else None)
    d = Decision(lap, 'PIT' if pit_lap else 'STAY OUT', 'HOLD PLAN', pit_lap, target, plan.plan, f'lock.strategy.{event}.views.{plan.name}', gain, gain_vs, None, None,
                 'not simulated (Phase 0)', [], alts, '', False, edges)
    d.reasons.append(f'lock plan {plan.plan}, stints {"/".join(map(str, plan.stints))}, pit loss {lock.strategy_assumptions(event).get("pit_loss", 0):.0f} s')
    if state is None or state.post_slope is None:
        d.reasons.append('no posterior yet: prior only'); return d
    lo, hi = prior.band90
    above_now = hi is not None and state.post_slope > hi and state.kept_laps >= 3
    below_now = lo is not None and state.post_slope < lo and state.kept_laps >= 3
    above_prev = prev_state is not None and prev_state.post_slope is not None and hi is not None and prev_state.post_slope > hi and prev_state.kept_laps >= 3
    below_prev = prev_state is not None and prev_state.post_slope is not None and lo is not None and prev_state.post_slope < lo and prev_state.kept_laps >= 3
    reports = [f for f in feedback if int(f.get('severity', 0)) >= 4 and int(f.get('lap', 0)) <= lap]
    if above_now and above_prev:
        d.status, d.action = 'ABOVE FORECAST BAND', 'REVIEW'
        d.change_reason = f'posterior {state.post_slope:+.3f} s/lap above the forecast band top {hi:+.3f} for two consecutive kept laps ({state.estimator_label.split(":")[0]})'
        d.reasons.append(d.change_reason)
        if edges[1]:
            d.reasons.append(f'lock band-high plan pits at lap {edges[1]}')
    elif below_now and below_prev:
        d.status, d.action = 'BELOW FORECAST BAND', 'REVIEW'
        d.change_reason = f'posterior {state.post_slope:+.3f} s/lap below the forecast band floor {lo:+.3f} for two consecutive kept laps: extending the stint is on the table'
        d.reasons.append(d.change_reason)
        if edges[0]:
            d.reasons.append(f'lock band-low plan pits at lap {edges[0]}')
    if reports:
        r = reports[-1]
        d.status = 'DRIVER REPORT' if d.status == 'HOLD PLAN' else d.status
        d.action = 'REVIEW'
        line = f"driver report lap {r['lap']}: {r['symptom']} {r['axle']} {r['corner_phase']} severity {r['severity']}/5, {r['trend']}" + ('' if r.get('engineer_confirmed') else ' (unconfirmed)')
        d.reasons.append(line)
        d.change_reason = (d.change_reason + '; ' if d.change_reason else '') + line
    if state.widened:
        d.reasons.append(f'band widened x{1.0 if not state.widened else 1.49:.2f} after {state.widen_reason}')
    return d


def timeline(lock: LockView, event: str, cursor: ReplayCursor, prior_for, corr: Corrections, feedback: list[dict], through_lap: Optional[int] = None) -> list[Decision]:
    """Re-evaluate the rule lap by lap (deterministic; identical on scrub and on replay). Returns change points."""
    k = cursor.lap if through_lap is None else through_lap
    out, prev_state, prev_key = [], None, None
    for lap in range(cursor.first_lap, k + 1):
        st = stint_state(cursor, prior_for(None), corr, lap=lap)
        if st is None:
            continue
        prior = prior_for(st.compound)
        if prev_state is not None and prev_state.stint != st.stint:
            prev_state = None
        d = decide(lock, event, lap, st, prior, prev_state, [f for f in feedback if int(f.get('lap', 0)) <= lap])
        key = (d.action, d.status, d.pit_lap, d.target_compound)
        if key != prev_key:
            d.changed_since_last_update = prev_key is not None
            out.append(d); prev_key = key
        prev_state = st
    return out
