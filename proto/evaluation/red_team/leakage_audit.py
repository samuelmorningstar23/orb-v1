"""Leakage audit: the data boundaries of roadmap v5 sections 1 and 3, checked in code, not in documentation.

Static (ast over every module):
    live/ and decision/           must not import counterfactual, ghost, replay, interaction or evaluation
    counterfactual/, events/,     must not import live or decision
    replay/
    app_v2/pages, ui, state,      must not import model_v2, pipeline, strategy2, liquid, counterfactual, live, decision,
    components                    replay, events, interaction or evaluation directly: pages consume services only
    (app_v2/services may bridge to live/ and counterfactual/; those imports are listed, not failed)
Dynamic:
    import closure               importing live.session + live.viewmodel + decision.optimizer in a fresh interpreter loads no
                                 counterfactual / replay / ghost module, and importing counterfactual.engine + events loads no live module
    future-read spy              Workstream 8's LiveSession run for one race through a feed proxy: every LapFeed call is recorded, the
                                 requested lap never exceeds the lap being produced, no returned row or frame carries a later
                                 LapNumber, no other feed attribute is touched; `inject=True` makes the proxy leak lap k+1 and the
                                 audit must catch it (tests/red_team)
    deny-list spy                every argument handed to LiveTyreStateEstimator.update is walked recursively: no key from the
                                 deny list (obs, obs_se, obs_push, err_*, ratio, z, n_race, pred_clearstint, cost_under_truth,
                                 best_under_truth) may reach the estimator
    target-driver exclusion      Workstream 2's engine compiled with exclude_target_driver=True calls RaceData.reference_slopes with the
                                 target driver, the reference frame drops that driver's laps, and the summary says so
    one forecast hash            lock_v2 shared.forecast_hash is recomputed from the pre_race_forecast block and compared with every
                                 hash Workstream 2 (out/counterfactual/*/summary.json), Workstream 8 (out/live/*/summary.json, live_predictor.json),
                                 provider A and the dashboard LockView report

    python evaluation/red_team/leakage_audit.py [--event Monza --driver NOR] [--out PATH]
Exit 0 when every check passes, 1 otherwise. Report: evaluation/red_team/leakage_audit_report.json
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
import traceback
from dataclasses import fields as dc_fields, is_dataclass
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))
from evaluation.red_team import PROTO, RT_DIR, LOCK_V2, now_iso, read_json, write_json  # noqa: E402

REPORT_PATH = RT_DIR / 'leakage_audit_report.json'
DENY_KEYS = ('obs', 'obs_se', 'obs_push', 'ratio', 'z', 'n_race', 'pred_clearstint', 'cost_under_truth_vs_best_s', 'best_under_truth', 'completed')
DENY_PREFIXES = ('err_',)
GHOST_SIDE = ('counterfactual', 'ghost', 'replay', 'interaction', 'evaluation')
LIVE_SIDE = ('live', 'decision')
MODELS = ('model_v2', 'pipeline', 'strategy2', 'liquid', 'features', 'tyre_proto', 'prior2025', 'sensitivity')
STATIC_RULES = [
    # (directory glob, forbidden top-level modules, severity, rule)
    ('live/**/*.py', GHOST_SIDE, 'fail', 'live/ must not import ghost-side modules (counterfactual, ghost, replay, interaction, evaluation)'),
    ('decision/**/*.py', GHOST_SIDE, 'fail', 'decision/ must not import ghost-side modules'),
    ('counterfactual/**/*.py', LIVE_SIDE, 'fail', 'counterfactual/ must not import live/ or decision/'),
    ('events/**/*.py', LIVE_SIDE, 'fail', 'events/ must not import live/ or decision/'),
    ('replay/**/*.py', LIVE_SIDE, 'fail', 'replay/ must not import live/ or decision/'),
    ('app_v2/pages/*.py', MODELS + ('counterfactual', 'live', 'decision', 'replay', 'events', 'interaction', 'evaluation'), 'fail', 'pages consume services only (roadmap 13.1: no page imports a model)'),
    ('app_v2/ui/*.py', MODELS + ('counterfactual', 'live', 'decision', 'replay', 'events', 'interaction', 'evaluation'), 'fail', 'ui components consume view models only'),
    ('app_v2/state/*.py', MODELS + ('counterfactual', 'live', 'decision', 'replay', 'events', 'interaction', 'evaluation'), 'fail', 'state modules consume services only'),
    ('app_v2/components/**/*.py', MODELS + ('counterfactual', 'live', 'decision', 'events', 'interaction', 'evaluation'), 'fail', 'components consume view models only (replay/ geometry is Workstream 4\'s own package)'),
    ('app_v2/services/*.py', MODELS + ('counterfactual', 'live', 'decision', 'replay', 'events', 'interaction', 'evaluation'), 'info', 'services may bridge to live/ and counterfactual/ (listed for the record)'),
    ('live/**/*.py', ('app_v2',), 'info', 'live/ importing the dashboard package inverts the dependency direction (listed, not a boundary rule)'),
]


# ---------------------------------------------------------------- static
def _imports(path: Path) -> list[tuple[str, int]]:
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except SyntaxError as e:
        return [(f'<syntax error: {e}>', 0)]
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.append((a.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.append((node.module, node.lineno))
    return out


def static_checks() -> dict:
    results = []
    for pattern, forbidden, severity, rule in STATIC_RULES:
        hits = []
        for p in sorted(PROTO.glob(pattern)):
            if '__pycache__' in p.parts:
                continue
            for mod, line in _imports(p):
                top = mod.split('.')[0]
                if top in forbidden:
                    hits.append(dict(file=str(p.relative_to(PROTO)), line=line, imports=mod))
        results.append(dict(rule=rule, pattern=pattern, forbidden=list(forbidden), severity=severity, violations=hits, status=('PASS' if not hits else ('FAIL' if severity == 'fail' else 'INFO'))))
    return dict(status='PASS' if all(r['status'] != 'FAIL' for r in results) else 'FAIL', rules=results)


def import_closure_checks() -> dict:
    """Fresh interpreters: what a package pulls into sys.modules."""
    py = sys.executable
    cases = [
        ('live side', 'import live.session, live.viewmodel, live.replay_run, decision.optimizer', GHOST_SIDE),
        ('ghost side', 'import counterfactual.engine, counterfactual.run, events.sources', LIVE_SIDE),
        ('replay side', 'import replay.timewarp, replay.trajectory', LIVE_SIDE),
    ]
    out = []
    for name, stmt, forbidden in cases:
        code = (f"import sys, json; sys.path.insert(0, {str(PROTO)!r}); {stmt}; "
                f"print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in {list(forbidden)!r})))")
        try:
            r = subprocess.run([py, '-c', code], capture_output=True, text=True, cwd=PROTO, timeout=120)
            loaded = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else None
            out.append(dict(case=name, statement=stmt, forbidden=list(forbidden), loaded=loaded, status=('PASS' if loaded == [] else 'FAIL'), stderr=r.stderr[-600:] if r.returncode else ''))
        except Exception as e:
            out.append(dict(case=name, statement=stmt, status='FAIL', error=repr(e)))
    return dict(status='PASS' if all(c['status'] == 'PASS' for c in out) else 'FAIL', cases=out)


# ---------------------------------------------------------------- dynamic: future-read spy on Workstream 8's live session
class FeedProxy:
    """Stands in for live.lapfeed.LapFeed inside a LiveSession: records every call, checks the requested lap against the
    lap being produced (`cursor`), inspects what comes back for later laps and refuses any other attribute."""
    ALLOWED_CALLS = ('row', 'through', 'field_at', 'laps_of')
    ALLOWED_ATTRS = ('event', 'n_laps', 't_ref_s', 'drivers')

    def __init__(self, feed, inject: bool = False):
        object.__setattr__(self, '_feed', feed)
        object.__setattr__(self, '_inject', inject)
        object.__setattr__(self, 'cursor', None)
        object.__setattr__(self, 'calls', [])
        object.__setattr__(self, 'violations', [])

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        feed = object.__getattribute__(self, '_feed')
        if name in self.ALLOWED_ATTRS:
            return getattr(feed, name)
        if name not in self.ALLOWED_CALLS:
            self.violations.append(f'feed attribute {name!r} accessed directly (only {self.ALLOWED_CALLS} are online-safe accessors)')
            raise AttributeError(name)
        real = getattr(feed, name)

        def wrapped(driver, k=None, *a, **kw):
            if name == 'laps_of':
                return real(driver)
            k_req = int(k)
            k_eff = k_req + 1 if (self._inject and name == 'row') else k_req      # deliberate violation for the self-test
            self.calls.append((name, driver, k_eff))
            if self.cursor is not None and k_eff > self.cursor:
                self.violations.append(f'{name}({driver}, {k_eff}) requested while producing lap {self.cursor}')
            out = real(driver, k_eff, *a, **kw)
            later = _max_lap(out)
            if later is not None and self.cursor is not None and later > self.cursor:
                self.violations.append(f'{name}({driver}, {k_eff}) returned LapNumber {later} > lap {self.cursor} being produced')
            return out
        return wrapped


def _max_lap(obj) -> Optional[int]:
    try:
        import pandas as pd
        if isinstance(obj, pd.DataFrame):
            return int(obj['LapNumber'].max()) if len(obj) else None
    except Exception:
        pass
    if isinstance(obj, dict) and 'LapNumber' in obj:
        return int(obj['LapNumber'])
    if isinstance(obj, list):
        laps = [getattr(c, 'lap', None) for c in obj]
        laps = [int(x) for x in laps if x is not None]
        return max(laps) if laps else None
    return None


def _walk_keys(obj, path='$', seen=None):
    seen = seen if seen is not None else set()
    if id(obj) in seen:
        return
    if isinstance(obj, dict):
        seen.add(id(obj))
        for k, v in obj.items():
            yield f'{path}.{k}', str(k)
            yield from _walk_keys(v, f'{path}.{k}', seen)
    elif isinstance(obj, (list, tuple)):
        seen.add(id(obj))
        for i, v in enumerate(obj):
            yield from _walk_keys(v, f'{path}[{i}]', seen)
    elif is_dataclass(obj) and not isinstance(obj, type):
        seen.add(id(obj))
        for f in dc_fields(obj):
            yield f'{path}.{f.name}', f.name
            yield from _walk_keys(getattr(obj, f.name), f'{path}.{f.name}', seen)
    elif hasattr(obj, '__dict__') and not isinstance(obj, type) and type(obj).__module__ not in ('builtins', 'numpy', 'pandas.core.frame', 'pandas.core.series'):
        seen.add(id(obj))
        for k, v in vars(obj).items():
            if k.startswith('_'):
                continue
            yield f'{path}.{k}', k
            yield from _walk_keys(v, f'{path}.{k}', seen)


def _denied(key: str) -> bool:
    return key in DENY_KEYS or any(key.startswith(p) for p in DENY_PREFIXES)


def future_read_spy(event: str = 'Monza', driver: str = 'NOR', race_csv: Optional[Path] = None, inject: bool = False, through_lap: Optional[int] = None) -> dict:
    """Run Workstream 8's LiveSession lap by lap behind the feed proxy and the deny-list spy."""
    from live.session import LiveSession
    from live.estimator import LiveTyreStateEstimator
    from live.lapfeed import FutureDataError
    session = LiveSession.open(event, driver, feedback_enabled=False, race_csv=race_csv)
    proxy = FeedProxy(session.feed, inject=inject)
    session.feed = proxy
    denied_hits: list[str] = []
    orig_update = LiveTyreStateEstimator.update

    def spy_update(self, prior_state, telemetry, context, driver_feedback=None, sensor_data=None):
        for arg_name, arg in (('telemetry', telemetry), ('context', context), ('driver_feedback', driver_feedback), ('sensor_data', sensor_data)):
            for path, key in _walk_keys(arg, arg_name):
                if _denied(key):
                    denied_hits.append(path)
        return orig_update(self, prior_state, telemetry, context, driver_feedback, sensor_data)

    LiveTyreStateEstimator.update = spy_update
    state, laps_done, errors = None, 0, []
    try:
        for k in session.laps():
            if through_lap is not None and k > through_lap:
                break
            proxy.cursor = int(k)
            try:
                res = session.step(state, k, None)
            except FutureDataError as e:
                errors.append(f'lap {k}: FutureDataError raised by the estimator: {e}')
                break
            if res is None:
                continue
            state = res.state
            laps_done += 1
            if res.tyre_state.get('uses_future_data') or res.tyre_state.get('uses_post_race_reference'):
                proxy.violations.append(f'lap {k}: record flags uses_future_data / uses_post_race_reference')
            ts = res.tyre_state.get('timestamp', '')
            if state.timestamp != ts:
                proxy.violations.append(f'lap {k}: state timestamp {state.timestamp} differs from the 7.1 record {ts}')
    finally:
        LiveTyreStateEstimator.update = orig_update
    ok = not proxy.violations and not denied_hits and not errors
    return dict(status='PASS' if ok else 'FAIL', event=event, driver=driver, race_csv=str(race_csv) if race_csv else f'feat/{event}_R.csv', inject=inject, laps_processed=laps_done,
                feed_calls=len(proxy.calls), calls_by_kind={n: sum(1 for c in proxy.calls if c[0] == n) for n in FeedProxy.ALLOWED_CALLS},
                max_requested_lap_minus_cursor=max((c[2] - c[2] for c in proxy.calls), default=0), violations=proxy.violations[:20], deny_list_hits=sorted(set(denied_hits))[:20],
                estimator_errors=errors, deny_list=list(DENY_KEYS) + [p + '*' for p in DENY_PREFIXES],
                note='the proxy sees only the LapFeed API; a leak that bypasses the feed (reading the CSV directly) is caught by the static import rules and the import-closure check, not here')


