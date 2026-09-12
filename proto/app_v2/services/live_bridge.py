"""Bridge to Workstream 8's live adapter (proto/live/viewmodel.py::build_live_vm) for the Live Predictor path.

- Same signature as view_models.build_live; returns a LiveVM whose `.orb_live` carries the 7.1 tyre-state record, the
  7.2 ranked recommendations, regime, widening, feedback log and projection.
- The live path never renders a race-derived reference: `forecast.observed / observed_se / err / n_race` are stripped here.
- When the live package is absent the labelled placeholder view model is returned (`vm.live_source == 'PLACEHOLDER'`).
"""
from __future__ import annotations
import dataclasses
from pathlib import Path
from typing import Optional
from app_v2.services import paths as P
from app_v2.services import asset_repository as A
from app_v2.services import view_models as VM

try:
    from live import viewmodel as _LV
    from live import ESTIMATOR_LABEL, MODEL_VERSION
    AVAILABLE, IMPORT_ERROR = True, ''
except Exception as e:  # pragma: no cover - the placeholder path
    _LV = None; ESTIMATOR_LABEL, MODEL_VERSION = 'PLACEHOLDER', 'none'; AVAILABLE, IMPORT_ERROR = False, repr(e)

CLIFF_LABEL = 'model-implied rate proxy (no cliff mechanism in the linear model)'
PREFIX_EVAL = P.OUT_DIR / 'live' / 'prefix_eval.json'
PREFIX_MD = P.OUT_DIR / 'live' / 'PREFIX_EVAL.md'
POST_RACE_FIELDS = dict(observed=None, observed_se=None, err=None, n_race=None)


def _strip_post_race(vm):
    """Live Predictor may only see what existed at the current timestamp: no race-derived reference on this path."""
    vm.forecast = dataclasses.replace(vm.forecast, **POST_RACE_FIELDS)
    return vm


def _tidy_kpis(kpis: list) -> list:
    for k in kpis:
        unit = getattr(k, 'unit', '')
        if unit and k.value.endswith(' ' + unit):
            k.value = k.value[: -len(unit)].rstrip()
        if k.label == 'CLIFF RISK' and CLIFF_LABEL not in k.sub:
            k.sub = f'{k.sub} · {CLIFF_LABEL}'
    return kpis


def build(lock, event: str, driver: str, cursor, latency_text: str = '—'):
    """LiveVM with `.orb_live` (dict or None) and `.live_source` ('live/estimator + decision/optimizer' | 'PLACEHOLDER')."""
    if AVAILABLE:
        vm = _LV.build_live_vm(lock, event, driver, cursor, latency_text)
        vm.live_source = 'live/estimator + decision/optimizer'
        vm.kpis = _tidy_kpis(vm.kpis)
    else:
        vm = VM.build_live(lock, event, driver, cursor, latency_text)
        vm.orb_live = None
        vm.live_source = 'PLACEHOLDER'
    return _strip_post_race(vm)


def estimator_label_short(vm) -> str:
    return ESTIMATOR_LABEL if getattr(vm, 'orb_live', None) else 'PLACEHOLDER'


def support_status(vm) -> str:
    orb = getattr(vm, 'orb_live', None)
    if orb and orb.get('tyre_state', {}).get('support_status'):
        return orb['tyre_state']['support_status']
    return vm.support.overall_support_status


def latency_text(vm, fallback: str) -> str:
    orb = getattr(vm, 'orb_live', None)
    lat = (orb or {}).get('tyre_state', {}).get('source_latency')
    return f'{lat:.1f} s (7.1 source_latency)' if isinstance(lat, (int, float)) else fallback


