"""v1 -> v2 lock adapter (roadmap v5 task 0.2).

Reads proto/out/lock.json (v1: rules, events, validation, validation_rows, live, strategy) and writes proto/out/lock_v2.json with
shared, pre_race_forecast, validation, input_availability (sensor_mode 'PUBLIC PROXY') and the driver_profile stub; live_predictor
and ghost_strategy stay null and counterfactuals stay empty until Workstreams 8 and 2 produce them.

Rules kept here on purpose:
  * the validation numbers are copied, never recomputed (headline: mae_all_with_fallback, calibration.all_with_fallback.r)
  * pre_race_forecast carries no race outcome: obs, obs_se, err_*, ratio, z and cost-under-truth stay in validation
  * validation_rows go to a hashed sidecar (out/lock_v2_sidecars/validation_rows.json); the lock stays small
  * forecast_hash is computed over the validated block with meta removed, so re-running at another time reproduces it

Usage: python validators/adapt_v1.py [--in out/lock.json] [--out out/lock_v2.json] [--root proto] [--season 2026]
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

PROTO = Path(__file__).resolve().parents[1]
REPO = PROTO.parent
if str(PROTO) not in sys.path:
    sys.path.insert(0, str(PROTO))

from shared.lockio import atomic_write_json, content_hash, read_json, sha256_file, sidecar_ref, strip_nonfinite, write_sidecar_json  # noqa: E402
from schemas.lock_v2 import DEFAULT_UNITS, LockV2, PUBLIC_DISPLAY_RULES, PreRaceForecast, SCHEMA_VERSION, compute_forecast_hash  # noqa: E402

MODEL_VERSION = 'provider_A_clearstint_v2'
MODEL_FILES = ('model_v2.py', 'pipeline.py', 'strategy2.py')
PRACTICE = ('FP1', 'FP2', 'FP3')
SIDECAR_DIR = 'out/lock_v2_sidecars'
HOLDOUT_MANIFEST = 'evaluation/holdout/sealed_holdout_manifest.json'
BASIS_PUSH = 'push-adjusted Friday curve (degradation at constant tyre energy) × its own season factor'
CONFIDENCE_EFFECT_PUBLIC = ('PUBLIC PROXY: no tyre pressures or temperatures are observed; thermal_stress_index and performance_wear_index are '
                            'demand-based proxies from public telemetry; bands carry the public-mode widening.')


# ---------------------------------------------------------------- provenance

def git_sha(repo: Path = REPO) -> str:
    try:
        out = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=repo, capture_output=True, text=True, timeout=10)
        sha = out.stdout.strip()
        if out.returncode == 0 and re.fullmatch(r'[0-9a-f]{7,40}', sha):
            return sha
    except (OSError, subprocess.SubprocessError):
        pass
    print('warning: git sha unavailable, recording 0000000', file=sys.stderr)
    return '0000000'


def model_hash(rules: dict[str, Any], proto: Path = PROTO) -> str:
    """Hash of the v1 model: its source files plus the rule constants recorded in the lock."""
    parts: dict[str, Any] = {'rules': rules, 'model_version': MODEL_VERSION}
    for name in MODEL_FILES:
        p = proto / name
        parts[name] = sha256_file(p) if p.exists() else None
    return content_hash(parts)


def make_meta(now: str, data_cutoff: str, sha: str, mhash: str, provenance: str) -> dict[str, Any]:
    return dict(schema_version=SCHEMA_VERSION, generated_at=now, data_cutoff=data_cutoff, git_sha=sha, model_version=MODEL_VERSION,
                model_hash=mhash, provenance=provenance, units=dict(DEFAULT_UNITS))


# ---------------------------------------------------------------- pre_race_forecast

def basis_for_row(r: dict[str, Any]) -> str:
    if r['issued'] and r['k_applied']:
        return 'cleaned Friday curve × season transfer factor'
    if r['issued']:
        return 'cleaned Friday curve (weekends disagree on the factor)'
    return 'low-degradation fallback: median race degradation of the withheld cases on the other weekends (leave-one-weekend-out)'


def compound_from_live(c: dict[str, Any]) -> dict[str, Any]:
    """v1 live[ev].compounds entry -> CompoundForecast fields (already a pre-race record)."""
    return dict(compound=c['compound'], n_prac=int(c['n_prac']), naive=c.get('naive'), clean=c['clean'], clean_se=c['clean_se'], gate=c['gate'],
                issued=bool(c['issued']), factor=c['factor'], factor_applied=bool(c['factor_applied']), factor_from_n_weekends=c.get('factor_from_n_weekends'),
                prediction=c['prediction'], band90=[c['band90'][0], c['band90'][1]], basis=c['basis'], energy_trend=c.get('energy_trend'),
                push_adj=c.get('push_adj'), second_opinion=c.get('second_opinion'))


def compound_from_row(r: dict[str, Any]) -> dict[str, Any]:
    """v1 validation_rows entry -> CompoundForecast fields; every post-race column is dropped here."""
    second = None
    if not r['issued'] and r.get('pred_push') is not None:
        second = dict(prediction=r['pred_push'], factor=r['k3'], factor_applied=bool(r['k3_applied']), basis=BASIS_PUSH)
    return dict(compound=r['compound'], n_prac=int(r['n_prac']), naive=r.get('naive'), clean=r['clean'], clean_se=r['clean_se'], gate=r['gate'],
                issued=bool(r['issued']), factor=r['k'], factor_applied=bool(r['k_applied']), factor_from_n_weekends=None,
                prediction=r['pred_clearstint'], band90=[r['lo'], r['hi']], basis=basis_for_row(r), energy_trend=r.get('energy_trend'),
                push_adj=r.get('push_adj'), second_opinion=second)


def plan_from_strategy(st: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """v1 strategy[ev] -> PreRacePlan from the 'Orb v1' view; cost_under_truth / best_under_truth are post-race and stay out."""
    if not st or 'Orb v1' not in st.get('views', {}):
        return None
    v = st['views']['Orb v1']
    alts = [dict(plan=a['plan'], stops=int(a['stops']), stints=[int(x) for x in a['stints']], time_s=a['time'], delta_to_best_s=max(0.0, a['delta_to_best']))
            for a in v.get('alternatives', [])[:8]]
    return dict(plan=v['plan'], stints=[int(x) for x in v['stints']], stops=int(v['stops']), n_laps=int(st['n_laps']), pit_loss_s=st['pit_loss'],
                crossover=dict(v.get('crossover', {})), alternatives=alts, offsets_s={k: float(x) for k, x in st['offsets'].items()},
                offsets_source=dict(st.get('offsets_source', {})), band_low_plan=st['views'].get('Orb v1, band low', {}).get('plan'),
                band_high_plan=st['views'].get('Orb v1, band high', {}).get('plan'))


def event_forecast(ev: str, meta: dict[str, Any], compounds: list[dict[str, Any]], status: str, data_cutoff: str, strategy: Optional[dict[str, Any]],
                   season: int, note: Optional[str] = None) -> dict[str, Any]:
    sessions_used = [s for s in meta['sessions'] if s in PRACTICE]
    temps = [meta.get('track_temp', {}).get(s) for s in sessions_used]
    temps = [t for t in temps if t is not None]
    plan = plan_from_strategy(strategy)
    return dict(event=ev, event_id=f'{season}_{ev}', season=season, status=status, data_cutoff=data_cutoff, format=meta['format'], sessions_used=sessions_used,
                race_laps=(int(strategy['n_laps']) if strategy else None), practice_laps_clean=int(meta['practice_laps_clean']), practice_runs=int(meta['practice_runs']),
                track_temp_practice_c=(round(sum(temps) / len(temps), 2) if temps else None), rain_in_practice=any(bool(meta.get('rain', {}).get(s, False)) for s in sessions_used),
                tyre_nomination=meta.get('tyres'), compounds={c['compound']: c for c in compounds}, strategy=plan, note=note)


def build_pre_race_forecast(v1: dict[str, Any], season: int, meta: dict[str, Any]) -> dict[str, Any]:
    events: dict[str, Any] = {}
    cutoff = v1['generated_at']
    for ev, L in v1.get('live', {}).items():
        st = v1.get('strategy', {}).get(ev)
        events[ev] = event_forecast(ev, L['meta'], [compound_from_live(c) for c in L['compounds']], 'prospective', cutoff, st, season, note=(st or {}).get('note'))
    rows_by_event: dict[str, list[dict[str, Any]]] = {}
    for r in v1.get('validation_rows', []):
        rows_by_event.setdefault(r['event'], []).append(r)
    for ev, rows in rows_by_event.items():
        if ev in events:
            continue
        events[ev] = event_forecast(ev, v1['events'][ev], [compound_from_row(r) for r in rows], 'leave_one_weekend_out', cutoff, v1.get('strategy', {}).get(ev), season)
    return dict(meta=meta, events=dict(sorted(events.items())))


# ---------------------------------------------------------------- shared

def drivers_seen(events: list[str], proto: Path) -> list[str]:
    seen: set[str] = set()
    try:
        import pandas as pd
    except ImportError:
        return []
    for ev in events:
        p = proto / 'feat' / f'{ev}_R.csv'
        if p.exists():
            seen.update(str(d) for d in pd.read_csv(p, usecols=['Driver'])['Driver'].dropna().unique())
    return sorted(d for d in seen if re.fullmatch(r'[A-Z]{3}', d))


def build_support(v1: dict[str, Any], season: int, proto: Path) -> dict[str, Any]:
    completed = sorted(ev for ev, m in v1['events'].items() if m.get('completed') and not m.get('race_unusable'))
    temps = [t for ev in completed for s, t in v1['events'][ev].get('track_temp', {}).items() if s in PRACTICE and t is not None]
    rainy = sorted(f'{ev}_{s}' for ev in completed for s, flag in v1['events'][ev].get('rain', {}).items() if flag)
    weather = ['dry'] + (['rain_affected_sessions: ' + ', '.join(rainy)] if rainy else [])
    return dict(definition=('Training support is the set of completed weekends scored leave-one-weekend-out by pipeline.py. A track is seen when it has practice '
                            'and race files; weather is in range when practice was dry and track temperature lies inside the observed practice range; '
                            'compound support covers the dry slick compounds fitted in training.'),
                tracks_seen=completed, drivers_seen=drivers_seen(completed, proto), seasons_seen=[season], weather=weather, compounds=['SOFT', 'MEDIUM', 'HARD'],
                track_temp_range_c=([round(min(temps), 2), round(max(temps), 2)] if temps else None), n_training_weekends=len(completed))


def build_shared(v1: dict[str, Any], forecast: dict[str, Any], fh: str, season: int, meta: dict[str, Any], proto: Path) -> dict[str, Any]:
    live = [ev for ev, e in forecast['events'].items() if e['status'] == 'prospective']
    if live:
        ev = live[0]
        e = forecast['events'][ev]
        snap = dict(snapshot_id=f"{ev}_{'+'.join(e['sessions_used'])}_{fh[7:15]}", kind='prospective', event=ev, event_id=e['event_id'], season=season,
                    issued_at=v1['generated_at'], sessions_used=e['sessions_used'], race_laps=e['race_laps'], tyre_nomination=e['tyre_nomination'],
                    note='issued from practice sessions only; the hash is frozen before the race and both modes must reference it')
    else:
        snap = dict(snapshot_id=f'historical_only_{fh[7:15]}', kind='historical_only', event=None, event_id=None, season=season, issued_at=v1['generated_at'],
                    sessions_used=[], race_laps=None, tyre_nomination=None, note='no prospective weekend in the v1 lock')
    return dict(meta=meta, forecast_snapshot=snap, model_version=MODEL_VERSION, forecast_hash=fh, training_cutoff=v1['generated_at'], support_definition=build_support(v1, season, proto))


# ---------------------------------------------------------------- validation, input availability, driver profile

def build_validation(v1: dict[str, Any], meta: dict[str, Any], root: Path) -> dict[str, Any]:
    block = dict(meta=meta, source='pipeline.py leave-one-weekend-out scorecard, copied verbatim from v1 out/lock.json', **v1['validation'])
    rows_path = root / SIDECAR_DIR / 'validation_rows.json'
    rows = v1.get('validation_rows', [])
    payload = dict(generated_at=v1['generated_at'], n_rows=len(rows), columns=(list(rows[0].keys()) if rows else []), rows=rows)
    block['rows'] = write_sidecar_json(payload, rows_path, root, description='one record per compound-weekend incl. observed race degradation (post-race)')
    manifest = root / HOLDOUT_MANIFEST
    block['sealed_holdout'] = sidecar_ref(manifest, root, format='json', description='sealed holdout manifest; never opened before freeze.json') if manifest.exists() else None
    return block


PUBLIC_CHANNEL_TABLE: dict[str, dict[str, Any]] = {
    'lap_time': dict(source='FastF1 live timing', unit='s', visibility='public', latency_s=3.0, available=True, description='lap times; basis of corrected pace loss'),
    'sector_times': dict(source='FastF1 live timing', unit='s', visibility='public', latency_s=3.0, available=True),
    'car_speed': dict(source='FastF1 car data', unit='km/h', visibility='public', latency_s=3.0, available=True),
    'throttle': dict(source='FastF1 car data', unit='%', visibility='public', latency_s=3.0, available=True),
    'brake': dict(source='FastF1 car data', unit='bool', visibility='public', latency_s=3.0, available=True),
    'gear': dict(source='FastF1 car data', unit='gear', visibility='public', latency_s=3.0, available=True),
    'drs': dict(source='FastF1 car data', unit='state', visibility='public', latency_s=3.0, available=True),
    'position_xy': dict(source='FastF1 position data', unit='m', visibility='public', latency_s=3.0, available=True),
    'gap_to_car_ahead': dict(source='derived from position data', unit='share of lap within 60 m', visibility='public', latency_s=3.0, available=True, description='traffic proxy'),
    'tyre_demand_index': dict(source='derived from speed and accelerations (energy_MJ)', unit='MJ', visibility='public', latency_s=3.0, available=True, description='the proxy is a tyre demand index, not a wear measurement'),
    'compound_and_stint': dict(source='FastF1 live timing', unit='category', visibility='public', latency_s=3.0, available=True),
    'track_status': dict(source='FastF1 live timing', unit='code', visibility='public', latency_s=3.0, available=True),
    'pit_events': dict(source='FastF1 live timing', unit='event', visibility='public', latency_s=3.0, available=True),
    'track_temp': dict(source='FastF1 weather feed', unit='degC', visibility='public', latency_s=60.0, available=True, sample_rate_hz=1 / 60),
    'air_temp': dict(source='FastF1 weather feed', unit='degC', visibility='public', latency_s=60.0, available=True, sample_rate_hz=1 / 60),
    'rain_flag': dict(source='FastF1 weather feed', unit='bool', visibility='public', latency_s=60.0, available=True, sample_rate_hz=1 / 60),
    'team_radio': dict(source='FastF1 team radio records', unit='text', visibility='public', latency_s=None, available=False, description='public but not ingested by v1'),
    'driver_feedback_structured': dict(source='engineer entry (DriverFeedbackAdapter)', unit='event', visibility='private', latency_s=None, available=False, description='Phase 0 live slice adds it'),
    'tyre_pressure': dict(source='team sensor adapter', unit='bar', visibility='private', latency_s=None, available=False),
    'tyre_surface_temp': dict(source='team sensor adapter', unit='degC', visibility='private', latency_s=None, available=False),
    'tyre_carcass_temp': dict(source='team sensor adapter', unit='degC', visibility='private', latency_s=None, available=False),
    'tread_depth': dict(source='team sensor adapter', unit='mm', visibility='private', latency_s=None, available=False),
    'brake_temp': dict(source='team sensor adapter', unit='degC', visibility='private', latency_s=None, available=False),
}
CHANNEL_MISSINGNESS_COLUMNS = {'lap_time': ['lap_s'], 'sector_times': ['s1', 's2', 's3'], 'car_speed': ['energy_MJ'], 'throttle': ['full_throttle'], 'brake': ['energy_MJ'],
                               'gear': ['energy_MJ'], 'drs': ['energy_MJ'], 'position_xy': ['traffic'], 'gap_to_car_ahead': ['traffic'], 'tyre_demand_index': ['energy_MJ'],
                               'track_temp': ['track_temp'], 'compound_and_stint': ['Compound'], 'track_status': ['TrackStatus']}


def feed_quality(event: Optional[str], proto: Path) -> tuple[dict[str, float], dict[str, float]]:
    """(missingness per channel, sample rate per channel) measured on the event's feature files when they exist."""
    if not event:
        return {}, {}
    try:
        import pandas as pd
    except ImportError:
        return {}, {}
    files = sorted((proto / 'feat').glob(f'{event}_*.csv'))
    if not files:
        return {}, {}
    d = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    miss = {ch: round(float(d[cols].isna().any(axis=1).mean()), 4) for ch, cols in CHANNEL_MISSINGNESS_COLUMNS.items() if all(c in d.columns for c in cols)}
    rates: dict[str, float] = {}
    ok = d['lap_s'].notna() & (d['lap_s'] > 0)
    if 'n_tel' in d.columns and ok.any():
        car = round(float((d.loc[ok, 'n_tel'] / d.loc[ok, 'lap_s']).median()), 2)
        rates.update({k: car for k in ('car_speed', 'throttle', 'brake', 'gear', 'drs')})
    if 'pos_distinct' in d.columns and ok.any():
        rates['position_xy'] = round(float((d.loc[ok, 'pos_distinct'] / d.loc[ok, 'lap_s']).median()), 2)
    return miss, rates


