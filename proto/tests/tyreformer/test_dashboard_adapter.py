"""Dashboard adapter: plot-ready, integrity-checked, and consistent with the scored replay."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from tyreformer import dashboard_adapter as A  # noqa: E402


@pytest.fixture(autouse=True)
def _need_exports():
    if not (A.LIVE / 'manifest.json').exists():
        pytest.skip('replay forecasts not exported')


def test_forecast_is_plot_ready_and_matches_the_scored_replay():
    assert 'Monza' in A.available_events()
    fc = A.stint_forecast('Monza', 'NOR', 30)
    assert fc is not None and fc['uses_future_data'] is False
    assert [x['h'] for x in fc['horizons']] == list(range(1, 11))
    for x in fc['horizons']:
        assert x['lo90'] <= x['q25'] <= x['median'] <= x['q75'] <= x['hi90']
    rep = pd.read_parquet(PROTO / 'out' / 'tyreformer' / 'predictions' / 'rolling_ensemble.parquet')
    r = rep[(rep['race_id'] == '2026_Monza') & (rep['session'] == 'R') & (rep['driver'] == 'NOR') & (rep['lap'] == 30)].iloc[0]
    assert abs(fc['horizons'][0]['median'] - r['h1_q50']) < 1e-9
    assert A.stint_forecast('Monza', 'NOR', 999) is None
    assert A.stint_forecast('NoSuchRace', 'NOR', 3) is None


def test_tampered_file_is_refused(tmp_path, monkeypatch):
    src = A.LIVE / 'manifest.json'
    live = tmp_path / 'live'
    live.mkdir()
    (live / 'manifest.json').write_bytes(src.read_bytes())
    data = (A.LIVE / '2026_Monza.parquet').read_bytes()
    (live / '2026_Monza.parquet').write_bytes(data[:-10] + b'0123456789')
    monkeypatch.setattr(A, 'LIVE', live)
    A.manifest.cache_clear(); A._race.cache_clear()
    try:
        with pytest.raises(A.IntegrityError):
            A.stint_forecast('Monza', 'NOR', 30)
    finally:
        A.manifest.cache_clear(); A._race.cache_clear()


def test_headline_carries_labels():
    h = A.headline()
    for key in ('cv_2023_2025', 'test_2026'):
        assert h[key]['label'] and h[key]['next1']['tyreformer'] < h[key]['next1']['orb_v1_estimator']
    if 'sealed_holdout' in h:
        assert h['sealed_holdout']['label'] == 'sealed holdout, aggregate only'
