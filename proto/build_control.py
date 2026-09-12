"""Workstream 9 tooling: summarise heartbeats, flag stale ones, write a checkpoint record. Usage: python build_control.py status | checkpoint C1 GO 'note'"""
import json, glob, os, sys, datetime as dt, subprocess, hashlib
def status():
    now = dt.datetime.now(); rows = []
    for f in sorted(glob.glob('progress/workstream_*.json')):
        h = json.load(open(f)); age = (now - dt.datetime.fromisoformat(h['updated_at'])).total_seconds() / 60
        st = h['status'] if age <= 40 else 'AMBER (stale %d min)' % age
        rows.append(f"workstream {h['workstream']:>2} {st:22s} {h['task'][:34]:34s} tests {h.get('tests_passed', 0)}/{h.get('tests_passed', 0) + h.get('tests_failed', 0)} eta {h.get('eta_minutes', '?')} min blockers {h.get('blockers', [])}")
    print('\n'.join(rows) if rows else 'no heartbeats yet')
def checkpoint(name, decision, note=''):
    os.makedirs(f'checkpoints/{name}', exist_ok=True)
    commit = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, cwd='..').stdout.strip() or None
    hashes = {p: hashlib.sha256(open(p, 'rb').read()).hexdigest()[:16] for p in ['out/lock.json', 'evaluation/holdout/sealed_holdout_manifest.json', 'fixtures/lock_v2_fixture.json', 'ui/tokens.py'] if os.path.exists(p)}
    rec = dict(checkpoint=name, decision=decision, note=note, at=dt.datetime.now().isoformat(timespec='seconds'), git_commit=commit, artifact_hashes=hashes, heartbeats=[json.load(open(f)) for f in sorted(glob.glob('progress/workstream_*.json'))])
    json.dump(rec, open(f'checkpoints/{name}/checkpoint.json', 'w'), indent=1); json.dump(hashes, open(f'checkpoints/{name}/artifact_hashes.json', 'w'), indent=1)
    if decision.startswith('GO'): json.dump(dict(checkpoint=name, git_commit=commit, at=rec['at']), open('checkpoints/last_green.json', 'w'), indent=1)
    open(f'checkpoints/{name}/checkpoint.md', 'w').write(f"# {name}: {decision}\n\n{note}\n\ncommit {commit}\n\n" + '\n'.join(f"- {k}: {v}" for k, v in hashes.items()) + '\n'); print(f'{name} recorded: {decision} at commit {commit}')
if __name__ == '__main__':
    {'status': status, 'checkpoint': lambda: checkpoint(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else '')}[sys.argv[1]]()
