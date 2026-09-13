"""Tests for tyreformer/baseline_kalman.py (fast: no season forecaster, one driver of one race).

Run from proto/: ../.venv/bin/python -m pytest tests/tyreformer/test_baseline_kalman.py -q -p no:cacheprovider
No __init__.py in this directory on purpose: a `tests.tyreformer` package would shadow proto/tyreformer on sys.path
(the same convention as tests/live and tests/evaluation)."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from evaluation import SEASON_DIRS                         # noqa: E402
from live.lapfeed import LapFeed                           # noqa: E402
from live.priors import Z90, CompoundPrior, EventPriors    # noqa: E402
from tyreformer import baseline_kalman as BK               # noqa: E402

MONZA_2026 = SEASON_DIRS[2026] / 'Monza_R.csv'


# ---------------------------------------------------------------- sealed weekends

def test_sealed_weekends_are_skipped_by_default(tmp_path):
    sealed = BK.sealed_ids()
    assert sealed, 'the sealed manifest lists no race ids'
    on_disk = {rid for rid in sealed if (SEASON_DIRS[int(rid.split('_', 1)[0])] / f"{rid.split('_', 1)[1]}_R.csv").exists()}
    assert on_disk, 'no sealed race file on disk to test against'
    jobs, skipped = BK.plan_jobs(BK.SEASONS)
    assert not {j['race_id'] for j in jobs} & sealed
    assert on_disk <= {s['race_id'] for s in skipped if s['status'] == 'skipped' and 'sealed' in s['skipped']}
    jobs_all, skipped_all = BK.plan_jobs(BK.SEASONS, include_sealed=True)
    assert on_disk <= {j['race_id'] for j in jobs_all if j['sealed']}
    assert not skipped_all
    # the run path itself: a sealed-only selection estimates nothing and writes no race file
    rid = sorted(on_disk)[0]
    season, event = rid.split('_', 1)
    res = BK.run(seasons=[int(season)], events=[event], workers=1, out_dir=tmp_path, quiet=True)
    assert res['entries'][rid]['status'] == 'skipped' and res['entries'][rid]['n_rows'] == 0
    assert not list(tmp_path.glob('*.parquet')) and not list(tmp_path.glob('*.csv.gz'))
    assert res['scores'] == {}


# ---------------------------------------------------------------- causality

def _synthetic_priors(n_laps: int) -> EventPriors:
    comps = {c: CompoundPrior(c, m, (m - 0.06, m + 0.06), True, 'ok', 'test', 'test') for c, m in (('SOFT', 0.08), ('MEDIUM', 0.05), ('HARD', 0.03))}
    return EventPriors('Monza', '2026_Monza', n_laps, comps, {'SOFT': 0.0, 'MEDIUM': 0.6, 'HARD': 1.2}, {}, 21.0, None, None, 'test')


@pytest.mark.skipif(not MONZA_2026.exists(), reason='2026 Monza race file not on disk')
def test_a_recorded_row_never_uses_a_future_lap(tmp_path):
    full_df = pd.read_csv(MONZA_2026)
    cut = 30
    laps = full_df.groupby('Driver')['LapNumber'].apply(set)
    stints = full_df.groupby('Driver')['Stint'].nunique()
    driver = sorted(d for d in laps.index if cut in laps[d] and max(laps[d]) >= cut + 10 and stints[d] >= 2)[0]
    n_through_cut = sum(1 for k in laps[driver] if k <= cut)
    feed = LapFeed('Monza', path=MONZA_2026)
    priors = _synthetic_priors(feed.n_laps)
    ref = BK.rows_frame(BK.run_driver(feed, priors, driver, season=2026, event='Monza'))
    assert ref['anchored'].any() and ref['error'].isna().all()

    truncated = full_df[~((full_df['Driver'] == driver) & (full_df['LapNumber'] > cut))]
    (tmp_path / 'trunc').mkdir()
    truncated.to_csv(tmp_path / 'trunc' / 'Monza_R.csv', index=False)
    perturbed = full_df.copy()
    later = (perturbed['Driver'] == driver) & (perturbed['LapNumber'] > cut)
    perturbed.loc[later, 'lap_s'] = perturbed.loc[later, 'lap_s'] + 4.0
    perturbed.loc[later, 'Compound'] = 'HARD'
    perturbed.loc[later, 'Stint'] = 9
    perturbed.loc[later, 'traffic'] = 0.0
    (tmp_path / 'pert').mkdir()
    perturbed.to_csv(tmp_path / 'pert' / 'Monza_R.csv', index=False)

    for name in ('trunc', 'pert'):
        f2 = LapFeed('Monza', path=tmp_path / name / 'Monza_R.csv')
        assert f2.n_laps == feed.n_laps
        got = BK.rows_frame(BK.run_driver(f2, priors, driver, season=2026, event='Monza'))
        assert got['lap'].max() == (cut if name == 'trunc' else ref['lap'].max())
        a = ref[ref['lap'] <= cut].reset_index(drop=True)
        b = got[got['lap'] <= cut].reset_index(drop=True)
        assert len(a) == n_through_cut and a['anchored'].any()
        pd.testing.assert_frame_equal(a, b, check_exact=True)
        if name == 'pert':      # the perturbation is real: the later laps' records do change
            assert not np.allclose(ref.loc[ref['lap'] > cut, 'y'].to_numpy(), got.loc[got['lap'] > cut, 'y'].to_numpy(), equal_nan=True)


# ---------------------------------------------------------------- default prior

def test_default_prior_for_a_race_compound_without_a_forecast_prior():
    f = lambda pred, band, issued=True: SimpleNamespace(prediction=pred, band90=band, issued=issued, gate='ok', basis='test', n_prac=50)
    fc = SimpleNamespace(compounds={'SOFT': f(0.08, [0.02, 0.14]), 'MEDIUM': f(0.04, None, False), 'HARD': f(float('nan'), [0.0, 0.1])},
                         offsets={'SOFT': 0.0, 'MEDIUM': 0.6, 'HARD': 1.2}, offsets_source={}, pool_events=['A', 'B'])
    pr, info = BK.priors_from_forecast(fc, 2024, 'Test', 57, ['MEDIUM', 'HARD'])
    assert info['prior_sources'] == {'HARD': BK.SOURCE_DEFAULT, 'MEDIUM': BK.SOURCE_DEFAULT, 'SOFT': BK.SOURCE_LOO}
    assert pr.compounds['SOFT'].mean == 0.08 and pr.compounds['SOFT'].band90 == (0.02, 0.14)
    med = float(np.median([0.08, 0.04]))
    for c in ('MEDIUM', 'HARD'):
        assert pr.compounds[c].mean == pytest.approx(med)
        assert pr.compounds[c].band90 == pytest.approx((med - 0.12, med + 0.12))
    assert pr.n_laps == 57 and pr.event_id == '2024_Test' and pr.pit_loss == 21.0 and pr.plan is None and pr.forecast_hash is None
    none_fc = SimpleNamespace(compounds={}, offsets={}, offsets_source={}, pool_events=[])
    pr2, _ = BK.priors_from_forecast(none_fc, 2024, 'Test', 57, ['SOFT'])
    assert pr2.compounds['SOFT'].mean == BK.DEFAULT_PRIOR_MEAN and set(pr2.compounds) == {'SOFT'}


# ---------------------------------------------------------------- score() on a hand-built frame

def _toy_frame() -> pd.DataFrame:
    """Driver AAA: stint 1 laps 1..9 (age = lap, lap 4 not kept), stint 2 laps 10..14 (ages 1, 2, 3, 4, 6: an age jump).
    Driver BBB: stint 1 laps 1..3, stint 2 lap 4 with age 4 (same age sequence, different stint).
    True corrected time: base + 0.1 x age. Origin k predicts base + 0.1 x (age_k + h) + c_k, so every error from k is c_k."""
    rows = []
    def add(driver, lap, stint, age, kept, anchored, n_obs, base, c, s, error=None):
        d = dict(race_id='2099_Toy', season=2099, event='Toy', driver=driver, lap=lap, stint=stint, tyre_age=age, kept=kept, anchored=anchored, n_obs=n_obs,
                 y=(base + 0.1 * age if error is None else math.nan), error=error)
        for h in BK.HORIZONS:
            d[f'pred_h{h}'] = base + 0.1 * (age + h) + c if anchored else math.nan
            d[f'sd_h{h}'] = s if anchored else math.nan
        rows.append(d)
    c = {2: 0.10, 3: -0.20, 4: 0.30, 5: -0.40, 6: 0.50, 7: -0.60, 8: 0.70, 9: -0.80, 11: 0.25, 12: -0.15, 13: 0.05, 14: -0.05}
    s = {2: 0.10, 3: 0.10, 4: 0.20, 5: 0.20, 6: 0.40, 7: 0.30, 8: 0.50, 9: 0.10, 11: 0.10, 12: 0.10, 13: 0.10, 14: 0.10}
    add('AAA', 1, 1, 1, False, False, 0, 90.0, 0.0, 0.0)
    for lap in range(2, 10):
        add('AAA', lap, 1, lap, lap != 4, True, (1 if lap == 2 else (lap - 1 if lap < 4 else lap - 2)), 90.0, c[lap], s[lap])
    add('AAA', 10, 2, 1, False, False, 0, 89.0, 0.0, 0.0)
    for lap, age, n_obs in ((11, 2, 1), (12, 3, 2), (13, 4, 3), (14, 6, 4)):
        add('AAA', lap, 2, age, True, True, n_obs, 89.0, c[lap], s[lap])
    add('BBB', 1, 1, 1, False, False, 0, 95.0, 0.0, 0.0)
    add('BBB', 2, 1, 2, True, True, 1, 95.0, 1.0, 1.0)
    add('BBB', 3, 1, 3, True, True, 2, 95.0, 2.0, 1.0)
    add('BBB', 4, 2, 4, True, True, 1, 95.0, 0.0, 1.0)
    add('CCC', 1, 1, None, False, False, 0, 90.0, 0.0, 0.0, error='KeyError: no pre-race prior for Toy INTERMEDIATE')
    df = pd.DataFrame(rows)
    df['tyre_age'] = df['tyre_age'].astype('Int64')
    return df


def test_score_on_a_two_stint_toy_frame():
    r = BK.score(_toy_frame(), horizons=(1, 3, 5))
    next1 = [0.10, 0.30, -0.40, 0.50, -0.60, 0.70, 0.25, -0.15, 1.0]          # AAA 2,4,5,6,7,8,11,12 and BBB 2
    assert r['next1_n'] == 9 and r['next1_mae'] == pytest.approx(np.mean(np.abs(next1)))
    assert r['next3_n'] == 5 and r['next3_mae'] == pytest.approx(np.mean([0.10, 0.20, 0.30, 0.40, 0.50]))   # AAA 2..6
    assert r['next5_n'] == 3 and r['next5_mae'] == pytest.approx(np.mean([0.10, 0.20, 0.30]))               # AAA 2..4
    assert r['cum3_n'] == 3 and r['cum3_mae'] == pytest.approx(np.mean([0.90, 1.20, 1.50]))                 # AAA 4, 5, 6
    assert r['cum5_n'] == 1 and r['cum5_mae'] == pytest.approx(1.50)                                        # AAA 4
    sd1 = [0.10, 0.20, 0.20, 0.40, 0.30, 0.50, 0.10, 0.10, 1.0]
    assert r['coverage90_next1_n'] == 9
    assert r['coverage90_next1'] == pytest.approx(np.mean([abs(e) <= Z90 * sd for e, sd in zip(next1, sd1)]))
    assert r['coverage90_next1'] == pytest.approx(6 / 9)
    assert r['coverage90_next3_n'] == 5 and r['coverage90_next3'] == pytest.approx(3 / 5)
    assert r['origins'] == 8 + 4 + 3                                                                        # anchored with n_obs >= 1
    # the recorded predictions are the only input: shuffling rows changes nothing
    assert BK.score(_toy_frame().sample(frac=1.0, random_state=3), horizons=(1, 3, 5)) == r
