"""Prototype: isolate tyre degradation from FP2 long runs; validate on race.
Stage 1: track evolution from each driver's push laps vs session time (driver-demeaned).
Stage 2: within-stint regression with stint fixed effects (absorbs driver, fuel-start, compound offset),
         after removing fuel burn (prior) and track evolution. Slope per compound = degradation.
Same estimator applied to race stints for validation.
"""
import fastf1, numpy as np, pandas as pd, warnings, logging, json
warnings.filterwarnings("ignore"); logging.getLogger("fastf1").setLevel(logging.ERROR)
import os; fastf1.Cache.enable_cache(os.path.expanduser('~/Trackshift/cache'))
YEAR, GP = 2026, 'Hungary'
FUEL_S_PER_KG, FUEL_KG_PER_LAP = 0.03, 1.6
COMPS = ['SOFT','MEDIUM','HARD']; PAL={'SOFT':'#C8102E','MEDIUM':'#D9A400','HARD':'#3A506B'}

def clean(laps):
    l = laps[laps['LapTime'].notna() & laps['IsAccurate'] & (laps['TrackStatus']=='1') & laps['PitOutTime'].isna() & laps['PitInTime'].isna()].copy()
    l['lap_s'] = l['LapTime'].dt.total_seconds(); l['t_min'] = l['LapStartTime'].dt.total_seconds()/60
    return l[l['Compound'].isin(COMPS)]

def fit_deg(df, evo_per_min=0.0, fuel_col='fuel'):
    """stint fixed effects + per-compound slope on TyreLife; returns slopes, residual std, corrected df"""
    d = df.copy()
    d['y'] = d['lap_s'] - FUEL_S_PER_KG*d[fuel_col] - evo_per_min*d['t_min']
    d['stint_id'] = d['Driver']+'_'+d['Stint'].astype(int).astype(str)
    stints = sorted(d['stint_id'].unique())
    X = [ (d['stint_id']==s).astype(float).values for s in stints ]
    X += [ ((d['Compound']==c)*d['TyreLife']).values.astype(float) for c in COMPS ]
    X = np.column_stack(X); b,*_ = np.linalg.lstsq(X, d['y'].values, rcond=None)
    slopes = {c: float(b[len(stints)+i]) for i,c in enumerate(COMPS)}
    fe = dict(zip(stints, b[:len(stints)])); d['fe']=d['stint_id'].map(fe)
    d['y_rel'] = d['y'] - d['fe']          # pace loss vs fresh tyre (relative)
    d['resid'] = d['y'] - X@b
    return slopes, float(d['resid'].std()), d

# ---------- FP2 ----------
fp2 = fastf1.get_session(YEAR, GP, 'FP2'); fp2.load(laps=True, telemetry=False, weather=True, messages=False)
p = clean(fp2.laps)
# stage 1: evolution from push laps (each driver's laps within 101% of own session best), driver-demeaned
push = p[p['lap_s'] <= 1.01*p.groupby('Driver')['lap_s'].transform('min')].copy()
push['dm'] = push['lap_s'] - push.groupby('Driver')['lap_s'].transform('mean')
evo = float(np.polyfit(push['t_min'], push['dm'], 1)[0]) if len(push)>10 else 0.0
print(f"Stage 1 track evolution: {evo:+.4f} s/min from {len(push)} push laps  (~{evo*60:+.2f} s over an hour)")
# stage 2: long runs
lr = p[p.groupby(['Driver','Stint'])['lap_s'].transform('size')>=5].copy()
lr = lr[lr['lap_s'] <= 1.03*lr.groupby(['Driver','Stint'])['lap_s'].transform('min')]   # drop cool-down/traffic laps
lr['fuel'] = 60 - FUEL_KG_PER_LAP*(lr['TyreLife']-1)   # assumed long-run fuel; stint FE absorbs the level, only the burn slope matters
naive = {c: float(np.polyfit(lr.loc[lr.Compound==c,'TyreLife'], lr.loc[lr.Compound==c,'lap_s'],1)[0]) for c in COMPS}
deg_nofix, _, _ = fit_deg(lr.assign(fuel=0.0), 0.0)          # stint FE only (no fuel/evo correction)
deg, rs, lrc = fit_deg(lr, evo)
print(f"FP2 long-run laps: {len(lr)}, stints: {lr.groupby(['Driver','Stint']).ngroups}, {lr['Compound'].value_counts().to_dict()}")
print("Naive pooled slope        :", {c: round(v,3) for c,v in naive.items()})
print("Stint-FE, no fuel/evo     :", {c: round(v,3) for c,v in deg_nofix.items()})
print("Stint-FE + fuel + evo (ours):", {c: round(v,3) for c,v in deg.items()}, " resid std", round(rs,3))

