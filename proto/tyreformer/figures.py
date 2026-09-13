"""Deck figures for Orb TyreFormer (dark slide surface, validated categorical slots: estimator orange, TyreFormer aqua,
trees blue; identity is never colour-only: every line and bar is direct-labelled).

    fig_tyreformer_horizon.png   error against forecast horizon, Orb v1 estimator vs TyreFormer, with 90 % weekend bootstrap bands
    fig_tyreformer_fan.png       one stint, one forecast: observed laps, TyreFormer 50 % / 90 % fan, the estimator's line
    fig_tyreformer_ladder.png    the ablation ladder on identical race origins (next-lap and 5-lap cumulative error)

CLI:  python -m tyreformer.figures [--experiment rolling]
"""
from __future__ import annotations

import argparse
import json

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd

from tyreformer import OUT
from tyreformer.data import SampleSet, CACHE
from tyreformer.headtohead import load_kalman, origin_table, attach_tyreformer
from tyreformer.train import PRED

BG, SURF, INK, INK2, GRID = '#090C11', '#11161E', '#F3F6FA', '#98A3B3', '#272F3B'
C_EST, C_TF, C_TREE = '#d95926', '#199e70', '#3987e5'


def _style(ax):
    ax.set_facecolor(SURF)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    for s in ('left', 'bottom'):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=10)
    ax.yaxis.label.set_color(INK2)
    ax.xaxis.label.set_color(INK2)
    ax.grid(axis='y', color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def merged(experiment: str) -> pd.DataFrame:
    ens = json.loads((OUT / 'ensemble.json').read_text(encoding='utf-8'))
    P = pd.read_parquet(PRED / f'{experiment}_ensemble.parquet')
    rids = sorted(P.loc[P['session'] == 'R', 'race_id'].unique())
    return attach_tyreformer(origin_table(load_kalman(rids)), P, ens['conformal_margins'])


def boot_ci(d: pd.DataFrame, col: str, n: int = 1000, seed: int = 3) -> tuple[float, float]:
    groups = [g[col].to_numpy() for _, g in d.groupby('race_id')]
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        vals.append(np.concatenate([groups[i] for i in pick]).mean())
    return float(np.percentile(vals, 5)), float(np.percentile(vals, 95))


def fig_horizon(M: pd.DataFrame, title: str, path) -> dict:
    hs = [1, 2, 3, 4, 5]
    res = {'estimator': [], 'tyreformer': []}
    fig, ax = plt.subplots(figsize=(8.0, 4.6), dpi=200)
    fig.patch.set_facecolor(BG)
    _style(ax)
    for key, col, color, label in (('estimator', 'kal', C_EST, 'Orb v1 live estimator'), ('tyreformer', 'h', C_TF, 'Orb TyreFormer')):
        means, lo, hi = [], [], []
        for h in hs:
            m = M[f'y{h}'].notna() & M[f'kal{h}'].notna() & M['h1_q50'].notna()
            pred = M.loc[m, f'kal{h}'] if key == 'estimator' else M.loc[m, f'h{h}_q50']
            d = pd.DataFrame(dict(race_id=M.loc[m, 'race_id'], e=(pred - M.loc[m, f'y{h}']).abs()))
            means.append(d['e'].mean())
            a, b = boot_ci(d, 'e')
            lo.append(a); hi.append(b)
        res[key] = dict(mae=means, ci90=list(zip(lo, hi)))
        ax.fill_between(hs, lo, hi, color=color, alpha=0.18, linewidth=0)
        ax.plot(hs, means, color=color, linewidth=2.2, marker='o', markersize=7, markeredgecolor=SURF, markeredgewidth=2)
        ax.annotate(f'{label}  {means[-1]:.3f} s', (hs[-1], means[-1]), xytext=(10, 0), textcoords='offset points', color=INK, fontsize=10, va='center')
    ax.set_xticks(hs)
    ax.set_xticklabels([f'+{h}' for h in hs])
    ax.set_xlim(0.7, 6.6)
    ax.set_xlabel('laps ahead')
    ax.set_ylabel('mean absolute error (s)')
    ax.set_title(title, color=INK, fontsize=12, loc='left', pad=12)
    fig.tight_layout()
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return res


def fan_data(experiment: str = 'rolling', event: str = 'Barcelona', driver: str | None = None) -> dict:
    """The representative stint of fig_fan as plain numbers (for the report page)."""
    d = _fan_select(experiment, event, driver)
    kk, kept, k0, row, est = d['kk'], d['kept'], d['k0'], d['row'], d['est']
    past = kept[(kept['lap'] <= k0) & (kept['lap'] > k0 - 12)]
    fut = kept[(kept['lap'] > k0) & (kept['lap'] <= k0 + 10)]
    return dict(event=event, season=2026, driver=d['drv'], stint=int(d['st']), compound=str(kk['compound'].iloc[0]), origin_lap=int(k0),
                past=[[int(a), float(b)] for a, b in zip(past['lap'], past['y'])], future=[[int(a), float(b)] for a, b in zip(fut['lap'], fut['y'])],
                tyreformer=[dict(lap=int(k0 + h), **{c: float(row[f'h{h}_{c}']) for c in ('q05', 'q25', 'q50', 'q75', 'q95')}) for h in range(1, 11)],
                estimator=[dict(lap=int(k0 + h), mean=float(est[f'pred_h{h}'])) for h in range(1, 6)])


def _fan_select(experiment: str, event: str, driver: str | None) -> dict:
    P = pd.read_parquet(PRED / f'{experiment}_ensemble.parquet')
    ens = json.loads((OUT / 'ensemble.json').read_text(encoding='utf-8'))
    rid = f'2026_{event}'
    K = load_kalman([rid])
    O = origin_table(K)
    M = attach_tyreformer(O, P, ens['conformal_margins'])
    # representative, not extreme: among long stints that clearly degrade (realised slope between the 60th and 90th
    # percentile of long stints), the origin whose TyreFormer 5-lap error is closest to the median of those origins
    cands = []
    for (drv, st), g in M.groupby(['driver', 'stint']):
        if driver and drv != driver:
            continue
        kk = K[(K['driver'] == drv) & (K['stint'] == st) & K['kept'].astype(bool)]
        if len(kk) < 12 or g['h1_q50'].isna().all():
            continue
        cands.append((float(np.polyfit(kk['tyre_age'], kk['y'], 1)[0]), drv, st))
    slopes = np.array([c[0] for c in cands])
    lo_s, hi_s = np.percentile(slopes, 60), np.percentile(slopes, 90)
    pool = []
    for sl, drv, st in cands:
        if not (lo_s <= sl <= hi_s):
            continue
        g = M[(M['driver'] == drv) & (M['stint'] == st)].sort_values('lap')
        g = g[g['y5'].notna() & g['h5_q50'].notna()]
        g = g.iloc[2:-2] if len(g) > 6 else g.iloc[0:0]
        for _, r in g.iterrows():
            pool.append((abs(r['h5_q50'] - r['y5']), drv, st, int(r['lap'])))
    errs = np.array([p[0] for p in pool])
    _, drv, st, k_pick = pool[int(np.argmin(np.abs(errs - np.median(errs))))]
    kk = K[(K['driver'] == drv) & (K['stint'] == st)].sort_values('lap')
    kept = kk[kk['kept'].astype(bool)]
    k0 = k_pick
    row = P[(P['race_id'] == rid) & (P['driver'] == drv) & (P['lap'] == k0) & (P['session'] == 'R')].iloc[0]
    est = kk[kk['lap'] == k0].iloc[0]
    return dict(kk=kk, kept=kept, k0=k0, row=row, est=est, drv=drv, st=st)


def fig_fan(experiment: str, path, event: str = 'Barcelona', driver: str | None = None) -> dict:
    d = _fan_select(experiment, event, driver)
    kk, kept, k0, row, est, drv, st = d['kk'], d['kept'], d['k0'], d['row'], d['est'], d['drv'], d['st']
    fig, ax = plt.subplots(figsize=(8.0, 4.6), dpi=200)
    fig.patch.set_facecolor(BG)
    _style(ax)
    past = kept[kept['lap'] <= k0]
    fut = kept[(kept['lap'] > k0) & (kept['lap'] <= k0 + 10)]
    ax.scatter(past['lap'], past['y'], s=36, color=INK2, zorder=3, label='clean laps seen')
    ax.scatter(fut['lap'], fut['y'], s=40, facecolors='none', edgecolors=INK, linewidths=1.4, zorder=4, label='what happened next')
    laps = np.arange(k0 + 1, k0 + 11)
    q = {c: np.array([row[f'h{h}_{c}'] for h in range(1, 11)]) for c in ('q05', 'q25', 'q50', 'q75', 'q95')}
    ax.fill_between(laps, q['q05'], q['q95'], color=C_TF, alpha=0.16, linewidth=0)
    ax.fill_between(laps, q['q25'], q['q75'], color=C_TF, alpha=0.32, linewidth=0)
    ax.plot(laps, q['q50'], color=C_TF, linewidth=2.2)
    ax.plot(laps[:5], [est[f'pred_h{h}'] for h in range(1, 6)], color=C_EST, linewidth=2.2, linestyle=(0, (5, 3)))
    ax.axvline(k0 + 0.5, color=GRID, linewidth=1)
    ax.annotate('Orb TyreFormer median, 50 % and 90 % band', (laps[-1], q['q50'][-1]), xytext=(-4, 16), textcoords='offset points', color=INK, fontsize=9, ha='right')
    ax.annotate('Orb v1 estimator', (laps[1], est['pred_h2']), xytext=(-8, 14), textcoords='offset points', color=INK, fontsize=9, ha='right')
    ax.annotate(f'forecast made at the end of lap {k0}', (k0 + 0.5, ax.get_ylim()[1]), xytext=(4, -14), textcoords='offset points', color=INK2, fontsize=9)
    ax.set_xlabel('race lap')
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax.set_ylabel('fuel-corrected lap time (s)')
    ax.set_title(f'{event} 2026, {drv}, {kk["compound"].iloc[0].lower()} stint: a race the model never trained on', color=INK, fontsize=12, loc='left', pad=12)
    leg = ax.legend(loc='upper left', frameon=False, fontsize=9)
    for t in leg.get_texts():
        t.set_color(INK2)
    fig.tight_layout()
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return dict(event=event, driver=drv, stint=int(st), origin_lap=k0)


def fig_ladder(M: pd.DataFrame, title: str, path) -> dict:
    m1 = M['y1'].notna() & M['kal1'].notna() & M['h1_q50'].notna() & M['gbm_h1_q50'].notna()
    d = M[m1]
    vals = [('current pace (persistence)', (d['anchor'] - d['y1']).abs().mean(), INK2),
            ('pre-race slope only', (d['prior1'] - d['y1']).abs().mean(), INK2),
            ('Orb v1 live estimator', (d['kal1'] - d['y1']).abs().mean(), C_EST),
            ('gradient-boosted trees', (d['gbm_h1_q50'] - d['y1']).abs().mean(), C_TREE),
            ('transformer', (d['tf_h1_q50'] - d['y1']).abs().mean(), C_TF),
            ('Orb TyreFormer ensemble', (d['h1_q50'] - d['y1']).abs().mean(), C_TF)]
    fig, ax = plt.subplots(figsize=(8.0, 4.2), dpi=200)
    fig.patch.set_facecolor(BG)
    _style(ax)
    ax.grid(axis='x', color=GRID, linewidth=0.6)
    ax.grid(axis='y', visible=False)
    y = np.arange(len(vals))[::-1]
    for yi, (name, v, c) in zip(y, vals):
        ax.barh(yi, v, height=0.56, color=c, alpha=(0.55 if name == 'transformer' else 1.0))
        ax.text(v + 0.004, yi, f'{v:.3f} s', va='center', color=INK, fontsize=10)
    ax.set_yticks(y)
    ax.set_yticklabels([n for n, _, _ in vals], color=INK)
    ax.set_xlabel('next-lap mean absolute error (s)')
    ax.set_xlim(0, max(v for _, v, _ in vals) * 1.18)
    ax.set_title(title, color=INK, fontsize=12, loc='left', pad=12)
    fig.tight_layout()
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    return {n: float(v) for n, v, _ in vals} | dict(n=int(m1.sum()), weekends=int(d['race_id'].nunique()))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--experiment', default='rolling')
    a = ap.parse_args(argv)
    out = {}
    M = merged(a.experiment)
    out['horizon'] = fig_horizon(M, 'Error by forecast horizon, every 2026 race (never in training)', OUT / 'fig_tyreformer_horizon.png')
    out['ladder_2026'] = fig_ladder(M, 'Next-lap error, 2026 races, identical origins', OUT / 'fig_tyreformer_ladder.png')
    Mcv = merged('cv')
    out['ladder_cv'] = fig_ladder(Mcv, 'Next-lap error, 2023-2025 cross-validation, identical origins', OUT / 'fig_tyreformer_ladder_cv.png')
    out['fan'] = fig_fan(a.experiment, OUT / 'fig_tyreformer_fan.png')
    (OUT / 'figures.json').write_text(json.dumps(out, indent=1, default=float), encoding='utf-8')
    print(json.dumps(out, indent=1, default=float))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
