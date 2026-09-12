"""Synthetic seasons with known degradation for the evaluation tests.

A weekend = FP1, FP2, FP3 (each driver: one 10-lap run per compound), Q (one lap per compound per driver) and a race
(each driver: stints on two or three compounds, pit in/out laps flagged). Lap times follow the model exactly:
    practice  lap_s = B_d + offset[c] + slope[c] x TyreLife + 0.03 x (40 - 1.1 x (TyreLife - 1))      (model_v2 practice fuel prior)
    race      lap_s = B_d + offset[c] + race_slope[c] x TyreLife + 0.03 x 70 x (1 - (lap - 1) / n_laps) (model_v2 race fuel)
t_min is constant inside a practice session so model_v2.evolution() returns 0 and the practice fit recovers the slopes
exactly (no noise) up to floating point. Same feature columns as feat/<event>_<session>.csv.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ['event', 'session', 'Driver', 'LapNumber', 'Stint', 'Compound', 'TyreLife', 'FreshTyre', 'lap_s', 's1', 's2', 's3', 't_min', 'TrackStatus', 'IsAccurate', 'pit_in', 'pit_out', 'deleted',
           'energy_MJ', 'e_lat', 'e_long', 'traffic', 'full_throttle', 'n_tel', 'pos_distinct', 'stale_share', 'track_temp', 'rain']
SLOPES = {'SOFT': 0.08, 'MEDIUM': 0.05, 'HARD': 0.03}
OFFSETS = {'SOFT': 0.0, 'MEDIUM': 0.6, 'HARD': 1.2}
DRIVERS = ['AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF']
BASE = {'AAA': 90.0, 'BBB': 90.3, 'CCC': 90.6, 'DDD': 90.9, 'EEE': 91.2, 'FFF': 91.5}
RACE_PLANS = [('SOFT', 'MEDIUM'), ('MEDIUM', 'HARD'), ('SOFT', 'HARD'), ('MEDIUM', 'HARD'), ('SOFT', 'MEDIUM', 'HARD'), ('HARD', 'MEDIUM')]


def _row(event, session, drv, lap, stint, comp, age, lap_s, t_min, fresh=True, status='1', pit_in=False, pit_out=False, traffic=0.1, track_temp=35.0):
    return dict(event=event, session=session, Driver=drv, LapNumber=int(lap), Stint=float(stint), Compound=comp, TyreLife=float(age), FreshTyre=bool(fresh), lap_s=float(lap_s),
                s1=lap_s / 3, s2=lap_s / 3, s3=lap_s / 3, t_min=float(t_min), TrackStatus=status, IsAccurate=True, pit_in=bool(pit_in), pit_out=bool(pit_out), deleted=False,
                energy_MJ=55.0, e_lat=30.0, e_long=25.0, traffic=traffic, full_throttle=0.6, n_tel=600, pos_distinct=300, stale_share=0.05, track_temp=track_temp, rain=False)


def practice_lap(drv, comp, age, slopes, offsets, noise, rng):
    fuel = 40.0 - 1.1 * (age - 1)
    return BASE[drv] + offsets[comp] + slopes[comp] * age + 0.03 * fuel + (rng.normal(0, noise) if noise else 0.0)


def race_lap(drv, comp, age, lap, n_laps, slopes, offsets, noise, rng):
    fuel = 70.0 * (1 - (lap - 1) / n_laps)
    return BASE[drv] + offsets[comp] + slopes[comp] * age + 0.03 * fuel + (rng.normal(0, noise) if noise else 0.0)


def make_weekend(feat_dir: Path, event: str, slopes=SLOPES, race_slopes=None, offsets=OFFSETS, n_laps: int = 40, noise: float = 0.0, seed: int = 0, run_len: int = 10):
    rng = np.random.default_rng(seed)
    race_slopes = race_slopes or slopes
    feat_dir = Path(feat_dir)
    feat_dir.mkdir(parents=True, exist_ok=True)
    for si, session in enumerate(('FP1', 'FP2', 'FP3')):
        rows = []
        for drv in DRIVERS:
            lap = 1
            for st, comp in enumerate(('SOFT', 'MEDIUM', 'HARD'), start=1):
                for age in range(1, run_len + 1):
                    rows.append(_row(event, session, drv, lap, st, comp, age, practice_lap(drv, comp, age, slopes, offsets, noise, rng), t_min=30.0))
                    lap += 1
        pd.DataFrame(rows, columns=COLUMNS).to_csv(feat_dir / f'{event}_{session}.csv', index=False)
    rows = []
    for drv in DRIVERS:
        for st, comp in enumerate(('SOFT', 'MEDIUM', 'HARD'), start=1):
            rows.append(_row(event, 'Q', drv, st, st, comp, 1, BASE[drv] + offsets[comp], t_min=10.0 + st))
    pd.DataFrame(rows, columns=COLUMNS).to_csv(feat_dir / f'{event}_Q.csv', index=False)
    rows = []
    for di, drv in enumerate(DRIVERS):
        plan = RACE_PLANS[di % len(RACE_PLANS)]
        k = len(plan)
        bounds = [round(n_laps * (i + 1) / k) for i in range(k - 1)]      # pit in-laps
        stint, age, t = 1, 1, 0.0
        for lap in range(1, n_laps + 1):
            comp = plan[stint - 1]
            pit_in = lap in bounds
            pit_out = (lap - 1) in bounds
            ls = race_lap(drv, comp, age, lap, n_laps, race_slopes, offsets, noise, rng) + (20.0 if pit_in else 0.0) + (10.0 if pit_out else 0.0)
            rows.append(_row(event, 'R', drv, lap, stint, comp, age, ls, t_min=t / 60.0, pit_in=pit_in, pit_out=pit_out))
            t += ls
            if pit_in:
                stint += 1; age = 1
            else:
                age += 1
    pd.DataFrame(rows, columns=COLUMNS).to_csv(feat_dir / f'{event}_R.csv', index=False)


def make_season(feat_dir: Path, events, **kw):
    for i, ev in enumerate(events):
        make_weekend(feat_dir, ev, seed=kw.pop('seed', 0) + i if 'seed' in kw else i, **{k: v for k, v in kw.items() if k != 'seed'})
