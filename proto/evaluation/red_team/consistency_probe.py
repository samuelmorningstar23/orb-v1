"""Lock / dashboard consistency probe (roadmap v5 14.3 'dashboard and lock disagree').

Renders every app_v2 route with streamlit.testing.v1.AppTest (the way tests/ui/test_pages.py does) for Monza (scored),
Madrid (live forecast, no race file) and a 2026 race replay (Austria), extracts every number shown in KPI cards,
tables, captions, markdown and chart labels, and matches each against the references that route is allowed to show:

    lock            out/lock.json and out/lock_v2.json (+ out/lock_v2_sidecars, sha256 verified by validate_lock.py)
    sidecars        out/live/<event>_<driver>/ (states, recommendations, estimator trace; .sha256 verified),
                    out/counterfactual/<scenario>/ (summary, laps.csv, lap_deltas, ghost_replay; hashes in summary),
                    out/maps/<event>/meta.json (.sha256 per file), out/live/prefix_eval.json, fixtures/
    assets          feat/<event>_R.csv values for the route's event (unsigned: listed as such), out/sensitivity.json
    derived         quantities the pages form from lock numbers by stated arithmetic: pit laps from stint lengths,
                    -delta_to_best, band width / (2 x 1.6449) = prior sd, fuel prior product, traffic rule x 100,
                    race temperature +/- 5 C and its median / range, the model_v2 race fuel correction of a lap
    live_runtime    when the route's driver has no hashed out/live record, Workstream 8's deterministic run is reproduced
                    in-process and those matches are listed separately as UNHASHED (not a mismatch)

A value matches when the reference formatted to the shown decimals equals it (display precision, ui/tokens.py);
integers need an integral reference unless a unit follows. References are tried most-specific first and every match
records how many distinct reference values would have matched (ambiguity), so coincidences are visible.
Numbers inside widgets labelled PLACEHOLDER / FIXTURE / pending are allowed and listed.

    python evaluation/red_team/consistency_probe.py [--routes live_predictor,ghost_strategy] [--verbose] [--out PATH]

Exit 0: every rendered number equals the lock or a hashed sidecar (placeholders and unhashed live values listed).
Exit 1: at least one mismatch (route, widget and values in the report).   Exit 2: a route failed to render or the lock is missing.
"""
from __future__ import annotations

import argparse
import glob
import html as _html
import json
import re
import sys
import traceback
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))
from evaluation.red_team import PROTO, RT_DIR, LOCK_V1, LOCK_V2, find_numbers, numeric_leaves, now_iso, read_json, write_json  # noqa: E402

REPORT_PATH = RT_DIR / 'consistency_probe_report.json'
PLACEHOLDER_WORDS = ('PLACEHOLDER', 'FIXTURE', 'pending', 'placeholder', 'fixture')
UNIT_RE = re.compile(r'^\s*(%|s/lap|s\b|°C|C\b|laps?\b|MJ|kg|x\b|×|st\b|Hz|m\b)')
HASH_CTX_RE = re.compile(r'(sha256|hash|snapshot|Forecast|file|git)\s+([0-9a-f]{6,64})')
Z90 = 1.6448536269514722
Z_Q90 = 1.2815515655446004
FUEL_S_PER_KG, RACE_FUEL_KG = 0.03, 70.0          # model_v2.prep_race race correction (live/lapfeed.py, counterfactual/racedata.py)
LIVE_PAGES = ('live_predictor', 'decision_board', 'driver_feedback')
GHOST_PAGES = ('ghost_strategy',)

# ---- routes: page module x injected session state -----------------------------------------------------------------
ROUTES: list[tuple[str, str, dict]] = [
    ('landing/Monza', 'landing', dict(ev='Monza', drv='LIN', mode='live')),
    ('pre_race/Monza', 'pre_race', dict(ev='Monza', drv='LIN', cmp='SOFT', mode='live')),
    ('pre_race/Madrid', 'pre_race', dict(ev='Madrid', cmp='SOFT', mode='live')),
    ('live_predictor/Monza-LIN-L30', 'live_predictor', dict(ev='Monza', drv='LIN', lap=30, mode='live')),
    ('live_predictor/Monza-NOR-L30', 'live_predictor', dict(ev='Monza', drv='NOR', lap=30, mode='live')),
    ('live_predictor/Madrid', 'live_predictor', dict(ev='Madrid', mode='live')),
    ('live_predictor/Austria-NOR-L30', 'live_predictor', dict(ev='Austria', drv='NOR', lap=30, mode='live')),
    ('decision_board/Monza-LIN-L30', 'decision_board', dict(ev='Monza', drv='LIN', lap=30, mode='live')),
    ('driver_feedback/Monza-LIN', 'driver_feedback', dict(ev='Monza', drv='LIN', lap=30, mode='live')),
    ('ghost_strategy/Monza-NOR-audit', 'ghost_strategy', dict(ev='Monza', drv='NOR', mode='audit')),
    ('ghost_strategy/Monza-NOR-scenario', 'ghost_strategy', dict(ev='Monza', drv='NOR', mode='scenario', scenario='hotter_dry')),
    ('ghost_strategy/Austria-NOR-audit', 'ghost_strategy', dict(ev='Austria', drv='NOR', mode='audit')),
    ('ghost_strategy/Madrid-audit', 'ghost_strategy', dict(ev='Madrid', mode='audit')),
    ('generalisation', 'generalisation', dict(ev='Monza', mode='audit')),
    ('validation', 'validation', dict(ev='Monza', mode='live')),
]


