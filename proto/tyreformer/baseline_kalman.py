"""Orb v1 live-estimator baseline for Orb TyreFormer: the real `LiveTyreStateEstimator` run lap by lap over every driver of
every completed race of 2023 to 2026, recording each lap's state and its 1- to 10-lap predictions, so a learned model can be
scored against it on identical forecast origins and targets (`score`).

Faithful by construction (nothing reimplemented, no estimator parameter changed)
    estimator   live.estimator.LiveTyreStateEstimator() with its defaults, one per driver session, as LiveSession builds it
    context     LiveSession.context_for(k, row), the product's per-lap context, including its support gate
                (live.priors.support_status: a rain flag, or a compound without a prior or a pace offset, makes the lap
                OUT OF SUPPORT, which doubles the compound's prior slope variance at a stint reset); feedback disabled as in
                live/prefix_eval.py; clock None (the clock only stamps timestamps). The hidden --support-gate off forces
                out_of_support False (sensitivity runs only).
    data        LapFeed(event, path=<season dir>/<event>_R.csv).row(driver, k), the only row the estimator sees at lap k
    errors      an update that raises (INTERMEDIATE / WET or a missing compound: no prior) is recorded with `error` set and
                the driver's state restarts, so the next lap opens a fresh stint (LiveSession itself would stop there)

Pre-race priors (default: strictly leave-one-out, pre-race only)
    F = SeasonForecaster(SEASON_DIRS[season], season, sealed=<that season's sealed race ids>), built fresh for every event;
    pool = F.development_events minus the event; fc = F.forecast(event, pool, target_obs_in_widening=False).
    Every compound with a finite prediction and a finite band90 becomes CompoundPrior(mean=prediction, band90), source
    'season_forecaster_loo'; offsets and their sources come from fc; pit loss 21 s; no plan; no forecast hash. The pool
    is leave-one-out within the season, so it includes weekends raced after the event. The forecaster's PoolSpy must show
    neither the event itself nor a sealed race among the pool sources (checked for every event).
    pipeline.band draws from pipeline's module-level generator, so a band depends on whatever ran earlier in the process.
    The generator is re-seeded to its import-time seed (0) before each event's forecast, which makes the priors
    independent of worker scheduling and of the --events subset (only the Monte-Carlo band edges are affected).
    Default prior: a slick compound run in the race without such a prior gets mean = median of the event's finite forecast
    predictions (0.03 s/lap per lap when there are none) and band90 = mean +- 0.12, source 'default_prior'.
    An event outside F.metas (no weekend table: fewer than 40 clean practice laps) is skipped with the reason recorded.
    --lock-priors (hidden; verifies the runner against the product): 2026 events take live.priors.load_priors(event) and
    a feed whose n_laps comes from the lock, exactly as LiveSession.open builds them. Those runs reproduce
    out/live/PREFIX_EVAL.md; other seasons in the same invocation keep the leave-one-out priors.

Recorded per driver lap: season, event, race_id, driver, lap, stint, compound, tyre_age, n_laps, lap_s, y (corrected lap
time), kept, reason, track_status, anchored, n_obs, slope, slope_sd, prior_mean, prior_sd, prior_source, regime, cliff_p3,
cliff_p5, support_status, out_of_support, pred_h{h} / sd_h{h} for h = 1..10 from state.predict(state.tyre_age + h, h)
(NaN until the stint is anchored), error (None when the update succeeded).

Scoring (`score`) uses live/prefix_eval.py's definitions on the recorded rows. An origin is lap k with anchored and
n_obs >= 1. The target k + h must be the same driver's lap k + h, kept, in the same stint, with tyre age = age(k) + h.
next-h error = pred_h - y(k + h). The 3- and 5-lap cumulative errors count only where every target 1..h exists. 90 %
coverage of next-1 and next-3 means |error| <= 1.6448536269514722 x sd.

Sealed weekends (evaluation.holdout.evaluator.sealed_race_ids) are skipped unless --include-sealed. A sealed weekend's
numbers are never printed, and sealed rows never enter a printed or logged score.

CLI (from proto/):  ../.venv/bin/python -m tyreformer.baseline_kalman [--seasons 2023,2024,2025,2026] [--events Monza,...]
                    [--include-sealed] [--workers N]
Outputs: out/tyreformer/kalman/<season>_<event>.parquet (.csv.gz without pyarrow) and out/tyreformer/kalman/_runlog.json,
merged by race id across invocations. --lock-priors writes under out/tyreformer/kalman/lock_priors/.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

PROTO = Path(__file__).resolve().parents[1]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

import numpy as np                                                    # noqa: E402
import pandas as pd                                                   # noqa: E402

from evaluation import SEASON_DIRS, git_sha                           # noqa: E402
from live import ESTIMATOR_LABEL, MODEL_VERSION                       # noqa: E402
from live.lapfeed import SLICKS, LapFeed                              # noqa: E402
from live.priors import Z90, CompoundPrior, EventPriors, load_priors  # noqa: E402
from live.session import LiveSession                                  # noqa: E402

SEASONS = (2023, 2024, 2025, 2026)
LOCK_SEASON = 2026
HORIZONS = tuple(range(1, 11))
CUM_HORIZONS = (3, 5)
COVERAGE_HORIZONS = (1, 3)
SUPPORT_GATES = ('product', 'off')
OUT_DIR = PROTO / 'out' / 'tyreformer' / 'kalman'
LOCK_OUT_DIR = OUT_DIR / 'lock_priors'
RUNLOG_NAME = '_runlog.json'
PREFIX_EVAL_JSON = PROTO / 'out' / 'live' / 'prefix_eval.json'
MAX_WORKERS = 10
PIT_LOSS_S = 21.0
PIPELINE_SEED = 0                  # pipeline.py: rng = np.random.default_rng(0)
DEFAULT_PRIOR_MEAN = 0.03          # s/lap per lap, when the event has no finite forecast prediction at all
DEFAULT_PRIOR_HALF_WIDTH = 0.12    # band90 = mean +- 0.12
SOURCE_LOO = 'season_forecaster_loo'
SOURCE_DEFAULT = 'default_prior'

_STR_COLS = ('event', 'race_id', 'driver', 'compound', 'reason', 'track_status', 'prior_source', 'regime', 'support_status', 'error')
_INT_COLS = ('season', 'lap', 'n_laps', 'n_obs')
_NULLABLE_INT_COLS = ('stint', 'tyre_age')
_BOOL_COLS = ('kept', 'anchored', 'out_of_support')
COLUMNS = (['season', 'event', 'race_id', 'driver', 'lap', 'stint', 'compound', 'tyre_age', 'n_laps', 'lap_s', 'y', 'kept', 'reason', 'track_status',
            'anchored', 'n_obs', 'slope', 'slope_sd', 'prior_mean', 'prior_sd', 'prior_source', 'regime', 'cliff_p3', 'cliff_p5', 'support_status',
            'out_of_support'] + [c for h in HORIZONS for c in (f'pred_h{h}', f'sd_h{h}')] + ['error'])
_FLOAT_COLS = tuple(c for c in COLUMNS if c not in _STR_COLS + _INT_COLS + _NULLABLE_INT_COLS + _BOOL_COLS)


class SkipEvent(Exception):
    """An event the runner does not process, for a documented reason (recorded in the run log; not a failure)."""


def _finite(v: Any) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _msg(e: BaseException) -> str:
    return f"{type(e).__name__}: {e.args[0] if isinstance(e, KeyError) and e.args else e}"


def race_id(season: int, event: str) -> str:
    return f'{int(season)}_{event}'


def sealed_ids() -> set[str]:
    from evaluation.holdout.evaluator import sealed_race_ids
    return set(sealed_race_ids())


# ---------------------------------------------------------------- job plan

def _entry(job: dict, **kw: Any) -> dict[str, Any]:
    e = dict(season=int(job['season']), event=str(job['event']), race_id=str(job['race_id']), sealed=bool(job.get('sealed')), status='pending', skipped=None,
             failure=None, file=None, format=None, n_rows=0, n_drivers=0, n_laps=None, errors=0, error_messages={}, rows_out_of_support=0, prior_mode=None,
             support_gate=None, prior_sources={}, priors={}, default_prior_mean=None, pool_n=None, leakage_check=None, runtime_s=0.0)
    e.update(kw)
    return e


def plan_jobs(seasons: Iterable[int] = SEASONS, events: Optional[Iterable[str]] = None, include_sealed: bool = False) -> tuple[list[dict], list[dict]]:
    """(jobs, skipped) for every race file of the seasons, optionally restricted to `events`. A sealed weekend goes to
    `skipped` unless include_sealed. Nothing is estimated here."""
    sealed = sealed_ids()
    wanted = None if events is None else {str(e) for e in events}
    jobs: list[dict] = []
    skipped: list[dict] = []
    for season in seasons:
        season = int(season)
        if season not in SEASON_DIRS:
            raise ValueError(f'unknown season {season}; known: {sorted(SEASON_DIRS)}')
        for path in sorted(SEASON_DIRS[season].glob('*_R.csv')):
            event = path.name[:-len('_R.csv')]
            if wanted is not None and event not in wanted:
                continue
            rid = race_id(season, event)
            job = dict(season=season, event=event, race_id=rid, sealed=rid in sealed, race_path=str(path))
            if job['sealed'] and not include_sealed:
                skipped.append(_entry(job, status='skipped', skipped='sealed holdout weekend (evaluation/holdout manifest); runs only with --include-sealed'))
            else:
                jobs.append(job)
    return jobs, skipped


# ---------------------------------------------------------------- priors

def race_compounds(feed: LapFeed) -> list[str]:
    """Slick compounds that appear in the race file (decides which default priors exist; no prior value depends on it)."""
    return sorted(set(feed.df['Compound'].dropna().astype(str)) & set(SLICKS))


def _prior_summary(priors: EventPriors) -> dict[str, dict[str, Any]]:
    return {c: dict(mean=float(p.mean), band90=[float(p.band90[0]), float(p.band90[1])], sd=float(p.sd), issued=bool(p.issued), source=p.source)
            for c, p in sorted(priors.compounds.items())}


def priors_from_forecast(fc: Any, season: int, event: str, n_laps: int, compounds_in_race: Iterable[str]) -> tuple[EventPriors, dict[str, Any]]:
    """EventPriors from a WeekendForecast-like object (compounds {c: prediction, band90, issued, gate, basis, n_prac},
    offsets, offsets_source, pool_events), plus the documented default prior for race slicks without a forecast prior."""
    comps: dict[str, CompoundPrior] = {}
    for c in sorted(fc.compounds):
        f = fc.compounds[c]
        band = f.band90
        if _finite(f.prediction) and band is not None and len(band) == 2 and all(_finite(v) for v in band):
            comps[c] = CompoundPrior(c, mean=float(f.prediction), band90=(float(band[0]), float(band[1])), issued=bool(f.issued), gate=str(f.gate),
                                     basis=str(f.basis), source=SOURCE_LOO, n_prac=(int(f.n_prac) if f.n_prac is not None else None))
    preds = [float(f.prediction) for f in fc.compounds.values() if _finite(f.prediction)]
    default_mean = float(np.median(preds)) if preds else DEFAULT_PRIOR_MEAN
    used_default = False
    for c in SLICKS:
        if c in set(compounds_in_race) and c not in comps:
            used_default = True
            comps[c] = CompoundPrior(c, mean=default_mean, band90=(default_mean - DEFAULT_PRIOR_HALF_WIDTH, default_mean + DEFAULT_PRIOR_HALF_WIDTH), issued=False,
                                     gate='no season-forecaster prior for this compound',
                                     basis=(f'default prior: median of the event\'s {len(preds)} finite forecast predictions' if preds else
                                            f'default prior: no finite forecast prediction for the event, {DEFAULT_PRIOR_MEAN} s/lap per lap')
                                     + f', band90 +-{DEFAULT_PRIOR_HALF_WIDTH}',
                                     source=SOURCE_DEFAULT, n_prac=None)
    priors = EventPriors(event=event, event_id=race_id(season, event), n_laps=int(n_laps), compounds=comps,
                         offsets={k: float(v) for k, v in (fc.offsets or {}).items()}, offsets_source=dict(fc.offsets_source or {}), pit_loss=PIT_LOSS_S,
                         plan=None, forecast_hash=None, source=SOURCE_LOO)
    info = dict(prior_mode=SOURCE_LOO, prior_sources={c: p.source for c, p in sorted(comps.items())}, priors=_prior_summary(priors),
                default_prior_mean=(default_mean if used_default else None), pool_n=len(getattr(fc, 'pool_events', []) or []))
    return priors, info


def loo_priors(season: int, event: str, n_laps: int, compounds_in_race: Iterable[str], forecaster: Any = None) -> tuple[EventPriors, dict[str, Any]]:
    """Strict leave-one-out pre-race priors for one race (see the module docstring). Raises SkipEvent without a weekend table."""
    import pipeline
    from evaluation.forecast import SeasonForecaster
    rid = race_id(season, event)
    sealed = sorted(r for r in sealed_ids() if r.startswith(f'{int(season)}_'))
    F = forecaster if forecaster is not None else SeasonForecaster(SEASON_DIRS[int(season)], int(season), sealed=sealed)
    if event not in F.metas:
        raise SkipEvent('no weekend table: fewer than 40 clean practice laps (pipeline rule), so no pre-race forecast exists')
    pool = [e for e in F.development_events if e != event]
    pipeline.rng = np.random.default_rng(PIPELINE_SEED)
    fc = F.forecast(event, pool, target_obs_in_widening=False)
    sources = F.spy.all_sources()
    leaks = sorted(sources & (set(sealed) | {rid}))
    if leaks:
        raise RuntimeError(f'leakage: {leaks} entered the pre-race forecast pool of {rid}')
    priors, info = priors_from_forecast(fc, season, event, n_laps, compounds_in_race)
    info['leakage_check'] = f'pass: {len(sources)} pool source races, neither the event nor a sealed race among them'
    return priors, info


def lock_event_priors(event: str) -> tuple[EventPriors, dict[str, Any]]:
    """The product's priors for a 2026 event (live.priors.load_priors), for the --lock-priors verification."""
    try:
        pr = load_priors(event)
    except KeyError as e:
        raise SkipEvent(f'no lock prior: {_msg(e)}') from None
    return pr, dict(prior_mode='lock', prior_sources={c: p.source for c, p in sorted(pr.compounds.items())}, priors=_prior_summary(pr), pool_n=None,
                    leakage_check='lock_v2 pre-race forecast (live/priors.py strips race-derived keys)', forecast_hash=pr.forecast_hash)


