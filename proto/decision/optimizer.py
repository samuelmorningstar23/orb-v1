"""StrategyOptimizer (roadmap v5 task 0.12, contract 7.2): the pre-race optimiser re-run from the current lap.

recommend(tyre_state, available_sets, race_context, competitor_context=None, previous=None) -> RankedActions

Same arithmetic as strategy2.best_plans / stint_time: a stint of L laps on compound d costs offset_d x L + slope_d x L(L+1)/2
(lock offsets, SOFT = 0), a stop costs the lock pit loss. The current stint continues with the live posterior slope of the
current compound (sampled from the posterior); the alternatives use the frozen pre-race forecast of their compound
(sampled from its band); the pit loss carries N(0, 1 s) noise. Candidate actions from lap k with R = n_laps - k laps left:
    PIT_NOW              pit at the end of lap k, new set of compound d, one stint to the flag
    PIT (lap j)          stay out until lap j in the next window (k+1 .. k+WINDOW), then pit to d
    EXTEND               pit later than the window (best lap beyond it), then one stint to the flag
    STAY_OUT             no further stop (only when two dry compounds have already been used)
    PIT (two-stop)       pit at j to d, then again at the best j2 to e ('convert to two-stop')
Constraints: minimum stint MIN_STINT laps, the two-compound rule (the plan must end with two distinct dry compounds), one
set per available inventory entry. Expected gain = time of the pre-race plan's remaining schedule minus the action's time
under the same samples (positive = the action is faster); median / q10 / q90 from the samples; probability_of_gain is
P(gain > 0) + 0.5 P(gain = 0), so the action identical to the plan scores 0.5.
Actions are ranked by median gain (the list always carries 'stay out' when legal and the best 'pit now', so the board
shows what doing nothing and boxing now would cost), with hysteresis: the previous top action keeps the top spot while its median gain is
within HYSTERESIS_S of the best, so the call only moves when the challenger is clearly better. A pit window is the
contiguous laps around the best lap whose mean time lies within WINDOW_TOL_S of it. rejoin_context is the observed lap-time ordering of the field at lap k (live/lapfeed.FieldSnapshot:
cars still on lap k are projected from their last completed lap) when a race file is available, else the string
'not available (no interval feed)'. Rival strategy responses are never simulated (roadmap Q10).
changed_since_last_update compares the top action with the previous lap's (action, compound, window start within one
lap); change_reason
names the observation that moved the call, taken from the estimator's per-lap change log (band exceedance, clean lap,
feedback, temperature, flag, pit reset). No recommendation changes silently.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

import numpy as np

from live import ESTIMATOR_LABEL
from live.estimator import TyreStateDistribution
from live.lapfeed import FieldCar
from live.priors import EventPriors, PlanPrior, LETTER

MIN_STINT = 6
WINDOW = 8
WINDOW_TOL_S = 0.5
PIT_LOSS_SD = 1.0
N_SAMPLES = 2000
SEED = 8
MAX_ACTIONS = 6
HYSTERESIS_S = 1.0             # the previous top action keeps the top spot while its median gain is within this of the best
DRY = ('SOFT', 'MEDIUM', 'HARD')
NOT_AVAILABLE = 'not available (no interval feed)'


@dataclass
class RaceContext:
    event: str
    n_laps: int
    lap: int
    priors: EventPriors
    issued_at: str
    compounds_used: list[str] = field(default_factory=list)
    stops_done: int = 0
    min_stint: int = MIN_STINT
    window: int = WINDOW
    n_samples: int = N_SAMPLES
    seed: int = SEED
    pit_loss_sd: float = PIT_LOSS_SD
    plan: Optional[PlanPrior] = None
    inventory_note: str = 'inventory placeholder: one new set of each dry compound with a lock offset (Phase 1 adds the live tyre-set feed)'


@dataclass
class CompetitorContext:
    driver: str
    cars: list[FieldCar]
    pit_loss: float
    lap: int


@dataclass
class RankedActions:
    lap: int
    issued_at: str
    actions: list[dict[str, Any]]              # contract 7.2 records, rank 1..n
    baseline: dict[str, Any]
    samples: int
    seed: int
    estimator: str = ESTIMATOR_LABEL

    @property
    def top(self) -> Optional[dict[str, Any]]:
        return self.actions[0] if self.actions else None

    def as_dict(self) -> dict[str, Any]:
        return dict(lap=self.lap, issued_at=self.issued_at, baseline=self.baseline, samples=self.samples, seed=self.seed, estimator=self.estimator, actions=self.actions)


def default_inventory(priors: EventPriors, compounds_used: list[str]) -> list[dict[str, Any]]:
    """Placeholder inventory (Phase 1 replaces it): one new set of each dry compound with a lock offset and a prior."""
    return [dict(set_id=f'{c[0]}-new-1', compound=c, status='new', age_laps=0) for c in DRY if c in priors.offsets and priors.has(c)]


def stint_cost(offset: float, slope: np.ndarray | float, laps) -> np.ndarray | float:
    """sum_{i=1..L} (offset + slope i) = offset L + slope L(L+1)/2 (strategy2.stint_time, closed form; laps may be an array)."""
    L = np.asarray(laps, dtype=float) if not np.isscalar(laps) else float(laps)
    return offset * L + slope * L * (L + 1.0) / 2.0


def continue_cost(offset: float, slope: np.ndarray | float, age: int, laps: int) -> np.ndarray | float:
    """Continue the current tyre from age `age` for `laps` more laps: sum_{i=age+1..age+laps} (offset + slope i)."""
    h = float(laps)
    return offset * h + slope * (h * (2.0 * float(age) + h + 1.0) / 2.0)


def rejoin_context(comp: Optional[CompetitorContext]) -> dict[str, Any]:
    if comp is None or not comp.cars:
        return dict(basis='observed_gap_structure', position_now=None, projected_rejoin_position=None,   # 7.2 data; rendered only in frozen_field mode
                    gap_ahead_s=None, gap_behind_s=None, cars_within_pit_loss=None, traffic_density=None, note=NOT_AVAILABLE)
    me = [c for c in comp.cars if c.driver == comp.driver]
    if not me:
        return dict(basis='observed_gap_structure', note=NOT_AVAILABLE)
    t_me = me[0].est_t_end_k
    order = sorted(comp.cars, key=lambda c: (c.est_t_end_k, c.driver))
    pos = [c.driver for c in order].index(comp.driver) + 1
    ahead = [c for c in order if c.est_t_end_k < t_me]
    behind = [c for c in order if c.est_t_end_k > t_me]
    gap_ahead = (t_me - ahead[-1].est_t_end_k) if ahead else None
    gap_behind = (behind[0].est_t_end_k - t_me) if behind else None
    within = sum(1 for c in behind if c.est_t_end_k - t_me < comp.pit_loss)
    near = sum(1 for c in comp.cars if c.driver != comp.driver and abs(c.est_t_end_k - (t_me + comp.pit_loss)) <= 3.0)
    density = 'clear' if near == 0 else ('light' if near <= 2 else 'dense')
    projected = sum(1 for c in comp.cars if c.driver != comp.driver and c.est_t_end_k < t_me + comp.pit_loss) + 1
    n_proj = sum(1 for c in comp.cars if c.projected)
    return dict(basis='observed_gap_structure', position_now=int(pos), projected_rejoin_position=int(projected),   # 7.2 data; rendered only in frozen_field mode (live pages show the gap structure)
                gap_ahead_s=(round(float(gap_ahead), 3) if gap_ahead is not None else None),
                gap_behind_s=(round(float(gap_behind), 3) if gap_behind is not None else None), cars_within_pit_loss=int(within), traffic_density=density,
                note=f'observed lap-time ordering at lap {comp.lap} (t_min + lap_s from the race file; {n_proj} cars still on lap {comp.lap} projected from their last completed lap); rival strategy responses are not simulated')


class StrategyOptimizer:
    label = 'exact stint enumeration on the live posterior (strategy2 arithmetic), sampled gains vs the pre-race plan'

    def __init__(self, n_samples: int = N_SAMPLES, seed: int = SEED):
        self.n_samples, self.seed = int(n_samples), int(seed)
        self.last: Optional[RankedActions] = None

    # ---- samples ---------------------------------------------------------------------------------------------------
    def _samples(self, st: TyreStateDistribution, rc: RaceContext) -> tuple[dict[str, np.ndarray], np.ndarray]:
        rng = np.random.default_rng(rc.seed * 7919 + rc.lap)
        n = rc.n_samples
        slopes = {st.compound: rng.normal(st.slope, st.slope_sd, n)}
        for c in DRY:
            if c != st.compound and rc.priors.has(c):
                pr = rc.priors.prior_for(c)
                slopes[c] = rng.normal(pr.mean, pr.sd, n)
        pit = rng.normal(rc.priors.pit_loss, rc.pit_loss_sd, n)
        return slopes, pit

    # ---- baseline: the pre-race plan's remaining schedule -------------------------------------------------------------
    def _baseline(self, st: TyreStateDistribution, rc: RaceContext, slopes: dict[str, np.ndarray], pit: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        n, k, age = rc.n_laps, rc.lap, st.tyre_age
        R = n - k
        o = rc.priors.offsets
        plan = rc.plan or rc.priors.plan
        cur = slopes[st.compound]
        if plan is None or rc.stops_done >= plan.stops:
            return continue_cost(o.get(st.compound, 0.0), cur, age, R), dict(plan=(plan.plan if plan else None), schedule='stay out to the flag', stops_remaining=0)
        stops = [(int(p), plan.compounds[i + 1]) for i, p in enumerate(plan.pit_laps) if i >= rc.stops_done]
        t = np.zeros_like(cur)
        lap_now, sched = k, []
        first = True
        for p, comp in stops:
            p = max(p, lap_now)
            if p > n - rc.min_stint:
                break
            h = p - lap_now
            t = t + (continue_cost(o.get(st.compound, 0.0), cur, age, h) if first else stint_cost(o.get(prev_comp, 0.0), slopes.get(prev_comp, cur), h))
            t = t + pit
            sched.append(f'pit lap {p} -> {comp}')
            lap_now, prev_comp, first = p, comp, False
        t = t + (continue_cost(o.get(st.compound, 0.0), cur, age, n - lap_now) if first else stint_cost(o.get(prev_comp, 0.0), slopes.get(prev_comp, cur), n - lap_now))
        return t, dict(plan=plan.plan, schedule='; '.join(sched) or 'stay out to the flag', stops_remaining=len(sched))

    # ---- candidates --------------------------------------------------------------------------------------------------
    def _candidates(self, st: TyreStateDistribution, rc: RaceContext, sets: list[dict], slopes: dict[str, np.ndarray], pit: np.ndarray) -> list[dict[str, Any]]:
        n, k, age = rc.n_laps, rc.lap, st.tyre_age
        R = n - k
        o = rc.priors.offsets
        cur = slopes[st.compound]
        used = set(rc.compounds_used) | {st.compound}
        inv: dict[str, list[dict]] = {}
        for s in sets:
            if s['compound'] in slopes and s['compound'] in o:
                inv.setdefault(s['compound'], []).append(s)
        cands = []
        if len(used) >= 2 or R < rc.min_stint:
            note = 'stay out to the flag' if len(used) >= 2 else f'stay out: only {R} laps remain, below the minimum stint (the two-compound rule cannot be met by a further stop)'
            cands.append(dict(action='STAY_OUT', j=None, compound=None, set=None, t=continue_cost(o[st.compound], cur, age, R), label=note))
        for d, dsets in inv.items():
            legal = len(used | {d}) >= 2
            if not legal:
                continue
            for j in range(k, min(k + rc.window, n - rc.min_stint) + 1):
                L = n - j
                if L < rc.min_stint:
                    continue
                t = continue_cost(o[st.compound], cur, age, j - k) + pit + stint_cost(o[d], slopes[d], L)
                cands.append(dict(action='PIT_NOW' if j == k else 'PIT', j=j, compound=d, set=dsets[0], t=t, label=f"{'pit now' if j == k else 'pit lap ' + str(j)} -> new {d.lower()}"))
            best_ext, per_j = None, {}
            for j in range(k + rc.window + 1, n - rc.min_stint + 1):
                t = continue_cost(o[st.compound], cur, age, j - k) + pit + stint_cost(o[d], slopes[d], n - j)
                per_j[j] = float(np.mean(t))
                if best_ext is None or per_j[j] < float(np.mean(best_ext['t'])):
                    best_ext = dict(action='EXTEND', j=j, compound=d, set=dsets[0], t=t, per_j=per_j, label=f'extend, pit lap {j} -> new {d.lower()}')
            if best_ext is not None:
                cands.append(best_ext)
        # two-stop conversions: (d, e) over inventory, first stop at any feasible lap (not only the window, so the call does not
        # creep with the window), second stop by the mean-time optimum; one candidate per pair carrying its per-lap means
        for d, dsets in inv.items():
            for e, esets in inv.items():
                if d == e and len(dsets) < 2:
                    continue
                if len(used | {d, e}) < 2:
                    continue
                best, per_j = None, {}
                mean_cur, mean_d, mean_e = float(np.mean(cur)), float(np.mean(slopes[d])), float(np.mean(slopes[e]))
                for j in range(k, n - 2 * rc.min_stint + 1):
                    j2s = np.arange(j + rc.min_stint, n - rc.min_stint + 1)
                    if len(j2s) == 0:
                        continue
                    tm = continue_cost(o[st.compound], mean_cur, age, j - k) + 2 * rc.priors.pit_loss + stint_cost(o[d], mean_d, j2s - j) + stint_cost(o[e], mean_e, n - j2s)
                    i = int(np.argmin(tm))
                    per_j[j] = float(tm[i])
                    if best is None or float(tm[i]) < best[0]:
                        best = (float(tm[i]), j, int(j2s[i]))
                if best is None:
                    continue
                _, j, j2 = best
                t = continue_cost(o[st.compound], cur, age, j - k) + 2 * pit + stint_cost(o[d], slopes[d], j2 - j) + stint_cost(o[e], slopes[e], n - j2)
                act = 'PIT_NOW' if j == k else ('PIT' if j <= k + rc.window else 'EXTEND')
                cands.append(dict(action=act, j=j, j2=j2, compound=d, compound2=e, set=dsets[0], set2=(esets[1] if d == e else esets[0]), t=t, two_stop=True, per_j=per_j,
                                  label=f"convert to two-stop: {'pit now' if j == k else 'pit lap ' + str(j)} -> new {d.lower()}, then lap {j2} -> new {e.lower()}"))
        return cands

    # ---- ranking -----------------------------------------------------------------------------------------------------
    def recommend(self, tyre_state: TyreStateDistribution, available_sets: Optional[list[dict]], race_context: RaceContext, competitor_context: Optional[CompetitorContext] = None,
                  previous: Optional[RankedActions] = None) -> RankedActions:
        st, rc = tyre_state, race_context
        sets = available_sets if available_sets is not None else default_inventory(rc.priors, rc.compounds_used)
        slopes, pit = self._samples(st, rc)
        t_base, base_info = self._baseline(st, rc, slopes, pit)
        cands = self._candidates(st, rc, sets, slopes, pit)
        rejoin = rejoin_context(competitor_context)
        prev = previous if previous is not None else self.last
        prev_top = prev.top if prev is not None else None
        # collapse: best lap per (action family, compound, two_stop) and a pit window around it
        groups: dict[tuple, list[dict]] = {}
        for c in cands:
            fam = 'TWO' if c.get('two_stop') else (c['action'] if c['action'] in ('STAY_OUT', 'EXTEND') else 'PIT')
            key = (fam, c.get('compound'), bool(c.get('two_stop')), c.get('compound2'))
            groups.setdefault(key, []).append(c)
        scored = []
        for key, items in groups.items():
            items = sorted(items, key=lambda c: float(np.mean(c['t'])))
            best = items[0]
            means = best['per_j'] if best.get('per_j') else {c['j']: float(np.mean(c['t'])) for c in items if c.get('j') is not None}
            window = None
            if best.get('j') is not None:
                lo = hi = best['j']
                while (lo - 1) in means and means[lo - 1] - means[best['j']] <= WINDOW_TOL_S:
                    lo -= 1
                while (hi + 1) in means and means[hi + 1] - means[best['j']] <= WINDOW_TOL_S:
                    hi += 1
                window = [int(lo), int(hi)]
            gain = t_base - best['t']
            q10, q50, q90 = (float(x) for x in np.quantile(gain, [0.1, 0.5, 0.9]))
            p_gain = float(np.mean(gain > 0.0) + 0.5 * np.mean(gain == 0.0))     # tie-adjusted: an action identical to the plan scores 0.5
            scored.append((q50, best, window, q10, q90, p_gain))
        scored.sort(key=lambda x: -x[0])
        if prev_top is not None and len(scored) > 1:       # hysteresis: a call only moves when the challenger is clearly better
            for i, sc in enumerate(scored[1:], start=1):
                if self._same_call(prev_top, sc[1], sc[2]) and scored[0][0] - sc[0] < HYSTERESIS_S:
                    scored.insert(0, scored.pop(i))
                    break
        # the board always shows 'stay out' (when legal) and the best 'pit now', however they rank
        keep = [sc for sc in scored[:MAX_ACTIONS]]
        for want in ('STAY_OUT', 'PIT_NOW'):
            if not any(sc[1]['action'] == want for sc in keep):
                extra = next((sc for sc in scored if sc[1]['action'] == want), None)
                if extra is None and want == 'PIT_NOW':
                    now = [c for c in cands if c['action'] == 'PIT_NOW' and not c.get('two_stop')]
                    if now:
                        best_now = min(now, key=lambda c: float(np.mean(c['t'])))
                        g = t_base - best_now['t']
                        extra = (float(np.quantile(g, 0.5)), best_now, [int(rc.lap), int(rc.lap)], float(np.quantile(g, 0.1)), float(np.quantile(g, 0.9)), float(np.mean(g > 0) + 0.5 * np.mean(g == 0)))
                if extra is not None:
                    if len(keep) >= MAX_ACTIONS:        # drop the lowest-ranked entry that is not itself a protected action
                        for i in range(len(keep) - 1, -1, -1):
                            if keep[i][1]['action'] not in ('STAY_OUT', 'PIT_NOW'):
                                keep.pop(i)
                                break
                    keep.append(extra)
        keep = [keep[0]] + sorted(keep[1:], key=lambda x: -x[0]) if keep else keep
        scored = keep
        used = set(rc.compounds_used) | {st.compound}
        constraints = [f'available sets: ' + ', '.join(f"{s['compound'].lower()} ({s['status']})" for s in sets) + f' [{rc.inventory_note}]', f'minimum stint {rc.min_stint} laps',
                       ('two dry compounds already used: no further stop is mandatory' if len(used) >= 2 else f'only {"/".join(sorted(used)).lower()} used so far: one more stop is mandatory (two-compound rule)')]
        d = st.derived
        base_reasons = [f"posterior degradation {st.slope:+.4f} s/lap per lap ({d.get('trend_vs_pre_race', 0.0):+.0%} vs the pre-race forecast {st.prior_slope:+.4f}) from {st.n_obs} clean laps on {st.compound.lower()} age {st.tyre_age}; regime {st.regime}",
                        f"useful life q10/q50/q90 {d.get('useful_laps_q10', 0):.0f}/{d.get('useful_laps_q50', 0):.0f}/{d.get('useful_laps_q90', 0):.0f} laps; cliff probability {d.get('cliff_probability_3_laps', 0):.0%} within 3 laps",
                        f"gains are measured against the pre-race plan's remaining schedule: {base_info['schedule']} (plan {base_info['plan']})"]
        for w in st.widening:
            base_reasons.append(f'band widened after {w.rule} (x{w.applied:.2f})')
        for f in st.feedback_this_lap:
            base_reasons.append(f'driver feedback: {f.symptom} {f.axle} {f.corner_phase} severity {f.severity}/5 {f.trend} ({f.rule})')
        actions = []
        for rank, (q50, best, window, q10, q90, p) in enumerate(scored, start=1):
            act = best['action']
            tgt = best.get('compound')
            tset = dict(set_id=best['set'].get('set_id'), compound=best['set']['compound'], status=best['set'].get('status', 'new'), age_laps=int(best['set'].get('age_laps', 0))) if best.get('set') else None
            reasons = [best['label']] + base_reasons
            if best.get('two_stop'):
                reasons.append(f"second stop lap {best['j2']} -> new {best['compound2'].lower()}")
            changed, reason = False, None
            if rank == 1:
                changed, reason = self._changed(prev_top, act, tgt, window, st, best, scored)
            actions.append(dict(rank=rank, lap=int(rc.lap), issued_at=rc.issued_at, action=act, pit_window=window if act != 'STAY_OUT' else None, target_compound=tgt, target_set=tset,
                                expected_gain_median=round(q50, 3), expected_gain_q10=round(q10, 3), expected_gain_q90=round(q90, 3), probability_of_gain=round(p, 4), rejoin_context=rejoin,
                                reasons=reasons, constraints=constraints, changed_since_last_update=bool(changed), change_reason=reason))
        out = RankedActions(int(rc.lap), rc.issued_at, actions, dict(base_info, time_median_s=float(np.median(t_base)) if len(actions) else None), rc.n_samples, rc.seed)
        self.last = out
        return out

    @staticmethod
    def headline(a: Optional[dict]) -> str:
        if a is None:
            return 'none'
        if a['action'] == 'STAY_OUT':
            return 'STAY OUT'
        w = a.get('pit_window') or [None, None]
        lap = f'lap {w[0]}' if w[0] == w[1] else f'laps {w[0]}-{w[1]}'
        return f"{a['action']} {lap}" + (f" new {a['target_compound'].lower()}" if a.get('target_compound') else '')

    @staticmethod
    def _same_call(prev_top: dict, best: dict, window: Optional[list[int]]) -> bool:
        act, tgt = best['action'], best.get('compound')
        pw = prev_top.get('pit_window')
        fam = lambda a: 'PIT' if a in ('PIT', 'PIT_NOW') else a      # a window that reaches the current lap becomes 'pit now': the same call
        if act == 'STAY_OUT' or (act == 'PIT_NOW' and prev_top['action'] == 'PIT_NOW'):
            same_window = True          # 'pit now' at lap k and at lap k+1 are the same call; so is 'stay out'
        else:                           # same call while the window start moves by at most one lap
            same_window = (pw is None and window is None) or (pw is not None and window is not None and abs(pw[0] - window[0]) <= 1)
        return fam(prev_top['action']) == fam(act) and prev_top.get('target_compound') == tgt and same_window and bool(prev_top.get('reasons', [''])[0].startswith('convert')) == bool(best.get('two_stop'))

    def _changed(self, prev_top: Optional[dict], act: str, tgt: Optional[str], window: Optional[list[int]], st: TyreStateDistribution, best: dict, scored: Optional[list] = None) -> tuple[bool, Optional[str]]:
        if prev_top is None:
            return False, None
        if self._same_call(prev_top, best, window):
            return False, None
        cause = self._cause(st)
        if cause.startswith('lap ') and scored:
            old = next((sc for sc in scored if self._same_call(prev_top, sc[1], sc[2])), None)
            if old is not None:
                cause = f"the expected gain of {self.headline(prev_top)} fell to {old[0]:+.1f} s (p {old[5]:.2f}) with {st.n_laps - st.lap} laps remaining while {best['label']} stands at {scored[0][0]:+.1f} s; no new clean observation this lap"
            else:
                cause = f"{self.headline(prev_top)} is no longer feasible with {st.n_laps - st.lap} laps remaining (minimum stint {MIN_STINT} laps)"
        return True, f"moved from {self.headline(prev_top)} to {self.headline(dict(action=act, pit_window=window, target_compound=tgt))} because {cause}"

    @staticmethod
    def _cause(st: TyreStateDistribution) -> str:
        """The observation that moved the call, from the estimator's change log of this lap (priority: band exceedance, feedback, temperature, flag, pit reset, clean lap)."""
        lo, hi = float(st.prior['band90'][0]), float(st.prior['band90'][1])
        if st.n_obs >= 1 and (st.slope > hi or st.slope < lo):
            side = 'above' if st.slope > hi else 'below'
            return f"the live degradation posterior {st.slope:+.4f} s/lap per lap sits {side} the pre-race band [{lo:+.4f}, {hi:+.4f}] after {st.n_obs} clean laps (band exceedance)"
        for c in st.changes:
            if c.startswith('driver feedback'):
                return c
        for c in st.changes:
            if 'temperature' in c:
                return c
        for c in st.changes:
            if 'track status' in c or 'rain' in c:
                return c
        for c in st.changes:
            if c.startswith('pit reset'):
                return c
        if st.regime in ('CLIFF', 'ANOMALY', 'ACCELERATING_WEAR', 'OVERHEATING', 'GRAINING'):
            return f'regime {st.regime}'
        for c in st.changes:
            if c.startswith('clean lap'):
                return c
        return f'lap {st.lap} completed (race distance advanced; no new clean observation)'


__all__ = ['StrategyOptimizer', 'RankedActions', 'RaceContext', 'CompetitorContext', 'rejoin_context', 'default_inventory', 'stint_cost', 'continue_cost', 'MIN_STINT', 'WINDOW', 'NOT_AVAILABLE']
