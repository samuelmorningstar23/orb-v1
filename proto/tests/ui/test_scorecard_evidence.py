"""C5: denominator/uncertainty semantics and both routes share evaluator evidence."""
import json
from pathlib import Path

from app_v2.ui import scorecard_evidence as E
from app_v2.services import validation_repository as VR


def test_metric_table_uses_eligible_n_not_bootstrap_row_count():
    metric = {'estimate': .123456, 'ci90': [.1, .2], 'n': 127, 'n_rows': 3,
              'n_unit': 'eligible prefixes', 'n_weekends': 3,
              'metric_label': 'weighted mean of per-race medians'}
    row = E.metric_rows({'aw_lead_laps_median': metric})[0]
    assert row == ['weighted mean of per-race medians (aw_lead_laps_median)', '0.1235', '[0.1000, 0.2000]', '127 eligible prefixes', 3]


def test_single_weekend_does_not_get_fake_zero_width_band():
    row = {'round': 2, 'event': 'Synthetic', 'n_pool': 1, 'n_compounds': 2,
           'bootstrap': {'mae_orb_v1': {'estimate': .04, 'ci90': None, 'n_rows': 2, 'n_weekends': 1}}}
    html = E.rolling_html({'series': [row]})
    assert 'unavailable' in html and '[0.0400, 0.0400]' not in html
    assert '0.0400' in html and '90% CI by weekend' in html


def test_missing_bootstrap_is_pending_not_unbanded_estimate():
    assert 'pending' in E.forecast_html({'mae': {'orb_v1': .123456}})
    assert '0.1235' not in E.forecast_html({'mae': {'orb_v1': .123456}})


def test_forecast_bands_and_denominators_are_artifact_values():
    ghost, _ = VR.ghost_scorecard()
    block = ghost['development_pool']['forecast']['bootstrap']
    html = E.forecast_html(ghost['development_pool']['forecast'])
    for key, metric in block.items():
        if 'estimate' not in metric:
            continue
        assert key in html and E.number(metric['estimate']) in html
        assert E.interval(metric) in html
        assert f"{metric.get('n', metric.get('n_rows'))} compound-weekends" in html


def test_live_scorecard_uses_all_source_bands_without_reaggregation():
    live, _ = VR.live_scorecard()
    html = E.live_html(live)
    for key, metric in live['pooled'].items():
        assert key in html and E.number(metric['estimate']) in html and E.interval(metric) in html
    assert 'model-implied rate proxy' in html


def test_both_scorecard_routes_use_same_rendered_artifact_rows():
    from test_pages import _run, _text
    ghost, _ = VR.ghost_scorecard()
    live, _ = VR.live_scorecard()
    expected = [E.number(ghost['development_pool']['forecast']['bootstrap']['mae_orb_v1']['estimate']),
                E.interval(live['pooled']['next1_mae']), '90% CI by weekend', E.METHOD]
    for page in ('validation', 'generalisation'):
        text = _text(_run(page, {'ev': 'Monza'}))
        for value in expected:
            assert value in text, (page, value)


def test_sealed_card_does_not_render_unapproved_extra_aggregates():
    from app_v2.pages.generalisation import sealed_html
    html = sealed_html(VR.sealed_block())
    assert 'sealed holdout, aggregate only' in html
    assert 'calibration' not in html and 'by compound' not in html and 'wins over naive' not in html
