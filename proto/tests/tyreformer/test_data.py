"""Orb TyreFormer data contract: sealed weekends refused, inputs causal, lap rules identical to the live estimator."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROTO = Path(__file__).resolve().parents[2]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from tyreformer import data as D  # noqa: E402


def test_sealed_weekends_are_refused():
    sealed = D.sealed_ids()
    assert sealed, 'the sealed manifest must list weekends'
    listed = {D.race_id(s, e) for s, e in D.weekends()}
    assert not (listed & sealed)
    rid = sorted(sealed)[0]
    season, event = rid.split('_', 1)
    with pytest.raises(PermissionError):
        D.load_session(int(season), event, 'R')
    with pytest.raises(PermissionError):
        D.build_session(int(season), event, 'R', None, {}, D.circuits(), df=D.load_session(2026, 'Monza', 'R'))


def test_development_cache_holds_no_sealed_weekend():
    p = D.CACHE / 'samples_dev.meta.parquet'
    if not p.exists():
        pytest.skip('development samples not built')
    import pandas as pd
    rids = set(pd.read_parquet(p, columns=['race_id'])['race_id'])
    assert not (rids & D.sealed_ids())


def test_inputs_never_depend_on_future_laps():
    """Cut the race at a moment in time (every lap completed after it is removed, for every car): the inputs of every
    origin completed before the cut are unchanged. A cut by lap number would not be causal: lapped cars complete lap k
    after the leaders have completed lap k+1."""
    full = D.load_session(2026, 'Monza', 'R')
    n_laps = int(full['LapNumber'].max())
    t_end = full['t_min'] * 60.0 + full['lap_s']
    t_cut = float(t_end[full['LapNumber'] == 30].median())
    trunc = full[t_end <= t_cut].reset_index(drop=True)
    vocab = D.circuits(extra=('Madrid',))
    A = D.build_session(2026, 'Monza', 'R', None, {}, vocab, df=full, n_laps=n_laps)
    B = D.build_session(2026, 'Monza', 'R', None, {}, vocab, df=trunc, n_laps=n_laps)
    ka = A.meta[['driver', 'lap']].astype(str).agg('|'.join, axis=1).tolist()
    kb = {k: i for i, k in enumerate(B.meta[['driver', 'lap']].astype(str).agg('|'.join, axis=1))}
    ia = [i for i, k in enumerate(ka) if k in kb]
    ib = [kb[ka[i]] for i in ia]
    assert len(ia) > 200
    assert np.array_equal(A.tokens[ia], B.tokens[ib])
    assert np.array_equal(A.tok_mask[ia], B.tok_mask[ib])
    assert np.array_equal(A.context[ia], B.context[ib])
    assert np.allclose(A.anchor[ia], B.anchor[ib])


def test_clean_rule_and_cliff_labels_match_the_live_estimator():
    from live.session import LiveSession
    df = D.annotate(D.load_session(2026, 'Monza', 'R'))
    for drv in ('NOR', 'LEC'):
        res = list(LiveSession.open('Monza', drv, feedback_enabled=False).run())
        g = df[df['Driver'] == drv].set_index('LapNumber')
        for r in res:
            assert bool(g.loc[r.lap, 'kept']) == bool(r.state.laps[-1].kept), (drv, r.lap)
            assert int(g.loc[r.lap, 'n_obs']) == int(r.state.n_obs), (drv, r.lap)
    S = D.build_session(2026, 'Monza', 'R', None, {}, D.circuits())
    # out/live/PREFIX_EVAL.md, Monza: 35 realised cliffs within 5 laps over 630 scored laps
    assert int(S.cliff_mask[:, 1].sum()) == 630
    assert int(S.cliff[S.cliff_mask[:, 1], 1].sum()) == 35