# ---------------------------------------------------------------- dynamic: target-driver exclusion in Workstream 2's engine
def target_driver_exclusion(event: str = 'Monza', driver: str = 'NOR', lap: int = 24, to_compound: str = 'MEDIUM') -> dict:
    from counterfactual import racedata
    from counterfactual.engine import CounterfactualEngine, ScenarioSpec
    calls: list[Optional[str]] = []
    orig = racedata.RaceData.reference_slopes

    def spy(self, exclude_driver=None):
        calls.append(exclude_driver)
        return orig(self, exclude_driver)

    racedata.RaceData.reference_slopes = spy
    try:
        eng = CounterfactualEngine()
        r_ex = eng.compile(ScenarioSpec(event, driver, lap, to_compound, exclude_target_driver=True))
        r_in = eng.compile(ScenarioSpec(event, driver, lap, to_compound, exclude_target_driver=False))
    finally:
        racedata.RaceData.reference_slopes = orig
    R = eng.race(event)
    n_all, n_ex = len(R._prep), int((R._prep['Driver'] != driver).sum())
    cv_ex, cv_in = r_ex.engine['curves'], r_in.engine['curves']
    checks = {
        'reference_slopes called with the target driver': driver in calls,
        'engine says target_driver_excluded': bool(cv_ex.get('target_driver_excluded')) and bool(r_ex.scenario['validation']['target_driver_excluded']),
        'reference frame drops the target driver laps': cv_ex.get('n_laps_used') == n_ex and n_ex < n_all,
        'all-driver refit matches the lock obs to 1e-4': all(abs(cv_in['by_compound'][c]['slope'] - cv_in['by_compound'][c]['lock_all_driver']['slope']) < 1e-4 for c in cv_in['by_compound'] if cv_in['by_compound'][c].get('lock_all_driver')),
        'included run uses every lap': cv_in.get('n_laps_used') == n_all and not cv_in.get('target_driver_excluded'),
        'label is the lead decision wording': cv_ex.get('label') == 'leave-one-driver-out Sunday reference',
        'post-race reference flagged': bool(r_ex.engine['uses_post_race_reference']) and bool(cv_ex.get('uses_post_race_reference')),
    }
    slopes = {c: dict(excluded=cv_ex['by_compound'][c]['slope'], all_drivers=cv_in['by_compound'][c]['slope'], lock=(cv_in['by_compound'][c].get('lock_all_driver') or {}).get('slope')) for c in cv_ex['by_compound']}
    return dict(status='PASS' if all(checks.values()) else 'FAIL', event=event, driver=driver, reference_slopes_calls=calls, n_laps_all=n_all, n_laps_excluded=n_ex, checks=checks, slopes=slopes)