# ---------------------------------------------------------------- the estimator loop

def _state_record(base: dict, state: Any, ctx: Any) -> dict[str, Any]:
    rec = state.laps[-1]
    d = dict(base, stint=int(state.stint), compound=str(state.compound), tyre_age=int(state.tyre_age), n_laps=int(ctx.n_laps), lap_s=float(rec.lap_s),
             y=float(rec.y), kept=bool(rec.kept), reason=str(rec.reason), track_status=str(rec.track_status), anchored=bool(state.anchored),
             n_obs=int(state.n_obs), slope=float(state.slope), slope_sd=float(state.slope_sd), prior_mean=float(state.prior_slope),
             prior_sd=float(state.prior_sd), prior_source=str(state.prior.get('source')), regime=str(state.regime),
             cliff_p3=float(state.derived['cliff_probability_3_laps']), cliff_p5=float(state.derived['cliff_probability_5_laps']),
             support_status=str(ctx.support_status), out_of_support=bool(ctx.out_of_support), error=None)
    for h in HORIZONS:
        mean, sd = state.predict(state.tyre_age + h, h)
        d[f'pred_h{h}'], d[f'sd_h{h}'] = float(mean), float(sd)
    return d


def _error_record(base: dict, row: dict, n_laps: int, ctx: Any, exc: BaseException) -> dict[str, Any]:
    comp = row.get('Compound')
    d = dict(base, stint=(int(row['Stint']) if _finite(row.get('Stint')) else None), compound=(comp if isinstance(comp, str) else None),
             tyre_age=(int(float(row['TyreLife'])) if _finite(row.get('TyreLife')) else None), n_laps=int(n_laps),
             lap_s=(float(row['lap_s']) if _finite(row.get('lap_s')) else math.nan), y=math.nan, kept=False, reason='estimator update raised',
             track_status=str(row.get('TrackStatus', '1')), anchored=False, n_obs=0, slope=math.nan, slope_sd=math.nan, prior_mean=math.nan, prior_sd=math.nan,
             prior_source=None, regime=None, cliff_p3=math.nan, cliff_p5=math.nan, support_status=(str(ctx.support_status) if ctx is not None else None),
             out_of_support=bool(ctx.out_of_support) if ctx is not None else False, error=_msg(exc))
    for h in HORIZONS:
        d[f'pred_h{h}'], d[f'sd_h{h}'] = math.nan, math.nan
    return d


