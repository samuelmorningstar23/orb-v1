"""Race data for the counterfactual engine: one `RaceData` per event (cached), one `DriverLaps` per driver.

Everything here is post-race material (the completed race file feat/<event>_R.csv). It is used by Ghost Strategy /
Race Twin only; the live path never imports this module.

Lap flags. TrackStatus is a string of digits ('1' clear, '2' yellow, '4' SC, '5' red, '6' VSC, '7' VSC ending); a lap
gets the most severe label it carries: RED > SC > VSC > YELLOW > GREEN. Rows can be missing (Monza 2026: laps 4-6
after the lap-3 red flag); a missing lap inside a red-flag gap is labelled RED, any other missing lap MISSING. Lap
times for missing laps are inferred from the session-time gap between the neighbouring rows (t_min is the lap start
time in minutes) and flagged `inferred`, so elapsed time stays continuous for the Race Twin scrubber.

Fuel correction (model_v2.prep_race): y = lap_s - 0.03 s/kg x fuel_kg, fuel_kg = 70 x (1 - (lap - 1) / n_laps).
No evolution term is applied to race laps (model_v2 applies it to practice sessions only).

Positions: the position at the end of lap k is the rank of the lap-k completion time (t_min x 60 + lap_s) among all
drivers that completed lap k; null where the row is missing. Derived from lap order, not from a timing feed.

Stop measurement (field-relative): for each actual stop with in-lap L and out-lap L+1,
    own_in  = y(L)   - median y of the driver's own ok laps in [L-4, L-1]
    own_out = y(L+1) - median y of the driver's own ok laps in [L+2, L+5]
    P_meas  = own - field_excess(lap),  field_excess(lap) = median over drivers not stopping on lap or lap-1 of
              (y(lap) - their own local ok median), which is ~0 under green and large under SC/VSC.
Subtracting the field's excess makes a stop under VSC measure the VSC pit loss rather than the VSC slowness.
A stop under a red flag is free (P_meas = 0): the tyre change happens during the stoppage.

Reference slopes: the race-derived pace-loss reference is model_v2.fit (stint fixed effects + per-compound slope on
TyreLife) on laps prepared exactly as pipeline.py / model_v2.prep_race do; with no driver excluded it reproduces
validation_rows.obs of the v1 lock to 1e-4 (a test asserts this). `reference_slopes(exclude_driver=...)` refits
without the target driver (target_driver_excluded=True in the scenario validation block).
"""
from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from counterfactual import PROTO
import model_v2 as M                       # noqa: E402  (proto/ is on sys.path via counterfactual/__init__)

COMPS = list(M.COMPS)
FUEL_S_PER_KG = float(M.FUEL_S_PER_KG)
RACE_FUEL_KG = float(M.RACE_FUEL_KG)
TRAFFIC_MAX = float(M.TRAFFIC_MAX)
SEVERITY = {'GREEN': 0, 'YELLOW': 1, 'VSC': 2, 'SC': 3, 'RED': 4, 'MISSING': 2}
FROZEN_LABELS = frozenset({'SC', 'VSC', 'RED', 'MISSING'})     # pace deltas frozen in fixed_context mode
WINDOW = 4                                                     # laps either side used for local clean medians


def status_label(ts: Any) -> str:
    s = str(ts)
    if '5' in s:
        return 'RED'
    if '4' in s:
        return 'SC'
    if '6' in s or '7' in s:
        return 'VSC'
    if '2' in s:
        return 'YELLOW'
    return 'GREEN'


def race_csv_path(event: str, feat_dir: Path | None = None) -> Path:
    return (feat_dir or PROTO / 'feat') / f'{event}_R.csv'


# ---------------------------------------------------------------- reference fit (mirrors pipeline.py / model_v2.prep_race)

