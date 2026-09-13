"""Catalogue caching must follow edits and retain separate forecast/audit identities."""
import json
import os
from app_v2.services import counterfactual_repository as CF


def test_catalogue_invalidates_changed_added_and_removed_summaries(tmp_path, monkeypatch):
    monkeypatch.setattr(CF, 'CF_DIR', tmp_path)
    def put(name, event, value):
        d=tmp_path/name; d.mkdir(exist_ok=True)
        p=d/'summary.json'
        p.write_text(json.dumps({'scenario':{'event_id':event,'driver_id':'NOR','summary':{'elapsed_delta_median_s':value}},'engine':{'curves':{'source':'race_reference'}}}))
        return p
    p=put('one','2026_Monza',-2.0)
    assert CF.list_scenarios('Monza')[0].finish_delta_s == -2.0
    p=put('one','2026_Monza',-4.0)
    os.utime(p,ns=(p.stat().st_atime_ns,p.stat().st_mtime_ns+1000000))
    assert CF.list_scenarios('Monza')[0].finish_delta_s == -4.0
    put('two','2026_Austria',1.0)
    assert len(CF.list_scenarios(None))==2
    p.unlink()
    assert CF.list_scenarios('Monza')==[]