def run_driver(feed: LapFeed, priors: EventPriors, driver: str, season: int, event: str, support_gate: str = 'product') -> list[dict[str, Any]]:
    """One driver's race through the real estimator: LiveSession.run's loop without the optimiser (which never alters the
    state), recording every lap. Lap k's record is produced from rows 1..k only."""
    if support_gate not in SUPPORT_GATES:
        raise ValueError(f'support_gate must be one of {SUPPORT_GATES}')
    session = LiveSession(event, driver, feed, priors, None, feedback_enabled=False, feedback_events=[])
    est = session.estimator
    rid = race_id(season, event)
    state = None
    out: list[dict[str, Any]] = []
    for k in session.laps():
        row = feed.row(driver, k)
        if row is None:
            continue
        base = dict(season=int(season), event=event, race_id=rid, driver=driver, lap=int(k))
        ctx = None
        try:
            ctx = session.context_for(k, row)
            if support_gate == 'off':
                ctx = dataclasses.replace(ctx, out_of_support=False)
            state = est.update(state, row, ctx)
        except Exception as e:           # recorded, and the stint restarts on the next lap
            out.append(_error_record(base, row, session.n_laps, ctx, e))
            state = None
            continue
        out.append(_state_record(base, state, ctx))
    return out


def rows_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame.from_records(records, columns=COLUMNS)
    for c in _INT_COLS:
        df[c] = df[c].astype('int64')
    for c in _NULLABLE_INT_COLS:
        df[c] = pd.to_numeric(df[c], errors='coerce').astype('Int64')
    for c in _BOOL_COLS:
        df[c] = df[c].astype(bool)
    for c in _STR_COLS:
        df[c] = df[c].astype('string')
    for c in _FLOAT_COLS:
        df[c] = pd.to_numeric(df[c], errors='coerce').astype('float64')
    return df


