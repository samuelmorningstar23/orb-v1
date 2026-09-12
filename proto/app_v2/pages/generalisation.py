"""Route 6c, Generalisation scorecard (Workstream 3's blind evaluation, out/validation/).

Ghost Strategy scorecard by cell over the development pool (leave-one-weekend-out inside each season, sealed weekends
excluded from every pool), the rolling-origin 2026 series, the abstention risk-coverage sweep, the Live Predictor
scorecard (separate card, never merged) and the sealed-holdout block. The sealed block stays "sealed: 6 weekends,
aggregate revealed after freeze" until a holdout_aggregate.json exists with a non-null `freeze` and a reveal record;
then only its aggregate.forecast block is shown, labelled "sealed holdout, aggregate only". Per-race sealed results are
never shown. Every number here is read verbatim from a hashed file; the page computes nothing.
"""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import validation_repository as VR
from app_v2.services import view_models as VM
from app_v2.ui import shell, cards, badges, banners, empty_states
from app_v2.ui.formatting import esc, pct

CLIFF_LABEL = 'model-implied rate proxy (no cliff mechanism in the linear model)'   # Workstream 8's label, carried through (services/live_bridge.CLIFF_LABEL)
SEALED_DP = 4   # the sealed-holdout MAE is the lead's quotable headline (0.0372 vs 0.1713 s/lap): shown at the precision it is quoted at


def _f(v, d: int = 3, unit: str = '') -> str:
    return '—' if v is None else f'{v:.{d}f}{unit}'


def _ci(ci, d: int = 3) -> str:
    return '' if not ci else f' [{ci[0]:.{d}f}, {ci[1]:.{d}f}]'


def cell_html(c: dict) -> str:
    pending = c['mae'] is None and c['hidden_next1'] is None
    if pending:
        val, sub = 'pending', c['status']
    elif c['mae'] is None:
        val = f"hidden-stop next-lap MAE {_f(c['hidden_next1'], 1)} s · naive {_f(c['hidden_next1_naive'], 1)}"
        sub = f"{c['hidden_n']} stops · 90% coverage {pct(c['hidden_cov'])} · {c['note'] or 'no pre-race cell: the curve has no driver term'}"
    else:
        val = f"MAE {_f(c['mae'])} s/lap · naive {_f(c['mae_naive'])}"
        sub = (f"coverage {pct(c['coverage'])} · {c['n_weekends']} weekends, {c['n_compound_weekends']} compound-weekends ({c['n_issued']} issued) · "
               f"hidden-stop next-lap {_f(c['hidden_next1'], 1)} vs naive {_f(c['hidden_next1_naive'], 1)} s ({c['hidden_n']} stops)")
        if c['regret_median'] is not None:
            sub += f" · regret Orb v1 median +{c['regret_median']:.1f} s ({c['regret_n']})"
    return (f'<div class="cs-cell {"pending" if pending else ""}"><div class="name">{esc(c["cell"])}</div><div class="val">{esc(val)}</div>'
            f'<div class="cs-muted">{esc(sub)}</div><div class="cs-src">{esc(c["source"])}</div></div>')