# The tutorial is a product route too: audit every case and step at its example lap.
for case, event, driver, lap in (('monza_nor', 'Monza', 'NOR', 24), ('monza_ver', 'Monza', 'VER', 24), ('austria_ver', 'Austria', 'VER', 32)):
    for step in range(5):
        ROUTES.append((f'guided_demo/{case}/step{step+1}', 'guided_demo',
                       dict(ev=event, drv=driver, lap=lap, _demo_case=case, _demo_step=step, _demo_live_lap=lap)))


def _page_script(page: str, state: dict) -> str:
    return f"""
import sys; sys.path.insert(0, {str(PROTO)!r})
import streamlit as st
from app_v2.pages import {page} as page
from app_v2.ui import shell
for k, v in {state!r}.items():
    st.session_state[k] = v
shell.inject_css(bool(st.session_state.get('present', False)))
page.render()
"""


# ---- HTML -> text surfaces ----------------------------------------------------------------------------------------
class _Extract(HTMLParser):
    """Text of an st.html fragment (style blocks dropped), plus table cells with their column header and row label."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.cells: list[tuple[str, str, str]] = []
        self._skip = 0
        self._headers: list[str] = []
        self._row: list[str] = []
        self._cell: Optional[list[str]] = None
        self._cell_is_header = False
        self.labels: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('style', 'script'):
            self._skip += 1
        if a.get('aria-label'):
            self.labels.append(a['aria-label'])
        if tag == 'tr':
            self._row = []
        if tag in ('td', 'th'):
            self._cell, self._cell_is_header = [], tag == 'th'
        if tag in ('div', 'tr', 'li', 'br', 'p', 'span', 'td', 'th', 'h1', 'h2', 'h3', 'ul'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('style', 'script'):
            self._skip = max(0, self._skip - 1)
        if tag in ('td', 'th') and self._cell is not None:
            txt = ' '.join(self._cell).strip()
            if self._cell_is_header:
                self._headers.append(txt)
            else:
                self._row.append(txt)
            self._cell = None
        if tag == 'tr' and self._row:
            label = self._row[0]
            for i, c in enumerate(self._row):
                head = self._headers[i] if i < len(self._headers) else f'col{i}'
                self.cells.append((head, label, c))
        if tag == 'table':
            self._headers = []
        if tag in ('div', 'tr', 'li', 'p', 'td', 'th', 'h1', 'h2', 'h3'):
            self.parts.append(' ')

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._cell is not None:
            self._cell.append(data)

    @property
    def text(self) -> str:
        return re.sub(r'\s+', ' ', ''.join(self.parts)).strip()


def _label_of(raw: str, text: str, labels: list[str]) -> str:
    m = re.search(r'class="cs-kpi-label">([^<]+)<', raw) or re.search(r'class="cs-card-title">([^<]+)<', raw) or re.search(r'class="status">([^<]+)<', raw)
    if m:
        return _html.unescape(m.group(1)).strip()[:60]
    if labels:
        return labels[0][:60]
    return (text[:50] + ('...' if len(text) > 50 else '')) or '(empty)'


def _plotly_strings(spec_json: str) -> list[str]:
    """Trace names, text labels and annotation / title texts (never the data arrays)."""
    out = []
    try:
        spec = json.loads(spec_json)
    except Exception:
        return out
    for tr in spec.get('data', []) or []:
        for key in ('name', 'hovertext'):
            v = tr.get(key)
            if isinstance(v, str):
                out.append(v)
        t = tr.get('text')
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, list):
            out.extend(str(x) for x in t if isinstance(x, str))
    lay = spec.get('layout', {}) or {}
    title = lay.get('title')
    if isinstance(title, dict) and isinstance(title.get('text'), str):
        out.append(title['text'])
    elif isinstance(title, str):
        out.append(title)
    for ann in lay.get('annotations', []) or []:
        if isinstance(ann, dict) and isinstance(ann.get('text'), str):
            out.append(ann['text'])
    for ax in ('xaxis', 'yaxis'):
        t = (lay.get(ax) or {}).get('title')
        if isinstance(t, dict) and isinstance(t.get('text'), str):
            out.append(t['text'])
    return out


def _children(node) -> list:
    ch = getattr(node, 'children', None)
    if ch is None:
        return []
    if isinstance(ch, dict):
        return list(ch.values())
    try:
        return list(ch)
    except TypeError:
        return []


def collect_surfaces(at) -> list[dict]:
    """Every text-bearing element of a rendered AppTest tree -> {widget, kind, text, cells, raw}."""
    surfaces: list[dict] = []

    def walk(node):
        for ch in _children(node):
            t = getattr(ch, 'type', type(ch).__name__)
            try:
                if t == 'html':
                    raw = str(ch.value)
                    if not (raw.lstrip().startswith('<style') or 'data-orb-ready' in raw):
                        p = _Extract(); p.feed(raw)
                        surfaces.append(dict(kind='html', widget=_label_of(raw, p.text, p.labels), text=p.text, cells=p.cells, raw=raw))
                elif t in ('markdown', 'caption', 'text', 'code', 'latex'):
                    raw = str(ch.value)
                    p = _Extract(); p.feed(raw)
                    txt = p.text if '<' in raw else re.sub(r'\s+', ' ', raw).strip()
                    surfaces.append(dict(kind=t, widget=(txt[:50] + ('...' if len(txt) > 50 else '')) or '(empty)', text=txt, cells=p.cells if '<' in raw else [], raw=raw))
                elif t == 'metric':
                    surfaces.append(dict(kind='metric', widget=str(getattr(ch, 'label', 'metric')), text=f'{getattr(ch, "value", "")} {getattr(ch, "delta", "")}', cells=[], raw=''))
                elif t in ('dataframe', 'table', 'arrow_data_frame', 'arrow_table'):
                    try:
                        df = ch.value
                        txt = ' '.join(str(x) for x in df.astype(str).values.ravel().tolist()) + ' ' + ' '.join(map(str, df.columns))
                    except Exception:
                        txt = str(getattr(ch, 'value', ''))
                    surfaces.append(dict(kind='table', widget='dataframe', text=txt, cells=[], raw=''))
                elif t == 'plotly_chart':
                    proto = getattr(ch, 'proto', None)
                    spec = getattr(proto, 'spec', '') if proto is not None else ''
                    if not spec and proto is not None and hasattr(proto, 'figure'):
                        spec = getattr(proto.figure, 'spec', '')
                    strings = _plotly_strings(spec) if spec else []
                    title = next((s for s in strings if s), 'plotly chart')
                    surfaces.append(dict(kind='plotly', widget=f'chart: {title[:50]}', text=' | '.join(strings), cells=[], raw=''))
            except Exception as e:  # a surface we cannot read is reported, never hidden
                surfaces.append(dict(kind='error', widget=t, text='', cells=[], raw=repr(e)))
            walk(ch)

    walk(at._tree)
    return surfaces


# ---- reference set ------------------------------------------------------------------------------------------------
class ReferenceSet:
    """Every number a page may legitimately show, with its provenance; matched at display precision, most specific kind first."""

    def __init__(self) -> None:
        self.values: dict[str, list[tuple[float, str]]] = {}     # kind -> [(value, path)], insertion order = priority
        self.notes: list[str] = []

    def copy(self) -> 'ReferenceSet':
        c = ReferenceSet(); c.values = {k: list(v) for k, v in self.values.items()}; c.notes = list(self.notes); return c

    def prepend_kind(self, kind: str) -> None:
        if kind in self.values:
            self.values = {kind: self.values[kind], **{k: v for k, v in self.values.items() if k != kind}}

    def add(self, kind: str, value: float, path: str) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if v != v:
            return
        self.values.setdefault(kind, []).append((v, path))

    def add_json(self, kind: str, obj: Any, root: str) -> None:
        for p, v in numeric_leaves(obj, root):
            self.add(kind, v, p)

    def add_record(self, kind: str, obj: Any, root: str) -> None:
        """Numeric leaves plus the numbers inside text fields (change reasons, confidence_effect ...) that pages render verbatim."""
        self.add_json(kind, obj, root)
        for p, s in _string_leaves(obj, root):
            for v, dec, ctx, pos in find_numbers(s):
                self.add(kind + ' (text)', v, p)

    @staticmethod
    def _fmt(ref: float, decimals: int) -> Optional[float]:
        try:
            return float(f'{ref:.{decimals}f}')
        except (ValueError, OverflowError):
            return None

    def match(self, value: float, decimals: int, ctx: str) -> Optional[tuple[str, str, float, int]]:
        """(kind, path, reference, ambiguity) for the first reference that formats to `value` at `decimals`; ambiguity is
        the number of distinct underlying reference values (rounded at decimals + 2) that would also have matched."""
        pct = ctx.lstrip().startswith('%')
        unit = bool(UNIT_RE.match(ctx))
        first = None
        distinct: set[float] = set()
        for kind, items in self.values.items():
            for ref, path in items:
                for r in ([ref, ref * 100.0] if pct else [ref]):
                    ok = False
                    if decimals > 0:
                        f = self._fmt(r, decimals)
                        ok = f is not None and (f == value or -f == value)
                    else:
                        if float(r).is_integer() and abs(abs(r) - abs(value)) < 1e-9:
                            ok = True
                        elif unit or abs(value) >= 10:
                            f = self._fmt(r, 0)
                            ok = f is not None and (f == value or -f == value)
                    if ok:
                        distinct.add(round(abs(r), decimals + 2))
                        if first is None:
                            first = (kind, path, ref)
        if first is None:
            return None
        return first[0], first[1], first[2], len(distinct)


def _string_leaves(obj: Any, path: str = '$'):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _string_leaves(v, f'{path}.{k}')
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _string_leaves(v, f'{path}[{i}]')


def _jsonl(path: Path) -> list:
    out = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _sidecar_verified(path: Path) -> bool:
    sc = path.with_suffix(path.suffix + '.sha256')
    if not sc.exists():
        return False
    try:
        from shared.lockio import sha256_file
        return sc.read_text().split()[0].lower() == sha256_file(path)
    except Exception:
        return False


def build_base_references(lock: dict, state_values: list[float]) -> ReferenceSet:
    """What every route may show: the two locks, the lock_v2 sidecars, fixtures, the sensitivity asset, the feedback log
    and the lock-derived quantities."""
    refs = ReferenceSet()
    refs.add_json('lock', lock, 'lock')
    if LOCK_V2.exists():
        refs.add_json('lock_v2', read_json(LOCK_V2), 'lock_v2')
    for p in sorted(glob.glob(str(PROTO / 'out' / 'lock_v2_sidecars' / '*.json'))):
        refs.add_json('sidecar:lock_v2', read_json(p), Path(p).name)
    fx = PROTO / 'fixtures' / 'lock_v2_fixture.json'
    if fx.exists():
        refs.add_json('fixture', read_json(fx), 'fixtures/lock_v2_fixture.json')
    for p in sorted(glob.glob(str(PROTO / 'fixtures' / 'sidecars' / '*.json'))):
        refs.add_json('fixture', read_json(p), str(Path(p).relative_to(PROTO)))
    sens = PROTO / 'out' / 'sensitivity.json'
    if sens.exists():
        signed = sens.with_suffix('.json.sha256').exists()
        refs.add_json('asset:out/sensitivity.json' + ('' if signed else ' (unsigned)'), read_json(sens), 'out/sensitivity.json')
        if not signed:
            refs.notes.append('out/sensitivity.json has no .sha256 sidecar and is not in the lock: its numbers are shown on the validation page as an unsigned asset')
    # Workstream 3's scorecards (out/validation/*.json): not in the lock; the pages print each file's sha256 next to the values
    # (services/asset_repository), so they are hashed-on-screen assets. Listed as assets, matched last in provenance order.
    # Public evidence only: never ingest the post-freeze per-race audit trail.
    for filename in ('ghost_scorecard.json', 'live_scorecard.json', 'holdout_aggregate.json',
                     'hidden_stop_2026.json', 'regret_2026.json', 'risk_coverage.json', 'rolling_origin_2026.json'):
        p = PROTO / 'out' / 'validation' / filename
        if not p.exists():
            continue
        p = str(p)
        rel = str(Path(p).relative_to(PROTO))
        signed = Path(p + '.sha256').exists()
        try:
            refs.add_json(f'asset:{rel}' + ('' if signed else ' (sha256 printed on the page, no sidecar)'), read_json(p), rel)
        except Exception as e:      # pragma: no cover - a half-written file during a rebuild
            refs.notes.append(f'{rel}: unreadable ({e!r})')
    refs.notes.append('out/validation/*.json (Workstream 3 scorecards) have no .sha256 sidecar; the pages print the file sha256 next to the values, so they are matched as on-screen-hashed assets')
    fb = PROTO / 'app_v2' / 'state' / 'feedback_events.jsonl'
    if fb.exists():
        for rec in _jsonl(fb):
            refs.add_json('state:feedback_log', rec, 'app_v2/state/feedback_events.jsonl')
    # ---- lock-derived quantities the pages are allowed to form ------------------------------------------------------
    d = 'derived'
    rules = lock.get('rules', {})
    refs.add(d, float(rules.get('fuel_s_per_kg', 0.03)) * float(rules.get('fuel_prior_kg_per_lap', 1.1)), 'lock.rules.fuel_s_per_kg x fuel_prior_kg_per_lap')
    refs.add(d, 100.0 * float(rules.get('traffic_max', 0.3)), 'lock.rules.traffic_max x 100')
    refs.add(d, 105.0, 'lock lap rule: 105% of stint best')
    refs.add(d, 90.0, 'nominal band coverage 90%')
    refs.add(d, 2026.0, 'season')
    for yr in (2023.0, 2024.0, 2025.0):
        refs.add(d, yr, 'season on disk (2023 to 2026: deck / generalisation caption)')
    refs.add(d, float(len(glob.glob(str(PROTO / 'feat' / '*_R.csv')))), 'count of feat/*_R.csv')
    events_blk = lock.get('events', {})
    completed = [e for e, m in events_blk.items() if m.get('completed')]
    refs.add(d, float(len(completed)), 'count of completed weekends in lock.events')
    refs.add(d, float(len(lock.get('live', {}))), 'count of lock.live events')
    temps = sorted(m['track_temp']['R'] for m in events_blk.values() if m.get('completed') and (m.get('track_temp') or {}).get('R') is not None)
    if temps:
        refs.add(d, temps[0], 'min race track temp (lock.events)'); refs.add(d, temps[-1], 'max race track temp (lock.events)')
        refs.add(d, temps[len(temps) // 2], 'median race track temp (lock.events)')
    for ev, m in events_blk.items():
        t = (m.get('track_temp') or {}).get('R')
        if t is not None:
            refs.add(d, t + 5.0, f'lock.events.{ev}.track_temp.R + 5'); refs.add(d, t - 5.0, f'lock.events.{ev}.track_temp.R - 5')
        refs.add(d, float(len(lock.get('live', {}).get(ev, {}).get('compounds', []) or [r for r in lock.get('validation_rows', []) if r['event'] == ev])), f'count of compounds for {ev}')
    for ev, s in lock.get('strategy', {}).items():
        for name, v in (s.get('views') or {}).items():
            for pl in [v] + list(v.get('alternatives') or []):
                acc = 0
                for st in pl.get('stints', []):
                    acc += int(st)
                    refs.add(d, float(acc), f'lock.strategy.{ev}.views.{name}: cumulative stint (pit lap)')
                if pl.get('delta_to_best') is not None:
                    refs.add(d, -float(pl['delta_to_best']), f'lock.strategy.{ev}.views.{name}: -delta_to_best')
            acc = 0
            for st in (v.get('best_under_truth') or {}).get('stints', []):
                acc += int(st); refs.add(d, float(acc), f'lock.strategy.{ev}.views.{name}.best_under_truth: cumulative stint')
    for r in lock.get('validation_rows', []):
        if r.get('hi') is not None and r.get('lo') is not None:
            w = float(r['hi']) - float(r['lo'])
            refs.add(d, w, f'validation_rows[{r["event"]},{r["compound"]}]: band width')
            sd = max(w / (2.0 * Z90), 1e-4)
            refs.add(d, sd, f'validation_rows[{r["event"]},{r["compound"]}]: prior sd = band width / (2 x 1.6449)')
            refs.add(d, float(r.get('pred_clearstint') or 0.0) + Z_Q90 * sd, f'validation_rows[{r["event"]},{r["compound"]}]: prior q90')
    for ev, lv in lock.get('live', {}).items():
        for c in lv.get('compounds', []):
            b = c.get('band90') or [None, None]
            if b[0] is not None:
                w = float(b[1]) - float(b[0])
                refs.add(d, w, f'live.{ev}.{c["compound"]}: band width')
                refs.add(d, max(w / (2.0 * Z90), 1e-4), f'live.{ev}.{c["compound"]}: prior sd')
    for f in (2.0, 4.0):
        refs.add(d, f, 'live/estimator.py widening multipliers (x2 status / temperature / feed, x4 rain)')
    for v in state_values:
        refs.add('state', float(v), 'route state (lap / intervention lap / scrubber)')
    return refs


def _race_csv_refs(refs: ReferenceSet, lock: dict, event: str) -> None:
    p = PROTO / 'feat' / f'{event}_R.csv'
    if not p.exists():
        return
    import pandas as pd
    df = pd.read_csv(p)
    kind = f'asset:feat/{event}_R.csv (unsigned)'
    for col in ('LapNumber', 'TyreLife', 'Stint', 'track_temp', 'pos_distinct', 'n_tel', 'stale_share', 'lap_s'):
        if col in df:
            for v in pd.unique(df[col].dropna()):
                refs.add(kind, float(v), f'feat/{event}_R.csv:{col}')
    for (drv, stint), s in df.groupby(['Driver', 'Stint']):
        refs.add(kind, float(s['LapNumber'].min()), f'feat/{event}_R.csv:{drv}:stint{int(stint)}:first_lap')
        refs.add(kind, float(s['LapNumber'].max()), f'feat/{event}_R.csv:{drv}:stint{int(stint)}:last_lap')
        refs.add(kind, float(len(s)), f'feat/{event}_R.csv:{drv}:stint{int(stint)}:laps')
    refs.add(kind, float(df['Driver'].nunique()), f'feat/{event}_R.csv:n_drivers')
    n_laps = (lock.get('strategy', {}).get(event) or {}).get('n_laps')
    if n_laps:   # model_v2 race correction of every recorded lap (live/lapfeed.corrected_time): the estimator's change log quotes it
        y = df['lap_s'].astype(float) - FUEL_S_PER_KG * RACE_FUEL_KG * (1.0 - (df['LapNumber'].astype(float) - 1.0) / float(n_laps))
        for v in pd.unique(y.dropna().round(3)):
            refs.add('derived', float(v), f'feat/{event}_R.csv: lap_s - 0.03 x 70 x (1 - (lap - 1) / {n_laps}) (model_v2 race fuel correction)')


def _live_refs(refs: ReferenceSet, event: str, driver: str, lap: int) -> None:
    """Hashed out/live/<event>_<driver>/ records, else Workstream 8's deterministic run reproduced in-process (listed as UNHASHED)."""
    d = PROTO / 'out' / 'live' / f'{event}_{driver}'
    if d.is_dir():
        ok = all(_sidecar_verified(d / f) for f in ('states.jsonl', 'recommendations.jsonl', 'estimator_trace.jsonl', 'live_predictor.json') if (d / f).exists())
        kind = f'sidecar:out/live/{event}_{driver}' + ('' if ok else ' (sidecar mismatch)')
        if not ok:
            refs.notes.append(f'{d.relative_to(PROTO)}: a .sha256 sidecar is missing or does not match')
        for f in ('summary.json', 'live_predictor.json'):
            if (d / f).exists():
                refs.add_record(kind, read_json(d / f), str((d / f).relative_to(PROTO)))
        for f in ('states.jsonl', 'recommendations.jsonl', 'estimator_trace.jsonl'):
            if (d / f).exists():
                for i, rec in enumerate(_jsonl(d / f)):
                    if int(rec.get('lap', 0) or 0) <= int(lap):        # the page shows the state at `lap` and the history before it
                        refs.add_record(kind, rec, f'{(d / f).relative_to(PROTO)}[{i}]')
        return
    if not (PROTO / 'feat' / f'{event}_R.csv').exists():
        return
    try:
        from live import viewmodel as LV
        session, results = LV.results_through(event, driver, int(lap))
    except Exception as e:
        refs.notes.append(f'live runtime reference unavailable for {event} {driver}: {e!r}')
        return
    kind = f'live_runtime:{event}_{driver} (no hashed record)'
    for r in results:
        refs.add_record(kind, r.tyre_state, f'{event}_{driver}:lap{r.lap}:tyre_state')
        refs.add_record(kind, r.ranked.actions, f'{event}_{driver}:lap{r.lap}:actions')
        refs.add_record(kind, dict(baseline=r.ranked.baseline), f'{event}_{driver}:lap{r.lap}:baseline')
        refs.add_record(kind, r.state.as_trace(), f'{event}_{driver}:lap{r.lap}:trace')
        refs.add(kind, r.state.prior_sd, f'{event}_{driver}:lap{r.lap}:prior_sd')
    refs.notes.append(f'{event} {driver}: no hashed out/live record for the route driver; the live numbers were reproduced in-process (live/viewmodel.results_through) and are listed as UNHASHED')


