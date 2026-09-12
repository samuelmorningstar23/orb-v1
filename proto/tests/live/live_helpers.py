"""Shared helpers for the live-slice tests (synthetic rows, priors, replay loop)."""
import math
import sys
from pathlib import Path

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from live.priors import CompoundPrior, EventPriors, PlanPrior  # noqa: E402
from live.estimator import LiveContext  # noqa: E402
from live.clock import SessionClock  # noqa: E402
from datetime import datetime  # noqa: E402

SYN_CLOCK = SessionClock('Synthetic', 60.0 * 60.0, start=datetime(2026, 9, 6, 15, 0, 0))


def mk_row(lap, age, lap_s, stint=1, compound='MEDIUM', t_min=None, status='1', traffic=0.1, pos=300, temp=45.0, rain=False, pit_in=False, pit_out=False, deleted=False, accurate=True, energy=55.0):
    return dict(event='Synthetic', session='R', Driver='SYN', LapNumber=int(lap), Stint=int(stint), Compound=compound, TyreLife=float(age), lap_s=float(lap_s),
                t_min=(60.0 + 1.5 * lap) if t_min is None else float(t_min), TrackStatus=str(status), IsAccurate=bool(accurate), pit_in=bool(pit_in), pit_out=bool(pit_out),
                deleted=bool(deleted), traffic=traffic, pos_distinct=pos, stale_share=0.05, n_tel=600, track_temp=temp, rain=bool(rain), energy_MJ=energy, e_lat=30.0, e_long=25.0, full_throttle=0.6)


def synthetic_priors(n_laps=50):
    comps = {'SOFT': CompoundPrior('SOFT', 0.08, (0.02, 0.14), True, 'ok', 'synthetic', 'test'),
             'MEDIUM': CompoundPrior('MEDIUM', 0.05, (0.01, 0.09), True, 'ok', 'synthetic', 'test'),
             'HARD': CompoundPrior('HARD', 0.03, (0.00, 0.06), True, 'ok', 'synthetic', 'test')}
    plan = PlanPrior('M-H', (22, 28), 1, (), {})
    return EventPriors('Synthetic', '2026_Synthetic', n_laps, comps, {'SOFT': 0.0, 'MEDIUM': 0.6, 'HARD': 1.2}, {}, 21.0, plan, 'sha256:' + '0' * 64, 'test', 45.0, False,
                       dict(tracks_seen=['Synthetic'], track_temp_range_c=[27.0, 55.0]))


def ctx_for(priors, lap, **kw):
    return LiveContext('Synthetic', 'SYN', int(lap), priors.n_laps, priors, SYN_CLOCK, **kw)


def run_rows(est, rows, priors, feedback=None, feedback_enabled=True, **ctx_kw):
    """Sequential replay over synthetic rows; feedback = {lap: [events]}."""
    st, states = None, []
    for r in rows:
        ctx = ctx_for(priors, r['LapNumber'], feedback_enabled=feedback_enabled, **ctx_kw)
        fb = (feedback or {}).get(r['LapNumber'])
        st = est.update(st, r, ctx, driver_feedback=fb)
        states.append(st)
    return states


