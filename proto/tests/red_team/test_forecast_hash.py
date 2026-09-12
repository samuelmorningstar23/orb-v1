"""One frozen forecast across modes (roadmap v5 task 0.0; Phase 0 acceptance 3 'both use the same pre-race forecast hash';
stop-the-line condition 'forecast hashes differ between modes'; 0.13 acceptance 'blocking_issues.json empty').

Live (live.priors), Ghost (counterfactual.provider), the dashboard (LockView) and a fresh recomputation over the
pre_race_forecast block must all report lock_v2.shared.forecast_hash; the scenario the Ghost page shows must carry it;
the published Madrid forecast must equal the lock's numbers and, while Madrid is prospective, point at the current lock."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rt_helpers import PROTO

POST_RACE_KEYS = {'obs', 'obs_se', 'obs_push', 'n_race', 'ratio', 'z', 'err_naive', 'err_clean', 'err_cs', 'err_push', 'cost_under_truth_vs_best_s', 'best_under_truth', 'observed', 'observed_se', 'race'}
FORECAST = PROTO / 'out' / 'forecast_Madrid_2026.json'
REPUBLISH = '../.venv/bin/python build_forecast.py Madrid  (lead; run after the last pre-race refresh, before the race)'


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _keys(o, path='$'):
    if isinstance(o, dict):
        for k, v in o.items():
            yield f'{path}.{k}', k
            yield from _keys(v, f'{path}.{k}')
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _keys(v, f'{path}[{i}]')


def test_one_forecast_hash_across_modes(lock_v2, lock_view):
    from schemas.lock_v2 import compute_forecast_hash
    from live.priors import load_priors
    from counterfactual.provider import ProviderA
    h = lock_v2['shared']['forecast_hash']
    assert h.startswith('sha256:') and len(h) == 71
    seen = {
        'recomputed over pre_race_forecast': compute_forecast_hash(lock_v2['pre_race_forecast']),
        'live: load_priors(Monza).forecast_hash': load_priors('Monza').forecast_hash,
        'live: load_priors(Madrid).forecast_hash': load_priors('Madrid').forecast_hash,
        'ghost: ProviderA().forecast_hash': ProviderA().forecast_hash,
        'dashboard: LockView.forecast_hash': 'sha256:' + lock_view.forecast_hash,
    }
    bad = {k: v for k, v in seen.items() if v != h}
    assert not bad, f'forecast hash differs between modes: lock_v2 says {h[:22]}..., but ' + ', '.join(f'{k} = {str(v)[:22]}...' for k, v in bad.items())


def test_provider_curves_are_pre_race_and_carry_the_hash(lock_v2, race_csv):
    from counterfactual.provider import ProviderA, assert_pre_race
    h = lock_v2['shared']['forecast_hash']
    p = ProviderA()
    for c in p.available_compounds('Monza'):
        cv = p.predict_curve('Monza', 'NOR', c, None, (1, 2))
        assert_pre_race(cv)
        assert cv.provenance.get('forecast_hash') == h, (c, cv.provenance)


def test_hash_check_rejects_a_tampered_block(lock_v2):
    """Self-test: one changed prediction changes the hash; a changed meta field does not."""
    import copy
    from schemas.lock_v2 import compute_forecast_hash
    h = lock_v2['shared']['forecast_hash']
    b = copy.deepcopy(lock_v2['pre_race_forecast'])
    ev = next(iter(b['events'].values()))
    comp = next(iter(ev['compounds'].values()))
    comp['prediction'] = float(comp['prediction']) + 1e-6
    assert compute_forecast_hash(b) != h, 'a tampered prediction must change the forecast hash'
    b2 = copy.deepcopy(lock_v2['pre_race_forecast'])
    b2['meta']['generated_at'] = '1999-01-01T00:00:00'
    assert compute_forecast_hash(b2) == h, 'top-level meta is provenance and must not change the hash'


@pytest.mark.xfail(strict=True, reason='Workstream 1 / lead: pre_race_forecast.events.*.data_cutoff is stamped with the lock generated_at, so the hash changes at '
                                       'every refresh with identical numbers (proven 21:03 vs 18:11); exclude data_cutoff from the hashed content or set it to the real session cutoff')
def test_forecast_hash_is_content_only(lock_v2):
    import copy
    from schemas.lock_v2 import compute_forecast_hash
    b = copy.deepcopy(lock_v2['pre_race_forecast'])
    for ev in b['events'].values():
        ev['data_cutoff'] = '2000-01-01T00:00:00'
    assert compute_forecast_hash(b) == lock_v2['shared']['forecast_hash'], 'the forecast hash depends on a build timestamp, not only on the forecast content'


def test_ghost_page_default_scenario_carries_the_lock_hash(lock_v2, lock_v1_path):
    from app_v2.services import counterfactual_repository as CF
    sc = CF.default_scenario('Monza')
    if sc is None:
        pytest.skip('no Workstream 2 scenario under out/counterfactual')
    h = lock_v2['shared']['forecast_hash'].replace('sha256:', '')
    assert sc.forecast_hash == h and sc.pre_race_forecast_hash == h, (
        f'the scenario the Ghost page shows by default ({sc.scenario_id}, generated {sc.generated_at}) records forecast {sc.forecast_hash[:8]} but the lock is {h[:8]}. '
        f'Its numbers still reproduce under the current lock (identity_checks: on-disk scenario reproduces), so this is a provenance pointer, not a content change; '
        f'regenerate it after every lock rebuild (Workstream 2: ../.venv/bin/python -m counterfactual.run --event {sc.event} --driver {sc.driver} --lap {sc.lap} --to {sc.to_compound} '
        f'--set {sc.set_status.upper()} --mode {sc.mode}) or make the hash content-only (Workstream 1: data_cutoff out of the hashed block)')


def test_published_madrid_forecast_matches_the_lock(lock_v1_path, lock_v2_path, lock_v2):
    if not FORECAST.exists():
        pytest.skip('out/forecast_Madrid_2026.json not published yet')
    fc = json.loads(FORECAST.read_text(encoding='utf-8'))
    lock = json.loads(lock_v1_path.read_text(encoding='utf-8'))
    live = lock['live']['Madrid']
    strat = lock['strategy']['Madrid']
    by_comp = {c['compound']: c for c in live['compounds']}
    for c in fc['compounds']:
        L = by_comp[c['compound']]
        assert c['prediction_s_per_lap'] == round(L['prediction'], 4) and c['band90'] == [round(b, 4) for b in L['band90']], (c, L)
        assert (c['issued'], c['gate'], c['basis'], c['clean_practice_laps']) == (L['issued'], L['gate'], L['basis'], L['n_prac']), c
    assert fc['sessions_used'] == live['meta']['sessions'] and 'R' not in fc['sessions_used'] and 'Q' not in fc['sessions_used'][:0]
    plan = strat['views']['Orb v1']
    assert fc['strategy']['central']['plan'] == plan['plan'] and fc['strategy']['central']['stints'] == plan['stints']
    assert fc['strategy']['offsets_s'] == strat['offsets'] and fc['strategy']['pit_loss_s'] == strat['pit_loss'] and fc['strategy']['race_laps'] == strat['n_laps']
    leaked = sorted({k for _, k in _keys(fc) if k in POST_RACE_KEYS})
    assert not leaked, f'post-race keys inside the published pre-race forecast: {leaked}'
    sidecar = (PROTO / 'out' / 'forecast_Madrid_2026.sha256').read_text().split()
    assert sidecar and sidecar[0] == _sha(FORECAST), 'forecast JSON no longer matches its .sha256 sidecar (edited after publication?)'
    prospective = lock_v2['pre_race_forecast']['events']['Madrid']['status'] == 'prospective' and not lock['events']['Madrid'].get('completed')
    if prospective:
        h = lock_v2['shared']['forecast_hash']
        stale = []
        if fc['lock_v2_forecast_hash'] != h:
            stale.append(f"lock_v2_forecast_hash {fc['lock_v2_forecast_hash'][7:15]} vs lock {h[7:15]}")
        if fc['lock_sha256'] != _sha(lock_v1_path):
            stale.append('lock_sha256 is not the current out/lock.json')
        if fc['lock_v2_sha256'] != _sha(lock_v2_path):
            stale.append('lock_v2_sha256 is not the current out/lock_v2.json')
        assert not stale, f'published forecast points at an earlier lock build ({"; ".join(stale)}); lock generated {lock["generated_at"]}, forecast issued {fc["issued_at"]} from lock {fc["lock_generated_at"]}. Re-publish: {REPUBLISH}'


def test_blocking_issues_empty():
    """Roadmap 0.13 acceptance: blocking_issues.json empty (resolved entries keep their evidence)."""
    p = PROTO / 'evaluation' / 'red_team' / 'blocking_issues.json'
    assert p.exists(), 'evaluation/red_team/blocking_issues.json missing'
    d = json.loads(p.read_text(encoding='utf-8'))
    assert d.get('issues') == [], f"open blocking issues: {[i.get('id') for i in d.get('issues', [])]}"
    for r in d.get('resolved', []):
        assert r.get('id') and r.get('evidence') and r.get('guarded_by'), f'resolved entry without evidence or a guarding test: {r.get("id")}'
