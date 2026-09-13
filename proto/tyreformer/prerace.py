"""Orb PreRace: a learned practice-to-race transfer model for the pre-race degradation slope, scored against Orb v1.

Orb v1 forecasts each compound's race degradation slope (s/lap per lap of tyre age) before the race as the cleaned
practice long-run slope times a season transfer factor (evaluation/forecast.py with pipeline.py's rules). This module
learns that transfer from the 2023 to 2026 development weekends and scores it head to head with Orb v1 on identical
compound-weekends.

    frame            one row per (season, event, compound) with a practice table; sealed weekends are dropped from the
                     event list before any file is read, so their practice and race files are never loaded
    features         pre-race inputs only (FEATURES). Orb v1's point forecast and the circuit history are recomputed
                     from the frame for every fold with the held-out weekends removed from every pool, so a held-out
                     race never reaches a training row's feature either (no second-order leak through factors or history)
    models           Orb v1 as is, the naive practice slope, ridge, Huber and histogram gradient boosting, each fitted on
                     the reference slope ('obs') or on its residual to Orb v1 ('resid'), and a blend of each shrunk toward
                     Orb v1. Hyperparameters, blend weights and split-conformal 90 % half-widths are chosen inside each
                     training set by grouped inner cross-validation (whole weekends)
    protocol A       leave-one-weekend-out over every development weekend 2023-2026; the only protocol used for selection
    protocol B       trained on the 2023-2025 development weekends, tested on every 2026 development weekend; no choice is
                     made on B
    predict_weekend  the learned forecast for one weekend, trained on the development weekends of earlier seasons plus
                     the weekend's own season minus itself (Madrid 2026: every development weekend)

The target `obs` is the race-derived pace-loss reference of the weekend (post-race, scoring only); obs_se, n_race and
race track temperature are never read. Pirelli C-numbers come from tyreformer.data.compound_numbers when procured.

CLI (from proto/):  ../.venv/bin/python -m tyreformer.prerace [--jobs 10] [--refresh]
"""
from __future__ import annotations

import argparse
import json
import math
import time
import warnings
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

from tyreformer import PROTO, OUT

PRERACE_OUT = OUT / 'prerace'
SEASONS = (2023, 2024, 2025, 2026)
COMPS = ('SOFT', 'MEDIUM', 'HARD')
PRACTICE_SESSIONS = ('FP1', 'FP2', 'FP3')
TEMPORAL_TRAIN, TEMPORAL_TEST = (2023, 2024, 2025), 2026
INNER_K = 8                 # grouped inner folds (whole weekends) inside every training set
FOLD_SEED = 2026
LEVEL = 0.90                # nominal band coverage
N_BOOT, BOOT_SEED = 2000, 2026
BLEND_WEIGHTS = tuple(float(w) for w in np.round(np.linspace(0.0, 1.0, 21), 2))
DEFAULT_MODEL = 'blend_ridge_resid'     # predict_weekend's model only while prerace_eval.json does not exist
UNITS = 's/lap per lap of tyre age'

PRACTICE_FEATURES = ('clean', 'clean_se', 'naive', 'n_prac', 'push_adj', 'energy_trend', 'practice_resid_sd', 'track_temp_practice', 'sprint', 'street')
FEATURES = PRACTICE_FEATURES + (
    'comp_soft', 'comp_medium', 'comp_hard', 'cnum', 'cnum_missing',
    'clean_other_soft', 'clean_other_medium', 'clean_other_hard', 'clean_other_mean',
    'orb_v1', 'orb_v1_missing', 'orb_v1_issued', 'orb_v1_factor', 'orb_v1_factor_applied',
    'hist_last', 'hist_mean', 'hist_missing',
    'season_2023', 'season_2024', 'season_2025', 'season_2026')
FEATURE_NOTES = {
    'clean': 'cleaned practice long-run slope (model_v2 fit, stint fixed effects)', 'clean_se': 'its standard error',
    'naive': 'raw practice slope (polyfit of lap time on tyre age)', 'n_prac': 'clean practice laps on the compound',
    'push_adj': 'practice slope at constant tyre energy (pipeline.fit_push)', 'energy_trend': 'within-run energy trend (pipeline.energy_trend)',
    'practice_resid_sd': 'residual sd of the practice fit', 'track_temp_practice': 'mean FP1-FP3 track temperature (C)',
    'sprint': 'sprint-format weekend', 'street': "evaluation.circuit_class == 'street'",
    'comp_*': 'compound one-hot', 'cnum': 'Pirelli C-number of the compound (tyreformer.data.compound_numbers)', 'cnum_missing': 'no verified C-number',
    'clean_other_*': "the weekend's cleaned practice slope of the other compounds (own compound blank)", 'clean_other_mean': 'their mean',
    'orb_v1': "Orb v1's pre-race point forecast (season leave-one-out factor pool, recomputed per fold without the held-out weekends)",
    'orb_v1_missing': 'no Orb v1 forecast (withheld with < 2 withheld pool cases)', 'orb_v1_issued': 'Orb v1 gate: issued (n_prac >= 30 and clean >= 0.02)',
    'orb_v1_factor': 'season transfer factor k', 'orb_v1_factor_applied': 'factor agreement rule met',
    'hist_last': 'reference slope of the same circuit and compound in the most recent strictly earlier season (development weekends only)',
    'hist_mean': 'mean over all strictly earlier seasons', 'hist_missing': 'no earlier season', 'season_*': 'season one-hot'}

GRIDS: dict[str, tuple[dict[str, Any], ...]] = {
    # strongest regularisation first: ties in the inner CV keep the stronger setting
    'ridge': tuple(dict(alpha=a) for a in (3000.0, 1000.0, 300.0, 100.0, 30.0, 10.0, 3.0, 1.0)),
    'huber': tuple(dict(alpha=a, epsilon=1.35) for a in (3000.0, 300.0, 30.0, 3.0, 0.3)),
    'hgbr': (dict(loss='absolute_error', learning_rate=0.05, max_iter=100, max_depth=2, max_leaf_nodes=4, min_samples_leaf=20, l2_regularization=10.0),
             dict(loss='squared_error', learning_rate=0.05, max_iter=100, max_depth=2, max_leaf_nodes=4, min_samples_leaf=20, l2_regularization=10.0),
             dict(loss='absolute_error', learning_rate=0.05, max_iter=200, max_depth=3, max_leaf_nodes=6, min_samples_leaf=10, l2_regularization=5.0),
             dict(loss='squared_error', learning_rate=0.05, max_iter=200, max_depth=3, max_leaf_nodes=6, min_samples_leaf=10, l2_regularization=5.0)),
}
TARGETS = ('obs', 'resid')
# reference baselines, never selection candidates; climatology = the compound's median reference slope in the training rows
BASELINES = ('orb_v1', 'naive', 'climatology')


def learned_names(grids: dict = GRIDS, targets: Iterable[str] = TARGETS) -> list[str]:
    base = [f'{fam}_{tgt}' for fam in grids for tgt in targets]
    return base + [f'blend_{b}' for b in base]


def parse_name(name: str) -> tuple[str, str, bool]:
    """'blend_hgbr_resid' -> ('hgbr', 'resid', True)."""
    blend = name.startswith('blend_')
    fam, tgt = (name[len('blend_'):] if blend else name).split('_', 1)
    if fam not in GRIDS or tgt not in TARGETS:
        raise ValueError(f'unknown model {name!r}')
    return fam, tgt, blend


def _season(rid: str) -> int:
    return int(rid.split('_', 1)[0])


# ---------------------------------------------------------------- sealed holdout

@lru_cache(maxsize=1)
def sealed_ids() -> frozenset[str]:
    from evaluation.holdout.evaluator import sealed_race_ids
    ids = frozenset(sealed_race_ids())
    assert ids, 'the sealed manifest lists no weekend: refusing to run without it'
    return ids