def run_race(feed: LapFeed, priors: EventPriors, season: int, event: str, support_gate: str = 'product', drivers: Optional[Iterable[str]] = None) -> pd.DataFrame:
    recs: list[dict[str, Any]] = []
    for d in (list(drivers) if drivers is not None else feed.drivers):
        recs.extend(run_driver(feed, priors, d, season=season, event=event, support_gate=support_gate))
    return rows_frame(recs)


# ---------------------------------------------------------------- files

def _have_pyarrow() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


def write_frame(df: pd.DataFrame, out_dir: Path, rid: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if _have_pyarrow():
        path = out_dir / f'{rid}.parquet'
        tmp = out_dir / f'.{rid}.parquet.tmp'
        df.to_parquet(tmp, index=False)
    else:
        path = out_dir / f'{rid}.csv.gz'
        tmp = out_dir / f'.{rid}.csv.gz.tmp'
        df.to_csv(tmp, index=False, compression='gzip')
    os.replace(tmp, path)
    return path


def read_frame(path: Path | str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix == '.parquet':
        return pd.read_parquet(p)
    df = pd.read_csv(p, compression='gzip')
    for c in _STR_COLS:
        df[c] = df[c].astype('string')
    for c in _NULLABLE_INT_COLS:
        df[c] = df[c].astype('Int64')
    return df


def load_rows(out_dir: Path | str = OUT_DIR, seasons: Optional[Iterable[int]] = None, include_sealed: bool = False) -> pd.DataFrame:
    """Every recorded race in out_dir (sealed weekends excluded unless include_sealed), concatenated."""
    sealed = sealed_ids()
    want = None if seasons is None else {int(s) for s in seasons}
    frames = []
    for p in sorted(Path(out_dir).glob('*_*.parquet')) + sorted(Path(out_dir).glob('*_*.csv.gz')):
        rid = p.name.split('.')[0]
        season = rid.split('_', 1)[0]
        if not season.isdigit() or (want is not None and int(season) not in want) or (rid in sealed and not include_sealed):
            continue
        frames.append(read_frame(p))
    return pd.concat(frames, ignore_index=True) if frames else rows_frame([])


def _rel(p: Path) -> str:
    try:
        return str(Path(p).resolve().relative_to(PROTO))
    except ValueError:
        return str(Path(p).resolve())


def _abs(s: str) -> Path:
    p = Path(s)
    return p if p.is_absolute() else PROTO / p


def _write_json(path: Path, obj: Any) -> None:
    tmp = path.with_name(f'.{path.name}.tmp')
    tmp.write_text(json.dumps(obj, indent=1, default=_json_default, allow_nan=False), encoding='utf-8')
    os.replace(tmp, path)


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f'not JSON serialisable: {type(o).__name__}')


def _clean_json(obj: Any) -> Any:
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): _clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_json(v) for v in obj]
    return obj


