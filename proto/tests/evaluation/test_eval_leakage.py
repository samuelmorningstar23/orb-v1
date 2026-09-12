"""Leakage: a sealed weekend's race never enters the factor pool used for any forecast (asserted by construction with a spy)."""
from __future__ import annotations

import json

import numpy as np
import pytest

from evaluation.forecast import SeasonForecaster, PoolSpy, score_forecast
from evaluation.holdout import evaluator as E


def test_sealed_never_in_any_pool(synthetic_season):
    season, d, events = synthetic_season['season'], synthetic_season['dir'], synthetic_season['events']
    sealed = [f'{season}_{events[2]}']
    spy = PoolSpy()
    F = SeasonForecaster(d, season, sealed=sealed, spy=spy)
    assert events[2] not in F.development_events and len(F.development_events) == 4
    loo = F.loo_forecasts()                                      # every development weekend, pool minus itself
    sealed_fc = F.forecast(events[2], F.development_events)      # the sealed weekend from the development pool
    assert sealed_fc.pool_events == sorted(e for e in events if e != events[2])
    for ev, fc in loo.items():
        assert events[2] not in fc.pool_events and ev not in fc.pool_events
    # the spy saw every pool read: no source is the sealed race, for any target
    assert sealed[0] not in spy.all_sources()
    assert spy.records, 'the spy must have seen pool reads'
    for target in [F.rid(e) for e in events]:
        assert sealed[0] not in spy.sources_for(target)
    # offering the sealed weekend as a pool member is refused, whatever the target
    with pytest.raises(PermissionError):
        F.forecast(events[0], events)
    with pytest.raises(PermissionError):
        F.scorable([events[2]])
    with pytest.raises(PermissionError):
        F.forecast(events[2], F.development_events, target_obs_in_widening=True)


def test_evaluate_sealed_reports_no_leak(synthetic_season):
    season, d, events = synthetic_season['season'], synthetic_season['dir'], synthetic_season['events']
    rid = f'{season}_{events[4]}'
    manifest = dict(race_ids=[rid], holdout_count=1, prohibited_for_tuning=True, metadata={rid: dict(circuit_class='permanent', degradation_class='high', temperature_regime='mild', sc_or_vsc=False)})
    spy = PoolSpy()
    res = E.evaluate_sealed(manifest, season_dirs={season: d}, spy=spy, bootstrap=False)
    assert res['leakage']['sealed_never_in_pool'] is True and res['leakage']['leaks'] == []
    assert res['leakage']['pool_events_by_season'][str(season)] == events[:4]
    assert rid not in res['leakage']['sources_seen'] and spy.records
    assert res['n_weekends'] == 1 and rid in res['per_race'] and 'forecast' in res['per_race'][rid]
    # the noise-free synthetic weekend is forecast exactly (k = 1) and inside its band
    rows = res['per_race'][rid]['forecast_rows']
    assert rows and all(r['err'] < 1e-6 for r in rows) and all(r['covered'] for r in rows)
    assert json.dumps(res['aggregate'])                          # serialisable aggregate


def test_forecaster_reproduces_lock_leave_one_out(real_data_available):
    """Provider-A style check: the 2026 development pool forecast equals out/lock.json's leave-one-weekend-out rows."""
    if not real_data_available:
        pytest.skip('feat/ or out/lock.json not present')
    from evaluation import PROTO
    F = SeasonForecaster(PROTO / 'feat', 2026)
    loo = F.loo_forecasts()
    rows = {(r['event'], r['compound']): r for r in json.loads((PROTO / 'out' / 'lock.json').read_text())['validation_rows']}
    n = 0
    for ev, fc in loo.items():
        for c, f in fc.compounds.items():
            r = rows.get((ev, c))
            if r is None or r.get('pred_clearstint') is None:
                continue
            n += 1
            assert abs(r['pred_clearstint'] - f.prediction) < 1e-4, (ev, c)
            assert abs(r['k'] - f.factor) < 1e-4 and bool(r['k_applied']) == f.factor_applied
            if r.get('floor') is not None and f.floor is not None:
                assert abs(r['floor'] - f.floor) < 1e-4
            assert abs(r['widen'] - f.widen) < 0.05                # Monte Carlo band (4000 samples)
    assert n >= 20
