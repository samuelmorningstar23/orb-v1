"""Strategy regret: held-out strategy replay under a post-race reference model (roadmap v5 section 9).

For each held-out weekend four plans are costed under the race-derived pace-loss reference and compared with the
hindsight oracle under the same reference:
    Orb v1        strategy2.best_plans with the PRE-RACE Orb v1 slopes (issued x factor or the fallback), the weekend's
                  compound offsets (qualifying / practice, SOFT = 0) and the lock pit loss (strategy2.PIT_LOSS = 21 s)
    naive         the same optimiser with the naive practice slopes (raw lap time vs tyre age, no cleaning)
    observed      the field's plan: the most common compound sequence among classified finishers (last lap >= n - 1,
                  slick compounds only) with the median stint lengths of the drivers on that sequence, the last stint
                  absorbing the rounding so the lengths sum to the race distance
    default       a no-model plan: MEDIUM then HARD, one stop at half distance (when both are scorable, else the two
                  hardest scorable compounds softer-first)
    oracle        exhaustive one- and two-stop search (every stint length >= MIN_STINT, step 1, two distinct compounds)
                  under the reference slopes: the best plan anyone could have chosen with hindsight
Cost of a plan = sum over stints of  offset[c] x L + s_ref[c] x L (L + 1) / 2  + stops x PIT_LOSS   (strategy2.stint_time)
regret(plan)   = cost(plan) - cost(oracle)   [s over the race; >= 0 for any plan inside the oracle's search space]
Option sets: Orb v1 and naive plan over the compounds they had a pre-race forecast (and an offset) for; the oracle,
the observed plan and the default plan over every compound with a race-derived reference and an offset (the race
fit covers compounds that had no practice long run). A plan that uses a compound without a reference cannot be
costed and is 'unscorable' (reported, never silently dropped); Orb v1's regret therefore includes the cost of a
compound it could not forecast, and an observed plan outside the oracle's search space (stints below MIN_STINT,
more than two stops) can show a negative regret.

Reported over the weekends: median, mean, worst decile (90th percentile and the mean of the worst 10 %), share within
2, 5 and 10 s, probability Orb v1 beats naive and beats the observed plan (weekend bootstrap on the mean difference and
the raw share of weekends), all with weekend-grouped bootstrap intervals. The reference slope is post-race material:
this is a "held-out strategy replay under a post-race reference model", never observed race time saved.

CLI:  python -m evaluation.regret [--seasons 2026,2025,2024,2023] [--out out/validation]
"""
from __future__ import annotations

import argparse
import itertools
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from evaluation import PROTO, OUT_DIR, SEASON_DIRS, COMPS, git_sha, now_iso, circuit_class
from evaluation.common import weekend_bootstrap, paired_probability, describe, write_json, finite
from evaluation.forecast import SeasonForecaster, WeekendForecast

import strategy2 as S                                     # noqa: E402
from counterfactual.racedata import RaceData, load_race   # noqa: E402  (post-race file access; scoring only)

LABEL = 'held-out strategy replay under a post-race reference model'
PLANS = ('orb', 'naive', 'observed', 'default')
MIN_STINT = int(S.MIN_STINT)
PIT_LOSS = float(S.PIT_LOSS)
LETTER = {'S': 'SOFT', 'M': 'MEDIUM', 'H': 'HARD'}
HARDNESS = {'SOFT': 0, 'MEDIUM': 1, 'HARD': 2}


def plan_cost(seq: list[str], stints: list[int], offsets: dict[str, float], slopes: dict[str, float], pit_loss: float = PIT_LOSS) -> float:
    return float(sum(S.stint_time(offsets[c], slopes[c], int(L)) for c, L in zip(seq, stints)) + (len(seq) - 1) * pit_loss)


