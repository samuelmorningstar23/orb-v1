"""Training data for Orb TyreFormer: every race and sprint lap of 2023 to 2026, turned into forecast-origin samples.

Lap arithmetic and the clean rule are the live estimator's (live/lapfeed.py, live/estimator.py), so the learned model is
scored on exactly the targets Orb v1 is scored on:
    y       = lap_s - 0.03 x 70 x (1 - (lap - 1) / n_laps)                       (corrected lap time)
    kept    = base_clean(row) and lap_s <= 1.05 x the best base-clean lap of the stint state so far (causal)
    state   = the estimator's stint state: a new state on the first lap, a Stint change, a pit out-lap or a compound
              change; a lap on a non-slick compound has no state and the next lap starts a fresh one
An origin is a lap k whose state holds at least one kept lap (the estimator's 'anchored and n_obs >= 1').
Targets at horizon h: lap k+h of the same driver, kept, same Stint number, tyre age = age_k + h (prefix_eval.py).
Cliff labels: prefix_eval.py's realised CLIFF rule within 3 and 5 laps, with the compound's pre-race prior slope.

Everything an origin's inputs contain is known at the end of lap k: the driver's own laps through k, the weekend's
pre-race forecast (strict leave-one-out SeasonForecaster, never a sealed race in any pool), the Pirelli compound
nomination and the circuit. Future laps appear only in targets and labels.
"""
from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from tyreformer import PROTO, OUT, DATA

SEASON_DIRS = {2023: PROTO / 'feat2023', 2024: PROTO / 'feat2024', 2025: PROTO / 'feat2025', 2026: PROTO / 'feat'}
SEASONS = (2023, 2024, 2025, 2026)
SLICKS = ('SOFT', 'MEDIUM', 'HARD')
FUEL_S_PER_KG, RACE_FUEL_KG, TRAFFIC_MAX, BEST_RATIO = 0.03, 70.0, 0.30, 1.05
SIGMA_Y = 0.40
W = 24            # laps of history per origin (the driver's session, all stints)
H = 10            # forecast horizons 1..H
CACHE = OUT / 'cache'

TOKEN_FEATURES = ('rel_kept', 'kept', 'rel_raw', 'has_time', 'age', 'back', 'same_state', 'lap_frac', 'traffic', 'traffic_missing',
                  'st_green', 'st_yellow', 'st_sc', 'st_vsc', 'st_red', 'pit_in', 'pit_out', 'deleted', 'inaccurate',
                  'c_soft', 'c_medium', 'c_hard', 'c_other', 'energy', 'energy_missing', 'e_lat', 'e_long', 'full_throttle',
                  's1_rel', 's2_rel', 's3_rel', 'feed_degraded', 'fresh', 'field', 'field_n', 'pad')
CONTEXT_FEATURES = ('age', 'n_kept', 'kept_last5', 'laps_remaining', 'n_laps', 'lap_frac', 'stint1', 'stint2', 'stint3p', 'fresh', 'start_age',
                    'track_temp', 'rain', 'cur_soft', 'cur_medium', 'cur_hard', 'cnum_cur', 'cnum_missing', 'cnum_hard', 'cnum_medium', 'cnum_soft',
                    'season_2023', 'season_2024', 'season_2025', 'season_2026', 'sprint',
                    'prior_cur', 'prior_cur_sd', 'prior_cur_issued', 'prior_cur_nprac', 'prior_cur_clean', 'prior_cur_default',
                    'prior_soft', 'prior_soft_sd', 'prior_soft_ok', 'prior_medium', 'prior_medium_sd', 'prior_medium_ok', 'prior_hard', 'prior_hard_sd', 'prior_hard_ok',
                    'off_soft', 'off_medium', 'off_hard', 'ols_slope', 'ols_ok', 'anchor_spread', 'track_temp_practice', 'temp_delta', 'field_now', 'field_n')
FIELD_WINDOW_S = 120.0

# global scalings (fixed constants, not fitted on any split: raw physical units mapped to O(1))
ENERGY_MU, ENERGY_SD = 60.0, 12.0
ELAT_MU, ELAT_SD = 35.0, 10.0
ELONG_MU, ELONG_SD = 25.0, 8.0


# ---------------------------------------------------------------- sealed holdout

def sealed_ids() -> set[str]:
    from evaluation.holdout.evaluator import sealed_race_ids
    return set(sealed_race_ids())