# ---------------------------------------------------------------- one event (process-pool worker)

def run_event(job: dict) -> dict[str, Any]:
    """Priors, the estimator over every driver, the output file; returns the run-log entry. Never raises."""
    t0 = time.time()
    lock = bool(job.get('lock_priors'))
    gate = str(job.get('support_gate', 'product'))
    entry = _entry(job, prior_mode=('lock' if lock else SOURCE_LOO), support_gate=gate)
    try:
        season, event = int(job['season']), str(job['event'])
        path = Path(job['race_path'])
        if lock:
            priors, info = lock_event_priors(event)
            feed = LapFeed(event, path=path, n_laps=priors.n_laps or None)
        else:
            feed = LapFeed(event, path=path)
        if not feed.drivers:
            raise SkipEvent('race file carries no driver codes (Driver column empty): no per-driver feed')
        if not lock:
            priors, info = loo_priors(season, event, feed.n_laps, race_compounds(feed))
        df = run_race(feed, priors, season, event, support_gate=gate)
        out = write_frame(df, Path(job['out_dir']), str(job['race_id']))
        msgs = Counter(df['error'].dropna().astype(str))
        entry.update(info)
        entry.update(status='ok', file=_rel(out), format=('parquet' if out.suffix == '.parquet' else 'csv.gz'), n_rows=int(len(df)),
                     n_drivers=int(df['driver'].nunique()), n_laps=int(priors.n_laps or feed.n_laps), errors=int(sum(msgs.values())),
                     error_messages=dict(msgs.most_common(25)), rows_out_of_support=int(df['out_of_support'].sum()))
    except SkipEvent as e:
        entry.update(status='skipped', skipped=str(e))
    except Exception as e:
        entry.update(status='failed', failure=_msg(e), traceback=traceback.format_exc(limit=8))
    entry['runtime_s'] = round(time.time() - t0, 2)
    return entry


# ---------------------------------------------------------------- scoring

