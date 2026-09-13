"""Independent fail-closed C6 release/rehearsal report validation."""
from __future__ import annotations
from datetime import datetime
import hashlib
import json
import re
from math import isfinite
from urllib.parse import urlparse
from evaluation.red_team.browser_consistency import browser_routes, VIEWPORTS

NAV_TITLES = {'Overview','Forecast','Live Predictor','Decision board','Driver feedback','Ghost Strategy','Generalisation','Validation','Guided demo'}


def finite_number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and isfinite(value)


def release_summary(report):
    failures=[]
    if not isinstance(report,dict):
        return dict(status='FAIL',failures=['missing C6 release evidence'])
    if report.get('status')!='PASS' or report.get('checkpoint')!='C6' or report.get('failures')!=[]:
        failures.append('release report itself is not C6 PASS')
    capture=report.get('capture') or {}; routes=capture.get('routes') or {};timings=capture.get('timings') or {}
    expected={name.split('/',1)[1] for name,_,_,_ in browser_routes() if name.startswith('acceptance/')}
    if set(routes)!=expected:
        failures.append('release route inventory incomplete or unexpected')
    if capture.get('external_requests')!=[]:
        failures.append('external requests present or not recorded')
    for key in ('raw_console_errors','raw_network_failures'):
        if capture.get(key)!=[]:
            failures.append(f'{key}: raw session event log not empty/recorded')
    for route in expected:
        row=routes.get(route) or {}
        if set(row)!=set(VIEWPORTS):
            failures.append(f'{route}: viewport matrix incomplete')
        for viewport in VIEWPORTS:
            entry=row.get(viewport) or {};label=f'{route}@{viewport}'
            for key in ('console_errors','other_4xx_5xx','expected_text_missing','benign_base_path_probes_404'):
                if entry.get(key)!=[]:
                    failures.append(f'{label}: {key} not empty/recorded')
            if entry.get('horizontal_overflow') is not False:
                failures.append(f'{label}: horizontal overflow/missing evidence')
            if not finite_number(entry.get('load_ms')) or not 0<entry['load_ms']<2000:
                failures.append(f'{label}: cold load not below 2000ms')
            if not finite_number(entry.get('diff_vs_golden')) or not 0<=entry['diff_vs_golden']<=.15:
                failures.append(f'{label}: golden difference missing/over limit')
            network=entry.get('network') or {}
            if network.get('external_requests')!=[] or not finite_number(network.get('local_request_count')) or network['local_request_count']<=0:
                failures.append(f'{label}: local-only request observation missing/failed')
            sockets=network.get('websockets')
            origin=urlparse(report.get('base',''))
            if not isinstance(sockets,list):
                failures.append(f'{label}: websocket evidence missing')
            else:
                for url in sockets:
                    target=urlparse(url)
                    if target.scheme not in ('ws','wss') or target.hostname!=origin.hostname or (target.port or (443 if target.scheme=='wss' else 80))!=(origin.port or (443 if origin.scheme=='https' else 80)) or (target.scheme=='wss')!=(origin.scheme=='https') or target.username:
                        failures.append(f'{label}: external websocket')
            if route.startswith('presentation_') and entry.get('sidebar_visible') is not False:
                failures.append(f'{label}: presentation controls not hidden')
            if entry.get('offline_notice_visible') is not True:
                failures.append(f'{label}: offline notice unproven')
    for viewport in VIEWPORTS:
        keyboard=timings.get(f'keyboard_nav_{viewport}') or {}
        if keyboard.get('missing')!=[] or keyboard.get('enter_activates') is not True or set(keyboard.get('reached',[]))!=NAV_TITLES:
            failures.append(f'{viewport}: keyboard route/Enter proof incomplete')
        activations=keyboard.get('activations') or []
        if len(activations)!=len(NAV_TITLES) or {a.get('target') for a in activations}!=NAV_TITLES or any(a.get('activated') is not True or not finite_number(a.get('switch_ms')) or a['switch_ms']>600 for a in activations):
            failures.append(f'{viewport}: each keyboard target must activate within600ms')
        for key in (f'route_switch_ms_{viewport}',f'route_switch_validation_ms_{viewport}'):
            if not finite_number(timings.get(key)) or not 0<timings[key]<600:
                failures.append(f'{key}: switch not below 600ms')
        replay=timings.get(f'replay_run_{viewport}') or {}
        if replay.get('console_errors')!=[] or replay.get('bad_responses')!=[] or 'Lap' not in replay.get('header_after_6s',''):
            failures.append(f'{viewport}: replay progression evidence missing/failed')
    return dict(status='FAIL' if failures else 'PASS',generated_at=report.get('generated_at'),
                expected_cases=len(expected)*len(VIEWPORTS),failures=failures)