def race_id(season: int, event: str) -> str:
    return f'{season}_{event}'


def weekends(seasons: Iterable[int] = SEASONS, allow_sealed: bool = False, sessions: tuple[str, ...] = ('R',)) -> list[tuple[int, str]]:
    """(season, event) with a race file on disk; sealed weekends are refused unless allow_sealed."""
    sealed = sealed_ids()
    out = []
    for s in seasons:
        for f in sorted(SEASON_DIRS[s].glob('*_R.csv')):
            ev = f.name[:-len('_R.csv')]
            if race_id(s, ev) in sealed and not allow_sealed:
                continue
            out.append((s, ev))
    return out


# ---------------------------------------------------------------- reference data (procured)

def compound_numbers() -> dict[tuple[int, str], dict[str, Optional[int]]]:
    """Pirelli C-number nominations {(season, event): {'HARD': 1, 'MEDIUM': 2, 'SOFT': 3}}; empty when not procured."""
    p = DATA / 'pirelli_compounds.csv'
    out: dict[tuple[int, str], dict[str, Optional[int]]] = {}
    if not p.exists():
        return out
    with p.open(newline='', encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            try:
                key = (int(r['season']), str(r['event']))
            except (KeyError, ValueError):
                continue
            vals = {}
            for c in SLICKS:
                v = (r.get(c.lower()) or '').strip()
                vals[c] = int(v) if v.isdigit() else None
            if str(r.get('verified', '')).strip().lower() not in ('true', '1', 'yes'):
                vals = {c: None for c in SLICKS}
            out[key] = vals
    return out


def circuits(extra: Iterable[str] = ()) -> list[str]:
    """Stable circuit vocabulary: every event name on disk (all seasons, practice included) plus extras; index 0 = unknown."""
    names = set(extra)
    for s in SEASONS:
        for f in SEASON_DIRS[s].glob('*_FP1.csv'):
            names.add(f.name.split('_')[0])
        for f in SEASON_DIRS[s].glob('*_R.csv'):
            names.add(f.name.split('_')[0])
    return ['<unknown>'] + sorted(names)


# ---------------------------------------------------------------- pre-race priors (strict leave-one-out)

def _fc_record(fc) -> dict[str, Any]:
    comps = {}
    for c, f in fc.compounds.items():
        band = f.band90 if f.band90 and all(v is not None and np.isfinite(v) for v in f.band90) else None
        pred = f.prediction if f.prediction is not None and np.isfinite(f.prediction) else None
        comps[c] = dict(prediction=pred, sd=(float((band[1] - band[0]) / (2 * 1.6448536269514722)) if band else None), band90=band, issued=bool(f.issued),
                        n_prac=int(f.n_prac), clean=(float(f.clean) if np.isfinite(f.clean) else None), naive=(float(f.naive) if np.isfinite(f.naive) else None))
    track = fc.meta.get('track_temp', {}) if fc.meta else {}
    practice_temps = [v for k, v in track.items() if k.startswith('FP') and v is not None and np.isfinite(v)]
    return dict(compounds=comps, offsets={k: float(v) for k, v in (fc.offsets or {}).items()}, track_temp_practice=(float(np.mean(practice_temps)) if practice_temps else None),
                pool_events=list(fc.pool_events))


def season_priors(season: int, allow_sealed: bool = False, refresh: bool = False) -> dict[str, dict[str, Any]]:
    """{event: pre-race forecast record} for every weekend of the season with a weekend table, strict leave-one-out:
    the pool is the season's non-sealed completed weekends minus the target. Sealed targets only with allow_sealed
    (their pool is the full development pool; the sealed race never informs anything). Cached on disk."""
    from evaluation.forecast import SeasonForecaster
    CACHE.mkdir(parents=True, exist_ok=True)
    tag = 'with_sealed' if allow_sealed else 'dev'
    path = CACHE / f'priors_{season}_{tag}.json'
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding='utf-8'))
    sealed_season = sorted(r for r in sealed_ids() if r.startswith(f'{season}_'))
    F = SeasonForecaster(SEASON_DIRS[season], season, sealed=sealed_season)
    dev = F.development_events
    out = {}
    for ev in F.events:
        if ev in F.sealed and not allow_sealed:
            continue
        pool = [e for e in dev if e != ev]
        out[ev] = _fc_record(F.forecast(ev, pool, target_obs_in_widening=False))
    path.write_text(json.dumps(out), encoding='utf-8')
    return out


