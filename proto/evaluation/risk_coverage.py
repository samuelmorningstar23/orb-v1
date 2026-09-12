"""Risk-coverage curve for abstention (roadmap v5 section 3.3): sweep the two gate thresholds on the development pool.

The production gate (pipeline.py) issues a compound's forecast when the cleaned practice fit rests on at least
MIN_PRAC = 30 clean laps AND the cleaned slope is at least MIN_SLOPE = 0.02 s/lap per lap; otherwise the compound
gets the low-degradation fallback (median race degradation of the pool's withheld cases). For every pair
(min_laps in 10..60 step 5, min_slope in 0..0.05 step 0.005) this module recomputes the leave-one-weekend-out forecasts
of every development weekend (2026 plus the non-sealed 2023 to 2025 weekends; factors from the same season, sealed
races never in a pool) and reports
    coverage      share of compound-weekends issued (the rest abstain to the fallback)
    mae_issued    MAE of the issued forecasts against the race-derived reference (s/lap per lap)
    mae_fallback  MAE of the fallback on the withheld cases
    mae_all       MAE over every compound-weekend (issued forecast or fallback), plus the naive MAE for scale
    n_no_forecast compound-weekends with neither (fallback impossible: fewer than 2 withheld cases in the pool)
Point forecasts only (the band is not needed for this curve). Output: risk_coverage.csv / .json and risk_coverage.png
(dark theme of proto/theme.py) under out/validation/.

CLI:  python -m evaluation.risk_coverage [--seasons 2026,2025,2024,2023] [--out out/validation]
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from evaluation import PROTO, OUT_DIR, SEASON_DIRS, git_sha, now_iso
from evaluation.common import mae, write_json, weekend_mean_bootstrap
from evaluation.forecast import SeasonForecaster, MIN_PRAC, MIN_SLOPE

LAPS_GRID = tuple(range(10, 61, 5))
SLOPE_GRID = tuple(round(x, 3) for x in np.arange(0.0, 0.0501, 0.005))


def _loo_rows(F: SeasonForecaster) -> list[dict[str, Any]]:
    """Point forecasts (no band) of every development weekend with the pool minus itself under the current gate."""
    rows = []
    dev = F.development_events
    for ev in dev:
        pool = [e for e in dev if e != ev]
        fc = F._raw_forecast(ev, pool, compute_band=False)
        ref = F.reference(ev)
        for c, f in fc.items():
            if c not in ref:
                continue
            obs = ref[c]['obs']
            rows.append(dict(race_id=F.rid(ev), season=F.season, event=ev, compound=c, issued=f.issued, n_prac=f.n_prac, clean=f.clean, prediction=f.prediction, naive=f.naive, obs=obs,
                             err=(abs(f.prediction - obs) if f.prediction is not None else None), err_naive=(abs(f.naive - obs) if np.isfinite(f.naive) else None)))
    return rows


def sweep(forecasters: Iterable[SeasonForecaster], laps_grid: Iterable[int] = LAPS_GRID, slope_grid: Iterable[float] = SLOPE_GRID) -> pd.DataFrame:
    forecasters = list(forecasters)
    out = []
    for ml in laps_grid:
        for ms in slope_grid:
            rows = []
            for F in forecasters:
                F.set_gate(ml, ms)
                rows.extend(_loo_rows(F))
            df = pd.DataFrame(rows)
            iss, fb = df[df['issued']], df[~df['issued']]
            out.append(dict(min_laps=int(ml), min_slope=float(ms), n_cases=int(len(df)), n_weekends=int(df['race_id'].nunique()), n_issued=int(len(iss)), coverage=(len(iss) / len(df)) if len(df) else None,
                            mae_issued=mae(iss['err']), mae_fallback=mae(fb['err']), mae_all=mae(df['err']), mae_naive=mae(df['err_naive']), mae_naive_issued=mae(iss['err_naive']),
                            n_no_forecast=int(df['prediction'].isna().sum()),
                            bootstrap={k: weekend_mean_bootstrap(d, col, n_unit='compound-weekends') for k, d, col in [
                                ('coverage', df, 'issued'), ('mae_issued', iss, 'err'), ('mae_fallback', fb, 'err'),
                                ('mae_all', df, 'err'), ('mae_naive', df, 'err_naive'), ('mae_naive_issued', iss, 'err_naive')]}))
    for F in forecasters:
        F.set_gate(MIN_PRAC, MIN_SLOPE)
    return pd.DataFrame(out)


def figure(table: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import theme                      # noqa: F401  (sets the dark editorial rcParams)
    import matplotlib.pyplot as plt
    from theme import INK, MUTED, RED, GOLD, SLATE, LINE
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2))
    slopes = sorted(table['min_slope'].unique())
    cmap = plt.get_cmap('viridis')
    for i, ms in enumerate(slopes):
        t = table[table['min_slope'] == ms].sort_values('min_laps')
        ax1.plot(t['coverage'], t['mae_issued'], '-o', ms=3.5, lw=1.2, color=cmap(i / max(1, len(slopes) - 1)), label=f'min slope {ms:.3f}')
        lo = [b['mae_issued']['ci90'][0] if b['mae_issued']['ci90'] else np.nan for b in t['bootstrap']]
        hi = [b['mae_issued']['ci90'][1] if b['mae_issued']['ci90'] else np.nan for b in t['bootstrap']]
        ax1.fill_between(t['coverage'], lo, hi, color=cmap(i / max(1, len(slopes) - 1)), alpha=.06)

    prod = table[(table['min_laps'] == MIN_PRAC) & (np.isclose(table['min_slope'], MIN_SLOPE))]
    if len(prod):
        ax1.scatter(prod['coverage'], prod['mae_issued'], s=140, facecolors='none', edgecolors=RED, lw=2, zorder=5, label=f'production gate ({MIN_PRAC} laps, {MIN_SLOPE})')
    ax1.set_xlabel('coverage: share of compound-weekends issued'); ax1.set_ylabel('MAE on issued cases (s/lap per lap)')
    ax1.set_title('Risk-coverage curve: each line sweeps the minimum-laps gate 10 to 60', color=INK, fontsize=11)
    ax1.legend(fontsize=7, ncol=2, loc='upper left')
    piv = table.pivot(index='min_slope', columns='min_laps', values='mae_all')
    im = ax2.imshow(piv.values, origin='lower', aspect='auto', cmap='magma_r', extent=[piv.columns.min() - 2.5, piv.columns.max() + 2.5, piv.index.min() - 0.0025, piv.index.max() + 0.0025])
    ax2.set_xlabel('minimum clean practice laps'); ax2.set_ylabel('minimum cleaned slope (s/lap per lap)')
    ax2.set_title('MAE over all compound-weekends (issued forecast or fallback)', color=INK, fontsize=11)
    ax2.scatter([MIN_PRAC], [MIN_SLOPE], s=140, facecolors='none', edgecolors=RED, lw=2)
    ax2.grid(False)
    cb = fig.colorbar(im, ax=ax2); cb.set_label('MAE (s/lap per lap)', color=MUTED); cb.ax.yaxis.set_tick_params(color=MUTED); plt.setp(cb.ax.get_yticklabels(), color=MUTED)
    fig.suptitle(f"Orb v1 diagnostic gate sweep: n={int(table['n_cases'].iloc[0])} compound-weekends / {int(table['n_weekends'].iloc[0])} weekends; shaded 90% weekend bootstrap MAE bands", color=MUTED, fontsize=10, y=0.995)
    fig.text(.5, .005, 'Eligible n and 90% coverage/error bands for every point: risk_coverage.csv. Heatmap is point estimates; production gate unchanged.', ha='center', fontsize=8, color=MUTED)
    fig.tight_layout(rect=[0,.035,1,.97])
    fig.savefig(path, dpi=150)
    plt.close(fig)


def run(seasons: Iterable[int] = (2026, 2025, 2024, 2023), out_dir: Path = OUT_DIR, quiet: bool = False) -> dict[str, Any]:
    from evaluation.holdout.evaluator import sealed_race_ids
    sealed = sealed_race_ids()
    forecasters = [SeasonForecaster(SEASON_DIRS[s], s, sealed=[r for r in sealed if r.startswith(f'{s}_')]) for s in seasons]
    table = sweep(forecasters)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv = table.drop(columns=['bootstrap']).copy()
    for metric in ('coverage', 'mae_issued', 'mae_fallback', 'mae_all', 'mae_naive', 'mae_naive_issued'):
        for field in ('n', 'n_weekends'):
            csv[f'{metric}_{field}'] = table['bootstrap'].map(lambda b, m=metric, f=field: b[m][f])
        for i, field in enumerate(('ci90_low', 'ci90_high')):
            csv[f'{metric}_{field}'] = table['bootstrap'].map(lambda b, m=metric, j=i: (b[m]['ci90'] or [None, None])[j])
    csv.to_csv(out_dir / 'risk_coverage.csv', index=False, float_format='%.10g')
    figure(table, out_dir / 'risk_coverage.png')
    prod = table[(table['min_laps'] == MIN_PRAC) & (np.isclose(table['min_slope'], MIN_SLOPE))].iloc[0].to_dict() if len(table) else {}
    best_all = table.sort_values('mae_all').iloc[0].to_dict() if len(table) else {}
    summary = dict(generated_at=now_iso(), git_sha=git_sha(), seasons=list(seasons), sealed_excluded=sealed, grid=dict(min_laps=list(LAPS_GRID), min_slope=list(SLOPE_GRID)),
                   n_cases=int(table['n_cases'].iloc[0]) if len(table) else 0, n_weekends=int(table['n_weekends'].iloc[0]) if len(table) else 0,
                   production_gate=prod, best_mae_all=best_all, units='MAE in s/lap per lap of tyre age; coverage = share of compound-weekends issued',
                   definitions=__doc__, table=table.to_dict(orient='records'))
    write_json(out_dir / 'risk_coverage.json', summary)
    if not quiet:
        print(render(table))
        print(f"production gate ({MIN_PRAC} laps, {MIN_SLOPE}): coverage {prod.get('coverage', float('nan')):.2f}, MAE issued {prod.get('mae_issued', float('nan')):.4f}, fallback {prod.get('mae_fallback', float('nan')):.4f}, all {prod.get('mae_all', float('nan')):.4f}")
        print(f"lowest MAE over all cases: min_laps {best_all.get('min_laps')}, min_slope {best_all.get('min_slope')}: {best_all.get('mae_all', float('nan')):.4f} at coverage {best_all.get('coverage', float('nan')):.2f}")
    return summary


def render(table: pd.DataFrame) -> str:
    L = ['| min laps | min slope | coverage | MAE issued | MAE fallback | MAE all | naive all | no forecast |', '|---|---|---|---|---|---|---|---|']
    f = lambda v: '—' if v is None or v != v else f'{v:.4f}'
    for _, r in table[table['min_slope'].isin([0.0, 0.01, 0.02, 0.03, 0.05]) & table['min_laps'].isin([10, 20, 30, 40, 60])].iterrows():
        L.append(f"| {int(r['min_laps'])} | {r['min_slope']:.3f} | {r['coverage']:.2f} | {f(r['mae_issued'])} | {f(r['mae_fallback'])} | {f(r['mae_all'])} | {f(r['mae_naive'])} | {int(r['n_no_forecast'])} |")
    return '\n'.join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seasons', default='2026,2025,2024,2023')
    ap.add_argument('--out', type=Path, default=OUT_DIR)
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    run([int(s) for s in a.seasons.split(',') if s], a.out, a.quiet)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
