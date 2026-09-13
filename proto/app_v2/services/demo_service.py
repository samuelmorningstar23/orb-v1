"""Read-only adapters for the guided demo. No fixture predictions or scenario generation."""
from dataclasses import dataclass
import math
from app_v2.services import counterfactual_repository as CF, live_bridge as LB, replay_service as RS
from app_v2.components import race_twin as RT


@dataclass(frozen=True)
class Case:
    key: str
    label: str
    event: str
    driver: str
    lap: int
    lesson: str


CASES = (
    Case('monza_nor', 'Norris · Monza', 'Monza', 'NOR', 24, 'Start here: learn the prediction, then replay one prepared tyre change.'),
    Case('monza_ver', 'Verstappen · Monza', 'Monza', 'VER', 24, 'Compare earlier and later stops, and try different replacement tyres.'),
    Case('austria_ver', 'Verstappen · Austria', 'Austria', 'VER', 32, 'Try the same questions at a different circuit.'),
)


def scenarios(case, source=CF.RACE_REFERENCE):
    return sorted((s for s in CF.scenarios_for(case.event, case.driver, source)
                   if s.mode == 'tyre_only' and s.set_status == 'new'
                   and str(s.validation.get('identity_test', '')).lower() == 'pass'
                   and str(s.validation.get('future_leakage_test', '')).lower() == 'pass'
                   and not s.validation.get('sealed_holdout')
                   and (source != CF.RACE_REFERENCE or s.validation.get('target_driver_excluded') is True)),
                  key=lambda s: (s.lap, s.to_compound, s.scenario_id))


def available_cases(lock):
    return [c for c in CASES if lock.event_meta(c.event).get('completed')
            and RT.assets_status(c.event)['status'] == 'ok' and scenarios(c)]


def live_snapshot(lock, case, lap):
    cursor = RS.ReplayCursor(case.event, case.driver, lock.n_laps(case.event))
    cursor.seek(max(cursor.first_lap, min(int(lap), cursor.last_lap)))
    reason = RS.prediction_unavailable_reason(cursor)
    if reason:
        return None, reason
    vm = LB.build(lock, case.event, case.driver, cursor, 'recorded replay')
    if not getattr(vm, 'orb_live', None):
        return None, 'The live estimator is unavailable. The demo will not substitute a prediction.'
    return vm, ''


def scenario_problem(sc, lock):
    if sc is None:
        return 'No prepared simulation exists for this selection.'
    if sc.forecast_hash != lock.forecast_hash:
        return 'This simulation was built from a different forecast. Its result is withheld.'
    verified = CF.verify_assets(sc)
    if not verified or any(v['status'] != 'verified' for v in verified.values()):
        return 'This simulation is being updated or its files do not match. Choose another prepared example.'
    values = (sc.finish_delta_s, sc.q10, sc.q90, sc.probability_of_gain)
    if any(v is None or not math.isfinite(v) for v in values):
        return 'This simulation has an incomplete result.'
    return ''


def finish_reading(sc):
    delta = sc.finish_delta_s
    if abs(delta) < .05:
        headline = 'About the same finish time'
    else:
        headline = f'{abs(delta):.1f} s {"later" if delta > 0 else "sooner"}'
    uncertainty = ('The range includes both a gain and a loss; this is an uncertain trade-off.'
                   if sc.q10 <= 0 <= sc.q90 else 'This is a modelled range, not a guaranteed race result.')
    return headline, uncertainty


def exact_replay(sc):
    """No first-driver/scenario fallback; never animate a superseded simulation."""
    if sc.is_pre_race or RT.assets_status(sc.event)['status'] != 'ok':
        return None
    frames, track, pitlane = RT.load_assets(sc.event, sc.driver, scenario_id=sc.scenario_id)
    if frames is None:
        return None
    if any(frames.meta.get(k) != v for k, v in
           (('event', sc.event), ('driver', sc.driver), ('scenario_id', sc.scenario_id))):
        return None
    delta = frames.arrays.get('time_delta_s', [])
    if not len(delta) or not math.isfinite(float(delta[-1])) or abs(float(delta[-1]) - sc.finish_delta_s) > 1.0:
        return None
    stamped = frames.meta.get('finish_delta_s')
    if stamped is not None and abs(float(stamped) - sc.finish_delta_s) > 1.0:
        return None
    return frames, track, pitlane


def action_title(action):
    name = {'PIT_NOW': 'Pit now', 'STAY_OUT': 'Stay out', 'EXTEND': 'Extend the stint', 'PIT': 'Plan a pit stop'}.get(action['action'], action['action'].replace('_', ' ').title())
    w = action.get('pit_window')
    if w:
        name += f' · lap {w[0]}' if w[0] == w[1] else f' · laps {w[0]}–{w[1]}'
    if action.get('target_compound'):
        name += f" · new {action['target_compound'].lower()} tyres"
    return name
