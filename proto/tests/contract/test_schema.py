"""The fixture validates; stable blocks reject extras; live and ghost claim flags cannot be flipped; enums and hashes are enforced."""
import json
import math

import pytest
from pydantic import ValidationError

from schemas import lock_v2 as S
from schemas.lock_v2 import LockV2, LiveTyreState, SidecarRef
from validators import validate_lock


def invalid(data, *needles: str):
    with pytest.raises(ValidationError) as exc:
        LockV2.model_validate(data)
    text = str(exc.value)
    for n in needles:
        assert n in text, f'expected {n!r} in error:\n{text}'
    return exc.value


def test_fixture_validates_and_covers_every_namespace(fixture_lock):
    lock = LockV2.model_validate(fixture_lock)
    assert sorted(lock.blocks()) == ['driver_profile', 'ghost_strategy', 'input_availability', 'live_predictor', 'pre_race_forecast', 'shared', 'validation']
    assert len(lock.counterfactuals) == 1 and lock.extensions
    assert lock.shared.forecast_hash == S.compute_forecast_hash(lock.pre_race_forecast)
    assert lock.ghost_strategy.forecast_snapshot_hash == lock.live_predictor.prior.forecast_hash == lock.counterfactuals[0].forecast_hash == lock.shared.forecast_hash


def test_fixture_passes_the_cli_validator(fixture_path, proto_dir):
    assert validate_lock.validate(fixture_path, proto_dir, strict=True, quiet=True) == 0


def test_round_trip_is_stable(fixture_lock):
    lock = LockV2.model_validate(fixture_lock)
    dumped = lock.model_dump(mode='json', by_alias=True)
    assert dumped == fixture_lock
    assert LockV2.model_validate(json.loads(json.dumps(dumped))).model_dump(mode='json', by_alias=True) == dumped


@pytest.mark.parametrize('path', [
    (), ('shared',), ('shared', 'meta'), ('shared', 'forecast_snapshot'), ('shared', 'support_definition'),
    ('pre_race_forecast',), ('pre_race_forecast', 'events', 'Monza'), ('pre_race_forecast', 'events', 'Monza', 'compounds', 'SOFT'), ('pre_race_forecast', 'events', 'Monza', 'strategy'),
    ('validation',), ('validation', 'calibration'), ('validation', 'rows'),
    ('live_predictor',), ('live_predictor', 'prior'), ('live_predictor', 'posterior'), ('live_predictor', 'recommendations', 0), ('live_predictor', 'driver_feedback', 0),
    ('ghost_strategy',), ('ghost_strategy', 'race_reference'), ('ghost_strategy', 'generalisation_status'),
    ('counterfactuals', 0), ('counterfactuals', 0, 'summary'), ('counterfactuals', 0, 'assumptions'), ('counterfactuals', 0, 'validation'),
    ('input_availability',), ('input_availability', 'channels', 'lap_time'), ('driver_profile',),
])
def test_extra_property_rejected_in_stable_blocks(fixture_lock, path):
    node = fixture_lock
    for p in path:
        node = node[p]
    node['tread_remaining_mm'] = 2.1
    invalid(fixture_lock, 'Extra inputs are not permitted')


def test_extensions_accept_anything(fixture_lock):
    fixture_lock['extensions']['workstream_5'] = {'frozen_field': {'nested': [1, 'two', {'three': 3.0}]}, 'anything': None}
    assert LockV2.model_validate(fixture_lock).extensions['workstream_5']['anything'] is None


@pytest.mark.parametrize('flag', ['uses_future_data', 'uses_post_race_reference'])
def test_live_predictor_cannot_claim_future_or_post_race_data(fixture_lock, flag):
    fixture_lock['live_predictor'][flag] = True
    invalid(fixture_lock, flag, 'Input should be False')


