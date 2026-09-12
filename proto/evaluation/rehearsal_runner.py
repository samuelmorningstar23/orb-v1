"""Timed C6 browser rehearsal with preserved numeric surfaces and reversible feedback.
Run from proto: ../.venv/bin/python evaluation/rehearsal_runner.py --server-proto PATH --out PATH --allow-feedback
The lead must reserve the shared feedback log for this run. No forecast/model write.
"""
from __future__ import annotations
import argparse, hashlib, importlib.util, json, math, re, sys, time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

def stamp(): return datetime.now(timezone.utc).isoformat()
def digest(data): return hashlib.sha256(data).hexdigest()
def dump(path, obj): path.write_text(json.dumps(obj, indent=2, default=str)+'\n')

def appended_event(before: bytes, after: bytes, marker: str):
    if not after.startswith(before): raise RuntimeError('feedback prefix changed; refusing restoration')
    added=after[len(before):].splitlines()
    if len(added)!=1: raise RuntimeError('expected exactly one appended feedback row; concurrent change detected')
    event=json.loads(added[0])
    if event.get('raw_message')!=marker: raise RuntimeError('appended row is not this rehearsal event')
    return event

def restore_feedback(path, before, existed, expected):
    current=path.read_bytes() if path.exists() else b''
    if current!=expected: raise RuntimeError('feedback CAS failed; refusing to overwrite concurrent changes')
    if existed: path.write_bytes(before)
    elif path.exists(): path.unlink()
    actual=path.read_bytes() if path.exists() else b''
    if actual!=before or path.exists()!=existed: raise RuntimeError('feedback restoration verification failed')
    return digest(actual)


def navigate(page,base,path,marker):
    """Use the real Streamlit navigation after root bootstrapping, never a deep reload."""
    parsed=urlparse(path)
    page.goto(base+'/?'+parsed.query,wait_until='domcontentloaded')
    page.wait_for_selector('[data-orb-ready="landing"]',state='attached',timeout=30000)
    if parsed.path not in ('','/'):
        title={'/live':'Live Predictor','/feedback':'Driver feedback','/ghost':'Ghost Strategy',
               '/validation':'Validation','/generalisation':'Generalisation','/pre-race':'Pre-race plan'}[parsed.path]
        link=page.get_by_role('link',name=title,exact=True).first
        if not link.is_visible():page.get_by_role('button',name='More',exact=True).click()
        link.click()
    page.wait_for_selector(f'[data-orb-ready="{marker}"]',state='attached',timeout=30000)
    page.wait_for_timeout(500)


