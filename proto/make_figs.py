"""Run model_v2 on every extracted weekend, learn practice->race transfer factors leave-one-weekend-out,
render the deck figures and write summary_v2.json."""
import glob, os, json, numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import model_v2 as M
import theme
from theme import PAL, INK, MUTED, BG, PANEL, ROSE, LINE

ORDER = ['Australia','Japan','Barcelona','Austria','Belgium','Hungary']

events = sorted({os.path.basename(f).split('_')[0] for f in glob.glob('feat/*_R.csv')})
outs = {}; res = []
for ev in events:
    o = M.run_event(ev, verbose=True)
    if o is not None: outs[ev] = o; res.append(o['res'])
R = pd.concat(res, ignore_index=True)
MIN_PRAC = 30    # a compound needs at least this many clean practice long-run laps before we issue a prediction
MIN_SLOPE = 0.02 # and the cleaned practice curve must show positive degradation; otherwise the confounder model has not isolated the tyre
R['gate'] = np.where(R.n_prac < MIN_PRAC, 'too few practice laps', np.where(R.predA < MIN_SLOPE, 'no positive degradation signal in cleaned practice', 'ok'))
excluded = R[R.gate != 'ok'][['event','compound','n_prac','predA','obs','gate']].round(3).to_dict(orient='records')
R_all = R.copy()
R = R[R.gate == 'ok'].reset_index(drop=True)
order = [e for e in ORDER if e in outs]

# ---------- leave-one-weekend-out transfer factors: race_deg ≈ k[c] * practice_deg ----------
R['ratio'] = R['obs']/R['predA']
k_all = R.groupby('compound')['ratio'].median().to_dict()
MIN_AGREE = 3   # apply a transfer factor only when >=3 other weekends agree (max/min ratio <= 2); otherwise leave the clean curve as is (k = 1)
def loo_k(ev, c):
    o = R[(R.event!=ev)&(R.compound==c)]['ratio']
    if len(o) < MIN_AGREE: return 1.0
    med = float(o.median()); agree = int(((o >= 0.5*med) & (o <= 1.5*med)).sum())
    return med if agree >= max(MIN_AGREE, int(np.ceil(len(o)/2))) else 1.0   # a majority of other weekends must sit within ±50% of their median
R['k_loo'] = [loo_k(e,c) for e,c in zip(R.event, R.compound)]
R['predC'] = R['predA']*R['k_loo']; R['errC'] = (R['predC']-R['obs']).abs()
# baseline: a single global transfer factor (all compounds pooled), also leave-one-weekend-out
R['k_glob'] = [float(R[(R.event!=e)]['ratio'].median()) for e in R.event]
R['predG'] = R['predA']*R['k_glob']; R['errG'] = (R['predG']-R['obs']).abs()
rng = np.random.default_rng(0)
def boot_ci(col, n=4000):
    v = R[col].values; idx = rng.integers(0, len(v), (n, len(v))); m_ = v[idx].mean(axis=1); return [float(np.percentile(m_, 5)), float(np.percentile(m_, 95))]
def boot_diff(a, b, n=4000):
    va, vb = R[a].values, R[b].values; idx = rng.integers(0, len(va), (n, len(va))); d = (va[idx]-vb[idx]).mean(axis=1); return float((d <= 0).mean())
CI = {c: boot_ci(c) for c in ['err_naive','errA','errG','errC']}
per_comp = {}
for c in ['SOFT','MEDIUM','HARD']:
    s = R[R.compound==c]
    if len(s)==0: continue
    d = (s['errA']-s['errC']).values
    if len(d) >= 3:
        idx = rng.integers(0, len(d), (4000, len(d))); dm = d[idx].mean(axis=1); ci = [float(np.percentile(dm,5)), float(np.percentile(dm,95))]
    else: ci = [float('nan'), float('nan')]
    per_comp[c] = dict(n=int(len(s)), mae_naive=float(s['err_naive'].mean()), mae_A=float(s['errA'].mean()), mae_C=float(s['errC'].mean()), k_applied=bool((s['k_loo']!=1.0).any()), k_values=[round(float(v),2) for v in s['k_loo']], ratios=[round(float(v),2) for v in s['ratio']], gain_ci90=ci)
P_C_beats_A = 1-boot_diff('errA','errC')   # share of bootstrap resamples where C has lower MAE than A
R.to_csv('results_v2.csv', index=False)
n_ev = len(order)

# ---------- Fig 1: validation across weekends ----------
rows = [(ev, c) for ev in order for c in ['SOFT','MEDIUM','HARD'] if ((R.event==ev)&(R.compound==c)).any()]
fig, ax = plt.subplots(figsize=(7.4, 0.4*len(rows)+1.3), dpi=170)
for i,(ev,c) in enumerate(rows):
    r = R[(R.event==ev)&(R.compound==c)].iloc[0]; y = len(rows)-1-i
    ax.plot([r.obs, r.predA], [y, y], color='#3A3F47', lw=1, zorder=1)
    ax.scatter(r.naive, y, marker='x', s=30, color='#6B7280', zorder=2)
    ax.scatter(r.predA, y, s=40, facecolors=BG, edgecolors=PAL[c], lw=1.4, zorder=3)
    if np.isfinite(r.predC): ax.scatter(r.predC, y, s=46, color=PAL[c], zorder=4)
    ax.plot([r.obs, r.obs], [y-0.32, y+0.32], color=INK, lw=2.2, zorder=5)
