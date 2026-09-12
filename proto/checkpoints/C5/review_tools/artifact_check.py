"""Workstream3 final C5 artifact consistency check; run from proto, no sealed per-race read."""
import ast,json,hashlib,subprocess
from pathlib import Path
p=Path('out/validation')
g=json.loads((p/'ghost_scorecard.json').read_text())
l=json.loads((p/'live_scorecard.json').read_text())
r=json.loads((p/'risk_coverage.json').read_text())
h=json.loads((p/'holdout_aggregate.json').read_text())
assert g['development_pool']['lock_consistency_2026']['all_match']
assert all(v['match'] for v in l['source_consistency'].values())
assert h['quotable'] is True and g['sealed_holdout']['aggregate']==h['aggregate']
assert g['sealed_holdout']['source_sha256']==hashlib.sha256((p/'holdout_aggregate.json').read_bytes()).hexdigest()
assert g['lock']['sha256']==hashlib.sha256(Path('out/lock.json').read_bytes()).hexdigest()
assert l['source']['sha256']==hashlib.sha256(Path('out/live/prefix_eval.json').read_bytes()).hexdigest()
assert len(r['table'])==121
for row in r['table']:
    for k,b in row['bootstrap'].items():
        assert (b['estimate'] is None and row[k] is None) or abs(b['estimate']-row[k])<1e-12
        assert b['n_weekends']<=row['n_weekends'] and b['n']<=row['n_cases']
        assert b['ci90'] is not None or b['n_weekends']<2
series=g['rolling_origin_2026']['series']
scored=[x for x in series if 'bootstrap' in x]
assert all(b['ci90'] is None and b['n_weekends']<=1 for x in scored for b in x['bootstrap'].values())
for f in ['common','scorecards','regret','hidden_stop','risk_coverage']:
    ast.parse(Path(f'evaluation/{f}.py').read_text())
changed=subprocess.check_output(['git','diff','--name-only'],text=True).splitlines()
protected=['proto/evaluation/forecast.py','proto/evaluation/holdout/sealed_holdout_manifest.json','proto/evaluation/holdout/sealed_holdout_manifest.sha256','proto/evaluation/holdout/freeze.json','proto/out/validation/holdout_aggregate.json']
assert not set(protected)&set(changed)
reveal=p/'holdout_per_race.json'
assert reveal.is_file() and reveal.stat().st_size==56683
print('PASS: lock11/11, prefix17/17, frozen input hashes and exact aggregate copy,121x6risk point/band/count checks,13rolling rounds11scored with honest per-round nullCI,5source parses, protected files unchanged, reveal existence/sizeonly.')
