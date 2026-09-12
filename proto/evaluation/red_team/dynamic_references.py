"""Explicit-feedback runtime evidence for C6 rehearsal, never a mismatch exemption."""
from __future__ import annotations
import hashlib
import json
from evaluation.red_team.consistency_probe import ReferenceSet, route_references, LIVE_PAGES


def live_runtime_references(base, lock, page, state, feedback_events):
    """Recompute the displayed prefix with the exact submitted feedback snapshot.

    Hashed no-feedback live sidecars are removed from this route's reference set.
    No future-lap feedback or mismatching event/driver record is admitted.
    Returns reference set plus serializable evidence identifying every runtime input.
    """
    from live.session import LiveSession
    if page not in LIVE_PAGES:
        raise ValueError('dynamic feedback references require a live route')
    event, driver, lap = state['ev'], state['drv'], int(state['lap'])
    applicable = [dict(e) for e in feedback_events if e.get('event') == event
                  and e.get('driver') in (driver, None, '') and 0 < int(e.get('lap', -1)) <= lap]
    session = LiveSession.open(event, driver, feedback_events=applicable)
    results = list(session.run(through_lap=lap))
    if not results or results[-1].lap != lap:
        raise RuntimeError(f'no exact live runtime state at requested lap {lap}')
    refs = route_references(base, lock, page, state)
    refs.values = {k: v for k, v in refs.values.items()
                   if not k.startswith(('sidecar:out/live/', 'live_runtime:', 'state:feedback_log'))}
    runtime = ReferenceSet()
    kind = f'live_runtime:{event}_{driver}:explicit_feedback'
    runtime.add(kind, session.n_laps, "session.n_laps")
    # Authored record-schema identifier displayed by latency_text, not a measured value.
    from app_v2.services.live_bridge import latency_text
    from types import SimpleNamespace
    if "(7.1 source_latency)" not in latency_text(SimpleNamespace(orb_live={"tyre_state": {"source_latency": 0.0}}), ""):
        raise RuntimeError("live contract identifier changed; update its typed reference")
    runtime.add("ui_contract_identifier", 7.1, "app_v2/services/live_bridge.py:latency_text:source_latency_schema")
    records = []
    for result in results:
        record = dict(lap=result.lap, tyre_state=result.tyre_state, actions=result.ranked.actions,
                      baseline=result.ranked.baseline, trace=result.state.as_trace(),
                      prior_sd=result.state.prior_sd, feedback_consumed=result.feedback)
        runtime.add_record(kind, record, f'{event}_{driver}:lap{result.lap}:explicit_feedback')
        records.append(record)
    # Runtime first: each match exposes the strongest available prefix evidence.
    runtime.values.update(refs.values)
    runtime.notes = refs.notes + ['C6 explicit-feedback replay; no no-feedback sidecar values admitted for live state.']
    payload = json.dumps(applicable, sort_keys=True, separators=(',', ':'), default=str).encode()
    evidence = dict(event=event, driver=driver, through_lap=lap, n_laps=session.n_laps, forecast_hash=session.priors.forecast_hash,
                    feedback_sha256=hashlib.sha256(payload).hexdigest(), feedback_events=applicable,
                    consumed_events=[e for r in results for e in r.feedback],
                    records=records, input_policy='frozen priors; feed through displayed lap only; exact explicit feedback snapshot')
    return runtime, evidence