def _counterfactual_refs(refs: ReferenceSet, event: str) -> None:
    import pandas as pd
    for p in sorted(glob.glob(str(PROTO / 'out' / 'counterfactual' / '**' / 'summary.json'), recursive=True)):    # incl. pre_race/<scenario>/
        s = read_json(p)
        eid = (s.get('scenario') or {}).get('event_id', '')
        if eid.split('_', 1)[-1] != event:
            continue
        kind = f'sidecar:out/counterfactual ({event})'
        refs.add_record(kind, s, str(Path(p).relative_to(PROTO)))
        for f in ('lap_deltas.json', 'ghost_replay.json'):
            q = Path(p).with_name(f)
            if q.exists():
                refs.add_json(kind, read_json(q), str(q.relative_to(PROTO)))
        laps_csv = Path(p).with_name('laps.csv')
        if laps_csv.exists():
            df = pd.read_csv(laps_csv)
            for col in df.columns:
                if df[col].dtype.kind in 'fi':
                    for v in pd.unique(df[col].dropna()):
                        refs.add(kind, float(v), f'{laps_csv.relative_to(PROTO)}:{col}')
    for p in sorted(glob.glob(str(PROTO / 'out' / 'counterfactual' / f'lattice_{event}_*.json'))):
        refs.add_json(f'sidecar:out/counterfactual ({event})', read_json(p), str(Path(p).relative_to(PROTO)))
    meta = PROTO / 'out' / 'maps' / event / 'meta.json'
    if meta.exists():
        refs.add_record(f'sidecar:out/maps/{event}', read_json(meta), f'out/maps/{event}/meta.json')


