"""Reads Workstream 2's counterfactual outputs under proto/out/counterfactual/. Never computes a scenario.

Layout (C2): one directory per scenario with summary.json (scenario block, engine block, events), laps.csv
(per-lap table: lap_delta, cumulative_delta with q10/q90, delta_tyre_mean, delta_pit_mean, pit_state, ...), lap_deltas.json
and ghost_replay.json; plus lattice_<Event>_<mode>.csv with driver x lap x compound summaries. summary.json carries the
sha256 of each asset; `verify_assets` checks the bytes on disk against it through services/asset_repository.
"""
from __future__ import annotations
import json, os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import pandas as pd
from app_v2.services import paths as P
from app_v2.services import asset_repository as A

try:
    import streamlit as st
    _cache = st.cache_data(show_spinner=False)
except Exception:  # pragma: no cover
    def _cache(fn):
        return fn

CF_DIR = P.OUT_DIR / 'counterfactual'
DEFAULT = dict(event='Monza', driver='NOR', lap=24, to_compound='MEDIUM', set_status='new', mode='tyre_only')
MODES = ('tyre_only', 'fixed_context')
REFERENCE_LABEL = 'leave-one-driver-out Sunday reference'


def event_short(event_id: str) -> str:
    return event_id.split('_', 1)[1] if '_' in (event_id or '') else (event_id or '')


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    event: str
    driver: str
    lap: int
    to_compound: str
    set_status: str
    mode: str
    path: str
    summary: dict

    @property
    def scenario(self) -> dict:
        return self.summary.get('scenario', {})

    @property
    def engine(self) -> dict:
        return self.summary.get('engine', {})

    @property
    def stats(self) -> dict:
        return self.scenario.get('summary', {})

    @property
    def finish_delta_s(self) -> Optional[float]:
        return self.stats.get('elapsed_delta_median_s')

    @property
    def q10(self) -> Optional[float]:
        return self.stats.get('elapsed_delta_q10_s')

    @property
    def q90(self) -> Optional[float]:
        return self.stats.get('elapsed_delta_q90_s')

    @property
    def probability_of_gain(self) -> Optional[float]:
        return self.stats.get('probability_of_gain')

    @property
    def oracle_regret_s(self) -> Optional[float]:
        return self.stats.get('oracle_regret_median_s')

    @property
    def claim_scope(self) -> str:
        return self.scenario.get('claim_scope', '')

    @property
    def validation(self) -> dict:
        return self.scenario.get('validation', {})

    @property
    def warnings(self) -> list[str]:
        return list(self.scenario.get('warnings') or [])

    @property
    def curves(self) -> dict:
        return (self.engine.get('curves') or {}).get('by_compound', {})

    @property
    def curve_source(self) -> str:
        return (self.engine.get('curves') or {}).get('source', self.engine.get('curve_source', ''))

    @property
    def actual_plan(self) -> dict:
        return self.scenario.get('actual_plan', {})

    @property
    def cf_plan(self) -> dict:
        return self.scenario.get('counterfactual_plan', {})

    @property
    def from_compound(self) -> str:
        return (self.scenario.get('intervention') or {}).get('from_compound', '')

    @property
    def assets(self) -> dict:
        return self.scenario.get('assets', {})

    @property
    def forecast_hash(self) -> str:
        return (self.scenario.get('forecast_hash') or '').replace('sha256:', '')

    @property
    def model_hash(self) -> str:
        return (self.scenario.get('model_hash') or '').replace('sha256:', '')

    @property
    def generated_at(self) -> str:
        return self.scenario.get('generated_at', '')

    @property
    def safety_car_schedule(self) -> list[dict]:
        return list(self.scenario.get('safety_car_schedule') or [])

    @property
    def assumptions(self) -> dict:
        return self.scenario.get('assumptions', {})

    @property
    def uses_post_race_reference(self) -> bool:
        return bool(self.engine.get('uses_post_race_reference', True))

    def label(self) -> str:
        return f'{self.driver} lap {self.lap} to new {self.to_compound.lower()} ({self.mode.replace("_", " ")})'


@_cache
def _read_summary(path: str, mtime: float) -> dict:
    with open(path) as f:
        return json.load(f)


