"""Validation: artefact-backed scorecards, sealed aggregate and independent scenario checks."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import counterfactual_repository as CF
from app_v2.services import validation_repository as VR
from app_v2.ui import shell, cards, banners, empty_states
from app_v2.ui.formatting import esc


def render() -> None:
    from app_v2.ui import scorecard_evidence as evidence
    from app_v2.pages.generalisation import sealed_html
    ctx = common.context('validation')
    if not common.require_lock(ctx, 'validation'):
        return
    common.header(ctx, 'validation', support='held-out', latency='n/a', session='Validation')
    st.markdown('## Validation evidence')
    banners.audit_banner()
    st.html(sealed_html(VR.sealed_block()))
    evidence.render()
    ghost, _ = VR.ghost_scorecard()
    lc = VR.lock_consistency(ghost)
    if lc:
        cards.section('Frozen lock agreement, 2026')
        st.html(cards.kv_html([('all metrics match', f"{'yes' if lc['all_match'] else 'NO'} · {lc['n_compared']} compared · tolerance {lc['tolerance']}"), ('lock generated', lc['lock_generated_at'] or '—')]))
        st.html(f'<div class="cs-muted">{esc(lc["note"])}</div>')
    cards.section('Counterfactual identity and leakage tests (out/counterfactual)', 'Changing nothing must produce zero delta; the engine must not read future laps for pre-race quantities. Both curve sources are listed and labelled; they are never mixed in one chart.')
    ids = CF.identity_status()
    if ids:
        st.html(cards.table_html(['scenario', 'mode', 'curve', 'identity test', 'identity delta (s)', 'future-leakage test', 'target driver excluded', 'sealed holdout', 'generated'],
                                 [[i['scenario_id'], i['mode'], i['curve_label'], i['identity_test'], f"{i['identity_check_delta_s']:+.4f}" if i['identity_check_delta_s'] is not None else '—', i['future_leakage_test'], 'yes' if i['target_driver_excluded'] else 'no', 'yes' if i['sealed_holdout'] else 'no (development pool)', f"{i['generated_at'][:16]} {i.get('git_sha') or ''}"] for i in ids], numeric_cols=(4,)))
    else:
        empty_states.pending('counterfactual identity tests', 'Workstream 2 scenario runs')
    shell.ready_marker('validation')