# ---------- Race ----------
r = fastf1.get_session(YEAR, GP, 'R'); r.load(laps=True, telemetry=False, weather=False, messages=False)
rl = clean(r.laps); n_laps = int(r.laps['LapNumber'].max())
rl['fuel'] = 110*(1-(rl['LapNumber']-1)/n_laps)
rl = rl[rl.groupby(['Driver','Stint'])['lap_s'].transform('size')>=8]
rl = rl[rl['lap_s'] <= 1.03*rl.groupby(['Driver','Stint'])['lap_s'].transform('min')]
race_deg, race_rs, rlc = fit_deg(rl, 0.0)
print(f"RACE laps used: {len(rl)}, stints: {rl.groupby(['Driver','Stint']).ngroups}")
print("RACE observed degradation  :", {c: round(v,3) for c,v in race_deg.items()}, " resid std", round(race_rs,3))
err = {c: round(abs(deg[c]-race_deg[c]),3) for c in COMPS}
print("Abs error FP2->race (s/lap):", err, "| naive error:", {c: round(abs(naive[c]-race_deg[c]),3) for c in COMPS})

# ---------- Figures ----------
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,'grid.color':'#E6E6E6','grid.linewidth':.6})
fig,ax=plt.subplots(1,2,figsize=(11,4.3),dpi=170)
for c in COMPS:
    s=lr[lr.Compound==c]; sc=lrc[lrc.Compound==c]; xs=np.linspace(1,max(s.TyreLife.max(),2),20)
    ax[0].scatter(s.TyreLife,s['lap_s'],s=14,alpha=.35,color=PAL[c],edgecolors='none')
    k,b0=np.polyfit(s.TyreLife,s['lap_s'],1); ax[0].plot(xs,k*xs+b0,color=PAL[c],lw=2,label=f"{c.title()}  {k:+.3f} s/lap")
    ax[1].scatter(sc.TyreLife,sc['y_rel'],s=14,alpha=.35,color=PAL[c],edgecolors='none')
    ax[1].plot(xs,deg[c]*xs,color=PAL[c],lw=2,label=f"{c.title()}  {deg[c]:+.3f} s/lap")
ax[0].set_title("Raw long-run lap times (pooled fit)",fontsize=11); ax[1].set_title("Fuel, track evolution & driver removed (our model)",fontsize=11)
ax[0].set_ylabel("Lap time (s)"); ax[1].set_ylabel("Pace loss vs fresh tyre (s)")
for a in ax: a.set_xlabel("Tyre age (laps)"); a.legend(frameon=False,fontsize=9)
fig.tight_layout(); fig.savefig("fig1_raw_vs_corrected.png",bbox_inches='tight')
fig,ax=plt.subplots(figsize=(6.4,4.3),dpi=170); xs=np.arange(0,31)
for c in COMPS:
    ax.plot(xs,deg[c]*xs,color=PAL[c],lw=2.2,label=f"{c.title()} · predicted from FP2 ({deg[c]:+.3f})")
    ax.plot(xs,race_deg[c]*xs,color=PAL[c],lw=2.2,ls=(0,(4,2)),label=f"{c.title()} · observed in race ({race_deg[c]:+.3f})")
ax.set_xlabel("Tyre age (laps)"); ax.set_ylabel("Pace loss vs fresh tyre (s)"); ax.legend(frameon=False,fontsize=8.5)
ax.set_title("Post-race validation: Friday prediction vs Sunday pace",fontsize=11); fig.tight_layout(); fig.savefig("fig2_validation.png",bbox_inches='tight')
json.dump({'evo_per_min':evo,'naive':naive,'stintfe_only':deg_nofix,'ours':deg,'race':race_deg,'err':err,'n_fp2':int(len(lr)),'n_race':int(len(rl)),'resid_fp2':rs,'resid_race':race_rs},open('results.json','w'),indent=1)
print("saved figures + results.json")