def run(args):
    sys.path.insert(0,str(args.server_proto))
    from playwright.sync_api import sync_playwright
    from evaluation.red_team.browser_consistency import dom_surfaces
    from evaluation.red_team.consistency_probe import build_base_references, route_references, match_surfaces
    from evaluation.red_team.dynamic_references import live_runtime_references
    out=args.out; out.mkdir(parents=True,exist_ok=True)
    lock=json.loads((args.server_proto/'out/lock.json').read_text())
    log=args.server_proto/'app_v2/state/feedback_events.jsonl'
    before=log.read_bytes() if log.exists() else b''; existed=log.exists(); after=None
    marker='C6 timed rehearsal '+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    rep=dict(generated_at=stamp(),started_at=None,ended_at=None,elapsed_s=0,base=args.base,viewport='1440x900',steps=[],
        external_requests=[],console_errors=[],network_failures=[],feedback=dict(before_sha256=digest(before),before_exists=existed,marker=marker,restored_exactly=False),
        coverage=dict(semantic_DOM=True,widgets=True,plotly_labels_and_ticks=True,race_twin_HUD=True,
                      raster_charts='Hash-linked source-artifact proof, not pixel OCR; risk JSON/CSV carries every plotted metric and weekend CI.'),exit_code=2,error=None)
    rep['input_sha256']={f:digest((args.server_proto/f).read_bytes()) for f in (
        'out/lock.json','out/lock_v2.json','out/forecast_Madrid_2026.json','out/forecast_Madrid_2026.pdf','out/forecast_Madrid_2026.sha256',
        'out/validation/ghost_scorecard.json','out/validation/live_scorecard.json','out/validation/holdout_aggregate.json',
        'evaluation/red_team/consistency_probe.py','evaluation/red_team/dynamic_references.py','tests/screenshots/network_guard.py')}
    rep['runner_sha256']=digest(Path(__file__).read_bytes())
    (out/'feedback_before.jsonl').write_bytes(before)
    start=time.monotonic()
    def wait_to(offset):
        while (remain:=offset-(time.monotonic()-start))>0:
            page.wait_for_timeout(min(15,remain)*1000)
    try:
        if not args.allow_feedback: raise RuntimeError('explicit --allow-feedback required after lead reserves exclusive log window')
        with urlopen(args.base+'/_stcore/health',timeout=5) as r:
            if r.status!=200: raise RuntimeError('dashboard not healthy')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(); context=browser.new_context(viewport=dict(width=1440,height=900),device_scale_factor=1,service_workers='block')
            spec=importlib.util.spec_from_file_location('orb_rehearsal_network_guard',args.server_proto/'tests/screenshots/network_guard.py')
            guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
            network_bucket=guard.bucket('setup','1440x900')
            guard.install(context,args.base,rep['external_requests'],lambda:network_bucket)
            page=context.new_page()
            page.on('console',lambda m:rep['console_errors'].append(dict(at=stamp(),kind=m.type,text=m.text)) if m.type=='error' else None)
            page.on('pageerror',lambda e:rep['console_errors'].append(dict(at=stamp(),kind='pageerror',text=str(e))))
            page.on('response',lambda r:rep['network_failures'].append(dict(at=stamp(),url=r.url,status=r.status)) if r.status>=400 else None)
            def go(path,marker):
                network_bucket['route']=path
                navigate(page,args.base,path,marker)
            go('/?ev=Monza&drv=NOR','landing')
            start=time.monotonic();rep['started_at']=stamp()
            def snapshot(name,module,state,offset):
                t=time.monotonic()
                for detail in page.locator('details').all():
                    if detail.get_attribute('open') is None: detail.locator('summary').click()
                page.wait_for_timeout(300)
                exceptions=page.locator('[data-testid="stException"]').all_text_contents()
                if exceptions: raise RuntimeError('; '.join(exceptions))
                header=' '.join(page.locator('[data-orb-header]').first.inner_text().split())
                lapmatch=re.search(r'Lap (\d+)/(\d+)',header,re.I)
                if module in ('live_predictor','driver_feedback') and lapmatch: state=dict(state,lap=int(lapmatch[1]))
                rec=dict(name=name,route=name,page=module,state=state,scheduled_offset_s=offset,elapsed_s=time.monotonic()-start,observed_at=stamp(),
                    status='ok',numbers=0,matched={},matches=[],ambiguous=[],placeholders=[],unclassified=[],unhashed_live=[],mismatches=[],error=None,notes=[],require_classified_numbers=True)
                base=build_base_references(lock,[v for k,v in state.items() if k in ('lap','ilap')])
                events=[json.loads(x) for x in (log.read_text().splitlines() if log.exists() else []) if x.strip()]
                if module in ('live_predictor','driver_feedback'):
                    refs,evidence=live_runtime_references(base,lock,module,state,events)
                    rec['runtime_evidence']=evidence
                else: refs=route_references(base,lock,module,state)
                # Axis ticks are computed by Plotly from a range and step; prove those
                # operational numbers by reconstructing the arithmetic progression.
                axes=page.locator('.js-plotly-plot').evaluate_all("els=>els.map((e,i)=>({chart:i,axes:Object.fromEntries(Object.entries(e._fullLayout||{}).filter(([k,v])=>/^[xy]axis[0-9]*$/.test(k)&&v).map(([k,v])=>[k,{range:v.range,dtick:v.dtick,tick0:v.tick0,type:v.type}]))}))")
                rec['plotly_axis_runtime']=axes
                for chart in axes:
                    for key,axis in chart['axes'].items():
                        rng=axis.get('range');step=axis.get('dtick');origin=axis.get('tick0') or 0
                        if axis.get('type')=='linear' and rng and isinstance(step,(int,float)) and step>0 and isinstance(origin,(int,float)):
                            lo,hi=sorted(rng);first=math.ceil((lo-origin)/step-1e-10);last=math.floor((hi-origin)/step+1e-10)
                            if last-first>1000:raise RuntimeError('implausible chart tick count')
                            for idx in range(first,last+1):refs.add('runtime:plotly_axis',origin+idx*step,f'chart{chart["chart"]}.{key}:tick0+{idx}*dtick; range={rng}; dtick={step}')
                surfaces=dom_surfaces(page)
                # Preserve all chart text, including the axes omitted by the C5 DOM helper.
                for text in page.locator('.js-plotly-plot .xtick text,.js-plotly-plot .ytick text').all_text_contents():
                    surfaces.append(dict(kind='browser:plotly_tick',widget='chart axis tick',text=text,cells=[],raw=''))
                # Native widget values are separately recorded with their exact current state.
                widgets=page.locator('[data-testid="stMain"] input,[data-testid="stMain"] [role="slider"]').evaluate_all("els=>els.filter(e=>e.getClientRects().length).map(e=>({tag:e.tagName,type:e.type,role:e.getAttribute('role'),label:e.getAttribute('aria-label'),value:e.getAttribute('aria-valuenow')??e.value,min:e.getAttribute('aria-valuemin')??e.min,max:e.getAttribute('aria-valuemax')??e.max}))")
                rec['widget_state']=widgets
                for w in widgets:
                    if w['value'] and re.fullmatch(r'-?\d+(?:\.\d+)?',str(w['value'])):
                        surfaces.append(dict(kind='browser:widget',widget=w.get('label') or w.get('role') or w.get('type'),text=str(w['value']),cells=[],raw=''))
                rec['surfaces']=surfaces;rec['main_text']=page.locator('[data-testid="stMain"]').inner_text();rec['header']=header
                match_surfaces(rec,surfaces,refs);rec['matched_records']=rec.get('matches',[])
                if module=='ghost_strategy':
                    rec['race_twin']=twin_snapshot(page,args.server_proto,out,name)
                    tr=rec['race_twin']['numeric_audit']
                    rec['numbers']+=tr['numbers'];rec['matched_records'].extend(tr.get('matches',[]));rec['mismatches'].extend(tr['mismatches']);rec['unclassified'].extend(tr['unclassified'])
                    for observation in rec['race_twin']['animation_samples']:
                        ar=observation['numeric_audit'];rec['numbers']+=ar['numbers'];rec['matched_records'].extend(ar.get('matches',[]));rec['mismatches'].extend(ar['mismatches']);rec['unclassified'].extend(ar['unclassified'])
                rec['images']=page.locator('[data-testid="stMain"] img').evaluate_all("els=>els.filter(e=>e.getClientRects().length).map(e=>({src:e.src,alt:e.alt}))")
                if module in ('generalisation','validation'):
                    rec['raster_source_proof']={f:digest((args.server_proto/'out/validation'/f).read_bytes()) for f in ('risk_coverage.png','risk_coverage.json','risk_coverage.csv')}
                rec['horizontal_overflow']=page.evaluate('document.documentElement.scrollWidth>window.innerWidth')
                rec['screenshot']=name+'.png';page.screenshot(path=str(out/rec['screenshot']),full_page=True)
                rec['console_errors']=list(rep['console_errors']);rec['network_failures']=list(rep['network_failures']);rec['external_requests']=list(rep['external_requests']);rec['network_runtime']=dict(network_bucket)
                rec['duration_s']=time.monotonic()-t;rep['steps'].append(rec);dump(out/'c6_rehearsal_report.json',rep)
                print(f"{name}: elapsed={rec['elapsed_s']:.1f}s numbers={rec['numbers']} mismatches={len(rec['mismatches'])} unclassified={len(rec['unclassified'])}",flush=True)
                if rec['mismatches'] or rec['unclassified'] or rec['status']!='ok': raise RuntimeError('numeric checkpoint failed: '+name)
                if rec['console_errors'] or rec['network_failures'] or rec['external_requests']: raise RuntimeError('console/network checkpoint failed: '+name)
            go('/live?ev=Monza&drv=NOR&lap=1&mode=live','live');snapshot('live_initial','live_predictor',dict(ev='Monza',drv='NOR',lap=1,mode='live'),0)
            page.get_by_role('button',name='Start replay',exact=True).click();wait_to(20)
            page.get_by_role('button',name='Pause',exact=True).click();page.wait_for_timeout(500)
            snapshot('live_replay_paused','live_predictor',dict(ev='Monza',drv='NOR',mode='live'),20)
            wait_to(45);go('/live?ev=Monza&drv=NOR&lap=30&mode=live','live');snapshot('live_before_feedback','live_predictor',dict(ev='Monza',drv='NOR',lap=30,mode='live'),45)
            wait_to(65);go('/feedback?ev=Monza&drv=NOR&lap=31','feedback');snapshot('feedback_before','driver_feedback',dict(ev='Monza',drv='NOR',lap=31,mode='live'),65)
            wait_to(80);page.get_by_role('textbox',name='Raw message',exact=True).fill(marker)
            print('Submitting authorized single feedback event now',flush=True);page.get_by_role('button',name='Log feedback',exact=True).click();page.wait_for_timeout(1000)
            after=log.read_bytes();event=appended_event(before,after,marker);rep['feedback'].update(event=event,appended_rows=1,after_append_sha256=digest(after));dump(out/'feedback_after.json',event)
            snapshot('feedback_after','driver_feedback',dict(ev='Monza',drv='NOR',lap=31,mode='live'),80)
            wait_to(105);go('/live?ev=Monza&drv=NOR&lap=32&mode=live','live');snapshot('live_after_feedback','live_predictor',dict(ev='Monza',drv='NOR',lap=32,mode='live'),105)
            page.get_by_role('button',name='Start replay',exact=True).click();wait_to(155)
            pause=page.get_by_role('button',name='Pause',exact=True)
            if pause.is_enabled(): pause.click();page.wait_for_timeout(400)
            snapshot('live_replay_finish','live_predictor',dict(ev='Monza',drv='NOR',lap=53,mode='live'),155)
            if rep['steps'][-1]['state']['lap']!=lock['strategy']['Monza']['n_laps']:raise RuntimeError('replay failed to reach race end')
            wait_to(180);go('/ghost?ev=Monza&drv=NOR&mode=audit&ilap=24&rep=MEDIUM','ghost');snapshot('ghost_ready','ghost_strategy',dict(ev='Monza',drv='NOR',mode='audit',ilap=24,rep='MEDIUM'),180)
            frame=next(f for f in page.frames if f.evaluate('typeof window.__orbTwin!=="undefined"'))
            frame.evaluate("""()=>{window.__orbRehearsalSamples=[];const observer=new MutationObserver(()=>window.__orbRehearsalSamples.push(window.__orbRehearsalRead())); for(const id of ['orb-lapno','orb-clock','orb-gap','orb-gapm','orb-a-txt','orb-g-txt','orb-lapval'])observer.observe(document.getElementById(id),{childList:true,characterData:true,subtree:true});window.__orbRehearsalObserver=observer;}""");frame.locator('#orb-play').click();page.wait_for_timeout(5000);frame.locator('#orb-play').click();frame.wait_for_timeout(200);frame.evaluate('window.__orbRehearsalObserver.disconnect()');wait_to(205)
            snapshot('ghost_replayed','ghost_strategy',dict(ev='Monza',drv='NOR',mode='audit',ilap=24,rep='MEDIUM'),205)
            wait_to(235);go('/validation?ev=Monza','validation');snapshot('validation','validation',dict(ev='Monza'),235)
            wait_to(270);go('/generalisation?ev=Monza','generalisation');snapshot('generalisation','generalisation',dict(ev='Monza'),270)
            wait_to(args.duration);go('/pre-race?ev=Madrid','prerace');snapshot('madrid_frozen','pre_race',dict(ev='Madrid'),args.duration)
            context.close();browser.close()
        rep['exit_code']=0
    except Exception as e:
        rep['error']=f'{type(e).__name__}: {e}'
    finally:
        rep['ended_at']=stamp();rep['elapsed_s']=time.monotonic()-start
        try:
            current=log.read_bytes() if log.exists() else b''
            if current!=before:
                appended_event(before,current,marker)
                rep['feedback']['restored_sha256']=restore_feedback(log,before,existed,after if after is not None else current)
            else: rep['feedback']['restored_sha256']=digest(current)
            rep['feedback']['restored_exactly']=(log.read_bytes() if log.exists() else b'')==before and log.exists()==existed
        except Exception as e: rep['exit_code']=2;rep['feedback']['restore_error']=str(e)
        rep['summary']=dict(steps=len(rep['steps']),numbers=sum(x['numbers'] for x in rep['steps']),mismatches=sum(len(x['mismatches']) for x in rep['steps']),
            unclassified=sum(len(x['unclassified']) for x in rep['steps']),load_failures=int(rep['error'] is not None),console_errors=len(rep['console_errors']),network_failures=len(rep['network_failures']),
            external_requests=len(rep['external_requests']),feedback_events=rep['feedback'].get('appended_rows',0),elapsed_s=rep['elapsed_s'])
        if rep['elapsed_s']<args.duration or rep['summary']['feedback_events']!=1 or any(rep['summary'][k] for k in ('mismatches','unclassified','load_failures','console_errors','network_failures','external_requests')):rep['exit_code']=2
        dump(out/'c6_rehearsal_report.json',rep)
    return rep


