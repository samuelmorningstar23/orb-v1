"""Orb TyreFormer: a probabilistic lap-sequence model of tyre degradation trained on the 2023 to 2026 seasons.

    data             per-lap annotation with the live estimator's causal clean rule, leave-one-out pre-race priors,
                     and forecast-origin samples (token window, context, multi-horizon targets, cliff labels)
    model            the transformer (quantile heads per horizon, cumulative heads, cliff heads)
    train            grouped-weekend training, temporal test (2023-2025 -> 2026), conformal calibration
    baseline_kalman  the real Orb v1 live estimator run over every race, for head-to-head scoring

Sealed holdout weekends (evaluation/holdout/sealed_holdout_manifest.json) never enter a training set: every loader
refuses them unless a caller passes allow_sealed=True, which only the one-shot sealed scorer does.
Import with proto/ on sys.path.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROTO = Path(__file__).resolve().parents[1]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

OUT = PROTO / 'out' / 'tyreformer'
DATA = PROTO / 'tyreformer' / 'data'