def score(rows_df: pd.DataFrame, horizons: Iterable[int] = (1, 3, 5)) -> dict[str, Any]:
    """live/prefix_eval.py's next-h MAE, 3- and 5-lap cumulative MAE and 90 % coverage (next-1, next-3) on recorded rows."""
    horizons = tuple(int(h) for h in horizons)
    need = sorted(set(horizons) | set(range(1, max(CUM_HORIZONS) + 1)))
    if min(need) < 1 or max(need) > max(HORIZONS):
        raise ValueError(f'horizons must lie in 1..{max(HORIZONS)}')
    df = rows_df.reset_index(drop=True)
    key = ['race_id', 'driver'] if 'race_id' in df.columns else (['season', 'event', 'driver'] if {'season', 'event'} <= set(df.columns) else ['driver'])
    y = pd.to_numeric(df['y'], errors='coerce').to_numpy(dtype=float)
    kept = df['kept'].astype('boolean').fillna(False).to_numpy(dtype=bool) & np.isfinite(y)
    if 'error' in df.columns:
        kept &= df['error'].isna().to_numpy(dtype=bool)
    real = pd.DataFrame({**{c: df[c] for c in key}, 'lap': df['lap'].astype('int64'), '_y': y, '_age': pd.to_numeric(df['tyre_age'], errors='coerce').astype(float),
                         '_stint': pd.to_numeric(df['stint'], errors='coerce').astype(float)})[kept]
    real = real.drop_duplicates(key + ['lap'], keep='last')
    origin = df['anchored'].astype('boolean').fillna(False).to_numpy(dtype=bool) & (pd.to_numeric(df['n_obs'], errors='coerce').fillna(0).to_numpy() >= 1)
    O = df.loc[origin, key + ['lap']].copy().reset_index(drop=True)
    O['lap'] = O['lap'].astype('int64')
    o_stint = pd.to_numeric(df.loc[origin, 'stint'], errors='coerce').astype(float).to_numpy()
    o_age = pd.to_numeric(df.loc[origin, 'tyre_age'], errors='coerce').astype(float).to_numpy()
    err: dict[int, np.ndarray] = {}
    valid: dict[int, np.ndarray] = {}
    for h in need:
        m = O.merge(real.assign(lap=real['lap'] - h), on=key + ['lap'], how='left')
        assert len(m) == len(O), 'target lookup multiplied origins'
        ok = m['_y'].notna().to_numpy() & (m['_stint'].to_numpy() == o_stint) & (m['_age'].to_numpy() == o_age + h)
        pred = pd.to_numeric(df.loc[origin, f'pred_h{h}'], errors='coerce').to_numpy(dtype=float)
        valid[h] = ok
        err[h] = np.where(ok, pred - m['_y'].to_numpy(dtype=float), np.nan)
    out: dict[str, Any] = dict(origins=int(len(O)))
    for h in horizons:
        e = err[h][valid[h]]
        out[f'next{h}_mae'] = float(np.mean(np.abs(e))) if len(e) else None
        out[f'next{h}_n'] = int(len(e))
    for h in CUM_HORIZONS:
        allok = np.logical_and.reduce([valid[j] for j in range(1, h + 1)])
        e = np.sum([err[j] for j in range(1, h + 1)], axis=0)[allok] if len(O) else np.array([])
        out[f'cum{h}_mae'] = float(np.mean(np.abs(e))) if len(e) else None
        out[f'cum{h}_n'] = int(len(e))
    for h in COVERAGE_HORIZONS:
        v = valid[h]
        e = err[h][v]
        sd = pd.to_numeric(df.loc[origin, f'sd_h{h}'], errors='coerce').to_numpy(dtype=float)[v]
        out[f'coverage90_next{h}'] = float(np.mean(np.abs(e) <= Z90 * sd)) if len(e) else None
        out[f'coverage90_next{h}_n'] = int(len(e))
    return out


def fmt_score(s: dict[str, Any]) -> str:
    def f(k: str, pct: bool = False) -> str:
        v = s.get(k)
        return '-' if v is None else (f'{v:.1%}' if pct else f'{v:.4f}')
    head = f"{s['races']} races, {s['rows']} rows, " if 'races' in s else ''
    return (head + f"{s.get('origins')} origins | next1 {f('next1_mae')} (n {s.get('next1_n')}), next3 {f('next3_mae')} (n {s.get('next3_n')}), "
            f"next5 {f('next5_mae')} (n {s.get('next5_n')}) | cum3 {f('cum3_mae')} (n {s.get('cum3_n')}), cum5 {f('cum5_mae')} (n {s.get('cum5_n')}) | "
            f"cov90 next1 {f('coverage90_next1', True)}, next3 {f('coverage90_next3', True)}")


def pooled_scores(entries: dict[str, dict], horizons: Iterable[int] = (1, 3, 5)) -> dict[str, Any]:
    """Per-season and all-season pooled scores over the recorded files of processed, NON-sealed entries (aggregate only)."""
    frames: dict[int, list[pd.DataFrame]] = {}
    for e in entries.values():
        if e.get('status') != 'ok' or e.get('sealed') or not e.get('file'):
            continue
        p = _abs(e['file'])
        if p.exists():
            frames.setdefault(int(e['season']), []).append(read_frame(p))
    out: dict[str, Any] = {}
    for season in sorted(frames):
        d = pd.concat(frames[season], ignore_index=True)
        out[str(season)] = dict(races=int(d['race_id'].nunique()), rows=int(len(d)), **score(d, horizons))
    if len(frames) > 1:
        d = pd.concat([x for fs in frames.values() for x in fs], ignore_index=True)
        out['all'] = dict(races=int(d['race_id'].nunique()), rows=int(len(d)), **score(d, horizons))
    return out


# ---------------------------------------------------------------- run log

POLICY = dict(
    estimator='live.estimator.LiveTyreStateEstimator() defaults; context from LiveSession.context_for (support gate from live.priors.support_status); '
              'feedback disabled; clock None; rows from LapFeed.row(driver, k)',
    priors_loo='SeasonForecaster(season dir, season, sealed=season sealed ids) per event; pool = development events minus the event; '
               'forecast(event, pool, target_obs_in_widening=False); pipeline.rng re-seeded to 0 before each forecast; prior = prediction with band90; '
               'pit loss 21 s; offsets from the forecast',
    default_prior=f'slick compound in the race without a forecast prior: mean = median of the event\'s finite forecast predictions '
                  f'({DEFAULT_PRIOR_MEAN} if none), band90 = mean +- {DEFAULT_PRIOR_HALF_WIDTH}',
    errors='an update that raises is recorded with error set; the driver state restarts (fresh stint on the next lap)',
    sealed='sealed weekends skipped unless --include-sealed; sealed rows never enter pooled scores',
    scoring='live/prefix_eval.py definitions (origin anchored and n_obs >= 1; target kept, same stint, tyre age + h; cumulative only where all '
            'targets exist; coverage |err| <= 1.6448536269514722 sd)')


