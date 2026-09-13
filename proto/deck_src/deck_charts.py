"""Chart images for the deck, drawn from the same files the deck quotes (rendered, not native, so every viewer shows
them identically and they can be checked on this machine, which has no PowerPoint chart renderer).

    ../.venv/bin/python deck_src/deck_charts.py

Reads out/validation/ghost_scorecard.json and deck_src/assets/season_effects.json; writes deck_src/assets/chart_*.png.
Colours and type follow ui/tokens.py.
"""
from __future__ import annotations
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
PROTO = HERE.parent
ASSETS = HERE / 'assets'
BG, PANEL, GRID, TEXT, MUTED, DIM = '#090C11', '#0E131A', '#1E2530', '#F3F6FA', '#98A3B3', '#6B7585'
TEAL, MINT, GREY = '#39D0C3', '#8FE9DC', '#55606E'
COMP = {'SOFT': '#E10600', 'MEDIUM': '#F2C230', 'HARD': '#D9DEE5'}
plt.rcParams.update({'font.family': 'Arial', 'font.size': 12, 'text.color': TEXT, 'axes.labelcolor': MUTED, 'xtick.color': MUTED, 'ytick.color': MUTED,
                     'axes.edgecolor': GRID, 'figure.facecolor': BG, 'axes.facecolor': PANEL, 'savefig.facecolor': BG})


def frame(ax, ylabel=None):
    ax.grid(axis='y', color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ('top', 'right', 'left'):
        ax.spines[side].set_visible(False)
    ax.spines['bottom'].set_color(GRID)
    ax.tick_params(axis='both', length=0)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=11)


def label_bars(ax, bars, fmt, color=TEXT, size=10, pad=0.004, signed=False):
    lo, hi = ax.get_ylim()
    for b in bars:
        v = b.get_height()
        y = v + pad * (hi - lo) * 3 if v >= 0 else v - pad * (hi - lo) * 3
        txt = (('+' if v > 0 else ('−' if v < 0 else '')) + fmt.format(abs(v))) if signed else fmt.format(v)
        ax.text(b.get_x() + b.get_width() / 2, y, txt, ha='center', va='bottom' if v >= 0 else 'top', fontsize=size, color=color)


def legend(ax, **kw):
    return ax.legend(**dict(dict(frameon=False, fontsize=11, labelcolor=MUTED), **kw))


def four_tests():
    g = json.loads((PROTO / 'out' / 'validation' / 'ghost_scorecard.json').read_text())
    s26 = g['development_pool']['by_season']['2026']['forecast']
    roll = g['rolling_origin_2026']['pooled']
    dev = g['development_pool']['forecast']
    seal = g['sealed_holdout']['aggregate']['forecast']
    cats = [f"2026\nleave one weekend out\n({s26['n_compound_weekends']} cases)", f"2026\nrolling origin\n({roll['n_compound_weekends']} cases)",
            f"2023 to 2026\nleave one weekend out\n({dev['n_compound_weekends']} cases)", f"Sealed holdout\naggregate only\n({seal['n_compound_weekends']} cases)"]
    orb = [s26['mae']['orb_v1'], roll['mae']['orb_v1'], dev['mae']['orb_v1'], seal['mae']['orb_v1']]
    naive = [s26['mae']['naive'], roll['mae']['naive'], dev['mae']['naive'], seal['mae']['naive']]
    fig, ax = plt.subplots(figsize=(7.4, 4.95), dpi=220)
    x = range(len(cats)); w = 0.36
    b1 = ax.bar([i - w / 2 for i in x], orb, w, color=TEAL, label='Orb v1')
    b2 = ax.bar([i + w / 2 for i in x], naive, w, color=GREY, label='Naive straight line')
    ax.set_xticks(list(x)); ax.set_xticklabels(cats, fontsize=10.5, color=MUTED)
    ax.set_ylim(0, max(naive) * 1.18)
    frame(ax, 'mean absolute error, s/lap per lap of tyre age')
    label_bars(ax, b1, '{:.3f}', color=MINT, size=11); label_bars(ax, b2, '{:.3f}', color=MUTED, size=11)
    legend(ax, loc='upper left', ncol=2)
    fig.tight_layout()
    fig.savefig(ASSETS / 'chart_tests.png')
    plt.close(fig)


