"""Chart semantics: source values, timeline units, uncertainty and forecast boundaries."""
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from app_v2.services import lock_repository as LR, replay_service as RS, live_bridge as LB
from app_v2.ui import charts


@pytest.fixture
def hungary():
    lock = LR.load_lock()
    return LB.build(lock, 'Hungary', 'NOR', RS.ReplayCursor('Hungary', 'NOR', 70).seek(38))


def trace(fig, name):
    return next(t for t in fig.data if t.name == name)


def test_current_stint_uses_race_laps_and_exact_projection_values(hungary):
    fig = charts.forecast_vs_live(hungary)
    assert fig.layout.xaxis.title.text == 'Race lap'
    assert list(trace(fig, 'Clean laps').x) == [20, 21, 30]
    future = trace(fig, 'Forecast points')
    assert list(future.x) == [39, 41, 43]
    source = hungary.orb_live['projection'][:3]
    np.testing.assert_allclose(future.y, [p['loss'] for p in source])
    np.testing.assert_allclose(future.customdata, [[p['age'], p['lo'], p['hi']] for p in source])
    assert any(a.text == 'Now · lap 38' and a.x == 38 for a in fig.layout.annotations)
    assert 43 < fig.layout.xaxis.range[1] < 44
    assert 17 < fig.layout.xaxis.range[0] < 18


def test_full_model_range_is_visible_including_negative_bound(hungary):
    fig = charts.forecast_vs_live(hungary)
    lower, upper = fig.layout.yaxis.range
    assert trace(fig, '90% range').mode == 'lines', 'Band edges must not look like observed samples'
    ys = list(trace(fig, '90% range').y)
    assert min(ys) < -1.8
    assert max(ys) > 7.4
    assert lower < min(ys) and upper > max(ys)


def test_other_drivers_and_distant_crossovers_cannot_distort_chart(hungary):
    expected = charts.forecast_vs_live(hungary).to_json()
    changed = deepcopy(hungary)
    changed.crossover = {'M-H': 10000}
    changed.comparable = [{'driver': 'OTHER', 'ages': [999], 'losses': [10000]}]
    assert charts.forecast_vs_live(changed).to_json() == expected


@pytest.mark.parametrize('lap, future_laps', [(52, [53]), (53, [])])
def test_projection_never_runs_past_race_finish(lap, future_laps):
    lock = LR.load_lock()
    vm = LB.build(lock, 'Monza', 'NOR', RS.ReplayCursor('Monza', 'NOR', 53).seek(lap))
    fig = charts.forecast_vs_live(vm)
    points = [t for t in fig.data if t.name == 'Forecast points']
    assert (list(points[0].x) if points else []) == future_laps
    assert all(max(t.x) <= 53 for t in fig.data if len(t.x))


def test_explicit_empty_projection_is_not_replaced_by_synthetic_future(hungary):
    fig = charts.forecast_vs_live(hungary, projection=[])
    assert 'Forecast points' not in [t.name for t in fig.data]
    assert max(max(t.x) for t in fig.data if len(t.x)) <= hungary.lap


def test_no_clean_laps_is_labelled_as_pre_race_estimate():
    lock = LR.load_lock()
    vm = LB.build(lock, 'Monza', 'NOR', RS.ReplayCursor('Monza', 'NOR', 53).seek(1))
    assert vm.state.kept_laps == 0
    names = [t.name for t in charts.forecast_vs_live(vm).data]
    assert 'Pre-race estimate' in names and 'Current fit' not in names
    assert 'Clean laps' not in names


def test_live_page_shows_evidence_instead_of_capped_life_as_expiry(hungary):
    at = AppTest.from_string("""
import streamlit as st
from app_v2.pages import live_predictor
st.session_state.update(ev='Hungary',drv='NOR',lap=38,mode='live')
live_predictor.render()
""").run(timeout=30)
    assert not at.exception, [e.value for e in at.exception]
    html = ' '.join(str(e.value) for e in at.get('html'))
    assert 'Clean laps used' in html and 'Of 21 recorded laps' in html
    assert 'Estimated useful life' not in html
    captions = ' '.join(str(e.value) for e in at.caption)
    assert 'model crossover proxy, capped at laps remaining' in captions
    assert 'Trend uncertain' in captions


def test_pre_race_chart_cannot_show_post_race_outcomes():
    lock = LR.load_lock()
    forecasts = [lock.forecast_for('Monza', c) for c in lock.compounds_for('Monza')]
    assert any(f.observed is not None for f in forecasts)
    expected = charts.pre_race_curves(forecasts).to_json()
    changed = [replace(f, observed=1000, observed_se=99) for f in forecasts]
    assert charts.pre_race_curves(changed).to_json() == expected
    assert not any('observed' in t.name.lower() for t in charts.pre_race_curves(forecasts).data)


def test_ghost_tyre_age_curve_does_not_plot_race_lap_intervention():
    lock = LR.load_lock()
    f = lock.forecast_for('Monza', 'MEDIUM')
    fig = charts.ghost_curves_real({}, 'MEDIUM', 'MEDIUM', f, f, 24, 53, False, 'audit')
    assert not fig.layout.shapes
    assert not fig.layout.annotations
    assert len([t for t in fig.data if t.mode == 'lines' and t.fill != 'toself']) == 1
