"""End-to-end replay on real races: schema-valid outputs, timestamps <= data_cutoff, sidecars, view-model keys, feedback matching."""
import json

import pytest

from schemas.lock_v2 import LivePredictor, LiveRecommendation, LiveTyreState, ts_le
from live_helpers import PROTO


@pytest.fixture(scope='module')
def replay_dir(tmp_path_factory, have_races):
    if not have_races:
        pytest.skip('race files or lock not present')
    from live import replay_run
    out = tmp_path_factory.mktemp('live_out')
    summary = replay_run.run('Monza', 'NOR', out_root=out, quiet=True)
    return out / 'Monza_NOR', summary


def test_replay_outputs_validate(replay_dir):
    d, summary = replay_dir
    states = [json.loads(l) for l in (d / 'states.jsonl').read_text().splitlines()]
    recs = [json.loads(l) for l in (d / 'recommendations.jsonl').read_text().splitlines()]
    assert len(states) == len(recs) == summary['laps_processed'] > 40
    prev = None
    for s, r in zip(states, recs):
        m = LiveTyreState.model_validate(s)
        assert s['lap'] == r['lap'] and ts_le(m.timestamp, summary['data_cutoff'])
        if prev is not None:
            assert m.lap > prev.lap and ts_le(prev.timestamp, m.timestamp)
        prev = m
        for a in r['actions']:
            am = LiveRecommendation.model_validate(a)
            assert am.lap == s['lap'] and ts_le(am.issued_at, m.timestamp) and ts_le(m.timestamp, am.issued_at)
            if am.changed_since_last_update:
                assert am.change_reason
        assert r['estimator'] == 'linear-Gaussian with fixed regime rules'
    block = json.load(open(d / 'live_predictor.json'))
    lp = LivePredictor.model_validate(block)
    assert lp.uses_future_data is False and lp.uses_post_race_reference is False and lp.state_history is not None
    assert summary['uses_future_data'] is False and summary['uses_post_race_reference'] is False
    for name in ('states.jsonl', 'recommendations.jsonl', 'estimator_trace.jsonl', 'live_predictor.json', 'summary.json', 'driver_feedback.json'):
        from shared.lockio import sha256_file
        digest = (d / f'{name}.sha256').read_text().split()[0]
        assert digest == sha256_file(d / name)


def test_feedback_from_log_is_matched_by_lap_and_reverts_when_disabled(tmp_path, have_races):
    if not have_races:
        pytest.skip('race files not present')
    from live.session import LiveSession
    log = tmp_path / 'feedback_events.jsonl'
    evt = dict(timestamp='2026-06-28T15:20:00', event='Austria', driver='NOR', lap=12, axle='rear', corner_phase='traction', symptom='sliding', severity=4, trend='worsening',
               driver_confidence=0.9, source='radio', raw_message='rears going', engineer_confirmed=True)
    log.write_text(json.dumps(evt) + '\n' + json.dumps(dict(evt, event='Monza', lap=9)) + '\n')
    on = list(LiveSession.open('Austria', 'NOR', feedback_path=log).run(through_lap=16))
    off = list(LiveSession.open('Austria', 'NOR', feedback_path=log, feedback_enabled=False).run(through_lap=16))
    none = list(LiveSession.open('Austria', 'NOR', feedback_events=[]).run(through_lap=16))
    l12 = next(r for r in on if r.lap == 12)
    assert l12.feedback and l12.state.regime_probs.get('OVERHEATING', 0) > 0 and all(not r.feedback for r in on if r.lap != 12)
    import numpy as np
    numeric = ('degradation_rate', 'corrected_pace_loss', 'useful_laps_q10', 'useful_laps_q50', 'useful_laps_q90', 'cliff_probability_3_laps', 'cliff_probability_5_laps', 'trend_vs_pre_race', 'confidence', 'state_regime')
    for a, b in zip(off, none):
        assert np.allclose(a.state.m, b.state.m, equal_nan=True) and a.state.P == b.state.P and a.state.regime_probs == b.state.regime_probs
        assert {k: a.tyre_state[k] for k in numeric} == {k: b.tyre_state[k] for k in numeric}
        assert a.tyre_state['sensor_availability']['team_radio'] is False       # the switch is visible in the channel table, nothing else
    assert on[-1].state.P != none[-1].state.P


def test_viewmodel_keys_match_workstream_6(have_races):
    if not have_races:
        pytest.skip('race files not present')
    pytest.importorskip('streamlit')
    from app_v2.services import lock_repository as LR, replay_service as RS, view_models as VM
    from live import viewmodel as LV
    lock = LR.load_lock()
    cur = RS.ReplayCursor('Monza', 'NOR', lock.n_laps('Monza')).seek(25)
    d = LV.build_live(lock, 'Monza', 'NOR', cur, 'replay')
    assert set(d) - {'orb_live'} == set(VM.LiveVM.__dataclass_fields__)
    vm = LV.build_live_vm(lock, 'Monza', 'NOR', cur, 'replay')
    assert isinstance(vm, VM.LiveVM) and vm.lap == 25 and vm.state is not None and vm.state.post_slope is not None
    assert vm.orb_live['tyre_state']['lap'] == 25 and LiveTyreState.model_validate(vm.orb_live['tyre_state'])
    assert [k.label for k in vm.kpis] == ['LIVE DEGRADATION', 'USEFUL LIFE', 'CLIFF RISK', 'PIT WINDOW', 'RECOMMENDED TYRE']
    assert all(k.value != '—' for k in vm.kpis[:3]) and vm.decision.rule_label.startswith('linear-Gaussian')
    assert vm.state.lap == 25 and max(vm.state.all_ages) == vm.state.tyre_age
