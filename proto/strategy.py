"""Saturday-night replay: compound offsets + calibrated slopes -> crossover laps and a 1-stop vs 2-stop decision,
evaluated under naive / clean / ClearStint curves and scored against the race-observed curves. Also what the field did."""
import json, sys, itertools, numpy as np, pandas as pd
import model_v2 as M
import theme
from theme import PAL, INK, MUTED, BG, PANEL, ROSE, LINE
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
PIT_LOSS = 21.0   # s, typical pit-lane time loss

OFFSET_STEP = 0.6   # s/lap pace step between adjacent compounds, stated assumption (Pirelli nominal order of magnitude); to be estimated from qualifying on Challenge Day
def compound_offsets(d):
    return {'SOFT': 0.0, 'MEDIUM': OFFSET_STEP, 'HARD': 2*OFFSET_STEP}, {'assumed_step_s': OFFSET_STEP}

def stint_time(offset, slope, laps):
    ages = np.arange(1, laps+1); return float(np.sum(offset + slope*ages))

def best_plan(offsets, slopes, n_laps, comps, max_stops=2):
    """enumerate 1- and 2-stop plans (>=2 different compounds), return list of (plan, total_time_rel) sorted"""
    out = []
    for stops in range(1, max_stops+1):
        for seq in itertools.product(comps, repeat=stops+1):
            if len(set(seq)) < 2: continue
            # stint lengths: coarse grid in steps of 2 laps, min 6
            best = None
            if stops == 1:
                for a in range(6, n_laps-5, 1):
                    t = stint_time(offsets[seq[0]], slopes[seq[0]], a) + stint_time(offsets[seq[1]], slopes[seq[1]], n_laps-a) + PIT_LOSS
                    if best is None or t < best[0]: best = (t, (a, n_laps-a))
            else:
                for a in range(6, n_laps-11, 2):
                    for b in range(6, n_laps-a-5, 2):
                        c = n_laps-a-b
                        t = sum(stint_time(offsets[s], slopes[s], L) for s,L in zip(seq,(a,b,c))) + 2*PIT_LOSS
                        if best is None or t < best[0]: best = (t, (a,b,c))
            out.append(dict(plan='-'.join(s[0] for s in seq), stops=stops, stints=best[1], time=best[0]))
    out = sorted(out, key=lambda x: x['time']); base = out[0]['time']
    for o in out: o['delta'] = o['time']-base
    return out

def field_strategy(d):
    r = d[d['session']=='R']; laps = r[r['LapNumber']>=1]
    stints = laps.groupby(['Driver','Stint']).agg(comp=('Compound','first'), n=('LapNumber','size')).reset_index()
    stops = stints.groupby('Driver').size()-1
    finishers = laps.groupby('Driver')['LapNumber'].max(); nl = int(finishers.max()); ok = finishers[finishers >= nl-2].index
    stops = stops.loc[stops.index.intersection(ok)]
    med_len = stints[stints.Driver.isin(ok)].groupby('comp')['n'].median().to_dict()
    return dict(n_laps=nl, stops_mode=int(stops.mode().iloc[0]), stops_share={int(k): int(v) for k,v in stops.value_counts().items()}, median_stint=med_len,
                seqs=stints[stints.Driver.isin(ok)].groupby('Driver')['comp'].apply(lambda s: '-'.join(x[0] for x in s if isinstance(x,str))).value_counts().head(3).to_dict())