# ---------------------------------------------------------------- per-lap annotation

def status_flags(ts: Any) -> tuple[int, int, int, int, int]:
    s = str(ts)
    red, sc, vsc, yellow = int('5' in s), int('4' in s), int('6' in s or '7' in s), int('2' in s)
    green = int(s == '1')
    return green, yellow, sc, vsc, red


def load_session(season: int, event: str, session: str = 'R', allow_sealed: bool = False) -> Optional[pd.DataFrame]:
    if race_id(season, event) in sealed_ids() and not allow_sealed:
        raise PermissionError(f'{race_id(season, event)} is a sealed holdout weekend')
    p = SEASON_DIRS[season] / f'{event}_{session}.csv'
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if df.empty:
        return None
    df['TrackStatus'] = df['TrackStatus'].astype(str)
    df['LapNumber'] = df['LapNumber'].astype(int)
    df['Stint'] = df['Stint'].fillna(0).astype(int)
    for c in ('pit_in', 'pit_out', 'deleted', 'IsAccurate', 'FreshTyre'):
        df[c] = df[c].fillna(False).astype(bool)
    df['rain'] = df['rain'].fillna(False).astype(bool) if 'rain' in df else False
    return df.sort_values(['Driver', 'LapNumber']).reset_index(drop=True)


def _cnum(v: Optional[int]) -> float:
    """Pirelli C-number scaled to (0, 1]; C0 (2023-2024 range) is a real compound, so 0.0 is reserved for missing."""
    return (int(v) + 1) / 7.0 if v is not None else 0.0