def route_references(base: ReferenceSet, lock: dict, page: str, state: dict) -> ReferenceSet:
    """Base references plus what this route may show, with the route-specific kinds tried first."""
    refs = base.copy()
    ev, drv, lap = state.get('ev'), state.get('drv'), int(state.get('lap') or 1)
    specific = ReferenceSet()
    if ev:
        _race_csv_refs(specific, lock, ev)
    if (page in LIVE_PAGES or (page == 'guided_demo' and state.get('_demo_step') in (1, 2))) and ev and drv:
        _live_refs(specific, ev, drv, lap)
    if (page in GHOST_PAGES or (page == 'guided_demo' and state.get('_demo_step') in (3, 4))) and ev:
        _counterfactual_refs(specific, ev)
    if page in ('validation', 'generalisation'):
        pe = PROTO / 'out' / 'live' / 'prefix_eval.json'
        if pe.exists():
            specific.add_record('sidecar:out/live/prefix_eval.json' + ('' if _sidecar_verified(pe) else ' (sidecar mismatch)'), read_json(pe), 'out/live/prefix_eval.json')
    merged = ReferenceSet()
    # provenance order: the locks first, then this route's hashed sidecars, then lock-derived quantities, then unsigned
    # assets, fixtures and state (the ambiguity count is independent of this order)
    order = ['lock', 'lock_v2', 'sidecar:lock_v2'] + [k for k in specific.values if not k.startswith('asset:')] + ['derived'] + [k for k in specific.values if k.startswith('asset:')]
    for k in order:
        merged.values.setdefault(k, [])
    for k, v in specific.values.items():
        merged.values.setdefault(k, []).extend(v)
    for k, v in refs.values.items():
        merged.values.setdefault(k, []).extend(v)
    merged.values = {k: v for k, v in merged.values.items() if v}
    merged.notes = refs.notes + specific.notes
    return merged


