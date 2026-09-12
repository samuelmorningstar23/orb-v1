"""Orb v1 live intelligence (roadmap v5 tasks 0.8, 0.10, 0.12 and the live-prefix evaluation).

Estimator of record for Phase 0: 'linear-Gaussian with fixed regime rules'. Nothing in this package reads a lap beyond the
lap being produced, a race-derived reference, a validation `obs` field or any Ghost Strategy output; `tests/live` asserts it.
Import with proto/ on sys.path: `from live.estimator import LiveTyreStateEstimator`.
"""
ESTIMATOR_LABEL = 'linear-Gaussian with fixed regime rules'
MODEL_VERSION = 'live_estimator_lg_v0.1'