# ---------------------------------------------------------------- one forecast hash
def forecast_hash_checks() -> dict:
    out: dict[str, Any] = dict(status='PASS', lock_v2_hash=None, recomputed=None, sources=[])
    if not LOCK_V2.exists():
        return dict(status='FAIL', error='out/lock_v2.json missing')
    v2 = read_json(LOCK_V2)
    h = v2['shared']['forecast_hash']
    out['lock_v2_hash'] = h
    try:
        from schemas.lock_v2 import compute_forecast_hash
        rec = compute_forecast_hash(v2['pre_race_forecast'])
    except Exception as e:
        rec = f'error: {e!r}'
    out['recomputed'] = rec
    out['sources'].append(dict(source='schemas.lock_v2.compute_forecast_hash(pre_race_forecast)', hash=rec, agrees=(rec == h)))
    for p in sorted((PROTO / 'out' / 'counterfactual').glob('*/summary.json')):
        s = read_json(p)
        a, b = s.get('scenario', {}).get('forecast_hash'), s.get('engine', {}).get('pre_race_forecast_hash')
        out['sources'].append(dict(source=str(p.relative_to(PROTO)), hash=a, agrees=(a == h and b == h), engine_hash=b))
    for p in sorted((PROTO / 'out' / 'live').glob('*/summary.json')):
        s = read_json(p)
        out['sources'].append(dict(source=str(p.relative_to(PROTO)), hash=s.get('forecast_hash'), agrees=(s.get('forecast_hash') == h)))
    for p in sorted((PROTO / 'out' / 'live').glob('*/live_predictor.json')):
        s = read_json(p)
        a = (s.get('prior') or {}).get('forecast_hash')
        out['sources'].append(dict(source=str(p.relative_to(PROTO)) + ' prior.forecast_hash', hash=a, agrees=(a == h)))
    try:
        from counterfactual.provider import ProviderA
        a = ProviderA().forecast_hash
        out['sources'].append(dict(source='counterfactual.provider.ProviderA().forecast_hash', hash=a, agrees=(a == h)))
    except Exception as e:
        out['sources'].append(dict(source='counterfactual.provider.ProviderA', hash=None, agrees=False, error=repr(e)))
    try:
        from app_v2.services import lock_repository as LR
        lk = LR.load_lock()
        a = 'sha256:' + lk.forecast_hash
        out['sources'].append(dict(source='app_v2 LockView.forecast_hash (' + lk.forecast_hash_source + ')', hash=a, agrees=(a == h)))
    except Exception as e:
        out['sources'].append(dict(source='app_v2 LockView', hash=None, agrees=False, error=repr(e)))
    try:
        from live.priors import load_priors
        a = load_priors('Monza').forecast_hash
        out['sources'].append(dict(source='live.priors.load_priors(Monza).forecast_hash', hash=a, agrees=(a == h)))
    except Exception as e:
        out['sources'].append(dict(source='live.priors', hash=None, agrees=False, error=repr(e)))
    fx = PROTO / 'fixtures' / 'lock_v2_fixture.json'
    if fx.exists():
        f = read_json(fx)
        out['fixture_hash'] = f.get('shared', {}).get('forecast_hash')
        out['fixture_note'] = 'the fixture carries its own (synthetic) forecast hash and is labelled FIXTURE on screen; it is not expected to equal the lock'
    out['status'] = 'PASS' if all(s['agrees'] for s in out['sources']) else 'FAIL'
    return out