def twin_snapshot(page,server_proto,out,name):
    frames=[f for f in page.frames if f.evaluate('typeof window.__orbTwin!=="undefined"')]
    if len(frames)!=1:raise RuntimeError('expected one actual Race Twin player')
    f=frames[0];f.evaluate('window.__orbTwin.pause()');f.wait_for_timeout(120)
    sampled=f.evaluate("""()=>{ window.__orbRehearsalRead=()=>{ const nodes=[];const walk=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;
      while(n=walk.nextNode()){const p=n.parentElement;if(p && !['SCRIPT','STYLE'].includes(p.tagName) && p.getClientRects().length && n.textContent.trim())nodes.push(n.textContent.trim());}
      return {t:__orbTwin.t,state:__orbTwin.state(),frames:__orbTwin.frames,fps:__orbTwin.fps,drawn:__orbTwin.drawn,
      text:nodes.join('\\n'),raw_text:document.body.innerText,hud:Object.fromEntries(['orb-lapno','orb-clock','orb-gap','orb-gapm','orb-a-txt','orb-g-txt','orb-lapval','orb-fps'].map(id=>[id,document.getElementById(id).textContent]))};};return window.__orbRehearsalRead();}""")
    script=f.locator('script').inner_text();match=re.search(r'const D = (.*?);\s*if \(!D\)',script,re.S)
    if not match:raise RuntimeError('RaceTwin embedded data absent')
    payload=json.loads(match[1]);data=payload['frames']
    from app_v2.components.race_twin.player import load_assets
    source,_,_=load_assets('Monza','NOR',scenario_id=data['meta'].get('scenario_id'))
    if source is None or source.to_player_dict()!=data:raise RuntimeError('RaceTwin embedded frames differ from frozen source asset')
    checks,rec=verify_twin_sample(sampled,data,name)
    observed=f.evaluate('window.__orbRehearsalSamples || []')
    animation=[]
    for idx,item in enumerate(observed):
        c,audit=verify_twin_sample(item,data,f'{name}:mutation{idx}')
        animation.append(dict(sample=item,checks=c,numeric_audit=audit))
    if name=='ghost_replayed' and (len(animation)<2 or observed[-1]['t']<=observed[0]['t']):raise RuntimeError('RaceTwin animation observer did not record progression')
    dump(out/(name+'_race_twin_frames.json'),data)
    return dict(sample=sampled,checks=checks,numeric_audit=rec,animation_samples=animation,source_frames_exact=True,embedded_frames_sha256=digest(json.dumps(data,sort_keys=True).encode()),frame_evidence=name+'_race_twin_frames.json')