def oracle_plan(offsets: dict[str, float], slopes: dict[str, float], n_laps: int, max_stops: int = 2, min_stint: int = MIN_STINT, pit_loss: float = PIT_LOSS) -> Optional[dict[str, Any]]:
    """Exhaustive best plan (step 1 in every stint length) under `slopes`; None with fewer than two compounds."""
    comps = [c for c in COMPS if c in offsets and c in slopes and np.isfinite(slopes[c])]
    if len(comps) < 2 or n_laps < 2 * min_stint:
        return None
    L = np.arange(1, n_laps + 1, dtype=float)
    cost = {c: offsets[c] * L + slopes[c] * L * (L + 1) / 2.0 for c in comps}      # cost[c][L-1] = stint of L laps
    best: Optional[tuple[float, tuple[str, ...], tuple[int, ...]]] = None
    for a in range(min_stint, n_laps - min_stint + 1):
        b = n_laps - a
        for c1, c2 in itertools.permutations(comps, 2):
            t = cost[c1][a - 1] + cost[c2][b - 1] + pit_loss
            if best is None or t < best[0]:
                best = (t, (c1, c2), (a, b))
    if max_stops >= 2 and n_laps >= 3 * min_stint:
        for seq in itertools.product(comps, repeat=3):
            if len(set(seq)) < 2:
                continue
            c1, c2, c3 = seq
            for a in range(min_stint, n_laps - 2 * min_stint + 1):
                rest = n_laps - a
                bs = np.arange(min_stint, rest - min_stint + 1)
                t = cost[c1][a - 1] + cost[c2][bs - 1] + cost[c3][rest - bs - 1] + 2 * pit_loss
                j = int(np.argmin(t))
                if best is None or t[j] < best[0]:
                    best = (float(t[j]), seq, (a, int(bs[j]), int(rest - bs[j])))
    if best is None:
        return None
    t, seq, stints = best
    return dict(plan='-'.join(c[0] for c in seq), seq=list(seq), stints=[int(x) for x in stints], stops=len(seq) - 1, cost=float(t))


def top_plan(offsets: dict[str, float], slopes: dict[str, float], n_laps: int) -> Optional[dict[str, Any]]:
    """strategy2.best_plans top entry (the production optimiser) as {plan, seq, stints, stops, time}."""
    plans = S.best_plans(offsets, {c: v for c, v in slopes.items() if c in offsets and np.isfinite(v)}, n_laps)
    if not plans:
        return None
    p = plans[0]
    return dict(plan=p['plan'], seq=[LETTER[ch] for ch in p['plan'].split('-')], stints=[int(x) for x in p['stints']], stops=int(p['stops']), time=float(p['time']))


def observed_plan(race: RaceData, n_laps: int) -> Optional[dict[str, Any]]:
    """Most common slick compound sequence among classified finishers with median stint lengths (last stint absorbs rounding)."""
    seqs: dict[tuple[str, ...], list[list[int]]] = {}
    for drv in race.drivers:
        dl = race.driver(drv)
        if dl.n < n_laps - 1:
            continue
        seq = tuple(s.compound for s in dl.stints)
        if any(c not in COMPS for c in seq) or len(seq) < 2:
            continue
        seqs.setdefault(seq, []).append([s.n_laps for s in dl.stints])
    if not seqs:
        return None
    counts = Counter({k: len(v) for k, v in seqs.items()})
    seq, n_drv = counts.most_common(1)[0]
    med = np.median(np.array(seqs[seq], dtype=float), axis=0)
    stints = [max(1, int(round(x))) for x in med]
    stints[-1] = max(1, n_laps - sum(stints[:-1]))
    return dict(plan='-'.join(c[0] for c in seq), seq=list(seq), stints=stints, stops=len(seq) - 1, drivers=int(n_drv), drivers_classified=int(sum(counts.values())))


def default_plan(scorable: Iterable[str], n_laps: int) -> Optional[dict[str, Any]]:
    comps = sorted(set(scorable), key=lambda c: HARDNESS[c])
    if len(comps) < 2:
        return None
    seq = ['MEDIUM', 'HARD'] if ('MEDIUM' in comps and 'HARD' in comps) else comps[-2:]
    a = n_laps // 2
    return dict(plan='-'.join(c[0] for c in seq), seq=seq, stints=[a, n_laps - a], stops=1)


