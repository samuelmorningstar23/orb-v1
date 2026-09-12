"""Hidden-stop-response evaluation (roadmap v5 section 9, 'Hidden-stop-response').

For every actual tyre change in a race (stint boundaries with pit in-lap L and out-lap L+1, both compounds dry slicks,
not under a red flag), the evaluator sees only the laps BEFORE the stop plus the actual intervention (stop lap, new
compound, set status from FreshTyre and the set's age at fitting), predicts the next 1, 3 and 5 representative
green-flag laps on the new tyre with the PRE-RACE model, and compares with what happened.

Representative laps: after the out-lap, within WINDOW_POST = 8 laps and inside the new stint, laps that are green
(TrackStatus 1), accurate, not pit in/out, not deleted, traffic share <= 0.30 (unknown traffic is not clean) and within
105 % of the fastest such lap in the window. The h-th representative lap need not be consecutive with the previous one;
each is predicted at its own tyre age. A case is scored at horizon h only when h representative laps exist.

Pre-stop baseline: the last K = 5 (at least 3) clean laps of the old stint before the in-lap, same cleaning rule
(105 % against the best of those laps); y is the fuel-corrected lap time y = lap_s - 0.03 x fuel_kg, fuel_kg = 70 x
(1 - (lap - 1) / n_laps) (model_v2.prep_race), so fuel is handled on both sides of the stop.

Orb v1 prediction (pre-race curve for the new compound + the driver's own pre-stop baseline):
    B_hat      = mean over the K baseline laps of  y_i - offset[c_old] - s_pre[c_old] x age_i
    y_hat(a)   = B_hat + offset[c_new] + s_pre[c_new] x a           for a representative lap at tyre age a
    s_pre[c]   = the weekend's pre-race Orb v1 slope for compound c (issued x factor, or the low-degradation fallback),
                 factors from the other weekends of the season (never a sealed race); offsets = the weekend's compound
                 pace offsets from qualifying / practice (strategy2.offsets_from_sessions), SOFT = 0
    90 % interval:  y_hat(a) +- 1.6449 x sqrt(sigma_y^2 + V_level + (a x sigma_s,new)^2)
                    V_level = sigma_y^2 / K + (a_bar_pre x sigma_s,old)^2 + n_off x OFFSET_SD^2
                    sigma_y = 0.40 s (live/estimator.py SIGMA_Y, clean-lap noise); sigma_s,c = (band_hi - band_lo) / (2 x 1.6449)
                    of compound c's pre-race 90 % band (0 when no band); a_bar_pre = mean tyre age of the baseline laps (the
                    old compound's slope error enters the level through B_hat); OFFSET_SD = 0.15 s per non-SOFT compound
                    offset (stated assumption, as counterfactual/engine.py), n_off = number of non-SOFT compounds among
                    {c_old, c_new} when they differ, 0 for a same-compound stop
    h-lap cumulative interval: sum(y_hat) +- 1.6449 x sqrt(h sigma_y^2 + h^2 V_level + (sum a)^2 sigma_s,new^2)
                    (lap noise independent; level, offset and slope errors perfectly correlated across the laps)
Naive baseline (fresh-tyre assumption): the new tyre runs at the pre-stop pace adjusted by the compound offset, with no
degradation and no age reset:
    P_hat            = mean over the K baseline laps of y_i
    y_naive(a)       = P_hat + offset[c_new] - offset[c_old]        (no interval: the baseline has no uncertainty model)
Metrics: next-lap MAE |y_hat_1 - y_1|; 3- and 5-lap cumulative MAE |sum_{j<=h} (y_hat_j - y_j)|; 90 % interval coverage
of the next lap and of the 3- and 5-lap sums; by new compound, circuit class (street / permanent), set status
(new / used from FreshTyre), stop regime (green: in-lap and out-lap green or yellow; sc_vsc otherwise), driver support
(driver seen in a pool weekend's race). Intervals are weekend-grouped bootstraps (evaluation.common).
The state-space (live estimator) baseline of the roadmap is the live-prefix evaluation (live/prefix_eval.py, Workstream 8);
it is referenced, not re-run here.

CLI:  python -m evaluation.hidden_stop [--seasons 2026,2025,2024,2023] [--out out/validation]
      writes hidden_stop_<season>.json (per-case rows and aggregates, development pool only) and prints the tables.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from evaluation import PROTO, OUT_DIR, SEASON_DIRS, COMPS, circuit_class, weather_regime, git_sha, now_iso
from evaluation.common import mae, share, weekend_bootstrap, weekend_mean_bootstrap, paired_probability, write_json
from evaluation.forecast import SeasonForecaster, WeekendForecast

from counterfactual.racedata import RaceData, load_race     # noqa: E402  (post-race file access; scoring only)

SIGMA_Y = 0.40          # s, clean-lap noise (live/estimator.py SIGMA_Y)
OFFSET_SD = 0.15        # s, sd of a compound pace offset (stated assumption, counterfactual/engine.py OFFSET_SD)
Z90 = 1.6448536269514722
K_BASELINE = 5
MIN_PRE = 3
WINDOW_POST = 8
HORIZONS = (1, 3, 5)
TRAFFIC_MAX = 0.30
BEST_RATIO = 1.05
GREENISH = ('GREEN', 'YELLOW')
CELLS = ('compound_new', 'circuit_class', 'set_status', 'stop_regime', 'driver_support')


def _kept_indices(dl, lo_lap: int, hi_lap: int, compound: str) -> list[int]:
    """0-based indices of clean laps in [lo_lap, hi_lap] (1-based, inclusive) on `compound`, 105 % rule inside the set."""
    idx = [i for i in range(max(lo_lap, 1) - 1, min(hi_lap, dl.n)) if dl.ok[i] and dl.compound[i] == compound and np.isfinite(dl.traffic[i]) and dl.traffic[i] <= TRAFFIC_MAX and np.isfinite(dl.y[i]) and np.isfinite(dl.age[i])]
    if not idx:
        return idx
    best = min(dl.lap_s[i] for i in idx)
    return [i for i in idx if dl.lap_s[i] <= BEST_RATIO * best]


def stop_cases(race: RaceData, fc: WeekendForecast, race_id: str, drivers_seen: Optional[set[str]] = None, k_baseline: int = K_BASELINE,
               window_post: int = WINDOW_POST, sigma_y: float = SIGMA_Y) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """All scorable stops of one race under the pre-race forecast `fc`. Returns (cases, skipped-by-reason)."""
    cases: list[dict[str, Any]] = []
    skipped: dict[str, int] = {}

    def skip(why: str) -> None:
        skipped[why] = skipped.get(why, 0) + 1

    slopes = fc.slopes()
    offsets = dict(fc.offsets)
    cclass = circuit_class(fc.event)
    for drv in race.drivers:
        dl = race.driver(drv)
        for si, s in enumerate(dl.stops):
            a, b = dl.stints[si], dl.stints[si + 1]
            c_old, c_new = s.from_compound, s.to_compound
            if c_old not in COMPS or c_new not in COMPS:
                skip('non-slick compound'); continue
            if s.free:
                skip('stop under red flag (free)'); continue
            if c_old not in slopes or c_new not in slopes:
                skip('no pre-race forecast for a compound'); continue
            if c_old not in offsets or c_new not in offsets:
                skip('no compound offset'); continue
            L = s.in_lap
            pre = _kept_indices(dl, a.start_lap, L - 1, c_old)[-k_baseline:]
            if len(pre) < MIN_PRE:
                skip('fewer than 3 clean pre-stop laps'); continue
            post_all = _kept_indices(dl, L + 2, min(L + 1 + window_post, b.end_lap), c_new)
            if not post_all:
                skip('no representative lap within 8 laps after the stop'); continue
            y_pre = np.array([dl.y[i] for i in pre]); a_pre = np.array([dl.age[i] for i in pre])
            B_hat = float(np.mean(y_pre - offsets[c_old] - slopes[c_old] * a_pre))
            P_hat = float(np.mean(y_pre))
            K = len(pre)
            sd_s = fc.compounds[c_new].slope_sd or 0.0
            sd_s_old = fc.compounds[c_old].slope_sd or 0.0
            n_off = (sum(1 for c in (c_old, c_new) if c != 'SOFT') if c_new != c_old else 0)
            v_level = sigma_y ** 2 / K + (float(np.mean(a_pre)) * sd_s_old) ** 2 + n_off * OFFSET_SD ** 2
            ages = np.array([dl.age[i] for i in post_all]); ys = np.array([dl.y[i] for i in post_all]); laps = [int(dl.lap[i]) for i in post_all]
            pred = B_hat + offsets[c_new] + slopes[c_new] * ages
            pred_naive = np.full_like(pred, P_hat + offsets[c_new] - offsets[c_old])
            regime = 'green' if (s.label_in in GREENISH and s.label_out in GREENISH) else 'sc_vsc'
            case = dict(race_id=race_id, season=fc.season, event=fc.event, driver=drv, stop_index=si + 1, in_lap=int(L), out_lap=int(s.out_lap), compound_old=c_old, compound_new=c_new,
                        set_status=('new' if b.fresh else ('used' if b.fresh is not None else 'unknown')), start_age=int(b.start_age), stop_regime=regime, label_in=s.label_in, label_out=s.label_out,
                        circuit_class=cclass, driver_support=('seen' if (drivers_seen is None or drv in drivers_seen) else 'unseen'),
                        n_pre=K, B_hat=B_hat, P_hat=P_hat, slope_old=float(slopes[c_old]), slope_new=float(slopes[c_new]), slope_new_sd=float(sd_s), slope_old_sd=float(sd_s_old), sd_level=math.sqrt(v_level), issued_new=bool(fc.compounds[c_new].issued),
                        laps_post=laps, ages_post=[float(v) for v in ages], y_post=[float(v) for v in ys], pred_orb=[float(v) for v in pred], pred_naive=[float(v) for v in pred_naive], n_post=len(post_all))
            for h in HORIZONS:
                if len(post_all) < h:
                    case[f'err{h}'] = None; case[f'err{h}_naive'] = None; case[f'cov{h}'] = None
                    continue
                e = float(np.sum(pred[:h] - ys[:h])); en = float(np.sum(pred_naive[:h] - ys[:h]))
                sd = math.sqrt(h * sigma_y ** 2 + (h ** 2) * v_level + (float(np.sum(ages[:h])) * sd_s) ** 2)
                case[f'err{h}'] = abs(e); case[f'err{h}_naive'] = abs(en); case[f'cov{h}'] = bool(abs(e) <= Z90 * sd); case[f'sd{h}'] = sd
            cases.append(case)
    return cases, skipped


def _metrics(df: pd.DataFrame) -> dict[str, Any]:
    m: dict[str, Any] = dict(n_cases=int(len(df)), n_weekends=int(df['race_id'].nunique()) if len(df) else 0)
    for h in HORIZONS:
        key = 'next1' if h == 1 else f'cum{h}'
        col = f'err{h}'
        m[f'{key}_mae'] = mae(df[col]) if len(df) else None
        m[f'{key}_mae_naive'] = mae(df[f'{col}_naive']) if len(df) else None
        m[f'{key}_n'] = int(df[col].notna().sum()) if len(df) else 0
        m[f'{key}_coverage90'] = share(df[f'cov{h}']) if len(df) else None
    return m


def aggregate(cases: list[dict[str, Any]], bootstrap: bool = True, min_weekends_per_cell: int = 1) -> dict[str, Any]:
    """Pooled metrics, weekend-grouped bootstrap intervals, and breakdowns by CELLS (cells below min_weekends_per_cell suppressed)."""
    df = pd.DataFrame(cases)
    if df.empty:
        return dict(pooled=_metrics(df), by={}, n_cases=0)
    out: dict[str, Any] = dict(pooled=_metrics(df))
    if bootstrap:
        ci = {}
        for h in HORIZONS:
            key = 'next1' if h == 1 else f'cum{h}'
            ci[f'{key}_mae'] = weekend_mean_bootstrap(df, f'err{h}', n_unit='stops')
            ci[f'{key}_mae_naive'] = weekend_mean_bootstrap(df, f'err{h}_naive', n_unit='stops')
            ci[f'{key}_coverage90'] = weekend_mean_bootstrap(df, f'cov{h}', n_unit='stops')
            ci[f'p_orb_beats_naive_{key}'] = paired_probability(df, f'err{h}', f'err{h}_naive')
        out['bootstrap'] = ci
    by: dict[str, dict[str, Any]] = {}
    for cell in CELLS:
        by[cell] = {}
        for val, d in df.groupby(cell):
            if d['race_id'].nunique() < min_weekends_per_cell:
                by[cell][str(val)] = dict(suppressed=f'fewer than {min_weekends_per_cell} weekends in the cell', n_cases=int(len(d)))
            else:
                by[cell][str(val)] = _metrics(d)
                if bootstrap:
                    by[cell][str(val)]['bootstrap'] = {}
                    for h in HORIZONS:
                        key = 'next1' if h == 1 else f'cum{h}'
                        for metric, col in [(f'{key}_mae', f'err{h}'), (f'{key}_mae_naive', f'err{h}_naive'), (f'{key}_coverage90', f'cov{h}')]:
                            by[cell][str(val)]['bootstrap'][metric] = weekend_mean_bootstrap(d, col, n_unit='stops')

    out['by'] = by
    return out


def evaluate_weekend(F: SeasonForecaster, fc: WeekendForecast, drivers_seen: Optional[set[str]] = None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    race = load_race(fc.event, str(F.race_path(fc.event)))
    return stop_cases(race, fc, fc.race_id, drivers_seen)


def drivers_seen_in(F: SeasonForecaster, pool_events: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for ev in pool_events:
        out.update(F.metas[ev].get('drivers_race', []))
    return out


def run_season(season: int, sealed: Iterable[str] = (), feat_dir: Optional[Path] = None, quiet: bool = False) -> dict[str, Any]:
    """Development pool of one season: every completed non-sealed weekend forecast leave-one-out (pipeline widening)."""
    F = SeasonForecaster(feat_dir or SEASON_DIRS[season], season, sealed=sealed)
    loo = F.loo_forecasts()
    cases, skipped, per_weekend = [], {}, {}
    for ev, fc in loo.items():
        cs, sk = evaluate_weekend(F, fc, drivers_seen_in(F, fc.pool_events))
        cases.extend(cs)
        for k, v in sk.items():
            skipped[k] = skipped.get(k, 0) + v
        per_weekend[fc.race_id] = dict(n_cases=len(cs), skipped=sk, weather=weather_regime(F.metas[ev]['track_temp'].get('R'), F.metas[ev]['rain'].get('R', False)))
    agg = aggregate(cases)
    out = dict(generated_at=now_iso(), git_sha=git_sha(), season=season, split='development_pool (leave-one-weekend-out; sealed weekends excluded from every pool)', sealed_excluded=sorted(F.sealed),
               weekends=sorted(loo), n_cases=len(cases), skipped=skipped, definitions=__doc__, units=dict(mae='s (next lap) / s over h laps (cumulative)', coverage='share of cases inside the 90 % interval'),
               parameters=dict(sigma_y=SIGMA_Y, offset_sd=OFFSET_SD, k_baseline=K_BASELINE, min_pre=MIN_PRE, window_post=WINDOW_POST, traffic_max=TRAFFIC_MAX, best_ratio=BEST_RATIO),
               per_weekend=per_weekend, aggregate=agg, cases=cases)
    if not quiet:
        print(render_table(out))
    return out


def render_table(out: dict[str, Any]) -> str:
    agg = out['aggregate']; p = agg['pooled']
    L = [f"Hidden-stop-response, season {out['season']} development pool: {out['n_cases']} stops over {p['n_weekends']} weekends (skipped: {out['skipped']})", '',
         '| cell | n | next-lap MAE | naive | 3-lap cum MAE | naive | 5-lap cum MAE | naive | cov90 next | cov90 +3 | cov90 +5 |', '|---|---|---|---|---|---|---|---|---|---|---|']

    def row(name: str, m: dict[str, Any]) -> str:
        f = lambda v: '—' if v is None else f'{v:.3f}'
        g = lambda v: '—' if v is None else f'{v:.0%}'
        return f"| {name} | {m['n_cases']} | {f(m['next1_mae'])} | {f(m['next1_mae_naive'])} | {f(m['cum3_mae'])} | {f(m['cum3_mae_naive'])} | {f(m['cum5_mae'])} | {f(m['cum5_mae_naive'])} | {g(m['next1_coverage90'])} | {g(m['cum3_coverage90'])} | {g(m['cum5_coverage90'])} |"
    L.append(row('pooled', p))
    for cell, vals in agg.get('by', {}).items():
        for v, m in vals.items():
            if 'suppressed' in m:
                L.append(f"| {cell}={v} | {m['n_cases']} | suppressed | | | | | | | | |")
            else:
                L.append(row(f'{cell}={v}', m))
    if 'bootstrap' in agg:
        b = agg['bootstrap']
        L += ['', 'Weekend-grouped bootstrap 90 % intervals: ' + '; '.join(f"{k} {v['estimate']:.3f} [{v['ci90'][0]:.3f}, {v['ci90'][1]:.3f}]" for k, v in b.items() if isinstance(v, dict) and v.get('ci90') and v.get('estimate') is not None),
              'P(Orb v1 beats naive): ' + '; '.join(f"{k.replace('p_orb_beats_naive_', '')} {v['p_bootstrap']:.2f} (rows {v['share_rows']:.2f})" for k, v in b.items() if k.startswith('p_orb') and v.get('p_bootstrap') is not None)]
    return '\n'.join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seasons', default='2026', help='comma-separated seasons (development pools only; sealed weekends are never scored here)')
    ap.add_argument('--out', type=Path, default=OUT_DIR)
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    from evaluation.holdout.evaluator import sealed_race_ids
    sealed = sealed_race_ids()
    a.out.mkdir(parents=True, exist_ok=True)
    for season in [int(s) for s in a.seasons.split(',') if s]:
        out = run_season(season, sealed=[r for r in sealed if r.startswith(f'{season}_')], quiet=a.quiet)
        write_json(a.out / f'hidden_stop_{season}.json', out)
        print(f'wrote {a.out / f"hidden_stop_{season}.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
