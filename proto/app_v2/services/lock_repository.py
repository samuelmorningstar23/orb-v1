"""Loads out/lock_v2.json when present (overlaying the v1 blocks from out/lock.json), else out/lock.json.

Pages never read JSON themselves: they consume `LockView`, whose accessors return small typed records with a
`source` label ('lock', 'lock_v2', 'FIXTURE') so the UI can show provenance next to every number.
"""
from __future__ import annotations
import json, os
from dataclasses import dataclass, field
from typing import Any, Optional
from app_v2.services import paths as P
from app_v2.services import asset_repository as A

try:  # cache when a Streamlit runtime exists; plain function otherwise (tests, scripts)
    import streamlit as st
    _cache = st.cache_data(show_spinner=False)
except Exception:  # pragma: no cover
    def _cache(fn):
        return fn


@dataclass(frozen=True)
class Forecast:
    event: str
    compound: str
    prediction: Optional[float]          # s/lap per lap of age
    band90: tuple[Optional[float], Optional[float]]
    issued: bool
    gate: str
    basis: str
    n_prac: Optional[int]
    source: str                          # 'lock.live' | 'lock.validation_rows' | 'none'
    observed: Optional[float] = None     # race-derived reference (post-race). Ghost only.
    observed_se: Optional[float] = None
    err: Optional[float] = None
    n_race: Optional[int] = None

    @property
    def width(self) -> Optional[float]:
        lo, hi = self.band90
        return None if lo is None or hi is None else hi - lo

    @property
    def covered(self) -> Optional[bool]:
        lo, hi = self.band90
        if self.observed is None or lo is None or hi is None:
            return None
        return lo <= self.observed <= hi


@dataclass(frozen=True)
class PlanView:
    name: str
    plan: str
    stints: tuple[int, ...]
    stops: int
    crossover: dict
    alternatives: tuple[dict, ...]
    cost_under_truth_s: Optional[float]
    best_under_truth: Optional[dict]

    @property
    def compounds(self) -> tuple[str, ...]:
        m = {'S': 'SOFT', 'M': 'MEDIUM', 'H': 'HARD'}
        return tuple(m.get(c, c) for c in self.plan.split('-'))

    @property
    def pit_laps(self) -> tuple[int, ...]:
        laps, acc = [], 0
        for s in self.stints[:-1]:
            acc += int(s); laps.append(acc)
        return tuple(laps)