def weekend_regret(fc: WeekendForecast, reference: dict[str, dict[str, float]], race: RaceData) -> dict[str, Any]:
    """The four plans, the oracle and the regret of each under the race-derived reference for one weekend."""
    n_laps = int(fc.n_laps or race.n_laps)
    ref = {c: float(v['obs']) for c, v in reference.items()}
    pre = fc.slopes(); naive = fc.naive_slopes()
    offsets = {c: float(v) for c, v in fc.offsets.items()}
    scorable = [c for c in COMPS if c in ref and c in offsets]                    # costable under the reference
    forecast_set = [c for c in COMPS if c in pre and c in offsets]                 # the pre-race option set
    out: dict[str, Any] = dict(race_id=fc.race_id, season=fc.season, event=fc.event, n_laps=n_laps, circuit_class=circuit_class(fc.event), offsets=offsets, pit_loss=PIT_LOSS,
                               scorable_compounds=scorable, forecast_compounds=forecast_set, reference_slopes={c: ref[c] for c in scorable}, pre_race_slopes={c: pre[c] for c in forecast_set},
                               label=LABEL, plans={})
    oracle = oracle_plan(offsets, {c: ref[c] for c in scorable}, n_laps)
    out['oracle'] = oracle
    if oracle is None:
        out['unscorable'] = 'fewer than two compounds with a race-derived reference and an offset'
        return out
    candidates = {
        'orb': top_plan(offsets, {c: pre[c] for c in forecast_set}, n_laps),
        'naive': top_plan(offsets, {c: naive[c] for c in forecast_set if c in naive}, n_laps),
        'observed': observed_plan(race, n_laps),
        'default': default_plan(scorable, n_laps),
    }
    for name, p in candidates.items():
        if p is None:
            out['plans'][name] = dict(unscorable='no plan (too few compounds or no classified finisher on slicks)')
            out[f'regret_{name}'] = None
            continue
        if any(c not in ref for c in p['seq']):
            out['plans'][name] = dict(**p, unscorable=f"uses a compound without a race-derived reference: {[c for c in p['seq'] if c not in ref]}")
            out[f'regret_{name}'] = None
            continue
        cost = plan_cost(p['seq'], p['stints'], offsets, ref)
        p = dict(p, cost_under_reference=cost, regret=cost - oracle['cost'])
        out['plans'][name] = p
        out[f'regret_{name}'] = float(cost - oracle['cost'])
    return out


def aggregate(rows: list[dict[str, Any]], bootstrap: bool = True) -> dict[str, Any]:
    df = pd.DataFrame([{k: v for k, v in r.items() if not isinstance(v, (dict, list))} for r in rows])
    out: dict[str, Any] = dict(label=LABEL, units='s over the race, plan cost under the race-derived reference minus the hindsight oracle', n_weekends=int(len(df)), plans={})
    if df.empty:
        return out
    for name in PLANS:
        col = f'regret_{name}'
        v = df[col].dropna() if col in df else pd.Series(dtype=float)
        d = describe(v.tolist())
        if d['n']:
            worst = v[v >= np.percentile(v, 90)]
            d.update(worst_decile_mean=float(worst.mean()), share_within_2s=float((v <= 2).mean()), share_within_5s=float((v <= 5).mean()), share_within_10s=float((v <= 10).mean()))
            if bootstrap:
                sub = df.dropna(subset=[col])
                d['ci90_mean'] = weekend_bootstrap(sub, lambda x, c=col: float(x[c].mean()))
                d['ci90_median'] = weekend_bootstrap(sub, lambda x, c=col: float(x[c].median()))
        out['plans'][name] = d
    if 'regret_orb' in df:
        out['p_orb_beats_naive'] = paired_probability(df, 'regret_orb', 'regret_naive') if 'regret_naive' in df else None
        out['p_orb_beats_observed'] = paired_probability(df, 'regret_orb', 'regret_observed') if 'regret_observed' in df else None
        out['p_orb_beats_default'] = paired_probability(df, 'regret_orb', 'regret_default') if 'regret_default' in df else None
    return out


