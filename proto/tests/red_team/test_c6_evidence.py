"""C6 evidence gates reject missing, short, incomplete or forged-success reports."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
from evaluation.red_team import c6_evidence as gates
from evaluation.red_team import claim_audit as claims
from evaluation.red_team.consistency_probe import ReferenceSet,match_surfaces


def rehearsal():
    start=datetime(2026,9,13,tzinfo=timezone.utc);event=dict(event='Monza',driver='NOR',lap=31)
    steps=[]
    for i,page in enumerate(('live_predictor','ghost_strategy','validation','generalisation','pre_race','live_predictor')):
        state=dict(ev='Monza',drv='NOR',lap=1 if i==0 else 53) if page=='live_predictor' else (dict(ev='Monza',drv='NOR',ilap=24,rep='MEDIUM') if page=='ghost_strategy' else dict(ev='Madrid') if page=='pre_race' else {})
        steps.append(dict(name=str(i),page=page,state=state,elapsed_s=i*60,numbers=1,mismatches=[],unclassified=[],console_errors=[],network_failures=[],
            matched_records=[dict(value=1,reference='test.literal_one',reference_value=1)],
            runtime_evidence=dict(consumed_events=[event]) if i==5 else {},race_twin=dict(source_frames_exact=True,checks=dict(hud=True)) if i==1 else None))
    return dict(exit_code=0,elapsed_s=301,external_requests=[],console_errors=[],network_failures=[],started_at=start.isoformat(),ended_at=(start+timedelta(seconds=301)).isoformat(),steps=steps,
                feedback=dict(event=event,appended_rows=1,restored_exactly=True,before_sha256='abc',restored_sha256='abc'),
                summary=dict(numbers=6,feedback_events=1,mismatches=0,unclassified=0,load_failures=0,console_errors=0,network_failures=0,external_requests=0))


def test_complete_rehearsal_evidence_accepted():
    assert gates.rehearsal_summary(rehearsal())['status']=='PASS'


@pytest.mark.parametrize('change',[lambda r:r.update(elapsed_s=299),lambda r:r.update(ended_at=r['started_at']),
    lambda r:r['steps'][0].update(matched_records=[]),lambda r:r['steps'][0].update(unclassified=[dict(value=7)]),
    lambda r:r['feedback'].update(restored_sha256='different'),lambda r:r['steps'][-1].update(runtime_evidence={}),
    lambda r:r['summary'].update(external_requests=1),lambda r:r.update(steps=r['steps'][:3])])
def test_rehearsal_corruption_is_blocking(change):
    r=rehearsal();change(r);assert gates.rehearsal_summary(r)['status']=='FAIL'


def test_absent_reports_never_pass():
    assert gates.rehearsal_summary(None)['status']=='FAIL'
    assert gates.release_summary(None)['status']=='FAIL'
    assert gates.release_summary(dict(status='PASS',checkpoint='C6',failures=[],capture={}))['status']=='FAIL'


def test_readme_is_presentation_and_qualified_claims_keep_same_line_scope():
    c=dict(id='example',pattern='23%',search_in=['README'],qualified_by=['lap-weighted'],disqualified_by=[])
    claims.locate([c],[('README.md',[(1,'23% reduction'),(2,'lap-weighted')])])
    assert c['n_presentation_unqualified']==1
    assert claims.source_kind('README.md')=='README'


def test_strict_rehearsal_never_waives_unclassified_small_integer():
    rec=dict(route='test',status='ok',numbers=0,matched={},ambiguous=[],placeholders=[],unclassified=[],unhashed_live=[],mismatches=[],error=None,require_classified_numbers=True)
    match_surfaces(rec,[dict(kind='text',widget='score',text='7',cells=[],raw='')],ReferenceSet())
    assert rec['status']=='mismatch' and len(rec['mismatches'])==1


def test_dynamic_feedback_snapshot_uses_prefix_and_replaces_old_live_sidecars():
    from evaluation.red_team.dynamic_references import live_runtime_references
    from evaluation.red_team.consistency_probe import build_base_references
    from evaluation.red_team import LOCK_V1,read_json
    lock=read_json(LOCK_V1)
    event=dict(event='Monza',driver='NOR',lap=31,symptom='sliding',axle='rear',corner_phase='traction',severity=4,trend='worsening',driver_confidence=.8,source='radio',engineer_confirmed=True)
    future=dict(event,lap=40)
    refs,evidence=live_runtime_references(build_base_references(lock,[32]),lock,'live_predictor',dict(ev='Monza',drv='NOR',lap=32),[event,future])
    assert evidence['feedback_events']==[event] and evidence['consumed_events']==[event]
    assert evidence['through_lap']==32 and max(r['lap'] for r in evidence['records'])==32
    assert not any(k.startswith('sidecar:out/live/') for k in refs.values)
    assert any(k.startswith('live_runtime:Monza_NOR:explicit_feedback') for k in refs.values)
    assert evidence['n_laps'] == 53
    assert any(path == 'session.n_laps' and value == 53 for values in refs.values.values() for value, path in values)


def test_acceptance_inventory_does_not_execute_capture_imports(monkeypatch,tmp_path):
    from evaluation.red_team import browser_consistency as browser
    capture=tmp_path/'tests/screenshots/capture.py';capture.parent.mkdir(parents=True)
    capture.write_text("raise RuntimeError('capture imports must not execute')\nROUTES = [('example', '/validation?ev=Monza')]\n")
    monkeypatch.setattr(browser,'PROTO',tmp_path)
    cases=browser.browser_routes()
    assert cases[-1][0]=='acceptance/example' and cases[-1][1]=='validation'


def test_release_cannot_hide_bootstrap_http_errors_as_benign():
    routes={name.split('/',1)[1]:{} for name,_,_,_ in gates.browser_routes() if name.startswith('acceptance/')}
    for name,views in routes.items():
        for vp in gates.VIEWPORTS:
            views[vp]=dict(console_errors=[],other_4xx_5xx=[],expected_text_missing=[],benign_base_path_probes_404=[],
                horizontal_overflow=False,load_ms=900,diff_vs_golden=0,offline_notice_visible=True,sidebar_visible=not name.startswith('presentation_'),
                network=dict(local_request_count=1,external_requests=[],websockets=['ws://localhost:8502/_stcore/stream']))
    timings={}
    for vp in gates.VIEWPORTS:
        timings.update({f'route_switch_ms_{vp}':150,f'route_switch_validation_ms_{vp}':150,
            f'keyboard_nav_{vp}':dict(missing=[],enter_activates=True,reached=list(gates.NAV_TITLES),
                activations=[dict(target=t,activated=True,switch_ms=150) for t in gates.NAV_TITLES]),
            f'replay_run_{vp}':dict(console_errors=[],bad_responses=[],header_after_6s='Lap 6/53')})
    r=dict(status='PASS',checkpoint='C6',failures=[],base='http://localhost:8502',capture=dict(routes=routes,timings=timings,external_requests=[],raw_console_errors=[],raw_network_failures=[]))
    assert gates.release_summary(r)['status']=='PASS'
    r['capture']['routes']['live_stable']['1440x900']['benign_base_path_probes_404']=['http://localhost:8502/live/_stcore/health']
    assert gates.release_summary(r)['status']=='FAIL'


def test_numeric_browser_navigation_preserves_query_and_uses_internal_link():
    from evaluation.red_team.browser_consistency import navigate
    class Page:
        def __init__(self):self.calls=[];self.first=self
        def goto(self,url,**kwargs):self.calls.append(('goto',url))
        def wait_for_selector(self,selector,**kwargs):self.calls.append(('wait',selector))
        def get_by_role(self,role,**kwargs):self.calls.append(('role',role,kwargs));return self
        def click(self):self.calls.append(('click',))
    page=Page();navigate(page,'http://localhost:8502/','/ghost?ev=Monza&drv=NOR&ilap=24&rep=MEDIUM&presentation=1','ghost_strategy')
    assert page.calls[0]==('goto','http://localhost:8502/?ev=Monza&drv=NOR&ilap=24&rep=MEDIUM&presentation=1')
    assert len([c for c in page.calls if c[0]=='goto'])==1
    assert ('role','link',dict(name='Ghost Strategy',exact=True)) in page.calls
    assert page.calls[-1]==('wait','[data-orb-ready="ghost"]')