def sealed_html(sb: dict) -> str:
    ids = ', '.join(x.replace('_', ' ') for x in VR.sealed_ids())
    if not sb['revealed']:
        body = (f'<div class="cs-kpi-value" style="font-size:1.15rem;margin:4px 0">{esc(sb["status_text"])}</div>'
                f'<div class="cs-muted">{esc(sb["reason"] or "no post-freeze aggregate on disk yet")}</div>'
                f'<div class="cs-muted" style="margin-top:6px">weekends: {esc(ids) or "listed in evaluation/README.md"} · per-race results: never shown · per-race reveal refused until evaluation/holdout/freeze.json exists (Workstream 3 evaluator)</div>')
        return cards.card_html('Sealed holdout', body, extra_class='raised')
    fc = sb['forecast']; mae = fc.get('mae') or {}; cov = fc.get('band_coverage90') or {}; cal = fc.get('calibration') or {}; bs = fc.get('bootstrap') or {}
    pairs = [('label', sb['label']), ('weekends', f"{(sb['weekends'] or {}).get('sealed', sb['n_weekends'])} sealed · {(sb['weekends'] or {}).get('forecast', '—')} forecastable · {(sb['weekends'] or {}).get('weekend_level_abstention', '—')} weekend-level abstention"),
             ('compound-weekends', f"{fc.get('n_compound_weekends')} ({fc.get('n_issued')} issued, {fc.get('n_withheld')} withheld)"),
             ('MAE Orb v1 vs naive', f"{_f(mae.get('orb_v1'), SEALED_DP)}{_ci((bs.get('mae_orb_v1') or {}).get('ci90'), SEALED_DP)} vs {_f(mae.get('naive'), SEALED_DP)}{_ci((bs.get('mae_naive') or {}).get('ci90'), SEALED_DP)} s/lap"),
             ('90% band coverage', f"{pct(cov.get('all'))} (issued {pct(cov.get('issued'))}, fallback {pct(cov.get('fallback'))}; nominal {pct(cov.get('nominal'))})"),
             ('calibration', f"slope {_f(cal.get('slope'), 2)} · r {_f(cal.get('r'), 2)} · n {cal.get('n', '—')}"),
             ('by compound', ' · '.join(f"{k.lower()} {v.get('n')}: {_f(v.get('mae_orb_v1'), SEALED_DP)} vs naive {_f(v.get('mae_naive'), SEALED_DP)}" for k, v in (fc.get('by_compound') or {}).items()) or '—'),
             ('wins over naive', f"{fc.get('wins_orb_over_naive', '—')} of {fc.get('n_compound_weekends', '—')}"),
             ('freeze / tuning', f"freeze recorded · post_holdout_tuning {sb.get('post_holdout_tuning')} · generated {sb.get('generated_at')} · git {(sb.get('git_sha') or '')[:7]}")]
    return cards.card_html(f'Sealed holdout · {sb["label"]}', cards.kv_html(pairs, stack=True) + f'<div class="cs-muted" style="margin-top:6px">aggregate only; per-race sealed results are never shown</div>', extra_class='raised')


def live_scorecard_html(lh: dict | None, asset) -> str:
    if lh is None:
        return cards.card_html('Live Predictor scorecard', '<div class="cs-muted">pending: out/validation/live_scorecard.json not present</div>')
    src = lh['source']
    pairs = [('next-lap MAE (estimator / prior-only)', f"{_f(lh['next1'])}{_ci(lh['next1_ci'])} / {_f(lh['next1_prior'])}{_ci(lh['next1_prior_ci'])} s"),
             ('3-lap / 5-lap cumulative MAE', f"{_f(lh['cum3'], 2)} / {_f(lh['cum5'], 2)} s (prior-only {_f(lh['cum3_prior'], 2)} / {_f(lh['cum5_prior'], 2)})"),
             ('90% coverage next lap / +3', f"{pct(lh['cov1'])} (prior-only {pct(lh['cov1_prior'])}) / {pct(lh['cov3'])}"),
             ('cliff-5 Brier vs climatology', f"{_f(lh['cliff5_brier'])}{_ci(lh['cliff5_brier_ci'])} vs {_f(lh['cliff5_clim'])}{_ci(lh['cliff5_clim_ci'])} · {CLIFF_LABEL}; worse than climatology, shown as such"),
             ('accelerating-wear detection / lead', f"{pct(lh['aw_rate'])}{_ci(lh['aw_rate_ci'], 2)} / {_f(lh['aw_lead'], 1)} laps"), ('false alert episodes per stint', _f(lh['false_alerts'], 2)), ('recommendation change rate', pct(lh['reco_change'])),
             ('races · laps · drivers', f"{', '.join(lh['races'])} · {lh['laps']} laps · {lh['drivers']} driver-races"),
             ('estimator', f"{src.get('estimator', '—')} · {src.get('model_version', '')} · feedback {src.get('feedback', '—')}"),
             ('driver-feedback ablation', f"{lh['ablation'].get('status', '—')}: {lh['ablation'].get('reason', '')}")]
    return cards.card_html('Live Predictor scorecard (from Workstream 8\'s prefix evaluation) · separate scorecard, never merged with Ghost Strategy', cards.kv_html(pairs, stack=True) + f'<div class="cs-muted" style="margin-top:6px">{esc(lh["note"])} · sha256 {asset.short_hash} · {asset.sidecar_status}</div>')


