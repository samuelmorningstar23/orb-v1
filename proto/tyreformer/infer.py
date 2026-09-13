"""Live inference for Orb TyreFormer: the ensemble forecast for one car at the end of one lap, from the laps completed so far.

    live = TyreFormerLive('production')            # or 'temporal' (both halves trained on 2023-2025 only)
    fc = live.forecast(season=2026, event='Monza', laps=feed_so_far, driver='NOR', n_laps=53, priors=priors_record)

`laps` is every row of the session completed at or before the moment of the forecast (all cars: the field signal needs
them). A row completed after the requesting car's lap is refused with FutureDataError. The forecast is the same ensemble
the evaluation scores: transformer quantiles re-centred on the blended median (out/tyreformer/ensemble.json weights),
conformal 90 % bands, the 3- and 5-lap sums, and the cliff probabilities, plus the data cutoff and the model identity.
"""
from __future__ import annotations

import json
import pickle
from typing import Any, Optional

import pandas as pd

from tyreformer import OUT
from tyreformer.blend import apply as blend_apply
from tyreformer.data import build_session, compound_numbers, H, SampleSet
from tyreformer.model import QUANTILES
from tyreformer.train import load_models, predict, predictions_frame, MODELS

QTAGS = [f'q{int(round(q * 100)):02d}' for q in QUANTILES]


class FutureDataError(AssertionError):
    """A lap completed after the forecast moment was offered."""


def gbm_frame(S: SampleSet, blob: dict) -> pd.DataFrame:
    from tyreformer.gbm import features
    X = features(S)
    out = S.meta[['race_id', 'season', 'event', 'session', 'driver', 'lap']].copy()
    for h, m in blob['models'].items():
        out[f'h{h}_q50'] = S.anchor + m.predict(X)
    return out


class TyreFormerLive:
    def __init__(self, variant: str = 'production'):
        self.variant = variant
        self.models, self.blob = load_models(f'{variant}_final')
        self.trees = pickle.loads((MODELS / f'gbm_{variant}_final.pkl').read_bytes())
        self.ensemble = json.loads((OUT / 'ensemble.json').read_text(encoding='utf-8'))
        self.margins: dict[str, float] = dict(self.ensemble['conformal_margins'])
        self.vocab = list(self.blob['circuits'])
        self.cnums = compound_numbers()

    def batch(self, S: SampleSet) -> pd.DataFrame:
        """Ensemble forecasts for every origin of a sample set (the replay path; identical arithmetic to forecast())."""
        tf = predictions_frame(S, predict(self.models, S), f'tyreformer_{self.variant}')
        return blend_apply(tf, gbm_frame(S, self.trees), self.ensemble['weights'], self.ensemble['cum_shift'])

    def forecast(self, season: int, event: str, laps: pd.DataFrame, driver: str, n_laps: int, priors: Optional[dict[str, Any]] = None,
                 session: str = 'R', lap: Optional[int] = None) -> Optional[dict[str, Any]]:
        df = laps.copy()
        mine = df[df['Driver'] == driver]
        if mine.empty:
            return None
        k = int(lap if lap is not None else mine['LapNumber'].max())
        row = mine[mine['LapNumber'] == k]
        if row.empty:
            return None
        cutoff = float(row['t_min'].iloc[0]) * 60.0 + float(row['lap_s'].iloc[0])
        t_end = df['t_min'].astype(float) * 60.0 + df['lap_s'].astype(float)
        if bool((t_end > cutoff + 1e-6).any()) or bool((mine['LapNumber'] > k).any()):
            raise FutureDataError(f'laps completed after {driver} lap {k} were offered to the live forecast')
        S = build_session(season, event, session, priors, self.cnums, self.vocab, df=df, n_laps=n_laps)
        if S is None:
            return None
        m = (S.meta['driver'] == driver).to_numpy() & (S.meta['lap'] == k).to_numpy()
        if not m.any():
            return dict(driver=driver, lap=k, available=False, reason='no clean lap in the current stint yet: the model needs one anchor lap')
        S = S.subset(m)
        r = self.batch(S).iloc[0]
        a = float(S.anchor[0])
        out = dict(driver=driver, lap=k, available=True, model=f'Orb TyreFormer ensemble ({self.variant})', data_cutoff_session_s=cutoff, anchor=a,
                   compound=str(S.meta['compound'].iloc[0]), tyre_age=float(S.meta['age'].iloc[0]), horizons=[])
        for h in range(1, H + 1):
            c = self.margins.get(f'h{h}', 0.0)
            qs = {t: float(r[f'h{h}_{t}']) for t in QTAGS}
            out['horizons'].append(dict(h=h, lap=k + h, median=qs['q50'], lo90=qs['q05'] - c, hi90=qs['q95'] + c, **qs))
        for hh in (3, 5):
            c = self.margins.get(f'cum{hh}', 0.0)
            out[f'cum{hh}'] = dict(median=float(r[f'cum{hh}_q50']), lo90=float(r[f'cum{hh}_q05']) - c, hi90=float(r[f'cum{hh}_q95']) + c)
        out['cliff_probability_3_laps'] = float(r['cliff_p3'])
        out['cliff_probability_5_laps'] = float(r['cliff_p5'])
        out['uses_future_data'] = False
        return out


__all__ = ['TyreFormerLive', 'FutureDataError', 'gbm_frame']