def _finite(v: Any) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def annotate(df: pd.DataFrame, n_laps: Optional[int] = None) -> pd.DataFrame:
    """Adds y, base_ok, kept, state (estimator reset rule), n_obs (kept laps in the state through this lap), sector
    references (causal), status flags. Operates per driver in lap order. n_laps is the scheduled race distance (known
    before the start); by default the last lap number in the file."""
    n_laps = int(n_laps or df['LapNumber'].max())
    d = df.copy()
    d['n_laps'] = n_laps
    fuel = RACE_FUEL_KG * (1.0 - (d['LapNumber'].astype(float) - 1.0) / float(n_laps))
    d['y'] = d['lap_s'] - FUEL_S_PER_KG * fuel
    tr = d['traffic']
    base = (d['lap_s'].notna() & d['TyreLife'].notna() & d['Compound'].isin(SLICKS) & ~d['pit_out'] & ~d['pit_in'] & (d['TrackStatus'] == '1')
            & ~d['deleted'] & d['IsAccurate'] & tr.notna() & (tr <= TRAFFIC_MAX))
    d['base_ok'] = base
    kept = np.zeros(len(d), dtype=bool)
    state = np.full(len(d), -1, dtype=int)
    n_obs = np.zeros(len(d), dtype=int)
    s_rel = np.zeros((len(d), 3), dtype=float)
    lap_s = d['lap_s'].to_numpy(dtype=float)
    comp = d['Compound'].astype(str).to_numpy()
    stint = d['Stint'].to_numpy()
    pit_out = d['pit_out'].to_numpy()
    base_np = base.to_numpy()
    sec = d[['s1', 's2', 's3']].to_numpy(dtype=float)
    sid = 0
    for drv, idx in d.groupby('Driver', sort=False).indices.items():
        idx = np.sort(idx)
        prev_stint, prev_comp, have_state = None, None, False
        best = None
        cnt = 0
        sec_best = np.full(3, np.nan)
        for i in idx:
            if comp[i] not in SLICKS:
                have_state = False            # the estimator raises on a non-slick lap; the next lap starts a fresh state
                state[i] = -1
                prev_stint, prev_comp = None, None
                continue
            new = (not have_state) or stint[i] != prev_stint or bool(pit_out[i]) or comp[i] != prev_comp
            if new:
                sid += 1
                best, cnt = None, 0
                sec_best[:] = np.nan
                have_state = True
            prev_stint, prev_comp = stint[i], comp[i]
            state[i] = sid
            if base_np[i]:
                best = lap_s[i] if best is None else min(best, lap_s[i])
                if lap_s[i] <= BEST_RATIO * best:
                    kept[i] = True
                    cnt += 1
                for j in range(3):
                    if np.isfinite(sec[i, j]):
                        sec_best[j] = sec[i, j] if not np.isfinite(sec_best[j]) else min(sec_best[j], sec[i, j])
            n_obs[i] = cnt
            for j in range(3):
                s_rel[i, j] = (sec[i, j] - sec_best[j]) if (np.isfinite(sec[i, j]) and np.isfinite(sec_best[j])) else 0.0
    d['kept'] = kept
    d['state'] = state
    d['n_obs'] = n_obs
    d[['s1_rel', 's2_rel', 's3_rel']] = np.clip(s_rel, -2.0, 5.0)
    flags = np.array([status_flags(t) for t in d['TrackStatus']], dtype=np.float32) if len(d) else np.zeros((0, 5), dtype=np.float32)
    d[['st_green', 'st_yellow', 'st_sc', 'st_vsc', 'st_red']] = flags
    # field common-mode signal (causal): the median, over other cars' kept laps completed in the FIELD_WINDOW_S seconds
    # before this lap ended, of each such lap's change against that car's own previous (up to 3) kept laps of the state
    y_np = d['y'].to_numpy(dtype=float)
    t_end = d['t_min'].to_numpy(dtype=float) * 60.0 + lap_s
    drivers = d['Driver'].astype(str).to_numpy()
    rel_local = np.full(len(d), np.nan)
    for drv, idx in d.groupby('Driver', sort=False).indices.items():
        hist: dict[int, list[float]] = {}
        for i in np.sort(idx):
            if state[i] < 0 or not kept[i]:
                continue
            h = hist.setdefault(int(state[i]), [])
            if h:
                rel_local[i] = y_np[i] - float(np.mean(h[-3:]))
            h.append(y_np[i])
    ok = np.isfinite(rel_local) & np.isfinite(t_end)
    o = np.argsort(t_end[ok])
    ts, vs, ds = t_end[ok][o], rel_local[ok][o], drivers[ok][o]
    field = np.zeros(len(d))
    field_n = np.zeros(len(d))
    for i in range(len(d)):
        if not np.isfinite(t_end[i]):
            continue
        hi = np.searchsorted(ts, t_end[i], side='right')
        lo = np.searchsorted(ts, t_end[i] - FIELD_WINDOW_S, side='left')
        v = vs[lo:hi][ds[lo:hi] != drivers[i]]
        if len(v):
            field[i], field_n[i] = float(np.median(v)), len(v)
    d['field'] = np.clip(field, -2.0, 2.0)
    d['field_n'] = field_n
    return d


# ---------------------------------------------------------------- samples

@dataclass
class SampleSet:
    tokens: np.ndarray          # [N, W, F_tok] float32
    tok_mask: np.ndarray        # [N, W] bool (True = real lap)
    context: np.ndarray         # [N, F_ctx] float32
    circuit: np.ndarray         # [N] int64
    target: np.ndarray          # [N, H] float32 (y(k+h) - anchor)
    target_mask: np.ndarray     # [N, H] bool
    cum: np.ndarray             # [N, 2] float32 (sum of the first 3 / 5 targets)
    cum_mask: np.ndarray        # [N, 2] bool
    cliff: np.ndarray           # [N, 2] float32 (realised cliff within 3 / 5 laps)
    cliff_mask: np.ndarray      # [N, 2] bool
    anchor: np.ndarray          # [N] float64
    meta: pd.DataFrame          # race_id, season, event, session, driver, lap, stint, compound, age, n_obs, prior_slope

    def __len__(self) -> int:
        return len(self.anchor)

    @staticmethod
    def concat(parts: list['SampleSet']) -> 'SampleSet':
        parts = [p for p in parts if p is not None and len(p)]
        return SampleSet(*(np.concatenate([getattr(p, f) for p in parts]) for f in ('tokens', 'tok_mask', 'context', 'circuit', 'target', 'target_mask', 'cum', 'cum_mask', 'cliff', 'cliff_mask', 'anchor')),
                         meta=pd.concat([p.meta for p in parts], ignore_index=True))

    def subset(self, m: np.ndarray) -> 'SampleSet':
        idx = np.flatnonzero(m) if m.dtype == bool else m
        return SampleSet(self.tokens[idx], self.tok_mask[idx], self.context[idx], self.circuit[idx], self.target[idx], self.target_mask[idx], self.cum[idx], self.cum_mask[idx],
                         self.cliff[idx], self.cliff_mask[idx], self.anchor[idx], self.meta.iloc[idx].reset_index(drop=True))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, **{f: getattr(self, f) for f in ('tokens', 'tok_mask', 'context', 'circuit', 'target', 'target_mask', 'cum', 'cum_mask', 'cliff', 'cliff_mask', 'anchor')})
        self.meta.to_parquet(path.with_suffix('.meta.parquet'), index=False)

    @staticmethod
    def load(path: Path) -> 'SampleSet':
        z = np.load(path)
        return SampleSet(*(z[f] for f in ('tokens', 'tok_mask', 'context', 'circuit', 'target', 'target_mask', 'cum', 'cum_mask', 'cliff', 'cliff_mask', 'anchor')),
                         meta=pd.read_parquet(path.with_suffix('.meta.parquet')))


