"""Per-driver unwrapped race distance S(t) on a 1 Hz race clock (roadmap v5 task 0.5).

    race clock   session time minus the red-flag standstills (from 'Aborted' until the restart 'Started'; the cut starts when
                 the last car has settled, so the drive into the pits is kept); t = 0 at the race start
    projection   every non-stale sample onto the canonical path; unwrapped by continuity (wrap into (-L/2, L/2]) with a guard
                 that re-projects locally when a jump is implausible; anchored to the timing lap number at the first lap start
    reconcile    residual S(t_start_k) - (k-1) L at every timing lap start is reported, never silently corrected
    output       t, t_session, S, timing lap, in_pit, pit_progress (arc length along the pit lane), the lap table and the
                 recorded stops (time-relative transit on the pit lane) as compressed float32 with a sha256 sidecar
Quality gate: a driver whose median distinct points per lap is below 100 is refused with the reason written to the meta.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from replay import io as rio
from replay.geometry import TrackPath, PitLane, QualityRefusal, drop_stale, pit_excursions
from replay.sources import PositionSource, MIN_DISTINCT_PER_LAP, STALE_STEP_M, COMPOUND_CODE, feed_quality

MAX_PLAUSIBLE_STEP_M = 150.0     # more than this between consecutive kept samples triggers the local re-projection
MAX_BACKWARD_M = 40.0
SETTLE_WINDOW_S = 10.0
SETTLE_MOVE_M = 3.0
NORMAL_STOP_MAX_S = 90.0
RESTART_WINDOW_S = 120.0          # restart roll-out search window before the 'Started' stamp


@dataclass
class DriverTrajectory:
    driver: str
    event: str
    L: float
    t: np.ndarray                 # race-clock seconds, 1 Hz from 0
    t_session: np.ndarray
    S: np.ndarray                 # unwrapped distance (m), non-decreasing
    lap: np.ndarray               # timing lap number per frame
    in_pit: np.ndarray            # bool per frame: on the pit lane (recorded excursion)
    pit_progress: np.ndarray      # arc length along the pit lane (m), nan when not in the pit lane
    laps: pd.DataFrame            # lap, t_start, t_end (race clock), lap_time, compound, compound_code, tyre_age, stint, pit_in, pit_out, green, accurate, track_status
    stops: list[dict]
    cuts: list[list[float]]
    quality: dict = field(default_factory=dict)
    status: Optional[np.ndarray] = None      # track-status code per frame (1 clear, 2 yellow, 4 SC, 5 red, 6 VSC, 7 VSC ending; 0 unknown)

    def __post_init__(self):
        if self.status is None:
            self.status = np.zeros(len(self.t), dtype=np.int8)

    @property
    def n_laps(self) -> int:
        return int(self.laps['lap'].max()) if len(self.laps) else int(self.S[-1] // self.L) + 1

    @property
    def S_end(self) -> float:
        return float(self.S[-1])

    def t_of_S(self, S_query) -> np.ndarray:
        """t_actual(S): first time the car reaches S (exact inverse of the piecewise-linear S(t), standstills included)."""
        Sk, tk = first_arrival_inverse(self.S, self.t)
        return np.interp(np.atleast_1d(S_query), Sk, tk, left=self.t[0], right=self.t[-1])

    def S_of_t(self, t_query) -> np.ndarray:
        return np.interp(np.atleast_1d(t_query), self.t, self.S)

    def save(self, directory: str | Path) -> str:
        d = Path(directory); d.mkdir(parents=True, exist_ok=True)
        laps = self.laps.copy()
        rec = {c: laps[c].to_numpy() for c in laps.columns}
        return rio.save_npz(d / f'{self.driver}.npz', t=self.t, t_session=self.t_session, S=self.S, lap=self.lap.astype(np.int16), in_pit=self.in_pit.astype(np.uint8),
                            pit_progress=self.pit_progress, status=self.status.astype(np.int8), L=np.float64(self.L), driver=self.driver, event=self.event, cuts=np.asarray(self.cuts, dtype=float).reshape(-1, 2),
                            laps_json=json.loads(laps.to_json(orient='records')), stops_json=[_stop_jsonable(s) for s in self.stops], quality=self.quality,
                            lap_numbers=rec['lap'].astype(np.int16), lap_t_start=rec['t_start'].astype(np.float32), lap_t_end=rec['t_end'].astype(np.float32),
                            lap_compound_code=rec['compound_code'].astype(np.int8), lap_tyre_age=rec['tyre_age'].astype(np.int16), lap_pit_in=rec['pit_in'].astype(np.uint8), lap_pit_out=rec['pit_out'].astype(np.uint8))

    @classmethod
    def load(cls, path: str | Path) -> 'DriverTrajectory':
        z = rio.load_npz(path)
        laps = pd.DataFrame(z['laps_json'])
        stops = [dict(s, tau=np.asarray(s['tau'], dtype=float), s_pit=np.asarray(s['s_pit'], dtype=float)) for s in z['stops_json']]
        return cls(driver=str(z['driver']), event=str(z['event']), L=float(z['L']), t=z['t'].astype(float), t_session=z['t_session'].astype(float), S=z['S'].astype(float),
                   lap=z['lap'].astype(int), in_pit=z['in_pit'].astype(bool), pit_progress=z['pit_progress'].astype(float), laps=laps, stops=stops,
                   cuts=np.asarray(z['cuts'], dtype=float).reshape(-1, 2).tolist(), quality=z.get('quality') or {}, status=z['status'].astype(np.int8) if 'status' in z else None)


def _stop_jsonable(s: dict) -> dict:
    out = {}
    for k, v in s.items():
        if isinstance(v, np.ndarray):
            out[k] = np.round(v, 3).tolist()
        elif isinstance(v, (np.floating, np.integer)):
            out[k] = v.item()
        else:
            out[k] = v
    return out


def first_arrival_inverse(S: np.ndarray, t: np.ndarray, eps: float = 1e-6) -> tuple[np.ndarray, np.ndarray]:
    """Point list (S', t') such that np.interp(S_q, S', t') is the FIRST time the non-decreasing S(t) reaches S_q.
    A standstill (plateau) keeps its start time at the plateau value and its end time at value + eps, so distances beyond the
    plateau interpolate from the moment the car moved again, not from when it stopped."""
    S = np.asarray(S, dtype=float); t = np.asarray(t, dtype=float)
    if len(S) == 0:
        return S, t
    d = np.diff(S) > 0
    first = np.concatenate([[True], d]); last = np.concatenate([d, [True]])
    S_adj = np.where(last & ~first, S + eps, S)
    keep = first | last
    Sk, tk = S_adj[keep], t[keep]
    order = np.argsort(Sk, kind='stable')
    return Sk[order], tk[order]


# ---------------------------------------------------------------- race clock

def race_clock_cuts(source: PositionSource, cap_s: float = 600.0) -> list[list[float]]:
    """Session-time intervals removed from the race clock: each 'Aborted' -> next 'Started', starting when the last car has
    settled (moved < 3 m over 10 s) or cap_s after the abort."""
    ss = source.session_status
    if ss is None or ss.empty:
        return []
    st = ss.sort_values('t')
    cuts = []
    times = st['t'].to_numpy(dtype=float); status = st['status'].astype(str).to_numpy()
    for i, (t_a, s_a) in enumerate(zip(times, status)):
        if s_a != 'Aborted':
            continue
        later = [(t_b, s_b) for t_b, s_b in zip(times[i + 1:], status[i + 1:]) if s_b == 'Started']
        if not later:
            continue
        t_r = later[0][0]
        settle = t_a
        for drv, p in source.positions.items():
            t = p['t'].to_numpy(dtype=float); xy = p[['x', 'y']].to_numpy(dtype=float)
            m = (t >= t_a) & (t <= min(t_a + cap_s, t_r))
            if m.sum() < 5:
                continue
            tt, pp = t[m], xy[m]
            found = None
            for j in range(len(tt)):
                k = np.searchsorted(tt, tt[j] + SETTLE_WINDOW_S)
                if k >= len(tt):
                    break
                seg = pp[j:k + 1]
                if np.hypot(seg[:, 0] - seg[0, 0], seg[:, 1] - seg[0, 1]).max() < SETTLE_MOVE_M:
                    found = tt[j]; break
            if found is None:
                found = min(t_a + cap_s, t_r)
            settle = max(settle, float(found))
        settle = min(settle, t_r - 1.0)
        # the restart: cars roll out before the 'Started' stamp. Within the last RESTART_WINDOW_S before the stamp, end the cut
        # when the third car has moved 5 m from where it stood at the window start (cars shuffled earlier in the standstill do not count)
        moved = []
        w0 = max(settle, t_r - RESTART_WINDOW_S)
        for drv, p in source.positions.items():
            t = p['t'].to_numpy(dtype=float); xy = p[['x', 'y']].to_numpy(dtype=float)
            m = (t >= w0) & (t <= t_r)
            if m.sum() < 5:
                continue
            tt, pp = t[m], xy[m]
            far = np.hypot(pp[:, 0] - pp[0, 0], pp[:, 1] - pp[0, 1]) > 5.0
            if far.any():
                moved.append(float(tt[int(np.argmax(far))]))
        resume = sorted(moved)[min(2, len(moved) - 1)] if moved else t_r
        end = float(min(max(resume, settle + 1.0), t_r))
        cuts.append([float(settle), end])
    return cuts


def make_race_clock(t0: float, cuts: list[list[float]]):
    """Callable session seconds -> race-clock seconds (vectorised), constant inside the cuts."""
    cuts = sorted([list(map(float, c)) for c in cuts])

    def rc(t):
        t = np.asarray(t, dtype=float)
        out = t - t0
        for a, b in cuts:
            out = out - np.clip(t - a, 0.0, b - a)
        return out
    return rc


# ---------------------------------------------------------------- projection

def unwrap_projection(s: np.ndarray, L: float, S0: float) -> tuple[np.ndarray, int]:
    """Continuity unwrap of projected s (mod L) starting at S0; returns (S, n_implausible_steps)."""
    ds = np.diff(s)
    ds = np.mod(ds + L / 2, L) - L / 2
    bad = int(((ds > MAX_PLAUSIBLE_STEP_M) | (ds < -MAX_BACKWARD_M)).sum())
    S = S0 + np.concatenate([[0.0], np.cumsum(ds)])
    return S, bad


def project_samples(track: TrackPath, t: np.ndarray, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """(s, dist, n_reprojected): global nearest projection with a local re-projection where the step is implausible."""
    s, d = track.project(xy[:, 0], xy[:, 1])
    L = track.L
    poly = track.polyline
    n_fix = 0
    for i in range(1, len(s)):
        step = np.mod(s[i] - s[i - 1] + L / 2, L) - L / 2
        dt = max(t[i] - t[i - 1], 1e-3)
        if step > MAX_PLAUSIBLE_STEP_M * max(dt, 1.0) or step < -MAX_BACKWARD_M:
            # search the path locally: vertices within [-40, +150*dt] m of the previous s
            lo = s[i - 1] - MAX_BACKWARD_M; hi = s[i - 1] + MAX_PLAUSIBLE_STEP_M * max(dt, 1.0)
            cand_s = np.arange(lo, hi, track.grid_m)
            pts = poly.xy_at(cand_s)
            dd = np.hypot(pts[:, 0] - xy[i, 0], pts[:, 1] - xy[i, 1])
            j = int(np.argmin(dd))
            if dd[j] < 30.0:
                s[i] = np.mod(cand_s[j], L); d[i] = dd[j]; n_fix += 1
    return s, d, n_fix


# ---------------------------------------------------------------- build

def build_trajectory(source: PositionSource, driver: str, track: TrackPath, pitlane: Optional[PitLane] = None, hz: float = 1.0,
                     cuts: Optional[list[list[float]]] = None, min_distinct: int = MIN_DISTINCT_PER_LAP) -> DriverTrajectory:
    q = feed_quality(source, driver, min_distinct)
    if not q['ok']:
        raise QualityRefusal(q['reason'], dict(event=source.event, event_id=source.event_id, driver=driver, status='refused', reason=q['reason'], quality=q))
    laps = source.driver_laps(driver)
    if laps.empty:
        raise QualityRefusal(f'{driver}: no laps', dict(event=source.event, driver=driver, status='refused', reason='no laps'))
    L = track.L
    cuts = race_clock_cuts(source) if cuts is None else cuts
    t0 = source.race_start()
    rc = make_race_clock(t0, cuts)
    # ---- samples in the race window, stale repeats and cut intervals removed
    p = source.positions[driver]
    t_all = p['t'].to_numpy(dtype=float); xy_all = p[['x', 'y']].to_numpy(dtype=float)
    t_lo = float(np.nanmin(laps['t_start'])) - 2.0; t_hi = float(np.nanmax(laps['t_end'])) + 2.0
    m = (t_all >= t_lo) & (t_all <= t_hi)
    for a, b in cuts:
        m &= ~((t_all > a) & (t_all < b))
    t = t_all[m]; xy = xy_all[m]
    keep = drop_stale(xy, STALE_STEP_M)
    # keep long stationary periods representable: also keep the last sample before a >2 s gap of stale repeats
    idx = np.where(keep)[0]
    t_k, xy_k = t[keep], xy[keep]
    if len(t_k) < 10:
        raise QualityRefusal(f'{driver}: only {len(t_k)} usable samples', dict(event=source.event, driver=driver, status='refused', reason='too few samples'))
    s, d, n_fix = project_samples(track, t_k, xy_k)
    # ---- anchor: first timing lap start with a nearby sample
    first = laps.iloc[0]
    k_first = int(first['lap'])
    j0 = int(np.argmin(np.abs(t_k - first['t_start']))) if np.isfinite(first['t_start']) else 0
    s_anchor = np.mod(s[j0] + L / 2, L) - L / 2
    S_anchor = (k_first - 1) * L + s_anchor
    S_rel, n_bad = unwrap_projection(s, L, 0.0)
    S = S_rel - S_rel[j0] + S_anchor
    # ---- timing reconciliation
    t_rc = rc(t_k)
    lap_rc_start = rc(laps['t_start'].to_numpy(dtype=float)); lap_rc_end = rc(laps['t_end'].to_numpy(dtype=float))
    resid = []
    for k, ts in zip(laps['lap'].to_numpy(dtype=int), lap_rc_start):
        if np.isfinite(ts) and t_rc[0] <= ts <= t_rc[-1]:
            resid.append(float(np.interp(ts, t_rc, S) - (k - 1) * L))
    resid = np.array(resid)
    # ---- 1 Hz grid on the race clock
    t_end_rc = float(np.nanmax(lap_rc_end)) if np.isfinite(lap_rc_end).any() else float(t_rc[-1])
    n_frames = int(np.ceil(max(t_end_rc, t_rc[-1]) * hz)) + 1
    tg = np.arange(n_frames) / hz
    uniq = np.concatenate([[True], np.diff(t_rc) > 0])
    Sg = np.interp(tg, t_rc[uniq], S[uniq], left=S[0], right=S[-1])
    Sg = np.maximum.accumulate(Sg)
    # session time of each frame: inverse of the race clock (piecewise linear with flat cuts -> use the sample mapping)
    tsg = np.interp(tg, t_rc[uniq], t_k[uniq], left=t_k[0] - (t_rc[0] - tg[0]) if len(tg) else t_k[0], right=t_k[-1] + (tg[-1] - t_rc[-1]))
    # ---- timing lap per frame
    lap_nums = laps['lap'].to_numpy(dtype=int)
    starts = np.where(np.isfinite(lap_rc_start), lap_rc_start, np.nan)
    order = np.argsort(np.nan_to_num(starts, nan=np.inf))
    st_sorted = starts[order]; ln_sorted = lap_nums[order]
    fin = np.isfinite(st_sorted)
    lap_frame = np.full(n_frames, int(lap_nums.min()), dtype=int)
    if fin.any():
        pos = np.searchsorted(st_sorted[fin], tg, side='right') - 1
        lap_frame = np.where(pos >= 0, ln_sorted[fin][np.clip(pos, 0, fin.sum() - 1)], int(lap_nums.min()))
    # ---- pit excursions on the pit lane
    in_pit = np.zeros(n_frames, dtype=bool); prog = np.full(n_frames, np.nan)
    stops = []
    if pitlane is not None:
        for e in pit_excursions(source, driver, track):
            sp, dp = pitlane.project(e['xy'][:, 0], e['xy'][:, 1])
            on_lane = dp < 25.0
            if on_lane.sum() < 3:
                continue
            te = rc(e['t']); sp = np.maximum.accumulate(np.where(on_lane, sp, np.nan) if on_lane.all() else np.interp(np.arange(len(sp)), np.where(on_lane)[0], sp[on_lane]))
            t_entry, t_exit = float(te[0]), float(te[-1])
            fm = (tg >= t_entry) & (tg <= t_exit)
            in_pit |= fm
            prog[fm] = np.interp(tg[fm], te, sp)
            S_entry = float(np.interp(t_entry, tg, Sg)); S_exit = float(np.interp(t_exit, tg, Sg))
            red = any(e['t'][0] <= b and e['t'][-1] >= a for a, b in cuts)          # the visit spans a red-flag standstill
            stops.append(dict(lap_in=int(e['lap_in']), t_entry=t_entry, t_exit=t_exit, duration=t_exit - t_entry, normal=bool(8.0 <= t_exit - t_entry <= NORMAL_STOP_MAX_S) and not red, red_flag=red,
                              tau=np.round(te - t_entry, 3), s_pit=np.round(sp, 2), S_entry=S_entry, S_exit=S_exit, s_entry_track=float(e['s_entry']), s_exit_track=float(e['s_exit'])))
    # ---- lap table on the race clock
    lt = laps.copy()
    lt['t_start'] = lap_rc_start; lt['t_end'] = lap_rc_end
    lt['compound_code'] = lt['compound'].map(lambda c: COMPOUND_CODE.get(str(c).upper(), 0)).astype(int)
    lt = lt[['lap', 't_start', 't_end', 'lap_time', 'compound', 'compound_code', 'tyre_age', 'stint', 'pit_in', 'pit_out', 'green', 'accurate', 'track_status']].reset_index(drop=True)
    off = d > 8.0
    if in_pit.any():
        off_share = float(np.mean(off[np.interp(t_rc, tg, in_pit.astype(float)) < 0.5])) if (~in_pit).any() else 0.0
    else:
        off_share = float(off.mean())
    dS = np.diff(Sg) * hz
    quality = dict(q, status='ok', n_samples_used=int(len(t_k)), n_reprojected=int(n_fix), n_implausible_steps=int(n_bad), timing_residual_median_abs_m=round(float(np.median(np.abs(resid))), 2) if len(resid) else None,
                   timing_residual_max_abs_m=round(float(np.max(np.abs(resid))), 2) if len(resid) else None, n_timing_anchors=int(len(resid)), max_frame_speed_mps=round(float(dS.max()), 1) if len(dS) else None,
                   off_path_share_outside_pits=round(off_share, 4), n_frames=int(n_frames), hz=hz, cuts_applied=len(cuts), n_stops=len(stops), stale_share=round(float(1 - keep.mean()), 4))
    status = source.track_status_at(tsg)
    return DriverTrajectory(driver=driver, event=source.event, L=L, t=tg, t_session=tsg, S=Sg, lap=lap_frame.astype(int), in_pit=in_pit, pit_progress=prog, laps=lt, stops=stops, cuts=[list(c) for c in cuts], quality=quality, status=status)


__all__ = ['DriverTrajectory', 'first_arrival_inverse', 'race_clock_cuts', 'make_race_clock', 'unwrap_projection', 'project_samples', 'build_trajectory', 'NORMAL_STOP_MAX_S']
