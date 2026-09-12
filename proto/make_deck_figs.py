"""Deck figures, all from out/lock.json (+ out/liquid.json), matplotlib, theme.py palette. Writes out/fig_*.png."""
import json, os, numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import theme; from theme import PAL, INK, MUTED, BG, PANEL, LINE, RED, GOLD, SLATE
import model_v2 as M
L = json.load(open('out/lock.json')); V = pd.DataFrame(L['validation_rows']); val = L['validation']
LQ = json.load(open('out/liquid.json')) if os.path.exists('out/liquid.json') else {}
os.makedirs('out', exist_ok=True); DPI = 200

# 1. calibration scatter: predicted from Friday vs observed in the race, all cases
fig, ax = plt.subplots(figsize=(5.6, 5.0), dpi=DPI); mx = float(max(V.obs.max(), V.pred_clearstint.max(), V.naive.max())) + 0.02
ax.plot([0, mx], [0, mx], color=MUTED, lw=1, ls='--', zorder=1)
for c in ['SOFT', 'MEDIUM', 'HARD']:
    s = V[V.compound == c]
    ax.scatter(s.naive, s.obs, marker='x', s=34, color=PAL[c], alpha=0.45, zorder=2)
    ax.scatter(s[s.issued].pred_clearstint, s[s.issued].obs, s=70, color=PAL[c], edgecolors=BG, lw=1, zorder=4)
    ax.scatter(s[~s.issued].pred_clearstint, s[~s.issued].obs, s=70, facecolors=BG, edgecolors=PAL[c], lw=1.6, marker='D', zorder=4)
ax.set_xlabel('Predicted from Friday (s/lap per lap of tyre age)'); ax.set_ylabel('Observed in the race'); ax.set_xlim(-0.01, mx); ax.set_ylim(-0.01, mx)
ax.legend(handles=[Line2D([], [], marker='o', color='w', markerfacecolor=MUTED, ms=8, label='ClearStint, issued'), Line2D([], [], marker='D', color='w', markerfacecolor=BG, markeredgecolor=MUTED, ms=7, label='ClearStint, low-degradation fallback'), Line2D([], [], marker='x', color=MUTED, ls='none', ms=7, label='Naive pooled fit')], loc='upper left', fontsize=8.5)
cal = val['calibration']; ax.set_title(f"{val['n_weekends']} weekends, {val['n_compound_weekends']} compound-weekends, leave-one-weekend-out\nClearStint r = {cal['all_with_fallback']['r']:.2f}, slope {cal['all_with_fallback']['slope']:.2f}   ·   naive r = {cal['naive']['r']:.2f}", fontsize=9.5, loc='left')
fig.tight_layout(); fig.savefig('out/fig_calibration.png', bbox_inches='tight')

# 2. the fifth confounder: within-run energy trend, withheld vs issued
fig, ax = plt.subplots(figsize=(5.6, 3.6), dpi=DPI)
for j, (lab, m) in enumerate([('Issued\n(Friday showed degradation)', V.issued), ('Withheld\n(no signal on Friday)', ~V.issued)]):
    s = V[m]; ax.scatter(j + np.random.default_rng(1).uniform(-0.14, 0.14, len(s)), s.energy_trend, color=[PAL[c] for c in s.compound], s=46, edgecolors=BG, lw=0.8, zorder=3)
    ax.hlines(s.energy_trend.median(), j - 0.3, j + 0.3, color=INK, lw=2.2, zorder=2); ax.text(j + 0.33, s.energy_trend.median(), f"median {s.energy_trend.median():+.2f}", va='center', fontsize=9, color=INK)
ax.axhline(0, color=MUTED, lw=0.8, ls='--'); ax.set_xticks([0, 1]); ax.set_xticklabels(['Issued\n(Friday showed degradation)', 'Withheld\n(no signal on Friday)'], fontsize=9)
ax.set_ylabel('Energy through the tyre, MJ per lap of age\n(within-run trend, Friday long runs)', fontsize=9); ax.set_title('Withheld compounds are the ones where drivers were still ramping up', fontsize=10, loc='left')
fig.tight_layout(); fig.savefig('out/fig_push.png', bbox_inches='tight')

