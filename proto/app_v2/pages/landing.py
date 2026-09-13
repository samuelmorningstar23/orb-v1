"""Landing: two doors (13.3). The user is never sent automatically from one mode to the other."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import counterfactual_repository as CF
from app_v2.services import validation_repository as VR
from app_v2.services import view_models as VM
from app_v2.ui import shell, empty_states, cards
from app_v2.ui.formatting import esc, pct

CLIFF_LABEL = 'model-implied rate proxy (no cliff mechanism in the linear model)'   # Workstream 8's label (services/live_bridge.CLIFF_LABEL)
SEALED_DP = 4   # the sealed-holdout MAE is the lead's quotable headline (0.0372 vs 0.1713 s/lap): shown at the precision it is quoted at


def _f(v, d: int = 3) -> str:
    return '—' if v is None else f'{v:.{d}f}'


def _ci(ci, d: int = 3) -> str:
    return '' if not ci else f' [{ci[0]:.{d}f}, {ci[1]:.{d}f}]'


def live_scorecard_html() -> str:
    """Live Predictor scorecard headline (from Workstream 8's prefix evaluation). Never merged with the Ghost scorecard."""
    l, asset = VR.live_scorecard(); lh = VR.live_headline(l)
    if lh is None:
        return cards.card_html('Live Predictor scorecard', '<div class="cs-muted">pending: out/validation/live_scorecard.json</div>')
    pairs = [('next-lap MAE, estimator vs prior-only', f"{_f(lh['next1'])}{_ci(lh['next1_ci'])} vs {_f(lh['next1_prior'])} s"), ('3-lap cumulative MAE', f"{_f(lh['cum3'], 2)} vs prior-only {_f(lh['cum3_prior'], 2)} s"),
             ('90% coverage, next lap', f"{pct(lh['cov1'])} (prior-only {pct(lh['cov1_prior'])})"), ('cliff-5 Brier vs climatology', f"{_f(lh['cliff5_brier'])} vs {_f(lh['cliff5_clim'])} · {CLIFF_LABEL}"),
             ('accelerating-wear detection / lead', f"{pct(lh['aw_rate'])} / {_f(lh['aw_lead'], 1)} laps · false alerts {_f(lh['false_alerts'], 2)} per stint"),
             ('prefix evaluation', f"{', '.join(lh['races'])} · {lh['laps']} laps · reveal through lap k, predict k+1 / k+3 / k+5")]
    return cards.card_html('Live Predictor scorecard', cards.kv_html(pairs) + f'<div class="cs-src" style="margin-top:6px">out/validation/live_scorecard.json sha256 {asset.short_hash} · {asset.sidecar_status} · generated {esc(l.get("generated_at", ""))}</div>')


def ghost_scorecard_html() -> str:
    """Ghost Strategy scorecard headline (development pool) plus the sealed-holdout status line."""
    g, asset = VR.ghost_scorecard(); hl = VR.dev_pool_headline(g); sb = VR.sealed_block()
    if hl is None:
        return cards.card_html('Ghost Strategy scorecard', f'<div class="cs-muted">pending: out/validation/ghost_scorecard.json · sealed holdout: {esc(sb["status_text"])}</div>')
    if sb['revealed']:
        fc = sb['forecast']; mae = fc.get('mae') or {}
        sealed = (f"{sb['label']}: MAE Orb v1 {_f(mae.get('orb_v1'), SEALED_DP)} vs naive {_f(mae.get('naive'), SEALED_DP)} s/lap, coverage {pct((fc.get('band_coverage90') or {}).get('all'))} over "
                  f"{fc.get('n_weekends')} forecastable of {sb['n_weekends']} sealed weekends, {fc.get('n_compound_weekends')} compound-weekends")
    else:
        sealed = sb['status_text']
    pairs = [('pre-race MAE, Orb v1 vs naive', f"{_f(hl['mae'])}{_ci(hl['mae_ci'])} vs {_f(hl['mae_naive'])} s/lap · {hl['n_weekends']} weekends, {hl['n_compound_weekends']} compound-weekends"),
             ('90% band coverage', f"{pct(hl['coverage'])} (nominal 90%) · issued {pct(hl['abstention'].get('share_issued'))}, the rest abstain to the fallback"),
             ('hidden-stop next-lap MAE, Orb v1 vs naive', f"{_f(hl['hidden_next1'], 1)} vs {_f(hl['hidden_next1_naive'], 1)} s · {hl['hidden_n']} stops"),
             ('strategy regret, Orb v1', f"median +{_f(hl['regret_median'], 1)} s over {hl['regret_n']} weekends · {hl['regret_label']}"),
             ('sealed holdout', sealed)]
    return cards.card_html('Ghost Strategy scorecard', cards.kv_html(pairs) + f'<div class="cs-src" style="margin-top:6px">out/validation/ghost_scorecard.json sha256 {asset.short_hash} · {asset.sidecar_status} · generated {esc(g.get("generated_at", ""))} · development pool, leave-one-weekend-out, sealed weekends excluded</div>')


def _status_html(items) -> str:
    return '<div class="cs-status">' + ''.join(f'<span class="item {"ok" if i.ok else "no"}" title="{esc(i.detail)}">{"●" if i.ok else "○"} {esc(i.label)}</span>' for i in items) + '</div>'


def replay_target(selected: str, available: list[str]) -> str | None:
    """A replay CTA must resolve to a race that actually exists."""
    return selected if selected in available else ('Monza' if 'Monza' in available else next(iter(available), None))



def ghost_target(event: str):
    """A prepared audit scenario for this weekend if one exists, else the first prepared elsewhere; None when none exist."""
    here = CF.scenarios_for(event)
    if here:
        return here[0]
    for sc in CF.scenarios_for(None) or []:
        return sc
    return None


def render() -> None:
    ctx = common.context('landing')
    if not common.require_lock(ctx, 'landing'):
        return
    common.header(ctx, 'landing', session='Overview')
    vm = VM.build_landing(ctx.lock)
    st.html('<section class="orb-hero"><div class="orb-eyebrow">THE STRATEGY WORKSPACE</div><h1>Every lap tells a story.<br><em>Make the next call.</em></h1><p>See the tyre trend. Understand the pit decision. Explore a different race with Ghost Strategy.</p></section>')
    if st.button('New here? Take the guided demo →', type='primary'):
        common.goto('demo')
    target = replay_target(ctx.event, vm.race_files)
    left, right = st.columns(2, gap='large')
    with left:
        st.html(cards.card_html('Live Predictor', '<h2>Watch the prediction evolve</h2><p>Replay a recorded race, advance a lap, and see the updated degradation estimate and pit recommendation.</p>', extra_class='start-card'))
        if st.button(f'Start {target} replay' if target else 'No recorded races available', type='primary', disabled=target is None, width='stretch'):
            common.goto('live', ev=target, drv=None, lap=1, mode='live')
        st.caption('Historical replay · an external live feed is not connected.')
    with right:
        gs = ghost_target(ctx.event)                 # this weekend when it has prepared simulations, else one that does
        body = (f'<h2>Compare a different stop</h2><p>Start with a prepared {gs.event} strategy and compare its modelled tyre-time result with the recorded race.</p>'
                if gs else '<h2>Compare a different stop</h2><p>No prepared simulation exists yet. A simulation is only written when replaying the actual plan reproduces the race exactly.</p>')
        st.html(cards.card_html('Ghost Strategy', body, extra_class='start-card'))
        if st.button(f'Compare {gs.event} strategies' if gs else 'No prepared strategies available', width='stretch', disabled=gs is None) and gs:
            common.goto('ghost', ev=gs.event, drv=gs.driver, mode='audit', ilap=gs.lap, rep=gs.to_compound, lap=None)
        st.caption('Modelled comparison · traffic and rivals are not simulated.')
    st.markdown('### Madrid · frozen forecast')
    st.caption('Issued before the race. Race results have not been used.')
    cols = st.columns(3)
    for col, comp in zip(cols, ctx.lock.compounds_for('Madrid')):
        f = ctx.lock.forecast_for('Madrid', comp)
        with col:
            cards.kpi_card(comp.title(), f'{f.prediction:+.3f}', f'90% band {f.band90[0]:+.3f} to {f.band90[1]:+.3f} · ' + ('issued' if f.issued else 'withheld; fallback applies'), 'live' if f.issued else 'decision', unit='s/lap')
    with cols[-1]:
        if st.button('View Madrid forecast', width='stretch'):
            common.goto('prerace', ev='Madrid', drv=None, lap=None)
    with st.expander('How well does the model perform?'):
        st.html(live_scorecard_html())
        st.html(ghost_scorecard_html())
        if st.button('Open validation'):
            common.goto('validation')
    shell.ready_marker('landing')