def update_runlog(out_dir: Path, entries: dict[str, dict], options: dict[str, Any], started: datetime, wall_s: float) -> dict[str, Any]:
    """Merge this invocation's entries into out_dir/_runlog.json by race id and recompute the totals and pooled scores."""
    path = Path(out_dir) / RUNLOG_NAME
    old: dict[str, Any] = {}
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            old = {}
    events = dict(old.get('events') or {})
    for rid, e in entries.items():
        e = dict(e)
        if e.get('sealed'):
            e['priors'] = {}             # no sealed-weekend values in the log, only which source each compound used
            e['default_prior_mean'] = None
        events[rid] = e
    events = dict(sorted(events.items()))
    ok = [e for e in events.values() if e['status'] == 'ok']
    totals = dict(events_listed=len(events), processed=len(ok), skipped=sum(e['status'] == 'skipped' for e in events.values()),
                  failed=sum(e['status'] == 'failed' for e in events.values()), rows=sum(e['n_rows'] for e in ok), error_rows=sum(e['errors'] for e in ok),
                  rows_out_of_support=sum(e.get('rows_out_of_support', 0) for e in ok), events_with_errors=sum(1 for e in ok if e['errors']),
                  runtime_s_sum=round(sum(float(e.get('runtime_s') or 0.0) for e in events.values()), 1))
    default_priors = [dict(race_id=e['race_id'], compound=c, mean=(e['default_prior_mean'] if not e['sealed'] else None)) for e in ok
                      for c, s in sorted(e.get('prior_sources', {}).items()) if s == SOURCE_DEFAULT]
    log = dict(generated_at=datetime.now().isoformat(timespec='seconds'), git_sha=git_sha(short=True), estimator=ESTIMATOR_LABEL, model_version=MODEL_VERSION,
               module='tyreformer.baseline_kalman', policy=POLICY, output_format=('parquet' if _have_pyarrow() else 'csv.gz'),
               sealed_race_ids=sorted(sealed_ids()), totals=totals,
               skipped={e['race_id']: e['skipped'] for e in events.values() if e['status'] == 'skipped'},
               failed={e['race_id']: e['failure'] for e in events.values() if e['status'] == 'failed'},
               default_priors=default_priors, pooled_scores_non_sealed=pooled_scores(events),
               runs=(list(old.get('runs') or []) + [dict(started_at=started.isoformat(timespec='seconds'), wall_s=round(wall_s, 1), options=options,
                                                           race_ids=sorted(entries))])[-20:],
               events=events)
    _write_json(path, _clean_json(log))
    return log


# ---------------------------------------------------------------- driver

def _say(e: dict, i: Optional[int] = None, n: Optional[int] = None, quiet: bool = False) -> None:
    if quiet:
        return
    tag = f'[{i}/{n}] ' if i is not None else ''
    rid = e['race_id']
    if e['status'] == 'skipped':
        print(f"{tag}{rid}: skipped ({e['skipped']})", flush=True)
    elif e['status'] == 'failed':
        print(f"{tag}{rid}: FAILED {e['failure']}", flush=True)
    elif e.get('sealed'):
        print(f'{tag}{rid}: sealed weekend processed (per-race output withheld from stdout)', flush=True)
    else:
        src = ', '.join(f"{c}={'loo' if s == SOURCE_LOO else ('default' if s == SOURCE_DEFAULT else s)}" for c, s in e['prior_sources'].items())
        print(f"{tag}{rid}: {e['n_rows']} rows, {e['n_drivers']} drivers, {e['errors']} error rows, {e['rows_out_of_support']} out-of-support rows; "
              f"priors {src}; {e['runtime_s']:.1f} s", flush=True)