def assert_no_sealed(race_ids: Iterable[str], where: str) -> int:
    """Raises AssertionError when any sealed race id is present; returns the number of ids checked."""
    ids = set(race_ids)
    bad = sorted(ids & sealed_ids())
    assert not bad, f'sealed holdout weekends in {where}: {bad}'
    return len(ids)


# ---------------------------------------------------------------- Orb v1 and the frame

_FORECASTERS: dict[int, Any] = {}


def season_forecaster(season: int):
    """SeasonForecaster for the season, built on the non-sealed weekends only (sealed files are never read)."""
    if season not in _FORECASTERS:
        from evaluation import SEASON_DIRS
        from evaluation.forecast import SeasonForecaster, events_in
        sealed = sealed_ids()
        events = [e for e in events_in(SEASON_DIRS[season]) if f'{season}_{e}' not in sealed]
        F = SeasonForecaster(SEASON_DIRS[season], season, sealed=sorted(r for r in sealed if r.startswith(f'{season}_')), events=events)
        assert_no_sealed([f'{season}_{e}' for e in F.metas], f'SeasonForecaster({season}) weekend tables')
        _FORECASTERS[season] = F
    return _FORECASTERS[season]


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def orb_v1_forecasts(season: int, refresh: bool = False) -> dict[str, Any]:
    """Orb v1's pre-race forecast for every non-sealed weekend of the season with a practice table:
    F.forecast(event, pool = development events minus event, target_obs_in_widening=False). Pre-race fields only.
    Cached in out/tyreformer/prerace/cache_orbv1_<season>.json (the band uses pipeline's global rng, so the cache also
    pins the band)."""
    path = PRERACE_OUT / f'cache_orbv1_{season}.json'
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding='utf-8'))
    from evaluation import git_sha, now_iso
    F = season_forecaster(season)
    dev = F.development_events
    events = {}
    for ev in F.events:
        fc = F.forecast(ev, [e for e in dev if e != ev], target_obs_in_widening=False)
        events[ev] = dict(race_id=fc.race_id, completed=bool(F.metas[ev]['completed']), development=ev in dev, pool_events=list(fc.pool_events),
                          compounds={c: dict(prediction=_num(f.prediction), band90=([_num(v) for v in f.band90] if f.band90 else None),
                                             band90_raw=([_num(v) for v in f.band90_raw] if f.band90_raw else None), widen=_num(f.widen), issued=bool(f.issued),
                                             gate=str(f.gate), factor=_num(f.factor), factor_applied=bool(f.factor_applied),
                                             factor_from_n_weekends=int(f.factor_from_n_weekends), floor=_num(f.floor), basis=str(f.basis))
                                     for c, f in fc.compounds.items()})
    out = dict(season=int(season), generated_at=now_iso(), git_sha=git_sha(), rule='SeasonForecaster.forecast(event, pool=development events minus event, target_obs_in_widening=False)',
               sealed_excluded=sorted(r for r in sealed_ids() if r.startswith(f'{season}_')), events=events)
    PRERACE_OUT.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding='utf-8')
    return out


def compound_numbers_status() -> tuple[dict, dict[str, Any]]:
    path = PROTO / 'tyreformer' / 'data' / 'pirelli_compounds.csv'
    try:
        from tyreformer.data import compound_numbers
        cn = compound_numbers()
    except Exception as e:                      # the procurement module is being edited by another task; never fatal here
        return {}, dict(status=f'unavailable ({type(e).__name__}: {e})', path=str(path.relative_to(PROTO)))
    n_with = sum(1 for v in cn.values() if any(x is not None for x in v.values()))
    return cn, dict(status=('loaded' if n_with else 'missing (no verified rows)'), path=str(path.relative_to(PROTO)), exists=path.exists(), n_weekends_listed=len(cn), n_weekends_with_numbers=n_with)


def build_frame(refresh_orb: bool = False) -> tuple[pd.DataFrame, dict[str, Any]]:
    """One row per (season, event, compound) of every non-sealed weekend with a practice table. `obs` is set only for
    development weekends (completed, not sealed) and is the scoring target; every other column is pre-race."""
    from evaluation import circuit_class
    cn, cn_status = compound_numbers_status()
    rows = []
    for season in SEASONS:
        F = season_forecaster(season)
        orb = orb_v1_forecasts(season, refresh=refresh_orb)['events']
        dev = set(F.development_events)
        for r in F.table.to_dict('records'):
            ev, c = r['event'], r['compound']
            meta = F.metas[ev]
            temps = [float(v) for k, v in meta['track_temp'].items() if k in PRACTICE_SESSIONS and _num(v) is not None]
            o = orb[ev]['compounds'][c]
            number = cn.get((season, ev), {}).get(c)
            band = o['band90'] or [None, None]
            rows.append(dict(race_id=f'{season}_{ev}', season=int(season), event=ev, compound=c, development=ev in dev, completed=bool(meta['completed']),
                             obs=(float(r['obs']) if ev in dev and _num(r['obs']) is not None else np.nan),
                             n_prac=float(r['n_prac']), naive=float(r['naive']), clean=float(r['clean']), clean_se=float(r['clean_se']),
                             push_adj=float(r['push_adj']), energy_trend=float(r['energy_trend']), issued=bool(r['issued']),
                             practice_resid_sd=float(meta['practice_resid_sd']), track_temp_practice=(float(np.mean(temps)) if temps else np.nan),
                             sprint=float(meta['format'] == 'sprint'), street=float(circuit_class(ev) == 'street'), circuit_class=circuit_class(ev),
                             cnum=(float(number) if number is not None else np.nan),
                             orb_v1_cached=(o['prediction'] if o['prediction'] is not None else np.nan),
                             orb_v1_lo=(band[0] if band[0] is not None else np.nan), orb_v1_hi=(band[1] if band[1] is not None else np.nan),
                             orb_v1_gate=o['gate'], orb_v1_basis=o['basis']))
    frame = pd.DataFrame(rows).sort_values(['season', 'event', 'compound']).reset_index(drop=True)
    assert_no_sealed(frame['race_id'], 'the prerace frame')
    dev_rows = frame['development'] & frame['obs'].notna()
    cn_status.update(n_frame_rows=int(len(frame)), n_frame_rows_with_cnum=int(frame['cnum'].notna().sum()),
                     n_development_rows=int(dev_rows.sum()), n_development_rows_with_cnum=int((dev_rows & frame['cnum'].notna()).sum()))
    return frame, cn_status


# ---------------------------------------------------------------- features (recomputed per fold)

def orb_v1_points(frame: pd.DataFrame, exclude: Iterable[str] = ()) -> pd.DataFrame:
    """Orb v1's point forecast for every frame row by pipeline.py's rules: factor = pipeline.agree_factor over obs/clean of
    the issued rows of the same compound in the row's season's development weekends minus the row's own weekend minus
    `exclude`; a withheld row gets the median obs of that pool's withheld rows (>= 2 needed). With exclude empty this
    equals SeasonForecaster.forecast(...).prediction (checked against the cache in the evaluation and the tests)."""
    import pipeline as P
    ex = list(set(exclude))
    season = frame['season'].to_numpy()
    rid = frame['race_id'].to_numpy()
    comp = frame['compound'].to_numpy()
    obs = frame['obs'].to_numpy(dtype=float)
    clean = frame['clean'].to_numpy(dtype=float)
    issued = frame['issued'].to_numpy(dtype=bool)
    usable = frame['development'].to_numpy(dtype=bool) & np.isfinite(obs) & ~np.isin(rid, ex)
    with np.errstate(divide='ignore', invalid='ignore'):
        ratio = np.where(issued, obs / clean, np.nan)
    n = len(frame)
    pred, factor, applied, from_n, floor = np.full(n, np.nan), np.ones(n), np.zeros(n), np.zeros(n), np.full(n, np.nan)
    floors: dict[str, float] = {}
    for i in range(n):
        pool = usable & (season == season[i]) & (rid != rid[i])
        if rid[i] not in floors:
            wh = obs[pool & ~issued]
            floors[rid[i]] = float(np.median(wh)) if len(wh) >= 2 else np.nan
        floor[i] = floors[rid[i]]
        r = ratio[pool & issued & (comp == comp[i])]
        r = r[np.isfinite(r)]
        k, ok = P.agree_factor(r)
        factor[i], applied[i], from_n[i] = float(k), float(bool(ok)), len(r)
        pred[i] = clean[i] * float(k) if issued[i] else floor[i]
    return pd.DataFrame(dict(orb_v1=pred, orb_v1_factor=factor, orb_v1_factor_applied=applied, orb_v1_factor_n=from_n, orb_v1_floor=floor), index=frame.index)