ax.set_yticks(range(len(rows))); ax.set_yticklabels([f"{ev} · {c.title()}" for ev,c in rows][::-1], fontsize=8.5)
ax.set_xlabel("Degradation, s/lap per lap of tyre age"); ax.set_xlim(-0.02, min(0.42, float(R['naive'].max())+0.02))
ax.legend(handles=[Line2D([],[],color=INK,lw=2.2,label='Observed in the race'), Line2D([],[],marker='o',color='w',markerfacecolor=MUTED,ms=7,label='ClearStint: clean practice curve × season transfer factor (leave-one-weekend-out)'),
                   Line2D([],[],marker='o',color='w',markerfacecolor=BG,markeredgecolor=MUTED,ms=7,label='Clean practice curve, uncalibrated'), Line2D([],[],marker='x',color='#6B7280',ls='none',ms=6,label='Naive pooled fit on raw laps')],
          frameon=False, fontsize=8, loc='upper left', bbox_to_anchor=(0.0, -0.16), ncol=1)
fig.tight_layout(); fig.savefig('v2_fig_validation.png', bbox_inches='tight')

# ---------- Fig 2: the transfer gap is systematic ----------
fig, ax = plt.subplots(figsize=(6.4, 3.8), dpi=170)
for j,c in enumerate(['SOFT','MEDIUM','HARD']):
    s = R[R.compound==c]
    ax.scatter([j+np.random.uniform(-0.12,0.12) for _ in range(len(s))], s['ratio'], color=PAL[c], s=42, zorder=3, edgecolors=BG, lw=0.8)
    ax.hlines(k_all[c], j-0.3, j+0.3, color=PAL[c], lw=2.5, zorder=2); ax.text(j+0.33, k_all[c], f"×{k_all[c]:.2f}", va='center', fontsize=10, weight='bold', color=PAL[c])
ax.axhline(1.0, color='#4A5058', lw=1, ls='--'); ax.set_xticks([0,1,2]); ax.set_xticklabels(['Soft','Medium','Hard'])
ax.set_ylabel("Race degradation ÷ cleaned practice degradation"); ax.set_ylim(0, max(1.3, float(R['ratio'].max())+0.35))
fig.tight_layout(); fig.savefig('v2_fig_ratio.png', bbox_inches='tight')

# ---------- Fig 3: energy per lap practice vs race, the diagnostic that rules out push level ----------
cand = [ev for ev in order if outs[ev]['res']['energy_source'].iloc[0]=='telemetry']
ev2 = 'Austria' if 'Austria' in cand else (cand[0] if cand else order[0])
o = outs[ev2]; p, r = o['p'], o['r']
fig, ax = plt.subplots(figsize=(6.4, 3.8), dpi=170)
data, labels, cols = [], [], []
for c in ['SOFT','MEDIUM','HARD']:
    a = p.loc[p.Compound==c,'energy_MJ'].dropna(); b = r.loc[r.Compound==c,'energy_MJ'].dropna()
    if len(a)>10 and len(b)>10: data += [a.values, b.values]; labels += [f"{c.title()}\npractice", f"{c.title()}\nrace"]; cols += [PAL[c], PAL[c]]
bp = ax.boxplot(data, patch_artist=True, widths=0.6, showfliers=False, medianprops=dict(color=BG, lw=1.5))
for i,(patch,col) in enumerate(zip(bp['boxes'], cols)): patch.set_facecolor(col); patch.set_alpha(0.95 if i%2==0 else 0.45); patch.set_edgecolor('none')
ax.set_xticks(range(1,len(labels)+1)); ax.set_xticklabels(labels, fontsize=8.5); ax.set_ylabel("Tyre energy per lap (MJ, proxy)")
ratio_E = float(np.nanmean([p.loc[p.Compound==c,'energy_MJ'].mean()/r.loc[r.Compound==c,'energy_MJ'].mean() for c in ['SOFT','MEDIUM','HARD'] if (p.Compound==c).sum()>10 and (r.Compound==c).sum()>10]))
ax.set_title(f"{ev2} 2026: energy per lap is the same on Friday and Sunday ({100*(ratio_E-1):+.0f}%)", fontsize=10.5, loc='left')
fig.tight_layout(); fig.savefig('v2_fig_energy.png', bbox_inches='tight')