def run(seasons: Iterable[int] = SEASONS, events: Optional[Iterable[str]] = None, include_sealed: bool = False, workers: int = MAX_WORKERS,
        lock_priors: bool = False, support_gate: str = 'product', out_dir: Optional[Path | str] = None, quiet: bool = False) -> dict[str, Any]:
    """Run the baseline over the selected races; returns this invocation's entries, pooled (non-sealed) scores and paths."""
    if support_gate not in SUPPORT_GATES:
        raise ValueError(f'support_gate must be one of {SUPPORT_GATES}')
    started, t0 = datetime.now(), time.time()
    if out_dir is None:
        out_dir = LOCK_OUT_DIR if lock_priors else (OUT_DIR if support_gate == 'product' else OUT_DIR / f'support_gate_{support_gate}')
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    seasons = [int(s) for s in seasons]
    events = [str(e) for e in events] if events is not None else None
    jobs, skipped = plan_jobs(seasons, events, include_sealed)
    for j in jobs:
        j.update(lock_priors=bool(lock_priors and j['season'] == LOCK_SEASON), support_gate=support_gate, out_dir=str(out_dir))
    entries: dict[str, dict] = {}
    for s in skipped:
        entries[s['race_id']] = s
        _say(s, quiet=quiet)
    n_workers = max(1, min(int(workers), MAX_WORKERS, len(jobs))) if jobs else 0
    if n_workers == 1:
        for i, j in enumerate(jobs, 1):
            e = run_event(j)
            entries[e['race_id']] = e
            _say(e, i, len(jobs), quiet)
    elif n_workers > 1:
        from tyreformer import baseline_kalman as importable     # by module name, so spawned workers can unpickle it under -m
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            futures = {ex.submit(importable.run_event, j): j for j in jobs}
            for i, fut in enumerate(as_completed(futures), 1):
                j = futures[fut]
                try:
                    e = fut.result()
                except Exception as exc:
                    e = _entry(j, status='failed', failure=_msg(exc))
                entries[e['race_id']] = e
                _say(e, i, len(jobs), quiet)
    wall = time.time() - t0
    options = dict(seasons=seasons, events=(sorted(events) if events is not None else None), include_sealed=bool(include_sealed), workers=n_workers,
                   lock_priors=bool(lock_priors), support_gate=support_gate, out_dir=_rel(out_dir))
    update_runlog(out_dir, entries, options, started, wall)
    return dict(entries=dict(sorted(entries.items())), scores=pooled_scores(entries), wall_s=wall, out_dir=out_dir, runlog=out_dir / RUNLOG_NAME, options=options)


def _prefix_reference(event: str) -> tuple[Optional[dict], Optional[str]]:
    try:
        d = json.loads(PREFIX_EVAL_JSON.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None, None
    return (d.get('races') or {}).get(event), d.get('generated_at')


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog='python -m tyreformer.baseline_kalman', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seasons', default=','.join(str(s) for s in SEASONS), help='comma-separated seasons (default 2023,2024,2025,2026)')
    ap.add_argument('--events', default=None, help='comma-separated event names, e.g. Monza,Austria (default: every race file)')
    ap.add_argument('--include-sealed', action='store_true', help='also run the sealed holdout weekends (never printed per race)')
    ap.add_argument('--workers', type=int, default=MAX_WORKERS, help=f'process-pool workers (capped at {MAX_WORKERS})')
    ap.add_argument('--out', type=Path, default=None, help='output directory (default out/tyreformer/kalman)')
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--lock-priors', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--support-gate', choices=SUPPORT_GATES, default='product', help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    seasons = [int(s) for s in a.seasons.split(',') if s.strip()]
    events = [e.strip() for e in a.events.split(',') if e.strip()] if a.events else None
    res = run(seasons, events, a.include_sealed, a.workers, a.lock_priors, a.support_gate, a.out, a.quiet)
    ents = list(res['entries'].values())
    ok = [e for e in ents if e['status'] == 'ok']
    sk = [e for e in ents if e['status'] == 'skipped']
    fl = [e for e in ents if e['status'] == 'failed']
    print(f"\nprocessed {len(ok)} races, skipped {len(sk)}, failed {len(fl)}; {sum(e['n_rows'] for e in ok)} rows "
          f"({sum(e['errors'] for e in ok)} error rows in {sum(1 for e in ok if e['errors'])} races, "
          f"{sum(e['rows_out_of_support'] for e in ok)} out-of-support rows); wall {res['wall_s']:.1f} s; {_rel(res['runlog'])}")
    for e in sk:
        print(f"  skipped {e['race_id']}: {e['skipped']}")
    for e in fl:
        print(f"  FAILED {e['race_id']}: {e['failure']}")
    if any(e['sealed'] for e in ok):
        print('  sealed weekends were processed; they are excluded from every score below')
    for name, s in res['scores'].items():
        print(f'  pooled {name} (non-sealed): {fmt_score(s)}')
    if a.lock_priors:
        for e in ok:
            if e['season'] != LOCK_SEASON or e['sealed']:
                continue
            ref, gen = _prefix_reference(e['event'])
            if ref is None:
                continue
            s = score(read_frame(_abs(e['file'])))
            print(f"  {e['race_id']} vs out/live/prefix_eval.json ({gen}):")
            num = lambda v: '-' if v is None else f'{v:.6f}'
            for k, n_run, n_ref in (('next1_mae', 'next1_n', 'next1_n'), ('next3_mae', 'next3_n', 'next3_n'), ('next5_mae', 'next5_n', 'next5_n'),
                                    ('cum3_mae', 'cum3_n', 'cum3_n'), ('cum5_mae', 'cum5_n', 'cum5_n'),
                                    ('coverage90_next1', 'coverage90_next1_n', 'next1_n'), ('coverage90_next3', 'coverage90_next3_n', 'next3_n')):
                diff = f'{s[k] - ref[k]:+.2e}' if s.get(k) is not None and ref.get(k) is not None else '-'
                print(f"    {k:18s} runner {num(s.get(k))} (n {s.get(n_run)})   reference {num(ref.get(k))} (n {ref.get(n_ref)})   diff {diff}")
    return 0 if not fl else 1


if __name__ == '__main__':
    raise SystemExit(main())