def _cliff_truth(laps_kept: list[tuple[int, float, float, int]], k: int, stint: int, b0: float, h: int) -> Optional[int]:
    """prefix_eval.py's realised cliff within h laps after k. laps_kept: (lap, y, age, stint) of the driver's kept laps."""
    seq = [(lap, y, age) for (lap, y, age, s) in laps_kept if s == stint and lap <= k + 5]
    future = [x for x in seq if x[0] <= k + h]
    if not future or future[-1][0] < k + 1:
        return None
    hist = [x for x in seq if x[0] <= k + h]
    for i in range(2, len(hist)):
        if hist[i][0] <= k:
            continue
        (l0, y0, a0), (l1, y1, a1), (l2, y2, a2) = hist[i - 2], hist[i - 1], hist[i]
        d1, d2 = (y1 - y0) / max(a1 - a0, 1), (y2 - y1) / max(a2 - a1, 1)
        if d1 > 0 and d2 > 0 and (y2 - y0) > max(2.0 * b0 * max(a2 - a0, 1), 2.0 * math.sqrt(2.0) * SIGMA_Y):
            return 1
    return 0


def build_session(season: int, event: str, session: str, priors: Optional[dict[str, Any]], cnums: dict, circuit_vocab: list[str],
                  allow_sealed: bool = False, all_origins: bool = False, df: Optional[pd.DataFrame] = None, n_laps: Optional[int] = None) -> Optional[SampleSet]:
    """Every origin of one race or sprint session. all_origins also emits laps whose state has no kept lap yet (no anchor:
    anchor = NaN, no targets); used only to render a complete replay, never for training or scoring. `df` replaces the
    file on disk (tests, live feeds); `n_laps` fixes the race distance."""
    if df is None:
        df = load_session(season, event, session, allow_sealed=allow_sealed)
    elif race_id(season, event) in sealed_ids() and not allow_sealed:
        raise PermissionError(f'{race_id(season, event)} is a sealed holdout weekend')
    if df is None:
        return None
    d = annotate(df, n_laps)
    n_laps = int(d['n_laps'].iloc[0])
    comps = (priors or {}).get('compounds', {})
    offsets = (priors or {}).get('offsets', {})
    preds_avail = [v['prediction'] for v in comps.values() if v.get('prediction') is not None]
    default_mean = float(np.median(preds_avail)) if preds_avail else 0.03
    cn = cnums.get((season, event), {})
    t_prac = (priors or {}).get('track_temp_practice')
    circ = circuit_vocab.index(event) if event in circuit_vocab else 0
    toks, masks, ctxs, circs, tgts, tmasks, cums, cmasks, clfs, clmasks, anchors, metas = [], [], [], [], [], [], [], [], [], [], [], []
    for drv, g in d.groupby('Driver', sort=False):
        g = g.sort_values('LapNumber').reset_index(drop=True)
        n = len(g)
        lap = g['LapNumber'].to_numpy()
        y = g['y'].to_numpy(dtype=float)
        kept = g['kept'].to_numpy()
        age = g['TyreLife'].to_numpy(dtype=float)
        stint = g['Stint'].to_numpy()
        state = g['state'].to_numpy()
        n_obs = g['n_obs'].to_numpy()
        comp = g['Compound'].astype(str).to_numpy()
        lap_s = g['lap_s'].to_numpy(dtype=float)
        traffic = g['traffic'].to_numpy(dtype=float)
        fresh = g['FreshTyre'].to_numpy()
        kept_list = [(int(lap[i]), float(y[i]), float(age[i]), int(stint[i])) for i in range(n) if kept[i]]
        by_lap = {int(lap[i]): i for i in range(n)}
        # token matrix for the whole driver session (anchor-free columns); rel columns filled per origin
        T = np.zeros((n, len(TOKEN_FEATURES)), dtype=np.float32)
        fi = {f: j for j, f in enumerate(TOKEN_FEATURES)}
        T[:, fi['kept']] = kept
        T[:, fi['has_time']] = np.isfinite(lap_s)
        T[:, fi['age']] = np.nan_to_num(age, nan=0.0) / 30.0
        T[:, fi['lap_frac']] = (lap - 1) / max(n_laps, 1)
        T[:, fi['traffic']] = np.nan_to_num(traffic, nan=0.0)
        T[:, fi['traffic_missing']] = ~np.isfinite(traffic)
        for f in ('st_green', 'st_yellow', 'st_sc', 'st_vsc', 'st_red', 's1_rel', 's2_rel', 's3_rel'):
            T[:, fi[f]] = g[f].to_numpy(dtype=float)
        T[:, fi['pit_in']] = g['pit_in'].to_numpy()
        T[:, fi['pit_out']] = g['pit_out'].to_numpy()
        T[:, fi['deleted']] = g['deleted'].to_numpy()
        T[:, fi['inaccurate']] = ~g['IsAccurate'].to_numpy()
        T[:, fi['c_soft']] = comp == 'SOFT'
        T[:, fi['c_medium']] = comp == 'MEDIUM'
        T[:, fi['c_hard']] = comp == 'HARD'
        T[:, fi['c_other']] = ~np.isin(comp, SLICKS)
        e = g['energy_MJ'].to_numpy(dtype=float)
        T[:, fi['energy']] = np.clip(np.nan_to_num((e - ENERGY_MU) / ENERGY_SD, nan=0.0), -4, 4)
        T[:, fi['energy_missing']] = ~np.isfinite(e)
        T[:, fi['e_lat']] = np.clip(np.nan_to_num((g['e_lat'].to_numpy(dtype=float) - ELAT_MU) / ELAT_SD, nan=0.0), -4, 4)
        T[:, fi['e_long']] = np.clip(np.nan_to_num((g['e_long'].to_numpy(dtype=float) - ELONG_MU) / ELONG_SD, nan=0.0), -4, 4)
        T[:, fi['full_throttle']] = np.nan_to_num(g['full_throttle'].to_numpy(dtype=float), nan=0.0)
        pos = g['pos_distinct'].to_numpy(dtype=float)
        T[:, fi['feed_degraded']] = np.isfinite(pos) & (pos < 100)
        T[:, fi['fresh']] = fresh
        T[:, fi['field']] = g['field'].to_numpy(dtype=float)
        T[:, fi['field_n']] = np.minimum(g['field_n'].to_numpy(dtype=float), 20.0) / 20.0
        T[:, fi['pad']] = 1.0
        for i in range(n):
            if state[i] < 0:
                continue
            has_obs = n_obs[i] >= 1
            if not has_obs and not all_origins:
                continue
            c = comp[i]
            st_idx = [j for j in range(i + 1) if state[j] == state[i]]
            kept_idx = [j for j in st_idx if kept[j]]
            if has_obs:
                last = kept_idx[-3:]
                anchor = float(np.mean(y[last]))
            else:
                anchor = float('nan')
            lo = max(0, i - W + 1)
            win = T[lo:i + 1].copy()
            rel = y[lo:i + 1] - (anchor if has_obs else 0.0)
            kk = kept[lo:i + 1]
            win[:, fi['rel_kept']] = np.where(kk & has_obs, np.clip(rel, -5, 5), 0.0)
            win[:, fi['rel_raw']] = np.where(np.isfinite(rel) & has_obs, np.clip(rel, -3, 30) / 10.0, 0.0)
            win[:, fi['back']] = (lap[i] - lap[lo:i + 1]) / float(W)
            win[:, fi['same_state']] = state[lo:i + 1] == state[i]
            tok = np.zeros((W, len(TOKEN_FEATURES)), dtype=np.float32)
            msk = np.zeros(W, dtype=bool)
            tok[W - len(win):] = win
            msk[W - len(win):] = True
            # targets
            tg = np.zeros(H, dtype=np.float32)
            tm = np.zeros(H, dtype=bool)
            if has_obs:
                for h in range(1, H + 1):
                    j = by_lap.get(int(lap[i]) + h)
                    if j is None or not kept[j] or stint[j] != stint[i] or not (np.isfinite(age[j]) and np.isfinite(age[i]) and age[j] == age[i] + h):
                        continue
                    tg[h - 1] = y[j] - anchor
                    tm[h - 1] = True
            cu = np.array([tg[:3].sum(), tg[:5].sum()], dtype=np.float32)
            cm = np.array([tm[:3].all(), tm[:5].all()], dtype=bool)
            pc = comps.get(c, {})
            b0 = pc.get('prediction') if pc.get('prediction') is not None else default_mean
            cl = np.zeros(2, dtype=np.float32)
            clm = np.zeros(2, dtype=bool)
            if has_obs:
                for hi, h in enumerate((3, 5)):
                    t = _cliff_truth(kept_list, int(lap[i]), int(stint[i]), float(b0), h)
                    if t is not None:
                        cl[hi], clm[hi] = t, True
            # context
            kx = [j for j in kept_idx]
            ols, ols_ok = 0.0, 0.0
            if len(kx) >= 3 and np.ptp(age[kx]) > 0:
                ols = float(np.polyfit(age[kx], y[kx], 1)[0])
                ols_ok = 1.0
            first = st_idx[0]
            cur_c = cn.get(c) if cn else None
            ctx = dict(age=np.nan_to_num(age[i], nan=0.0) / 30.0, n_kept=len(kept_idx) / 20.0, kept_last5=float(kept[max(0, i - 4):i + 1].mean()),
                       laps_remaining=(n_laps - lap[i]) / 60.0, n_laps=n_laps / 70.0, lap_frac=(lap[i] - 1) / max(n_laps, 1),
                       stint1=float(stint[i] <= 1), stint2=float(stint[i] == 2), stint3p=float(stint[i] >= 3), fresh=float(fresh[i]),
                       start_age=np.nan_to_num(age[first], nan=0.0) / 20.0, track_temp=np.nan_to_num(float(g['track_temp'].iloc[i]), nan=30.0) / 50.0,
                       rain=float(bool(g['rain'].iloc[i])), cur_soft=float(c == 'SOFT'), cur_medium=float(c == 'MEDIUM'), cur_hard=float(c == 'HARD'),
                       cnum_cur=((cur_c + 1) / 7.0 if cur_c is not None else 0.0), cnum_missing=float(cur_c is None),
                       cnum_hard=_cnum(cn.get('HARD')), cnum_medium=_cnum(cn.get('MEDIUM')), cnum_soft=_cnum(cn.get('SOFT')),
                       season_2023=float(season == 2023), season_2024=float(season == 2024), season_2025=float(season == 2025), season_2026=float(season == 2026),
                       sprint=float(session != 'R'),
                       prior_cur=float(np.clip(b0, -0.2, 0.4)) * 10.0, prior_cur_sd=float(np.clip(pc.get('sd') or 0.05, 0.0, 0.3)) * 10.0, prior_cur_issued=float(bool(pc.get('issued'))),
                       prior_cur_nprac=(pc.get('n_prac') or 0) / 100.0, prior_cur_clean=float(np.clip(pc.get('clean') if pc.get('clean') is not None else 0.0, -0.2, 0.4)) * 10.0,
                       prior_cur_default=float(pc.get('prediction') is None),
                       off_soft=float(offsets.get('SOFT', 0.0)), off_medium=float(offsets.get('MEDIUM', 0.0)), off_hard=float(offsets.get('HARD', 0.0)),
                       ols_slope=float(np.clip(ols, -0.5, 1.0)) * 10.0, ols_ok=ols_ok, anchor_spread=(float(np.std(y[kept_idx[-3:]])) if len(kept_idx) >= 2 else 0.0),
                       track_temp_practice=(t_prac / 50.0 if t_prac else 0.0), temp_delta=((float(g['track_temp'].iloc[i]) - t_prac) / 10.0 if (t_prac and _finite(g['track_temp'].iloc[i])) else 0.0),
                       field_now=float(g['field'].iloc[i]), field_n=min(float(g['field_n'].iloc[i]), 20.0) / 20.0)
            for cc in SLICKS:
                v = comps.get(cc, {})
                ok = v.get('prediction') is not None
                ctx[f'prior_{cc.lower()}'] = float(np.clip(v['prediction'], -0.2, 0.4)) * 10.0 if ok else 0.0
                ctx[f'prior_{cc.lower()}_sd'] = float(np.clip(v.get('sd') or 0.05, 0, 0.3)) * 10.0 if ok else 0.0
                ctx[f'prior_{cc.lower()}_ok'] = float(ok)
            toks.append(tok); masks.append(msk); ctxs.append(np.array([ctx[f] for f in CONTEXT_FEATURES], dtype=np.float32)); circs.append(circ)
            tgts.append(tg); tmasks.append(tm); cums.append(cu); cmasks.append(cm); clfs.append(cl); clmasks.append(clm); anchors.append(anchor)
            metas.append((race_id(season, event), season, event, session, drv, int(lap[i]), int(stint[i]), c, float(age[i]) if np.isfinite(age[i]) else np.nan, int(n_obs[i]), float(b0)))
    if not anchors:
        return None
    meta = pd.DataFrame(metas, columns=['race_id', 'season', 'event', 'session', 'driver', 'lap', 'stint', 'compound', 'age', 'n_obs', 'prior_slope'])
    return SampleSet(np.stack(toks), np.stack(masks), np.stack(ctxs), np.array(circs, dtype=np.int64), np.stack(tgts), np.stack(tmasks), np.stack(cums), np.stack(cmasks),
                     np.stack(clfs), np.stack(clmasks), np.array(anchors, dtype=np.float64), meta)


