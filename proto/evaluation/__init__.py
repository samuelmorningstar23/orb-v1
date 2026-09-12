"""Orb v1 blind evaluation (Workstream 3; roadmap v5 section 9 and task 0.1).

    forecast        pipeline.py's leave-one-weekend-out pre-race forecast on any season directory, with an explicit
                    factor pool and a leakage spy (a sealed weekend's race never enters any pool)
    hidden_stop     hidden-stop-response evaluation (pre-race curve + driver baseline vs what happened after real stops)
    regret          strategy regret: pre-race / naive / observed / default plans vs the hindsight oracle under the
                    race-derived reference ("held-out strategy replay under a post-race reference model")
    risk_coverage   abstention gate sweep: coverage (share issued) against error on issued cases and the fallback error
    scorecards      Ghost Strategy and Live Predictor scorecards (weekend-grouped bootstrap), rolling-origin 2026
    holdout/        the sealed manifest (lead-only) and the sealed-holdout evaluator (aggregate unless freeze.json)

Import with proto/ on sys.path: `from evaluation.forecast import SeasonForecaster`.
Wording rules (roadmap 9.2): race estimates are "race-derived pace-loss references"; the regret table is a
"held-out strategy replay under a post-race reference model", never "observed race time saved"; "untouched" is
reserved for the sealed holdout and the prospective race.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

PROTO = Path(__file__).resolve().parents[1]
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

HOLDOUT_DIR = PROTO / 'evaluation' / 'holdout'
MANIFEST_PATH = HOLDOUT_DIR / 'sealed_holdout_manifest.json'
MANIFEST_SHA_PATH = HOLDOUT_DIR / 'sealed_holdout_manifest.sha256'
FREEZE_PATH = HOLDOUT_DIR / 'freeze.json'
OUT_DIR = PROTO / 'out' / 'validation'
SEASON_DIRS = {2023: PROTO / 'feat2023', 2024: PROTO / 'feat2024', 2025: PROTO / 'feat2025', 2026: PROTO / 'feat'}
COMPS = ('SOFT', 'MEDIUM', 'HARD')

# 2026 calendar order of the rounds on disk (race start dates from live/clock.py RACE_START_LOCAL; Bahrain and
# Saudi Arabia 2026 do not exist in the timing data; Madrid is the live weekend and has no race file yet).
CALENDAR_2026 = ('Australia', 'China', 'Japan', 'Miami', 'Canada', 'Monaco', 'Barcelona', 'Austria', 'Britain', 'Belgium',
                 'Hungary', 'Zandvoort', 'Monza', 'Madrid')

# Circuit classes mirror evaluation/holdout/seal_holdout.py (the sealing rule); Madrid (Madring, 2026) is a
# street-type layout and is classed 'street' here. Degradation classes likewise; unknown circuits are 'medium'.
STREET = frozenset({'Monaco', 'Singapore', 'Azerbaijan', 'Miami', 'LasVegas', 'SaudiArabia', 'Australia', 'Canada', 'Madrid'})
HIGH_DEG = frozenset({'Barcelona', 'Bahrain', 'Japan', 'Britain', 'Hungary', 'Zandvoort', 'Qatar', 'Austria'})
LOW_DEG = frozenset({'Monza', 'Azerbaijan', 'LasVegas', 'SaudiArabia', 'Monaco', 'Canada', 'Miami'})


def circuit_class(event: str) -> str:
    return 'street' if event in STREET else 'permanent'


def degradation_class(event: str) -> str:
    return 'high' if event in HIGH_DEG else ('low' if event in LOW_DEG else 'medium')


def temperature_regime(track_temp: float | None) -> str:
    """Same rule as the sealing script: hot >= 40 C, cool < 30 C, mild between; unknown when missing."""
    if track_temp is None or track_temp != track_temp:
        return 'unknown'
    return 'hot' if track_temp >= 40 else ('cool' if track_temp < 30 else 'mild')


def weather_regime(track_temp: float | None, rain: bool) -> str:
    """Actual-weather regime of a race: 'wet_affected' when rain was flagged in the race feed, else the temperature regime."""
    return 'wet_affected' if rain else temperature_regime(track_temp)


def race_id(season: int, event: str) -> str:
    return f'{season}_{event}'


def git_sha(short: bool = False) -> str | None:
    try:
        out = subprocess.run(['git', 'rev-parse', '--short' if short else 'HEAD'], cwd=PROTO, capture_output=True, text=True, timeout=5)
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and sha else None
    except Exception:
        return None


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec='seconds')


__all__ = ['PROTO', 'HOLDOUT_DIR', 'MANIFEST_PATH', 'MANIFEST_SHA_PATH', 'FREEZE_PATH', 'OUT_DIR', 'SEASON_DIRS', 'COMPS', 'CALENDAR_2026',
           'STREET', 'HIGH_DEG', 'LOW_DEG', 'circuit_class', 'degradation_class', 'temperature_regime', 'weather_regime', 'race_id', 'git_sha', 'now_iso']