def run(ev):
    d = M.load_event(ev); R = pd.read_csv('results_v2.csv'); r = R[R.event==ev].set_index('compound')
    offs, n_off = compound_offsets(d)
    comps = [c for c in ['SOFT','MEDIUM','HARD'] if c in offs]
    # slopes under each view; compounds withheld by the gate fall back to the clean curve for the replay, flagged
    views = {}
    for name, col in [('Naive fit','naive'), ('Clean practice curve','predA'), ('ClearStint','predC'), ('Race-observed (truth)','obs')]:
        s = {}
        for c in comps:
            if c in r.index: s[c] = float(r.loc[c, col])
        views[name] = s
    comps_ok = [c for c in comps if all(c in v for v in views.values())]
    if len(comps_ok) < 2: return None
    fs = field_strategy(d); n_laps = fs['n_laps']
    plans = {name: best_plan(offs, {c: v[c] for c in comps_ok}, n_laps, comps_ok) for name, v in views.items()}
    truth = views['Race-observed (truth)']
    def eval_under_truth(plan):
        seq = plan['plan'].split('-'); m = {'S':'SOFT','M':'MEDIUM','H':'HARD'}
        return sum(stint_time(offs[m[s]], truth[m[s]], L) for s,L in zip(seq, plan['stints'])) + PIT_LOSS*plan['stops']
    truth_best = plans['Race-observed (truth)'][0]; t_best = eval_under_truth(truth_best)
    table = []
    for name in ['Naive fit','Clean practice curve','ClearStint','Race-observed (truth)']:
        rec = plans[name][0]; cost = eval_under_truth(rec) - t_best
        table.append(dict(view=name, plan=rec['plan'], stints=rec['stints'], cost_vs_truth_s=round(cost,1)))
    # crossover laps (ClearStint view): age at which compound j beats compound i on cumulative-time-per-lap basis -> per-lap pace equality
    cs = views['ClearStint']; xo = {}
    for a, b in itertools.combinations(comps_ok, 2):
        if cs[b] != cs[a]:
            L = (offs[b]-offs[a])/(cs[a]-cs[b])   # lap age where pace(a) == pace(b)
            if 0 < L < n_laps: xo[f"{a.title()} vs {b.title()}"] = round(L,1)
    out = dict(event=ev, n_laps=n_laps, offsets=offs, n_offsets=n_off, comps=comps_ok, views=views, table=table, crossover_clearstint=xo, field=fs, pit_loss=PIT_LOSS)
    # figure
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2), dpi=170, gridspec_kw={'width_ratios':[1.05,1]})
    xs = np.arange(1, 36)
    for c in comps_ok:
        ax[0].plot(xs, offs[c] + cs[c]*xs, color=PAL[c], lw=2.4, label=f"{c.title()}: {cs[c]:+.3f} s/lap")
        ax[0].plot(xs, offs[c] + truth[c]*xs, color=PAL[c], lw=1.4, ls=(0,(3,2)), alpha=.7)
    for j,(k,L) in enumerate(sorted(xo.items(), key=lambda kv: kv[1])): ax[0].axvline(L, color='#4A5058', lw=1, ls=':'); ax[0].text(18.5, 4.75-0.45*j, f"{k} cross at lap {L:.0f}", fontsize=7.5, color=MUTED, ha='left', va='top')
    ax[0].set_xlabel("Tyre age (laps)"); ax[0].set_ylabel("Pace vs fresh soft (s/lap)"); ax[0].legend(frameon=False, fontsize=8, loc='upper left')
    ax[0].set_title("ClearStint curves (solid) vs race-observed (dashed)", fontsize=9.5, loc='left')
    ax[1].axis('off')
    short = {'Naive fit':'Naive fit', 'Clean practice curve':'Cleaned curve', 'ClearStint':'ClearStint', 'Race-observed (truth)':'Race-observed'}
    rows = [[short[t['view']], t['plan'], '/'.join(map(str,t['stints'])), f"{t['cost_vs_truth_s']:+.0f} s" if t['view']!='Race-observed (truth)' else '0 (best)'] for t in table]
    tbl = ax[1].table(cellText=rows, colLabels=['Curve used', 'Best plan', 'Stint laps', 'Cost vs best'], colWidths=[0.34,0.22,0.22,0.22], loc='upper center', cellLoc='left', colLoc='left', bbox=[0, 0.42, 1, 0.55])
    tbl.auto_set_font_size(False); tbl.set_fontsize(8.5)
    for (i,j), cell in tbl.get_celld().items():
        cell.set_edgecolor(LINE); cell.set_facecolor(PANEL); cell.get_text().set_color(INK);
        if i == 0: cell.set_text_props(weight='bold', color=MUTED); cell.set_facecolor(BG)
        elif rows[i-1][0]=='ClearStint': cell.set_facecolor(ROSE)
    seqs = ', '.join(f"{k} ({v})" for k,v in fs['seqs'].items())
    ax[1].text(0, 0.30, f"What the field did: {fs['stops_mode']}-stop for {fs['stops_share'].get(fs['stops_mode'],0)} of {sum(fs['stops_share'].values())} classified drivers.\nMost common sequences: {seqs}.\nMedian stint length: " + ', '.join(f"{c.title()} {int(v)}" for c,v in fs['median_stint'].items() if c in comps_ok) + " laps.", fontsize=8.5, color=INK, va='top', wrap=True)
    ax[1].text(0, 0.02, f"Pit loss {PIT_LOSS:.0f} s; compound pace steps assumed {OFFSET_STEP:.1f} s (soft < medium < hard); linear degradation. 'Cost vs best' = extra race time if you follow that curve's plan and the race behaves as observed.", fontsize=7.5, color=MUTED, va='bottom', wrap=True)
    fig.tight_layout(); fig.savefig(f'v2_fig_strategy_{ev}.png', bbox_inches='tight')
    return out

if __name__ == '__main__':
    res = {}
    for ev in (sys.argv[1:] or ['Hungary','Austria']):
        o = run(ev)
        if o: res[ev] = o; print(json.dumps({k: o[k] for k in ['event','n_laps','offsets','n_offsets','table','crossover_clearstint']}, indent=1, default=str)); print('field:', o['field'])
    json.dump(res, open('strategy.json','w'), indent=1, default=str)
