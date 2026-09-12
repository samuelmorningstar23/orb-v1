"""LiveSession: the lap-by-lap loop shared by the replay CLI, the prefix evaluation and the view-model adapter.

For each completed lap k of a driver: read only that lap's row (LapFeed.row), update the estimator, then re-run the
optimiser; driver feedback matched by lap (app_v2/state/feedback_events.jsonl rows for this event and driver, or an
explicit list) is handed to the estimator on the lap it names. Every produced record carries data_cutoff = the
completion time of lap k. The loop never looks at lap k+1 (LapFeed enforces it) and never opens a Ghost Strategy
output or a race-derived reference (live/priors.py strips them).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Optional

from live.clock import SessionClock
from live.estimator import LiveContext, LiveTyreStateEstimator, TyreStateDistribution
from live.lapfeed import LapFeed
from live.priors import EventPriors, load_priors, support_status
from decision.optimizer import CompetitorContext, RaceContext, RankedActions, StrategyOptimizer

PROTO = Path(__file__).resolve().parents[1]
FEEDBACK_LOG = PROTO / 'app_v2' / 'state' / 'feedback_events.jsonl'


def read_feedback(path: Optional[Path], event: str, driver: str) -> list[dict]:
    p = path or FEEDBACK_LOG
    if not p.exists():
        return []
    out = []
    with open(p, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get('event') == event and (r.get('driver') in (driver, None, '')):
                out.append(r)
    return out


@dataclass
class LapResult:
    lap: int
    state: TyreStateDistribution
    tyre_state: dict[str, Any]            # contract 7.1 record
    ranked: RankedActions
    feedback: list[dict]                  # feedback events consumed on this lap


@dataclass
class LiveSession:
    event: str
    driver: str
    feed: LapFeed
    priors: EventPriors
    clock: SessionClock
    estimator: LiveTyreStateEstimator = field(default_factory=LiveTyreStateEstimator)
    optimizer: StrategyOptimizer = field(default_factory=StrategyOptimizer)
    feedback_enabled: bool = True
    feedback_events: list[dict] = field(default_factory=list)
    available_sets: Optional[list[dict]] = None
    out_of_support: bool = False
    source_latency_s: float = 3.0

    @classmethod
    def open(cls, event: str, driver: str, feedback_path: Optional[Path] = None, feedback_events: Optional[list[dict]] = None, feedback_enabled: bool = True,
             lock_v2: Optional[Path] = None, race_csv: Optional[Path] = None, **kw) -> 'LiveSession':
        priors = load_priors(event, lock_v2=lock_v2) if lock_v2 else load_priors(event)
        feed = LapFeed(event, path=race_csv, n_laps=priors.n_laps or None)
        clock = SessionClock(event, feed.t_ref_s)
        fb = list(feedback_events) if feedback_events is not None else read_feedback(feedback_path, event, driver)
        return cls(event, driver, feed, priors, clock, feedback_enabled=feedback_enabled, feedback_events=fb, **kw)

    @property
    def n_laps(self) -> int:
        return int(self.priors.n_laps or self.feed.n_laps)

    def laps(self) -> list[int]:
        return self.feed.laps_of(self.driver)

    def context_for(self, k: int, row: dict) -> LiveContext:
        ss, sr = support_status(self.priors, str(row['Compound']), row.get('track_temp'), bool(row.get('rain', False)))
        oos = self.out_of_support or ss.startswith('OUT OF SUPPORT')
        return LiveContext(self.event, self.driver, int(k), self.n_laps, self.priors, self.clock, 0.0, oos, ss, sr, self.source_latency_s, self.feedback_enabled)

    def step(self, state: Optional[TyreStateDistribution], k: int, previous: Optional[RankedActions] = None) -> Optional[LapResult]:
        row = self.feed.row(self.driver, k)
        if row is None:
            return None
        ctx = self.context_for(k, row)
        fb = [e for e in self.feedback_events if int(e.get('lap', -1)) == int(k)] if self.feedback_enabled else []
        state = self.estimator.update(state, row, ctx, driver_feedback=fb or None)
        rec = self.estimator.to_live_tyre_state(state, ctx)
        rc = RaceContext(self.event, self.n_laps, int(k), self.priors, state.timestamp, list(state.compounds_used), int(state.stops_done), plan=self.priors.plan)
        cc = CompetitorContext(self.driver, self.feed.field_at(self.driver, k), self.priors.pit_loss, int(k))
        ranked = self.optimizer.recommend(state, self.available_sets, rc, cc, previous=previous)
        return LapResult(int(k), state, rec, ranked, fb)

    def run(self, through_lap: Optional[int] = None) -> Iterator[LapResult]:
        state, prev = None, None
        for k in self.laps():
            if through_lap is not None and k > through_lap:
                break
            res = self.step(state, k, prev)
            if res is None:
                continue
            state, prev = res.state, res.ranked
            yield res

    def state_at(self, lap: int) -> Optional[LapResult]:
        last = None
        for res in self.run(through_lap=lap):
            last = res
        return last


__all__ = ['LiveSession', 'LapResult', 'read_feedback', 'FEEDBACK_LOG']
