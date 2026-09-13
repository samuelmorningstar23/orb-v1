"""Read-only adapter for the dashboard: Orb TyreFormer replay forecasts and headline numbers, plot-ready.

The dashboard never imports torch or sklearn through this module: it reads the exported replay forecasts
(out/tyreformer/live/2026_<event>.parquet, sha256-checked against manifest.json) and the evaluation JSON files.
Every forecast row for lap k was produced from data through lap k only (tyreformer.infer refuses anything later), by a
model that never trained on that race (2026 deployment protocol: 2023-2025 plus the earlier 2026 races).

    available_events() -> ['Australia', ...]
    stint_forecast(event, driver, lap) -> dict | None     # None when that origin has no forecast (no clean anchor lap yet)
    headline() -> dict                                    # quotable numbers with their labels, for a Validation panel
"""
from __future__ import annotations

import functools
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd

PROTO = Path(__file__).resolve().parents[1]
OUT = PROTO / 'out' / 'tyreformer'
LIVE = OUT / 'live'
LABEL = 'Orb TyreFormer (learned second opinion)'


class IntegrityError(RuntimeError):
    """An exported forecast file does not match the manifest."""


@functools.lru_cache(maxsize=1)
def manifest() -> dict[str, Any]:
    p = LIVE / 'manifest.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def available_events() -> list[str]:
    return sorted(n[len('2026_'):-len('.parquet')] for n in manifest().get('files', {}))


@functools.lru_cache(maxsize=16)
def _race(event: str) -> pd.DataFrame:
    name = f'2026_{event}.parquet'
    rec = manifest().get('files', {}).get(name)
    if rec is None:
        raise KeyError(f'no TyreFormer replay forecasts for {event}')
    p = LIVE / name
    if hashlib.sha256(p.read_bytes()).hexdigest() != rec['sha256']:
        raise IntegrityError(f'{name} does not match manifest.json')
    return pd.read_parquet(p)


def stint_forecast(event: str, driver: str, lap: int) -> Optional[dict[str, Any]]:
    try:
        df = _race(event)
    except KeyError:
        return None
    r = df[(df['driver'] == driver) & (df['lap'] == int(lap))]
    if r.empty:
        return None
    r = r.iloc[0]
    horizons = [dict(h=h, lap=int(lap) + h, median=float(r[f'h{h}_q50']), q25=float(r[f'h{h}_q25']), q75=float(r[f'h{h}_q75']),
                     lo90=float(r[f'h{h}_lo90']), hi90=float(r[f'h{h}_hi90'])) for h in range(1, 11)]
    m = manifest()
    return dict(label=LABEL, event=event, driver=driver, lap=int(lap), compound=str(r['compound']), tyre_age=float(r['age']), stint=int(r['stint']),
                clean_laps_in_stint=int(r['n_obs']), level_now=float(r['anchor']), horizons=horizons,
                cum3=dict(median=float(r['cum3_q50']), lo90=float(r['cum3_lo90']), hi90=float(r['cum3_hi90'])),
                cum5=dict(median=float(r['cum5_q50']), lo90=float(r['cum5_lo90']), hi90=float(r['cum5_hi90'])),
                cliff_probability_3_laps=float(r['cliff_p3']), cliff_probability_5_laps=float(r['cliff_p5']),
                units=m.get('units'), protocol=m.get('protocol'), uses_future_data=False)


def headline() -> dict[str, Any]:
    """The numbers a Validation panel may quote, each with the label it must carry."""
    ev = json.loads((OUT / 'evaluation.json').read_text(encoding='utf-8'))
    sealed_p = OUT / 'sealed_holdout_aggregate.json'
    sealed = json.loads(sealed_p.read_text(encoding='utf-8')) if sealed_p.exists() else None

    def pick(h: dict) -> dict[str, Any]:
        out = {}
        for k in ('next1', 'next3', 'next5', 'cum5'):
            d = h.get(k)
            if d:
                out[k] = dict(orb_v1_estimator=d['orb_v1_estimator'], tyreformer=d['tyreformer'], difference_ci90=d['difference_ci90'], n=d['n'],
                              races_tyreformer_better=d['weekends_tyreformer_better'], races=d['weekends'])
        c = h.get('cliff5')
        if c:
            out['cliff5_brier'] = dict(orb_v1_estimator=c['orb_v1_estimator_brier'], tyreformer=c['tyreformer_brier'], constant_base_rate=c['climatology_train_rate'], n=c['n'])
        return out

    res = dict(model=LABEL, units='seconds of fuel-corrected lap time; Brier score for the cliff probability',
               cv_2023_2025=dict(label='5-fold weekend-grouped cross-validation, 2023-2025, identical origins', **pick(ev['cv_2023_2025']['head_to_head'])),
               test_2026=dict(label='every 2026 race, deployment protocol (trained on 2023-2025 and earlier 2026 races only), identical origins', **pick(ev['test_2026_rolling']['head_to_head'])))
    if sealed:
        res['sealed_holdout'] = dict(label=sealed['label'], frozen_at=sealed['freeze']['frozen_at'], **pick(sealed['head_to_head']))
    return res


__all__ = ['available_events', 'stint_forecast', 'headline', 'IntegrityError', 'LABEL']
