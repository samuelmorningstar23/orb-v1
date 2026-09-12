"""Display the evaluator's estimates and uncertainty verbatim; never resample in the UI."""
from __future__ import annotations
import streamlit as st
from app_v2.services import validation_repository as VR
from app_v2.ui import cards
from app_v2.ui.formatting import esc

METHOD = '90% CI: weekend-grouped bootstrap (resample weekends, never rows). Counts are denominators, not estimates. A single weekend cannot support a weekend-bootstrap band.'


def number(value):
    return '—' if value is None else f'{value:.4f}'


def interval(metric):
    band = metric.get('ci90')
    if band is None:
        return 'unavailable — ' + metric.get('ci90_status', metric.get('note', 'insufficient independent weekends'))
    return f'[{number(band[0])}, {number(band[1])}]'


def metric_rows(metrics, default_unit='observations'):
    """No inferred denominators: use the count and unit supplied by the evaluator."""
    rows = []
    for key, metric in metrics.items():
        if not isinstance(metric, dict) or 'estimate' not in metric:
            continue
        label = metric.get('metric_label') or key
        if label != key:
            label += f' ({key})'
        n = metric.get('n', metric.get('n_rows'))
        unit = metric.get('n_unit', default_unit)
        rows.append([label, number(metric['estimate']), interval(metric), f'{n if n is not None else "—"} {unit}', metric.get('n_weekends', '—')])
    return rows


def metrics_html(metrics, default_unit='observations'):
    rows = metric_rows(metrics, default_unit)
    return cards.table_html(['metric (source label)', 'estimate', '90% CI by weekend', 'n', 'weekends'], rows, numeric_cols=(1, 4)) if rows else '<div class="cs-muted">Bootstrap evidence pending; no estimate substituted.</div>'


def forecast_html(forecast):
    return metrics_html(forecast.get('bootstrap') or {}, 'compound-weekends')


def block_html(block):
    body = '<div class="cs-src">ghost_scorecard · development pool · pre-race forecast · s/lap for MAE; proportions for coverage</div>' + forecast_html(block.get('forecast') or {})
    hidden = block.get('hidden_stop') or {}
    if hidden.get('bootstrap'):
        body += '<div class="cs-src">hidden-stop response · seconds for MAE; proportions for coverage</div>' + metrics_html(hidden['bootstrap'], 'eligible stops')
    regret = block.get('regret') or {}
    if regret.get('plans'):
        body += f'<div class="cs-src">{esc(VR.REGRET_LABEL)} · seconds</div>'
        for plan, values in regret['plans'].items():
            body += f'<div class="cs-muted">{esc(plan)}</div>' + metrics_html({key: values[key] for key in ('ci90_mean', 'ci90_median') if key in values}, 'scorable weekends')
    return body


def live_html(data):
    if not data:
        return '<div class="cs-muted">Live Predictor scorecard pending</div>'
    return ('<div class="cs-src">Live Predictor scorecard · separate scorecard, never merged with Ghost Strategy</div>' + metrics_html(data.get('pooled') or {}) + '<div class="cs-muted">model-implied rate proxy (no cliff mechanism in the linear model). Brier scores are worse than climatology and shown as such. '
            + esc(data.get('note', '')) + '</div>')


def rolling_html(rolling):
    rows = []
    for row in rolling.get('series') or []:
        metrics = row.get('bootstrap') or {}
        if not metrics:
            rows.append([row.get('round'), row.get('event'), row.get('n_pool'), '—', '—', row.get('note', 'evidence pending'), '—', '—'])
        for key, metric in metrics.items():
            rows.append([row.get('round'), row.get('event'), row.get('n_pool'), key, number(metric.get('estimate')), interval(metric), metric.get('n', metric.get('n_rows', row.get('n_compounds', '—'))), metric.get('n_weekends', '—')])
    return cards.table_html(['round', 'event', 'prior pool', 'metric', 'estimate', '90% CI by weekend', 'n compound-weekends', 'weekends'], rows, numeric_cols=(0, 2, 4, 6, 7))


def render(*, cells=False):
    ghost, ga = VR.ghost_scorecard(); live, la = VR.live_scorecard(); risk, ra = VR.risk_coverage()
    st.html(f'<div class="cs-muted">{esc(METHOD)}</div>')
    cards.section('Ghost Strategy scorecard', 'ghost_scorecard · development pool · forecast; development pool, leave-one-weekend-out inside each season')
    if ghost:
        pool = ghost.get('development_pool') or {}
        st.html(block_html(pool))
        if cells:
            for group in ('by_season', 'by_circuit_class', 'by_weather_regime', 'by_driver_support'):
                with st.expander(group.replace('_', ' ') + ' · development pool', expanded=False):
                    for name, block in (pool.get(group) or {}).items():
                        st.html(cards.card_html(str(name), block_html(block)))
        rolling = ghost.get('rolling_origin_2026') or {}
        cards.section('Rolling origin, 2026', rolling.get('method', 'pending'))
        st.html(rolling_html(rolling))
        for label, key in [('all forecastable rounds', 'pooled'), ('prior pool of at least three rounds', 'pooled_from_round_4')]:
            st.html(cards.card_html('Rolling origin · ' + label, forecast_html(rolling.get(key) or {})))
    cards.section('Live Predictor scorecard', 'from out/live/prefix_eval.json · separate scorecard, never merged with Ghost Strategy; MAE in seconds, coverage and rates as proportions')
    st.html(live_html(live))
    cards.section('Abstention: risk-coverage sweep (risk_coverage.json)', 'coverage = share of compound-weekends issued; the production gate is frozen; the sweep is reported, never used to retune')
    if risk:
        png = VR.risk_coverage_png()
        if png.exists:
            st.image(png.path, caption=f'risk_coverage.png · sha256 {png.short_hash} · uncertainty and denominators below', width='stretch')
        for label, key in [('production gate', 'production_gate'), ('lowest MAE over all cases in the sweep', 'best_mae_all')]:
            gate = risk.get(key) or {}
            st.html(cards.card_html(label, f'<div class="cs-muted">gate settings: min laps {esc(gate.get("min_laps"))}; min slope {esc(gate.get("min_slope"))}</div>' + metrics_html(gate.get('bootstrap') or {}, 'compound-weekends')))
    st.html('<div class="cs-muted">' + ' · '.join(esc(VR.provenance(d, a, n)) for d, a, n in [(ghost, ga, 'ghost_scorecard.json'), (live, la, 'live_scorecard.json'), (risk, ra, 'risk_coverage.json')]) + '</div>')
    st.html(f'<div class="cs-muted">SCORECARDS.md · sha256 {VR.scorecards_md().short_hash}</div>')