def tyre_state_rows(ts: dict) -> list[tuple[str, str]]:
    """The 7.1 live_tyre_state record, formatted for a key/value panel (public mode: no tread, no wear percentages)."""
    f3 = lambda v: '—' if v is None else f'{v:+.3f}'
    f2 = lambda v: '—' if v is None else f'{v:.2f}'
    pc = lambda v: '—' if v is None else f'{100 * v:.0f}%'
    avail = ts.get('sensor_availability') or {}
    n_ok = sum(1 for v in avail.values() if v)
    return [('lap / timestamp', f"{ts.get('lap')} · {ts.get('timestamp', '—')}"), ('compound / age', f"{ts.get('compound')} / {ts.get('tyre_age')}"), ('state_regime', str(ts.get('state_regime', '—'))),
            ('corrected_pace_loss', f"{ts.get('corrected_pace_loss', 0):+.2f} s"), ('degradation_rate', f"{f3(ts.get('degradation_rate'))} s/lap"), ('thermal_stress_index', f2(ts.get('thermal_stress_index'))),
            ('performance_wear_index', f2(ts.get('performance_wear_index'))), ('useful_laps q10/q50/q90', f"{ts.get('useful_laps_q10', 0):.0f} / {ts.get('useful_laps_q50', 0):.0f} / {ts.get('useful_laps_q90', 0):.0f}"),
            ('cliff_probability 3 / 5 laps', f"{pc(ts.get('cliff_probability_3_laps'))} / {pc(ts.get('cliff_probability_5_laps'))} · {CLIFF_LABEL}"), ('trend_vs_pre_race', f"{ts.get('trend_vs_pre_race', 0):+.2f}x"),
            ('confidence', f2(ts.get('confidence'))), ('sensor_mode', str(ts.get('sensor_mode', '—'))), ('support_status', str(ts.get('support_status', '—'))), ('sensor_availability', f"{n_ok} of {len(avail)} channels · " + ', '.join(k for k, v in avail.items() if v)),
            ('source_latency', f"{ts.get('source_latency', '—')} s"), ('missing_channels', ', '.join(ts.get('missing_channels') or []) or 'none'), ('quality_status', str(ts.get('quality_status', '—'))),
            ('confidence_effect', str(ts.get('confidence_effect', '—')))]


def recommendation_rows(r: dict) -> list[tuple[str, str]]:
    """The 7.2 live_recommendation record, formatted."""
    w = r.get('pit_window'); rj = r.get('rejoin_context') or {}; ts = r.get('target_set') or {}
    g = lambda v: '—' if v is None else f'{v:.1f} s'
    rejoin = (f"P{rj.get('position_now')} now → ~P{rj.get('projected_rejoin_position')}, gap ahead {g(rj.get('gap_ahead_s'))}, behind {g(rj.get('gap_behind_s'))}, {rj.get('cars_within_pit_loss')} cars within pit loss, traffic {rj.get('traffic_density')} ({(rj.get('basis') or '').replace('_', ' ')})"
              if rj.get('position_now') is not None else rj.get('note', 'not available'))
    return [('action', str(r.get('action', '—')).replace('_', ' ')), ('pit_window', f'laps {w[0]}-{w[1]}' if w and w[0] != w[1] else (f'lap {w[0]}' if w else '—')), ('target_compound', str(r.get('target_compound') or '—')),
            ('target_set', f"{ts.get('set_id')} ({ts.get('status')}, age {ts.get('age_laps')})" if ts else '—'), ('expected_gain median / q10 / q90', f"{r.get('expected_gain_median', 0):+.1f} / {r.get('expected_gain_q10', 0):+.1f} / {r.get('expected_gain_q90', 0):+.1f} s"),
            ('probability_of_gain', f"{100 * r.get('probability_of_gain', 0):.0f}%"), ('rejoin_context', rejoin), ('constraints', ' · '.join(r.get('constraints') or []) or '—'),
            ('changed_since_last_update', 'yes' if r.get('changed_since_last_update') else 'no'), ('change_reason', str(r.get('change_reason') or '—'))]


def prefix_eval() -> tuple[Optional[dict], A.Asset]:
    return A.load_json_asset(PREFIX_EVAL)


def prefix_reading() -> str:
    """Workstream 8's own reading of the table (the paragraph after 'Reading the table:' in PREFIX_EVAL.md)."""
    if not PREFIX_MD.exists():
        return ''
    text = PREFIX_MD.read_text()
    key = 'Reading the table:'
    if key not in text:
        return ''
    para = text.split(key, 1)[1].strip().split('\n\n', 1)[0]
    return ' '.join(para.split())


def prefix_asset_md() -> A.Asset:
    return A.resolve(PREFIX_MD)
