"""Tests for Workstream 9 build control: status parsing, stale detection, checkpoint artifacts in a temp git repo,
ownership audit classification, stop-the-line, heartbeat and summary. Hermetic: every test uses tmp_path."""
import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROTO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROTO))
import build_control as bc  # noqa: E402

_spec = importlib.util.spec_from_file_location('ownership_audit', PROTO / 'release' / 'ownership_audit.py')
oa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oa)

GIT = ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false']


def hb(workstream, minutes_ago, status='GREEN', **kw):
    base = dict(workstream=workstream, task=f'task_{workstream}', status=status, commit=None, completed=[], in_progress=[], blockers=[],
                tests_passed=3, tests_failed=0, eta_minutes=10, needs_review_from=[],
                updated_at=(dt.datetime.now() - dt.timedelta(minutes=minutes_ago)).isoformat(timespec='seconds'))
    base.update(kw)
    return base


def write_hb(root, workstream, h):
    Path(root, 'progress').mkdir(exist_ok=True)
    Path(root, 'progress', f'workstream_{workstream}.json').write_text(json.dumps(h))


@pytest.fixture
def root(tmp_path):
    for d in ('progress', 'checkpoints', 'release'):
        (tmp_path / d).mkdir()
    return tmp_path


def make_repo(path, nested=False):
    """Git repo with a proto-like layout; returns the proto root (== repo root unless nested)."""
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=path, check=True)
    proto = path / 'proto' if nested else path
    proto.mkdir(exist_ok=True)
    (proto / 'out').mkdir()
    (proto / 'out' / 'lock.json').write_text('{"ok": true}\n')
    (proto / 'tests').mkdir()
    (proto / 'tests' / 'test_smoke.py').write_text('def test_ok():\n    assert True\n')
    for d in ('progress', 'checkpoints', 'release'):
        (proto / d).mkdir()
    (path / '.gitignore').write_text('__pycache__/\n')
    subprocess.run(['git', 'add', '-A'], cwd=path, check=True)
    subprocess.run(GIT + ['commit', '-q', '-m', 'init'], cwd=path, check=True)
    return proto


# ----------------------------------------------------------------------------- status / staleness
def test_effective_status_rules():
    assert bc.effective_status('GREEN', 40) == 'GREEN'
    assert bc.effective_status('green', 12.5) == 'GREEN'
    assert bc.effective_status('GREEN', 40.5).startswith('AMBER (stale 40')
    assert bc.effective_status('AMBER', 90).startswith('AMBER (stale 90')
    assert bc.effective_status('RED', 100).startswith('RED (stale')
    assert bc.effective_status('GREEN', None) == 'RED (bad updated_at)'
    assert bc.effective_status('BLUE', 1).startswith('RED (bad status')
    assert bc.effective_status('GREEN', -1.5) == 'GREEN'
    assert bc.effective_status('GREEN', -9).startswith('GREEN (clock ahead 9')
    assert bc.effective_status('AMBER', -30).startswith('AMBER (clock ahead')


def test_age_minutes_handles_naive_and_aware_timestamps():
    t = dt.datetime.now() - dt.timedelta(minutes=10)
    assert 9.9 < bc.age_minutes(t.isoformat()) < 10.2
    aware = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)).isoformat()
    assert 9.9 < bc.age_minutes(aware) < 10.2
    assert bc.age_minutes('not a time') is None and bc.age_minutes(None) is None


def test_load_heartbeats_parsing_and_stale_detection(root):
    write_hb(root, 1, hb(1, 5))
    write_hb(root, 6, hb(6, 41))
    write_hb(root, 9, hb(9, 39, blockers=['waiting on lock v2'], tests_passed=7, tests_failed=1))
    Path(root, 'progress', 'workstream_2.json').write_text('{not json')
    rows = {r['workstream']: r for r in bc.load_heartbeats(root)}
    assert [r['workstream'] for r in bc.load_heartbeats(root)] == [1, 2, 6, 9]
    assert rows[1]['effective'] == 'GREEN' and not rows[1]['stale']
    assert rows[6]['effective'].startswith('AMBER (stale') and rows[6]['stale']
    assert rows[9]['effective'] == 'GREEN' and not rows[9]['stale'] and rows[9]['blockers'] == ['waiting on lock v2']
    assert rows[9]['tests_passed'] == 7 and rows[9]['tests_failed'] == 1
    assert rows[2]['unreadable'] and rows[2]['effective'].startswith('RED (unreadable')


