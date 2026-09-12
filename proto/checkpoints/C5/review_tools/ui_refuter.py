"""Independent Workstream3 refutation of C5 dashboard evidence delegation.
Run from proto with ../.venv/bin/python /private/tmp/orb-c5-workstream3-ui-refute.py TARGET_PROTO
No sealed per-race artifact is opened, enumerated or hashed.
"""
import json
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
from app_v2.ui import scorecard_evidence as E
from app_v2.pages import validation as V, generalisation as G
from app_v2.services import validation_repository as VR

metrics={'sample':dict(estimate=.123456,ci90=[.012345,.987654],n=41,n_unit='eligible stops',n_weekends=3),
 'single':dict(estimate=9.5,ci90=None,n=7,n_unit='windows',n_weekends=1)}
rows=E.metric_rows(metrics)
assert rows[0]==['sample','0.1235','[0.0123, 0.9877]','41 eligible stops',3]
assert 'unavailable' in rows[1][2] and rows[1][3]=='7 windows'
assert 'bootstrap' not in E.__dict__ and 'numpy' not in E.__dict__
for mod in (V,G):
    source=Path(mod.__file__).read_text()
    assert 'evidence.render(' in source and 'sealed_html(VR.sealed_block())' in source
    assert 'holdout_per_race' not in source and 'read_csv(' not in source
original=VR.holdout_aggregate
try:
    for flag in (False,None):
        VR.holdout_aggregate=lambda flag=flag: ({'quotable':flag,'freeze':{},'aggregate':{'forecast':{'secret':123}}},None)
        sb=VR.sealed_block()
        assert sb['revealed'] is False and sb['forecast'] is None
finally:
    VR.holdout_aggregate=original

count=0
for name in ('ghost_scorecard.json','live_scorecard.json','risk_coverage.json'):
    data=json.loads((root/'out/validation'/name).read_text())
    def walk(obj):
        global count
        if isinstance(obj,dict):
            if 'estimate' in obj and 'ci90' in obj:
                row=E.metric_rows({'check':obj})[0]
                estimate='—' if obj['estimate'] is None else format(obj['estimate'],'.4f')
                assert row[1]==estimate
                if obj['ci90'] is None:
                    assert 'unavailable' in row[2]
                else:
                    assert row[2]=='['+', '.join(format(x,'.4f') for x in obj['ci90'])+']'
                n=obj.get('n',obj.get('n_rows'))
                assert row[3]==f"{n if n is not None else '—'} {obj.get('n_unit','observations')}"
                assert row[4]==obj.get('n_weekends','—')
                count+=1
            for v in obj.values(): walk(v)
        elif isinstance(obj,list):
            for v in obj: walk(v)
    walk(data)
assert count>50
print(f'PASS independent UI refutation: {count} artifact estimate/band/count mappings; adversarial rounding and null interval checks; both routes share renderer and sealed gate; no direct future/per-race reads in changed page sources.')
