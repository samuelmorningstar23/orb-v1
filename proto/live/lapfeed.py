"""Online-safe access to a recorded race (feat/<event>_R.csv) for the live slice.

The boundary rule of roadmap v5 section 3 in code: `LapFeed.row(driver, k)` and `LapFeed.through(driver, k)` only ever
return laps with LapNumber <= k, and `FieldSnapshot.at(k, cutoff_s)` only returns other cars' laps completed at or before
the requesting car's own completion of lap k. Any attempt to hand the estimator a row beyond the lap it is producing raises
`FutureDataError` (tests/live/test_estimator.py::test_feeding_a_future_lap_raises).

Lap arithmetic follows model_v2.prep_race: corrected time y = lap_s - FUEL_S_PER_KG * fuel_kg - evolution * t_min with
fuel_kg = RACE_FUEL_KG * (1 - (lap - 1) / n_laps); race evolution is 0 unless the lock carries a race value (it does not).
Clean-lap rule (causal): IsAccurate, TrackStatus == '1', not pit in/out, not deleted, dry slick compound, traffic <= 0.30
(unknown traffic is not assumed clean), and lap_s <= 1.05 x the stint's best *so far*.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

PROTO = Path(__file__).resolve().parents[1]
FEAT_DIR = PROTO / 'feat'
FUEL_S_PER_KG, RACE_FUEL_KG, TRAFFIC_MAX, BEST_RATIO = 0.03, 70.0, 0.30, 1.05
SLICKS = ('SOFT', 'MEDIUM', 'HARD')
ROW_KEYS = ('event', 'session', 'Driver', 'LapNumber', 'Stint', 'Compound', 'TyreLife', 'lap_s', 't_min', 'TrackStatus', 'IsAccurate', 'pit_in',
            'pit_out', 'deleted', 'traffic', 'pos_distinct', 'stale_share', 'n_tel', 'track_temp', 'rain', 'energy_MJ', 'e_lat', 'e_long', 'full_throttle')


class FutureDataError(AssertionError):
    """Raised when a lap beyond the lap being produced (or a rival lap completed after the data cutoff) is offered."""


def race_csv(event: str) -> Path:
    return FEAT_DIR / f'{event}_R.csv'


def load_race(event: str, path: Optional[Path] = None) -> pd.DataFrame:
    p = path or race_csv(event)
    if not p.exists():
        raise FileNotFoundError(p)
    df = pd.read_csv(p)
    df['TrackStatus'] = df['TrackStatus'].astype(str)
    df['LapNumber'] = df['LapNumber'].astype(int)
    df['Stint'] = df['Stint'].fillna(0).astype(int)
    for c in ('pit_in', 'pit_out', 'deleted', 'IsAccurate'):
        df[c] = df[c].astype(bool)
    if 'rain' in df:
        df['rain'] = df['rain'].fillna(False).astype(bool)
    else:
        df['rain'] = False
    return df.sort_values(['Driver', 'LapNumber']).reset_index(drop=True)


def fuel_kg(lap: int, n_laps: int) -> float:
    return RACE_FUEL_KG * (1.0 - (float(lap) - 1.0) / float(n_laps))


def corrected_time(lap_s: float, lap: int, n_laps: int, t_min: float = 0.0, evolution_s_per_min: float = 0.0) -> float:
    """model_v2 race definition: y = lap_s - 0.03 x fuel_kg - evolution x t_min (evolution 0 for the race unless given)."""
    t = float(t_min) if t_min is not None and math.isfinite(float(t_min)) else 0.0
    return float(lap_s) - FUEL_S_PER_KG * fuel_kg(lap, n_laps) - float(evolution_s_per_min) * t


def is_green(track_status: str) -> bool:
    return str(track_status) == '1'


def base_clean(row: dict) -> tuple[bool, str]:
    """Static part of the clean-lap rule (everything but the 105 % rule, which needs the stint history)."""
    if row.get('lap_s') is None or not math.isfinite(float(row['lap_s'])):
        return False, 'no lap time'
    if row.get('TyreLife') is None or not math.isfinite(float(row['TyreLife'])):
        return False, 'no tyre age'
    if str(row.get('Compound')) not in SLICKS:
        return False, f"compound {row.get('Compound')} outside the dry model"
    if bool(row.get('pit_out')):
        return False, 'pit out-lap'
    if bool(row.get('pit_in')):
        return False, 'pit in-lap'
    if not is_green(row.get('TrackStatus', '1')):
        return False, f"track status {row.get('TrackStatus')} (SC / VSC / yellow / red)"
    if bool(row.get('deleted')):
        return False, 'lap deleted'
    if not bool(row.get('IsAccurate', True)):
        return False, 'lap flagged inaccurate'
    tr = row.get('traffic')
    if tr is None or not math.isfinite(float(tr)):
        return False, 'traffic unknown (no gap data)'
    if float(tr) > TRAFFIC_MAX:
        return False, f'traffic {float(tr):.0%} of lap within 60 m of a car'
    return True, 'kept'


def row_dict(r: pd.Series) -> dict:
    out = {}
    for k in ROW_KEYS:
        if k in r.index:
            v = r[k]
            if isinstance(v, (np.floating, float)):
                v = float(v)
            elif isinstance(v, (np.integer,)):
                v = int(v)
            elif isinstance(v, (np.bool_,)):
                v = bool(v)
            out[k] = v
    return out


@dataclass(frozen=True)
class FieldCar:
    driver: str
    lap: int                 # last lap completed at or before the cutoff
    t_end_s: float           # session time (s) of that completion
    lap_s: float             # that lap's time
    est_t_end_k: float       # estimated completion time of lap k (actual when lap == k)
    projected: bool          # True when lap < k (the car has not finished lap k yet)


class LapFeed:
    """One race file, exposed lap by lap. `k` is always the lap being produced; nothing beyond k leaves this object."""

    def __init__(self, event: str, path: Optional[Path] = None, n_laps: Optional[int] = None):
        self.event = event
        self.df = load_race(event, path)
        self.n_laps = int(n_laps or self.df['LapNumber'].max())
        self._by_driver = {d: g.sort_values('LapNumber').reset_index(drop=True) for d, g in self.df.groupby('Driver')}
        self.df['t_end_s'] = self.df['t_min'].astype(float) * 60.0 + self.df['lap_s'].astype(float)
        lap1 = self.df[self.df['LapNumber'] == 1]
        self.t_ref_s = float((lap1['t_min'].astype(float) * 60.0).min()) if len(lap1) else float((self.df['t_min'].astype(float) * 60.0).min())

    @property
    def drivers(self) -> list[str]:
        return sorted(self._by_driver)

    def laps_of(self, driver: str) -> list[int]:
        return [int(x) for x in self._by_driver[driver]['LapNumber']]

    def through(self, driver: str, k: int) -> pd.DataFrame:
        g = self._by_driver[driver]
        out = g[g['LapNumber'] <= int(k)]
        if len(out) and int(out['LapNumber'].max()) > int(k):
            raise FutureDataError(f'lap beyond {k} exposed for {driver}')
        return out

    def row(self, driver: str, k: int) -> Optional[dict]:
        g = self._by_driver[driver]
        m = g[g['LapNumber'] == int(k)]
        if m.empty:
            return None
        return row_dict(m.iloc[0])

    def field_at(self, driver: str, k: int) -> list[FieldCar]:
        """Other cars as known when `driver` completes lap k: only laps completed at or before that moment are used;
        cars that have not yet completed lap k are projected from their last completed lap and its lap time."""
        me = self.row(driver, k)
        if me is None:
            return []
        cutoff = float(me['t_min']) * 60.0 + float(me['lap_s'])
        cars = []
        for d, g in self._by_driver.items():
            t_end = g['t_min'].astype(float).to_numpy() * 60.0 + g['lap_s'].astype(float).to_numpy()
            laps = g['LapNumber'].to_numpy()
            ok = (t_end <= cutoff + 1e-9) & (laps <= k) & np.isfinite(t_end)
            if not ok.any():
                continue
            i = int(np.flatnonzero(ok)[-1])
            lap_i, t_i, ls = int(laps[i]), float(t_end[i]), float(g['lap_s'].iloc[i])
            if lap_i > k or t_i > cutoff + 1e-9:
                raise FutureDataError(f'{d}: lap {lap_i} completed after the cutoff of lap {k} exposed')
            est = t_i + (k - lap_i) * ls
            cars.append(FieldCar(d, lap_i, t_i, ls, est, lap_i < k))
        return cars


__all__ = ['FutureDataError', 'LapFeed', 'FieldCar', 'load_race', 'race_csv', 'corrected_time', 'fuel_kg', 'base_clean', 'is_green', 'row_dict',
           'FUEL_S_PER_KG', 'RACE_FUEL_KG', 'TRAFFIC_MAX', 'BEST_RATIO', 'SLICKS']