@pytest.mark.parametrize('flag', ['model_implied', 'live_estimator_disabled'])
def test_ghost_strategy_is_always_model_implied(fixture_lock, flag):
    fixture_lock['ghost_strategy'][flag] = False
    invalid(fixture_lock, flag, 'Input should be True')


@pytest.mark.parametrize('bad', ['IN-SUPPORT', 'in support', 'OUT OF SUPPORT', 'NEAR SUPPORT', ''])
def test_support_status_enum_enforced(fixture_lock, bad):
    fixture_lock['live_predictor']['posterior']['support_status'] = bad
    invalid(fixture_lock, 'support_status')
    fixture_lock['live_predictor']['posterior']['support_status'] = 'IN SUPPORT'
    fixture_lock['ghost_strategy']['generalisation_status']['overall_support_status'] = bad
    invalid(fixture_lock, 'overall_support_status')


def test_support_status_values_accepted(fixture_lock):
    for value in ('IN SUPPORT', 'NEAR TRAINING SUPPORT', 'OUT OF SUPPORT, FORECAST WITHHELD'):
        fixture_lock['live_predictor']['posterior']['support_status'] = value
        g = fixture_lock['ghost_strategy']['generalisation_status']
        g['overall_support_status'] = value
        g['abstention_reason'] = 'track never seen and practice wet' if value == S.SUPPORT_WITHHELD else None
        fixture_lock['ghost_strategy']['counterfactual'] = None if value == S.SUPPORT_WITHHELD else fixture_lock['ghost_strategy']['counterfactual']
        LockV2.model_validate(fixture_lock)


def test_withheld_forecast_needs_reason_and_no_counterfactual(fixture_lock):
    g = fixture_lock['ghost_strategy']['generalisation_status']
    g['overall_support_status'] = S.SUPPORT_WITHHELD
    invalid(fixture_lock, 'abstention_reason')
    g['abstention_reason'] = 'never-seen circuit'
    invalid(fixture_lock, 'withheld forecast cannot carry a counterfactual')


@pytest.mark.parametrize('bad', ['PUBLIC_PROXY', 'public proxy', 'TEAM', 'TEAM_SENSOR'])
def test_sensor_mode_enum_enforced(fixture_lock, bad):
    fixture_lock['live_predictor']['posterior']['sensor_mode'] = bad
    invalid(fixture_lock, 'sensor_mode')


def test_public_proxy_forbids_private_channels(fixture_lock):
    fixture_lock['live_predictor']['posterior']['team_sensor'] = {'pressure_bar': {'FL': 1.9, 'FR': 1.9, 'RL': 1.7, 'RR': 1.7}}
    invalid(fixture_lock, "not allowed under sensor_mode 'PUBLIC PROXY'")
    fixture_lock['live_predictor']['posterior']['team_sensor'] = None
    fixture_lock['input_availability']['channels']['tyre_pressure']['available'] = True
    fixture_lock['input_availability']['missing_channels'].remove('tyre_pressure')
    invalid(fixture_lock, "'PUBLIC PROXY' cannot have private channels available")


def test_sensor_mode_must_agree_between_live_state_and_input_table(fixture_lock):
    fixture_lock['live_predictor']['posterior']['sensor_mode'] = 'TEAM SENSOR'
    invalid(fixture_lock, 'sensor_mode differs')


def test_ordered_quantiles_enforced(fixture_lock):
    post = fixture_lock['live_predictor']['posterior']
    post['useful_laps_q10'], post['useful_laps_q50'] = 9.0, 8.0
    invalid(fixture_lock, 'quantiles must be ordered')
    post['useful_laps_q10'] = 6.0
    post['cliff_probability_3_laps'] = 0.5
    invalid(fixture_lock, 'cliff_probability_3_laps cannot exceed')
    post['cliff_probability_3_laps'] = 0.18
    rec = fixture_lock['live_predictor']['recommendations'][0]
    rec['expected_gain_q10'] = rec['expected_gain_median'] + 1
    invalid(fixture_lock, 'quantiles must be ordered')