# ---- per-route probe ------------------------------------------------------------------------------------------------
def probe_route(name: str, page: str, state: dict, refs: ReferenceSet, verbose: bool = False) -> dict:
    from streamlit.testing.v1 import AppTest
    rec: dict[str, Any] = dict(route=name, page=page, state=state, status='ok', numbers=0, matched={}, ambiguous=[], placeholders=[], unclassified=[], unhashed_live=[], mismatches=[], error=None,
                               notes=[n for n in refs.notes if 'route driver' in n or 'runtime reference' in n])
    try:
        at = AppTest.from_string(_page_script(page, state))
        at.run(timeout=90)
        if at.exception:
            rec['status'] = 'load_failure'; rec['error'] = '; '.join(str(e.value)[:300] for e in at.exception)
            return rec
        surfaces = collect_surfaces(at)
    except Exception as e:
        rec['status'] = 'load_failure'; rec['error'] = f'{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}'
        return rec
    return match_surfaces(rec, surfaces, refs, verbose)


def match_surfaces(rec: dict, surfaces: list[dict], refs: ReferenceSet, verbose: bool = False) -> dict:
    """Shared numeric matcher for AppTest elements and actual browser DOM surfaces."""
    name = rec['route']
    for s in surfaces:
        if s['kind'] == 'error':
            rec['status'] = 'load_failure'; rec['error'] = f"surface {s['widget']}: {s['raw']}"
            continue
        text = HASH_CTX_RE.sub(r'\1 ', s['text'])
        text = re.sub(r'\bL(\d{1,2})\b', r'lap \1', text)
        text = re.sub(r'\bx(\d)', r'x \1', text)
        text = re.sub(r'\bq(10|50|90)\b', ' ', text)
        placeholder = any(w in s['text'] for w in PLACEHOLDER_WORDS) or any(w in s['widget'] for w in PLACEHOLDER_WORDS)
        cell_ctx = {}
        for head, label, cell in s['cells']:
            for v, dec, ctx, pos in find_numbers(cell):
                cell_ctx[(v, dec)] = f'{head} / {label}'
        for v, dec, ctx, pos in find_numbers(text):
            rec['numbers'] += 1
            m = refs.match(v, dec, ctx)
            where = cell_ctx.get((v, dec), '')
            shown = text[max(0, pos - 28):pos + 22].strip()
            if m is not None:
                kind, path, ref, amb = m
                rec['matched'][kind] = rec['matched'].get(kind, 0) + 1
                entry = dict(widget=s['widget'], value=v, decimals=dec, shown=shown, reference=path, reference_value=ref, kind=kind, ambiguity=amb)
                rec.setdefault('matches', []).append(entry)
                if kind.startswith('live_runtime'):
                    rec['unhashed_live'].append(entry)
                if amb > 1 and dec > 0:
                    rec['ambiguous'].append(entry)
                if verbose:
                    print(f'   ok  {name} [{s["widget"][:36]}] {v} <- {kind} {path} (ambiguity {amb})')
                continue
            entry = dict(widget=s['widget'], kind=s['kind'], value=v, decimals=dec, unit_context=ctx.strip()[:12], column=where, shown=shown)
            if placeholder:
                rec['placeholders'].append(entry)
            elif dec == 0 and not UNIT_RE.match(ctx) and abs(v) < 100:
                rec['unclassified'].append(entry)
                if rec.get('require_classified_numbers'):
                    rec['mismatches'].append(entry)
            else:
                rec['mismatches'].append(entry)
    if rec['status'] == 'ok' and rec['mismatches']:
        rec['status'] = 'mismatch'
    return rec