def test_missing_active_workstreams_are_flagged_and_rendered(root):
    write_hb(root, 9, hb(9, 1))
    rep = bc.status_report(root)
    assert rep['active_workstreams'] == [1, 6, 9]           # wave 0 before any green checkpoint
    assert rep['missing'] == [1, 6] and rep['stale'] == []
    text = bc.render_status(rep, color=False)
    assert 'MISSING heartbeats: workstreams [1, 6]' in text and 'merge queue: OPEN' in text and 'last green: none' in text
    assert '\033[' not in text
    assert '\033[' in bc.render_status(rep, color=True)


def test_status_lists_stale_and_blockers(root):
    write_hb(root, 1, hb(1, 200, status='RED', blockers=['fixture invalid']))
    write_hb(root, 6, hb(6, 2))
    write_hb(root, 9, hb(9, 2))
    rep = bc.status_report(root)
    assert rep['stale'] == [1] and rep['blockers'] == {'1': ['fixture invalid']}
    text = bc.render_status(rep, color=False)
    assert 'STALE heartbeats (> 40 min): workstreams [1]' in text and 'fixture invalid' in text


def test_active_workstreams_waves_and_override(root):
    cp = root / 'checkpoints' / 'C1'
    cp.mkdir()
    (cp / 'checkpoint.json').write_text(json.dumps(dict(checkpoint='C1', decision='GO')))
    assert bc.active_workstreams(root) == [1, 2, 4, 6, 8, 9]
    (root / 'checkpoints' / 'C2').mkdir()
    (root / 'checkpoints' / 'C2' / 'checkpoint.json').write_text(json.dumps(dict(checkpoint='C2', decision='HOLD')))
    assert bc.active_workstreams(root) == [1, 2, 4, 6, 8, 9]   # HOLD does not open wave 2
    (root / 'release' / 'active_workstreams.json').write_text(json.dumps(dict(active=[1, 9])))
    assert bc.active_workstreams(root) == [1, 9]


# ----------------------------------------------------------------------------- stop the line / queue
def test_stop_the_line_roundtrip(root):
    bc.stop_the_line(root, 'holdout opened early', by='workstream 7')
    assert (root / 'release' / 'STOP_THE_LINE.json').is_file()
    assert bc.get_queue(root)['state'] == 'FROZEN'
    text = bc.render_status(bc.status_report(root), color=False)
    assert 'STOP THE LINE' in text and 'holdout opened early' in text
    rec = bc.clear_stop(root, 'resealed and verified')
    assert rec['reason'] == 'holdout opened early' and rec['cleared_by'] == 'workstream 9'
    assert not (root / 'release' / 'STOP_THE_LINE.json').exists()
    assert bc.get_queue(root)['state'] == 'OPEN'
    assert len((root / 'release' / 'stop_history.jsonl').read_text().splitlines()) == 1
    assert bc.clear_stop(root) is None


# ----------------------------------------------------------------------------- checkpoints
def test_checkpoint_creates_artifact_set_and_updates_last_green(tmp_path):
    root = make_repo(tmp_path)
    write_hb(root, 9, hb(9, 1))
    rec = bc.checkpoint('C1', 'GO', 'unit test', root=root, echo=False)
    cdir = root / 'checkpoints' / 'C1'
    for f in ('checkpoint.json', 'checkpoint.md', 'test_report.json', 'artifact_hashes.json', 'ownership_audit.json', 'last_green.json'):
        assert (cdir / f).is_file(), f
    tr = json.loads((cdir / 'test_report.json').read_text())
    assert [c['name'] for c in tr['checks']] == list(bc.CHECK_ORDER)
    st = {c['name']: c['status'] for c in tr['checks']}
    assert st['schema_validation'] == 'SKIP' and 'validators/validate_lock.py' in tr['checks'][0]['note']
    assert st['pytest'] == 'PASS' and tr['pytest']['passed'] == 1 and tr['test_dirs'] == []
    assert st['ownership_audit'] == 'PASS' and st['lock_dashboard_consistency'] == 'NOT_IMPLEMENTED'
    assert st['sealed_holdout_integrity'] == 'SKIP'
    assert (cdir / 'logs' / 'pytest.txt').is_file()
    assert rec['all_green'] and rec['decision'] == 'GO' and not rec['decision_overrides_checks'] and rec['exit_code'] == 0
    lg = json.loads((root / 'checkpoints' / 'last_green.json').read_text())
    assert lg['checkpoint'] == 'C1' and lg['git_commit'] == rec['git_commit'] and len(lg['git_commit']) >= 7
    assert bc.get_queue(root)['state'] == 'OPEN'
    assert json.loads((cdir / 'artifact_hashes.json').read_text()) == {'out/lock.json': bc.sha256_file(root / 'out' / 'lock.json')}
    md = (cdir / 'checkpoint.md').read_text()
    assert md.startswith('# C1: GO') and '| pytest | PASS |' in md and '| 9 | GREEN |' in md
    assert bc.status_report(root)['last_checkpoint']['decision'] == 'GO'