def test_recommendation_rules(fixture_lock):
    rec = fixture_lock['live_predictor']['recommendations'][0]
    rec['pit_window'] = None
    invalid(fixture_lock, 'requires a pit_window')
    rec['pit_window'] = [24, 25]
    rec['change_reason'] = None
    invalid(fixture_lock, 'must carry a change_reason')


def test_driver_feedback_vocabulary(fixture_lock):
    fb = fixture_lock['live_predictor']['driver_feedback'][0]
    for field, bad in (('axle', 'left'), ('corner_phase', 'apex'), ('symptom', 'bouncing'), ('severity', 6), ('trend', 'better'), ('driver_confidence', 1.5)):
        good = fb[field]
        fb[field] = bad
        invalid(fixture_lock, field)
        fb[field] = good
    LockV2.model_validate(fixture_lock)


def test_online_safety_timestamps(fixture_lock):
    live = fixture_lock['live_predictor']
    live['posterior']['timestamp'] = '2026-09-06T17:00:00'
    invalid(fixture_lock, 'later than data_cutoff')
    live['posterior']['timestamp'] = live['data_cutoff']
    live['recommendations'][0]['issued_at'] = '2026-09-06T17:00:00'
    invalid(fixture_lock, 'issued after data_cutoff')
    live['recommendations'][0]['issued_at'] = live['data_cutoff']
    live['driver_feedback'][0]['timestamp'] = '2026-09-06T17:00:00'
    invalid(fixture_lock, 'after data_cutoff')
    live['driver_feedback'][0]['timestamp'] = live['data_cutoff']
    live['posterior']['timestamp'] = '2026-09-06T15:00:00+00:00'
    invalid(fixture_lock, 'mixed naive and timezone-aware')


def test_forecast_hash_must_match_block(fixture_lock):
    fixture_lock['shared']['forecast_hash'] = 'sha256:' + '0' * 64
    invalid(fixture_lock, 'forecast_hash', 'does not match the pre_race_forecast block')


def test_changing_the_forecast_changes_the_hash(fixture_lock):
    fixture_lock['pre_race_forecast']['events']['Madrid']['compounds']['SOFT']['prediction'] += 0.001
    invalid(fixture_lock, 'does not match the pre_race_forecast block')


def test_changing_forecast_meta_does_not_change_the_hash(fixture_lock):
    fixture_lock['pre_race_forecast']['meta']['generated_at'] = '2027-01-01T00:00:00'
    fixture_lock['pre_race_forecast']['meta']['git_sha'] = 'deadbeef'
    LockV2.model_validate(fixture_lock)


def test_every_mode_references_the_same_forecast(fixture_lock):
    other = 'sha256:' + 'a' * 64
    for path in (('ghost_strategy', 'forecast_snapshot_hash'), ('live_predictor', 'prior', 'forecast_hash'), ('counterfactuals', 0, 'forecast_hash')):
        lock = json.loads(json.dumps(fixture_lock))
        node = lock
        for p in path[:-1]:
            node = node[p]
        node[path[-1]] = other
        invalid(lock, 'differs from shared.forecast_hash')


def test_ghost_counterfactual_must_equal_the_scenario(fixture_lock):
    fixture_lock['ghost_strategy']['counterfactual']['summary']['elapsed_delta_median_s'] -= 1.0
    invalid(fixture_lock, 'map must equal numbers')
    fixture_lock['ghost_strategy']['counterfactual']['summary']['elapsed_delta_median_s'] += 1.0
    fixture_lock['ghost_strategy']['counterfactual']['scenario_id'] = 'missing'
    invalid(fixture_lock, 'is not in counterfactuals[]')


