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
             ('90% band coverage', f"{pct(cov.get('all'))} · 90% CI{_ci((bs.get('band_coverage90') or {}).get('ci90'), 4)}"),
             ('freeze / tuning', f"freeze recorded · post_holdout_tuning {sb.get('post_holdout_tuning')} · generated {sb.get('generated_at')} · git {(sb.get('git_sha') or '')[:7]}")]
    return cards.card_html(f'Sealed holdout · {sb["label"]}', cards.kv_html(pairs, stack=True) + f'<div class="cs-muted" style="margin-top:6px">90% CI by weekend bootstrap; Aggregate only; per-race sealed results are never shown</div>', extra_class='raised')


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
    from app_v2.ui import scorecard_evidence as evidence
    ctx = common.context('generalisation')
    if not common.require_lock(ctx, 'generalisation'):
        return
    st.session_state['mode'] = 'audit'
    ctx.mode = 'audit'
    common.header(ctx, 'generalisation', support='development pool / sealed', latency='n/a', session='Scorecard')
    st.markdown('## Generalisation scorecard')
    banners.audit_banner()
    st.html(sealed_html(VR.sealed_block()))
    evidence.render(cells=True)
    g, _ = VR.ghost_scorecard()
    lc = VR.lock_consistency(g)
    if lc:
        st.html(cards.card_html('scorecard vs lock, 2026 (Workstream 3 lock_consistency_2026)', cards.kv_html([('all metrics match', f"{'yes' if lc['all_match'] else 'NO'} · {lc['n_compared']} compared · tolerance {lc['tolerance']}"), ('lock generated', lc['lock_generated_at'] or '—')]) + f'<div class="cs-muted">{esc(lc["note"])}</div>'))
    shell.ready_marker('generalisation')
