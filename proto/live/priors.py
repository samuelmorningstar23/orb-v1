"""Pre-race priors for the live slice, read from the frozen forecast only.

Source order: out/lock_v2.json `pre_race_forecast` (by construction free of race outcomes; carries the forecast hash), then
out/lock.json `live` and `validation_rows` restricted to the whitelisted forecast fields. The v1 validation rows also carry
`obs`, `obs_se`, `err_*` (race-derived): those keys are on a deny list and are removed before anything else touches the row,
so the live slice can never read a post-race reference (tests/live/test_estimator.py::test_priors_never_expose_race_outcomes).
Prior slope: mean = prediction, sd = (band90[1] - band90[0]) / (2 x 1.6449) (band90 is the 5th to 95th percentile).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

PROTO = Path(__file__).resolve().parents[1]
LOCK_V1 = PROTO / 'out' / 'lock.json'
LOCK_V2 = PROTO / 'out' / 'lock_v2.json'
Z90 = 1.6448536269514722          # 95th percentile of the standard normal: band90 = mean +- Z90 x sd
Z_Q90 = 1.2815515655446004        # 90th percentile
FORECAST_KEYS = ('event', 'compound', 'n_prac', 'naive', 'clean', 'clean_se', 'gate', 'issued', 'pred_clearstint', 'lo', 'hi', 'prediction', 'band90', 'basis', 'energy_trend', 'push_adj')
POST_RACE_KEYS = frozenset({'obs', 'obs_se', 'obs_push', 'n_race', 'completed', 'ratio', 'z', 'err_naive', 'err_clean', 'err_cs', 'err_push',
                            'cost_under_truth_vs_best_s', 'best_under_truth'})
LETTER = {'S': 'SOFT', 'M': 'MEDIUM', 'H': 'HARD', 'I': 'INTERMEDIATE', 'W': 'WET'}


@dataclass(frozen=True)
class CompoundPrior:
    compound: str
    mean: float                       # s/lap per lap of age
    band90: tuple[float, float]
    issued: bool
    gate: str
    basis: str
    source: str
    n_prac: Optional[int] = None

    @property
    def sd(self) -> float:
        lo, hi = self.band90
        return max((hi - lo) / (2.0 * Z90), 1e-4)

    @property
    def var(self) -> float:
        return self.sd ** 2

    @property
    def q90(self) -> float:
        return self.mean + Z_Q90 * self.sd

    def as_dict(self) -> dict[str, Any]:
        return dict(compound=self.compound, mean=self.mean, sd=self.sd, band90=list(self.band90), issued=self.issued, gate=self.gate, basis=self.basis, source=self.source, n_prac=self.n_prac)


@dataclass(frozen=True)
class PlanPrior:
    plan: str                          # e.g. 'S-M'
    stints: tuple[int, ...]
    stops: int
    alternatives: tuple[dict, ...] = ()
    crossover: dict = field(default_factory=dict)

    @property
    def compounds(self) -> tuple[str, ...]:
        return tuple(LETTER.get(c, c) for c in self.plan.split('-'))

    @property
    def pit_laps(self) -> tuple[int, ...]:
        laps, acc = [], 0
        for s in self.stints[:-1]:
            acc += int(s)
            laps.append(acc)
        return tuple(laps)


@dataclass(frozen=True)
class EventPriors:
    event: str
    event_id: str
    n_laps: int
    compounds: dict[str, CompoundPrior]
    offsets: dict[str, float]
    offsets_source: dict[str, str]
    pit_loss: float
    plan: Optional[PlanPrior]
    forecast_hash: Optional[str]
    source: str
    track_temp_practice_c: Optional[float] = None
    rain_in_practice: bool = False
    support: dict = field(default_factory=dict)

    def prior_for(self, compound: str) -> CompoundPrior:
        if compound in self.compounds:
            return self.compounds[compound]
        raise KeyError(f'no pre-race prior for {self.event} {compound}')

    def has(self, compound: str) -> bool:
        return compound in self.compounds


def _scrub(row: dict) -> dict:
    """Drop every post-race key before the row is used anywhere (deny list, not a whitelist, so unknown keys are kept visible)."""
    return {k: v for k, v in row.items() if k not in POST_RACE_KEYS and not k.startswith('err_')}


def _from_v2(lock: dict, event: str) -> Optional[EventPriors]:
    pf = (lock.get('pre_race_forecast') or {}).get('events') or {}
    e = pf.get(event)
    if not e:
        return None
    comps = {}
    for c, f in (e.get('compounds') or {}).items():
        f = _scrub(f)
        comps[c] = CompoundPrior(c, float(f['prediction']), (float(f['band90'][0]), float(f['band90'][1])), bool(f['issued']), str(f['gate']), str(f['basis']), 'lock_v2.pre_race_forecast', f.get('n_prac'))
    s = e.get('strategy') or {}
    plan = PlanPrior(s['plan'], tuple(int(x) for x in s['stints']), int(s['stops']), tuple(dict(a) for a in s.get('alternatives', [])), dict(s.get('crossover') or {})) if s else None
    offsets = {k: float(v) for k, v in (s.get('offsets_s') or {}).items()}
    fh = (lock.get('shared') or {}).get('forecast_hash')
    support = dict((lock.get('shared') or {}).get('support_definition') or {})
    return EventPriors(event, e.get('event_id', f'2026_{event}'), int(e.get('race_laps') or s.get('n_laps') or 0), comps, offsets, dict(s.get('offsets_source') or {}),
                       float(s.get('pit_loss_s', 21.0)), plan, fh, 'lock_v2', e.get('track_temp_practice_c'), bool(e.get('rain_in_practice', False)), support)


def _from_v1(lock: dict, event: str) -> Optional[EventPriors]:
    comps = {}
    live = (lock.get('live') or {}).get(event)
    if live:
        for c in live.get('compounds', []):
            c = _scrub(c)
            b = c.get('band90') or [None, None]
            if c.get('prediction') is None or b[0] is None:
                continue
            comps[c['compound']] = CompoundPrior(c['compound'], float(c['prediction']), (float(b[0]), float(b[1])), bool(c.get('issued')), str(c.get('gate', '')), str(c.get('basis', '')), 'lock.live', c.get('n_prac'))
    else:
        for r in lock.get('validation_rows', []):
            if r.get('event') != event:
                continue
            r = _scrub(r)
            assert 'obs' not in r and not any(k.startswith('err_') for k in r), 'post-race keys survived the scrub'
            if r.get('pred_clearstint') is None or r.get('lo') is None:
                continue
            basis = 'issued: cleaned Friday curve x season factor' if r.get('issued') else 'low-degradation fallback (median race degradation of withheld cases on other weekends)'
            comps[r['compound']] = CompoundPrior(r['compound'], float(r['pred_clearstint']), (float(r['lo']), float(r['hi'])), bool(r.get('issued')), str(r.get('gate', '')), basis, 'lock.validation_rows(forecast fields only)', r.get('n_prac'))
    if not comps:
        return None
    s = (lock.get('strategy') or {}).get(event) or {}
    v = (s.get('views') or {}).get('Orb v1') or {}
    plan = PlanPrior(v['plan'], tuple(int(x) for x in v['stints']), int(v['stops']), tuple(_scrub(a) for a in v.get('alternatives', [])), dict(v.get('crossover') or {})) if v else None
    return EventPriors(event, f'2026_{event}', int(s.get('n_laps') or 0), comps, {k: float(x) for k, x in (s.get('offsets') or {}).items()}, dict(s.get('offsets_source') or {}),
                       float(s.get('pit_loss', 21.0)), plan, None, 'lock_v1', None, False, {})


def load_priors(event: str, lock_v2: Path = LOCK_V2, lock_v1: Path = LOCK_V1) -> EventPriors:
    """lock_v2 first (forecast block + hash), v1 for anything v2 lacks (offsets, pit loss); never a race outcome."""
    v2 = json.load(open(lock_v2, encoding='utf-8')) if Path(lock_v2).exists() else None
    v1 = json.load(open(lock_v1, encoding='utf-8')) if Path(lock_v1).exists() else None
    out = _from_v2(v2, event) if v2 else None
    if out is None and v1:
        out = _from_v1(v1, event)
    if out is None:
        raise KeyError(f'no pre-race forecast for {event} in {lock_v2.name if v2 else ""} {lock_v1.name if v1 else ""}')
    if v1 and (not out.offsets or not out.n_laps):
        s = (v1.get('strategy') or {}).get(event) or {}
        out = EventPriors(out.event, out.event_id, out.n_laps or int(s.get('n_laps') or 0), out.compounds, out.offsets or {k: float(x) for k, x in (s.get('offsets') or {}).items()},
                          out.offsets_source or dict(s.get('offsets_source') or {}), out.pit_loss, out.plan, out.forecast_hash, out.source, out.track_temp_practice_c, out.rain_in_practice, out.support)
    return out


def support_status(priors: EventPriors, compound: str, track_temp_c: Optional[float], rain: bool) -> tuple[str, str]:
    """('IN SUPPORT' | 'NEAR TRAINING SUPPORT' | 'OUT OF SUPPORT, FORECAST WITHHELD', reason) from the lock's support definition."""
    sd = priors.support or {}
    if rain:
        return 'OUT OF SUPPORT, FORECAST WITHHELD', 'rain flagged in the race feed; dry-only model'
    if not priors.has(compound):
        return 'OUT OF SUPPORT, FORECAST WITHHELD', f'no pre-race forecast for {compound}'
    if compound not in priors.offsets:
        return 'OUT OF SUPPORT, FORECAST WITHHELD', f'{compound} has no pace offset in the lock'
    rng = sd.get('track_temp_range_c')
    if rng and track_temp_c is not None and not (float(rng[0]) - 3.0 <= float(track_temp_c) <= float(rng[1]) + 3.0):
        return 'NEAR TRAINING SUPPORT', f'track temperature {track_temp_c:.1f} C outside the training range {rng[0]:.1f} to {rng[1]:.1f} C'
    tracks = sd.get('tracks_seen') or []
    if tracks and priors.event not in tracks:
        return 'NEAR TRAINING SUPPORT', 'circuit not scored in a previous weekend'
    if not priors.compounds[compound].issued:
        return 'NEAR TRAINING SUPPORT', f'{compound} forecast withheld on Friday: low-degradation fallback prior'
    return 'IN SUPPORT', ''


__all__ = ['CompoundPrior', 'PlanPrior', 'EventPriors', 'load_priors', 'support_status', 'POST_RACE_KEYS', 'Z90', 'Z_Q90', 'LETTER']