def public_channels(missingness: Optional[dict[str, float]] = None, rates: Optional[dict[str, float]] = None) -> dict[str, dict[str, Any]]:
    missingness, rates = missingness or {}, rates or {}
    out: dict[str, dict[str, Any]] = {}
    for name, spec in PUBLIC_CHANNEL_TABLE.items():
        ch = dict(source=spec['source'], unit=spec['unit'], sample_rate_hz=spec.get('sample_rate_hz', rates.get(name)), latency_s=spec.get('latency_s'),
                  available=spec['available'], visibility=spec['visibility'], online_safe=True, missingness=missingness.get(name), quality_score=None,
                  ablation_value=None, description=spec.get('description'))
        if ch['missingness'] is not None:
            ch['quality_score'] = round(1.0 - ch['missingness'], 4)
        out[name] = ch
    return out


def build_input_availability(meta: dict[str, Any], event_id: Optional[str], channels: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return dict(meta=meta, sensor_mode='PUBLIC PROXY', event_id=event_id, channels=channels, missing_channels=sorted(k for k, c in channels.items() if not c['available']),
                confidence_effect=CONFIDENCE_EFFECT_PUBLIC, public_display_rules=list(PUBLIC_DISPLAY_RULES))


def build_driver_profile(meta: dict[str, Any]) -> dict[str, Any]:
    return dict(meta=meta, status='stub', population_prior=dict(residual_mean_s_per_lap=0.0, residual_sd_s_per_lap=None,
                                                                note='Phase 2: unseen drivers receive the population prior; no ranking of tyre management is implied'),
                drivers={}, note='Driver profiles are Phase 2 (roadmap v5 section 5); this block is a typed placeholder.')


# ---------------------------------------------------------------- main

def adapt(v1_path: Path, out_path: Path, root: Path, season: int = 2026, proto: Path = PROTO, now: Optional[str] = None) -> LockV2:
    v1 = strip_nonfinite(read_json(v1_path))
    now = now or dt.datetime.now().isoformat(timespec='seconds')
    cutoff = v1['generated_at']
    sha, mhash = git_sha(), model_hash(v1.get('rules', {}), proto)
    prov = f'validators/adapt_v1.py from {Path(v1_path).name} (v1 generated_at {cutoff})'
    meta = lambda what: make_meta(now, cutoff, sha, mhash, f'{prov}: {what}')  # noqa: E731

    forecast = build_pre_race_forecast(v1, season, meta('pre_race_forecast from live[] and validation_rows[] minus post-race columns'))
    forecast_model = PreRaceForecast.model_validate(forecast)
    fh = compute_forecast_hash(forecast_model)
    live_event = next((e for e in forecast['events'].values() if e['status'] == 'prospective'), None)
    miss, rates = feed_quality(live_event['event'] if live_event else None, proto)

    lock = dict(schema_version=SCHEMA_VERSION,
                shared=build_shared(v1, forecast, fh, season, meta('shared'), proto),
                pre_race_forecast=forecast_model.model_dump(mode='json', by_alias=True),
                validation=build_validation(v1, meta('validation copied verbatim'), root),
                live_predictor=None, ghost_strategy=None, counterfactuals=[],
                input_availability=build_input_availability(meta('input_availability: public feed table'), live_event['event_id'] if live_event else None, public_channels(miss, rates)),
                driver_profile=build_driver_profile(meta('driver_profile stub')),
                extensions={})
    model = LockV2.model_validate(lock)
    atomic_write_json(out_path, model.model_dump(mode='json', by_alias=True))
    return model


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--in', dest='src', default=str(PROTO / 'out' / 'lock.json'))
    ap.add_argument('--out', dest='dst', default=str(PROTO / 'out' / 'lock_v2.json'))
    ap.add_argument('--root', default=str(PROTO), help='lock root that sidecar paths are relative to (default: proto/)')
    ap.add_argument('--season', type=int, default=2026)
    a = ap.parse_args(argv)
    model = adapt(Path(a.src), Path(a.dst), Path(a.root), a.season)
    ev = model.pre_race_forecast.events
    print(f'wrote {a.dst}: {len(ev)} events ({sum(e.status == "prospective" for e in ev.values())} prospective), forecast_hash {model.shared.forecast_hash}')
    v = model.validation
    print(f'validation copied: mae_all_with_fallback naive {v.mae_all_with_fallback.naive:.4f} clearstint {v.mae_all_with_fallback.clearstint:.4f}, '
          f'calibration r {v.calibration.all_with_fallback.r:.3f}; rows sidecar {v.rows.path} ({v.rows.bytes} B)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
