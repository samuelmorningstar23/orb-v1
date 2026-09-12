"""Route 7, Validation: the v1 numbers (calibration ladder, per compound, withheld cases, band coverage, sensitivity),
Workstream 8's live-prefix evaluation (three races) with its honest reading, and Workstream 2's counterfactual identity tests."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import asset_repository as A
from app_v2.services import counterfactual_repository as CF
from app_v2.services import live_bridge as LB
from app_v2.services import paths as P
from app_v2.ui import shell, cards, badges, charts, banners, empty_states
from app_v2.ui.formatting import esc, pct

GATE_SHORT = {'no positive degradation signal in cleaned practice': 'no +deg signal', 'too few clean practice laps': 'too few clean laps'}


def prefix_rows(pe: dict) -> list[list]:
    rows = []
    for name, r in list(pe.get('races', {}).items()) + [('pooled', pe.get('pooled', {}))]:
        if not r:
            continue
        rows.append([name, f"{r['drivers']}", f"{r['laps']}", f"{r['next1_mae']:.3f} / {r['next1_mae_prior_only']:.3f}", f"{r['cum3_mae']:.3f} / {r['cum3_mae_prior_only']:.3f}", f"{r['cum5_mae']:.3f} / {r['cum5_mae_prior_only']:.3f}",
                     f"{pct(r['coverage90_next1'])} / {pct(r['coverage90_next1_prior_only'])}", pct(r['coverage90_next3']), f"{r['cliff5_brier']:.3f} vs {r['cliff5_brier_climatology']:.3f} ({r['cliff5_events']}/{r['cliff5_n']})",
                     f"{pct(r['aw_detection_rate'])} of {r['aw_true_stints']} · {r['aw_lead_laps_median']:.1f} laps", f"{r['aw_false_alert_episodes_per_stint']:.2f}", pct(r['recommendation_change_rate'])])
    return rows


def render() -> None:
    ctx = common.context('validation')
    if not common.require_lock(ctx, 'validation'):
        return
    lock = ctx.lock
    common.header(ctx, 'validation', support='held-out', latency='n/a', session='Validation')
    v = lock.validation; cal = v.get('calibration', {}); m = v.get('mae_issued', {}); a = v.get('mae_all_with_fallback', {})
    st.markdown(f"## Leave-one-weekend-out over {v.get('n_weekends')} weekends, {v.get('n_compound_weekends')} compound-weekends: {v.get('n_issued')} issued, {v.get('n_withheld')} withheld")
    banners.audit_banner()
    k = st.columns(5)
    with k[0]:
        cards.kpi_card('MAE ORB V1', f"{a.get('clearstint', float('nan')):.3f}", f"all cases · 90% CI {v['ci90_mae_clearstint_all'][0]:.3f} to {v['ci90_mae_clearstint_all'][1]:.3f}", 'live', 'lock.validation', 's/lap')
    with k[1]:
        cards.kpi_card('MAE NAIVE', f"{a.get('naive', float('nan')):.3f}", f"wins Orb v1 over naive {v.get('wins_clearstint_over_naive')} of {v.get('n_compound_weekends')}", 'neutral', 'lock.validation', 's/lap')
    with k[2]:
        cards.kpi_card('CALIBRATION SLOPE', f"{cal.get('all_with_fallback', {}).get('slope', float('nan')):+.2f}", f"Pearson r {cal.get('all_with_fallback', {}).get('r', float('nan')):+.2f} · n {cal.get('all_with_fallback', {}).get('n')}", 'neutral', 'lock.validation')
    with k[3]:
        bc = v.get('band_coverage', {})
        cards.kpi_card('BAND COVERAGE', pct(bc.get('calibrated_all')), f"nominal 90% · issued {pct(bc.get('calibrated_issued'))} · fallback {pct(bc.get('calibrated_fallback'))} · widening x{bc.get('widening_factor_median', 0):.2f}", 'live' if (bc.get('calibrated_all') or 0) >= 0.85 else 'decision', 'lock.validation')
    with k[4]:
        cards.kpi_card('P(BEATS CLEANED CURVE)', f"{v.get('p_clearstint_beats_clean_issued', 0):.2f}", f"issued cases · P(beats naive) {v.get('p_clearstint_beats_naive_all', 0):.2f}", 'neutral', 'lock.validation')
    # ---- live-prefix evaluation -----------------------------------------------------------------------------
    cards.section('Live-prefix evaluation: reveal through lap k, predict k+1 / k+3 / k+5, step forward', 'Estimator vs a prior-only baseline that keeps the pre-race slope and re-estimates only the stint level. Feedback disabled (no recorded feedback for these races).')
    pe, pe_asset = LB.prefix_eval()
    if pe:
        st.html(cards.table_html(['race', 'drivers', 'laps', 'next-lap MAE (est / prior)', '3-lap cum MAE', '5-lap cum MAE', 'cov90 next (est / prior)', 'cov90 +3', 'cliff-5 Brier vs climatology (events/n)', 'accel.-wear detect · lead', 'false alerts / stint', 'reco change rate'],
                                 prefix_rows(pe), numeric_cols=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)))
        reading = LB.prefix_reading()
        st.html(cards.card_html('honest reading (out/live/PREFIX_EVAL.md)', f'<div class="cs-list">{esc(reading) if reading else "reading paragraph not found in PREFIX_EVAL.md"}</div><div class="cs-muted" style="margin-top:6px">cliff probabilities are a {esc(LB.CLIFF_LABEL)}; Brier scores are worse than climatology everywhere and are shown as such.</div>'))
        st.html(f'<div class="cs-muted">asset out/live/prefix_eval.json sha256 {pe_asset.short_hash} · {pe_asset.sidecar_status} · estimator {esc(pe.get("estimator", "—"))} · {esc(pe.get("model_version", ""))} · generated {esc(pe.get("generated_at", ""))}</div>')
    else:
        empty_states.pending('live-prefix evaluation', 'Workstream 8 (out/live/prefix_eval.json)')
    left, right = st.columns([3, 2], gap='large')
    with left:
        cards.section('Calibration ladder (pre-race, lock)')
        rows = [['Naive pooled fit', f"{a.get('naive', 0):.3f}", f"{cal['naive']['slope']:+.2f}", f"{cal['naive']['r']:+.2f}", cal['naive']['n']],
                ['Cleaned Friday curve (issued only)', f"{m.get('clean', 0):.3f}", f"{cal['clean']['slope']:+.2f}", f"{cal['clean']['r']:+.2f}", cal['clean']['n']],
                ['Orb v1 (issued only)', f"{m.get('clearstint', 0):.3f}", f"{cal['clearstint']['slope']:+.2f}", f"{cal['clearstint']['r']:+.2f}", cal['clearstint']['n']],
                ['Orb v1, all cases incl. low-deg fallback', f"{a.get('clearstint', 0):.3f}", f"{cal['all_with_fallback']['slope']:+.2f}", f"{cal['all_with_fallback']['r']:+.2f}", cal['all_with_fallback']['n']]]
        st.html(cards.table_html(['Predictor', 'MAE s/lap', 'Calibration slope', 'Pearson r', 'n'], rows, numeric_cols=(1, 2, 3, 4)))
        st.plotly_chart(charts.calibration_scatter(lock.validation_rows), width='stretch', config={'displayModeBar': False})
        cards.section('Per compound (lock.validation.by_compound)')
        bcp = v.get('by_compound', {})
        st.html(cards.table_html(['Compound', 'cases', 'MAE naive', 'MAE Orb v1', 'transfer factor (median)'], [[badges.compound_html(c), d['n'], f"{d['mae_naive']:.3f}", f"{d['mae_clearstint']:.3f}", f"x{d['k_median']:.2f}"] for c, d in bcp.items()], numeric_cols=(1, 2, 3, 4)).replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"'))
        cards.section('Counterfactual identity and leakage tests (out/counterfactual)', 'Changing nothing must produce zero delta; the engine must not read future laps for pre-race quantities.')
        ids = CF.identity_status()
        if ids:
            st.html(cards.table_html(['scenario', 'mode', 'identity test', 'identity delta (s)', 'future-leakage test', 'target driver excluded', 'sealed holdout', 'generated'],
                                     [[i['scenario_id'], i['mode'], i['identity_test'], f"{i['identity_check_delta_s']:+.4f}" if i['identity_check_delta_s'] is not None else '—', i['future_leakage_test'], 'yes' if i['target_driver_excluded'] else 'no', 'yes' if i['sealed_holdout'] else 'no (development pool)', f"{i['generated_at'][:16]} {i.get('git_sha') or ''}"] for i in ids], numeric_cols=(3,)))
        else:
            empty_states.pending('counterfactual identity tests', 'Workstream 2 scenario runs')
    with right:
        cards.section('Withheld cases and what the race did')
        st.html(cards.table_html(['Event', 'Compound', 'Gate', 'cleaned', 'observed', 'floor'], [[w['event'], w['compound'][0] + ' · ' + w['compound'].title(), GATE_SHORT.get(w['gate'], w['gate']), f"{w['clean']:+.4f}", f"{w['obs']:+.4f}", f"{w['floor']:.4f}"] for w in v.get('withheld_cases', [])], numeric_cols=(3, 4, 5)))
        st.markdown('<div class="cs-muted">gates: no +deg signal = no positive degradation signal in cleaned practice; too few clean laps = below the 30-lap minimum (lock rules)</div>', unsafe_allow_html=True)
        cards.section('Sensitivity of the headline error to stated assumptions')
        sj, asset = A.load_json_asset(P.SENSITIVITY)
        if sj:
            st.html(cards.table_html(['Setting', 'cases', 'issued', 'MAE Orb v1', 'MAE naive', 'r'], [[k2, r['n'], r['issued'], f"{r['mae']:.4f}", f"{r['mae_naive']:.3f}", f"{r['r']:+.2f}"] for k2, r in sj['runs'].items()], numeric_cols=(1, 2, 3, 4, 5)))
            st.html(f'<div class="cs-muted">asset out/sensitivity.json sha256 {asset.short_hash} · {asset.sidecar_status}</div>')
        else:
            empty_states.pending('sensitivity table', 'out/sensitivity.json')
        cards.section('Still pending', 'Strategy regret over the sealed sample, risk-coverage curve, public-only vs sensor-assisted ablation, profile repeatability (Phase 2).')
        st.html('<div class="cs-chips">' + badges.badge_html('risk-coverage curve · pending', 'placeholder') + badges.badge_html('strategy regret (sealed) · pending Workstream 3', 'placeholder') + badges.badge_html('public-only vs sensor-assisted ablation · pending', 'placeholder') + '</div>')
        pdg = v.get('push_diagnostic', {})
        if pdg:
            cards.section('Push profile diagnostic (lock)')
            st.html(cards.kv_html([('energy trend, withheld', f"median {pdg['energy_trend_withheld']['50%']:+.3f} (range {pdg['energy_trend_withheld']['min']:+.3f} to {pdg['energy_trend_withheld']['max']:+.3f})"),
                                   ('energy trend, issued', f"median {pdg['energy_trend_issued']['50%']:+.3f} (range {pdg['energy_trend_issued']['min']:+.3f} to {pdg['energy_trend_issued']['max']:+.3f})")]))
    shell.ready_marker('validation')