def run(routes: Optional[list[str]] = None, verbose: bool = False, out: Path | str | None = REPORT_PATH) -> dict:
    selected = [r for r in ROUTES if routes is None or r[0] in routes or r[1] in routes]
    state_vals = [float(v) for r in selected for k, v in r[2].items() if k in ('lap', 'ilap', 'glap') and isinstance(v, (int, float))]
    if not LOCK_V1.exists():
        rep = dict(generated_at=now_iso(), exit_code=2, error=f'lock missing: {LOCK_V1}', routes=[])
        if out:
            write_json(out, rep)
        return rep
    lock = read_json(LOCK_V1)
    base = build_base_references(lock, state_vals)
    results = []
    kinds: dict[str, int] = {}
    for n, p, s in selected:
        refs = route_references(base, lock, p, s)
        for k, v in refs.values.items():
            kinds[k] = max(kinds.get(k, 0), len(v))
        results.append(probe_route(n, p, s, refs, verbose))
    n_mis = sum(len(r['mismatches']) for r in results)
    n_fail = sum(1 for r in results if r['status'] == 'load_failure')
    exit_code = 2 if n_fail else (1 if n_mis else 0)
    notes = list(dict.fromkeys(base.notes + [n for r in results for n in r['notes']]))
    rep = dict(generated_at=now_iso(), exit_code=exit_code,
               definition='exit 0: every rendered number equals the lock, a hashed sidecar, a labelled fixture or a lock-derived quantity at the display precision of ui/tokens.py; '
                          'placeholders (PLACEHOLDER / FIXTURE / pending) and UNHASHED live values (route driver without an out/live record) are allowed and listed; '
                          'ambiguity = number of distinct reference values that would have matched (coincidence risk)',
               lock=dict(v1=str(LOCK_V1.relative_to(PROTO)), v2=str(LOCK_V2.relative_to(PROTO)) if LOCK_V2.exists() else None),
               reference_kinds_max=kinds, notes=notes,
               summary=dict(routes=len(results), load_failures=n_fail, numbers=sum(r['numbers'] for r in results), mismatches=n_mis,
                            placeholders=sum(len(r['placeholders']) for r in results), unclassified_integers=sum(len(r['unclassified']) for r in results),
                            unhashed_live_values=sum(len(r['unhashed_live']) for r in results), ambiguous_matches=sum(len(r['ambiguous']) for r in results)),
               routes=results)
    if out:
        write_json(out, rep)
    return rep


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--routes', default=None, help='comma-separated route names or page modules (default: all)')
    ap.add_argument('--browser', action='store_true', help='also audit actual DOM at 1440x900 and 1920x1080; server required')
    ap.add_argument('--base', default='http://localhost:8502')
    ap.add_argument('--verbose', action='store_true')
    ap.add_argument('--out', default=str(REPORT_PATH))
    a = ap.parse_args(argv)
    rep = run([x.strip() for x in a.routes.split(',')] if a.routes else None, a.verbose, a.out)
    if rep.get('error'):
        print(f'consistency probe: {rep["error"]}')
        return rep['exit_code']
    if a.browser:
        from evaluation.red_team.browser_consistency import run as run_browser
        browser = run_browser(a.base, routes=[x.strip() for x in a.routes.split(',')] if a.routes else None)
        rep['browser'] = browser
        rep['exit_code'] = max(rep['exit_code'], browser['exit_code'])
        write_json(a.out, rep)
        print(f"browser consistency: {browser.get('summary')} -> exit {browser['exit_code']}")
    s = rep['summary']
    print(f"consistency probe: {s['routes']} routes, {s['numbers']} numbers, {s['mismatches']} mismatches, {s['placeholders']} placeholder values, "
          f"{s['unhashed_live_values']} unhashed live values, {s['ambiguous_matches']} ambiguous matches, {s['unclassified_integers']} unclassified small integers, "
          f"{s['load_failures']} load failures -> exit {rep['exit_code']}")
    for r in rep['routes']:
        flag = 'FAIL' if r['status'] != 'ok' else 'ok  '
        print(f"  {flag} {r['route']:<34} numbers {r['numbers']:>4}  mismatches {len(r['mismatches']):>2}  placeholders {len(r['placeholders']):>2}  unhashed {len(r['unhashed_live']):>3}  ambiguous {len(r['ambiguous']):>3}"
              + (f"  error: {r['error'][:160]}" if r['error'] else ''))
        for m in r['mismatches']:
            print(f"       MISMATCH [{m['widget'][:40]}] {m['shown']!r} value {m['value']} ({m['decimals']} dp) unit {m['unit_context']!r} {('col ' + m['column']) if m['column'] else ''}")
    for n in rep['notes']:
        print(f'  note: {n}')
    print(f'report: {a.out}')
    return rep['exit_code']


if __name__ == '__main__':
    sys.exit(main())