def test_counterfactual_claims_are_bound_to_mode(fixture_lock):
    cf = fixture_lock['counterfactuals'][0]
    cf['track_position_simulated'] = True
    invalid(fixture_lock, 'tyre_only scenarios cannot simulate')
    cf['track_position_simulated'] = False
    for k, v in (('estimated_finish_position_median', 5.0), ('estimated_finish_position_q10', 4.0), ('estimated_finish_position_q90', 7.0)):
        cf['summary'][k] = v
        fixture_lock['ghost_strategy']['counterfactual']['summary'][k] = v
    invalid(fixture_lock, 'finish positions are allowed only in frozen_field')
    cf['assumptions']['rival_strategy_response'] = 'reactive'
    invalid(fixture_lock, 'rival_strategy_response')


def test_plan_consistency(fixture_lock):
    cf = fixture_lock['counterfactuals'][0]
    cf['counterfactual_plan']['pit_laps'] = [22]
    invalid(fixture_lock, 'pit_laps')
    cf['counterfactual_plan']['pit_laps'] = [23]
    cf['counterfactual_plan']['label'] = 'M-M'
    invalid(fixture_lock, 'label must spell the stint compounds')


def test_scenario_explorer_is_never_evidence(fixture_lock):
    g = fixture_lock['ghost_strategy']
    g['weather_context'] = 'hotter_dry'
    invalid(fixture_lock, 'only actual-weather audits count as evidence')
    g['weather_context'] = 'wet'
    invalid(fixture_lock, 'weather_context')


def test_nan_and_inf_are_rejected(fixture_lock):
    fixture_lock['live_predictor']['posterior']['degradation_rate'] = float('nan')
    invalid(fixture_lock, 'degradation_rate')
    fixture_lock['live_predictor']['posterior']['degradation_rate'] = math.inf
    invalid(fixture_lock, 'degradation_rate')


def test_pre_race_band_and_gate_consistency(fixture_lock):
    c = fixture_lock['pre_race_forecast']['events']['Monza']['compounds']['SOFT']
    c['band90'] = [c['band90'][1], c['band90'][0]]
    invalid(fixture_lock, 'band90 must be [low, high]')
    c['band90'] = [c['band90'][1], c['band90'][0]]
    c['issued'] = False
    invalid(fixture_lock, "issued must be true exactly when gate == 'ok'")


@pytest.mark.parametrize('bad', ['/abs/path.json', '../escape.json', 'out/../x.json', 'out\\win.json', ''])
def test_sidecar_paths_are_relative_posix(bad):
    with pytest.raises(ValidationError):
        SidecarRef(path=bad, sha256='0' * 64)
    with pytest.raises(ValidationError):
        SidecarRef(path='out/x.json', sha256='not-a-hash')
    SidecarRef(path='out/x.json', sha256='0' * 64)


def test_live_tyre_state_stands_alone(fixture_lock):
    state = LiveTyreState.model_validate(fixture_lock['live_predictor']['posterior'])
    assert state.sensor_mode == 'PUBLIC PROXY' and state.support_status == 'IN SUPPORT'
    assert set(state.missing_channels) >= {k for k, v in state.sensor_availability.items() if not v}
    fixture_lock['live_predictor']['posterior']['missing_channels'] = []
    with pytest.raises(ValidationError, match='must be listed in missing_channels'):
        LiveTyreState.model_validate(fixture_lock['live_predictor']['posterior'])


def test_minimal_lock_only_needs_shared(fixture_lock):
    lock = LockV2.model_validate({'schema_version': S.SCHEMA_VERSION, 'shared': fixture_lock['shared']})
    assert lock.pre_race_forecast is None and lock.counterfactuals == [] and lock.extensions == {}
    invalid({'schema_version': '3.0.0', 'shared': fixture_lock['shared']}, 'not major version 3')


def test_exported_json_schema_matches_the_models():
    on_disk = json.loads(S.SCHEMA_JSON_PATH.read_text(encoding='utf-8'))
    assert on_disk == S.json_schema(), 'schemas/lock_v2.schema.json is stale: run `python proto/schemas/lock_v2.py export`'