def test_checkpoint_hold_keeps_queue_frozen_and_last_green(tmp_path):
    root = make_repo(tmp_path)
    bc.write_json(root / 'checkpoints' / 'last_green.json', dict(checkpoint='C0', git_commit='abc1234', at='x'))
    rec = bc.checkpoint('C2', 'HOLD', 'red issue open', root=root, echo=False)
    assert rec['decision'] == 'HOLD' and rec['exit_code'] == 2
    assert bc.get_queue(root)['state'] == 'FROZEN'
    assert json.loads((root / 'checkpoints' / 'last_green.json').read_text())['checkpoint'] == 'C0'
    assert not (root / 'checkpoints' / 'C2' / 'last_green.json').exists()


def test_auto_proposes_hold_on_failing_tests_and_lead_decides(tmp_path):
    root = make_repo(tmp_path)
    (root / 'tests' / 'test_fail.py').write_text('def test_bad():\n    assert False\n')
    rec = bc.checkpoint('C3', 'AUTO', root=root, echo=False)
    assert rec['decision'] == 'PENDING' and rec['proposed'] == 'HOLD' and not rec['all_green'] and rec['exit_code'] == 3
    st = {c['name']: c for c in rec['checks']}
    assert st['pytest']['status'] == 'FAIL' and st['pytest']['counts'] == {'failed': 1, 'passed': 1}
    assert bc.get_queue(root)['state'] == 'FROZEN' and not (root / 'checkpoints' / 'last_green.json').exists()
    assert bc.status_report(root)['last_checkpoint']['proposed'] == 'HOLD'
    rec2 = bc.decide('C3', 'GO', 'lead accepts the known failure', root=root, echo=False)
    assert rec2['decision'] == 'GO' and rec2['decision_overrides_checks'] and rec2['exit_code'] == 0
    assert json.loads((root / 'checkpoints' / 'last_green.json').read_text())['checkpoint'] == 'C3'
    assert bc.get_queue(root)['state'] == 'OPEN'
    assert 'WARNING' in (root / 'checkpoints' / 'C3' / 'checkpoint.md').read_text()
    bc.sign('C3', 'lead', root)
    assert json.loads((root / 'checkpoints' / 'C3' / 'checkpoint.json').read_text())['signed_by'] == 'lead'


def test_rehearsal_writes_artifacts_but_changes_no_state(tmp_path):
    root = make_repo(tmp_path)
    bc.set_queue(root, 'OPEN', 'baseline')
    rec = bc.checkpoint('C1', 'REHEARSAL', root=root, echo=False)
    rdir = root / 'checkpoints' / 'rehearsal' / 'C1'
    assert rec['decision'] == 'REHEARSAL' and rec['exit_code'] == 0
    for f in ('checkpoint.json', 'checkpoint.md', 'test_report.json', 'artifact_hashes.json', 'ownership_audit.json'):
        assert (rdir / f).is_file(), f
    assert not (root / 'checkpoints' / 'C1').exists()
    assert not (root / 'checkpoints' / 'last_green.json').exists()
    assert bc.get_queue(root) == bc.get_queue(root) and bc.get_queue(root)['reason'] == 'baseline'
    assert bc.last_checkpoint(root) is None


def test_holdout_integrity_check_detects_tampering(tmp_path):
    root = make_repo(tmp_path)
    hd = root / 'evaluation' / 'holdout'
    hd.mkdir(parents=True)
    (hd / 'sealed_holdout_manifest.json').write_text('{"sealed": [1, 2]}')
    (hd / 'sealed_holdout_manifest.sha256').write_text(bc.sha256_file(hd / 'sealed_holdout_manifest.json', 64) + '  sealed_holdout_manifest.json\n')
    assert bc.check_holdout_integrity(root)['status'] == 'PASS'
    prev = {bc.HOLDOUT_MANIFEST: bc.sha256_file(hd / 'sealed_holdout_manifest.json')}
    bc.write_json(root / 'checkpoints' / 'C0' / 'artifact_hashes.json', prev)
    bc.write_json(root / 'checkpoints' / 'last_green.json', dict(checkpoint='C0', git_commit='x', at='y'))
    assert bc.check_holdout_integrity(root)['status'] == 'PASS'
    (hd / 'sealed_holdout_manifest.json').write_text('{"sealed": [1, 2, 3]}')
    c = bc.check_holdout_integrity(root)
    assert c['status'] == 'FAIL' and 'sidecar' in c['note'] and 'changed since last green C0' in c['note']