def prep_race_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Race laps prepared as model_v2.prep_race does when telemetry is healthy (the pace-estimated energy fallback needs
    practice files; it only changes energy_MJ, which the TyreLife fit does not use)."""
    d = df.copy()
    d['clean'] = d['IsAccurate'] & (d['TrackStatus'].astype(str) == '1') & ~d['pit_in'] & ~d['pit_out'] & d['energy_MJ'].notna() & d['Compound'].isin(COMPS) & (~d['deleted'])
    d['stint_id'] = d['session'] + '_' + d['Driver'] + '_' + d['Stint'].fillna(0).astype(int).astype(str)
    r = d[d['session'] == 'R'].copy()
    r['telemetry_ok'] = r['pos_distinct'] >= 100
    r = r.sort_values(['stint_id', 'LapNumber'])
    n_laps = int(r['LapNumber'].max())
    r = r[r['clean'] & ((r['traffic'] <= TRAFFIC_MAX) | (~r['telemetry_ok'] & r['traffic'].isna()))]
    r = r[r.groupby('stint_id')['lap_s'].transform('size') >= 8]
    r = r[r['lap_s'] <= 1.05 * r.groupby('stint_id')['lap_s'].transform('min')]
    fuel = RACE_FUEL_KG * (1 - (r['LapNumber'] - 1) / n_laps)
    r['y'] = r['lap_s'] - FUEL_S_PER_KG * fuel
    return r


def traffic_beta(df: pd.DataFrame) -> dict[str, Any]:
    """Seconds lost per unit traffic share: stint FE + compound slopes + one traffic coefficient on clean green laps
    without the traffic filter. Clamped at zero (traffic cannot make a lap faster)."""
    d = df.copy()
    d['stint_id'] = d['session'] + '_' + d['Driver'] + '_' + d['Stint'].fillna(0).astype(int).astype(str)
    n_laps = int(d['LapNumber'].max())
    ok = d['IsAccurate'] & (d['TrackStatus'].astype(str) == '1') & ~d['pit_in'] & ~d['pit_out'] & ~d['deleted'] & d['Compound'].isin(COMPS) & d['traffic'].notna() & d['lap_s'].notna() & d['TyreLife'].notna()   # TyreLife enters the design matrix: a missing value makes the fit non-finite
    r = d[ok].copy()
    r = r[r.groupby('stint_id')['lap_s'].transform('size') >= 8]
    r = r[r['lap_s'] <= 1.08 * r.groupby('stint_id')['lap_s'].transform('min')]
    if len(r) < 60:
        return dict(beta=0.0, se=float('nan'), n=int(len(r)), note='too few laps; traffic effect set to 0')
    r['y'] = r['lap_s'] - FUEL_S_PER_KG * RACE_FUEL_KG * (1 - (r['LapNumber'] - 1) / n_laps)
    stints = sorted(r['stint_id'].unique())
    X = [(r['stint_id'] == s).astype(float).values for s in stints]
    comps = [c for c in COMPS if (r['Compound'] == c).sum() >= 8]
    X += [((r['Compound'] == c) * r['TyreLife']).values.astype(float) for c in comps]
    X.append(r['traffic'].values.astype(float))
    X = np.column_stack(X)
    y = r['y'].values
    finite = np.isfinite(X).all(axis=1) & np.isfinite(y)        # a single non-finite row would fail the whole decomposition
    if not finite.all():
        X, y = X[finite], y[finite]
    if len(y) < 60 or X.size == 0:
        return dict(beta=0.0, se=float('nan'), n=int(len(y)), note='too few finite laps; traffic effect set to 0')
    try:
        b, *_ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:                                # ill-conditioned race: degrade to no traffic term, never crash the scenario
        return dict(beta=0.0, se=float('nan'), n=int(len(y)), note='traffic fit did not converge; traffic effect set to 0')
    res = y - X @ b
    s2 = float(res @ res) / max(1, len(y) - X.shape[1])
    try:
        se = float(np.sqrt(s2 * np.linalg.pinv(X.T @ X)[-1, -1]))
    except Exception:
        se = float('nan')
    beta = float(b[-1])
    return dict(beta=max(beta, 0.0), beta_raw=beta, se=se, n=int(len(y)), note='s per unit lap share spent < 60 m behind a car; clamped at 0')


# ---------------------------------------------------------------- per-driver laps

@dataclass
class Stop:
    in_lap: int
    out_lap: int
    label_in: str
    label_out: str
    from_compound: str
    to_compound: str
    free: bool                     # under a red flag: the change happens during the stoppage
    own_in: float
    own_out: float
    meas_in: float                 # field-relative in-lap loss (s), NaN when not measurable
    meas_out: float
    measured: bool

    @property
    def meas_total(self) -> float:
        return float(self.meas_in + self.meas_out) if self.measured else float('nan')


@dataclass
class StintRec:
    index: int
    start_lap: int
    end_lap: int
    compound: str
    start_age: int
    set_status: str                # new | scrubbed | used (start_age 1 / 2-3 / >3)
    fresh: Optional[bool]

    @property
    def n_laps(self) -> int:
        return self.end_lap - self.start_lap + 1


def set_status_from_age(start_age: int) -> str:
    return 'new' if start_age <= 1 else ('scrubbed' if start_age <= 3 else 'used')


@dataclass
class DriverLaps:
    """Arrays indexed by lap - 1 for laps 1..n (n = the driver's last completed lap)."""
    driver: str
    n: int
    lap: np.ndarray
    present: np.ndarray
    lap_s: np.ndarray              # observed, or inferred for missing rows
    inferred: np.ndarray
    y: np.ndarray                  # fuel-corrected lap time
    compound: list[str]
    age: np.ndarray                # TyreLife (float), filled through missing rows
    stint: np.ndarray              # stint index 0.. (filled)
    label: list[str]
    pit_in: np.ndarray
    pit_out: np.ndarray
    traffic: np.ndarray            # NaN where unknown
    position: np.ndarray           # NaN where not derivable
    t_end: np.ndarray              # session seconds at lap completion (NaN when missing)
    ok: np.ndarray                 # clean green non-pit accurate lap
    stints: list[StintRec]
    stops: list[Stop]
    retired: bool
    stint_of_lap: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=int))

    @property
    def elapsed(self) -> np.ndarray:
        return np.cumsum(self.lap_s)

    @property
    def pit_laps(self) -> list[int]:
        return [s.end_lap for s in self.stints[:-1]]