def seasons():
    se = json.loads((ASSETS / 'season_effects.json').read_text())
    years = sorted(se['degradation'])
    pre = int(se['fuel']['pre_2026_fuel_kg']); now = int(se['fuel']['model_fuel_kg'])
    for key, field, name, fmt, ylabel, fname in (('degradation', 'median_fuel_corrected', f'Race degradation, fuel-corrected ({pre} kg to 2025, {now} kg 2026)', '{:.3f}', 's/lap per lap of tyre age', 'chart_deg_season.png'),
                                                 ('stint_length', 'median', 'Median completed stint, laps', '{:.0f}', 'laps', 'chart_stint_season.png')):
        fig, ax = plt.subplots(figsize=(6.0, 3.45), dpi=220)
        w = 0.26
        top = 0
        for k, comp in enumerate(('SOFT', 'MEDIUM', 'HARD')):
            vals = [se[key][y][comp][field] or 0 for y in years]
            top = max(top, max(vals))
            bars = ax.bar([i + (k - 1) * w for i in range(len(years))], vals, w, color=COMP[comp], label=comp.title())
            ax.set_ylim(0, top * 1.25)
            label_bars(ax, bars, fmt, color=MUTED, size=8.5)
        ax.set_ylim(0, top * 1.25)
        ax.set_xticks(range(len(years))); ax.set_xticklabels(years, fontsize=11, color=TEXT)
        frame(ax, ylabel)
        ax.set_title(name, fontsize=11.5 if len(name) > 40 else 12.5, color=TEXT, loc='left', pad=8)
        legend(ax, loc='upper left', ncol=3, fontsize=10)
        fig.tight_layout()
        fig.savefig(ASSETS / fname)
        plt.close(fig)


def fuel_pairs():
    se = json.loads((ASSETS / 'season_effects.json').read_text())
    p = se['paired_same_circuit']['2025_to_2026']
    comps = ('SOFT', 'MEDIUM', 'HARD')
    cats = [f"{c.title()}\n({p[c]['n']} circuits)" for c in comps]
    series = [('Raw change', [p[c]['median_change'] for c in comps], GREY),
              ('Fuel-corrected, 2025 start at 100 kg', [p[c]['median_change_fuel_adjusted']['100'] for c in comps], TEAL),
              ('Fuel-corrected, 2025 start at 110 kg', [p[c]['median_change_fuel_adjusted']['110'] for c in comps], MINT)]
    fig, ax = plt.subplots(figsize=(5.2, 4.95), dpi=220)
    w = 0.26
    allv = [v for _, vals, _ in series for v in vals]
    ax.set_ylim(min(0, min(allv)) * 1.3 - 0.002, max(allv) * 1.3)
    for k, (name, vals, col) in enumerate(series):
        bars = ax.bar([i + (k - 1) * w for i in range(len(comps))], vals, w, color=col, label=name)
        label_bars(ax, bars, '{:.3f}', color=MUTED, size=8.5, signed=True)
    ax.axhline(0, color=DIM, linewidth=0.8)
    ax.set_xticks(range(len(comps))); ax.set_xticklabels(cats, fontsize=10.5, color=TEXT)
    frame(ax, 'change in race degradation, s/lap per lap')
    ax.set_title('Same circuits, 2025 to 2026', fontsize=12.5, color=TEXT, loc='left', pad=8)
    legend(ax, loc='upper right', fontsize=9.5)
    fig.tight_layout()
    fig.savefig(ASSETS / 'chart_fuel_pairs.png')
    plt.close(fig)


if __name__ == '__main__':
    four_tests(); seasons(); fuel_pairs()
    print('written', sorted(p.name for p in ASSETS.glob('chart_*.png')))