def circuit_history(frame: pd.DataFrame, exclude: Iterable[str] = ()) -> pd.DataFrame:
    """Reference slope of the same circuit and compound from strictly earlier seasons (development weekends only, minus
    `exclude`): hist_last (most recent season), hist_mean (all earlier seasons), hist_missing; audit columns
    hist_last_season and hist_sources (race ids used)."""
    ex = set(exclude)
    season = frame['season'].to_numpy()
    rid = frame['race_id'].to_numpy()
    obs = frame['obs'].to_numpy(dtype=float)
    usable = frame['development'].to_numpy(dtype=bool) & np.isfinite(obs) & np.array([r not in ex for r in rid], dtype=bool)
    by_key: dict[tuple[str, str], list[int]] = defaultdict(list)
    for j in np.flatnonzero(usable):
        by_key[(frame['event'].iat[j], frame['compound'].iat[j])].append(int(j))
    n = len(frame)
    last, mean, last_season = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    sources: list[list[str]] = [[] for _ in range(n)]
    for i in range(n):
        cands = [j for j in by_key.get((frame['event'].iat[i], frame['compound'].iat[i]), []) if season[j] < season[i]]
        if not cands:
            continue
        j_last = max(cands, key=lambda j: season[j])
        last[i], last_season[i] = obs[j_last], season[j_last]
        mean[i] = float(np.mean(obs[cands]))
        sources[i] = sorted(rid[j] for j in cands)
    return pd.DataFrame(dict(hist_last=last, hist_mean=mean, hist_missing=np.isnan(last).astype(float), hist_last_season=last_season, hist_sources=sources), index=frame.index)