def run(event: str = 'Monza', driver: str = 'NOR', out: Path | str | None = REPORT_PATH) -> dict:
    rep: dict[str, Any] = dict(generated_at=now_iso(), event=event, driver=driver, checks={})
    for name, fn in (('static_imports', static_checks), ('import_closure', import_closure_checks),
                     ('future_read_and_deny_list_spy', lambda: future_read_spy(event, driver)),
                     ('target_driver_exclusion', lambda: target_driver_exclusion(event, driver)),
                     ('one_forecast_hash', forecast_hash_checks)):
        try:
            rep['checks'][name] = fn()
        except Exception as e:
            rep['checks'][name] = dict(status='FAIL', error=f'{type(e).__name__}: {e}', traceback=traceback.format_exc()[-1200:])
    rep['status'] = 'PASS' if all(c.get('status') == 'PASS' for c in rep['checks'].values()) else 'FAIL'
    rep['exit_code'] = 0 if rep['status'] == 'PASS' else 1
    if out:
        write_json(out, rep)
    return rep


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--event', default='Monza'); ap.add_argument('--driver', default='NOR'); ap.add_argument('--out', default=str(REPORT_PATH))
    a = ap.parse_args(argv)
    rep = run(a.event, a.driver, a.out)
    print(f"leakage audit: {rep['status']} (exit {rep['exit_code']})")
    for name, c in rep['checks'].items():
        print(f"  {c.get('status'):<5} {name}" + (f"  error: {c['error']}" if c.get('error') else ''))
        if name == 'static_imports':
            for r in c.get('rules', []):
                if r['violations']:
                    print(f"        {r['status']} {r['rule']}: " + '; '.join(f"{v['file']}:{v['line']} imports {v['imports']}" for v in r['violations'][:8]))
        if name == 'import_closure':
            for cs in c.get('cases', []):
                print(f"        {cs['status']} {cs['case']}: loaded {cs.get('loaded')}" + (f" stderr {cs['stderr'][:200]}" if cs.get('stderr') else ''))
        if name == 'future_read_and_deny_list_spy' and c.get('status'):
            print(f"        laps {c.get('laps_processed')} feed calls {c.get('feed_calls')} {c.get('calls_by_kind')} violations {c.get('violations')} deny hits {c.get('deny_list_hits')}")
        if name == 'target_driver_exclusion' and c.get('checks'):
            for k, v in c['checks'].items():
                print(f"        {'ok ' if v else 'BAD'} {k}")
        if name == 'one_forecast_hash':
            for s in c.get('sources', []):
                print(f"        {'ok ' if s['agrees'] else 'BAD'} {s['source']} {str(s.get('hash'))[:23]}")
    print(f'report: {a.out}')
    return rep['exit_code']


if __name__ == '__main__':
    sys.exit(main())
