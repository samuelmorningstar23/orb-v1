#!/usr/bin/env python3
"""Orb v1 build control (Build Control and Integration Marshal).

Run from proto/ with the project venv python. Commands:

  status [--json] [--no-color]      heartbeat table (stale > 40 min -> AMBER, missing -> flagged), blockers,
                                    merge-queue state, STOP_THE_LINE (red), last checkpoint, last green
  checkpoint Cn DECISION [note]     freeze merge queue, run integration checks, write checkpoints/Cn/
                                    {checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json,
                                    ownership_audit.json, logs/}; unfreeze and update last_green.json on GO.
                                    DECISION: GO | GO_WITH_REASSIGNMENT | ROLLBACK | CUT_FROM_DEMO | HOLD
                                              AUTO      -> checks only; records PENDING + proposed decision,
                                                           queue stays FROZEN until `decide`
                                              REHEARSAL -> full artifact set under checkpoints/rehearsal/Cn/,
                                                           no state (queue, last green) is changed
  decide Cn DECISION [note]         finalise a PENDING checkpoint without re-running the checks
  sign Cn "name"                    reviewer signs the checkpoint report
  checks                            run the integration checks only, print results, write nothing
  stop-the-line "reason" [--by X]   write release/STOP_THE_LINE.json and freeze the merge queue
  clear-stop [note]                 clear it (archived to release/stop_history.jsonl), queue OPEN
  freeze [reason] | unfreeze [note] manual merge-queue control
  rollback --dry-run                show last green commit, worktree plan and diff summary; no side effects
  rollback [--drill]                delegate to release/rollback.sh (creates the last-green worktree)
  heartbeat '<json>'                merge fields into progress/workstream_9.json and stamp updated_at
  summary                           write progress/SUMMARY.md (traffic-light table for the lead)
  active-workstreams 1 6 9 | auto        override / restore the wave-derived set of workstreams expected to heartbeat

Ownership: Workstream 9 writes only progress/, checkpoints/, release/, tests/release/ and this file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

STALE_MIN = 40
PROTO = Path(os.environ.get('ORB_PROTO_ROOT') or Path(__file__).resolve().parent)
WORKTREE = os.environ.get('ORB_LAST_GREEN_WORKTREE', '/private/tmp/orbv1_last_green')
# Waves (ROADMAP_v5 s14.6): 1, 6, 9 first; 2, 4, 8 at C1; 3, 5, 7 from C1 as reviewers, builders from C2.
WAVES = {0: (1, 6, 9), 1: (2, 4, 8), 2: (3, 5, 7)}
HASH_PATHS = (
    'out/lock.json', 'out/lock_v2.json',
    'evaluation/holdout/sealed_holdout_manifest.json', 'evaluation/holdout/sealed_holdout_manifest.sha256',
    'fixtures/lock_v2_fixture.json', 'schemas/lock_v2_minimal.py', 'ui/tokens.py', 'theme/base.css',
)
HOLDOUT_MANIFEST = 'evaluation/holdout/sealed_holdout_manifest.json'
HOLDOUT_SIDECAR = 'evaluation/holdout/sealed_holdout_manifest.sha256'
CONSISTENCY_PROBE = 'evaluation/red_team/consistency_probe.py'   # Workstream 7 provides; exit 0 = lock and dashboard agree
RED_TEAM_REPORT = 'evaluation/red_team/red_team_report.json'
GREEN = ('GO', 'GO_WITH_REASSIGNMENT')
DECISIONS = GREEN + ('ROLLBACK', 'CUT_FROM_DEMO', 'HOLD')
SPECIAL = ('AUTO', 'REHEARSAL')
CHECK_TIMEOUT = int(os.environ.get('ORB_CHECK_TIMEOUT', '900'))
CHECK_ORDER = ('schema_validation', 'pytest', 'ownership_audit', 'lock_dashboard_consistency', 'sealed_holdout_integrity')


# ----------------------------------------------------------------------------- helpers
def now() -> dt.datetime:
    return dt.datetime.now().replace(microsecond=0)


def iso(t: dt.datetime | None = None) -> str:
    return (t or now()).isoformat(timespec='seconds')


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return default


def write_json(path, obj) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=str) + '\n')
    return path


def git(args, cwd, timeout=60):
    """stdout of a git command, or None when git fails or is unavailable."""
    try:
        r = subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def repo_root(root=PROTO):
    out = git(['rev-parse', '--show-toplevel'], root)
    return Path(out) if out else None


def git_commit(root=PROTO, short=True):
    return git(['rev-parse'] + (['--short'] if short else []) + ['HEAD'], root)


def sha256_file(path, n=16) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:n]


def _int(x) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _list(x) -> list:
    if x is None:
        return []
    return list(x) if isinstance(x, (list, tuple)) else [x]


# ----------------------------------------------------------------------------- heartbeats
def parse_time(s):
    if not s:
        return None
    try:
        t = dt.datetime.fromisoformat(str(s))
    except ValueError:
        return None
    if t.tzinfo is not None:
        t = t.astimezone().replace(tzinfo=None)
    return t


def age_minutes(updated_at, now_=None):
    t = parse_time(updated_at)
    return None if t is None else ((now_ or now()) - t).total_seconds() / 60.0


def effective_status(status, age) -> str:
    """Traffic light after applying the staleness rule (> STALE_MIN minutes -> AMBER; RED stays RED)."""
    s = str(status or '').upper()
    if age is None:
        return 'RED (bad updated_at)'
    if age > STALE_MIN:
        return ('RED' if s == 'RED' else 'AMBER') + f' (stale {int(age)} min)'
    return s if s in ('GREEN', 'AMBER', 'RED') else f'RED (bad status {s or "?"})'


def workstream_number(path):
    m = re.search(r'workstream_(\d+)\.json$', str(path))
    return int(m.group(1)) if m else None


def _row(workstream, effective, **kw):
    base = dict(workstream=workstream, status='?', effective=effective, age_min=None, stale=True, task='', tests_passed=0,
                tests_failed=0, eta_minutes=None, blockers=[], needs_review_from=[], completed=[], in_progress=[],
                commit=None, updated_at=None, file=None, missing=False, unreadable=False)
    base.update(kw)
    return base


def load_heartbeats(root=PROTO, now_=None) -> list[dict]:
    rows = []
    files = sorted(Path(root, 'progress').glob('workstream_*.json'), key=lambda p: workstream_number(p) or 0)
    for f in files:
        n = workstream_number(f)
        try:
            h = json.loads(f.read_text())
            if not isinstance(h, dict):
                raise ValueError('heartbeat is not a JSON object')
        except Exception as e:
            rows.append(_row(n, f'RED (unreadable: {e})', file=str(f), unreadable=True))
            continue
        age = age_minutes(h.get('updated_at'), now_)
        rows.append(_row(h.get('workstream', n), effective_status(h.get('status'), age), status=h.get('status', '?'),
                         age_min=None if age is None else round(age, 1), stale=age is None or age > STALE_MIN,
                         task=str(h.get('task', '')), tests_passed=_int(h.get('tests_passed')),
                         tests_failed=_int(h.get('tests_failed')), eta_minutes=h.get('eta_minutes'),
                         blockers=_list(h.get('blockers')), needs_review_from=_list(h.get('needs_review_from')),
                         completed=_list(h.get('completed')), in_progress=_list(h.get('in_progress')),
                         commit=h.get('commit'), updated_at=h.get('updated_at'), file=str(f)))
    return rows


def checkpoint_dirs(root=PROTO) -> list[Path]:
    out = []
    for d in Path(root, 'checkpoints').glob('C*'):
        m = re.fullmatch(r'C(\d+)', d.name)
        if m and (d / 'checkpoint.json').is_file():
            out.append((int(m.group(1)), d))
    return [d for _, d in sorted(out)]


def last_checkpoint(root=PROTO):
    dirs = checkpoint_dirs(root)
    return read_json(dirs[-1] / 'checkpoint.json') if dirs else None


def active_workstreams(root=PROTO) -> list[int]:
    """release/active_workstreams.json overrides; otherwise derived from the waves and the last green checkpoint."""
    ov = read_json(Path(root, 'release', 'active_workstreams.json'))
    if isinstance(ov, dict) and isinstance(ov.get('active'), list):
        return sorted({int(a) for a in ov['active']})
    n = -1
    for d in checkpoint_dirs(root):
        rec = read_json(d / 'checkpoint.json') or {}
        if str(rec.get('decision', '')).upper() in GREEN:
            n = int(d.name[1:])
    active = set(WAVES[0])
    for wave, workstreams in WAVES.items():
        if wave <= n:
            active.update(workstreams)
    return sorted(active)


# ----------------------------------------------------------------------------- merge queue / stop the line
def get_queue(root=PROTO) -> dict:
    return read_json(Path(root, 'release', 'merge_queue.json')) or dict(state='OPEN', reason='never frozen', since=None, by=None)


def set_queue(root, state, reason, by='workstream 9') -> dict:
    q = dict(state=state, reason=reason, since=iso(), by=by)
    write_json(Path(root, 'release', 'merge_queue.json'), q)
    return q


def get_stop(root=PROTO):
    return read_json(Path(root, 'release', 'STOP_THE_LINE.json'))


def stop_the_line(root, reason, by='workstream 9') -> dict:
    rec = dict(reason=reason, at=iso(), by=by, at_commit=git_commit(root))
    write_json(Path(root, 'release', 'STOP_THE_LINE.json'), rec)
    set_queue(root, 'FROZEN', f'stop-the-line: {reason}', by)
    return rec


def clear_stop(root, note='', by='workstream 9'):
    p = Path(root, 'release', 'STOP_THE_LINE.json')
    rec = read_json(p)
    if rec is None:
        return None
    rec.update(cleared_at=iso(), cleared_by=by, clear_note=note)
    with open(Path(root, 'release', 'stop_history.jsonl'), 'a') as f:
        f.write(json.dumps(rec) + '\n')
    p.unlink()
    set_queue(root, 'OPEN', f'stop cleared: {note or rec["reason"]}', by)
    return rec


# ----------------------------------------------------------------------------- status
def status_report(root=PROTO, now_=None) -> dict:
    now_ = now_ or now()
    rows = load_heartbeats(root, now_)
    active = active_workstreams(root)
    present = {r['workstream'] for r in rows}
    for a in active:
        if a not in present:
            rows.append(_row(a, 'MISSING (no heartbeat)', missing=True))
    rows.sort(key=lambda r: (r['workstream'] if isinstance(r['workstream'], int) else 99))
    lc = last_checkpoint(root)
    return dict(at=iso(now_), active_workstreams=active, heartbeats=rows,
                missing=[r['workstream'] for r in rows if r['missing']],
                stale=[r['workstream'] for r in rows if r['stale'] and not r['missing']],
                blockers={str(r['workstream']): r['blockers'] for r in rows if r['blockers']},
                stop=get_stop(root), queue=get_queue(root),
                last_checkpoint=lc and {k: lc.get(k) for k in ('checkpoint', 'decision', 'proposed', 'at', 'git_commit', 'all_green')},
                last_green=read_json(Path(root, 'checkpoints', 'last_green.json')))


def _color_enabled() -> bool:
    return sys.stdout.isatty() and not os.environ.get('NO_COLOR')


def paint(txt, code, enabled) -> str:
    return f'\033[{code}m{txt}\033[0m' if enabled else txt


def light_code(effective: str) -> str:
    return {'GREEN': '32', 'AMBER': '33'}.get(effective.split()[0], '31')


def render_status(rep: dict, color=None) -> str:
    color = _color_enabled() if color is None else color
    L = []
    if rep['stop']:
        s = rep['stop']
        L.append(paint(f"!!! STOP THE LINE !!! since {s.get('at')} by {s.get('by')}: {s.get('reason')}   (clear with: build_control.py clear-stop)", '1;31', color))
    q = rep['queue']
    L.append(f"merge queue: {q.get('state')} ({q.get('reason')}; since {q.get('since') or '-'})")
    lc = rep['last_checkpoint']
    L.append('last checkpoint: ' + (f"{lc['checkpoint']} {lc['decision']}" + (f" (proposed {lc['proposed']})" if lc.get('decision') == 'PENDING' else '')
                                     + f" at {lc['at']} commit {lc['git_commit']}" if lc else 'none'))
    lg = rep['last_green']
    L.append('last green: ' + (f"{lg.get('checkpoint')} commit {lg.get('git_commit')} at {lg.get('at')}" if lg else 'none'))
    L.append(f"active workstreams: {rep['active_workstreams']}   stale threshold {STALE_MIN} min   now {rep['at']}")
    hdr = f"{'workstream':>5}  {'status':24s} {'age':>5}  {'task':34s} {'tests':>7}  {'eta':>5}  blockers / needs review"
    L += [hdr, '-' * len(hdr)]
    for r in rep['heartbeats']:
        age = '-' if r['age_min'] is None else f"{r['age_min']:.0f}m"
        tests = f"{r['tests_passed']}/{r['tests_passed'] + r['tests_failed']}"
        eta = '?' if r['eta_minutes'] in (None, '') else str(r['eta_minutes'])
        extra = '; '.join(map(str, r['blockers'])) or '-'
        if r['needs_review_from']:
            extra += f"  review: {','.join(map(str, r['needs_review_from']))}"
        L.append(f"{str(r['workstream']):>5}  {paint(r['effective'][:24].ljust(24), light_code(r['effective']), color)} {age:>5}  "
                 f"{r['task'][:34]:34s} {tests:>7}  {eta:>5}  {extra[:70]}")
    if rep['missing']:
        L.append(paint(f"MISSING heartbeats: workstreams {rep['missing']} (active, no progress/workstream_N.json)", '31', color))
    if rep['stale']:
        L.append(paint(f"STALE heartbeats (> {STALE_MIN} min): workstreams {rep['stale']}", '33', color))
    if rep['blockers']:
        L.append('blockers: ' + '; '.join(f"workstream {a}: {', '.join(map(str, b))}" for a, b in rep['blockers'].items()))
    return '\n'.join(L)


# ----------------------------------------------------------------------------- integration checks
def run_cmd(args, cwd, timeout=CHECK_TIMEOUT) -> dict:
    t0 = dt.datetime.now()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    try:
        r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env)
        rc, out, err, to = r.returncode, r.stdout, r.stderr, False
    except subprocess.TimeoutExpired as e:
        rc, out, err, to = -1, _s(e.stdout), _s(e.stderr), True
    except OSError as e:
        rc, out, err, to = -2, '', str(e), False
    return dict(returncode=rc, stdout=out or '', stderr=err or '', duration_s=round((dt.datetime.now() - t0).total_seconds(), 2), timed_out=to)


def _s(x) -> str:
    return x.decode(errors='replace') if isinstance(x, bytes) else (x or '')


def _tail(s, n=40) -> str:
    return '\n'.join((s or '').splitlines()[-n:])


def _check(name, status, note='', command=None, res=None, **extra) -> dict:
    d = dict(name=name, status=status, note=note, command=command)
    if res:
        d.update(returncode=res['returncode'], duration_s=res['duration_s'], timed_out=res['timed_out'],
                 stdout_tail=_tail(res['stdout']), stderr_tail=_tail(res['stderr']), _log=res['stdout'] + ('\n--- stderr ---\n' + res['stderr'] if res['stderr'] else ''))
    d.update(extra)
    return d


def check_schema(root) -> dict:
    v, lock = Path(root, 'validators', 'validate_lock.py'), Path(root, 'out', 'lock_v2.json')
    if not v.is_file() or not lock.is_file():
        missing = [str(p.relative_to(root)) for p in (v, lock) if not p.is_file()]
        return _check('schema_validation', 'SKIP', 'skipped, missing: ' + ', '.join(missing) + ' (Workstream 1 provides the validator; lock_v2.json comes from the pipeline)')
    cmd = [sys.executable, 'validators/validate_lock.py', 'out/lock_v2.json']
    res = run_cmd(cmd, root)
    return _check('schema_validation', 'PASS' if res['returncode'] == 0 else 'FAIL', '' if res['returncode'] == 0 else f"validator exit {res['returncode']}", ' '.join(cmd), res)


PYTEST_RE = re.compile(r'(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|warnings?|deselected)')


def parse_pytest_summary(text) -> dict:
    counts = {}
    for line in reversed((text or '').splitlines()):
        if re.search(r'\bin [\d.]+s\b', line) and re.search(r'\b(passed|failed|error|no tests ran)\b', line):
            for n, k in PYTEST_RE.findall(line):
                counts[{'error': 'errors', 'warning': 'warnings'}.get(k, k)] = int(n)
            if 'no tests ran' in line:
                counts.setdefault('passed', 0)
            break
    return counts


def check_pytest(root) -> dict:
    tests = Path(root, 'tests')
    if not tests.is_dir():
        return _check('pytest', 'SKIP', 'tests/ directory missing', counts={}, test_dirs=[])
    dirs = sorted(d.name for d in tests.iterdir() if d.is_dir() and not d.name.startswith(('_', '.')))
    cmd = [sys.executable, '-m', 'pytest', 'tests', '-q', '-p', 'no:cacheprovider', '--color=no']
    res = run_cmd(cmd, root)
    rc = res['returncode']
    status = 'PASS' if rc == 0 else 'SKIP' if rc == 5 else 'FAIL'
    note = {0: '', 5: 'no tests collected'}.get(rc, f'pytest exit code {rc}')
    if res['timed_out']:
        status, note = 'FAIL', f'timed out after {CHECK_TIMEOUT}s'
    return _check('pytest', status, note, ' '.join(cmd), res, counts=parse_pytest_summary(res['stdout']), test_dirs=dirs)


def _ownership_module():
    path = Path(__file__).resolve().parent / 'release' / 'ownership_audit.py'
    spec = importlib.util.spec_from_file_location('ownership_audit', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_ownership(root, out_path=None) -> dict:
    try:
        rep = _ownership_module().audit(root)
    except Exception as e:  # the audit must never take the checkpoint down
        return _check('ownership_audit', 'FAIL', f'audit crashed: {e!r}')
    if out_path:
        write_json(out_path, rep)
    if rep.get('error'):
        return _check('ownership_audit', 'SKIP', rep['error'], 'release/ownership_audit.py', summary=rep['summary'])
    flagged = [c['path'] for c in rep['changed'] if c['flagged']]
    note = f"{rep['summary']['total']} changed paths, {len(flagged)} flagged" + (': ' + ', '.join(flagged)[:600] if flagged else '')
    return _check('ownership_audit', 'PASS' if not flagged else 'WARN', note, 'release/ownership_audit.py', summary=rep['summary'], flagged=flagged)


def check_consistency_probe(root) -> dict:
    probe = Path(root, CONSISTENCY_PROBE)
    if not probe.is_file():
        return _check('lock_dashboard_consistency', 'NOT_IMPLEMENTED', f'not implemented: Workstream 7 provides {CONSISTENCY_PROBE} (exit 0 = lock and dashboard agree)')
    cmd = [sys.executable, CONSISTENCY_PROBE]
    res = run_cmd(cmd, root)
    return _check('lock_dashboard_consistency', 'PASS' if res['returncode'] == 0 else 'FAIL', '' if res['returncode'] == 0 else f"probe exit {res['returncode']}", ' '.join(cmd), res)


def check_holdout_integrity(root) -> dict:
    """Stop-the-line condition 1: the sealed holdout must not change. Manifest vs .sha256 sidecar vs last green."""
    m, s = Path(root, HOLDOUT_MANIFEST), Path(root, HOLDOUT_SIDECAR)
    if not m.is_file():
        return _check('sealed_holdout_integrity', 'SKIP', f'{HOLDOUT_MANIFEST} missing')
    full = sha256_file(m, 64)
    problems = []
    recorded = (s.read_text().split() or [''])[0] if s.is_file() else None
    if recorded is None:
        problems.append(f'sidecar {HOLDOUT_SIDECAR} missing')
    elif recorded != full:
        problems.append('manifest does not match its .sha256 sidecar')
    lg = read_json(Path(root, 'checkpoints', 'last_green.json')) or {}
    prev = read_json(Path(root, 'checkpoints', str(lg.get('checkpoint', '')), 'artifact_hashes.json')) or {}
    if prev.get(HOLDOUT_MANIFEST) and prev[HOLDOUT_MANIFEST] != full[:16]:
        problems.append(f"manifest changed since last green {lg.get('checkpoint')} (sealed holdout opened or re-sealed; lead must confirm)")
    return _check('sealed_holdout_integrity', 'FAIL' if problems else 'PASS', '; '.join(problems), sha256=full)


def run_checks(root=PROTO, out_dir=None, echo=True) -> list[dict]:
    out_dir = Path(out_dir) if out_dir else None
    steps = [('schema_validation', lambda: check_schema(root)),
             ('pytest', lambda: check_pytest(root)),
             ('ownership_audit', lambda: check_ownership(root, out_dir / 'ownership_audit.json' if out_dir else None)),
             ('lock_dashboard_consistency', lambda: check_consistency_probe(root)),
             ('sealed_holdout_integrity', lambda: check_holdout_integrity(root))]
    results = []
    for i, (name, fn) in enumerate(steps, 1):
        if echo:
            print(f'[{i}/{len(steps)}] {name} ...', end=' ', flush=True)
        try:
            c = fn()
        except Exception as e:
            c = _check(name, 'FAIL', f'check crashed: {e!r}')
        log = c.pop('_log', None)
        if out_dir and log is not None:
            p = out_dir / 'logs' / f'{name}.txt'   # .txt: the repo ignores *.log and the checkpoint record must be committable
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(log)
            c['log'] = str(p.relative_to(out_dir.parent.parent)) if out_dir.is_relative_to(out_dir.parent.parent) else str(p)
        results.append(c)
        if echo:
            print(c['status'] + (f" - {c['note']}" if c['note'] else '') + (f" ({c['duration_s']}s)" if c.get('duration_s') is not None else ''))
    return results


def all_green(checks) -> bool:
    return not any(c['status'] == 'FAIL' for c in checks)


def summarize(checks) -> dict:
    out = {}
    for c in checks:
        out[c['status']] = out.get(c['status'], 0) + 1
    return out


def artifact_hashes(root=PROTO) -> dict:
    return {p: sha256_file(Path(root, p)) for p in HASH_PATHS if Path(root, p).is_file()}


def hash_diff(cur: dict, prev: dict) -> dict:
    return dict(changed=[k for k in cur if k in prev and prev[k] != cur[k]], added=[k for k in cur if k not in prev], removed=[k for k in prev if k not in cur])


# ----------------------------------------------------------------------------- checkpoints
def render_checkpoint_md(rec: dict, tr: dict) -> str:
    name, dec = rec['checkpoint'], rec['decision']
    L = [f"# {name}: {dec}" + (f" (proposed {rec.get('proposed')})" if dec == 'PENDING' else ''), '']
    if rec.get('note'):
        L += [rec['note'], '']
    if rec.get('decision_note'):
        L += [f"Decision note: {rec['decision_note']}", '']
    prev = rec.get('previous_green') or {}
    L += [f"- at: {rec['at']}",
          f"- commit: {rec.get('git_commit')} (branch {rec.get('git_branch')}, {rec.get('git_dirty_paths', 0)} uncommitted paths)",
          f"- decided by: {rec.get('decided_by')}" + (f" at {rec['decided_at']}" if rec.get('decided_at') else ''),
          f"- checks green: {rec.get('all_green')}",
          f"- previous green: {prev.get('checkpoint')} at {prev.get('git_commit')}" if prev else '- previous green: none',
          f"- active workstreams: {rec.get('active_workstreams')}; missing heartbeats: {rec.get('missing_heartbeats') or 'none'}; stale: {rec.get('stale_heartbeats') or 'none'}"]
    if rec.get('signed_by'):
        L.append(f"- signed: {rec['signed_by']} at {rec['signed_at']}")
    if rec.get('decision_overrides_checks'):
        L += ['', '**WARNING: a green decision was recorded although a check FAILED (decision_overrides_checks).**']
    if rec.get('stop_the_line'):
        L += ['', f"**STOP THE LINE active: {rec['stop_the_line'].get('reason')} (since {rec['stop_the_line'].get('at')})**"]
    L += ['', '## Integration checks', '', '| check | status | note |', '|---|---|---|']
    for c in rec.get('checks', []):
        L.append(f"| {c['name']} | {c['status']} | {(c.get('note') or '').replace('|', '/')} |")
    py = tr.get('pytest') or {}
    if py:
        L += ['', 'pytest: ' + ', '.join(f'{k} {v}' for k, v in py.items()) + f"; test dirs {tr.get('test_dirs')}"]
    L += ['', f"## Artifact hashes (sha256[:16], compared with last green {prev.get('checkpoint') if prev else 'none'})", '']
    hc = rec.get('hash_changes_since_last_green') or {}
    for k, v in rec.get('artifact_hashes', {}).items():
        mark = ' (CHANGED)' if k in hc.get('changed', []) else ' (new)' if k in hc.get('added', []) else ''
        L.append(f"- {k}: {v}{mark}")
    for k in hc.get('removed', []):
        L.append(f"- {k}: REMOVED")
    L += ['', '## Heartbeats', '', '| workstream | status | age min | task | tests | eta | blockers |', '|---|---|---|---|---|---|---|']
    for r in rec.get('heartbeats', []):
        L.append(f"| {r['workstream']} | {r['effective']} | {r['age_min'] if r['age_min'] is not None else '-'} | {r['task'][:40]} | "
                 f"{r['tests_passed']}/{r['tests_passed'] + r['tests_failed']} | {r['eta_minutes']} | {'; '.join(map(str, r['blockers'])) or '-'} |")
    own = next((c for c in rec.get('checks', []) if c['name'] == 'ownership_audit'), None)
    if own:
        L += ['', '## Ownership audit', '', f"{own['status']}: {own.get('note', '')}"]
    L += ['', f"merge queue before checkpoint: {(rec.get('merge_queue_before') or {}).get('state')}",
          f"artifacts: {rec.get('directory')}/ (checkpoint.json, checkpoint.md, test_report.json, artifact_hashes.json, ownership_audit.json, logs/)", '']
    return '\n'.join(L)


def apply_decision(root, rec: dict, cdir: Path, echo=True) -> int:
    """Side effects of a decision: last-green registry and merge queue. Returns the process exit code."""
    name, final = rec['checkpoint'], rec['decision']
    if rec.get('rehearsal'):
        if echo:
            print(f'{name} REHEARSAL recorded under {cdir} (no decision, queue and last green untouched)')
        return 0
    if final in GREEN:
        lg = dict(checkpoint=name, git_commit=rec.get('git_commit'), at=rec['at'], decision=final)
        write_json(Path(root, 'checkpoints', 'last_green.json'), lg)
        write_json(cdir / 'last_green.json', lg)
        set_queue(root, 'OPEN', f'{name} {final}')
        rc = 0
    elif final == 'PENDING':
        set_queue(root, 'FROZEN', f"{name} pending lead decision (checks {'green' if rec.get('all_green') else 'RED'}; proposed {rec.get('proposed')})")
        rc = 3
    else:
        set_queue(root, 'FROZEN', f'{name} {final}; awaiting GO')
        rc = 2
    if echo:
        q = get_queue(root)
        print(f"{name} recorded: {final} at commit {rec.get('git_commit')}; merge queue {q['state']} ({q['reason']})")
        if rec.get('decision_overrides_checks'):
            print('WARNING: green decision recorded although a check FAILED (decision_overrides_checks=true)')
        if final == 'PENDING':
            print(f"next: python build_control.py decide {name} GO|GO_WITH_REASSIGNMENT|ROLLBACK|CUT_FROM_DEMO|HOLD 'note'")
    return rc


def checkpoint(name: str, decision: str, note: str = '', root=PROTO, by='lead', echo=True) -> dict:
    root = Path(root)
    if not re.fullmatch(r'C\d+', name):
        raise SystemExit(f'bad checkpoint name {name!r} (expected C0 .. C7)')
    decision = decision.upper()
    if decision not in DECISIONS + SPECIAL:
        raise SystemExit(f'bad decision {decision!r}; one of {DECISIONS + SPECIAL}')
    rehearsal = decision == 'REHEARSAL'
    cdir = Path(root, 'checkpoints', 'rehearsal', name) if rehearsal else Path(root, 'checkpoints', name)
    cdir.mkdir(parents=True, exist_ok=True)
    prev_queue = get_queue(root)
    if not rehearsal:
        set_queue(root, 'FROZEN', f'checkpoint {name} in progress')
    if echo:
        print(f"== checkpoint {name} ({decision}) at {iso()} == merge queue {'untouched (rehearsal)' if rehearsal else 'FROZEN'}")
    checks = run_checks(root, cdir, echo)
    green = all_green(checks)
    proposed = 'GO' if green else 'HOLD'
    if decision == 'AUTO':
        final, decided_by = 'PENDING', 'auto (checks only; lead decides with build_control.py decide)'
    elif rehearsal:
        final, decided_by = 'REHEARSAL', 'none (rehearsal; nothing decided)'
    else:
        final, decided_by = decision, by
    hashes = artifact_hashes(root)
    lg = read_json(Path(root, 'checkpoints', 'last_green.json')) or {}
    prev_hashes = read_json(Path(root, 'checkpoints', str(lg.get('checkpoint', '')), 'artifact_hashes.json')) or {}
    rep = status_report(root)
    dirty = git(['status', '--porcelain', '--untracked-files=all'], root)
    rec = dict(checkpoint=name, decision=final, proposed=proposed, note=note, at=iso(), git_commit=git_commit(root),
               git_branch=git(['branch', '--show-current'], root), git_dirty_paths=len(dirty.splitlines()) if dirty else 0,
               decided_by=decided_by, all_green=green, decision_overrides_checks=(final in GREEN and not green),
               checks=[{k: v for k, v in c.items() if k not in ('stdout_tail', 'stderr_tail')} for c in checks],
               artifact_hashes=hashes, hash_changes_since_last_green=hash_diff(hashes, prev_hashes), previous_green=lg or None,
               active_workstreams=rep['active_workstreams'], missing_heartbeats=rep['missing'], stale_heartbeats=rep['stale'],
               heartbeats=rep['heartbeats'], stop_the_line=rep['stop'], merge_queue_before=prev_queue, rehearsal=rehearsal,
               directory=str(cdir.relative_to(root)))
    py = next((c for c in checks if c['name'] == 'pytest'), {})
    tr = dict(checkpoint=name, at=rec['at'], git_commit=rec['git_commit'], all_green=green, summary=summarize(checks),
              pytest=py.get('counts', {}), test_dirs=py.get('test_dirs', []), checks=checks)
    write_json(cdir / 'checkpoint.json', rec)
    write_json(cdir / 'artifact_hashes.json', hashes)
    write_json(cdir / 'test_report.json', tr)
    if not (cdir / 'ownership_audit.json').is_file():
        write_json(cdir / 'ownership_audit.json', dict(error='ownership audit did not run', checked_at=rec['at']))
    rt = Path(root, RED_TEAM_REPORT)
    if rt.is_file():
        shutil.copy(rt, cdir / 'red_team_report.json')
    (cdir / 'checkpoint.md').write_text(render_checkpoint_md(rec, tr))
    if echo:
        print(f"checks: {summarize(checks)}  green={green}  hashes changed since last green: {rec['hash_changes_since_last_green']['changed'] or 'none'}")
        if rep['missing'] or rep['stale']:
            print(f"heartbeats: missing {rep['missing'] or 'none'}, stale {rep['stale'] or 'none'}")
    rec['exit_code'] = apply_decision(root, rec, cdir, echo)
    return rec


def decide(name: str, decision: str, note: str = '', root=PROTO, by='lead', echo=True) -> dict:
    root = Path(root)
    cdir = Path(root, 'checkpoints', name)
    rec = read_json(cdir / 'checkpoint.json')
    if not rec:
        raise SystemExit(f'no checkpoint record at {cdir}/checkpoint.json (run: build_control.py checkpoint {name} AUTO)')
    decision = decision.upper()
    if decision not in DECISIONS:
        raise SystemExit(f'bad decision {decision!r}; one of {DECISIONS}')
    rec.update(decision=decision, decided_by=by, decided_at=iso(), decision_note=note,
               decision_overrides_checks=(decision in GREEN and not rec.get('all_green', False)))
    write_json(cdir / 'checkpoint.json', rec)
    (cdir / 'checkpoint.md').write_text(render_checkpoint_md(rec, read_json(cdir / 'test_report.json') or {}))
    rec['exit_code'] = apply_decision(root, rec, cdir, echo)
    return rec


def sign(name: str, signer: str, root=PROTO) -> dict:
    cdir = Path(root, 'checkpoints', name)
    rec = read_json(cdir / 'checkpoint.json')
    if not rec:
        raise SystemExit(f'no checkpoint record at {cdir}/checkpoint.json')
    rec.update(signed_by=signer, signed_at=iso())
    write_json(cdir / 'checkpoint.json', rec)
    with open(cdir / 'checkpoint.md', 'a') as f:
        f.write(f"\nSigned: {signer} at {rec['signed_at']}\n")
    return rec


# ----------------------------------------------------------------------------- heartbeat / summary / rollback
def write_heartbeat(root, fields: dict, workstream=9) -> dict:
    p = Path(root, 'progress', f'workstream_{workstream}.json')
    h = read_json(p) or dict(workstream=workstream, task='build_control', status='GREEN', commit=None, completed=[], in_progress=[],
                             blockers=[], tests_passed=0, tests_failed=0, eta_minutes=0, needs_review_from=['lead'])
    h.update(fields)
    h['workstream'] = workstream
    h['updated_at'] = iso()
    write_json(p, h)
    return h


def write_summary(root=PROTO) -> Path:
    rep = status_report(root)
    q, lc, lg, stop = rep['queue'], rep['last_checkpoint'], rep['last_green'], rep['stop']
    L = [f"# Orb v1 build status at {rep['at']}", '',
         f"Merge queue: **{q.get('state')}** ({q.get('reason')}). "
         + (f"**STOP THE LINE since {stop.get('at')}: {stop.get('reason')}**. " if stop else 'Stop-the-line: none. ')
         + ('Last checkpoint: ' + (f"{lc['checkpoint']} {lc['decision']} at {lc['at']} (commit {lc['git_commit']})" if lc else 'none') + '. ')
         + ('Last green: ' + (f"{lg.get('checkpoint')} at commit {lg.get('git_commit')}" if lg else 'none') + '.'),
         '', f"Active workstreams: {rep['active_workstreams']}. Stale threshold {STALE_MIN} min.", '',
         '| Workstream | Light | Status | Age (min) | Task | Tests | ETA (min) | Blockers | Needs review from |',
         '|---|---|---|---|---|---|---|---|---|']
    for r in rep['heartbeats']:
        L.append(f"| {r['workstream']} | {r['effective'].split()[0]} | {r['effective']} | {r['age_min'] if r['age_min'] is not None else '-'} | {r['task'][:48]} | "
                 f"{r['tests_passed']}/{r['tests_passed'] + r['tests_failed']} | {r['eta_minutes'] if r['eta_minutes'] is not None else '?'} | "
                 f"{'; '.join(map(str, r['blockers'])) or '-'} | {', '.join(map(str, r['needs_review_from'])) or '-'} |")
    L += ['', '## Notes for the lead', '']
    notes = [f"- Workstream {a}: no heartbeat file (progress/workstream_{a}.json) although active; Workstream 9 cannot message workstreams, lead to ping." for a in rep['missing']]
    notes += [f"- Workstream {r['workstream']}: heartbeat stale ({r['age_min']:.0f} min > {STALE_MIN}); lead to ping." for r in rep['heartbeats'] if r['stale'] and not r['missing'] and r['age_min'] is not None]
    notes += [f"- Workstream {r['workstream']}: heartbeat unreadable or bad timestamp ({r['effective']})." for r in rep['heartbeats'] if r['unreadable'] or (r['age_min'] is None and not r['missing'])]
    notes += [f"- Workstream {a} blockers: {', '.join(map(str, b))}" for a, b in rep['blockers'].items()]
    if stop:
        notes.append(f"- STOP THE LINE is active (raised by {stop.get('by')}); no production writes until cleared and a checkpoint says GO.")
    if lc and lc.get('decision') == 'PENDING':
        notes.append(f"- {lc['checkpoint']} awaits the lead decision (proposed {lc.get('proposed')}): python build_control.py decide {lc['checkpoint']} GO 'note'")
    L += notes or ['- No missing, stale or blocked workstreams.']
    L.append('')
    p = Path(root, 'progress', 'SUMMARY.md')
    p.write_text('\n'.join(L))
    return p


def rollback_dry_run(root=PROTO, worktree=WORKTREE) -> int:
    lg = read_json(Path(root, 'checkpoints', 'last_green.json'))
    if not lg:
        print('no checkpoints/last_green.json; nothing to roll back to')
        return 1
    sha = git(['rev-parse', '--verify', '--quiet', f"{lg.get('git_commit')}^{{commit}}"], root)
    print(f"last green: {lg.get('checkpoint')} commit {lg.get('git_commit')} ({sha or 'NOT FOUND in this repository'}) recorded {lg.get('at')}")
    print(f"worktree path: {worktree} ({'exists' if Path(worktree).exists() else 'absent'})")
    if not sha:
        return 1
    stat = git(['diff', '--stat=110', sha], root)
    untracked = git(['ls-files', '--others', '--exclude-standard'], root) or ''
    print('diff summary, working tree vs last green (tracked files):')
    print(stat or '(no tracked differences)')
    print(f"untracked files not in last green: {len(untracked.splitlines())}")
    print('plan (dry run, nothing done): release/rollback.sh adds a detached git worktree of that commit at the path above and prints this summary;')
    print('the main working tree is never modified. --drill also verifies proto/out/lock.json parses inside the worktree, then removes it.')
    return 0


# ----------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default=None, help='proto directory (default: directory of this file or $ORB_PROTO_ROOT)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('status'); s.add_argument('--json', action='store_true'); s.add_argument('--no-color', action='store_true')
    for cmd in ('checkpoint', 'decide'):
        c = sub.add_parser(cmd); c.add_argument('name'); c.add_argument('decision'); c.add_argument('note', nargs='?', default=''); c.add_argument('--by', default='lead')
    sg = sub.add_parser('sign'); sg.add_argument('name'); sg.add_argument('signer')
    sub.add_parser('checks')
    st = sub.add_parser('stop-the-line'); st.add_argument('reason'); st.add_argument('--by', default='workstream 9')
    cs = sub.add_parser('clear-stop'); cs.add_argument('note', nargs='?', default='')
    fr = sub.add_parser('freeze'); fr.add_argument('reason', nargs='?', default='manual freeze')
    uf = sub.add_parser('unfreeze'); uf.add_argument('note', nargs='?', default='manual unfreeze')
    rb = sub.add_parser('rollback'); rb.add_argument('--dry-run', action='store_true'); rb.add_argument('--drill', action='store_true')
    hb = sub.add_parser('heartbeat'); hb.add_argument('fields', nargs='?', default='{}')
    sub.add_parser('summary')
    aa = sub.add_parser('active-workstreams'); aa.add_argument('workstreams', nargs='+')
    a = ap.parse_args(argv)
    root = Path(a.root).resolve() if a.root else PROTO

    if a.cmd == 'status':
        rep = status_report(root)
        print(json.dumps(rep, indent=1, default=str) if a.json else render_status(rep, color=False if a.no_color else None))
        return 0
    if a.cmd == 'checkpoint':
        return checkpoint(a.name, a.decision, a.note, root=root, by=a.by)['exit_code']
    if a.cmd == 'decide':
        return decide(a.name, a.decision, a.note, root=root, by=a.by)['exit_code']
    if a.cmd == 'sign':
        rec = sign(a.name, a.signer, root); print(f"{a.name} signed by {a.signer} at {rec['signed_at']}"); return 0
    if a.cmd == 'checks':
        checks = run_checks(root, None, echo=True)
        print(f'summary: {summarize(checks)}  green={all_green(checks)}')
        return 0 if all_green(checks) else 1
    if a.cmd == 'stop-the-line':
        rec = stop_the_line(root, a.reason, a.by)
        print(f"STOP THE LINE raised at {rec['at']} by {rec['by']}: {rec['reason']} (merge queue FROZEN)"); return 0
    if a.cmd == 'clear-stop':
        rec = clear_stop(root, a.note)
        print('no STOP_THE_LINE active' if rec is None else f"stop cleared ({rec['reason']}); merge queue OPEN"); return 0
    if a.cmd == 'freeze':
        q = set_queue(root, 'FROZEN', a.reason); print(f"merge queue FROZEN ({q['reason']})"); return 0
    if a.cmd == 'unfreeze':
        q = set_queue(root, 'OPEN', a.note); print(f"merge queue OPEN ({q['reason']})"); return 0
    if a.cmd == 'rollback':
        if a.dry_run:
            return rollback_dry_run(root)
        script = Path(root, 'release', 'rollback.sh')
        return subprocess.call(['bash', str(script)] + (['--drill'] if a.drill else []))
    if a.cmd == 'heartbeat':
        h = write_heartbeat(root, json.loads(a.fields)); print(f"workstream 9 heartbeat written ({h['status']}, {h['updated_at']})"); return 0
    if a.cmd == 'summary':
        p = write_summary(root); print(f'wrote {p}'); return 0
    if a.cmd == 'active-workstreams':
        p = Path(root, 'release', 'active_workstreams.json')
        if a.workstreams == ['auto']:
            p.unlink(missing_ok=True); print(f'active workstreams derived from waves: {active_workstreams(root)}')
        else:
            write_json(p, dict(active=sorted({int(x) for x in a.workstreams}), set_at=iso())); print(f'active workstreams override: {active_workstreams(root)}')
        return 0
    return 2


if __name__ == '__main__':
    sys.exit(main())