def test_parse_pytest_summary():
    assert bc.parse_pytest_summary('....\n4 passed in 0.10s\n') == {'passed': 4}
    assert bc.parse_pytest_summary('F..\n1 failed, 2 passed, 1 warning in 0.5s') == {'failed': 1, 'passed': 2, 'warnings': 1}
    assert bc.parse_pytest_summary('no tests ran in 0.01s') == {'passed': 0}
    assert bc.parse_pytest_summary('') == {}


# ----------------------------------------------------------------------------- ownership audit
@pytest.mark.parametrize('path,owner,category,flagged', [
    ('schemas/lock_v2.py', 1, 'workstream', False), ('fixtures/x.json', 1, 'workstream', False), ('validators/validate_lock.py', 1, 'workstream', False),
    ('shared/util.py', 1, 'workstream', False), ('tests/contract/test_x.py', 1, 'workstream', False),
    ('counterfactual/core.py', 2, 'workstream', False), ('events/source.py', 2, 'workstream', False),
    ('evaluation/holdout/x.json', 3, 'workstream', False), ('evaluation/red_team/report.json', 7, 'workstream', False),
    ('replay/path.py', 4, 'workstream', False), ('dashboard/components/player.js', 4, 'workstream', False),
    ('interaction/field.py', 5, 'workstream', False),
    ('app_v2/main.py', 6, 'workstream', False), ('ui/tokens.py', 6, 'workstream', False), ('theme/base.css', 6, 'workstream', False),
    ('views/live.py', 6, 'workstream', False), ('tests/ui/test_a.py', 6, 'workstream', False), ('tests/screenshots/a.png', 6, 'workstream', False),
    ('live/estimator.py', 8, 'workstream', False), ('decision/engine.py', 8, 'workstream', False),
    ('progress/workstream_9.json', 9, 'workstream', False), ('progress/workstream_6.json', 6, 'workstream', False), ('progress/workstream_12.json', None, 'unowned', True),
    ('progress/SUMMARY.md', 9, 'workstream', False), ('checkpoints/C1/checkpoint.json', 9, 'workstream', False),
    ('release/rollback.sh', 9, 'workstream', False), ('build_control.py', 9, 'workstream', False), ('tests/release/test_build_control.py', 9, 'workstream', False),
    ('app.py', 'lead', 'lead_only', True), ('out/lock.json', 'lead', 'lead_only', True), ('extract_seasons.py', 'lead', 'lead_only', True),
    ('refresh.sh', 'lead', 'lead_only', True), ('strategy2.py', 'lead', 'lead_only', True),
    ('out/lock_v2.json', 1, 'workstream', False), ('out/lock_v2_sidecars/validation_rows.json', 1, 'workstream', False), ('tests/conftest.py', 1, 'workstream', False),
    ('out/counterfactual/x.json', 2, 'workstream', False), ('out/validation/scorecard.json', 3, 'workstream', False), ('out/maps/madrid.json', 4, 'workstream', False),
    ('app_v2/components/race_twin/player.js', 4, 'workstream', False), ('app_v2/components/other.py', 6, 'workstream', False), ('out/live/state.json', 8, 'workstream', False),
    ('evaluation/holdout/sealed_holdout_manifest.json', 'lead', 'lead_only', True), ('evaluation/holdout/sealed_holdout_manifest.sha256', 'lead', 'lead_only', True),
    ('evaluation/holdout/weekend_metadata.csv', 3, 'workstream', False), ('evaluation/holdout/superseded_manifest_v0.sha256', 3, 'workstream', False),
    ('tests/counterfactual/test_c.py', 2, 'workstream', False), ('tests/replay/test_r.py', 4, 'workstream', False), ('tests/live/test_l.py', 8, 'workstream', False),
    ('tests/evaluation/test_e.py', 3, 'workstream', False), ('tests/red_team/test_t.py', 7, 'workstream', False),
    ('cleanup_pass.sh', 'lead', 'lead_only', True), ('refresh_2025.log', 'lead', 'lead_only', True), ('build_deck_v5.py', 'lead', 'lead_only', True),
    ('out/deck.pptx', 'lead', 'lead_only', True), ('out/roadmap.pdf', 'lead', 'lead_only', True),
    ('out/sub/x.pdf', None, 'unowned', True), ('sub/build_x.py', None, 'unowned', True), ('release/build_x.py', 9, 'workstream', False),
    ('out/ROADMAP_v5.md', None, 'unowned', True), ('out/other/x.json', None, 'unowned', True), ('random.py', None, 'unowned', True),
    ('dashboard/other.py', None, 'unowned', True), ('sub/extract_x.py', None, 'unowned', True), ('build_control.pyc', None, 'unowned', True),
])
def test_ownership_classification(path, owner, category, flagged):
    c = oa.classify(path)
    assert (c['owner'], c['category'], c['flagged']) == (owner, category, flagged), c