def render() -> None:
    ctx = common.context('generalisation')
    if not common.require_lock(ctx, 'generalisation'):
        return
    lock = ctx.lock
    st.session_state['mode'] = 'audit'
    ctx.mode = 'audit'
    g, g_asset = VR.ghost_scorecard(); l, l_asset = VR.live_scorecard(); rc, rc_asset = VR.risk_coverage(); sb = VR.sealed_block()
    hl = VR.dev_pool_headline(g); cells = VR.dev_pool_cells(g); ro = VR.rolling_origin(g); lh = VR.live_headline(l)
    common.header(ctx, 'generalisation', support='development pool / sealed', latency='n/a', session='Scorecard')
    st.markdown('## Generalisation scorecard')
    banners.audit_banner()
    if hl is None:
        banners.note_banner('Cells aggregate held-out results by cell. Workstream 3\'s ghost_scorecard.json is not on disk: every cell is shown as pending, never estimated here.')
    else:
        banners.note_banner(f"Cells aggregate held-out results by cell over the development pool: {hl['n_weekends']} weekends, {hl['n_compound_weekends']} compound-weekends, seasons {', '.join(map(str, hl['seasons']))}; {hl['split']}. "
                            f"Race estimates are a {VR.REFERENCE_WORDING}; regret is a {hl['regret_label']}; the sealed holdout is aggregate only. Data cutoff: {hl['data_cutoff']}.")
    # ---- headline KPIs (Ghost Strategy scorecard) -------------------------------------------------------------------------
    if hl is not None:
        k = st.columns(5)
        with k[0]:
            cards.kpi_card('PRE-RACE MAE ORB V1', _f(hl['mae']), f"90% CI{_ci(hl['mae_ci'])} · {hl['n_weekends']} weekends, {hl['n_compound_weekends']} compound-weekends ({hl['n_issued']} issued)", 'live', 'ghost_scorecard · development pool · forecast', 's/lap')
        with k[1]:
            cards.kpi_card('MAE NAIVE', _f(hl['mae_naive']), f"90% CI{_ci(hl['mae_naive_ci'])} · P(Orb v1 beats naive) {_f(hl['p_beats_naive'], 2)} (weekend bootstrap)", 'neutral', 'ghost_scorecard · development pool · forecast', 's/lap')
        with k[2]:
            cov = hl['coverage']
            cards.kpi_card('BAND COVERAGE', pct(cov), f"nominal 90% · CI {pct((hl['coverage_ci'] or [None, None])[0])} to {pct((hl['coverage_ci'] or [None, None])[1])} · share issued {pct(hl['abstention'].get('share_issued'))}", 'live' if (cov or 0) >= 0.85 else 'decision', 'ghost_scorecard · development pool · forecast')
        with k[3]:
            cards.kpi_card('HIDDEN-STOP NEXT-LAP MAE', _f(hl['hidden_next1'], 1), f"naive {_f(hl['hidden_next1_naive'], 1)} s · {hl['hidden_n']} stops, {hl['hidden_weekends']} weekends · 90% coverage {pct(hl['hidden_cov1'])} · 3 / 5-lap {_f(hl['hidden_cum3'], 1)} / {_f(hl['hidden_cum5'], 1)} vs naive {_f(hl['hidden_cum3_naive'], 1)} / {_f(hl['hidden_cum5_naive'], 1)}", 'live', 'ghost_scorecard · development pool · hidden stop', 's')
        with k[4]:
            cards.kpi_card('STRATEGY REGRET, ORB V1', f"+{hl['regret_median']:.1f}" if hl['regret_median'] is not None else '—', f"median over {hl['regret_n']} scorable weekends · mean +{_f(hl['regret_mean'], 1)}{_ci(hl['regret_mean_ci'], 1)} · naive median +{_f(hl['regret_naive_median'], 1)} ({hl['regret_naive_n']}) · {hl['regret_label']}", 'decision', 'ghost_scorecard · development pool · regret', 's')
    # ---- cells --------------------------------------------------------------------------------------------------------
    cards.section('Cells (development pool, leave-one-weekend-out)', 'Pre-race degradation MAE against the race-derived pace-loss reference, band coverage, hidden-stop next-lap MAE and Orb v1 regret per cell, exactly as Workstream 3 tabulated them.')
    if not cells:
        cells = VM.generalisation_cells(lock)
        for c in cells:
            c.setdefault('hidden_next1', None); c.setdefault('hidden_next1_naive', None); c.setdefault('hidden_n', None); c.setdefault('hidden_cov', None); c.setdefault('regret_median', None); c.setdefault('regret_n', None); c.setdefault('note', ''); c.setdefault('n_weekends', c.get('n')); c.setdefault('n_compound_weekends', c.get('n')); c.setdefault('n_issued', '—')
    cols = st.columns(3)
    for i, c in enumerate(cells):
        with cols[i % 3]:
            st.html(cell_html(c))
    left, right = st.columns([3, 2], gap='large')
    with left:
        cards.section('Rolling origin, 2026', ro['method'] if ro else 'pending')
        if ro:
            rows = []
            for r in ro['series']:
                if r.get('note'):
                    rows.append([r['round'], r['event'], r['n_pool'], '—', '—', '—', r['note'], '', ''])
                else:
                    rows.append([r['round'], r['event'], r['n_pool'], r['n_compounds'], r['n_issued'], r['n_no_forecast'], _f(r['mae_orb_v1'], 4), _f(r['mae_naive'], 4), pct(r['band_coverage90'])])
            st.html(cards.table_html(['round', 'event', 'pool', 'compounds', 'issued', 'no forecast', 'MAE Orb v1', 'MAE naive', 'cov90'], rows, numeric_cols=(0, 2, 3, 4, 5, 6, 7, 8)))
            p, p4 = ro['pooled'], ro['pooled_from_round_4']
            st.html(f'<div class="cs-muted">pooled over {p.get("n_weekends")} rounds: MAE Orb v1 {_f((p.get("mae") or {}).get("orb_v1"), 4)} vs naive {_f((p.get("mae") or {}).get("naive"), 4)} s/lap, coverage {pct((p.get("band_coverage90") or {}).get("all"))} · from a pool of at least 3 rounds ({p4.get("n_weekends")} rounds): {_f((p4.get("mae") or {}).get("orb_v1"), 4)} vs {_f((p4.get("mae") or {}).get("naive"), 4)}</div>')
        else:
            empty_states.pending('rolling-origin series', 'Workstream 3 (ghost_scorecard.json)')
        seasons = VR.by_season_rows(g)
        if seasons:
            cards.section('By season (development pool, leave-one-weekend-out inside the season)', seasons[0]['split'])
            st.html(cards.table_html(['season', 'weekends', 'compound-weekends', 'issued / withheld', 'MAE Orb v1 [90% CI]', 'MAE naive', 'cov90', 'wins over naive', 'calibration r'],
                                     [[r['season'], r['n_weekends'], r['n_compound_weekends'], f"{r['n_issued']} / {r['n_withheld']}", f"{_f(r['mae'])}{_ci(r['mae_ci'])}", _f(r['mae_naive']), pct(r['coverage']), f"{r['wins']} of {r['n_compound_weekends']}", _f(r['calibration_r'], 2)] for r in seasons], numeric_cols=(1, 2, 3, 4, 5, 6, 7, 8)))
        cards.section('Abstention: risk-coverage sweep (risk_coverage.json)', 'Both gate thresholds swept over the development pool; coverage = share of compound-weekends issued, the rest fall to the low-degradation fallback. Point forecasts only.')
        png = VR.risk_coverage_png()
        if png.exists:
            st.image(png.path, caption=f'out/validation/risk_coverage.png sha256 {png.short_hash} · {png.sidecar_status} (dark theme of proto/theme.py)', width='stretch')
        gates = VR.risk_gate_rows(rc)
        if gates:
            st.html(cards.table_html(['gate', 'min laps', 'min slope', 'coverage (issued)', 'MAE issued', 'MAE fallback', 'MAE all', 'MAE naive'],
                                     [[r['name'], f"{r['min_laps']:.0f}", f"{r['min_slope']:.3f}", pct(r['coverage']), _f(r['mae_issued'], 4), _f(r['mae_fallback'], 4), _f(r['mae_all'], 4), _f(r['mae_naive'], 4)] for r in gates], numeric_cols=(1, 2, 3, 4, 5, 6, 7)))
            st.html(f'<div class="cs-muted">{rc.get("units", "")} · {rc.get("n_cases")} compound-weekends, {rc.get("n_weekends")} weekends · the production gate is the lock rule (pipeline.py); the sweep is reported, not used to retune</div>')
        elif not png.exists:
            empty_states.pending('risk-coverage curve', 'Workstream 3 (risk_coverage.json)')
    with right:
        st.html(sealed_html(sb))
        st.html(live_scorecard_html(lh, l_asset))
        cards.section('v1 evidence in the lock (lock.validation, 2026 leave-one-weekend-out)')
        v = lock.validation
        st.html(cards.kv_html([('weekends', v.get('n_weekends')), ('compound-weekends', v.get('n_compound_weekends')), ('issued / withheld', f"{v.get('n_issued')} / {v.get('n_withheld')}"),
                               ('MAE Orb v1, all cases', f"{v['mae_all_with_fallback']['clearstint']:.3f} s/lap (90% CI {v['ci90_mae_clearstint_all'][0]:.3f} to {v['ci90_mae_clearstint_all'][1]:.3f})"),
                               ('MAE naive', f"{v['mae_all_with_fallback']['naive']:.3f} s/lap"), ('calibrated band coverage', pct(v['band_coverage']['calibrated_all']) + ' (nominal 90%)'),
                               ('wins over naive', f"{v['wins_clearstint_over_naive']} of {v['n_compound_weekends']}")]))
        lc = VR.lock_consistency(g)
        if lc:
            m = lc['metrics'].get('mae_orb_v1_all') or {}
            st.html(cards.card_html('scorecard vs lock, 2026 (Workstream 3 lock_consistency_2026)', cards.kv_html([('all metrics match', f"{'yes' if lc['all_match'] else 'NO'} · {lc['n_compared']} compared · tolerance {lc['tolerance']}"),
                                                                                                             ('MAE Orb v1, all cases', f"scorecard {_f(m.get('scorecard'), 4)} · lock {_f(m.get('lock'), 4)}"), ('lock generated', lc['lock_generated_at'] or '—')]) + f'<div class="cs-muted" style="margin-top:6px">{esc(lc["note"])}</div>', extra_class='raised' if not lc['all_match'] else ''))
        st.html('<div class="cs-chips">' + badges.badge_html('never "works under any weather"', 'neutral') + badges.badge_html('abstains outside the evidence', 'live') + badges.badge_html('sealed holdout: aggregate only, after freeze', 'decision') + badges.badge_html('two scorecards, never merged', 'neutral') + '</div>')
    st.html('<div class="cs-muted">' + ' · '.join(esc(x) for x in [VR.provenance(g, g_asset, 'ghost_scorecard.json'), VR.provenance(l, l_asset, 'live_scorecard.json'), VR.provenance(rc, rc_asset, 'risk_coverage.json'),
                                                                   f'out/validation/holdout_aggregate.json: {"revealed" if sb["revealed"] else "present, withheld (pre-freeze)" if sb["asset"].exists else "missing"}', f'SCORECARDS.md sha256 {VR.scorecards_md().short_hash}']) + '</div>')
    shell.ready_marker('generalisation')
