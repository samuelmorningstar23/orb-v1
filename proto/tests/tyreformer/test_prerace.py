"""Orb PreRace leakage contract: no sealed weekend in any frame, circuit history from strictly earlier seasons only, and a
held-out weekend's forecast unchanged when its own race outcome is altered (perturbation), with a positive control.

No __init__.py in this directory on purpose: a `tyreformer` test package would shadow proto/tyreformer on sys.path.
Run from proto/:  ../.venv/bin/python -m pytest tests/tyreformer/test_prerace.py -q -p no:cacheprovider
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from tyreformer import prerace as PR  # noqa: E402

# one setting per family keeps the leakage checks fast; the property is structural and identical for the full grids
FAST_GRIDS = {'ridge': PR.GRIDS['ridge'][2:4], 'huber': PR.GRIDS['huber'][1:2], 'hgbr': PR.GRIDS['hgbr'][:1]}
FAST_K = 4


@pytest.fixture(scope='module')
def frame() -> pd.DataFrame:
    f, _ = PR.build_frame()
    return f


def _learned(fold: dict) -> list[str]:
    return [m for m in fold['preds'] if m not in PR.BASELINES + ('orb_v1_conformal',)]


def test_no_sealed_race_id_in_any_training_frame(frame):
    sealed = PR.sealed_ids()
    assert sealed
    assert not set(frame['race_id']) & sealed
    for s in PR.SEASONS:
        assert not {f'{s}_{e}' for e in PR.season_forecaster(s).metas} & sealed, f'a sealed weekend table was loaded for {s}'
    splits = PR.protocol_A_splits(frame) + [PR.protocol_B_split(frame), PR.weekend_split(frame, 2026, 'Madrid')]
    assert len(splits) == len(PR.development_weekends(frame)) + 2
    for train, test in splits:
        assert train and test
        assert not set(train) & sealed and not set(test) & sealed
        assert not set(train) & set(test)
    train_B, test_B = PR.protocol_B_split(frame)
    assert {PR._season(w) for w in train_B} <= {2023, 2024, 2025} and {PR._season(w) for w in test_B} == {2026}
    # the guards refuse a sealed id
    probe = sorted(sealed)[0]
    with pytest.raises(AssertionError):
        PR.assert_no_sealed([probe], 'probe')
    with pytest.raises(PermissionError):
        PR.predict_weekend(PR._season(probe), probe.split('_', 1)[1], model='ridge_obs', frame=frame)
    for name in ('predictions_A.csv', 'predictions_B.csv'):
        p = PR.PRERACE_OUT / name
        if p.exists():
            assert not set(pd.read_csv(p, usecols=['race_id'])['race_id']) & sealed


def test_orb_v1_reimplementation_matches_season_forecaster(frame):
    X, _ = PR.features(frame)
    m = frame['orb_v1_cached'].notna()
    assert m.sum() > 150
    np.testing.assert_allclose(X.loc[m, 'orb_v1'].to_numpy(), frame.loc[m, 'orb_v1_cached'].to_numpy(), rtol=0, atol=1e-12)


def test_circuit_history_uses_strictly_earlier_seasons_only(frame):
    X, audit = PR.features(frame)
    sealed = PR.sealed_ids()
    has = X['hist_missing'] == 0
    assert has.sum() > 50
    for i in frame.index[has]:
        s = frame.at[i, 'season']
        assert audit.at[i, 'hist_last_season'] < s
        assert audit.at[i, 'hist_sources'] and all(PR._season(r) < s for r in audit.at[i, 'hist_sources'])
        assert not set(audit.at[i, 'hist_sources']) & sealed
        assert all(r.split('_', 1)[1] == frame.at[i, 'event'] for r in audit.at[i, 'hist_sources'])
    assert (X.loc[frame['season'] == 2023, 'hist_missing'] == 1).all()
    assert (X.loc[frame['race_id'] == '2026_Madrid', 'hist_missing'] == 1).all()
    cols = ['hist_last', 'hist_mean', 'hist_missing']
    for s in PR.SEASONS:
        g = frame.copy()
        g.loc[g['season'] >= s, 'obs'] = g.loc[g['season'] >= s, 'obs'] + 1.0     # alter every race of season s and later
        Xg, _ = PR.features(g)
        rows = frame['season'] == s
        pd.testing.assert_frame_equal(X.loc[rows, cols], Xg.loc[rows, cols])


@pytest.mark.parametrize('target', ['2025_Hungary', '2026_Monza'])
def test_loo_forecast_unchanged_when_held_out_race_is_altered(frame, target):
    dev = PR.development_weekends(frame)
    assert target in dev
    train = [w for w in dev if w != target]
    base = PR.run_fold(frame, train, [target], grids=FAST_GRIDS, inner_k=FAST_K)
    g = frame.copy()
    m = g['race_id'] == target
    g.loc[m, 'obs'] = 0.5 - 3.0 * g.loc[m, 'obs']
    pert = PR.run_fold(g, train, [target], grids=FAST_GRIDS, inner_k=FAST_K)
    assert set(base['preds']) == set(pert['preds']) and len(_learned(base)) == 12
    for name, d in base['preds'].items():
        for k in ('pred', 'lo', 'hi'):
            np.testing.assert_array_equal(d[k], pert['preds'][name][k], err_msg=f'{target} {name} {k} moved with its own race')
    # positive control: altering one training race of the same season does move the learned forecast
    season = PR._season(target)
    other = next(w for w in train if PR._season(w) == season)
    h = frame.copy()
    h.loc[h['race_id'] == other, 'obs'] = h.loc[h['race_id'] == other, 'obs'] + 0.3
    ctrl = PR.run_fold(h, train, [target], grids=FAST_GRIDS, inner_k=FAST_K)
    moved = [n for n in _learned(base) if not np.allclose(base['preds'][n]['pred'], ctrl['preds'][n]['pred'])]
    assert len(moved) >= 6, f'the perturbation check has no power: only {moved} moved'


def test_temporal_forecast_unchanged_when_a_2026_race_is_altered(frame):
    train, test = PR.protocol_B_split(frame)
    base = PR.run_fold(frame, train, test, grids=FAST_GRIDS, inner_k=FAST_K)
    target = '2026_Hungary'
    g = frame.copy()
    m = g['race_id'] == target
    g.loc[m, 'obs'] = g.loc[m, 'obs'] + 0.4
    pert = PR.run_fold(g, train, test, grids=FAST_GRIDS, inner_k=FAST_K)
    rows = np.flatnonzero(frame.loc[base['test_index'], 'race_id'].to_numpy() == target)
    assert len(rows) >= 2
    assert all(PR._season(w) < 2026 for w in base['train_ids'])
    for name, d in base['preds'].items():
        for k in ('pred', 'lo', 'hi'):
            np.testing.assert_array_equal(d[k][rows], pert['preds'][name][k][rows], err_msg=f'{target} {name} {k} moved with its own race')


def test_madrid_2026_forecast(frame):
    out = PR.predict_weekend(2026, 'Madrid', model='ridge_resid', frame=frame, inner_k=FAST_K)
    assert out['compounds'] and set(out['compounds']) <= set(PR.COMPS)
    assert out['training']['n_weekends'] == len(PR.development_weekends(frame))
    for c, v in out['compounds'].items():
        assert np.isfinite(v['prediction']) and v['band90'][0] <= v['prediction'] <= v['band90'][1]
        assert v['inputs']['hist_missing'] == 1.0
