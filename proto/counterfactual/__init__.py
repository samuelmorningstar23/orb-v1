"""Orb v1 counterfactual core (Workstream 2; roadmap v5 tasks 0.3 and 0.4).

    provider   TyreCurveProvider interface + ProviderA (reproduces the v1 lock curves exactly)
    racedata   race-file loading, lap flags, positions, race-derived reference slopes (post-race, target driver excludable)
    pitmodel   standardised pit event as a distribution, measured from the race with a season-pool fallback
    engine     the single-car counterfactual: Y = B + T + P + I + e, modes tyre_only / fixed_context
    run        CLI: one scenario (laps.csv + summary.json with sha256 sidecars) or a driver x lap x compound lattice

Import with proto/ on sys.path: `from counterfactual.engine import CounterfactualEngine`.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROTO = Path(__file__).resolve().parents[1]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

__all__ = ['PROTO']
