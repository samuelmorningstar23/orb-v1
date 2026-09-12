"""Route 4, Driver feedback: structured entry (7.3), latest feedback, Workstream 8's reading of the log (regime shift,
telemetry corroboration), effect on posterior and recommendation. The form appends to app_v2/state/feedback_events.jsonl,
the same file live/session.py reads, so a report on lap L is consumed by the estimator from lap L of the replay."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import asset_repository as A
from app_v2.services import feedback_service as FS
from app_v2.services import live_bridge as LB
from app_v2.services import replay_service as RS
from app_v2.services import view_models as VM
from app_v2.state import app_state
from app_v2.ui import shell, cards, badges, banners, alerts, empty_states
from app_v2.ui.formatting import esc


def _shift(d: dict | None) -> str:
    return ', '.join(f'{k} {v:+.2f}' for k, v in (d or {}).items()) or 'none'


def render() -> None:
    ctx = common.context('feedback')
    if not common.require_lock(ctx, 'feedback'):
        return
    lock, ev = ctx.lock, ctx.event
    st.session_state['mode'] = 'live'
    driver = ctx.driver or app_state.default_driver(lock, ev) or 'UNK'
    src = app_state.source_for(ev, driver, lock.n_laps(ev)) if A.race_csv_asset(ev).exists else None
    vm, unavailable = None, ''
    if src is not None:
        src.poll()
        unavailable = RS.prediction_unavailable_reason(src.cursor)
        if not unavailable:
            vm = LB.build(lock, ev, driver, src.cursor, 'replay')
    orb = getattr(vm, 'orb_live', None) if vm else None
    lap_now = src.cursor.lap if src else int(st.session_state.get('lap') or 1)
    support = LB.support_status(vm) if vm else VM.SS.support_for(lock, ev, driver, ctx.compound).overall_support_status
    common.header(ctx, 'feedback', lap=lap_now, n_laps=lock.n_laps(ev), support=support, latency=LB.latency_text(vm, 'replay') if vm else 'no feed')
    st.markdown(f'## Driver feedback · {ev} · {driver} · lap {lap_now}')
    st.caption('Record what the driver feels. The estimate incorporates the report from the lap you select.')
    if src is None:
        empty_states.empty('No active replay', 'Choose a recorded race before adding driver feedback.')
        if st.button('Start Monza replay', type='primary'):
            common.goto('live', ev='Monza', drv='NOR', lap=1, mode='live')
        shell.ready_marker('feedback'); return
    if unavailable:
        banners.note_banner(unavailable)
    left, right = st.columns([3, 2], gap='large')
    with left:
        cards.section('Driver report')
        with st.form('feedback_form', clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            lap = c1.number_input('Lap', min_value=1, max_value=int(lock.n_laps(ev) or 80), value=lap_now, step=1)
            axle = c2.selectbox('Axle', FS.AXLES, index=1)
            phase = c3.selectbox('Corner phase', FS.CORNER_PHASES, index=4)
            c4, c5, c6 = st.columns(3)
            symptom = c4.selectbox('Symptom', FS.SYMPTOMS, index=6)
            severity = c5.slider('Severity', 1, 5, 3)
            trend = c6.selectbox('Trend', FS.TRENDS, index=2)
            c7, c8, c9 = st.columns(3)
            conf = c7.slider('Driver confidence', 0.0, 1.0, 0.7, 0.05)
            source = c8.selectbox('Source', FS.SOURCES, index=0)
            confirmed = c9.checkbox('Engineer confirmed', value=True)
            raw = st.text_input('Raw message', placeholder='e.g. "rears are going, traction out of the last corner"')
            submitted = st.form_submit_button('Log feedback', type='primary')
        if submitted:
            evt = FS.make_event(ev, driver, int(lap), axle, phase, symptom, int(severity), trend, float(conf), source, raw, bool(confirmed))
            FS.append(evt)
            alerts.alert('live', 'feedback logged', f'lap {lap} · {symptom} {axle} {phase} · severity {severity}/5 · {trend} · confidence {conf:.2f}' + (' · the estimator sees it from that lap of the replay' if int(lap) <= lap_now else f' · replay is at lap {lap_now}: it takes effect when the replay reaches lap {lap}'))
            st.rerun()
        log = (orb or {}).get('feedback_log') or []
        with st.expander('Report history & interpretation'):
            cards.section('Latest feedback (log)')
            rows = [[f['timestamp'][-8:], f['event'], f['driver'], f['lap'], f['symptom'], f['axle'], f['corner_phase'], f'{f["severity"]}/5', f['trend'], f'{f["driver_confidence"]:.2f}', f['source'], 'yes' if f['engineer_confirmed'] else 'no', f['raw_message']] for f in FS.latest(12)]
            if rows:
                st.html(cards.table_html(['time', 'event', 'driver', 'lap', 'symptom', 'axle', 'phase', 'severity', 'trend', 'conf.', 'source', 'confirmed', 'raw'], rows, numeric_cols=(3,)))
            else:
                st.html('<div class="cs-muted">no feedback logged yet</div>')
            cards.section("Estimator's reading of each report (live/feedback.py)", 'Rule applied, regime shift, process-noise multiplier, and whether the following laps confirmed or weakened it.')
            if log:
                st.html(cards.table_html(['lap', 'report', 'rule', 'regime shift', 'noise x', 'telemetry support', 'laps since', 'note'],
                                         [[e['lap'], f"{e['symptom']} {e['axle']} {e['corner_phase']} {e['severity']}/5", e.get('rule', '—'), _shift(e.get('regime_shift')), f"{e.get('noise_multiplier', 1):.2f}", e.get('telemetry_support', 'pending'), e.get('laps_since', 0), e.get('note', '')] for e in log], numeric_cols=(0, 4, 6)))
            elif orb:
                st.html('<div class="cs-muted">no report has reached the estimator yet for this session at this lap (reports apply from the lap they name; the replay is at lap ' + str(lap_now) + ')</div>')
            else:
                empty_states.pending('estimator reading', 'the live package (not importable)' if not LB.AVAILABLE else 'a race feed for this weekend')
    with right:
        cards.section('Current prediction')
        if orb:
            ts = orb['tyre_state']
            cards.kpi_card('Tyre degradation', f"{orb['slope']:+.3f}", f"90% range {orb['slope']-1.645*orb['slope_sd']:+.3f} to {orb['slope']+1.645*orb['slope_sd']:+.3f}", 'live', unit='s/lap')
            st.html(cards.card_html('Recommended strategy', f'<p>{esc(orb.get("top_headline", "—"))}</p>'))
            st.caption('Reports adjust the inferred tyre state; they are not direct tyre measurements.')
        if st.button('Return to prediction', type='primary', width='stretch'):
            common.goto('live', lap=lap_now)
        with st.expander('Feedback model details'):
            st.caption('Reports affect regime probabilities and uncertainty. They never directly add seconds to the tyre curve.')
            if orb:
                st.html(cards.kv_html([('regime', orb['regime']), ('regime probabilities', _shift(orb.get('regime_probs'))), ('estimator', orb['estimator_label']), ('reports this session', len(FS.for_session(ev, driver)))], stack=True))
    shell.ready_marker('feedback')
