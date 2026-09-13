"""Live inference equals the scored replay for the same origin, and refuses laps completed after the forecast moment."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from tyreformer import OUT, data as D  # noqa: E402
from tyreformer.train import MODELS, PRED  # noqa: E402


@pytest.fixture(scope='module')
def live():
    if not (MODELS / 'temporal_final.pt').exists() or not (MODELS / 'gbm_temporal_final.pkl').exists() or not (OUT / 'ensemble.json').exists():
        pytest.skip('temporal ensemble not trained')
    from tyreformer.infer import TyreFormerLive
    return TyreFormerLive('temporal')


def test_live_forecast_equals_scored_replay_and_refuses_future_laps(live):
    from tyreformer.infer import FutureDataError
    full = D.load_session(2026, 'Monza', 'R')
    n_laps = int(full['LapNumber'].max())
    priors = D.season_priors(2026).get('Monza')
    drv, k = 'NOR', 30
    mine = full[(full['Driver'] == drv) & (full['LapNumber'] == k)].iloc[0]
    cutoff = float(mine['t_min']) * 60.0 + float(mine['lap_s'])
    t_end = full['t_min'] * 60.0 + full['lap_s']
    so_far = full[t_end <= cutoff + 1e-6].reset_index(drop=True)
    fc = live.forecast(2026, 'Monza', so_far, drv, n_laps, priors, lap=k)
    assert fc['available'] and fc['uses_future_data'] is False
    replay = pd.read_parquet(PRED / 'temporal_ensemble.parquet')
    r = replay[(replay['race_id'] == '2026_Monza') & (replay['session'] == 'R') & (replay['driver'] == drv) & (replay['lap'] == k)].iloc[0]
    for h in (1, 3, 5, 10):
        assert np.isclose(fc['horizons'][h - 1]['median'], r[f'h{h}_q50'], atol=2e-3), h
    assert np.isclose(fc['cum5']['median'], r['cum5_q50'], atol=5e-3)
    assert np.isclose(fc['cliff_probability_5_laps'], r['cliff_p5'], atol=1e-3)
    lo, hi = fc['horizons'][0]['lo90'], fc['horizons'][0]['hi90']
    assert lo < fc['horizons'][0]['median'] < hi
    with pytest.raises(FutureDataError):
        live.forecast(2026, 'Monza', full, drv, n_laps, priors, lap=k)
