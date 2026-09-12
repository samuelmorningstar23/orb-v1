#!/usr/bin/env python3
"""Ownership audit. Maps every changed path in the repository (git status --porcelain incl. untracked,
git diff --name-only, staged changes) to its owning workstream using the ROADMAP_v5 section 6 directory rules, and flags
(a) paths no workstream owns and (b) paths in the lead-only set. Nobody can tell from the tree who wrote a file, so a
flag means "a human must confirm", not "wrong workstream".

Usage:  python release/ownership_audit.py [--root PROTO_DIR] [--out FILE.json] [--strict] [--paths P ...]
        --strict exits 1 when anything is flagged; --paths classifies the given proto-relative paths without git.
Output: JSON on stdout (and to --out).
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RULES_VERSION = 'roadmap_v5_s6 + workstream9 brief + lead decisions 12 Sep 2026 14:55, 15:05, 20:58 and 22:00 (out/ subtrees, tests/ per workstream, lead-only globs incl. generated documents and the published forecast)'
# Directory rules end with '/'; file rules do not. Longest prefix wins (evaluation/red_team/ beats evaluation/).
RULES = (
    ('schemas/', 1), ('fixtures/', 1), ('validators/', 1), ('shared/', 1), ('tests/contract/', 1),
    ('tests/conftest.py', 1), ('out/lock_v2.json', 1), ('out/lock_v2_sidecars/', 1),          # lead decision: adapter output
    ('counterfactual/', 2), ('events/', 2), ('out/counterfactual/', 2), ('tests/counterfactual/', 2),
    ('evaluation/', 3), ('out/validation/', 3), ('tests/evaluation/', 3),
    ('replay/', 4), ('dashboard/components/', 4), ('out/maps/', 4), ('app_v2/components/race_twin/', 4), ('tests/replay/', 4),
    ('interaction/', 5),
    ('app_v2/', 6), ('ui/', 6), ('theme/', 6), ('views/', 6), ('tests/ui/', 6), ('tests/screenshots/', 6),
    ('evaluation/red_team/', 7), ('tests/red_team/', 7),
    ('live/', 8), ('decision/', 8), ('out/live/', 8), ('tests/live/', 8),
    ('progress/', 9), ('checkpoints/', 9), ('release/', 9), ('tests/release/', 9), ('build_control.py', 9),
)
LEAD_ONLY = {'README.md', 'requirements.txt', 'make_deck_figs.py', 'app.py', 'pipeline.py', 'model_v2.py', 'strategy2.py', 'liquid.py', 'out/lock.json', 'out/results.csv', 'out/validation.csv', 'refresh.sh', 'cleanup_pass.sh'}
# Globs match segment-wise ('*' never crosses '/'), so 'out/*.pdf' means direct children of out/ only.
LEAD_ONLY_GLOBS = ('extract_*.py', 'build_*.py', 'refresh*.log', 'out/*.pptx', 'out/*.pdf', 'out/excluded_*.csv', 'deck_src/*',   # lead decision 12 Sep 20:58: deck source is lead-only
                   'out/CONTEXT_NOTES.md', 'out/THE_CASE.md', 'out/talk_track.md', 'out/ROADMAP.md', 'out/JURY_QUESTIONS.md', 'out/forecast_*.json', 'out/forecast_*.sha256')   # lead decision 12 Sep 22:00: outputs of the lead-only builders (build_case.py, build_manual.py, build_forecast.py)
SEALED_PATTERNS = ('evaluation/holdout/sealed_holdout_manifest.*',)   # lead-only after sealing
WORKSTREAM_NAMES = {1: 'contract and fixtures', 2: 'counterfactual core and events', 3: 'blind evaluation', 4: 'geometry and animation',
               5: 'frozen field', 6: 'dashboard', 7: 'red team', 8: 'live intelligence', 9: 'build control'}


def classify(rel: str) -> dict:
    """Classify a path relative to proto/ (posix separators)."""
    rel = rel.replace(os.sep, '/')
    while rel.startswith('./'):
        rel = rel[2:]
    if rel in LEAD_ONLY:
        return dict(owner='lead', category='lead_only', flagged=True, reason='lead-only file; only the lead edits it')
    for prefix, owner in RULES:                        # exact file rules beat lead-only globs (build_control.py vs build_*.py)
        if not prefix.endswith('/') and rel == prefix:
            return dict(owner=owner, category='workstream', flagged=False, reason=f'owned by workstream {owner} ({WORKSTREAM_NAMES[owner]}: {prefix})')
    if any(_glob(rel, g) for g in SEALED_PATTERNS):
        return dict(owner='lead', category='lead_only', flagged=True, reason='sealed artifact; lead-only after sealing (stop-the-line condition 1 if changed)')
    if any(_glob(rel, g) for g in LEAD_ONLY_GLOBS):
        return dict(owner='lead', category='lead_only', flagged=True, reason='lead-only file; only the lead edits it')
    m = re.fullmatch(r'progress/workstream_(\d+)\.json', rel)     # every workstream writes its own heartbeat into progress/
    if m:
        n = int(m.group(1))
        if n in WORKSTREAM_NAMES:
            return dict(owner=n, category='workstream', flagged=False, reason=f'heartbeat of workstream {n} ({WORKSTREAM_NAMES[n]})')
        return dict(owner=None, category='unowned', flagged=True, reason=f'heartbeat for unknown workstream {n}')
    best = None
    for prefix, owner in RULES:
        hit = rel == prefix or (prefix.endswith('/') and rel.startswith(prefix)) or (not prefix.endswith('/') and rel == prefix)
        if hit and (best is None or len(prefix) > len(best[0])):
            best = (prefix, owner)
    if best:
        return dict(owner=best[1], category='workstream', flagged=False, reason=f'owned by workstream {best[1]} ({WORKSTREAM_NAMES[best[1]]}: {best[0]})')
    return dict(owner=None, category='unowned', flagged=True, reason='no workstream owns this path (lead to confirm)')


def _glob(rel: str, pattern: str) -> bool:
    """Segment-wise glob: same number of '/' parts and every part fnmatch-es, so '*' never crosses a directory."""
    a, b = rel.split('/'), pattern.split('/')
    return len(a) == len(b) and all(fnmatch.fnmatch(x, y) for x, y in zip(a, b))


def _git(args, cwd):
    try:
        r = subprocess.run(['git', *args], cwd=str(cwd), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def changed_paths(repo_root) -> dict:
    """path (relative to the repo root) -> git status code. Union of porcelain (incl. untracked), unstaged and staged diffs."""
    out = _git(['status', '--porcelain=v1', '-z', '--untracked-files=all'], repo_root)
    if out is None:
        raise RuntimeError('git status failed')
    entries, paths, i = out.split('\0'), {}, 0
    while i < len(entries):
        e = entries[i]
        i += 1
        if not e:
            continue
        xy, path = e[:2], e[3:]
        paths[path] = xy.strip() or '??'
        if xy[0] in 'RC' and i < len(entries):      # rename/copy: the next entry is the original path
            paths.setdefault(entries[i], 'R-')
            i += 1
    for args, code in ((['diff', '--name-only', '-z'], 'M'), (['diff', '--name-only', '--cached', '-z'], 'M+')):
        for p in filter(None, (_git(args, repo_root) or '').split('\0')):
            paths.setdefault(p, code)
    return paths


def audit(proto_root, repo_root=None, paths=None) -> dict:
    proto_root = Path(proto_root).resolve()
    rec = dict(at=dt.datetime.now().isoformat(timespec='seconds'), proto_root=str(proto_root), rules_version=RULES_VERSION, changed=[])
    if paths is None:
        top = repo_root or (_git(['rev-parse', '--show-toplevel'], proto_root) or '').strip()
        if not top:
            rec.update(error='not a git repository', summary=_summary([]))
            return rec
        top = Path(top).resolve()
        rec['repo_root'] = str(top)
        rec['git_commit'] = (_git(['rev-parse', '--short', 'HEAD'], top) or '').strip() or None
        changed = changed_paths(top)
        rel_proto = os.path.relpath(proto_root, top).replace(os.sep, '/')
    else:
        changed, rel_proto = {p: '?' for p in paths}, '.'
    for path, code in sorted(changed.items()):
        if rel_proto == '.':
            rel, inside = path, True
        elif path.startswith(rel_proto + '/'):
            rel, inside = path[len(rel_proto) + 1:], True
        else:
            rel, inside = path, False
        c = classify(rel) if inside else (dict(owner='lead/notes', category='coordination', flagged=False, reason='coordination notes (lead decision 12 Sep 20:58)')
                                          if rel.startswith('coordination/') or rel in ('WORKSTREAMS.md', 'INSTRUCTIONS.md')
                                          else dict(owner='lead', category='lead_only', flagged=True, reason='C6 lead-authored repository entry-point README') if rel == 'README.md'
                                          else dict(owner=None, category='outside_proto', flagged=True, reason='outside proto/; no workstream owns repository-root paths (lead to confirm)'))
        rec['changed'].append(dict(path=path, git_status=code, **c))
    rec['summary'] = _summary(rec['changed'])
    rec['flagged_paths'] = [c['path'] for c in rec['changed'] if c['flagged']]
    return rec


def _summary(changed) -> dict:
    by_owner = {}
    for c in changed:
        k = 'unowned' if c['owner'] is None else str(c['owner'])
        by_owner[k] = by_owner.get(k, 0) + 1
    return dict(total=len(changed), flagged=sum(c['flagged'] for c in changed), unowned=sum(c['category'] == 'unowned' for c in changed),
                lead_only=sum(c['category'] == 'lead_only' for c in changed), outside_proto=sum(c['category'] == 'outside_proto' for c in changed),
                by_owner=dict(sorted(by_owner.items())))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--root', default=str(Path(__file__).resolve().parent.parent), help='proto directory')
    ap.add_argument('--out', default=None, help='also write the JSON report here')
    ap.add_argument('--strict', action='store_true', help='exit 1 when any path is flagged')
    ap.add_argument('--paths', nargs='*', default=None, help='classify these proto-relative paths instead of asking git')
    a = ap.parse_args(argv)
    rep = audit(a.root, paths=a.paths)
    text = json.dumps(rep, indent=1)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text + '\n')
    print(text)
    return 1 if (a.strict and rep['summary']['flagged']) else 0


if __name__ == '__main__':
    sys.exit(main())
