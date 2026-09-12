"""Support status (roadmap 7.0 support fields) computed from lock metadata and the feature files. Display only."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional
from app_v2.services import paths as P
from app_v2.services import asset_repository as A
from app_v2.services import replay_service as RS
from app_v2.services.lock_repository import LockView

IN, NEAR, OUT = 'IN SUPPORT', 'NEAR TRAINING SUPPORT', 'OUT OF SUPPORT, FORECAST WITHHELD'


@dataclass(frozen=True)
class Support:
    track_seen_during_training: Optional[bool]
    driver_seen_during_training: Optional[bool]
    weather_in_training_range: Optional[bool]
    compound_support: Optional[bool]
    season_support: bool
    overall_support_status: str
    abstention_reason: str
    source: str

    def as_dict(self) -> dict:
        return asdict(self)


def driver_seen(driver: Optional[str], exclude_event: Optional[str] = None) -> Optional[bool]:
    if not driver:
        return None
    for ev in A.available_race_events():
        if ev == exclude_event:
            continue
        df = RS.load_race(ev)
        if df is not None and driver in set(df['Driver'].unique()):
            return True
    return False


def support_for(lock: LockView, event: str, driver: Optional[str] = None, compound: Optional[str] = None, scenario_temp: Optional[float] = None, scenario_weather: str = 'dry') -> Support:
    meta = lock.event_meta(event)
    track_seen = bool(meta.get('completed')) and any(r['event'] == event for r in lock.validation_rows)
    seen_drv = driver_seen(driver, exclude_event=None)
    lo, hi = lock.race_temp_range()
    if scenario_weather in ('damp', 'wet', 'variable'):
        weather_ok = False
    elif bool((meta.get('rain') or {}).get('R', False)):
        weather_ok = False
    elif scenario_temp is not None and lo is not None:
        weather_ok = lo <= scenario_temp <= hi
    else:
        weather_ok = True
    offsets = (lock.strategy.get(event) or {}).get('offsets') or meta.get('offsets') or {}
    comp_ok = None if compound is None else compound in offsets
    fc = lock.forecast_for(event, compound) if compound else None
    reason = ''
    race_rain = bool((meta.get('rain') or {}).get('R', False))
    practice_rain = any(bool(v) for k, v in (meta.get('rain') or {}).items() if k != 'R')
    if scenario_weather in ('wet',):
        overall, reason = OUT, 'no wet model has validated'
    elif scenario_weather in ('damp', 'variable'):
        overall, reason = OUT, 'damp / variable conditions are outside the dry training support'
    elif race_rain:
        overall, reason = OUT, 'rain recorded in the race session; dry-only model'
    elif comp_ok is False:
        overall, reason = OUT, f'{compound} has no offset in the lock for this event'
    elif fc is not None and fc.source == 'none':
        overall, reason = OUT, 'no forecast in the lock for this event and compound'
    elif not weather_ok:
        overall, reason = NEAR, f'scenario temperature outside the scored range {lo:.0f} to {hi:.0f} C'
    elif not track_seen:
        overall, reason = NEAR, 'circuit not scored in a previous weekend; forecast rests on same-weekend practice only'
    elif practice_rain:
        overall, reason = NEAR, 'rain in a practice session reduced the clean long-run sample; race was dry'
    else:
        overall = IN
    return Support(track_seen, seen_drv, weather_ok, comp_ok, True, overall, reason, 'lock metadata + feature files')
