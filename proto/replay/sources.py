"""PositionSource: the one container geometry, trajectory and timewarp read from.

    laps            DataFrame, one row per (driver, lap): driver, lap, t_start, t_end, lap_time, s1_end, s2_end, pit_in, pit_out,
                    t_pit_in, t_pit_out, green, accurate, compound, tyre_age, stint, track_status  (times in session seconds)
    positions       {driver: DataFrame(t, x, y)} in session seconds and METRES, time-sorted, placeholder (0, 0) rows removed
    track_status    DataFrame(t, status) with the FastF1 codes as strings ('1' clear, '2' yellow, '4' SC, '5' red, '6' VSC, '7' VSC ending)
    session_status  DataFrame(t, status) ('Started', 'Aborted', 'Finished', ...)

Loaders: from_fastf1 (cached session; X/Y are 1/10 m in the feed) and from_mini_race (fixtures/mini_race, already metres).
Feed quality is measured here (distinct points per lap) because both the geometry and the trajectory gate on it.
"""
from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

MIN_DISTINCT_PER_LAP = 100      # quality gate: median distinct (>= 1 m apart) position points per lap
STALE_STEP_M = 1.0              # a sample closer than this to the previous kept sample is a stale repeat
COMPOUND_CODE = {'UNKNOWN': 0, 'SOFT': 1, 'MEDIUM': 2, 'HARD': 3, 'INTERMEDIATE': 4, 'WET': 5}
CODE_COMPOUND = {v: k for k, v in COMPOUND_CODE.items()}

LAP_COLUMNS = ['driver', 'lap', 't_start', 't_end', 'lap_time', 's1_end', 's2_end', 'pit_in', 'pit_out', 't_pit_in', 't_pit_out',
               'green', 'accurate', 'compound', 'tyre_age', 'stint', 'track_status']


@dataclass
class PositionSource:
    event: str
    year: int
    session: str
    n_laps: int
    laps: pd.DataFrame
    positions: dict[str, pd.DataFrame]
    track_status: pd.DataFrame
    session_status: pd.DataFrame
    meta: dict = field(default_factory=dict)

    @property
    def event_id(self) -> str:
        return f'{self.year}_{self.event}'

    @property
    def drivers(self) -> list[str]:
        return sorted(d for d in self.laps['driver'].unique() if d in self.positions)

    def driver_laps(self, driver: str) -> pd.DataFrame:
        d = self.laps[self.laps['driver'] == driver].sort_values('lap')
        return d.reset_index(drop=True)

    def race_start(self) -> float:
        """Session time of the race start: the 'Started' status if present, else the earliest lap-1 start."""
        ss = self.session_status
        started = ss[ss['status'] == 'Started']['t']
        if len(started):
            return float(started.iloc[0])
        first = self.laps[self.laps['lap'] == self.laps['lap'].min()]['t_start']
        return float(np.nanmin(first.to_numpy(dtype=float)))

    def track_status_at(self, t: np.ndarray) -> np.ndarray:
        """Integer status code at session times t (0 when unknown)."""
        ts = self.track_status
        if ts is None or ts.empty:
            return np.zeros(len(t), dtype=np.int8)
        tt = ts['t'].to_numpy(dtype=float)
        codes = pd.to_numeric(ts['status'], errors='coerce').fillna(0).to_numpy(dtype=int)
        idx = np.searchsorted(tt, np.asarray(t, dtype=float), side='right') - 1
        out = np.where(idx >= 0, codes[np.clip(idx, 0, len(codes) - 1)], 0)
        return out.astype(np.int8)

    def summary(self) -> dict:
        return dict(event=self.event, year=self.year, session=self.session, n_laps=int(self.n_laps), drivers=self.drivers,
                    n_lap_rows=int(len(self.laps)), n_position_rows={d: int(len(p)) for d, p in self.positions.items()})


# ---------------------------------------------------------------- quality

def distinct_points_per_lap(pos: pd.DataFrame, laps: pd.DataFrame, stale_step_m: float = STALE_STEP_M) -> np.ndarray:
    """For each lap row (needs t_start, t_end) the number of position samples at least `stale_step_m` from the previous one."""
    t = pos['t'].to_numpy(dtype=float); x = pos['x'].to_numpy(dtype=float); y = pos['y'].to_numpy(dtype=float)
    out = np.zeros(len(laps), dtype=int)
    for i, (a, b) in enumerate(zip(laps['t_start'].to_numpy(dtype=float), laps['t_end'].to_numpy(dtype=float))):
        if not (np.isfinite(a) and np.isfinite(b)) or b <= a:
            continue
        m = (t >= a) & (t < b)
        if m.sum() < 2:
            out[i] = int(m.sum()); continue
        d = np.hypot(np.diff(x[m]), np.diff(y[m]))
        out[i] = 1 + int((d >= stale_step_m).sum())
    return out


