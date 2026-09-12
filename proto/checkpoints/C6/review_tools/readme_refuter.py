"""Independent read-only C6 README/environment/provenance check; never runs pipeline."""
from pathlib import Path
import json,hashlib,re,subprocess,sys
root=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/Users/samuelmorningstar/Trackshift/proto')
readme=(root/'README.md').read_text()
pins=(root/'requirements.txt').read_text().strip().splitlines()
freeze=subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True).strip().splitlines()
assert pins==freeze, 'requirements are not the exact active environment freeze'
for name in ('schemas/README.md','counterfactual/README.md','evaluation/README.md','app_v2/streamlit_app.py','out/validation/holdout_aggregate.json','out/validation/SCORECARDS.md'):
    assert (root/name).exists(),name
for name in ('forecast_Madrid_2026.json','forecast_Madrid_2026.pdf','forecast_Madrid_2026.sha256'):
    assert hashlib.sha256((root/'out'/name).read_bytes()).hexdigest() in readme,name
lock2=json.loads((root/'out/lock_v2.json').read_text())
assert lock2['shared']['forecast_hash'] in readme
assert len(re.findall(r'^\d+\. \*\*.+?\?\*\*',readme,flags=re.M))==8
assert 'factor 1' in readme and 'fallback applies to withheld curves' in readme
assert '(1.0, False)' in (root/'pipeline.py').read_text()
assert 'Qualifying refresh began' in readme and '21:32:31 IST' in readme and '21:33:14 IST' in readme
assert 'Compound transfer-factor fitting excludes the held-out weekend' in readme
assert 'gitignored' in readme and 'separate clone' in readme and 'does not automatically rebuild' in readme
blocks=re.findall(r'```sh\n(.*?)```',readme,flags=re.S)
pipeline_block=next(block for block in blocks if 'python pipeline.py' in block)
assert 'cd /tmp/orb-reproduction/proto' in pipeline_block and 'git clone --no-hardlinks' in pipeline_block
report=json.loads((root/'checkpoints/C6/fresh_clone_report.json').read_text())
clone=Path(report['clone'])/'proto'
a=json.loads((root/'out/lock.json').read_text());b=json.loads((clone/'out/lock.json').read_text())
a.pop('generated_at');b.pop('generated_at')
assert json.dumps(a,sort_keys=True)==json.dumps(b,sort_keys=True)
for name,digest in report['feature_files'].items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
    assert hashlib.sha256((clone/name).read_bytes()).hexdigest()==digest
assert report['pipeline_exit']==0 and report['dashboard']['health']==200
print(json.dumps({'status':'PASS','exact_pins':len(pins),'jury_questions':8,'existing_references':6,'Madrid_digests':4,'clone_features_verified':len(report['feature_files']),'clone_lock_equal_except_generated_at':True,'method_and_timeline_corrections_verified':True,'pipeline_was_not_run_by_refuter':True},indent=2))
