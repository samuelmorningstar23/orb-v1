"""Independent C5 arithmetic/cluster/chronology refuter; never reads per-race holdout."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
import numpy as np


def read(path):
    assert path.name != 'holdout_per_race.json', 'sealed per-race evidence prohibited'
    return json.loads(path.read_text())


def cluster_mean(rows):
    """Independent bootstrap: repeatedly select cluster names and replicate their raw observations."""
    groups = {}
    for name, value, weight in rows:
        if value is not None and np.isfinite(value) and weight is not None and np.isfinite(weight) and weight > 0:
            groups.setdefault(name, []).append((float(value), float(weight)))
    names = sorted(groups)
    if not names:
        return dict(estimate=None, ci90=None, n=0, n_weekends=0)
    def stat(keys):
        values = [pair for key in keys for pair in groups[key]]
        return sum(v*w for v,w in values) / sum(w for v,w in values)
    bands = None
    if len(names) >= 2:
        rng=np.random.default_rng(2026)
        samples=[stat(rng.choice(names, len(names), replace=True)) for _ in range(2000)]
        bands=np.percentile(samples,[5,95]).tolist()
    return dict(estimate=stat(names), ci90=bands,
                n=int(sum(w for values in groups.values() for _,w in values)), n_weekends=len(names))


def check_metric(actual, expected, label):
    for key in ('estimate','ci90','n','n_weekends'):
        a,b=actual.get(key),expected[key]
        assert (a is None and b is None) or (a is not None and b is not None and np.allclose(a,b,rtol=1e-10,atol=1e-12)), f'{label}.{key} differs'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,default=Path.cwd());ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args(); root=args.source.resolve();sys.path.insert(0,str(root))
    def deny_per_race(event, arguments):
        if event == 'open' and isinstance(arguments[0], (str, bytes)) and Path(arguments[0]).name == 'holdout_per_race.json':
            raise PermissionError('per-race holdout read is forbidden, including helper reads')
    sys.addaudithook(deny_per_race)
    inputs=('out/lock.json','out/validation/ghost_scorecard.json','out/validation/live_scorecard.json',
            'out/validation/risk_coverage.json','out/validation/risk_coverage.csv','out/validation/holdout_aggregate.json','out/live/prefix_eval.json')
    fingerprints={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in inputs}
    checks=[]
    lock=read(root/'out/lock.json');ghost=read(root/'out/validation/ghost_scorecard.json')
    live=read(root/'out/validation/live_scorecard.json');prefix=read(root/'out/live/prefix_eval.json')
    holdout_path=root/'out/validation/holdout_aggregate.json';holdout=read(holdout_path)
    assert holdout['quotable'] is True and holdout['dry_run_before_freeze'] is False and holdout['post_holdout_tuning'] is False
    assert ghost['sealed_holdout']['aggregate'] == holdout['aggregate']
    assert ghost['sealed_holdout']['source_sha256'] == hashlib.sha256(holdout_path.read_bytes()).hexdigest()
    assert live['source']['sha256'] == hashlib.sha256((root/'out/live/prefix_eval.json').read_bytes()).hexdigest()
    assert live['per_race'] == prefix['races']
    assert all(row['match'] for row in live['source_consistency'].values()), 'live pooled point estimate differs from source'
    checks.append(dict(check='aggregate_and_prefix_provenance',status='PASS'))
    weights={'next1_mae':'next1_n','next1_mae_prior_only':'next1_n','cum3_mae':'cum3_n','cum3_mae_prior_only':'cum3_n',
             'cum5_mae':'cum5_n','cum5_mae_prior_only':'cum5_n','coverage90_next1':'next1_n','coverage90_next1_prior_only':'next1_n',
             'coverage90_next3':'next3_n','cliff3_brier':'cliff3_n','cliff5_brier':'cliff5_n','recommendation_change_rate':'lap_pairs',
             'aw_false_alert_episodes_per_stint':'aw_false_stints','aw_detection_rate':'aw_true_stints'}
    for metric,weight in weights.items():
        rows=[(event,data.get(metric),data.get(weight)) for event,data in prefix['races'].items()]
        check_metric(live['pooled'][metric],cluster_mean(rows),'live.'+metric)
    # Nonlinear pooled climatology is fitted again after each weekend resample.
    for horizon in (3,5):
        count=f'cliff{horizon}_n';events=f'cliff{horizon}_events'
        names=sorted(name for name,row in prefix['races'].items() if row[count]>0)
        def climatology(draw):
            p=sum(prefix['races'][name][events] for name in draw)/sum(prefix['races'][name][count] for name in draw)
            return p*(1-p)
        rng=np.random.default_rng(2026)
        stats=[climatology(rng.choice(names,len(names),replace=True)) for _ in range(2000)]
        check_metric(live['pooled'][f'cliff{horizon}_brier_climatology'],dict(estimate=climatology(names),ci90=np.percentile(stats,[5,95]).tolist(),
                     n=sum(prefix['races'][name][count] for name in names),n_weekends=len(names)),f'climatology{horizon}')
    groups={event:[a['lead_laps'] for a in rows if a.get('truth') and a.get('lead_laps') is not None and np.isfinite(a['lead_laps'])]
            for event,rows in prefix['per_stint_alerts'].items()}
    groups={key:values for key,values in groups.items() if values}; names=sorted(groups)
    median=lambda draw:float(np.median([v for name in draw for v in groups[name]]))
    rng=np.random.default_rng(2026);stats=[median(rng.choice(names,len(names),replace=True)) for _ in range(2000)]
    check_metric(live['pooled']['aw_lead_laps_median'],dict(estimate=median(names),ci90=np.percentile(stats,[5,95]).tolist() if len(names)>1 else None,
                 n=sum(map(len,groups.values())),n_weekends=len(names)),'alert_lead')
    checks.append(dict(check='live_independent_weekend_bootstrap',status='PASS',metrics=len(weights)+3,draws_per_metric=2000))
    # Independently derive the lock's displayed MAEs and grouped intervals from its public validation rows.
    rows=lock['validation_rows']; expected=cluster_mean([(r['event'],abs(r['pred_clearstint']-r['obs']),1) for r in rows])
    actual=ghost['development_pool']['by_season']['2026']['forecast']['bootstrap']['mae_orb_v1']
    # Lock serialization rounds inputs; exact new scorer output may differ within its declared tolerance.
    assert abs(actual['estimate']-expected['estimate']) < 5e-4
    assert np.allclose(actual['ci90'],expected['ci90'],atol=5e-4,rtol=0)
    assert actual['n']==expected['n'] and actual['n_weekends']==expected['n_weekends']
    assert ghost['development_pool']['lock_consistency_2026']['all_match']
    checks.append(dict(check='lock_public_rows_independent_mae_and_weekend_band',status='PASS',rows=len(rows)))
    # Verify every risk CSV band/count exactly mirrors its JSON cell (121 x six metrics).
    import pandas as pd
    risk=read(root/'out/validation/risk_coverage.json');csv=pd.read_csv(root/'out/validation/risk_coverage.csv')
    for row,(_,tab) in zip(risk['table'],csv.iterrows(),strict=True):
        assert int(tab['min_laps'])==row['min_laps'] and np.isclose(tab['min_slope'],row['min_slope'])
        for key,b in row['bootstrap'].items():
            assert np.isclose(b['estimate'],row[key]) if row[key] is not None else b['estimate'] is None
            assert tab[key+'_n']==b['n'] and tab[key+'_n_weekends']==b['n_weekends']
            for i,suffix in enumerate(('low','high')):
                value=tab[key+'_ci90_'+suffix]
                assert np.isclose(value,b['ci90'][i],atol=1e-9) if b['ci90'] else pd.isna(value)
    checks.append(dict(check='risk_csv_json_all_cells',status='PASS',rows=len(csv),metrics=6))
    # Rebuild independent errors at the production gate and two extreme gate cells.
    from evaluation import SEASON_DIRS
    from evaluation.forecast import SeasonForecaster
    forecasters=[SeasonForecaster(SEASON_DIRS[season],season,sealed=[r for r in ghost['sealed_excluded'] if r.startswith(str(season)+'_')])
                 for season in ghost['seasons']]
    for minimum,slope in ((10,0.0),(30,0.02),(60,0.05)):
        observations=[]
        for F in forecasters:
            F.set_gate(minimum,slope)
            for event in F.development_events:
                pool=[e for e in F.development_events if e!=event]
                assert not any(F.rid(e) in ghost['sealed_excluded'] for e in pool+[event])
                forecast=F._raw_forecast(event,pool,compute_band=False); reference=F.reference(event)
                for compound,info in forecast.items():
                    if compound not in reference:
                        continue
                    observed=reference[compound]['obs']
                    observations.append(dict(cluster=F.rid(event),issued=info.issued,
                        err=abs(info.prediction-observed) if info.prediction is not None else None,
                        naive=abs(info.naive-observed) if np.isfinite(info.naive) else None))
        cell=next(r for r in risk['table'] if r['min_laps']==minimum and r['min_slope']==slope)
        for metric,field,issued in [('coverage','issued',None),('mae_all','err',None),('mae_naive','naive',None),
                                    ('mae_issued','err',True),('mae_fallback','err',False),('mae_naive_issued','naive',True)]:
            independent=cluster_mean([(r['cluster'],r[field],1) for r in observations if issued is None or r['issued']==issued])
            check_metric(cell['bootstrap'][metric],independent,f'risk.{minimum}.{slope}.{metric}')
    checks.append(dict(check='risk_independent_error_and_cluster_band_recomputation',status='PASS',gate_cells=3,metrics_per_cell=6,draws_per_metric=2000))
    # Exercise strict chronology, recording every factor/fallback pool call at runtime.
    from evaluation import CALENDAR_2026,SEASON_DIRS
    from evaluation.forecast import SeasonForecaster,score_forecast
    forecaster=SeasonForecaster(SEASON_DIRS[2026],2026)
    order=[event for event in CALENDAR_2026 if event in forecaster.metas]
    original=forecaster._pool_rows; allowed=set(); calls=0
    def guarded(target,pool,what,*a,**kw):
        nonlocal calls
        assert set(pool)<=allowed and target not in pool, 'target/future weekend in training pool'
        result=original(target,pool,what,*a,**kw);calls+=1
        return result
    forecaster._pool_rows=guarded
    rolling=ghost['rolling_origin_2026']['series']
    for index,event in enumerate(order):
        allowed={e for e in order[:index] if forecaster.metas[e]['completed']}
        row=next(s for s in rolling if s['event']==event)
        assert row['n_pool']==len(allowed)
        if not forecaster.metas[event]['completed']:
            assert 'note' in row
            continue
        forecast=forecaster.forecast(event,sorted(allowed),target_obs_in_widening=False)
        assert set(forecast.pool_events)==allowed
        scored=score_forecast(forecast,forecaster.reference(event))
        for metric,value in [('mae_orb_v1','err'),('mae_naive','err_naive'),('band_coverage90','covered')]:
            independent=cluster_mean([(event,r[value],1) for r in scored])
            check_metric(row['bootstrap'][metric],independent,event+'.'+metric)
        for compound,info in forecast.compounds.items():
            assert row['factors'][compound]['k']==info.factor
    checks.append(dict(check='rolling_temporal_pool_guard_and_independent_round_metrics',status='PASS',rounds=len(order),pool_calls=calls))
    assert fingerprints == {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in inputs}, 'inputs changed during refutation'
    report=dict(status='PASS',generated_at=datetime.now(timezone.utc).isoformat(),input_sha256=fingerprints,checks=checks,notes=['No per-race holdout reads; aggregate equivalence checked without printing figures.',
                'Independent raw-observation cluster resampling uses no evaluation bootstrap helper.',
                'Risk full matrix cross-format checked; production and two extreme gate cells independently recomputed.'])
    args.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':
    main()