def rehearsal_summary(report):
    failures=[]
    if not isinstance(report,dict):
        return dict(status='FAIL',failures=['missing C6 rehearsal evidence'])
    if report.get('exit_code')!=0:
        failures.append('rehearsal did not exit successfully')
    elapsed=report.get('elapsed_s')
    if not finite_number(elapsed) or elapsed<300:
        failures.append('rehearsal elapsed time below 300 seconds/missing')
    try:
        wall=(datetime.fromisoformat(report['ended_at'])-datetime.fromisoformat(report['started_at'])).total_seconds()
        if wall<300 or not finite_number(elapsed) or abs(wall-elapsed)>5:
            failures.append('wall-clock duration does not prove the reported five minutes')
    except (KeyError,TypeError,ValueError):
        failures.append('missing/invalid start and end timestamps')
    steps=report.get('steps') or []
    required={'live_predictor','ghost_strategy','validation','generalisation','pre_race'}
    if not required<={step.get('page') for step in steps}:
        failures.append('required rehearsal pages missing')
    live_states=[step.get('state') or {} for step in steps if step.get('page')=='live_predictor']
    monza_laps=[s['lap'] for s in live_states if s.get('ev')=='Monza' and s.get('drv')=='NOR' and finite_number(s.get('lap'))]
    if not monza_laps or max(monza_laps)<=min(monza_laps):
        failures.append('Monza NOR live replay did not demonstrably advance')
    if not any(step.get('page')=='ghost_strategy' and all((step.get('state') or {}).get(k)==v for k,v in dict(ev='Monza',drv='NOR',ilap=24,rep='MEDIUM').items()) for step in steps):
        failures.append('requested Monza NOR lap24 MEDIUM Ghost scenario unproven')
    if not any(step.get('page')=='pre_race' and (step.get('state') or {}).get('ev')=='Madrid' for step in steps):
        failures.append('Madrid forecast page unproven')
    offsets=[step.get('elapsed_s') for step in steps]
    if not offsets or any(not finite_number(x) for x in offsets) or offsets!=sorted(offsets) or offsets[-1]<290:
        failures.append('timed samples do not span the rehearsal')
    for index,step in enumerate(steps):
        for key in ('mismatches','unclassified','console_errors','network_failures'):
            if step.get(key)!=[]:
                failures.append(f'step{index}: {key} present/not recorded')
        if not finite_number(step.get('numbers')) or step['numbers']<=0:
            failures.append(f'step{index}: numeric evidence missing')
        matches=step.get('matched_records')
        if not isinstance(matches,list) or len(matches)!=step.get('numbers'):
            failures.append(f'step{index}: not every numeric observation has provenance')
        elif any(not m.get('reference') or not finite_number(m.get('reference_value')) for m in matches):
            failures.append(f'step{index}: incomplete reference records')
    summary=report.get('summary') or {}
    for key in ('mismatches','unclassified','load_failures','console_errors','network_failures','external_requests'):
        if summary.get(key)!=0:
            failures.append(f'summary.{key} not zero/recorded')
    for key in ('external_requests','console_errors','network_failures'):
        if report.get(key)!=[]:
            failures.append(f'{key}: raw event log not empty/recorded')
    feedback=report.get('feedback') or {}; event=feedback.get('event')
    if summary.get('feedback_events')!=1 or feedback.get('appended_rows')!=1 or feedback.get('restored_exactly') is not True:
        failures.append('exactly one feedback event and restoration unproven')
    if not feedback.get('before_sha256') or feedback.get('before_sha256')!=feedback.get('restored_sha256'):
        failures.append('feedback cleanup hash differs')
    if not event or not any(event in ((step.get('runtime_evidence') or {}).get('consumed_events') or []) for step in steps):
        failures.append('submitted feedback event not proved consumed by live runtime')
    twins=[step['race_twin'] for step in steps if step.get('race_twin')]
    if not twins or any(t.get('source_frames_exact') is not True or not t.get('checks') or not all(v is True for v in t['checks'].values()) for t in twins):
        failures.append('Race Twin frame/HUD evidence missing or failed')
    return dict(status='FAIL' if failures else 'PASS',generated_at=report.get('generated_at'),elapsed_s=elapsed,
                steps=len(steps),numbers=summary.get('numbers'),failures=failures)


def readme_summary(proto):
    """Direct assertions for README facts absent from the historical contested-claim catalog."""
    path=proto/'README.md';failures=[]
    if not path.exists():
        return dict(status='FAIL',failures=['README missing'])
    text=path.read_text()
    forecast=json.loads((proto/'out/forecast_Madrid_2026.json').read_text())
    lock=json.loads((proto/'out/lock_v2.json').read_text())
    aggregate=json.loads((proto/'out/validation/holdout_aggregate.json').read_text())
    for name in ('forecast_Madrid_2026.json','forecast_Madrid_2026.pdf','forecast_Madrid_2026.sha256'):
        digest=hashlib.sha256((proto/'out'/name).read_bytes()).hexdigest()
        if not any(name in line and digest in line for line in text.splitlines()):
            failures.append(f'{name}: full digest missing/different')
    if not any('shared.forecast_hash' in line and lock['shared']['forecast_hash'] in line for line in text.splitlines()):
        failures.append('lock-v2 forecast hash missing/different')
    issued=datetime.fromisoformat(forecast['issued_at'])
    if issued.strftime('%d %B %Y at %H:%M:%S IST') not in text:
        failures.append('forecast publication date/time missing/different')
    if 'sealed holdout, aggregate only' not in text:
        failures.append('required aggregate-only label missing')
    match=re.search(r'MAE\s+([0-9.]+)\s+(?:vs|versus)\s+naive\s+([0-9.]+)\s*s/lap,\s*coverage\s+([0-9.]+),\s*(\d+)\s*weekends\s*/\s*(\d+)\s*compound-weekends',text)
    expected=(0.0372,0.1713,1.0,5.0,9.0)
    f=aggregate['aggregate']['forecast']
    source_values=(round(f['mae']['orb_v1'],4),round(f['mae']['naive'],4),f['band_coverage90']['all'],f['n_weekends'],f['n_compound_weekends'])
    if source_values!=expected:
        failures.append('sealed source headline differs from approved frozen aggregate')
    if not match or tuple(map(float,match.groups()))!=expected:
        failures.append('README approved sealed aggregate headline missing/different')
    if aggregate.get('quotable') is not True or aggregate.get('dry_run_before_freeze') is not False or aggregate.get('post_holdout_tuning') is not False:
        failures.append('sealed source is not the quotable untuned post-freeze aggregate')
    return dict(status='FAIL' if failures else 'PASS',failures=failures,
                source='README.md',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),facts_checked=6)