def verify_twin_sample(sampled,data,name):
    s=sampled['state'];t=sampled['t'];i=min(max(math.floor(t),0),len(data['t'])-1);j=min(i+1,len(data['t'])-1);a=t-i;k=i if a<.5 else j
    checks={}
    for dest,src in [('Sa','S_actual'),('Sc','S_cf'),('td','time_delta_s'),('dd','distance_delta_m')]:
        expected=data[src][i]+(data[src][j]-data[src][i])*a;checks[dest]=abs(s[dest]-expected)<1e-9
    for dest,src in [('lapA','lap_actual'),('lapC','lap_cf'),('ageA','tyre_age_actual'),('ageC','tyre_age_cf')]:checks[dest]=s[dest]==data[src][k]
    if not all(checks.values()):raise RuntimeError('RaceTwin runtime interpolation differs from embedded source')
    hud=sampled['hud'];n=data['meta'].get('n_laps',max(data['lap_actual']))
    checks['lap_HUD']=hud['orb-lapno']==f"LAP {s['lapA']} / {n}"
    rounded=math.floor(t+.5);clock=(f'{rounded//3600}:' if rounded>=3600 else '')+f'{(rounded%3600)//60:02d}:{rounded%60:02d}' if rounded>=3600 else f'{rounded//60}:{rounded%60:02d}'
    checks['clock_HUD']=hud['orb-clock']==clock
    distance=(f'{abs(s["dd"])/1000:.2f} km ' if abs(s['dd'])>=1000 else f'{math.floor(abs(s["dd"])+.5)} m ')+('ahead' if s['dd']>=0 else 'behind')
    checks['distance_HUD']=hud['orb-gapm']==distance
    checks['age_HUD']=f"age {s['ageA']}" in hud['orb-a-txt'] and f"age {s['ageC']}" in hud['orb-g-txt']
    gap=('+' if s['td']>0 else '−' if s['td']<0 else '')+f"{abs(s['td']):.1f} s"
    checks['gap_HUD']=hud['orb-gap']=='ghost '+gap
    if not all(checks.values()):raise RuntimeError('RaceTwin HUD differs from runtime state')
    from evaluation.red_team.consistency_probe import ReferenceSet,match_surfaces
    references=ReferenceSet();references.add_record('runtime:race_twin',s,'__orbTwin.state verified against exact frozen frame source')
    for key in ('t','frames','fps','drawn'):references.add('runtime:race_twin',sampled[key],f'__orbTwin.{key} sampled atomically with HUD')
    references.add('runtime:race_twin',n,'frames.meta.n_laps')
    references.add('runtime:race_twin',math.floor(abs(s['dd'])+.5),'round(abs(distance_delta_m))')
    references.add('runtime:race_twin',abs(s['dd'])/1000,'abs(distance_delta_m)/1000 kilometres')
    for val,label in [(rounded//3600,'clock hours'),((rounded%3600)//60,'clock minutes'),(rounded%60,'clock seconds')]:references.add('runtime:race_twin',val,label+' derived from round(tau)')
    for q in (10,90):references.add('contract:race_twin_halo',q,'player.html authored halo quantiles 10–90% (S_cf_q10/S_cf_q90)')
    for speed in (1,2,5,10):references.add('control:race_twin',speed,'player.html authored speed options 1/2/5/10x')
    rec=dict(route=name+':RaceTwin',status='ok',numbers=0,matched={},matches=[],ambiguous=[],placeholders=[],unclassified=[],unhashed_live=[],mismatches=[],notes=[],require_classified_numbers=True)
    match_surfaces(rec,[dict(kind='browser:race_twin_HUD',widget='Race Twin HUD and controls',text=sampled['text'],cells=[],raw='')],references)
    if rec['mismatches'] or rec['unclassified']:raise RuntimeError('RaceTwin displayed number has no source/runtime reference: '+json.dumps(rec['mismatches']+rec['unclassified']))
    return checks,rec

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--base',default='http://localhost:8502');ap.add_argument('--server-proto',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--duration',type=float,default=300);ap.add_argument('--allow-feedback',action='store_true');args=ap.parse_args()
    if args.duration<300:ap.error('definitive rehearsal duration must be at least300seconds')
    result=run(args);print(json.dumps(result['summary'],indent=2));sys.exit(result['exit_code'])