@dataclass
class LockView:
    raw: dict
    version: str                         # 'v1' | 'v2'
    path: str
    asset: A.Asset
    v2: Optional[dict] = None
    v2_asset: Optional[A.Asset] = None
    fixture: Optional[dict] = None       # proto/fixtures/lock_v2_fixture.json (labelled FIXTURE wherever shown)
    fixture_asset: Optional[A.Asset] = None

    # ---- shared -------------------------------------------------------------------------------------------------
    @property
    def generated_at(self) -> str:
        return (self.v2 or {}).get('shared', {}).get('generated_at') or self.raw.get('generated_at', '')

    @property
    def forecast_hash(self) -> str:
        """Forecast hash shown in the global frame. v2: shared.forecast_hash; v1: sha256 of the lock file itself."""
        h = (self.v2 or {}).get('shared', {}).get('forecast_hash')
        if h:
            return h.replace('sha256:', '')
        return self.asset.sha256 or ''

    @property
    def forecast_hash_source(self) -> str:
        return 'lock_v2.shared.forecast_hash' if (self.v2 or {}).get('shared', {}).get('forecast_hash') else 'sha256(out/lock.json)'

    @property
    def model_version(self) -> str:
        return (self.v2 or {}).get('shared', {}).get('model_version') or 'v1 estimator (cleaned Friday curve x season factor)'

    @property
    def rules(self) -> dict:
        return self.raw.get('rules', {})

    @property
    def events(self) -> dict:
        return self.raw.get('events', {})

    @property
    def strategy(self) -> dict:
        return self.raw.get('strategy', {})

    @property
    def validation(self) -> dict:
        return self.raw.get('validation', {})

    @property
    def validation_rows(self) -> list[dict]:
        return self.raw.get('validation_rows', [])

    @property
    def live(self) -> dict:
        return self.raw.get('live', {})

    # ---- event helpers ----------------------------------------------------------------------------------------------
    def event_names(self) -> list[str]:
        live = list(self.live)
        return live + [e for e in self.events if e not in live]

    def event_meta(self, event: str) -> dict:
        return self.events.get(event) or self.live.get(event, {}).get('meta', {}) or {}

    def is_live_event(self, event: str) -> bool:
        return event in self.live

    def has_forecast(self, event: str) -> bool:
        return event in self.live or any(r['event'] == event for r in self.validation_rows)

    def n_laps(self, event: str) -> Optional[int]:
        s = self.strategy.get(event)
        return int(s['n_laps']) if s and s.get('n_laps') else None

    def compounds_for(self, event: str) -> list[str]:
        if event in self.live:
            return [c['compound'] for c in self.live[event]['compounds']]
        return [r['compound'] for r in self.validation_rows if r['event'] == event]

    def forecast_for(self, event: str, compound: str) -> Forecast:
        if event in self.live:
            for c in self.live[event]['compounds']:
                if c['compound'] == compound:
                    b = c.get('band90') or [None, None]
                    return Forecast(event, compound, c.get('prediction'), (b[0], b[1]), bool(c.get('issued')), c.get('gate', ''), c.get('basis', ''), c.get('n_prac'), 'lock.live')
        for r in self.validation_rows:
            if r['event'] == event and r['compound'] == compound:
                basis = 'issued: cleaned Friday curve x season factor' if r.get('issued') else 'low-degradation fallback (median race degradation of withheld cases)'
                return Forecast(event, compound, r.get('pred_clearstint'), (r.get('lo'), r.get('hi')), bool(r.get('issued')), r.get('gate', ''), basis, r.get('n_prac'), 'lock.validation_rows',
                                observed=r.get('obs'), observed_se=r.get('obs_se'), err=r.get('err_cs'), n_race=r.get('n_race'))
        return Forecast(event, compound, None, (None, None), False, 'no forecast in lock', '', None, 'none')

    def plan_views(self, event: str) -> dict[str, PlanView]:
        s = self.strategy.get(event) or {}
        out = {}
        for name, v in (s.get('views') or {}).items():
            out[name] = PlanView(name, v['plan'], tuple(int(x) for x in v['stints']), int(v['stops']), dict(v.get('crossover') or {}), tuple(v.get('alternatives') or ()), v.get('cost_under_truth_vs_best_s'), v.get('best_under_truth'))
        return out

    def primary_plan(self, event: str) -> Optional[PlanView]:
        views = self.plan_views(event)
        for name in ('Orb v1', 'Cleaned Friday curve', 'Naive fit'):
            if name in views:
                return views[name]
        return None

    def strategy_assumptions(self, event: str) -> dict:
        s = self.strategy.get(event) or {}
        return dict(pit_loss=s.get('pit_loss'), offsets=s.get('offsets', {}), offsets_source=s.get('offsets_source', {}), note=s.get('note'), n_laps=s.get('n_laps'))

    def track_temp_history(self, event: str) -> list[tuple[str, float]]:
        tt = self.event_meta(event).get('track_temp') or {}
        order = ['FP1', 'FP2', 'FP3', 'SQ', 'S', 'Q', 'R']
        return [(s, float(tt[s])) for s in order if s in tt and tt[s] is not None]

    def evolution_for(self, event: str, session: str) -> Optional[float]:
        """Track evolution (s/min) for a session, only if the lock carries it. Race sessions are not in the v1 lock."""
        evo = self.event_meta(event).get('evolution_s_per_min') or {}
        return evo.get(session)

    def rain_in(self, event: str) -> bool:
        return any(bool(v) for v in (self.event_meta(event).get('rain') or {}).values())

    def race_temp_range(self) -> tuple[Optional[float], Optional[float]]:
        temps = [m['track_temp']['R'] for m in self.events.values() if m.get('track_temp', {}).get('R') is not None and m.get('completed')]
        return (min(temps), max(temps)) if temps else (None, None)

    # ---- v2 / fixture blocks -----------------------------------------------------------------------------------------
    def live_predictor_block(self) -> tuple[Optional[dict], str]:
        if self.v2 and self.v2.get('live_predictor'):
            return self.v2['live_predictor'], 'lock_v2'
        if self.fixture and self.fixture.get('live_predictor'):
            return self.fixture['live_predictor'], 'FIXTURE'
        return None, 'none'

    def ghost_block(self) -> tuple[Optional[dict], str]:
        if self.v2 and self.v2.get('ghost_strategy'):
            return self.v2['ghost_strategy'], 'lock_v2'
        if self.fixture and self.fixture.get('ghost_strategy'):
            return self.fixture['ghost_strategy'], 'FIXTURE'
        return None, 'none'

    def support_definition(self) -> dict:
        return (self.v2 or {}).get('shared', {}).get('support_definition') or {}


@_cache
def _read_json(path: str, mtime: float) -> dict:
    with open(path) as f:
        return json.load(f)


def _mtime(p) -> float:
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def load_lock() -> Optional[LockView]:
    """v1 lock is the base; v2 (if present) overlays shared/live_predictor/ghost_strategy; fixture fills gaps (labelled)."""
    v1_asset = A.resolve(P.LOCK_V1)
    v2_asset = A.resolve(P.LOCK_V2)
    fx_asset = A.resolve(P.LOCK_V2_FIXTURE)
    raw = _read_json(str(P.LOCK_V1), _mtime(P.LOCK_V1)) if v1_asset.exists else None
    v2 = _read_json(str(P.LOCK_V2), _mtime(P.LOCK_V2)) if v2_asset.exists else None
    fixture = _read_json(str(P.LOCK_V2_FIXTURE), _mtime(P.LOCK_V2_FIXTURE)) if fx_asset.exists else None
    if raw is None and v2 is None:
        return None
    if raw is None:                       # v2 only: adapt its v1-shaped blocks if any, else empty base
        raw = {k: v2.get(k, {}) for k in ('rules', 'events', 'validation', 'validation_rows', 'live', 'strategy')}
        raw['generated_at'] = v2.get('shared', {}).get('generated_at', '')
    return LockView(raw=raw, version='v2' if v2 else 'v1', path=str(P.LOCK_V2 if v2 else P.LOCK_V1), asset=v2_asset if v2 else v1_asset,
                    v2=v2, v2_asset=v2_asset if v2 else None, fixture=fixture, fixture_asset=fx_asset if fixture else None)