# ---------- Fig 4: clean practice curves vs race curves, same event ----------
pA, A, rA, RA = o['p'], o['A'], o['r'], o['RA']
fig, ax = plt.subplots(1, 2, figsize=(11, 4.1), dpi=170, sharey=True)
for c in ['SOFT','MEDIUM','HARD']:
    s = pA[pA.Compound==c]; t = rA[rA.Compound==c]
    if len(s) >= 8:
        ax[0].scatter(s.TyreLife, s.y_rel, s=12, alpha=.35, color=PAL[c], edgecolors='none'); xs = np.linspace(0, s.TyreLife.max(), 20); ax[0].plot(xs, A[c]*xs, color=PAL[c], lw=2, label=f"{c.title()} {A[c]:+.3f} s/lap")
    if len(t) >= 8 and c in RA:
        ax[1].scatter(t.TyreLife, t.y_rel, s=12, alpha=.3, color=PAL[c], edgecolors='none'); xs = np.linspace(0, t.TyreLife.max(), 20); ax[1].plot(xs, RA[c]*xs, color=PAL[c], lw=2, label=f"{c.title()} {RA[c]:+.3f} s/lap")
ax[0].set_title(f"Practice, cleaned: {len(pA)} laps, {pA.stint_id.nunique()} stints", fontsize=10.5, loc='left'); ax[1].set_title(f"Race, same estimator: {len(rA)} laps, {rA.stint_id.nunique()} stints", fontsize=10.5, loc='left')
for a in ax: a.set_xlabel("Tyre age (laps)"); a.legend(frameon=False, fontsize=8.5)
ax[0].set_ylabel("Pace loss vs fresh tyre (s)")
fig.suptitle(f"{ev2} 2026. Fuel, track evolution, traffic and driver removed on both sides. Hard transfers almost 1:1; soft and medium are managed on Sunday.", fontsize=9.5, y=1.01, color=MUTED)
fig.tight_layout(); fig.savefig('v2_fig_curves.png', bbox_inches='tight')

# ---------- Fig 5: sector shares ----------
sd = M.sector_deg(rA)
fig, ax = plt.subplots(figsize=(6.2, 3.3), dpi=170)
comps = [c for c in ['SOFT','MEDIUM','HARD'] if c in sd]; left = np.zeros(len(comps))
for k,(sec,alpha) in enumerate([('s1',1.0),('s2',0.7),('s3',0.4)]):
    vals = np.array([max(0, sd[c][sec]) for c in comps])
    ax.barh(range(len(comps)), vals, left=left, color=[PAL[c] for c in comps], alpha=alpha, height=0.55, edgecolor=BG, lw=1.5)
    for i,v in enumerate(vals):
        if v > 0.006: ax.text(left[i]+v/2, i, f"S{k+1}", ha='center', va='center', fontsize=8, color=(BG if comps[i]=='MEDIUM' else '#EEEEEE'), weight='bold')
    left += vals
ax.set_yticks(range(len(comps))); ax.set_yticklabels([c.title() for c in comps]); ax.set_xlabel("Race degradation, s/lap per lap, split by sector"); ax.invert_yaxis()
ax.set_title(f"{ev2} 2026: where on the lap the tyre loses time", fontsize=10.5, loc='left')
fig.tight_layout(); fig.savefig('v2_fig_sector.png', bbox_inches='tight')

mae = R[['err_naive','errA','errG','errC']].mean().round(4).to_dict()
summary = dict(events=order, n_rows=int(len(R)), mae=mae, mae_by_comp=R.groupby('compound')[['err_naive','errA','errC']].mean().round(4).to_dict(orient='index'),
               k=k_all, wins_C_over_A=int((R.errC < R.errA).sum()), wins_C_over_naive=int((R.errC < R.err_naive).sum()),
               energy_event=ev2, energy_ratio=ratio_E, n_prac_laps=int(sum(len(outs[e]['p']) for e in order)), n_race_laps=int(sum(len(outs[e]['r']) for e in order)),
               energy_source={e: outs[e]['res']['energy_source'].iloc[0] for e in order}, sector=sd,
               per_event={e: outs[e]['res'][['compound','naive','predA','obs','errA','race_E','prac_E']].round(4).to_dict(orient='records') for e in order},
               hard_err=float(R[R.compound=='HARD']['errA'].mean()), excluded=excluded, min_prac=MIN_PRAC, min_slope=MIN_SLOPE, ci=CI, p_C_beats_A=float(P_C_beats_A), per_comp=per_comp, k_applied_to=[c for c,v in per_comp.items() if v['k_applied']], n_per_comp=R.groupby('compound').size().to_dict(), wins_C_over_G=int((R.errC < R.errG).sum()),
               n_gated_lown=int(sum(1 for e in excluded if e['gate'].startswith('too few'))), n_gated_neg=int(sum(1 for e in excluded if e['gate'].startswith('no positive'))), n_all=int(len(R_all)))
json.dump(summary, open('summary_v2.json','w'), indent=1, default=float)
print("\nSUMMARY", json.dumps({k: summary[k] for k in ['events','n_rows','mae','k','wins_C_over_A','wins_C_over_naive','energy_ratio','hard_err','excluded']}, indent=1, default=float))
