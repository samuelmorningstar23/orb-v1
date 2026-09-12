"""Independent C6 release-matrix and network-boundary refutation."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from evaluation.red_team.c6_evidence import release_summary


def run(source,out):
    report_path=source/'tests/screenshots/c6_release_report.json'
    report=json.loads(report_path.read_text())
    matrix=release_summary(report)
    assert matrix['status']=='PASS',matrix['failures']
    path=source/'tests/screenshots/network_guard.py'
    spec=importlib.util.spec_from_file_location('candidate_network_guard',path)
    guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
    cases={'http://localhost:8502/x':True,'ws://localhost:8502/_stcore/stream':True,
           'https://localhost:8502/x':False,'ws://localhost:8599/x':False,
           'http://localhost.evil.test:8502/x':False,'http://localhost:8502@evil.test/x':False,
           'https://cdn.example/x.js':False,'wss://remote.example/socket':False,
           'http://127.0.0.1:8502/x':False,'file:///tmp/test':False,'data:text/plain,hello':True}
    for url,expected in cases.items():
        assert guard.is_local_url('http://localhost:8502',url) is expected,url
    result=dict(status='PASS',generated_at=datetime.now(timezone.utc).isoformat(),release_matrix=matrix,
                independent_origin_attack_cases=len(cases),source_sha256={
                    str(path.relative_to(source)):hashlib.sha256(path.read_bytes()).hexdigest(),
                    str(report_path.relative_to(source)):hashlib.sha256(report_path.read_bytes()).hexdigest(),
                    **{f'tests/screenshots/{name}':hashlib.sha256((source/'tests/screenshots'/name).read_bytes()).hexdigest()
                       for name in ('capture.py','release_gate.py')}},
                note='Independent direct matrix/timing/error/keyboard/protocol checks and hostile-origin cases; no browser rerun or writes to product state.')
    out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();run(args.source,args.out)