def _local_median(y: np.ndarray, ok: np.ndarray, lo: int, hi: int, exclude: Optional[int] = None) -> float:
    """Median of y over ok laps with lap numbers in [lo, hi] (1-based, inclusive), NaN when none."""
    n = len(y)
    idx = [i for i in range(max(lo, 1) - 1, min(hi, n)) if ok[i] and (exclude is None or i != exclude - 1)]
    return float(np.median(y[idx])) if idx else float('nan')


class RaceData:
    """The whole race: frame, flags, positions, field excess, reference slopes, per-driver lap arrays (lazy)."""

    def __init__(self, event: str, path: Path | str | None = None):
        self.event = event
        self.path = Path(path) if path else race_csv_path(event)
        if not self.path.exists():
            raise FileNotFoundError(f'no race file for {event}: {self.path}')
        df = pd.read_csv(self.path)
        df['TrackStatus'] = df['TrackStatus'].astype(str)
        df['LapNumber'] = df['LapNumber'].astype(int)
        df['Stint'] = df['Stint'].fillna(0).astype(int)
        for c in ('pit_in', 'pit_out', 'deleted', 'IsAccurate', 'FreshTyre'):
            df[c] = df[c].astype(bool)
        df = df.sort_values(['Driver', 'LapNumber']).reset_index(drop=True)
        df['label'] = df['TrackStatus'].map(status_label)
        # derived pit-out: the lap after a pit-in lap (FastF1's PitOutTime is missing for about half the stops)
        nxt_driver = df['Driver'].shift(-1)
        nxt_lap = df['LapNumber'].shift(-1)
        follows = (df['Driver'].shift(1) == df['Driver']) & (df['LapNumber'].shift(1) == df['LapNumber'] - 1) & df['pit_in'].shift(1, fill_value=False)
        df['pit_out_d'] = df['pit_out'] | follows | ((df['TyreLife'] <= 1) & (df['LapNumber'] > 1) & (df['Stint'] != df['Stint'].shift(1)) & (df['Driver'] == df['Driver'].shift(1)))
        del nxt_driver, nxt_lap
        self.n_laps = int(df['LapNumber'].max())
        df['fuel_kg'] = RACE_FUEL_KG * (1 - (df['LapNumber'] - 1) / self.n_laps)
        df['y'] = df['lap_s'] - FUEL_S_PER_KG * df['fuel_kg']
        df['ok'] = df['IsAccurate'] & (df['label'] == 'GREEN') & ~df['pit_in'] & ~df['pit_out_d'] & ~df['deleted'] & df['lap_s'].notna()
        df['t_end'] = df['t_min'] * 60.0 + df['lap_s']
        df['position'] = df.groupby('LapNumber')['t_end'].rank(method='first')
        self.df = df
        self.drivers: list[str] = sorted(df['Driver'].unique())
        self.laps_by_driver: dict[str, int] = df.groupby('Driver')['LapNumber'].max().astype(int).to_dict()
        self._prep = prep_race_frame(df)
        self._ref_cache: dict[Optional[str], dict[str, Any]] = {}
        self._traffic: Optional[dict[str, Any]] = None
        self._driver_cache: dict[str, DriverLaps] = {}
        self._field_excess: Optional[np.ndarray] = None
        self._race_labels: Optional[list[str]] = None

    # ---------------------------------------------------------------- race-level schedule
    @property
    def race_labels(self) -> list[str]:
        """Most severe label per lap over the field; laps missing for >= half the field between a RED lap and the
        next present laps are RED (the red-flag gap)."""
        if self._race_labels is None:
            lab = ['GREEN'] * self.n_laps
            g = self.df.groupby('LapNumber')['label'].agg(lambda s: max(s, key=lambda x: SEVERITY[x]))
            for lap_no, l in g.items():
                lab[int(lap_no) - 1] = l
            counts = self.df.groupby('LapNumber')['Driver'].size()
            n_drivers = len(self.drivers)
            for i in range(self.n_laps):
                if counts.get(i + 1, 0) < 0.5 * n_drivers:
                    prev_red = any(lab[j] == 'RED' for j in range(max(0, i - 4), i))
                    lab[i] = 'RED' if prev_red else ('MISSING' if counts.get(i + 1, 0) == 0 else lab[i])
            self._race_labels = lab
        return self._race_labels

    def safety_car_schedule(self) -> list[dict[str, Any]]:
        """[{kind: SC|VSC|RED, start_lap, end_lap}] merged over consecutive laps of the same kind (schema SafetyCarPeriod)."""
        out: list[dict[str, Any]] = []
        for i, l in enumerate(self.race_labels):
            if l not in ('SC', 'VSC', 'RED'):
                continue
            if out and out[-1]['kind'] == l and out[-1]['end_lap'] == i:
                out[-1]['end_lap'] = i + 1
            else:
                out.append(dict(kind=l, start_lap=i + 1, end_lap=i + 1))
        return out

    # ---------------------------------------------------------------- field excess
    @property
    def field_excess(self) -> np.ndarray:
        """Per lap: median over non-stopping drivers of (y - own local ok median). ~0 under green."""
        if self._field_excess is None:
            fe = np.zeros(self.n_laps)
            per_lap: dict[int, list[float]] = {i: [] for i in range(self.n_laps)}
            for drv, x in self.df.groupby('Driver'):
                laps = x['LapNumber'].values
                y = x['y'].values
                ok = x['ok'].values
                stop_laps = set(laps[x['pit_in'].values]) | set(laps[x['pit_out_d'].values])
                lap_to_i = {int(l): i for i, l in enumerate(laps)}
                for i, l in enumerate(laps):
                    if int(l) in stop_laps or (int(l) - 1) in stop_laps or not np.isfinite(y[i]):
                        continue
                    idx = [lap_to_i[k] for k in range(int(l) - WINDOW, int(l) + WINDOW + 1) if k in lap_to_i and k != int(l) and ok[lap_to_i[k]]]
                    if len(idx) >= 2:
                        per_lap[int(l) - 1].append(float(y[i] - np.median(y[idx])))
            for i, vals in per_lap.items():
                fe[i] = float(np.median(vals)) if len(vals) >= 3 else 0.0
            self._field_excess = fe
        return self._field_excess

    # ---------------------------------------------------------------- reference slopes
    def reference_slopes(self, exclude_driver: Optional[str] = None) -> dict[str, Any]:
        """{'slopes': {c: s}, 'se': {c: se}, 'n_laps': n, 'n_stints': k, 'resid_sd': sd, 'excluded': drv}."""
        key = exclude_driver
        if key not in self._ref_cache:
            r = self._prep if exclude_driver is None else self._prep[self._prep['Driver'] != exclude_driver]
            if len(r) < 40:
                self._ref_cache[key] = dict(slopes={}, se={}, n_laps=int(len(r)), n_stints=int(r['stint_id'].nunique()) if len(r) else 0, resid_sd=float('nan'), excluded=exclude_driver)
            else:
                slopes, ses, rs, _ = M.fit(r, 'TyreLife')
                self._ref_cache[key] = dict(slopes=slopes, se=ses, n_laps=int(len(r)), n_stints=int(r['stint_id'].nunique()), resid_sd=float(rs), excluded=exclude_driver)
        return self._ref_cache[key]

    @property
    def traffic(self) -> dict[str, Any]:
        if self._traffic is None:
            self._traffic = traffic_beta(self.df)
        return self._traffic

    def max_stint_laps(self) -> dict[str, int]:
        """Longest stint driven on each compound in this race: the support of the linear (cliff-free) reference."""
        out: dict[str, int] = {}
        for drv in self.drivers:
            for s in self.driver(drv).stints:
                out[s.compound] = max(out.get(s.compound, 0), s.n_laps)
        return out

    # ---------------------------------------------------------------- per-driver laps
    def driver(self, driver: str) -> DriverLaps:
        if driver in self._driver_cache:
            return self._driver_cache[driver]
        if driver not in self.laps_by_driver:
            raise KeyError(f'{driver} did not start {self.event} (drivers: {", ".join(self.drivers)})')
        x = self.df[self.df['Driver'] == driver].set_index('LapNumber')
        n = int(x.index.max())
        laps = np.arange(1, n + 1)
        present = np.array([l in x.index for l in laps])
        lap_s = np.full(n, np.nan)
        y = np.full(n, np.nan)
        age = np.full(n, np.nan)
        traffic = np.full(n, np.nan)
        position = np.full(n, np.nan)
        t_end = np.full(n, np.nan)
        stint = np.full(n, -1, dtype=int)
        compound = [''] * n
        label = ['MISSING'] * n
        pit_in = np.zeros(n, dtype=bool)
        pit_out = np.zeros(n, dtype=bool)
        ok = np.zeros(n, dtype=bool)
        fresh: dict[int, Optional[bool]] = {}
        for l in x.index:
            i = int(l) - 1
            r = x.loc[l]
            lap_s[i] = r['lap_s']
            y[i] = r['y']
            age[i] = r['TyreLife']
            traffic[i] = r['traffic']
            position[i] = r['position']
            t_end[i] = r['t_end']
            stint[i] = int(r['Stint'])
            compound[i] = str(r['Compound'])
            label[i] = r['label']
            pit_in[i] = bool(r['pit_in'])
            pit_out[i] = bool(r['pit_out_d'])
            ok[i] = bool(r['ok'])
            fresh[int(r['Stint'])] = bool(r['FreshTyre'])
        race_lab = self.race_labels
        # fill missing rows: stint / compound / age from the next present lap (a tyre fitted during the gap belongs to
        # the gap's laps), lap time from the session-time gap, label from the race-level schedule
        inferred = np.zeros(n, dtype=bool)
        i = 0
        while i < n:
            if present[i]:
                i += 1
                continue
            j = i
            while j < n and not present[j]:
                j += 1
            # block [i, j) missing; prev = i-1 (present or none), nxt = j (present or none)
            if j < n:
                for k in range(i, j):
                    stint[k] = stint[j]
                    compound[k] = compound[j]
                    age[k] = age[j] - (j - k)
            elif i > 0:
                for k in range(i, j):
                    stint[k] = stint[i - 1]
                    compound[k] = compound[i - 1]
                    age[k] = age[i - 1] + (k - i + 1)
            for k in range(i, j):
                label[k] = race_lab[k] if race_lab[k] in ('RED', 'SC', 'VSC') else 'MISSING'
                inferred[k] = True
            if i > 0 and j < n and np.isfinite(t_end[i - 1]):
                gap = float(x.loc[j + 1, 't_min'] * 60.0 - t_end[i - 1])
                per = gap / (j - i) if gap > 0 else float('nan')
                for k in range(i, j):
                    lap_s[k] = per
                    y[k] = per - FUEL_S_PER_KG * RACE_FUEL_KG * (1 - k / self.n_laps)
            i = j
        # stints
        stints: list[StintRec] = []
        cur = None
        for i in range(n):
            if cur is None or stint[i] != cur.index:
                if cur is not None:
                    cur.end_lap = i
                a0 = int(round(age[i])) if np.isfinite(age[i]) else 1
                cur = StintRec(index=int(stint[i]), start_lap=i + 1, end_lap=n, compound=compound[i], start_age=max(a0, 1), set_status=set_status_from_age(max(a0, 1)), fresh=fresh.get(int(stint[i])))
                stints.append(cur)
        # stops between stints (+ the field-relative measurement)
        fe = self.field_excess
        stops: list[Stop] = []
        for a, b in zip(stints, stints[1:]):
            L = a.end_lap
            li, lo_ = label[L - 1], (label[L] if L < n else 'MISSING')
            free = li == 'RED' or lo_ == 'RED'
            own_in = float(y[L - 1] - _local_median(y, ok, L - WINDOW, L - 1)) if present[L - 1] else float('nan')
            own_out = float(y[L] - _local_median(y, ok, L + 2, L + 1 + WINDOW)) if (L < n and present[L]) else float('nan')
            if free:
                m_in, m_out, measured = 0.0, 0.0, True
            else:
                m_in = own_in - fe[L - 1] if np.isfinite(own_in) else float('nan')
                m_out = own_out - fe[L] if (L < n and np.isfinite(own_out)) else float('nan')
                measured = bool(np.isfinite(m_in) and np.isfinite(m_out))
            stops.append(Stop(in_lap=L, out_lap=L + 1, label_in=li, label_out=lo_, from_compound=a.compound, to_compound=b.compound, free=free,
                              own_in=own_in, own_out=own_out, meas_in=m_in, meas_out=m_out, measured=measured))
        dl = DriverLaps(driver=driver, n=n, lap=laps, present=present, lap_s=lap_s, inferred=inferred, y=y, compound=compound, age=age, stint=stint,
                        label=label, pit_in=pit_in, pit_out=pit_out, traffic=traffic, position=position, t_end=t_end, ok=ok, stints=stints, stops=stops,
                        retired=n < self.n_laps)
        self._driver_cache[driver] = dl
        return dl


@functools.lru_cache(maxsize=16)
def load_race(event: str, path: str | None = None) -> RaceData:
    """Cached per (event, path): the reference and field excess are computed once per process."""
    return RaceData(event, path)


__all__ = ['RaceData', 'DriverLaps', 'StintRec', 'Stop', 'load_race', 'status_label', 'prep_race_frame', 'traffic_beta', 'race_csv_path',
           'set_status_from_age', 'FROZEN_LABELS', 'SEVERITY', 'COMPS', 'FUEL_S_PER_KG', 'RACE_FUEL_KG']