@_cache
def _read_csv(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_csv(path)


@_cache
def _read_json(path: str, mtime: float) -> dict:
    with open(path) as f:
        return json.load(f)


def _mtime(p: Path) -> float:
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def list_scenarios(event: Optional[str] = None) -> list[Scenario]:
    out = []
    if not CF_DIR.exists():
        return out
    for d in sorted(CF_DIR.iterdir()):
        s = d / 'summary.json'
        if not d.is_dir() or not s.exists():
            continue
        try:
            summary = _read_summary(str(s), _mtime(s))
        except (json.JSONDecodeError, OSError):
            continue
        sc = summary.get('scenario', {})
        ev = event_short(sc.get('event_id', ''))
        if event and ev != event:
            continue
        iv = sc.get('intervention') or {}
        out.append(Scenario(sc.get('scenario_id', d.name), ev, sc.get('driver_id', ''), int(iv.get('lap', 0) or 0), str(iv.get('to_compound', '')).upper(), str(iv.get('set_status', 'new')), sc.get('simulation_mode', 'tyre_only'), str(d), summary))
    return out


def find_scenario(event: str, driver: str, lap: int, to_compound: str, set_status: str = 'new', mode: str = 'tyre_only') -> Optional[Scenario]:
    for s in list_scenarios(event):
        if s.driver == driver and s.lap == int(lap) and s.to_compound == to_compound.upper() and s.set_status == set_status and s.mode == mode:
            return s
    return None


def scenarios_for(event: str, driver: Optional[str] = None) -> list[Scenario]:
    return [s for s in list_scenarios(event) if driver is None or s.driver == driver]


def default_scenario(event: str) -> Optional[Scenario]:
    s = find_scenario(event, DEFAULT['driver'], DEFAULT['lap'], DEFAULT['to_compound'], DEFAULT['set_status'], DEFAULT['mode']) if event == DEFAULT['event'] else None
    if s is None:
        all_ = list_scenarios(event)
        s = next((x for x in all_ if x.mode == 'tyre_only'), all_[0] if all_ else None)
    return s


def verify_assets(sc: Scenario) -> dict[str, dict]:
    """Verify each asset named in summary.json against its recorded sha256 (Workstream 2's hash is the sidecar)."""
    out = {}
    for name, a in sc.assets.items():
        p = P.PROTO_ROOT / a.get('path', '')
        digest = A.sha256_of(p)
        expected = (a.get('sha256') or '').replace('sha256:', '')
        status = 'missing' if digest is None else ('verified' if digest == expected else 'mismatch')
        out[name] = dict(path=str(p), status=status, sha256=digest, short=(digest or '------')[:6])
    return out


def load_laps(sc: Scenario) -> Optional[pd.DataFrame]:
    p = Path(sc.path) / 'laps.csv'
    if not p.exists():
        return None
    return _read_csv(str(p), _mtime(p))


def load_lap_deltas(sc: Scenario) -> list[dict]:
    p = Path(sc.path) / 'lap_deltas.json'
    if not p.exists():
        return []
    return list(_read_json(str(p), _mtime(p)).get('records') or [])


def load_ghost_replay(sc: Scenario) -> list[dict]:
    p = Path(sc.path) / 'ghost_replay.json'
    if not p.exists():
        return []
    return list(_read_json(str(p), _mtime(p)).get('records') or [])


def decomposition(sc: Scenario) -> dict:
    """Y = B + T + P + I + e from the engine block: B is preserved (0 by construction), T tyre, P pit, the rest is I + e."""
    e = sc.engine
    total = e.get('elapsed_delta_mean_s'); tyre = e.get('tyre_delta_mean_s'); pit = e.get('pit_delta_mean_s')
    rest = (total - tyre - pit) if None not in (total, tyre, pit) else None
    return dict(baseline=0.0 if e.get('plan_info') is not None or sc.assumptions.get('driver_baseline_preserved') else None, tyre=tyre, pit=pit, interaction=rest, total=total,
                median=sc.finish_delta_s, identity_check_delta_s=e.get('identity_check_delta_s'), n_samples=e.get('n_samples'), seed=e.get('seed'), sd=e.get('elapsed_delta_sd_s'))


def ghost_delta_at(records: list[dict], lap: int) -> Optional[float]:
    for r in records:
        if int(r.get('lap', 0)) == int(lap):
            return float(r['ghost_elapsed_s']) - float(r['actual_elapsed_s'])
    return None


def lattice_asset(event: str, mode: str = 'tyre_only') -> A.Asset:
    return A.resolve(CF_DIR / f'lattice_{event}_{mode}.csv')


def lattice_lookup(event: str, driver: str, lap: int, to_compound: str, set_status: str = 'new', mode: str = 'tyre_only') -> Optional[dict]:
    p = CF_DIR / f'lattice_{event}_{mode}.csv'
    if not p.exists():
        return None
    df = _read_csv(str(p), _mtime(p))
    m = df[(df['driver'] == driver) & (df['lap'] == int(lap)) & (df['to_compound'] == to_compound.upper()) & (df['set_status'] == set_status)]
    if m.empty:
        return None
    r = m.iloc[0].to_dict()
    r['source'] = f'lattice_{event}_{mode}.csv'
    return r


def lattice_options(event: str, driver: str, mode: str = 'tyre_only') -> tuple[list[int], list[str]]:
    p = CF_DIR / f'lattice_{event}_{mode}.csv'
    if not p.exists():
        return [], []
    df = _read_csv(str(p), _mtime(p)); d = df[df['driver'] == driver]
    return sorted(int(x) for x in d['lap'].unique()), sorted(str(x) for x in d['to_compound'].unique())


def identity_status(event: Optional[str] = None) -> list[dict]:
    out = []
    for s in list_scenarios(event):
        v = s.validation
        out.append(dict(scenario_id=s.scenario_id, event=s.event, driver=s.driver, mode=s.mode, identity_test=v.get('identity_test'), future_leakage_test=v.get('future_leakage_test'),
                        target_driver_excluded=v.get('target_driver_excluded'), sealed_holdout=v.get('sealed_holdout'), identity_check_delta_s=s.engine.get('identity_check_delta_s'), generated_at=s.generated_at, git_sha=s.scenario.get('git_sha')))
    return out