def feed_quality(source: PositionSource, driver: str, min_distinct: int = MIN_DISTINCT_PER_LAP) -> dict:
    """Quality record for one driver: median/min distinct points per lap, samples, verdict and reason."""
    pos = source.positions.get(driver)
    laps = source.driver_laps(driver)
    if pos is None or pos.empty or laps.empty:
        return dict(driver=driver, ok=False, median_distinct_per_lap=0, min_distinct_per_lap=0, n_laps=int(len(laps)), n_samples=0,
                    reason=f'{driver}: no position samples')
    counts = distinct_points_per_lap(pos, laps)
    counts = counts[counts > 0] if (counts > 0).any() else counts
    med = int(np.median(counts)) if len(counts) else 0
    ok = med >= min_distinct
    reason = '' if ok else f'{driver}: median {med} distinct position points per lap < {min_distinct} (feed degraded at source)'
    return dict(driver=driver, ok=bool(ok), median_distinct_per_lap=med, min_distinct_per_lap=int(counts.min()) if len(counts) else 0,
                n_laps=int(len(laps)), n_samples=int(len(pos)), reason=reason)


def gate_drivers(source: PositionSource, min_distinct: int = MIN_DISTINCT_PER_LAP) -> tuple[list[str], list[dict]]:
    """(passing drivers, per-driver quality records)."""
    records = [feed_quality(source, d, min_distinct) for d in source.drivers]
    return [r['driver'] for r in records if r['ok']], records


def stale_share(pos: pd.DataFrame, stale_step_m: float = STALE_STEP_M) -> float:
    if len(pos) < 2:
        return 0.0
    d = np.hypot(np.diff(pos['x'].to_numpy(dtype=float)), np.diff(pos['y'].to_numpy(dtype=float)))
    return float((d < stale_step_m).mean())


# ---------------------------------------------------------------- loaders

def _td(v) -> float:
    """pandas Timedelta / NaT -> seconds (nan)."""
    try:
        if pd.isna(v):
            return float('nan')
        return float(v.total_seconds())
    except AttributeError:
        return float(v)