def test_json_schema_forbids_additional_properties_everywhere_but_extensions():
    schema = S.json_schema()
    assert schema['additionalProperties'] is False
    assert schema['properties']['extensions']['additionalProperties'] is True
    open_defs = [name for name, d in schema['$defs'].items() if d.get('type') == 'object' and d.get('additionalProperties') is not False]
    assert open_defs == [], f'stable blocks must set additionalProperties false: {open_defs}'
    assert schema['$defs']['LivePredictor']['properties']['uses_future_data']['const'] is False
    assert schema['$defs']['GhostStrategy']['properties']['model_implied']['const'] is True


def test_traffic_mode_vocabulary(fixture_lock):
    cf = fixture_lock['counterfactuals'][0]
    assert cf['traffic_mode'] == 'paired_replay'
    for legacy in ('observed_fixed', 'none', 'simulated', 'clean-air'):
        cf['traffic_mode'] = legacy
        invalid(fixture_lock, 'traffic_mode')
    cf['traffic_mode'] = 'clean_air'
    LockV2.model_validate(fixture_lock)
    cf['traffic_mode'] = 'frozen_field'
    invalid(fixture_lock, 'tyre_only scenarios cannot simulate')
    assert set(S.json_schema()['$defs']['CounterfactualScenario']['properties']['traffic_mode']['enum']) == {'clean_air', 'paired_replay', 'frozen_field'}


def test_safety_car_schedule_accepts_literal_or_period_list(fixture_lock):
    cf = fixture_lock['counterfactuals'][0]
    for literal in ('historical_fixed', 'observed_fixed'):
        cf['safety_car_schedule'] = literal
        assert LockV2.model_validate(fixture_lock).counterfactuals[0].safety_car_schedule == literal
    cf['safety_car_schedule'] = [{'kind': 'VSC', 'start_lap': 3, 'end_lap': 4}, {'kind': 'SC', 'start_lap': 30, 'end_lap': 33}]
    periods = LockV2.model_validate(fixture_lock).counterfactuals[0].safety_car_schedule
    assert [p.kind for p in periods] == ['VSC', 'SC']
    cf['safety_car_schedule'] = []
    LockV2.model_validate(fixture_lock)                       # an empty observed period list is legitimate (no SC in the race)
    cf['safety_car_schedule'] = [{'kind': 'SC', 'start_lap': 10, 'end_lap': 9}]
    invalid(fixture_lock, 'end_lap must be >= start_lap')
    cf['safety_car_schedule'] = [{'kind': 'RED', 'start_lap': 10, 'end_lap': 11, 'cause': 'debris'}]
    invalid(fixture_lock, 'Extra inputs are not permitted')
    cf['safety_car_schedule'] = 'fixed'
    invalid(fixture_lock, 'safety_car_schedule')
    del cf['safety_car_schedule']
    invalid(fixture_lock, 'safety_car_schedule', 'Field required')


def test_state_regime_vocabulary_and_minor_version_compatibility(fixture_lock):
    assert S.SCHEMA_VERSION == '2.1.0'
    post = fixture_lock['live_predictor']['posterior']
    for regime in ('accelerating_wear', 'anomaly', 'normal', 'overheating', 'cliff', 'unknown'):
        post['state_regime'] = regime
        assert LockV2.model_validate(fixture_lock).live_predictor.posterior.state_regime == regime
    post['state_regime'] = 'wearing_fast'
    invalid(fixture_lock, 'state_regime')
    post['state_regime'] = 'normal'
    fixture_lock['live_predictor']['meta']['schema_version'] = '2.0.0'          # a block written under 2.0.x still validates: minor bumps are additive
    fixture_lock['schema_version'] = '2.0.0'
    LockV2.model_validate(fixture_lock)
    assert set(S.json_schema()['$defs']['LiveTyreState']['properties']['state_regime']['enum']) >= {'accelerating_wear', 'anomaly', 'warm_up', 'cooling'}
