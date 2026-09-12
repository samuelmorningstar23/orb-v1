"""View models consumed by pages. Pages never touch JSON, CSV or models; they render these records.

Every numeric field carries provenance through `source` strings: 'lock', 'lock_v2', 'FIXTURE', 'asset:<sha6>' or
'PLACEHOLDER'. Empty values are None and rendered as an em dash with the reason next to it.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from app_v2.services import paths as P
from app_v2.services import asset_repository as A
from app_v2.services import replay_service as RS
from app_v2.services import feedback_service as FS
from app_v2.services import decision_service as DS
from app_v2.services import support_service as SS
from app_v2.services.lock_repository import LockView, Forecast, PlanView

MODE_LABEL = {'landing': 'LANDING', 'live': 'LIVE PREDICTOR', 'decision': 'LIVE PREDICTOR', 'feedback': 'LIVE PREDICTOR', 'prerace': 'PRE-RACE PLAN',
              'ghost': 'GHOST STRATEGY', 'scenario': 'GHOST STRATEGY', 'generalisation': 'GHOST STRATEGY', 'validation': 'VALIDATION'}
SENSOR_MODE = 'PUBLIC PROXY'          # TEAM SENSOR arrives with the team adapter (Phase 1)


@dataclass
class HeaderVM:
    mode: str
    event: str
    season: int
    session: str
    lap: Optional[int]
    n_laps: Optional[int]
    forecast_hash6: str
    forecast_hash_source: str
    sensor_mode: str
    support_status: str
    latency_text: str
    lock_version: str
    generated_at: str

    @property
    def lap_text(self) -> str:
        if self.lap is None:
            return 'Lap —'
        return f'Lap {self.lap}/{self.n_laps}' if self.n_laps else f'Lap {self.lap}'


@dataclass
class StatusItem:
    label: str
    ok: bool
    detail: str


@dataclass
class LandingVM:
    live_status: list[StatusItem]
    ghost_status: list[StatusItem]
    lock_present: bool
    forecast_hash6: str
    live_events: list[str]
    scored_events: list[str]
    race_files: list[str]


@dataclass
class KPI:
    label: str
    value: str
    sub: str
    tone: str = 'neutral'       # neutral | live | decision | critical
    source: str = 'lock'
    unit: str = ''


@dataclass
class LiveVM:
    event: str
    driver: str
    lap: int
    n_laps: Optional[int]
    state: Optional[RS.StintState]
    prior: RS.Prior
    forecast: Forecast
    corrections: RS.Corrections
    decision: DS.Decision
    history: list[DS.Decision]
    kpis: list[KPI]
    comparable: list[dict]
    feed: dict
    feedback: list[dict]
    temp_history_lock: list[tuple[str, float]]
    temp_series: list[tuple[int, float]]
    crossover: dict
    plan: Optional[PlanView]
    support: SS.Support
    asset: A.Asset
    fixture_reco: Optional[dict]
    fixture_label: str
    evolution_applied: bool


def build_header(lock: Optional[LockView], mode: str, event: str, session: str = 'Race', lap: Optional[int] = None, n_laps: Optional[int] = None,
                 support_status: str = 'PENDING', latency_text: str = '—') -> HeaderVM:
    if lock is None:
        return HeaderVM(MODE_LABEL.get(mode, 'ORB V1'), event or '—', P.SEASON_OF_FEAT, session, lap, n_laps, '------', 'no lock', SENSOR_MODE, 'NO LOCK', latency_text, 'none', '')
    return HeaderVM(MODE_LABEL.get(mode, 'ORB V1'), event, P.SEASON_OF_FEAT, session, lap, n_laps or (lock.n_laps(event) if event else None), lock.forecast_hash[:6] or '------',
                    lock.forecast_hash_source, SENSOR_MODE, support_status, latency_text, lock.version, lock.generated_at)


def build_landing(lock: Optional[LockView]) -> LandingVM:
    race_files = A.available_race_events()
    if lock is None:
        return LandingVM([StatusItem('pre-race forecast', False, 'out/lock.json missing')], [StatusItem('lock', False, 'missing')], False, '------', [], [], race_files)
    live_events = list(lock.live)
    scored = [e for e in lock.events if e not in lock.live and lock.events[e].get('completed')]
    forecast_ok = 'Madrid' in lock.live
    live = [
        StatusItem('pre-race forecast found', forecast_ok, f"lock.live.Madrid: {len(lock.live.get('Madrid', {}).get('compounds', []))} compounds" if forecast_ok else 'lock.live has no Madrid block'),
        StatusItem('live source ready', bool(race_files), f'{len(race_files)} recorded race files for replay' if race_files else 'no feat/*_R.csv'),
        StatusItem('driver feedback enabled', FS.enabled(), str(FS.log_path().relative_to(P.PROTO_ROOT))),
        StatusItem('available sets loaded', True, 'placeholder: inventory arrives with Phase 1'),
    ]
    try:                                           # Workstream 8's live package (services/live_bridge imports view_models: import lazily)
        from app_v2.services import live_bridge as LB
        live.append(StatusItem('live estimator', LB.AVAILABLE, f'{LB.ESTIMATOR_LABEL} ({LB.MODEL_VERSION})' if LB.AVAILABLE else f'live package not importable: {LB.IMPORT_ERROR}'))
    except Exception as e:  # pragma: no cover
        live.append(StatusItem('live estimator', False, repr(e)))
    ghost_block, ghost_src = lock.ghost_block()
    try:                                           # Workstream 2 scenarios on disk, both curve sources
        from app_v2.services import counterfactual_repository as CF
        n_ref = len(CF.list_scenarios(curve_source=CF.RACE_REFERENCE)); n_pre = len(CF.list_scenarios(curve_source=CF.PRE_RACE))
        cf_ok, cf_detail = n_ref > 0, f'{n_ref} race-reference + {n_pre} pre-race-curve scenarios under out/counterfactual' + (' · lock_v2 ghost block present' if ghost_src == 'lock_v2' else '')
    except Exception as e:  # pragma: no cover
        cf_ok, cf_detail = ghost_src == 'lock_v2', repr(e)
    try:                                           # Workstream 4 Race Twin assets
        from app_v2.components import race_twin as RT
        statuses = {ev: RT.assets_status(ev).get('status') for ev in scored}
        ok_evs = [e for e, v in statuses.items() if v == 'ok']; refused = [e for e, v in statuses.items() if v == 'refused']
        rt_ok, rt_detail = bool(ok_evs), f'Race Twin player assets: {", ".join(ok_evs) or "none"}' + (f' · refused (feed degraded at source): {", ".join(refused)}' if refused else '') + ' · Plotly fallback elsewhere'
    except Exception as e:  # pragma: no cover
        rt_ok, rt_detail = False, f'canonical centreline unavailable ({type(e).__name__}); Plotly fallback active'
    try:                                           # Workstream 3 scorecards
        from app_v2.services import validation_repository as VR
        g, ga = VR.ghost_scorecard(); sb = VR.sealed_block()
        ev_ok, ev_detail = g is not None, (f"ghost_scorecard.json {ga.short_hash} generated {g.get('generated_at', '')} · {sb['status_text']}" if g else 'out/validation/ghost_scorecard.json missing')
    except Exception as e:  # pragma: no cover
        ev_ok, ev_detail = False, repr(e)
    ghost = [
        StatusItem('scored weekends in lock', bool(scored), f'{len(scored)} completed weekends, {lock.validation.get("n_compound_weekends", 0)} compound-weekends'),
        StatusItem('forecast snapshot hashed', bool(lock.forecast_hash), f'{lock.forecast_hash[:6]} ({lock.forecast_hash_source})'),
        StatusItem('counterfactual engine', cf_ok, cf_detail),
        StatusItem('geometry / player', rt_ok, rt_detail),
        StatusItem('blind evaluation scorecards', ev_ok, ev_detail),
    ]
    return LandingVM(live, ghost, True, lock.forecast_hash[:6], live_events, scored, race_files)


def corrections_for(lock: LockView, event: str) -> RS.Corrections:
    r = lock.rules; bc = lock.validation.get('band_coverage', {})
    return RS.Corrections(float(r.get('fuel_s_per_kg', 0.03)), float(r.get('fuel_prior_kg_per_lap', 1.1)), lock.evolution_for(event, 'R'), float(r.get('traffic_max', 0.3)), float(bc.get('widening_factor_median', 1.0)))


def prior_for(lock: LockView, event: str, compound: str) -> RS.Prior:
    f = lock.forecast_for(event, compound)
    return RS.Prior(compound, f.prediction, f.band90, f.source)


def suggest_driver(lock: LockView, event: str) -> Optional[str]:
    """Deterministic demo default: the driver whose longest stint has the most kept laps."""
    best, best_n = None, -1
    for drv in RS.drivers_for(event):
        stints = RS.race_stints(event, drv)
        if not stints:
            continue
        s = max(stints, key=lambda x: x['laps'])
        c = RS.ReplayCursor(event, drv, lock.n_laps(event))
        st = RS.stint_state(c.seek(s['last_lap']), prior_for(lock, event, s['compound']), corrections_for(lock, event))
        n = st.kept_laps if st else 0
        if n > best_n:
            best, best_n = drv, n
    return best


def build_live(lock: LockView, event: str, driver: str, cursor: RS.ReplayCursor, latency_text: str = '—') -> LiveVM:
    corr = corrections_for(lock, event)
    row = cursor.lap_row()
    compound = str(row['Compound']) if row is not None else (lock.compounds_for(event) or ['MEDIUM'])[0]
    prior = prior_for(lock, event, compound)
    forecast = lock.forecast_for(event, compound)
    state = RS.stint_state(cursor, prior, corr)
    prev = RS.stint_state(cursor, prior, corr, lap=cursor.lap - 1) if cursor.lap > cursor.first_lap else None
    if prev is not None and state is not None and prev.stint != state.stint:
        prev = None
    feedback = FS.for_session(event, driver, through_lap=cursor.lap)
    decision = DS.decide(lock, event, cursor.lap, state, prior, prev, feedback)
    history = DS.timeline(lock, event, cursor, lambda c: prior_for(lock, event, c or compound), corr, feedback)
    if len(history) >= 2:
        decision.changed_since_last_update = history[-1].lap == cursor.lap and history[-1].changed_since_last_update
    plan = lock.primary_plan(event)
    fx, fx_src = lock.live_predictor_block()
    fx_reco = (fx or {}).get('recommendations', [None])[0] if fx else None
    support = SS.support_for(lock, event, driver, compound)
    kpis = _live_kpis(state, prior, forecast, decision, plan, fx_reco, fx_src)
    return LiveVM(event, driver, cursor.lap, cursor.n_laps, state, prior, forecast, corr, decision, history, kpis, RS.comparable_traces(cursor, compound, corr),
                  RS.feed_quality(row), feedback, lock.track_temp_history(event), RS.track_temp_series(cursor), (plan.crossover if plan else {}), plan, support, cursor.asset,
                  fx_reco, fx_src, corr.evolution_s_per_min is not None)


def _live_kpis(state, prior: RS.Prior, forecast: Forecast, decision: DS.Decision, plan, fx_reco, fx_src) -> list[KPI]:
    from app_v2.theme.tokens import fmt
    if state is None or state.post_slope is None:
        deg = KPI('LIVE DEGRADATION', '—', 'no laps yet', 'neutral', 'PLACEHOLDER')
    else:
        pct = (state.trend_vs_prior - 1) * 100 if state.trend_vs_prior is not None else None
        sub = (f'{pct:+.0f}% vs forecast {fmt(prior.slope, "seconds_per_lap")}' if pct is not None else 'no forecast slope') + f' · {state.kept_laps} kept laps'
        tone = 'critical' if decision.status == 'ABOVE FORECAST BAND' else ('live' if state.kept_laps >= 3 else 'neutral')
        deg = KPI('LIVE DEGRADATION', fmt(state.post_slope, 'seconds_per_lap'), sub, tone, 'PLACEHOLDER', 's/lap')
    useful = KPI('USEFUL LIFE', '—', 'pending Workstream 8 LiveTyreStateEstimator', 'neutral', 'pending')
    cliff = KPI('CLIFF RISK', '—', 'pending Workstream 8 (3-lap cliff probability)', 'neutral', 'pending')
    if decision.pit_lap:
        edge = f' · band-edge plans pit {decision.band_edge_laps[1]} / {decision.band_edge_laps[0]}' if all(decision.band_edge_laps) else ''
        pit = KPI('PIT WINDOW', f'lap {decision.pit_lap}', f'lock plan {decision.plan}{edge}', 'decision' if decision.action == 'REVIEW' else 'neutral', 'lock')
    elif decision.plan:
        pit = KPI('PIT WINDOW', 'no stop', f'lock plan {decision.plan}: stay out to the flag' + (' · under review' if decision.action == 'REVIEW' else ''), 'decision' if decision.action == 'REVIEW' else 'neutral', 'lock')
    else:
        pit = KPI('PIT WINDOW', '—', 'no strategy in lock', 'neutral', 'lock')
    if decision.target_compound:
        tyre = KPI('RECOMMENDED TYRE', f'new {decision.target_compound.lower()}', 'probability of gain pending Workstream 8', 'neutral', 'lock')
    else:
        tyre = KPI('RECOMMENDED TYRE', '—', 'no further stop in plan', 'neutral', 'lock')
    return [deg, useful, cliff, pit, tyre]


# ---- Ghost Strategy -----------------------------------------------------------------------------------------------
@dataclass
class GhostVM:
    event: str
    driver: str
    compound: str
    mode: str                                 # historical_audit | scenario_explorer
    forecast: Forecast
    forecast_alt: Optional[Forecast]          # replacement compound curve (lock)
    stints: list[dict]
    n_laps: Optional[int]
    plan: Optional[PlanView]
    views: dict
    assumptions: dict
    support: SS.Support
    block: Optional[dict]
    block_source: str
    intervention_lap: int
    replacement: str
    counterfactual_delta_s: Optional[float]
    counterfactual_source: str
    counterfactual_summary: dict
    hidden_stop: Optional[dict]
    regret_s: Optional[float]
    temp_history: list[tuple[str, float]]
    scenarios: list[dict]
    scenario: str
    asset: A.Asset
    weather_context: str


SCENARIOS = (
    ('actual_historical', 'Actual historical weather', 0.0),
    ('pre_race_snapshot', 'Pre-race forecast snapshot', 0.0),
    ('cooler_dry', 'Cooler dry (-5 C track)', -5.0),
    ('baseline_dry', 'Baseline dry (season median)', None),
    ('hotter_dry', 'Hotter dry (+5 C track)', 5.0),
    ('damp', 'Damp / variable', None),
    ('wet', 'Wet', None),
)


def scenario_table(lock: LockView, event: str, driver: Optional[str], compound: str) -> list[dict]:
    race_t = (lock.event_meta(event).get('track_temp') or {}).get('R')
    lo, hi = lock.race_temp_range()
    temps = sorted(m['track_temp']['R'] for m in lock.events.values() if m.get('completed') and m.get('track_temp', {}).get('R') is not None)
    median = temps[len(temps) // 2] if temps else None
    out = []
    for key, label, delta in SCENARIOS:
        weather = 'wet' if key == 'wet' else ('damp' if key == 'damp' else 'dry')
        if key == 'baseline_dry':
            t = median
        elif delta is None or race_t is None:
            t = None
        else:
            t = race_t + delta
        s = SS.support_for(lock, event, driver, compound, scenario_temp=t, scenario_weather=weather)
        out.append(dict(key=key, label=label, track_temp=t, weather=weather, support=s.overall_support_status, reason=s.abstention_reason, available=weather == 'dry',
                        evidence=(key == 'actual_historical'), range=(lo, hi)))
    return out


def build_ghost(lock: LockView, event: str, driver: str, compound: str, mode: str, intervention_lap: int, replacement: str, scenario: str = 'actual_historical') -> GhostVM:
    forecast = lock.forecast_for(event, compound)
    alt = lock.forecast_for(event, replacement) if replacement and replacement != compound else None
    stints = RS.race_stints(event, driver)
    block, src = lock.ghost_block()
    cf_delta, cf_src, cf_summary = None, 'pending Workstream 2', {}
    if block and (block.get('counterfactual') or {}).get('summary', {}).get('elapsed_delta_median_s') is not None:
        cf_summary = dict(block['counterfactual']['summary'])
        cf_delta, cf_src = cf_summary['elapsed_delta_median_s'], src
    plan = lock.primary_plan(event); views = lock.plan_views(event)
    regret = plan.cost_under_truth_s if plan else None
    hidden = plan.best_under_truth if plan else None
    weather = 'actual historical (lock events: track temperature per session, rain flags)'
    return GhostVM(event, driver, compound, mode, forecast, alt, stints, lock.n_laps(event), plan, views, lock.strategy_assumptions(event), SS.support_for(lock, event, driver, compound),
                   block, src, intervention_lap, replacement, cf_delta, cf_src, cf_summary, hidden, regret, lock.track_temp_history(event), scenario_table(lock, event, driver, compound), scenario,
                   A.race_csv_asset(event), weather)


# ---- Generalisation scorecard ---------------------------------------------------------------------------------------
def generalisation_cells(lock: LockView) -> list[dict]:
    v = lock.validation
    seen = dict(cell='seen circuit, seen driver', status='v1 leave-one-weekend-out', mae=v.get('mae_all_with_fallback', {}).get('clearstint'), mae_naive=v.get('mae_all_with_fallback', {}).get('naive'),
                coverage=v.get('band_coverage', {}).get('calibrated_all'), n=v.get('n_compound_weekends'), source='lock.validation')
    pending = [dict(cell=c, status='pending sealed evaluation', mae=None, mae_naive=None, coverage=None, n=None, source='none') for c in
               ('unseen circuit, seen driver', 'seen circuit, held-out driver', 'hot dry', 'cool dry', 'variable', 'high degradation', 'low degradation', 'street circuit', 'permanent circuit')]
    return [seen] + pending
