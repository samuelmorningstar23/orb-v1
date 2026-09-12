"""Route 4, Driver feedback: structured entry (7.3), latest feedback, effect on posterior (Workstream 8 pending)."""
from __future__ import annotations
import streamlit as st
from app_v2.pages import common
from app_v2.services import feedback_service as FS
from app_v2.services import view_models as VM
from app_v2.state import app_state
from app_v2.ui import shell, cards, badges, banners, alerts
from app_v2.ui.formatting import esc


def render() -> None:
    ctx = common.context('feedback')
    if not common.require_lock(ctx, 'feedback'):
        return
    lock, ev = ctx.lock, ctx.event
    st.session_state['mode'] = 'live'
    driver = ctx.driver or app_state.default_driver(lock, ev) or 'UNK'
    lap_now = int(st.session_state.get('lap') or 1)
    sup = VM.SS.support_for(lock, ev, driver, ctx.compound)
    common.header(ctx, 'feedback', lap=lap_now, n_laps=lock.n_laps(ev), support=sup.overall_support_status, latency='replay')
    st.markdown(f'## Driver feedback · {ev} · {driver}')
    banners.note_banner('Feedback is a timestamped observation with a confidence, entered or confirmed by the engineer. It shifts regime probabilities; it never adds seconds to a curve. It can be disabled with the result reverting.')
    left, right = st.columns([3, 2], gap='large')
    with left:
        cards.section('Structured entry', f'Appends to {FS.log_path().name}; timestamp is automatic.')
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
            alerts.alert('live', 'feedback logged', f'lap {lap} · {symptom} {axle} {phase} · severity {severity}/5 · {trend} · confidence {conf:.2f}')
        cards.section('Latest feedback')
        rows = [[f['timestamp'][-8:], f['event'], f['driver'], f['lap'], f['symptom'], f['axle'], f['corner_phase'], f'{f["severity"]}/5', f['trend'], f'{f["driver_confidence"]:.2f}', f['source'], 'yes' if f['engineer_confirmed'] else 'no', f['raw_message']] for f in FS.latest(12)]
        if rows:
            st.html(cards.table_html(['time', 'event', 'driver', 'lap', 'symptom', 'axle', 'phase', 'severity', 'trend', 'conf.', 'source', 'confirmed', 'raw'], rows, numeric_cols=(3,)))
        else:
            st.html('<div class="cs-muted">no feedback logged yet</div>')
    with right:
        cards.section('Whether telemetry supports it', 'Pending Workstream 8: the next laps confirm or weaken each report.')
        st.html(badges.badge_html('telemetry corroboration · pending Workstream 8', 'placeholder'))
        cards.section('Effect on posterior and recommendation')
        st.html(cards.card_html('', '<div class="cs-muted">PLACEHOLDER · Workstream 8 LiveTyreStateEstimator consumes the log and shifts regime probabilities (for example normal degradation toward overheating). Until then a severity 4 or 5 report moves the decision card to REVIEW with the report named as the reason; the posterior itself is unchanged.</div>'))
        cards.section('Calibration history', 'Pending: how often reports were confirmed by the following laps, per driver.')
        st.html(badges.badge_html('calibration history · pending', 'placeholder'))
        n = len(FS.for_session(ev, driver))
        st.html(cards.kv_html([('reports this session', n), ('log path', str(FS.log_path().relative_to(FS.P.PROTO_ROOT))), ('enabled', 'yes' if FS.enabled() else 'no (directory not writable)')]))
    shell.ready_marker('feedback')
