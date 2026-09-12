"""C5 evaluation evidence: cluster counts, source-faithful pooling, frozen-rule diagnostics."""
import json
import numpy as np
import pandas as pd
import pytest
from evaluation.common import weekend_bootstrap, weekend_mean_bootstrap
from evaluation.scorecards import live_scorecard, _forecast_block, render_rolling, _ci
from evaluation.risk_coverage import sweep
from evaluation.forecast import SeasonForecaster, MIN_PRAC, MIN_SLOPE


def test_fast_mean_matches_literal_whole_weekend_resampling():
    df = pd.DataFrame(dict(race_id=['A']*3+['B']*7+['C']*2, v=[1.,3.,9.]+[0.]*7+[20.,30.]))
    a = weekend_mean_bootstrap(df, 'v', n=400, seed=13)
    b = weekend_bootstrap(df, lambda d: float(d.v.mean()), n=400, seed=13)
    assert a['estimate'] == pytest.approx(b['estimate'])
    assert a['ci90'] == pytest.approx(b['ci90'])
    assert (a['n'], a['n_weekends']) == (12, 3)


def test_weighted_mean_counts_eligible_windows_and_weekends():
    df = pd.DataFrame(dict(race_id=['A','B','C'], v=[1.,3.,None], count=[10,30,200]))
    b = weekend_mean_bootstrap(df, 'v', 'count', n_unit='windows')
    assert b['estimate'] == 2.5
    assert (b['n'], b['n_weekends'], b['n_rows']) == (40, 2, 2)
    assert b['ci90'] == [1.,3.]
    assert b['n_unit'] == 'windows'


def test_single_weekend_metric_discloses_unavailable_band():
    b = weekend_mean_bootstrap(pd.DataFrame(dict(race_id=['A']*5, v=[1.]*5)), 'v')
    assert b['ci90'] is None and b['n_weekends'] == 1
    assert '90% CI unavailable' in _ci(b) and 'n=5' in _ci(b)


def test_empty_metric_discloses_zero_support():
    b = weekend_mean_bootstrap(pd.DataFrame(dict(race_id=['A'], v=[None])), 'v')
    assert b['estimate'] is None and b['ci90'] is None and b['n'] == 0


def test_live_median_recomputed_from_stints_and_climatology_from_pooled_counts(tmp_path, monkeypatch):
    import evaluation.scorecards as S
    monkeypatch.setattr(S, 'PROTO', tmp_path)
    p = tmp_path / 'prefix.json'
    source = dict(races={
      'A':dict(next1_mae=1.,next1_n=10,aw_lead_laps_median=1.,aw_true_stints=1,cliff5_n=10,cliff5_events=1,cliff5_brier_climatology=.09),
      'B':dict(next1_mae=3.,next1_n=30,aw_lead_laps_median=10.,aw_true_stints=3,cliff5_n=30,cliff5_events=15,cliff5_brier_climatology=.25)},
      per_stint_alerts={'A':[dict(truth=True,lead_laps=1.)], 'B':[dict(truth=True,lead_laps=x) for x in [2.,10.,20.]]},
      pooled=dict(next1_mae=2.5,aw_lead_laps_median=6.,cliff5_brier_climatology=.24))
    p.write_text(json.dumps(source))
    out = live_scorecard(p, tmp_path/'no_feedback', tmp_path/'no_live', quiet=True)
    assert out['pooled']['aw_lead_laps_median']['estimate'] == 6.
    assert out['pooled']['aw_lead_laps_median']['n'] == 4
    assert out['pooled']['cliff5_brier_climatology']['estimate'] == pytest.approx(.24)
    assert all(v['match'] for v in out['source_consistency'].values())


def test_risk_sweep_adds_cluster_intervals_without_changing_gate(synthetic_season):
    s = synthetic_season
    f = SeasonForecaster(s['dir'], s['season'])
    table = sweep([f], laps_grid=[30], slope_grid=[.02])
    row = table.iloc[0]
    for k, b in row['bootstrap'].items():
        assert b['estimate'] == pytest.approx(row[k])
        assert b['n_weekends'] <= row['n_weekends']
        assert b['n_unit'] == 'compound-weekends'
        if b['n_weekends'] >= 2:
            assert len(b['ci90']) == 2
    assert (f.min_prac, f.min_slope) == (MIN_PRAC, MIN_SLOPE)
