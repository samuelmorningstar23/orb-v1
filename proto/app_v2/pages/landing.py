"""Landing: two doors (13.3). The user is never sent automatically from one mode to the other."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
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


def render() -> None:
    ctx = common.context('landing')
    common.header(ctx, 'landing', session='Landing', support='—' if ctx.lock is None else 'lock loaded', latency='n/a')
    if ctx.lock is None:
        empty_states.missing_lock(); shell.ready_marker('landing'); return
    vm = VM.build_landing(ctx.lock)
    st.markdown('## Predict. Monitor. Decide. Prove.')
    st.markdown(f'<div class="cs-muted">Pre-race prior locked and hashed ({vm.forecast_hash6}) · live posterior every lap · ranked pit and compound actions · Race Twin proof. Two tools, two data boundaries, one frozen forecast.</div>', unsafe_allow_html=True)
    left, right = st.columns(2, gap='large')
    with left:
        st.html(f'<div class="cs-mode live"><h2>LIVE PREDICTOR</h2><div class="lead">Compare actual tyre behaviour against the locked pre-race forecast and receive updated pit and compound recommendations. Sees only what existed at the current timestamp; makes the call.</div>{_status_html(vm.live_status)}</div>')
        c1, c2, c3 = st.columns(3)
        if c1.button('Start historical replay', type='primary', width='stretch', key='btn_replay'):
            common.goto('live', mode='live')
        c2.button('Load recorded-live session', width='stretch', disabled=True, help='Workstream 2 delivered the RecordedLive source (proto/events/, task 0.9); the dashboard consumes the replay source only in Phase 0.', key='btn_recorded')
        c3.button('Connect live feed', width='stretch', disabled=True, help='Live adapter is Phase 1.', key='btn_live')
        st.markdown(f'<div class="cs-muted">Recorded races available for replay: {esc(", ".join(vm.race_files))}. Live forecast weekend: {esc(", ".join(vm.live_events) or "none")} (no race file yet: the forecast is shown, replay waits for a source).</div>', unsafe_allow_html=True)
        st.html(live_scorecard_html())
    with right:
        st.html(f'<div class="cs-mode ghost"><h2>GHOST STRATEGY</h2><div class="lead">Audit a completed race, test alternative tyre strategies and inspect generalisation across supported drivers, circuits and weather. Sees the finished race; audits whether the model deserved to make the call.</div>{_status_html(vm.ghost_status)}</div>')
        c1, c2, c3 = st.columns(3)
        if c1.button('Historical audit', type='primary', width='stretch', key='btn_audit'):
            common.goto('ghost', mode='audit')
        if c2.button('Scenario explorer', width='stretch', key='btn_scenario'):
            common.goto('ghost', mode='scenario')
        if c3.button('Generalisation scorecard', width='stretch', key='btn_gen'):
            common.goto('generalisation', mode='audit')
        st.markdown(f'<div class="cs-muted">Scored weekends in the lock: {esc(", ".join(vm.scored_events))}.</div>', unsafe_allow_html=True)
        st.html(ghost_scorecard_html())
    st.markdown('<div class="cs-muted" style="margin-top:16px">Defensible sentence: Orb v1 can be tested across any available driver, circuit and supported weather regime, and it abstains when the selected conditions fall outside the evidence.</div>', unsafe_allow_html=True)
    shell.ready_marker('landing')
