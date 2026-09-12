"""StrategyOptimizer: ranked actions with ordered quantiles, constraints, change reasons, rejoin context, contract validation."""
import pytest

from decision.optimizer import StrategyOptimizer, RaceContext, CompetitorContext, rejoin_context, NOT_AVAILABLE, MIN_STINT
from live.estimator import LiveTyreStateEstimator
from live.lapfeed import FieldCar
from schemas.lock_v2 import LiveRecommendation
from live_helpers import mk_row, run_rows


def _state(priors, rows):
    return run_rows(LiveTyreStateEstimator(), rows, priors)[-1]


def test_ranked_actions_are_ordered_and_valid(priors, clean_rows):
    st = _state(priors, clean_rows[:15])
    opt = StrategyOptimizer()
    rc = RaceContext('Synthetic', priors.n_laps, 15, priors, '2026-09-06T15:20:00', ['MEDIUM'], 0, plan=priors.plan)
    ra = opt.recommend(st, None, rc, None)
    assert ra.actions and [a['rank'] for a in ra.actions] == list(range(1, len(ra.actions) + 1))
    meds = [a['expected_gain_median'] for a in ra.actions]
    assert meds == sorted(meds, reverse=True)
    for a in ra.actions:
        m = LiveRecommendation.model_validate(a)
        assert m.expected_gain_q10 <= m.expected_gain_median <= m.expected_gain_q90
        assert 0.0 <= m.probability_of_gain <= 1.0
        if m.action in ('PIT', 'PIT_NOW', 'EXTEND'):
            assert m.pit_window and m.target_compound and m.target_set and m.target_set.compound == m.target_compound
            assert m.pit_window[0] >= 15 and priors.n_laps - m.pit_window[1] >= MIN_STINT
        assert m.rejoin_context.note == NOT_AVAILABLE
        assert any('minimum stint' in c for c in m.constraints) and any('two-compound' in c or 'two dry compounds' in c for c in m.constraints)
        assert any('posterior degradation' in r for r in m.reasons)
    # only one compound used so far: STAY_OUT is illegal
    assert all(a['action'] != 'STAY_OUT' for a in ra.actions)
    assert ra.actions[0]['changed_since_last_update'] is False and ra.baseline['plan'] == 'M-H'


def test_stay_out_legal_after_two_compounds_and_change_reason(priors, clean_rows):
    st = _state(priors, clean_rows[:15])
    opt = StrategyOptimizer()
    rc = RaceContext('Synthetic', priors.n_laps, 15, priors, '2026-09-06T15:20:00', ['SOFT', 'MEDIUM'], 1, plan=priors.plan)
    ra = opt.recommend(st, None, rc, None)
    assert any(a['action'] == 'STAY_OUT' for a in ra.actions)
    # a second call with the same state and the same call: no change flagged
    ra2 = opt.recommend(st, None, RaceContext('Synthetic', priors.n_laps, 16, priors, '2026-09-06T15:21:30', ['SOFT', 'MEDIUM'], 1, plan=priors.plan), None, previous=ra)
    top, top2 = ra.top, ra2.top
    if top['action'] == top2['action'] and top.get('target_compound') == top2.get('target_compound'):
        assert top2['changed_since_last_update'] is False
    # force a change: a very different posterior (fast degradation) moves the call, and the reason names the observation
    fast = [mk_row(k, k, 90.0 + 0.25 * k + 0.03 * 70 * (1 - (k - 1) / 50)) for k in range(1, 17)]
    st_fast = _state(priors, fast)
    ra3 = opt.recommend(st_fast, None, RaceContext('Synthetic', priors.n_laps, 16, priors, '2026-09-06T15:21:30', ['SOFT', 'MEDIUM'], 1, plan=priors.plan), None, previous=ra)
    if ra3.top['changed_since_last_update']:
        assert ra3.top['change_reason'] and 'moved from' in ra3.top['change_reason'] and ('band exceedance' in ra3.top['change_reason'] or 'clean lap' in ra3.top['change_reason'] or 'regime' in ra3.top['change_reason'])
    LiveRecommendation.model_validate(ra3.top)


def test_pit_now_is_the_same_call_across_laps(priors, clean_rows):
    """'pit now' at lap k and 'pit now' at lap k+1 must not register as a change."""
    fast = [mk_row(k, k, 90.0 + 0.30 * k + 0.03 * 70 * (1 - (k - 1) / 50)) for k in range(1, 21)]
    states = run_rows(LiveTyreStateEstimator(), fast, priors)
    opt = StrategyOptimizer()
    prev, changes = None, 0
    for st in states[9:]:
        ra = opt.recommend(st, None, RaceContext('Synthetic', priors.n_laps, st.lap, priors, '2026-09-06T15:20:00', ['SOFT', 'MEDIUM'], 1, plan=priors.plan), None, previous=prev)
        if prev is not None and ra.top['action'] == prev.top['action'] == 'PIT_NOW' and ra.top['target_compound'] == prev.top['target_compound']:
            assert ra.top['changed_since_last_update'] is False
        changes += int(ra.top['changed_since_last_update'])
        prev = ra
    assert changes <= 3


def test_rejoin_context_from_field_snapshot():
    cars = [FieldCar('AAA', 20, 1000.0, 90.0, 1000.0, False), FieldCar('SYN', 20, 1003.0, 90.0, 1003.0, False), FieldCar('BBB', 20, 1010.0, 90.0, 1010.0, False),
            FieldCar('CCC', 19, 1000.0, 91.0, 1091.0, True)]
    rj = rejoin_context(CompetitorContext('SYN', cars, 21.0, 20))
    assert rj['position_now'] == 2 and rj['gap_ahead_s'] == pytest.approx(3.0) and rj['gap_behind_s'] == pytest.approx(7.0)
    assert rj['cars_within_pit_loss'] == 1 and rj['projected_rejoin_position'] == 3 and rj['basis'] == 'observed_gap_structure' and 'projected' in rj['note']
    assert rejoin_context(None)['note'] == NOT_AVAILABLE


def test_two_stop_and_extend_candidates_exist(priors, clean_rows):
    st = _state(priors, clean_rows[:10])
    ra = StrategyOptimizer().recommend(st, None, RaceContext('Synthetic', priors.n_laps, 10, priors, '2026-09-06T15:15:00', ['MEDIUM'], 0, plan=priors.plan), None)
    labels = [a['reasons'][0] for a in ra.actions]
    assert any(l.startswith('convert to two-stop') for l in labels) and any(a['action'] == 'EXTEND' for a in ra.actions)
    assert any(a['action'] == 'PIT_NOW' for a in ra.actions)          # the board always shows what boxing now would cost
    assert not any(a['action'] == 'STAY_OUT' for a in ra.actions)     # one compound used: stay out is illegal