def features(frame: pd.DataFrame, exclude: Iterable[str] = ()) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(X[FEATURES], audit) for every frame row. Nothing of a row's own race enters its features; `exclude` removes
    weekends (the held-out ones) from every pool that reads race outcomes (Orb v1 factors and floor, circuit history)."""
    X = pd.DataFrame(index=frame.index)
    for c in PRACTICE_FEATURES:
        X[c] = frame[c].astype(float)
    for c in COMPS:
        X[f'comp_{c.lower()}'] = (frame['compound'] == c).astype(float)
    X['cnum'] = frame['cnum'].astype(float)
    X['cnum_missing'] = frame['cnum'].isna().astype(float)
    wk = frame.pivot_table(index='race_id', columns='compound', values='clean', aggfunc='first')
    for c in COMPS:
        vals = frame['race_id'].map(wk[c]) if c in wk.columns else pd.Series(np.nan, index=frame.index)
        X[f'clean_other_{c.lower()}'] = np.where(frame['compound'] == c, np.nan, vals.astype(float))
    X['clean_other_mean'] = X[[f'clean_other_{c.lower()}' for c in COMPS]].mean(axis=1, skipna=True)
    o = orb_v1_points(frame, exclude)
    X['orb_v1'] = o['orb_v1']
    X['orb_v1_missing'] = o['orb_v1'].isna().astype(float)
    X['orb_v1_issued'] = frame['issued'].astype(float)
    X['orb_v1_factor'] = o['orb_v1_factor']
    X['orb_v1_factor_applied'] = o['orb_v1_factor_applied']
    h = circuit_history(frame, exclude)
    for c in ('hist_last', 'hist_mean', 'hist_missing'):
        X[c] = h[c]
    for s in SEASONS:
        X[f'season_{s}'] = (frame['season'] == s).astype(float)
    audit = pd.concat([h[['hist_last_season', 'hist_sources']], o[['orb_v1_factor_n', 'orb_v1_floor']]], axis=1)
    return X[list(FEATURES)], audit


# ---------------------------------------------------------------- models

class QuantileClip(TransformerMixin, BaseEstimator):
    """Clips each column to its training [q, 1 - q] quantiles (NaN kept); tames heavy-tailed practice slopes."""

    def __init__(self, q: float = 0.01):
        self.q = q

    def fit(self, X, y=None):
        X = np.asarray(X, dtype=float)
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', category=RuntimeWarning)
            lo, hi = np.nanquantile(X, self.q, axis=0), np.nanquantile(X, 1.0 - self.q, axis=0)
        self.lo_ = np.where(np.isnan(lo), -np.inf, lo)
        self.hi_ = np.where(np.isnan(hi), np.inf, hi)
        self.n_features_in_ = X.shape[1]
        return self

    def transform(self, X):
        return np.clip(np.asarray(X, dtype=float), self.lo_, self.hi_)


def make_model(family: str, hp: dict[str, Any]):
    from sklearn.compose import TransformedTargetRegressor
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import HuberRegressor, Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if family == 'hgbr':
        return HistGradientBoostingRegressor(early_stopping=False, random_state=0, **hp)
    if family == 'ridge':
        est = Ridge(alpha=hp['alpha'])
    elif family == 'huber':
        est = HuberRegressor(alpha=hp['alpha'], epsilon=hp['epsilon'], max_iter=5000)
    else:
        raise ValueError(family)
    pipe = make_pipeline(QuantileClip(0.01), SimpleImputer(strategy='median', add_indicator=True), StandardScaler(), est)
    return TransformedTargetRegressor(regressor=pipe, transformer=StandardScaler(), check_inverse=False)


def conformal_q(abs_residuals: np.ndarray, level: float = LEVEL) -> float:
    """Split-conformal half-width: the ceil((n + 1) level)-th smallest absolute out-of-fold residual (capped at n)."""
    r = np.sort(np.asarray(abs_residuals, dtype=float))
    r = r[np.isfinite(r)]
    if not len(r):
        return float('nan')
    k = int(math.ceil((len(r) + 1) * level))
    return float(r[min(k, len(r)) - 1])


def inner_folds(weekends: Iterable[str], k: int = INNER_K, seed: int = FOLD_SEED) -> list[frozenset[str]]:
    """Deterministic grouped folds over a set of weekends (depends on the ids only, never on outcomes)."""
    w = sorted(set(weekends))
    k = max(2, min(k, len(w)))
    perm = np.random.default_rng(seed).permutation(len(w))
    folds: list[set[str]] = [set() for _ in range(k)]
    for pos, idx in enumerate(perm):
        folds[pos % k].add(w[idx])
    return [frozenset(f) for f in folds]


def development_weekends(frame: pd.DataFrame) -> list[str]:
    return sorted(frame.loc[frame['development'] & frame['obs'].notna(), 'race_id'].unique())


def protocol_A_splits(frame: pd.DataFrame) -> list[tuple[list[str], list[str]]]:
    dev = development_weekends(frame)
    return [([x for x in dev if x != w], [w]) for w in dev]


def protocol_B_split(frame: pd.DataFrame) -> tuple[list[str], list[str]]:
    dev = development_weekends(frame)
    return [w for w in dev if _season(w) in TEMPORAL_TRAIN], [w for w in dev if _season(w) == TEMPORAL_TEST]


def weekend_split(frame: pd.DataFrame, season: int, event: str) -> tuple[list[str], list[str]]:
    rid = f'{season}_{event}'
    return [w for w in development_weekends(frame) if _season(w) <= int(season) and w != rid], [rid]


def run_fold(frame: pd.DataFrame, train_ids: Iterable[str], test_ids: Iterable[str], grids: Optional[dict] = None, targets: Iterable[str] = TARGETS,
             inner_k: int = INNER_K, blend: bool = True) -> dict[str, Any]:
    """Fit every requested model on the development rows of `train_ids` and forecast every frame row of `test_ids`.

    Training features: computed with the test weekends removed from every outcome pool. Test features: computed with
    nothing extra removed (a row's own weekend is never in its own pools). Inside the training set, grouped inner folds
    (features recomputed without the inner validation weekends as well) give out-of-fold predictions that choose the
    hyperparameter (lowest MAE), the blend weight toward Orb v1 and the conformal 90 % half-width."""
    grids = GRIDS if grids is None else grids
    targets = tuple(targets)
    train_ids, test_ids = sorted(set(train_ids)), sorted(set(test_ids))
    if set(train_ids) & set(test_ids):
        raise ValueError('a weekend is both a training and a test weekend')
    checked = assert_no_sealed(train_ids, 'a training frame') + assert_no_sealed(test_ids, 'a test frame')
    rid = frame['race_id'].to_numpy()
    y = frame['obs'].to_numpy(dtype=float)
    tr = np.isin(rid, train_ids) & frame['development'].to_numpy(dtype=bool) & np.isfinite(y)
    te = np.isin(rid, test_ids)
    assert tr.any() and te.any(), 'empty training or test frame'
    assert not (set(rid[tr]) & set(test_ids))
    test_set = frozenset(test_ids)
    X_tr = features(frame, test_set)[0].to_numpy(dtype=float)
    X_te = features(frame, ())[0].to_numpy(dtype=float)
    j_orb = FEATURES.index('orb_v1')

    def orb(X: np.ndarray, mask: np.ndarray, fallback: float) -> np.ndarray:
        v = X[mask, j_orb]
        return np.where(np.isfinite(v), v, fallback)

    inner = []
    orb_oof = np.full(len(frame), np.nan)
    for val in inner_folds(rid[tr], inner_k):
        Xj = features(frame, test_set | val)[0].to_numpy(dtype=float)
        vm = tr & np.isin(rid, list(val))
        fm = tr & ~vm
        fb = float(np.median(y[fm]))
        orb_oof[vm] = orb(Xj, vm, fb)
        inner.append((Xj, fm, vm, fb))
    fb_tr = float(np.median(y[tr]))
    orb_te = orb(X_te, te, fb_tr)
    naive = frame['naive'].to_numpy(dtype=float)
    q_naive = conformal_q(np.abs(y[tr] - naive[tr]))
    q_orb = conformal_q(np.abs(y[tr] - orb(X_tr, tr, fb_tr)))
    comp = frame['compound'].to_numpy()
    medians = {c: (float(np.median(y[tr & (comp == c)])) if (tr & (comp == c)).any() else fb_tr) for c in COMPS}
    clim = np.array([medians.get(c, fb_tr) for c in comp])
    q_clim = conformal_q(np.abs(y[tr] - clim[tr]))
    cached = frame['orb_v1_cached'].to_numpy(dtype=float)[te]
    preds: dict[str, dict[str, np.ndarray]] = {
        'orb_v1': dict(pred=orb_te, lo=frame['orb_v1_lo'].to_numpy(dtype=float)[te], hi=frame['orb_v1_hi'].to_numpy(dtype=float)[te]),
        'orb_v1_conformal': dict(pred=orb_te, lo=orb_te - q_orb, hi=orb_te + q_orb),
        'naive': dict(pred=naive[te], lo=naive[te] - q_naive, hi=naive[te] + q_naive),
        'climatology': dict(pred=clim[te], lo=clim[te] - q_clim, hi=clim[te] + q_clim)}
    diag: dict[str, Any] = dict(naive=dict(q90=q_naive), orb_v1_conformal=dict(q90=q_orb), climatology=dict(medians=medians, q90=q_clim))
    from threadpoolctl import threadpool_limits
    with warnings.catch_warnings(), threadpool_limits(limits=1):     # OpenMP on ~150 rows is ~100x slower than one thread
        warnings.simplefilter('ignore')
        for fam, grid in grids.items():
            for tgt in targets:
                name = f'{fam}_{tgt}'
                oof = np.full((len(grid), len(frame)), np.nan)
                for Xj, fm, vm, fb in inner:
                    off_f = orb(Xj, fm, fb) if tgt == 'resid' else 0.0
                    off_v = orb(Xj, vm, fb) if tgt == 'resid' else 0.0
                    for g, hp in enumerate(grid):
                        oof[g, vm] = make_model(fam, hp).fit(Xj[fm], y[fm] - off_f).predict(Xj[vm]) + off_v
                inner_mae = np.mean(np.abs(oof[:, tr] - y[tr]), axis=1)
                g = int(np.argmin(inner_mae))
                q = conformal_q(np.abs(oof[g, tr] - y[tr]))
                off_tr = orb(X_tr, tr, fb_tr) if tgt == 'resid' else 0.0
                off_te = orb_te if tgt == 'resid' else 0.0
                p = make_model(fam, grid[g]).fit(X_tr[tr], y[tr] - off_tr).predict(X_te[te]) + off_te
                preds[name] = dict(pred=p, lo=p - q, hi=p + q)
                diag[name] = dict(hp_index=g, hp=grid[g], inner_mae=[float(v) for v in inner_mae], q90=q)
                if blend:
                    b, o, yt = oof[g, tr], orb_oof[tr], y[tr]
                    maes = [float(np.mean(np.abs(w * b + (1.0 - w) * o - yt))) for w in BLEND_WEIGHTS]
                    w = BLEND_WEIGHTS[int(np.argmin(maes))]        # ties keep the smaller weight (closer to Orb v1)
                    qb = conformal_q(np.abs(w * b + (1.0 - w) * o - yt))
                    pb = w * p + (1.0 - w) * orb_te
                    preds[f'blend_{name}'] = dict(pred=pb, lo=pb - qb, hi=pb + qb)
                    diag[f'blend_{name}'] = dict(base=name, weight=w, hp_index=g, hp=grid[g], inner_mae_by_weight=maes, q90=qb)
    return dict(train_ids=train_ids, test_ids=test_ids, test_index=frame.index[te].to_numpy(), n_train_rows=int(tr.sum()), n_train_weekends=int(len(set(rid[tr]))),
                n_test_rows=int(te.sum()), preds=preds, diag=diag, inner_k=len(inner),
                orb_v1_reimplementation_max_abs_diff=(float(np.nanmax(np.abs(orb_te - cached))) if np.isfinite(cached).any() else None),
                sealed_ids_checked=checked)


def _fold_task(frame: pd.DataFrame, train_ids: list[str], test_ids: list[str]) -> dict[str, Any]:
    return run_fold(frame, train_ids, test_ids)


def run_splits(frame: pd.DataFrame, splits: list[tuple[list[str], list[str]]], jobs: int = 1) -> list[dict[str, Any]]:
    if jobs <= 1:
        return [_fold_task(frame, tr, te) for tr, te in splits]
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        futures = [ex.submit(_fold_task, frame, tr, te) for tr, te in splits]
        return [f.result() for f in futures]


# ---------------------------------------------------------------- scoring

def assemble(frame: pd.DataFrame, folds: list[dict[str, Any]]) -> pd.DataFrame:
    """Per development row of the test weekends: identifiers, obs, Orb v1, naive and every model's forecast and band."""
    cols: dict[str, pd.Series] = {}
    tested = []
    for f in folds:
        idx = f['test_index']
        tested.extend(idx.tolist())
        for m, d in f['preds'].items():
            for k in ('pred', 'lo', 'hi'):
                col = m if k == 'pred' else f'{m}_{k}'
                if col not in cols:
                    cols[col] = pd.Series(np.nan, index=frame.index, dtype=float)
                cols[col].loc[idx] = d[k]
    P = frame[['race_id', 'season', 'event', 'compound', 'circuit_class', 'issued', 'cnum', 'obs', 'naive', 'orb_v1_cached']].copy()
    for col, s in cols.items():
        P[col] = s
    P = P.loc[sorted(set(tested))]
    P = P[frame.loc[P.index, 'development'] & P['obs'].notna()]
    P['gate'] = np.where(P['issued'], 'issued', 'withheld')
    return P.reset_index(drop=True)


def _corr(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def _spearman(x: np.ndarray, y: np.ndarray) -> Optional[float]:
    from scipy.stats import spearmanr
    if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(spearmanr(x, y).statistic)


def model_metrics(P: pd.DataFrame, m: str) -> dict[str, Any]:
    out: dict[str, Any] = dict(n_rows=int(len(P)), n_weekends=int(P['race_id'].nunique()))
    if not len(P):
        return out
    pred, obs, naive = P[m].to_numpy(float), P['obs'].to_numpy(float), P['naive'].to_numpy(float)
    err = np.abs(pred - obs)
    out.update(mae=float(err.mean()), median_ae=float(np.median(err)), mean_error=float(np.mean(pred - obs)), pearson_r=_corr(pred, obs), spearman_rho=_spearman(pred, obs),
               calibration_slope=(float(np.polyfit(pred, obs, 1)[0]) if len(P) >= 3 and np.std(pred) > 0 else None),
               calibration_intercept=(float(np.polyfit(pred, obs, 1)[1]) if len(P) >= 3 and np.std(pred) > 0 else None),
               share_beats_naive=(None if m == 'naive' else float(np.mean(err < np.abs(naive - obs)))))
    if f'{m}_lo' in P:
        lo, hi = P[f'{m}_lo'].to_numpy(float), P[f'{m}_hi'].to_numpy(float)
        out.update(coverage90=float(np.mean((lo <= obs) & (obs <= hi))), mean_band_width=float(np.mean(hi - lo)))
    return out


def bootstrap(P: pd.DataFrame, models: list[str], references: tuple[str, ...] = ('orb_v1', 'climatology'), n: int = N_BOOT, seed: int = BOOT_SEED) -> dict[str, Any]:
    """Weekend-grouped percentile bootstrap: whole weekends (race_id) drawn with replacement, rows never resampled
    individually; one draw matrix shared by every model, so paired differences against the references are coherent.
    p_beats = share of draws where the model's MAE is below the reference's (ties count half)."""
    weekends = sorted(P['race_id'].unique())
    rows = {w: np.flatnonzero(P['race_id'].to_numpy() == w) for w in weekends}
    draws = np.random.default_rng(seed).integers(0, len(weekends), size=(n, len(weekends)))
    idx = [np.concatenate([rows[weekends[k]] for k in d]) for d in draws]
    obs = P['obs'].to_numpy(float)
    err = {m: np.abs(P[m].to_numpy(float) - obs) for m in models}
    boot_mae = {m: np.array([err[m][i].mean() for i in idx]) for m in models}
    out: dict[str, Any] = dict(method=f'weekend-grouped percentile bootstrap, {n} draws, seed {seed}, whole weekends resampled (rows never resampled individually)',
                               n_weekends=len(weekends), n_rows=int(len(P)), models={})
    for m in models:
        pred = P[m].to_numpy(float)
        rs = [v for v in (_corr(pred[i], obs[i]) for i in idx) if v is not None]
        rho = [v for v in (_spearman(pred[i], obs[i]) for i in idx) if v is not None]
        cell = dict(mae=dict(estimate=float(err[m].mean()), ci90=[float(v) for v in np.percentile(boot_mae[m], [5, 95])]),
                    pearson_r=dict(estimate=_corr(pred, obs), ci90=([float(v) for v in np.percentile(rs, [5, 95])] if len(rs) >= n // 10 else None), n_valid=len(rs)),
                    spearman_rho=dict(estimate=_spearman(pred, obs), ci90=([float(v) for v in np.percentile(rho, [5, 95])] if len(rho) >= n // 10 else None), n_valid=len(rho)))
        for ref in references:
            if ref in err and m != ref:
                diff = boot_mae[m] - boot_mae[ref]
                cell['mae_minus_' + ref] = dict(estimate=float(err[m].mean() - err[ref].mean()), ci90=[float(v) for v in np.percentile(diff, [5, 95])],
                                                p_beats=float(np.mean(diff < 0) + 0.5 * np.mean(diff == 0)))
        out['models'][m] = cell
    return out


def breakdowns(P: pd.DataFrame, models: list[str]) -> dict[str, Any]:
    """Reporting slices only (never used for selection): circuit class, Orb v1 gate, season."""
    out: dict[str, Any] = {}
    for key in ('circuit_class', 'gate', 'season'):
        out[key] = {str(v): {m: model_metrics(d, m) for m in models} for v, d in P.groupby(key)}
    return out


def evaluate_protocol(P: pd.DataFrame, models: list[str]) -> dict[str, Any]:
    return dict(n_rows=int(len(P)), n_weekends=int(P['race_id'].nunique()), metrics={m: model_metrics(P, m) for m in models},
                breakdowns=breakdowns(P, models))


def select_model(metrics: dict[str, dict[str, Any]], candidates: list[str]) -> str:
    """Pre-declared rule: the learned candidate with the lowest protocol-A MAE (ties: higher Spearman)."""
    return min(candidates, key=lambda m: (round(metrics[m]['mae'], 12), -(metrics[m].get('spearman_rho') or -1.0)))


def _choices(folds: list[dict[str, Any]], names: list[str]) -> dict[str, Any]:
    out = {}
    for m in names:
        ds = [f['diag'][m] for f in folds if m in f['diag']]
        if not ds:
            continue
        counts = Counter(json.dumps(d['hp'], sort_keys=True) for d in ds)
        cell: dict[str, Any] = dict(n_folds=len(ds), hp_counts={k: int(v) for k, v in counts.most_common()}, q90_median=float(np.median([d['q90'] for d in ds])))
        if 'weight' in ds[0]:
            w = np.array([d['weight'] for d in ds])
            cell.update(weight_median=float(np.median(w)), weight_p10=float(np.percentile(w, 10)), weight_p90=float(np.percentile(w, 90)))
        out[m] = cell
    return out


# ---------------------------------------------------------------- per-weekend forecast

def chosen_model(eval_path: Path = PRERACE_OUT / 'prerace_eval.json') -> str:
    if eval_path.exists():
        return json.loads(eval_path.read_text(encoding='utf-8'))['selection']['chosen_model']
    return DEFAULT_MODEL


def predict_weekend(season: int, event: str, model: Optional[str] = None, frame: Optional[pd.DataFrame] = None, inner_k: int = INNER_K) -> dict[str, Any]:
    """The learned pre-race forecast per compound for one weekend. Trained on every development row of earlier seasons
    plus the weekend's own season minus the weekend (for Madrid 2026, which has no race: every development row); the
    weekend's own race outcome, if any, never enters. Sealed weekends are refused."""
    from evaluation import git_sha, now_iso
    rid = f'{int(season)}_{event}'
    if rid in sealed_ids():
        raise PermissionError(f'{rid} is a sealed holdout weekend: no forecast from this module')
    if frame is None:
        frame, _ = build_frame()
    rows = frame[frame['race_id'] == rid]
    if rows.empty:
        raise KeyError(f'{rid}: no practice table (no files or too few clean practice laps)')
    name = model or chosen_model()
    fam, tgt, blend = parse_name(name)
    train, test = weekend_split(frame, season, event)
    assert_no_sealed(train, f'the training frame of {rid}')
    fold = run_fold(frame, train, test, grids={fam: GRIDS[fam]}, targets=(tgt,), inner_k=inner_k, blend=blend)
    X, audit = features(frame, ())
    pos = {int(i): k for k, i in enumerate(fold['test_index'])}
    orb_cache = orb_v1_forecasts(int(season))['events'][event]['compounds']
    comps = {}
    for i, r in rows.iterrows():
        k = pos[int(i)]
        d, o = fold['preds'][name], orb_cache[r['compound']]
        comps[r['compound']] = dict(
            prediction=float(d['pred'][k]), band90=[float(d['lo'][k]), float(d['hi'][k])], conformal_half_width90=float(fold['diag'][name]['q90']),
            orb_v1=dict(prediction=o['prediction'], band90=o['band90'], issued=o['issued'], gate=o['gate'], factor=o['factor'], factor_applied=o['factor_applied'], basis=o['basis']),
            naive=float(r['naive']), c_number=(int(r['cnum']) if np.isfinite(r['cnum']) else None),
            inputs={f: (None if not np.isfinite(v) else float(v)) for f, v in X.loc[i].items()},
            circuit_history_sources=list(audit.at[i, 'hist_sources']))
    d = fold['diag'][name]
    return dict(season=int(season), event=event, race_id=rid, units=UNITS, generated_at=now_iso(), git_sha=git_sha(), model=name,
                model_description=dict(family=fam, target=tgt, blend_toward_orb_v1=blend, hyperparameters=d['hp'], blend_weight=d.get('weight'),
                                       selection='hyperparameter and blend weight by grouped inner CV inside this training set; model family chosen by protocol A (prerace_eval.json)'),
                training=dict(rule="development rows of earlier seasons plus this season's other development weekends", n_rows=fold['n_train_rows'],
                              n_weekends=fold['n_train_weekends'], seasons=sorted({_season(w) for w in fold['train_ids']}), sealed_excluded=sorted(sealed_ids())),
                completed=bool(rows['completed'].iloc[0]), compounds=comps,
                status='development candidate from the learned prerace model; not the shipping Orb v1 forecast and not a sealed or scored result')


# ---------------------------------------------------------------- report

def _fmt(v: Optional[float], nd: int = 4, pct: bool = False) -> str:
    if v is None or not np.isfinite(v):
        return 'n/a'
    return f'{v:.0%}' if pct else f'{v:.{nd}f}'


def _ci(cell: Optional[dict], nd: int = 4) -> str:
    if not cell or cell.get('estimate') is None:
        return 'n/a'
    ci = cell.get('ci90')
    return f"{cell['estimate']:.{nd}f}" + (f" [{ci[0]:.{nd}f}, {ci[1]:.{nd}f}]" if ci else '')


def _verdict(cell: dict, ref: str = 'Orb v1') -> str:
    lo, hi = cell['ci90']
    if hi < 0:
        return f'beats {ref} (90% CI of the MAE difference excludes zero)'
    if lo > 0:
        return f'is worse than {ref} (90% CI of the MAE difference excludes zero)'
    return f'does not beat {ref} conclusively (90% CI of the MAE difference includes zero)'


MODEL_LABELS = {'orb_v1': 'Orb v1 (as is, native band)', 'naive': 'naive practice slope', 'climatology': 'climatology (compound median of training rows; reference)'}


def _row_label(m: str, best: str) -> str:
    return MODEL_LABELS.get(m, f'`{m}`') + (' **selected**' if m == best else '')


def render_md(ev: dict[str, Any]) -> str:
    best = ev['selection']['chosen_model']
    fam, tgt, blend = parse_name(best)
    A, B = ev['protocols']['A'], ev['protocols']['B']
    cn = ev['c_numbers']
    L = ['# Orb PreRace: learned practice-to-race transfer vs Orb v1', '',
         f"Generated {ev['generated_at']} (git {str(ev['git_sha'])[:7]}). Target: the race-derived pace-loss reference slope ({UNITS}) of each development compound-weekend. "
         f"Sealed holdout weekends were never loaded (assertion passed). Pirelli C-numbers {cn['status']}: {cn['n_development_rows_with_cnum']} of {cn['n_development_rows']} rows.", '',
         f"Selected on protocol A only: **`{best}`** ({ {'huber': 'Huber regression', 'ridge': 'ridge regression', 'hgbr': 'histogram gradient boosting'}[fam] } on "
         f"{'the reference slope' if tgt == 'obs' else 'the residual to Orb v1'}{', blended toward Orb v1' if blend else ''}; lowest A MAE of {len(ev['learned_candidates'])} learned candidates). "
         "Hyperparameters, blend weights and conformal 90% bands are chosen inside every training set by grouped inner cross-validation. No choice was made on protocol B.", '',
         '## Headline', '',
         '| protocol | model | MAE [90% CI] | r [90% CI] | Spearman | calib. slope | beats naive | coverage90 (mean width) |', '|---|---|---|---|---|---|---|---|']
    for key, pr, label in (('A', A, f"A: leave one weekend out, 2023-2026 ({A['n_rows']} rows, {A['n_weekends']} weekends)"),
                           ('B', B, f"B: train 2023-2025, test 2026 ({B['n_rows']} rows, {B['n_weekends']} weekends)")):
        for m in ('orb_v1', 'naive', 'climatology', best):
            mt, b = pr['metrics'][m], pr['bootstrap']['models'][m]
            L.append(f"| {label if m == 'orb_v1' else ''} | {_row_label(m, best)} | {_ci(b['mae'])} | {_ci(b['pearson_r'], 2)} | {_fmt(mt['spearman_rho'], 2)} | {_fmt(mt['calibration_slope'], 2)} | "
                     f"{_fmt(mt['share_beats_naive'], pct=True)} | {_fmt(mt.get('coverage90'), pct=True)} ({_fmt(mt.get('mean_band_width'), 3)}) |")
    L += ['', f'Paired weekend bootstrap ({N_BOOT} draws, whole weekends resampled):', '']
    for key, pr in (('A', A), ('B', B)):
        b = pr['bootstrap']['models']
        h, hc = b[best]['mae_minus_orb_v1'], b[best]['mae_minus_climatology']
        L.append(f"- {key}: MAE `{best}` minus Orb v1 {_ci(h)}, P(beats Orb v1) {h['p_beats']:.3f}; minus climatology {_ci(hc)}, P(beats climatology) {hc['p_beats']:.3f}; "
                 f"Orb v1 minus climatology {_ci(b['orb_v1']['mae_minus_climatology'])}.")
    L += ['', '## All candidates (MAE / r / Spearman)', '', '| model | protocol A | protocol B |', '|---|---|---|']
    for m in ['orb_v1', 'naive', 'climatology'] + list(ev['learned_candidates']):
        cells = [f"{_fmt(pr['metrics'][m]['mae'])} / {_fmt(pr['metrics'][m]['pearson_r'], 2)} / {_fmt(pr['metrics'][m]['spearman_rho'], 2)}" for pr in (A, B)]
        L.append(f"| {_row_label(m, best)} | {cells[0]} | {cells[1]} |")
    L += ['', '## Breakdown (MAE / r; reporting only, never used for selection)', '', '| protocol | slice | rows | Orb v1 | climatology | selected |', '|---|---|---|---|---|---|']
    for key, pr, dims in (('A', A, ('circuit_class', 'gate', 'season')), ('B', B, ('circuit_class', 'gate'))):
        for dim in dims:
            for val, cell in pr['breakdowns'][dim].items():
                f = lambda m: f"{_fmt(cell[m]['mae'])} / {_fmt(cell[m]['pearson_r'], 2)}"
                L.append(f"| {key} | {val} | {cell['orb_v1']['n_rows']} | {f('orb_v1')} | {f('climatology')} | {f(best)} |")
    mad = ev.get('madrid_2026')
    if mad:
        L += ['', f"## Madrid 2026 (no race yet; `{mad['path']}`)", '', f"`{best}` trained on all {mad['training_rows']} development rows.", '',
              '| compound | selected [90% band] | Orb v1 [90% band] |', '|---|---|---|']
        for c, v in mad['compounds'].items():
            ob = v.get('orb_v1_band90') or [None, None]
            L.append(f"| {c} | {v['prediction']:.4f} [{v['band90'][0]:.4f}, {v['band90'][1]:.4f}] | {_fmt(v['orb_v1'])} [{_fmt(ob[0])}, {_fmt(ob[1])}] |")
    L += ['', '## Findings', ''] + [f'{i}. {s}' for i, s in enumerate(ev['findings'], 1)] + ['', '## Caveats', ''] + [f'- {s}' for s in ev['caveats']] + ['']
    return '\n'.join(L)


def findings(ev: dict[str, Any]) -> tuple[list[str], list[str]]:
    best = ev['selection']['chosen_model']
    A, B = ev['protocols']['A'], ev['protocols']['B']
    bA, bB = A['bootstrap']['models'], B['bootstrap']['models']
    mA, mB = A['metrics'], B['metrics']
    hA, hB = bA[best]['mae_minus_orb_v1'], bB[best]['mae_minus_orb_v1']
    cA = bA[best]['mae_minus_climatology']
    gate = A['breakdowns']['gate']
    F = [f"On protocol A `{best}` has MAE {_ci(bA[best]['mae'])} against Orb v1's {_ci(bA['orb_v1']['mae'])} (P(beats Orb v1) {hA['p_beats']:.2f}, so on A it {_verdict(hA)}), "
         f"and it ranks the weekends better: r {_ci(bA[best]['pearson_r'], 2)} against {_ci(bA['orb_v1']['pearson_r'], 2)}, Spearman {_fmt(mA[best]['spearman_rho'], 2)} against "
         f"{_fmt(mA['orb_v1']['spearman_rho'], 2)}, calibration slope {_fmt(mA[best]['calibration_slope'], 2)} against {_fmt(mA['orb_v1']['calibration_slope'], 2)} (ideal 1).",
         f"Most of that MAE gain is shrinkage rather than practice-to-race transfer: a per-compound constant with no practice input (climatology) already scores {_ci(bA['climatology']['mae'])} on A, "
         f"and `{best}` improves on it by only {_ci(dict(cA, estimate=-cA['estimate'], ci90=[-cA['ci90'][1], -cA['ci90'][0]]))} ({_verdict(cA, 'climatology')}). "
         f"The gain over Orb v1 sits in its issued forecasts (MAE {_fmt(gate['issued'][best]['mae'])} against {_fmt(gate['issued']['orb_v1']['mae'])}, where cleaned slope x factor overshoots), "
         f"much less in the withheld fallback ({_fmt(gate['withheld'][best]['mae'])} against {_fmt(gate['withheld']['orb_v1']['mae'])})."]
    seasons = sorted(A['breakdowns']['season'].items())
    wins = [s for s, c in seasons if c[best]['mae'] < c['orb_v1']['mae']]
    losses = [s for s, c in seasons if c[best]['mae'] >= c['orb_v1']['mae']]
    F.append(f"The pooled result is not uniform across seasons (A, MAE `{best}` against Orb v1): " + '; '.join(f"{s} {c[best]['mae']:.4f} against {c['orb_v1']['mae']:.4f}" for s, c in seasons)
             + (f". It wins in {', '.join(wins)}" if wins else '. It wins in no season') + (f" and loses in {', '.join(losses)}, even though A lets it train on that season's other weekends." if losses else '.'))
    top = B.get('highest_reference_rows', [])
    rho_word = 'above' if (mB[best]['spearman_rho'] or 0) > (mB['orb_v1']['spearman_rho'] or 0) else 'not above'
    F.append(f"On the untouched temporal check B (trained on 2023-2025 only; no choice made on B) `{best}` {_verdict(hB)} on 2026: MAE {_ci(bB[best]['mae'])} against {_ci(bB['orb_v1']['mae'])}, "
             f"P(beats Orb v1) {hB['p_beats']:.2f}, r {_fmt(mB[best]['pearson_r'], 2)} against {_fmt(mB['orb_v1']['pearson_r'], 2)}. Its Spearman {_fmt(mB[best]['spearman_rho'], 2)} is {rho_word} Orb v1's "
             f"{_fmt(mB['orb_v1']['spearman_rho'], 2)}, but it compresses the highest-degradation rows (calibration slope {_fmt(mB[best]['calibration_slope'], 2)}): "
             + ', '.join(f"{r['event']} {r['compound'].lower()} reference {r['obs']:.3f}, Orb v1 {r['orb_v1']:.3f}, `{best}` {r['selected']:.3f}" for r in top) + '.')
    st = A['breakdowns']['circuit_class'].get('street')
    if st:
        F.append(f"Street circuits stay close to unpredictable: on A (street, {st[best]['n_rows']} rows) `{best}` reaches r {_fmt(st[best]['pearson_r'], 2)} (Orb v1 {_fmt(st['orb_v1']['pearson_r'], 2)}) and MAE "
                 f"{_fmt(st[best]['mae'])} against climatology {_fmt(st['climatology']['mae'])}. Its conformal 90% band covers {_fmt(mA[best]['coverage90'], pct=True)} on A and {_fmt(mB[best]['coverage90'], pct=True)} on B "
                 f"at mean width {_fmt(mA[best]['mean_band_width'], 3)}, against Orb v1's native band at {_fmt(mA['orb_v1']['coverage90'], pct=True)} and {_fmt(mB['orb_v1']['coverage90'], pct=True)} (width {_fmt(mA['orb_v1']['mean_band_width'], 3)}).")
    C = [f"`{best}` was the best of {len(ev['learned_candidates'])} learned candidates on protocol A, so its A figures carry selection optimism; B has {B['n_weekends']} weekends and wide intervals.",
         "Both protocols use Orb v1's within-season leave-one-out factor pool (as in SCORECARDS.md), for the baseline and for the orb_v1 input. "
         f"In B a 2026 row's Orb v1 forecast therefore draws on the other {B['n_weekends'] - 1} 2026 races, while the learned parameters see only 2023-2025. "
         "Orb v1 was also built on the 2026 season files (pipeline.py reads feat/; evaluation/forecast.py extends its rules to 2023-2025), so its 2026 figures may be flattered.",
         "The target is itself a noisy race-derived estimate; no race-weekend quantity (race track temperature, race laps, obs_se) is an input, and degradation_class is excluded as a possible outcome-informed label.",
         "Circuit history comes from strictly earlier seasons only, so 2023 rows and new circuits (Madrid) have none; a sealed weekend is never a source (Monza 2025 falls back to Monza 2023).",
         "Development evaluation only: the sealed holdout was not touched, no figure here is a sealed-holdout result, and the learned model is not part of the shipping product."]
    return F, C


def evaluate(jobs: int = 10, refresh: bool = False, quiet: bool = False) -> dict[str, Any]:
    from evaluation import git_sha, now_iso
    from evaluation.common import paired_probability, write_json
    t0 = time.time()
    PRERACE_OUT.mkdir(parents=True, exist_ok=True)
    frame, cn_status = build_frame(refresh_orb=refresh)
    X0, audit0 = features(frame, ())
    dev_mask = frame['development'] & frame['obs'].notna()
    reimpl = float(np.nanmax(np.abs(X0.loc[dev_mask, 'orb_v1'] - frame.loc[dev_mask, 'orb_v1_cached'])))
    hist_ok = all(all(_season(s) < frame.at[i, 'season'] for s in audit0.at[i, 'hist_sources']) for i in frame.index)
    assert reimpl < 1e-9, f'Orb v1 reimplementation differs from SeasonForecaster by {reimpl}'
    assert hist_ok, 'circuit history used a season >= the row season'
    hist_sources = {s for lst in audit0['hist_sources'] for s in lst}
    assert_no_sealed(hist_sources, 'circuit-history sources')
    splits_A = protocol_A_splits(frame)
    split_B = protocol_B_split(frame)
    if not quiet:
        print(f'frame {len(frame)} rows, development {int(dev_mask.sum())} rows / {len(development_weekends(frame))} weekends; C-numbers {cn_status}', flush=True)
    tA = time.time()
    folds_A = run_splits(frame, splits_A, jobs=jobs)
    tB = time.time()
    folds_B = run_splits(frame, [split_B], jobs=1)
    tE = time.time()
    names = learned_names()
    models = list(BASELINES) + ['orb_v1_conformal'] + names
    out: dict[str, Any] = dict(title='Orb PreRace: learned practice-to-race transfer model vs Orb v1', generated_at=now_iso(), git_sha=git_sha(), units=UNITS,
                               target='obs: race-derived pace-loss reference slope per compound (model_v2 fit on the race, all drivers); development weekends only',
                               features=list(FEATURES), feature_notes=FEATURE_NOTES, excluded_inputs=['degradation_class (hand label that may encode outcomes)', 'race track temperature', 'n_race', 'obs_se'],
                               grids={k: list(v) for k, v in GRIDS.items()}, targets=list(TARGETS), blend_weights=list(BLEND_WEIGHTS), inner_k=INNER_K, level=LEVEL,
                               learned_candidates=names, c_numbers=cn_status,
                               orb_v1_check=dict(reimplementation_max_abs_diff_vs_season_forecaster=reimpl, fold_max_abs_diff=max(f['orb_v1_reimplementation_max_abs_diff'] or 0.0 for f in folds_A + folds_B),
                                                 rule='SeasonForecaster.forecast(event, pool=season development events minus event, target_obs_in_widening=False); cache out/tyreformer/prerace/cache_orbv1_<season>.json'),
                               row_counts=dict(frame_rows=int(len(frame)), development_rows=int(dev_mask.sum()), development_weekends=len(development_weekends(frame)),
                                               by_season={str(s): dict(rows=int((dev_mask & (frame['season'] == s)).sum()), weekends=int(frame.loc[dev_mask & (frame['season'] == s), 'race_id'].nunique())) for s in SEASONS}),
                               protocols={})
    for key, folds, desc in (('A', folds_A, 'leave-one-weekend-out over every development weekend 2023-2026 (grouped by season+event); training features computed without the held-out weekend; used for model selection'),
                             ('B', folds_B, 'train on the 2023-2025 development weekends, test on every 2026 development weekend; untouched: no choice made on B')):
        P = assemble(frame, folds)
        assert all(np.isfinite(P[m]).all() for m in models), f'protocol {key}: a model left a row without a forecast'
        pr = evaluate_protocol(P, models)
        pr.update(description=desc, n_folds=len(folds), train_rows_per_fold=dict(min=min(f['n_train_rows'] for f in folds), max=max(f['n_train_rows'] for f in folds)),
                  choices=_choices(folds, names), predictions=P)
        out['protocols'][key] = pr
    best = select_model(out['protocols']['A']['metrics'], names)
    out['selection'] = dict(chosen_model=best, rule='lowest protocol-A MAE among the learned candidates (ties: higher Spearman); protocol B was not consulted', family=parse_name(best)[0],
                            target=parse_name(best)[1], blend_toward_orb_v1=parse_name(best)[2], hyperparameters_by_fold_A=out['protocols']['A']['choices'][best],
                            hyperparameters_B=folds_B[0]['diag'][best])
    for key in ('A', 'B'):
        pr = out['protocols'][key]
        P = pr.pop('predictions')
        pr['bootstrap'] = bootstrap(P, models)
        P2 = P.assign(err_best=(P[best] - P['obs']).abs(), err_orb=(P['orb_v1'] - P['obs']).abs())
        pr['bootstrap']['p_best_beats_orb_v1_evaluation_common'] = paired_probability(P2, 'err_best', 'err_orb')
        pr['bootstrap']['p_best_beats_orb_v1_evaluation_common'].pop('share_rows_bootstrap', None)
        pr['highest_reference_rows'] = [dict(race_id=r['race_id'], event=r['event'], compound=r['compound'], obs=float(r['obs']), orb_v1=float(r['orb_v1']), selected=float(r[best]),
                                             climatology=float(r['climatology'])) for r in P.sort_values('obs', ascending=False).head(3).to_dict('records')]
        keep = ['season', 'event', 'compound', 'race_id', 'circuit_class', 'gate', 'cnum', 'obs', 'orb_v1', 'orb_v1_lo', 'orb_v1_hi', 'naive', 'naive_lo', 'naive_hi',
                'climatology', 'climatology_lo', 'climatology_hi']
        cols = keep + [c for m in names for c in (m, f'{m}_lo', f'{m}_hi')]
        P[cols].rename(columns={'cnum': 'c_number'}).round(6).to_csv(PRERACE_OUT / f'predictions_{key}.csv', index=False)
    n_frames = len(folds_A) + len(folds_B)
    out['sealed_exclusion'] = dict(asserted=True, passed=True, sealed_race_ids=sorted(sealed_ids()), sealed_weekend_files_read=False,
                                   training_frames_checked=n_frames, violations=0, frame_race_ids=int(frame['race_id'].nunique()), history_sources_checked=len(hist_sources),
                                   method='SeasonForecaster built on events without the sealed weekends; assert_no_sealed on the frame, every training and test frame and every circuit-history source')
    out['timing_s'] = dict(frame_and_checks=round(tA - t0, 1), protocol_A=round(tB - tA, 1), protocol_B=round(tE - tB, 1))
    mad = predict_weekend(2026, 'Madrid', model=best, frame=frame)
    write_json(PRERACE_OUT / 'forecast_Madrid_2026.json', mad)
    out['madrid_2026'] = dict(path='out/tyreformer/prerace/forecast_Madrid_2026.json', model=best, training_rows=mad['training']['n_rows'],
                              compounds={c: dict(prediction=v['prediction'], band90=v['band90'], orb_v1=v['orb_v1']['prediction'], orb_v1_band90=v['orb_v1']['band90'],
                                                 orb_v1_issued=v['orb_v1']['issued']) for c, v in mad['compounds'].items()})
    out['findings'], out['caveats'] = findings(out)
    out['timing_s']['total'] = round(time.time() - t0, 1)
    write_json(PRERACE_OUT / 'prerace_eval.json', out)
    (PRERACE_OUT / 'PRERACE.md').write_text(render_md(out), encoding='utf-8')
    if not quiet:
        for key in ('A', 'B'):
            m, b = out['protocols'][key]['metrics'], out['protocols'][key]['bootstrap']['models']
            print(f'protocol {key}:')
            for name in ['orb_v1', 'naive', best]:
                print(f"  {name:22s} MAE {_ci(b[name]['mae'])} r {_ci(b[name]['pearson_r'], 2)} rho {_fmt(m[name]['spearman_rho'], 2)} slope {_fmt(m[name]['calibration_slope'], 2)} "
                      f"beats-naive {_fmt(m[name]['share_beats_naive'], pct=True)} cov {_fmt(m[name]['coverage90'], pct=True)}")
            print(f"  P({best} beats Orb v1) = {b[best]['mae_minus_orb_v1']['p_beats']:.3f}; diff {_ci(b[best]['mae_minus_orb_v1'])}")
        print(f"wrote {PRERACE_OUT} in {out['timing_s']['total']} s")
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--jobs', type=int, default=10)
    ap.add_argument('--refresh', action='store_true', help='recompute the Orb v1 forecast caches')
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    evaluate(jobs=a.jobs, refresh=a.refresh, quiet=a.quiet)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