def test_ownership_audit_on_repo_changes(tmp_path):
    root = make_repo(tmp_path)
    (root / 'out' / 'lock.json').write_text('{"ok": false}')          # modified lead-only file
    (root / 'live').mkdir()
    (root / 'live' / 'new.py').write_text('x = 1\n')                   # untracked, workstream 8
    (root / 'stray.txt').write_text('s')                               # untracked, unowned
    rep = oa.audit(root)
    by = {c['path']: c for c in rep['changed']}
    assert by['out/lock.json']['category'] == 'lead_only' and by['out/lock.json']['flagged'] and by['out/lock.json']['git_status'] == 'M'
    assert by['live/new.py']['owner'] == 8 and not by['live/new.py']['flagged'] and by['live/new.py']['git_status'] == '??'
    assert by['stray.txt']['category'] == 'unowned' and by['stray.txt']['flagged']
    assert rep['summary'] == dict(total=3, flagged=2, unowned=1, lead_only=1, outside_proto=0, by_owner={'8': 1, 'lead': 1, 'unowned': 1})
    assert rep['flagged_paths'] == ['out/lock.json', 'stray.txt']
    subprocess.run(['git', 'add', 'live/new.py'], cwd=root, check=True)
    assert oa.audit(root)['changed'][0]['path'] == 'live/new.py'      # staged changes are still reported


def test_ownership_audit_with_nested_proto_and_paths_outside(tmp_path):
    proto = make_repo(tmp_path, nested=True)
    (proto / 'live').mkdir()
    (proto / 'live' / 'x.py').write_text('x = 1\n')
    (tmp_path / 'README.md').write_text('root file')
    rep = oa.audit(proto)
    by = {c['path']: c for c in rep['changed']}
    assert by['proto/live/x.py']['owner'] == 8 and not by['proto/live/x.py']['flagged']
    assert by['README.md']['category'] == 'outside_proto' and by['README.md']['flagged']
    assert rep['summary']['outside_proto'] == 1


def test_ownership_audit_outside_git(tmp_path):
    rep = oa.audit(tmp_path)
    assert rep['error'] == 'not a git repository' and rep['summary']['total'] == 0


# ----------------------------------------------------------------------------- heartbeat / summary / CLI
def test_heartbeat_and_summary(root):
    h = bc.write_heartbeat(root, dict(task='build control', status='GREEN', tests_passed=12, blockers=[]))
    assert h['workstream'] == 9 and bc.age_minutes(h['updated_at']) < 1
    h2 = bc.write_heartbeat(root, dict(eta_minutes=5))
    assert h2['task'] == 'build control' and h2['eta_minutes'] == 5
    p = bc.write_summary(root)
    text = p.read_text()
    assert p.name == 'SUMMARY.md' and '| 9 | GREEN |' in text
    assert 'Workstream 1: no heartbeat file' in text and 'Workstream 6: no heartbeat file' in text
    write_hb(root, 1, hb(1, -12))
    assert 'Workstream 1: updated_at is 12 min in the future (clock ahead)' in bc.write_summary(root).read_text()


def test_cli_status_and_stop_commands(tmp_path):
    root = make_repo(tmp_path)
    write_hb(root, 9, hb(9, 1))
    run = lambda *args: subprocess.run([sys.executable, str(PROTO / 'build_control.py'), '--root', str(root), *args], capture_output=True, text=True)
    r = run('status', '--no-color')
    assert r.returncode == 0 and 'merge queue: OPEN' in r.stdout and 'MISSING heartbeats: workstreams [1, 6]' in r.stdout
    assert run('stop-the-line', 'schema drift broke workstream 8', '--by', 'workstream 1').returncode == 0
    r = run('status', '--no-color')
    assert 'STOP THE LINE' in r.stdout and 'schema drift broke workstream 8' in r.stdout and 'merge queue: FROZEN' in r.stdout
    assert run('clear-stop', 'fixed').returncode == 0 and 'STOP THE LINE' not in run('status').stdout
    r = run('status', '--json')
    assert json.loads(r.stdout)['queue']['state'] == 'OPEN'
    r = run('rollback', '--dry-run')
    assert r.returncode == 1 and 'no checkpoints/last_green.json' in r.stdout