# 3. withheld cases: what the race did
w = V[~V.issued].sort_values('obs'); fig, ax = plt.subplots(figsize=(5.6, 3.4), dpi=DPI)
ax.barh(range(len(w)), w.obs, color=[PAL[c] for c in w.compound], height=0.6, edgecolor=BG)
ax.set_yticks(range(len(w))); ax.set_yticklabels([f"{e} · {c.title()}" for e, c in zip(w.event, w.compound)], fontsize=8); ax.invert_yaxis()
ax.axvline(w.obs.median(), color=INK, lw=1.5, ls='--'); ax.text(w.obs.median() + 0.003, len(w) - 0.6, f"median {w.obs.median():.3f}", fontsize=8.5, color=INK)
ax.set_xlabel('Race degradation, s/lap per lap of age'); ax.set_title(f"All {len(w)} withheld cases were low-degradation races", fontsize=10, loc='left')
fig.tight_layout(); fig.savefig('out/fig_withheld.png', bbox_inches='tight')

# 4. Madrid live curves (cleaned Friday laps, predictions, bands)
if 'Madrid' in L['live']:
    d = M.load_event('Madrid'); p, evo = M.prep_practice(d); _, _, _, pf = M.fit(p, 'TyreLife'); rows = L['live']['Madrid']['compounds']
    fig, ax = plt.subplots(figsize=(6.2, 4.0), dpi=DPI); xs = np.linspace(0, float(pf.TyreLife.max()) + 1, 30)
    for row in rows:
        c = row['compound']; s = pf[pf.Compound == c]; ax.scatter(s.TyreLife, s.y_rel, s=10, alpha=0.3, color=PAL[c], edgecolors='none')
        ax.plot(xs, row['naive'] * xs, color=PAL[c], lw=1, ls=':'); ax.plot(xs, row['clean'] * xs, color=PAL[c], lw=1.2, ls='--'); ax.fill_between(xs, row['band90'][0] * xs, row['band90'][1] * xs, color=PAL[c], alpha=0.12, lw=0)
        ax.plot(xs, row['prediction'] * xs, color=PAL[c], lw=2.6, label=f"{c.title()} {row['prediction']:+.3f} s/lap" + ('' if row['issued'] else ' (withheld: low-deg fallback)'))
    ax.set_xlabel('Tyre age (laps)'); ax.set_ylabel('Pace loss vs fresh tyre (s)'); ax.set_ylim(-3, 4); ax.legend(fontsize=8.5, loc='upper left')
    ax.set_title(f"Madrid, {len(pf)} cleaned Friday laps · dotted naive · dashed cleaned slope · band 90%", fontsize=9.5, loc='left')
    fig.tight_layout(); fig.savefig('out/fig_madrid.png', bbox_inches='tight')

# 5. liquid model shape plot for one weekend + season summary
if LQ:
    ev = 'Austria' if 'Austria' in LQ else next(iter(LQ)); o = LQ[ev]; fig, ax = plt.subplots(figsize=(5.6, 3.6), dpi=DPI)
    for c, cv in o['curves'].items():
        ax.plot(cv['ages'], cv['liquid'], color=PAL[c], lw=2.4, label=f'{c.title()} liquid'); 
        if cv.get('quadratic'): ax.plot(cv['ages'], cv['quadratic'], color=PAL[c], lw=1.2, ls='--')
        if cv.get('cliff_lap'): ax.axvline(cv['cliff_lap'], color=PAL[c], lw=0.8, ls=':')
    ax.set_xlabel('Tyre age (laps)'); ax.set_ylabel('Pace loss vs lap 1 of the stint (s)'); ax.legend(fontsize=8.5); ax.set_title(f'{ev} race: curve shape learned lap by lap (solid) vs quadratic fit (dashed)', fontsize=9.5, loc='left')
    fig.tight_layout(); fig.savefig('out/fig_liquid.png', bbox_inches='tight')

# 6. strategy replay bars
S = L['strategy']; evs = [e for e in ['Hungary', 'Austria', 'Barcelona', 'Belgium', 'Monza', 'Zandvoort', 'Miami', 'Canada', 'Britain'] if e in S and 'cost_under_truth_vs_best_s' in S[e]['views'].get('ClearStint', {})]
fig, ax = plt.subplots(figsize=(6.0, 3.4), dpi=DPI); x = np.arange(len(evs))
for k, (name, col, off) in enumerate([('Naive fit', '#6B7280', -0.2), ('ClearStint', RED, 0.2)]):
    ax.bar(x + off, [S[e]['views'][name]['cost_under_truth_vs_best_s'] for e in evs], width=0.38, color=col, label=name)
ax.set_xticks(x); ax.set_xticklabels(evs, fontsize=8.5); ax.set_ylabel('Race time lost vs the best plan (s)'); ax.legend(fontsize=9)
ax.set_title('Following each Friday view instead of the plan the race actually rewarded', fontsize=10, loc='left')
fig.tight_layout(); fig.savefig('out/fig_strategy.png', bbox_inches='tight')
print('figures written:', sorted(f for f in os.listdir('out') if f.startswith('fig_')))