def _build_one(args) -> tuple[str, Optional[SampleSet], float]:
    season, event, session, priors, cnums, vocab, allow_sealed = args
    t0 = time.time()
    try:
        s = build_session(season, event, session, priors, cnums, vocab, allow_sealed=allow_sealed)
    except PermissionError:
        raise
    return f'{season}_{event}_{session}', s, time.time() - t0


def build_all(seasons: Iterable[int] = SEASONS, sessions: tuple[str, ...] = ('R', 'S'), allow_sealed: bool = False, workers: int = 10, quiet: bool = False,
              only_sealed: bool = False) -> SampleSet:
    """Samples for every (non-sealed) race and sprint of the seasons, built in parallel."""
    from concurrent.futures import ProcessPoolExecutor
    cn = compound_numbers()
    vocab = circuits(extra=('Madrid',))
    sealed = sealed_ids()
    jobs = []
    for s in seasons:
        pri = season_priors(s, allow_sealed=allow_sealed)
        for (ss, ev) in weekends([s], allow_sealed=allow_sealed):
            if only_sealed and race_id(ss, ev) not in sealed:
                continue
            for sess in sessions:
                jobs.append((ss, ev, sess, pri.get(ev), cn, vocab, allow_sealed))
    parts = []
    results = map(_build_one, jobs) if workers <= 1 else None
    ex = ProcessPoolExecutor(max_workers=workers) if results is None else None
    try:
        for key, s, dt in (results if results is not None else ex.map(_build_one, jobs)):
            if s is not None:
                parts.append(s)
            if not quiet:
                print(f'{key}: {0 if s is None else len(s)} origins ({dt:.1f} s)', flush=True)
    finally:
        if ex is not None:
            ex.shutdown()
    out = SampleSet.concat(parts)
    if not allow_sealed:
        bad = set(out.meta['race_id']) & sealed
        assert not bad, f'sealed weekends in a development sample set: {sorted(bad)}'
    return out


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default='2023,2024,2025,2026')
    ap.add_argument('--out', default=str(CACHE / 'samples_dev.npz'))
    ap.add_argument('--workers', type=int, default=10)
    a = ap.parse_args()
    t0 = time.time()
    S = build_all([int(x) for x in a.seasons.split(',')], workers=a.workers)
    S.save(Path(a.out))
    print(f'{len(S)} origins, {S.target_mask.sum()} horizon targets, {int(S.cliff_mask[:, 1].sum())} cliff-5 labels ({int(S.cliff[S.cliff_mask[:, 1], 1].sum())} events); {time.time() - t0:.0f} s -> {a.out}')
