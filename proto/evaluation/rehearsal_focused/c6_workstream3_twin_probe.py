import sys,importlib.util,json,time
from pathlib import Path
server=Path('/Users/samuelmorningstar/Trackshift/proto');sys.path.insert(0,str(server))
spec=importlib.util.spec_from_file_location('rehearsal_under_test','/private/tmp/orb-c6-workstream3/proto/evaluation/rehearsal_runner.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
spec=importlib.util.spec_from_file_location('network_guard',server/'tests/screenshots/network_guard.py');N=importlib.util.module_from_spec(spec);spec.loader.exec_module(N)
from playwright.sync_api import sync_playwright
out=Path('/private/tmp/orb-c6-workstream3/proto/evaluation/rehearsal_focused');out.mkdir(exist_ok=True)
errors=[];bad=[];external=[];rep={}
try:
 with sync_playwright() as p:
  browser=p.chromium.launch();ctx=browser.new_context(viewport={'width':1440,'height':900},service_workers='block');bucket=N.bucket('focused','1440x900');N.install(ctx,'http://localhost:8502',external,lambda:bucket);page=ctx.new_page()
  page.on('console',lambda m:errors.append(m.text) if m.type=='error' else None);page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:bad.append([r.url,r.status]) if r.status>=400 else None)
  R.navigate(page,'http://localhost:8502','/ghost?ev=Monza&drv=NOR&mode=audit&ilap=24&rep=MEDIUM','ghost')
  rep['twin']=R.twin_snapshot(page,server,out,'focused_twin')
  frame=next(f for f in page.frames if f.evaluate('typeof window.__orbTwin!=="undefined"'))
  frame.evaluate("""()=>{window.__orbRehearsalSamples=[];const observer=new MutationObserver(()=>window.__orbRehearsalSamples.push(window.__orbRehearsalRead())); for(const id of ['orb-lapno','orb-clock','orb-gap','orb-gapm','orb-a-txt','orb-g-txt','orb-lapval'])observer.observe(document.getElementById(id),{childList:true,characterData:true,subtree:true});window.__orbRehearsalObserver=observer;}""")
  frame.locator('#orb-play').click();page.wait_for_timeout(5000);frame.locator('#orb-play').click();frame.wait_for_timeout(200);frame.evaluate('window.__orbRehearsalObserver.disconnect()')
  rep['animation']=R.twin_snapshot(page,server,out,'ghost_replayed')
  rep['animation_count']=len(rep['animation']['animation_samples'])
  assert not errors and not bad and not external
  rep['passed']=True;browser.close()
except Exception as e:rep['error']=repr(e);rep['passed']=False
rep.update(console_errors=errors,network_failures=bad,external_requests=external);(out/'twin_observer_report.json').write_text(json.dumps(rep,indent=2));print(json.dumps({k:v for k,v in rep.items() if k not in ('twin','animation')},indent=2));sys.exit(0 if rep['passed'] else 2)