def from_fastf1(year: int, event: str, cache_dir: str | Path, session: str = 'R', *, offline: bool = False) -> PositionSource:
    """Build a PositionSource from a cached FastF1 session (loads telemetry; X/Y 1/10 m -> metres)."""
    import fastf1
    fastf1.Cache.enable_cache(str(cache_dir))
    if offline:
        fastf1.Cache.offline_mode(True)
    s = fastf1.get_session(year, event, session)
    s.load(telemetry=True, laps=True, weather=False, messages=True)
    laps = s.laps
    rows = []
    for _, r in laps.iterrows():
        rows.append(dict(driver=str(r['Driver']), lap=int(r['LapNumber']), t_start=_td(r['LapStartTime']), t_end=_td(r['Time']),
                         lap_time=_td(r['LapTime']), s1_end=_td(r['Sector1SessionTime']), s2_end=_td(r['Sector2SessionTime']),
                         pit_in=bool(pd.notna(r['PitInTime'])), pit_out=bool(pd.notna(r['PitOutTime'])), t_pit_in=_td(r['PitInTime']), t_pit_out=_td(r['PitOutTime']),
                         green=str(r['TrackStatus']) == '1', accurate=bool(r['IsAccurate']), compound=str(r['Compound']) if pd.notna(r['Compound']) else 'UNKNOWN',
                         tyre_age=int(r['TyreLife']) if pd.notna(r['TyreLife']) else 0, stint=int(r['Stint']) if pd.notna(r['Stint']) else 0, track_status=str(r['TrackStatus'])))
    lap_df = pd.DataFrame(rows, columns=LAP_COLUMNS)
    numbers = {str(r['Driver']): str(r['DriverNumber']) for _, r in laps[['Driver', 'DriverNumber']].drop_duplicates().iterrows()}
    positions: dict[str, pd.DataFrame] = {}
    for drv, num in numbers.items():
        p = s.pos_data.get(num)
        if p is None or len(p) == 0:
            continue
        t = p['SessionTime'].dt.total_seconds().to_numpy(dtype=float)
        x = p['X'].to_numpy(dtype=float) / 10.0; y = p['Y'].to_numpy(dtype=float) / 10.0
        keep = np.isfinite(t) & np.isfinite(x) & np.isfinite(y) & ~((x == 0.0) & (y == 0.0))
        if 'Status' in p.columns:
            keep &= (p['Status'].astype(str) != 'OffTrack').to_numpy()
        df = pd.DataFrame(dict(t=t[keep], x=x[keep], y=y[keep])).sort_values('t', kind='stable').drop_duplicates('t').reset_index(drop=True)
        positions[drv] = df
    ts = s.track_status
    track_status = pd.DataFrame(dict(t=ts['Time'].dt.total_seconds().to_numpy(dtype=float), status=ts['Status'].astype(str).to_numpy())) if ts is not None and len(ts) else pd.DataFrame(columns=['t', 'status'])
    ss = s.session_status
    session_status = pd.DataFrame(dict(t=ss['Time'].dt.total_seconds().to_numpy(dtype=float), status=ss['Status'].astype(str).to_numpy())) if ss is not None and len(ss) else pd.DataFrame(columns=['t', 'status'])
    meta = dict(source='fastf1', fastf1_version=fastf1.__version__, event_name=str(s.event['EventName']), date=str(s.date), cache_dir=str(cache_dir),
                position_units='metres (feed 1/10 m divided by 10)', driver_numbers=numbers, offline=offline)
    if offline:
        date = str(s.date)[:10]
        candidates = list(Path(cache_dir).glob(f'{year}/*/{date}_*'))
        cache_files = [p for d in candidates for p in d.glob('*.ff1pkl')]
        meta['cached_source_sha256'] = {str(p.relative_to(cache_dir)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(cache_files)}
    return PositionSource(event=event, year=int(year), session=session, n_laps=int(s.total_laps or lap_df['lap'].max()), laps=lap_df, positions=positions,
                          track_status=track_status, session_status=session_status, meta=meta)


def from_mini_race(directory: str | Path) -> PositionSource:
    """fixtures/mini_race: feat-layout laps (t_min, lap_s, s1..s3) and a 4 Hz Driver,SessionTime_s,X,Y trace in metres."""
    d = Path(directory)
    manifest = json.loads((d / 'manifest.json').read_text())
    laps_raw = pd.read_csv(d / manifest['files']['laps'])
    pos_raw = pd.read_csv(d / manifest['files']['positions'])
    rows = []
    for _, r in laps_raw.iterrows():
        t0 = float(r['t_min']) * 60.0; lt = float(r['lap_s']); t1 = t0 + lt
        s1 = float(r['s1']) if pd.notna(r['s1']) else float('nan'); s2 = float(r['s2']) if pd.notna(r['s2']) else float('nan')
        rows.append(dict(driver=str(r['Driver']), lap=int(r['LapNumber']), t_start=t0, t_end=t1, lap_time=lt,
                         s1_end=t0 + s1 if np.isfinite(s1) else float('nan'), s2_end=t0 + s1 + s2 if np.isfinite(s1) and np.isfinite(s2) else float('nan'),
                         pit_in=bool(r['pit_in']), pit_out=bool(r['pit_out']), t_pit_in=t1 - 5.0 if bool(r['pit_in']) else float('nan'), t_pit_out=t0 + 5.0 if bool(r['pit_out']) else float('nan'),
                         green=str(r['TrackStatus']) == '1', accurate=bool(r['IsAccurate']), compound=str(r['Compound']), tyre_age=int(r['TyreLife']), stint=int(r['Stint']), track_status=str(r['TrackStatus'])))
    lap_df = pd.DataFrame(rows, columns=LAP_COLUMNS)
    positions = {}
    for drv, p in pos_raw.groupby('Driver'):
        positions[str(drv)] = pd.DataFrame(dict(t=p['SessionTime_s'].to_numpy(dtype=float), x=p['X'].to_numpy(dtype=float), y=p['Y'].to_numpy(dtype=float))).sort_values('t').reset_index(drop=True)
    t_end = float(lap_df['t_end'].max())
    track_status = pd.DataFrame(dict(t=[0.0], status=['1']))
    session_status = pd.DataFrame(dict(t=[0.0, t_end], status=['Started', 'Finished']))
    return PositionSource(event=str(manifest['event']), year=2026, session=str(manifest['session']), n_laps=int(manifest['n_laps']), laps=lap_df, positions=positions,
                          track_status=track_status, session_status=session_status, meta=dict(source='mini_race', manifest=manifest, position_units='metres'))


def degrade(source: PositionSource, points_per_lap: int = 26, seed: int = 2026) -> PositionSource:
    """Synthetic copy of a source with the position feed degraded to ~points_per_lap distinct points per lap (stale repeats kept),
    the way the Hungary 2026 race feed arrives. Used by the quality-refusal tests."""
    rng = np.random.default_rng(seed)
    positions = {}
    for drv, p in source.positions.items():
        laps = source.driver_laps(drv)
        t = p['t'].to_numpy(dtype=float); x = p['x'].to_numpy(dtype=float); y = p['y'].to_numpy(dtype=float)
        keep_x = x.copy(); keep_y = y.copy()
        for a, b in zip(laps['t_start'], laps['t_end']):
            idx = np.where((t >= a) & (t < b))[0]
            if len(idx) <= points_per_lap:
                continue
            anchors = np.sort(rng.choice(idx, size=points_per_lap, replace=False))
            last = anchors[0]
            for i in idx:
                if i in anchors:
                    last = i
                keep_x[i] = x[last]; keep_y[i] = y[last]
        positions[drv] = pd.DataFrame(dict(t=t, x=keep_x, y=keep_y))
    return PositionSource(event=source.event, year=source.year, session=source.session, n_laps=source.n_laps, laps=source.laps.copy(), positions=positions,
                          track_status=source.track_status.copy(), session_status=source.session_status.copy(), meta=dict(source.meta, degraded_to=points_per_lap))


__all__ = ['PositionSource', 'MIN_DISTINCT_PER_LAP', 'STALE_STEP_M', 'COMPOUND_CODE', 'CODE_COMPOUND', 'LAP_COLUMNS', 'distinct_points_per_lap',
           'feed_quality', 'gate_drivers', 'stale_share', 'from_fastf1', 'from_mini_race', 'degrade']