def run_season(season: int, sealed: Iterable[str] = (), feat_dir: Optional[Path] = None, quiet: bool = False) -> dict[str, Any]:
    F = SeasonForecaster(feat_dir or SEASON_DIRS[season], season, sealed=sealed)
    loo = F.loo_forecasts()
    rows = []
    for ev, fc in loo.items():
        race = load_race(ev, str(F.race_path(ev)))
        rows.append(weekend_regret(fc, F.reference(ev), race))
    agg = aggregate(rows)
    out = dict(generated_at=now_iso(), git_sha=git_sha(), season=season, label=LABEL, split='development_pool (leave-one-weekend-out; sealed weekends excluded from every pool)',
               sealed_excluded=sorted(F.sealed), definitions=__doc__, aggregate=agg, weekends=rows)
    if not quiet:
        print(render_table(out))
    return out


def render_table(out: dict[str, Any]) -> str:
    agg = out['aggregate']
    L = [f"Strategy regret, season {out.get('season', '')}: {LABEL} ({agg['n_weekends']} weekends)", '',
         '| plan | n | median | mean | p90 | worst-decile mean | within 2 s | within 5 s | within 10 s |', '|---|---|---|---|---|---|---|---|---|']
    for name in PLANS:
        d = agg['plans'].get(name, {})
        if not d.get('n'):
            L.append(f'| {name} | 0 | — | — | — | — | — | — | — |'); continue
        ci = d.get('ci90_mean', {}).get('ci90')
        mean = f"{d['mean']:.1f}" + (f" [{ci[0]:.1f}, {ci[1]:.1f}]" if ci else '')
        L.append(f"| {name} | {d['n']} | {d['median']:.1f} | {mean} | {d['p90']:.1f} | {d['worst_decile_mean']:.1f} | {d['share_within_2s']:.0%} | {d['share_within_5s']:.0%} | {d['share_within_10s']:.0%} |")
    for k in ('p_orb_beats_naive', 'p_orb_beats_observed', 'p_orb_beats_default'):
        v = agg.get(k)
        if v and v.get('share_rows') is not None:
            L.append(f"{k}: share of weekends {v['share_rows']:.2f}; P(mean regret lower) under the weekend bootstrap {v['p_bootstrap'] if v['p_bootstrap'] is None else round(v['p_bootstrap'], 2)} (n={v['n_weekends']} weekends with both plans scorable)")
    if 'weekends' in out:
        L += ['', '| weekend | Orb v1 plan | regret | naive plan | regret | observed plan | regret | default | regret | oracle |', '|---|---|---|---|---|---|---|---|---|---|']
        for r in out['weekends']:
            def pl(n):
                p = r['plans'].get(n, {})
                return (f"{p.get('plan', '—')} {p.get('stints', '')}", ('—' if r.get(f'regret_{n}') is None else f"{r[f'regret_{n}']:.1f}"))
            o = r.get('oracle') or {}
            cells = [c for n in PLANS for c in pl(n)]
            L.append(f"| {r['race_id']} | " + ' | '.join(cells) + f" | {o.get('plan', '—')} {o.get('stints', '')} |")
    return '\n'.join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--seasons', default='2026')
    ap.add_argument('--out', type=Path, default=OUT_DIR)
    ap.add_argument('--quiet', action='store_true')
    a = ap.parse_args(argv)
    from evaluation.holdout.evaluator import sealed_race_ids
    sealed = sealed_race_ids()
    a.out.mkdir(parents=True, exist_ok=True)
    for season in [int(s) for s in a.seasons.split(',') if s]:
        out = run_season(season, sealed=[r for r in sealed if r.startswith(f'{season}_')], quiet=a.quiet)
        write_json(a.out / f'regret_{season}.json', out)
        print(f'wrote {a.out / f"regret_{season}.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
