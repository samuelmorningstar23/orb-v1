"""Route 6c, Generalisation scorecard: aggregate results by cell over the sealed sample (pending Workstream 3 for most cells)."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import asset_repository as A
from app_v2.services import paths as P
from app_v2.services import view_models as VM
from app_v2.ui import shell, cards, badges, banners
from app_v2.ui.formatting import esc, pct


def cell_html(c: dict) -> str:
    pending = c['mae'] is None
    val = 'pending sealed evaluation' if pending else f'MAE {c["mae"]:.3f} s/lap · naive {c["mae_naive"]:.3f}'
    sub = '' if pending else f'coverage {pct(c["coverage"])} · n {c["n"]} · {c["source"]}'
    return f'<div class="cs-cell {"pending" if pending else ""}"><div class="name">{esc(c["cell"])}</div><div class="val">{esc(val)}</div><div class="cs-muted">{esc(sub or c["status"])}</div></div>'


def render() -> None:
    ctx = common.context('generalisation')
    if not common.require_lock(ctx, 'generalisation'):
        return
    lock = ctx.lock
    st.session_state['mode'] = 'audit'
    ctx.mode = 'audit'
    common.header(ctx, 'generalisation', support='sealed sample', latency='n/a', session='Scorecard')
    st.markdown('## Generalisation scorecard')
    banners.audit_banner()
    banners.note_banner('Cells aggregate held-out results over the sealed sample by cell. Only the v1 leave-one-weekend-out cell exists today; every other cell waits for the sealed evaluation and is shown as pending, never estimated here.')
    cells = VM.generalisation_cells(lock)
    cols = st.columns(3)
    for i, c in enumerate(cells):
        with cols[i % 3]:
            st.html(cell_html(c))
    left, right = st.columns([3, 2], gap='large')
    with left:
        cards.section('v1 evidence behind the populated cell (lock.validation)')
        v = lock.validation
        st.html(cards.kv_html([('weekends', v.get('n_weekends')), ('compound-weekends', v.get('n_compound_weekends')), ('issued / withheld', f"{v.get('n_issued')} / {v.get('n_withheld')}"),
                               ('MAE Orb v1, all cases', f"{v['mae_all_with_fallback']['clearstint']:.3f} s/lap (90% CI {v['ci90_mae_clearstint_all'][0]:.3f} to {v['ci90_mae_clearstint_all'][1]:.3f})"),
                               ('MAE naive', f"{v['mae_all_with_fallback']['naive']:.3f} s/lap"), ('calibrated band coverage', pct(v['band_coverage']['calibrated_all']) + ' (nominal 90%)'),
                               ('wins over naive', f"{v['wins_clearstint_over_naive']} of {v['n_compound_weekends']}")]))
    with right:
        cards.section('Sealed holdout')
        manifest = A.resolve(P.PROTO_ROOT / 'evaluation' / 'holdout' / 'sealed_holdout_manifest.json')
        st.html(cards.kv_html([('manifest', 'present' if manifest.exists else 'missing'), ('sha256', manifest.short_hash if manifest.exists else '—'), ('sidecar', manifest.sidecar_status), ('per-race reveal', 'refused until freeze.json')]))
        block, src = lock.ghost_block()
        if block and block.get('generalisation_status'):
            g = block['generalisation_status']
            st.html(cards.card_html(f'{src} · generalisation_status shape', cards.kv_html([(k, str(v)) for k, v in g.items()]), extra_class='raised'))
        st.html('<div class="cs-chips">' + badges.badge_html('never "works under any weather"', 'neutral') + badges.badge_html('abstains outside the evidence', 'live') + '</div>')
    shell.ready_marker('generalisation')
