"""Independent report/precision/animation refutation; does not execute dashboard code."""
import argparse, hashlib, json, math
from pathlib import Path
from datetime import datetime, timezone
from evaluation.red_team.c6_evidence import rehearsal_summary

def inspect(source):
    path=source/'c6_rehearsal_report.json';report=json.loads(path.read_text())
    gate=rehearsal_summary(report);failures=list(gate['failures']);count=0;animation_count=0
    for step in report.get('steps',[]):
        for m in step.get('matched_records',[]):
            count+=1; value=m.get('value');ref=m.get('reference_value');dec=m.get('decimals')
            if not isinstance(dec,int) or dec<0 or not any(abs(float(f'{v:.{dec}f}'))==abs(value) for v in (ref,ref*100)):
                failures.append(f"{step['name']}: display precision differs from recorded reference")
        twin=step.get('race_twin')
        if not twin:continue
        frames_path=source/twin['frame_evidence'];data=json.loads(frames_path.read_text())
        if hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()!=twin['embedded_frames_sha256']:
            failures.append('recorded RaceTwin frame digest differs')
        samples=[twin['sample']]+[a['sample'] for a in twin['animation_samples']]
        animation_count+=len(twin['animation_samples'])
        if step['name']=='ghost_replayed' and (len(samples)<3 or samples[-1]['t']<=samples[1]['t']):failures.append('no observed animation advancement')
        for sample in samples:
            t=sample['t'];state=sample['state'];i=min(max(math.floor(t),0),len(data['t'])-1);j=min(i+1,len(data['t'])-1);fraction=t-i;k=i if fraction<.5 else j
            for key,column in [('Sa','S_actual'),('Sc','S_cf'),('td','time_delta_s'),('dd','distance_delta_m')]:
                expected=data[column][i]*(1-fraction)+data[column][j]*fraction
                if not math.isclose(state[key],expected,abs_tol=1e-8,rel_tol=0):failures.append(f'animation state {key} differs from source interpolation')
            for key,column in [('lapA','lap_actual'),('lapC','lap_cf'),('ageA','tyre_age_actual'),('ageC','tyre_age_cf')]:
                if state[key]!=data[column][k]:failures.append(f'animation state {key} differs from discrete source frame')
    if count!=report.get('summary',{}).get('numbers'):failures.append('summary number count differs from independent record count')
    return dict(status='FAIL' if failures else 'PASS',generated_at=datetime.now(timezone.utc).isoformat(),report_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),gate=gate,independent_precision_records=count,independent_animation_samples=animation_count,failures=failures,note='Direct report, raw-error, duration, provenance precision and recorded-frame interpolation checks; no dashboard run or product mutation.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    result=inspect(args.source);args.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));raise SystemExit(0 if result['status']=='PASS' else 2)
