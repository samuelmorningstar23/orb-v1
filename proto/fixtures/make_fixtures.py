"""Deterministic generator for the Workstream 1 fixtures. Re-run after a schema change; the output must not change otherwise.

    python fixtures/make_fixtures.py            writes:
      fixtures/lock_v2_fixture.json             every namespace populated with realistic values (Monza 2026 replay/audit, Madrid prospective)
      fixtures/sidecars/*.json                  small sidecars the fixture references by {path, sha256}
      fixtures/mini_race/Mini_R.csv             synthetic race in the feat CSV layout: 3 drivers x 14 laps, one stop each
      fixtures/mini_race/Mini_positions.csv     4 Hz position trace (Driver, SessionTime_s, X, Y) on a stadium loop, consistent with the lap times
      fixtures/mini_race/manifest.json          what the mini race contains and how it was generated
      fixtures/golden_race.json                 the real Monza 2026 feature files by path with sha256 (only when feat/Monza_*.csv exist)

Numbers come from fixtures/seed_v1_snapshot.json (a frozen copy of out/lock.json as of 2026-09-12T14:31:34) plus illustrative live,
ghost and counterfactual values that follow the roadmap story (the MEDIUM degrading 31% faster than forecast, stop moved to laps 24-25).
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
PROTO = HERE.parent
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from shared.lockio import atomic_write_json, atomic_write_text, content_hash, read_json, sha256_file, sha256_text, sidecar_ref, write_sidecar_json  # noqa: E402
from schemas.lock_v2 import CLAIM_SCOPE_BY_MODE, DEFAULT_UNITS, LockV2, PreRaceForecast, SCHEMA_VERSION, compute_forecast_hash  # noqa: E402
from validators.adapt_v1 import (CONFIDENCE_EFFECT_PUBLIC, HOLDOUT_MANIFEST, MODEL_VERSION, build_driver_profile, build_input_availability,  # noqa: E402
                                 compound_from_live, compound_from_row, event_forecast, make_meta, public_channels)

SEED = read_json(HERE / 'seed_v1_snapshot.json')
SEASON = 2026
GENERATED_AT = '2026-09-12T15:30:00'          # fixed: the fixture must be byte-stable across regenerations
GIT_SHA = '02f4c00'                           # C0 commit
MODEL_HASH = content_hash({'fixture_model': MODEL_VERSION, 'rules': SEED['rules']})
RACE_START = datetime.fromisoformat('2026-09-06T15:00:00')   # Monza 2026 race, local time; fixture timestamps are naive local
LAP_S = 87.2
FEAT_COLUMNS = ['event', 'session', 'Driver', 'LapNumber', 'Stint', 'Compound', 'TyreLife', 'FreshTyre', 'lap_s', 's1', 's2', 's3', 't_min', 'TrackStatus',
                'IsAccurate', 'pit_in', 'pit_out', 'deleted', 'energy_MJ', 'e_lat', 'e_long', 'traffic', 'full_throttle', 'n_tel', 'pos_distinct', 'stale_share',
                'track_temp', 'rain']
GRID_2026 = ['ALB', 'ALO', 'ANT', 'BEA', 'BOR', 'BOT', 'COL', 'GAS', 'HAD', 'HAM', 'HUL', 'LAW', 'LEC', 'LIN', 'NOR', 'OCO', 'PER', 'PIA', 'RUS', 'SAI', 'STR', 'TSU', 'VER']
TRACKS_SEEN = ['Australia', 'Austria', 'Barcelona', 'Belgium', 'Britain', 'Canada', 'Hungary', 'Japan', 'Miami', 'Monza', 'Zandvoort']


def ts(lap: float, offset_s: float = 0.0) -> str:
    return (RACE_START + timedelta(seconds=LAP_S * lap + offset_s)).isoformat(timespec='seconds')


def meta(what: str, data_cutoff: str) -> dict[str, Any]:
    return make_meta(GENERATED_AT, data_cutoff, GIT_SHA, MODEL_HASH, f'fixtures/make_fixtures.py: {what}')


# ---------------------------------------------------------------- lock fixture

def build_lock() -> dict[str, Any]:
    v1_at = SEED['v1_generated_at']
    monza_rows = SEED['validation_rows_monza']
    monza_obs = {r['compound']: r for r in monza_rows}
    events = {
        'Madrid': event_forecast('Madrid', SEED['live_madrid']['meta'], [compound_from_live(c) for c in SEED['live_madrid']['compounds']], 'prospective', v1_at,
                                 SEED['strategy']['Madrid'], SEASON, note=SEED['strategy']['Madrid'].get('note')),
        'Monza': event_forecast('Monza', SEED['events']['Monza'], [compound_from_row(r) for r in monza_rows], 'leave_one_weekend_out', v1_at, SEED['strategy']['Monza'], SEASON),
    }
    forecast = PreRaceForecast.model_validate(dict(meta=meta('pre_race_forecast from seed_v1_snapshot.json', v1_at), events=events))
    fh = compute_forecast_hash(forecast)
    monza_medium = forecast.events['Monza'].compounds['MEDIUM']

    shared = dict(meta=meta('shared', v1_at),
                  forecast_snapshot=dict(snapshot_id=f'Madrid_FP1+FP2_{fh[7:15]}', kind='prospective', event='Madrid', event_id='2026_Madrid', season=SEASON, issued_at=v1_at,
                                         sessions_used=['FP1', 'FP2'], race_laps=56, tyre_nomination=SEED['live_madrid']['meta'].get('tyres'),
                                         note='issued from practice sessions only; the hash is frozen before the race and both modes must reference it'),
                  model_version=MODEL_VERSION, forecast_hash=fh, training_cutoff=v1_at,
                  support_definition=dict(definition='Training support is the set of completed 2026 weekends scored leave-one-weekend-out; a track is seen when it has practice and race files; '
                                                     'weather is in range when practice was dry and track temperature lies inside the observed practice range.',
                                          tracks_seen=TRACKS_SEEN, drivers_seen=GRID_2026, seasons_seen=[SEASON], weather=['dry'], compounds=['SOFT', 'MEDIUM', 'HARD'],
                                          track_temp_range_c=[27.55, 55.1], n_training_weekends=len(TRACKS_SEEN)))

    rows_ref = write_sidecar_json(dict(generated_at=v1_at, n_rows=len(monza_rows), columns=list(monza_rows[0].keys()), rows=monza_rows),
                                  HERE / 'sidecars' / 'validation_rows_monza.json', PROTO, description='Monza compound-weekend rows incl. observed race degradation (post-race)')
    manifest = PROTO / HOLDOUT_MANIFEST
    validation = dict(meta=meta('validation copied from seed_v1_snapshot.json', v1_at), source='pipeline.py leave-one-weekend-out scorecard (frozen v1 snapshot of 2026-09-12T14:31:34)',
                      **SEED['validation'], rows=rows_ref,
                      sealed_holdout=(sidecar_ref(manifest, PROTO, format='json', description='sealed holdout manifest gold-v1.1; never opened before freeze.json') if manifest.exists() else None))

    # live predictor: Monza replay, NOR on the MEDIUM, lap 17 consumed
    cutoff = ts(17, 5.0)
    history = []
    for lap in range(1, 18):
        rate = round(monza_medium.prediction * (1.0 + 0.31 * min(1.0, max(0.0, (lap - 9) / 8))), 5)
        history.append(dict(lap=lap, timestamp=ts(lap), compound='MEDIUM', tyre_age=lap, degradation_rate=rate, corrected_pace_loss=round(0.04 * lap, 3),
                            useful_laps_q50=max(6.0, round(27 - 1.15 * lap, 1)), cliff_probability_5_laps=round(min(0.41, 0.02 * lap), 3), state_regime=('overheating' if lap >= 15 else 'normal')))
    history_ref = write_sidecar_json(dict(event_id='2026_Monza', driver='NOR', n=len(history), records=history), HERE / 'sidecars' / 'live_state_history_monza_nor.json', PROTO,
                                     description='per-lap LiveTyreState summaries consumed so far (online-safe)')
    availability = {'lap_time': True, 'sector_times': True, 'car_telemetry': True, 'position_xy': True, 'weather': True, 'team_radio': True,
                    'tyre_pressure': False, 'tyre_surface_temp': False, 'tyre_carcass_temp': False, 'tread_depth': False}
    posterior = dict(lap=17, timestamp=ts(17), compound='MEDIUM', tyre_age=17, state_regime='overheating', corrected_pace_loss=0.68, degradation_rate=0.0397,
                     thermal_stress_index=0.71, performance_wear_index=0.58, useful_laps_q10=6.0, useful_laps_q50=8.0, useful_laps_q90=11.0,
                     cliff_probability_3_laps=0.18, cliff_probability_5_laps=0.41, trend_vs_pre_race=0.31, confidence=0.74, sensor_mode='PUBLIC PROXY', support_status='IN SUPPORT',
                     sensor_availability=availability, source_latency=2.8, missing_channels=sorted(k for k, v in availability.items() if not v), quality_status='OK',
                     confidence_effect=CONFIDENCE_EFFECT_PUBLIC, team_sensor=None)
    rejoin = dict(basis='observed_gap_structure', position_now=4, projected_rejoin_position=6, gap_ahead_s=3.1, gap_behind_s=8.4, cars_within_pit_loss=2, traffic_density='light',
                  note='rival strategy responses are not simulated')
    recommendations = [
        dict(rank=1, lap=17, issued_at=ts(17, 3.0), action='PIT', pit_window=[24, 25], target_compound='MEDIUM', target_set=dict(set_id='M3', compound='MEDIUM', status='new', age_laps=0),
             expected_gain_median=3.8, expected_gain_q10=-1.2, expected_gain_q90=7.9, probability_of_gain=0.76, rejoin_context=rejoin,
             reasons=['posterior degradation 0.0397 s/lap per lap is 31% above the pre-race forecast', 'two clean laps outside the forecast band', 'driver reported worsening rear traction on lap 15'],
             constraints=['two dry compounds already satisfied after this stop', 'one new MEDIUM set remaining'], changed_since_last_update=True,
             change_reason='two clean laps exceeded the forecast band; driver reported worsening rear traction (lap 15)'),
        dict(rank=2, lap=17, issued_at=ts(17, 3.0), action='EXTEND', pit_window=[27, 28], target_compound='HARD', target_set=dict(set_id='H2', compound='HARD', status='new', age_laps=0),
             expected_gain_median=-1.1, expected_gain_q10=-5.6, expected_gain_q90=2.3, probability_of_gain=0.38, rejoin_context=rejoin,
             reasons=['the pre-race plan; still viable if the next two laps return inside the band'], constraints=['cliff probability within 5 laps is 0.41'], changed_since_last_update=False, change_reason=None),
    ]
    feedback = [dict(feedback_id='fb-0001', timestamp=ts(15, 40.0), lap=15, axle='rear', corner_phase='traction', symptom='lack_of_grip', severity=3, trend='worsening', driver_confidence=0.8,
                     source='team_radio', raw_message='Rears are going, no traction out of the second Lesmo', engineer_confirmed=True)]
    live = dict(meta=meta('live_predictor: Monza 2026 replay fixture, NOR, lap 17', cutoff), event_id='2026_Monza', driver='NOR', session='R', source='replay', data_cutoff=cutoff, lap=17, n_laps=53,
                uses_future_data=False, uses_post_race_reference=False, feedback_enabled=True,
                prior=dict(forecast_hash=fh, event_id='2026_Monza', driver='NOR', compound='MEDIUM', degradation_rate=monza_medium.prediction, band90=list(monza_medium.band90),
                           useful_laps_q10=20.0, useful_laps_q50=27.0, useful_laps_q90=33.0, planned_plan='M-H', planned_pit_window=[25, 29],
                           basis='pre-race forecast for Monza MEDIUM (' + monza_medium.basis + '), frozen before the race'),
                posterior=posterior, recommendations=recommendations, driver_feedback=feedback, state_history=history_ref, recommendation_history=None)

    # ghost strategy + counterfactual: historical audit of NOR at Monza with the stop moved from lap 19 to lap 23
    post_race = ts(53, 600.0)
    summary = dict(elapsed_delta_median_s=-2.4, elapsed_delta_q10_s=-5.1, elapsed_delta_q90_s=1.3, probability_of_gain=0.71, oracle_regret_median_s=3.9,
                   estimated_finish_position_median=None, estimated_finish_position_q10=None, estimated_finish_position_q90=None)
    deltas = [dict(lap=lap, delta_s=round((-0.12 * (lap - 19) if 19 <= lap < 23 else (0.35 if lap == 23 else -0.0665)) if lap >= 19 else 0.0, 4)) for lap in range(1, 54)]
    deltas_ref = write_sidecar_json(dict(scenario_id='monza2026_nor_stop19_to_23_tyre_only', n=len(deltas), records=deltas), HERE / 'sidecars' / 'cf_monza_nor_lap_deltas.json', PROTO,
                                    description='per-lap counterfactual minus actual lap time (s), model-implied')
    replay = [dict(lap=lap, actual_elapsed_s=round(LAP_S * lap + (21.0 if lap >= 19 else 0.0), 1), ghost_elapsed_s=round(LAP_S * lap + (21.0 if lap >= 23 else 0.0) + sum(d['delta_s'] for d in deltas[:lap]), 1)) for lap in range(1, 54)]
    replay_ref = write_sidecar_json(dict(event_id='2026_Monza', driver='NOR', n=len(replay), records=replay), HERE / 'sidecars' / 'ghost_replay_monza_nor.json', PROTO,
                                    description='actual vs ghost elapsed time per lap for the Race Twin scrubber')
    scenario = dict(scenario_id='monza2026_nor_stop19_to_23_tyre_only', schema_version=SCHEMA_VERSION, event_id='2026_Monza', driver_id='NOR', simulation_mode='tyre_only',
                    availability_mode='PUBLIC PROXY', forecast_hash=fh, model_hash=MODEL_HASH, split_id='development_pool', data_cutoff=post_race, generated_at=GENERATED_AT, git_sha=GIT_SHA,
                    intervention=dict(lap=23, from_compound='MEDIUM', to_compound='HARD', set_status='new', pit_stop=True),
                    actual_plan=dict(label='M-H', stints=[dict(compound='MEDIUM', laps=19, set_status='new'), dict(compound='HARD', laps=34, set_status='new')], pit_laps=[19], n_laps=53),
                    counterfactual_plan=dict(label='M-H', stints=[dict(compound='MEDIUM', laps=23, set_status='new'), dict(compound='HARD', laps=30, set_status='new')], pit_laps=[23], n_laps=53),
                    summary=summary, assumptions=dict(rivals_follow_observed_trajectories=True, rival_strategy_response='none', safety_car_mode='fixed_observed_schedule', driver_baseline_preserved=True),
                    claim_scope=CLAIM_SCOPE_BY_MODE['tyre_only'], track_position_simulated=False, rival_interactions_simulated=False, traffic_mode='paired_replay', safety_car_schedule='observed_fixed',
                    assets={'lap_deltas': deltas_ref}, validation=dict(identity_test='pass', future_leakage_test='pass', target_driver_excluded=True, sealed_holdout=False),
                    warnings=['rivals keep their observed strategy', 'SC/VSC periods are fixed as observed; the period list is not enumerated in this fixture'])
    ghost = dict(meta=meta('ghost_strategy: Monza 2026 historical audit fixture, NOR', post_race), mode='historical_audit', event='Monza', event_id='2026_Monza', driver='NOR',
                 weather_context='actual_historical', forecast_snapshot_hash=fh,
                 race_reference=dict(kind='race-derived pace-loss reference', by_compound={'SOFT': 0.0251, 'MEDIUM': 0.0281, 'HARD': 0.0228}, by_compound_se={'SOFT': 0.0139, 'MEDIUM': 0.0031, 'HARD': 0.0031},
                                     n_laps_used=471, n_stints_used=20, target_driver_excluded=True, source='race fit with the target driver excluded (fixture values; v1 all-driver fit: '
                                     + ', '.join(f"{c} {monza_obs[c]['obs']}" for c in ('SOFT', 'MEDIUM', 'HARD')) + ')'),
                 counterfactual=dict(scenario_id=scenario['scenario_id'], simulation_mode='tyre_only', summary=summary),
                 generalisation_status=dict(track_seen_during_training=True, driver_seen_during_training=True, weather_in_training_range=True, compound_support=True, season_support=True,
                                            circuit_generalisation='seen', overall_support_status='IN SUPPORT', abstention_reason=None),
                 model_implied=True, live_estimator_disabled=True, claim_scope=CLAIM_SCOPE_BY_MODE['tyre_only'], evidence_grade='observed_outcome_audit', ghost_replay=replay_ref)

    missingness = {'lap_time': 0.0, 'sector_times': 0.0, 'car_speed': 0.0, 'throttle': 0.0, 'brake': 0.0, 'gear': 0.0, 'drs': 0.0, 'position_xy': 0.031, 'gap_to_car_ahead': 0.031,
                   'tyre_demand_index': 0.0, 'compound_and_stint': 0.0, 'track_status': 0.0, 'track_temp': 0.0}
    rates = {'car_speed': 7.5, 'throttle': 7.5, 'brake': 7.5, 'gear': 7.5, 'drs': 7.5, 'position_xy': 3.7}
    lock = dict(schema_version=SCHEMA_VERSION, shared=shared, pre_race_forecast=forecast.model_dump(mode='json', by_alias=True), validation=validation, live_predictor=live,
                ghost_strategy=ghost, counterfactuals=[scenario],
                input_availability=build_input_availability(meta('input_availability: public feed table (fixture)', cutoff), '2026_Monza', public_channels(missingness, rates)),
                driver_profile=build_driver_profile(meta('driver_profile stub', v1_at)),
                extensions={'workstream_3': {'ghost_scorecard': {'status': 'pending', 'note': 'scorecards live here until Workstream 1 promotes them to a stable block'}},
                            'workstream_8': {'regime_model': 'regime-switching state-space v0', 'process_noise': 0.004}})
    return LockV2.model_validate(lock).model_dump(mode='json', by_alias=True)


# ---------------------------------------------------------------- mini race

TRACK_LENGTH_M, TRACK_RADIUS_M = 1500.0, 120.0
STRAIGHT_M = (TRACK_LENGTH_M - 2 * math.pi * TRACK_RADIUS_M) / 2
DRIVERS = [dict(driver='ALP', base_s=45.0, plan=[('SOFT', 6), ('MEDIUM', 8)]), dict(driver='BRV', base_s=45.3, plan=[('MEDIUM', 8), ('HARD', 6)]), dict(driver='CHR', base_s=45.6, plan=[('SOFT', 5), ('HARD', 9)])]
OFFSET_S = {'SOFT': 0.0, 'MEDIUM': 0.4, 'HARD': 0.9}
DEG_S = {'SOFT': 0.12, 'MEDIUM': 0.06, 'HARD': 0.03}
FUEL_S_PER_LAP, PIT_IN_S, PIT_OUT_S, GRID_START_S = 0.033, 18.0, 8.0, 4.0
N_LAPS, HZ = 14, 4


def track_xy(s: float) -> tuple[float, float]:
    """Stadium loop, counter-clockwise, start/finish at (0, 0) heading +x."""
    s = s % TRACK_LENGTH_M
    a, r = STRAIGHT_M, TRACK_RADIUS_M
    if s < a:
        return s, 0.0
    s -= a
    if s < math.pi * r:
        th = -math.pi / 2 + s / r
        return a + r * math.cos(th), r + r * math.sin(th)
    s -= math.pi * r
    if s < a:
        return a - s, 2 * r
    s -= a
    th = math.pi / 2 + s / r
    return r * math.cos(th), r + r * math.sin(th)


def build_mini_race() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    rng = np.random.RandomState(2026)
    rows, traces = [], []
    for d in DRIVERS:
        t = 0.0
        lap = 0
        stint_no = 0
        for compound, n in d['plan']:
            stint_no += 1
            for age in range(1, n + 1):
                lap += 1
                first_of_stint, last_of_stint = age == 1, age == n
                pit_out = first_of_stint and stint_no > 1
                pit_in = last_of_stint and stint_no < len(d['plan'])
                lap_s = d['base_s'] + OFFSET_S[compound] + DEG_S[compound] * (age - 1) - FUEL_S_PER_LAP * (lap - 1) + rng.normal(0, 0.08)
                lap_s += (GRID_START_S if lap == 1 else 0.0) + (PIT_IN_S if pit_in else 0.0) + (PIT_OUT_S if pit_out else 0.0)
                lap_s = round(float(lap_s), 3)
                s1 = round(lap_s * (0.33 + rng.normal(0, 0.004)), 3)
                s2 = round(lap_s * (0.35 + rng.normal(0, 0.004)), 3)
                s3 = round(lap_s - s1 - s2, 3)
                energy = float(rng.normal(38.0, 0.6)) * (0.75 if (pit_in or pit_out or lap == 1) else 1.0)
                e_lat = energy * float(rng.uniform(0.58, 0.62))
                rows.append(dict(event='Mini', session='R', Driver=d['driver'], LapNumber=lap, Stint=float(stint_no), Compound=compound, TyreLife=float(age), FreshTyre=True,
                                 lap_s=lap_s, s1=(np.nan if lap == 1 else s1), s2=s2, s3=(round(lap_s - s2, 3) if lap == 1 else s3), t_min=round(t / 60.0, 6), TrackStatus=1,
                                 IsAccurate=not (pit_in or pit_out or lap == 1), pit_in=pit_in, pit_out=pit_out, deleted=False, energy_MJ=round(energy, 4), e_lat=round(e_lat, 4),
                                 e_long=round(energy - e_lat, 4), traffic=round(float(rng.uniform(0.0, 0.25)), 4), full_throttle=round(float(rng.uniform(0.55, 0.65)), 4),
                                 n_tel=int(round(lap_s * 7.6)), pos_distinct=int(round(lap_s * 3.8)), stale_share=round(float(rng.uniform(0.05, 0.15)), 4), track_temp=40.0, rain=False))
                t += lap_s
    laps = pd.DataFrame(rows, columns=FEAT_COLUMNS)
    # 4 Hz trace on one global 0.25 s grid per driver: constant speed within each lap, consistent with the lap times above
    for drv, g in laps.groupby('Driver', sort=False):
        starts = (g.t_min.values * 60.0)
        durations = g.lap_s.values
        t_end = float(starts[-1] + durations[-1])
        for k in range(int(math.ceil(t_end * HZ))):
            tt = k / HZ
            i = int(np.searchsorted(starts, tt, side='right') - 1)
            x, y = track_xy((tt - starts[i]) / durations[i] * TRACK_LENGTH_M)
            traces.append((drv, round(tt, 2), round(x, 2), round(y, 2)))
    positions = pd.DataFrame(traces, columns=['Driver', 'SessionTime_s', 'X', 'Y'])
    manifest = dict(event='Mini', session='R', n_laps=N_LAPS, drivers=[d['driver'] for d in DRIVERS], sample_rate_hz=HZ, seed=2026,
                    plans={d['driver']: [dict(compound=c, laps=n) for c, n in d['plan']] for d in DRIVERS},
                    pit_laps={d['driver']: d['plan'][0][1] for d in DRIVERS},
                    lap_time_model=dict(base_s={d['driver']: d['base_s'] for d in DRIVERS}, compound_offset_s=OFFSET_S, degradation_s_per_lap=DEG_S, fuel_s_per_lap=FUEL_S_PER_LAP,
                                        pit_in_s=PIT_IN_S, pit_out_s=PIT_OUT_S, grid_start_s=GRID_START_S, noise_sd_s=0.08),
                    track=dict(shape='stadium', direction='counter-clockwise', length_m=TRACK_LENGTH_M, straight_m=round(STRAIGHT_M, 3), radius_m=TRACK_RADIUS_M,
                               start_finish_xy=[0.0, 0.0], note='samples on a global 0.25 s grid from t=0; constant speed within each lap; the car is at (0,0) at each lap start time in Mini_R.csv (t_min * 60), so the first sample at or after a lap start lies within one sample of travel of the line'),
                    files=dict(laps='Mini_R.csv', positions='Mini_positions.csv'), columns=dict(laps=FEAT_COLUMNS, positions=['Driver', 'SessionTime_s', 'X', 'Y']))
    return laps, positions, manifest


# ---------------------------------------------------------------- golden race

def build_golden() -> dict[str, Any] | None:
    files = {s: PROTO / 'feat' / f'Monza_{s}.csv' for s in ('FP1', 'FP2', 'FP3', 'Q', 'R')}
    if not all(p.exists() for p in files.values()):
        return None
    header = files['R'].open('r', encoding='utf-8').readline().rstrip('\n')
    out = {}
    for s, p in files.items():
        with p.open('rb') as f:
            n_rows = sum(1 for _ in f) - 1
        out[s] = dict(path=f'feat/Monza_{s}.csv', sha256=sha256_file(p), bytes=p.stat().st_size, rows=n_rows, format='csv')
    return dict(golden='monza_2026', event='Monza', season=SEASON, event_id='2026_Monza', path_root='proto', hash_of='file bytes (sha256)',
                columns=header.split(','), header_sha256=sha256_text(header), files=out,
                note='feat/ is gitignored: tests skip the byte-hash check when the files are absent and always check the column layout against fixtures/mini_race')


def main() -> int:
    lock = build_lock()
    atomic_write_json(HERE / 'lock_v2_fixture.json', lock)
    print(f"fixture: forecast_hash {lock['shared']['forecast_hash']}, blocks {[k for k, v in lock.items() if v not in (None, [], {})]}")
    laps, positions, manifest = build_mini_race()
    mini = HERE / 'mini_race'
    mini.mkdir(exist_ok=True)
    atomic_write_text(mini / 'Mini_R.csv', laps.to_csv(index=False))
    atomic_write_text(mini / 'Mini_positions.csv', positions.to_csv(index=False))
    manifest['sha256'] = {name: sha256_file(mini / name) for name in ('Mini_R.csv', 'Mini_positions.csv')}
    atomic_write_json(mini / 'manifest.json', manifest)
    print(f'mini race: {len(laps)} laps, {len(positions)} position samples, pit laps {manifest["pit_laps"]}')
    golden = build_golden()
    if golden:
        atomic_write_json(HERE / 'golden_race.json', golden)
        print('golden:', {s: f['sha256'][:12] for s, f in golden['files'].items()})
    else:
        print('golden: feat/Monza_*.csv not found, golden_race.json left untouched')
    return 0


if __name__ == '__main__':
    sys.exit(main())
