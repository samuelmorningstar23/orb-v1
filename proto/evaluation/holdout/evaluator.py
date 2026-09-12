"""Sealed-holdout evaluator (roadmap v5 task 0.1 and section 9.0): aggregate metrics only, per-race results behind freeze.json.

For each sealed weekend (evaluation/holdout/sealed_holdout_manifest.json, six weekends of 2023 to 2025):
    pre-race forecast   practice files of that weekend only; transfer factors, fallback floor and band widening learned
                        from the NON-sealed completed weekends of the same season (evaluation.forecast.SeasonForecaster,
                        strict mode: nothing about any sealed race enters any pool; a PoolSpy records every pool read)
    reference           the race-derived pace-loss reference (model_v2.fit on the race, all drivers), scoring only
    forecast error      |prediction - reference| per compound-weekend, naive and clean-only for comparison
    band coverage       share of compound-weekends whose reference lies inside the calibrated 90 % band
    hidden-stop test    evaluation.hidden_stop.stop_cases with the same pre-race forecast
    strategy regret     evaluation.regret.weekend_regret (held-out strategy replay under a post-race reference model)

Outputs (proto/out/validation/):
    holdout_aggregate.json   ALWAYS: metrics pooled over the six weekends with weekend-grouped bootstrap intervals; cells
                             (circuit class, degradation class, temperature regime, SC presence) reported only when they hold
                             at least MIN_CELL_WEEKENDS = 3 weekends; no per-weekend value anywhere in the file
    holdout_per_race.json    ONLY when evaluation/holdout/freeze.json exists with model_frozen, feature_list_frozen,
                             gate_threshold_frozen, provider_frozen all true and a git_commit; otherwise the evaluator prints
                             "per-race results sealed" and exits 0
post_holdout_tuning is true in the output when a freeze exists and the current git commit differs from the freeze commit.
Every aggregate file carries two top-level flags: dry_run_before_freeze and quotable. Without a valid freeze the run is a
DRY RUN (dry_run_before_freeze=true, quotable=false, a warning is printed and stored in the file): no number from such a
file may be quoted anywhere (lead decision, 12 Sep: the 16:55 aggregate was revealed before the freeze). Under a valid
freeze the flags are dry_run_before_freeze=false, quotable=true.
The manifest's sha256 must match sealed_holdout_manifest.sha256; on a mismatch the evaluator prints a stop-the-line
message and exits 2 (writing release/STOP_THE_LINE.json is Workstream 9's). It never prints a per-race number.

CLI:  python -m evaluation.holdout.evaluator [--out out/validation] [--freeze evaluation/holdout/freeze.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from evaluation import PROTO, OUT_DIR, SEASON_DIRS, COMPS, MANIFEST_PATH, MANIFEST_SHA_PATH, FREEZE_PATH, git_sha, now_iso, weather_regime
from evaluation.common import mae, share, weekend_bootstrap, paired_probability, write_json, finite
from evaluation.forecast import SeasonForecaster, PoolSpy, score_forecast
from evaluation.hidden_stop import stop_cases, aggregate as hs_aggregate, drivers_seen_in
from evaluation.regret import weekend_regret, aggregate as regret_aggregate, LABEL as REGRET_LABEL

from counterfactual.racedata import load_race     # noqa: E402

FREEZE_FLAGS = ('model_frozen', 'feature_list_frozen', 'gate_threshold_frozen', 'provider_frozen')
MIN_CELL_WEEKENDS = 3
CELL_KEYS = ('circuit_class', 'degradation_class', 'temperature_regime', 'sc_or_vsc')
STOP_MESSAGE = ('STOP THE LINE: the sealed holdout manifest does not match its recorded sha256 (stop-the-line condition: sealed holdout opened or altered). '
                'No evaluation was run. Workstream 9 records release/STOP_THE_LINE.json; the lead restores the sealed manifest from the last green commit.')
DRY_RUN_WARNING = ('WARNING: sealed-holdout aggregate produced WITHOUT a valid freeze (evaluation/holdout/freeze.json): this is a DRY RUN BEFORE THE MODEL FREEZE '
                   '(dry_run_before_freeze=true, quotable=false). Do not quote any number from this file in any document, scorecard or deck. '
                   'After the lead writes freeze.json (checkpoint C4), re-run `python -m evaluation.holdout.evaluator` then `python -m evaluation.scorecards` '
                   'and quote only that run, labelled "sealed holdout, aggregate".')
QUOTABLE_RULE = ('quotable is true only for a run produced under a valid freeze.json (model_frozen, feature_list_frozen, gate_threshold_frozen, provider_frozen all true '
                 'and a git_commit); a dry run before the freeze is never quoted anywhere')


# ---------------------------------------------------------------- manifest and freeze

def sha256_of(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest_check(manifest_path: Path | str = MANIFEST_PATH, sha_path: Path | str = MANIFEST_SHA_PATH) -> dict[str, Any]:
    """{'ok': bool, 'message': str, 'sha256': actual, 'recorded': from the .sha256 file}."""
    manifest_path, sha_path = Path(manifest_path), Path(sha_path)
    if not manifest_path.exists() or not sha_path.exists():
        return dict(ok=False, message=f'missing {manifest_path.name if not manifest_path.exists() else sha_path.name}', sha256=None, recorded=None)
    actual = sha256_of(manifest_path)
    recorded = sha_path.read_text(encoding='utf-8').split()[0].strip().lower() if sha_path.read_text(encoding='utf-8').strip() else ''
    if actual != recorded:
        return dict(ok=False, message=f'sha256 mismatch: file {actual[:16]}... recorded {recorded[:16]}...', sha256=actual, recorded=recorded)
    try:
        m = json.loads(manifest_path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        return dict(ok=False, message=f'manifest is not valid JSON: {e}', sha256=actual, recorded=recorded)
    ids = list(m.get('race_ids', []))
    problems = []
    if not ids or sorted(ids) != sorted(m.get('metadata', {}).keys()):
        problems.append('race_ids and metadata keys differ')
    if int(m.get('holdout_count', -1)) != len(ids):
        problems.append('holdout_count differs from the number of race_ids')
    if m.get('prohibited_for_tuning') is not True:
        problems.append('prohibited_for_tuning is not true')
    if problems:
        return dict(ok=False, message='manifest inconsistent: ' + '; '.join(problems), sha256=actual, recorded=recorded)
    return dict(ok=True, message='manifest sha256 verified', sha256=actual, recorded=recorded)


def load_manifest(manifest_path: Path | str = MANIFEST_PATH, sha_path: Path | str = MANIFEST_SHA_PATH) -> dict[str, Any]:
    chk = manifest_check(manifest_path, sha_path)
    if not chk['ok']:
        raise PermissionError(f"{STOP_MESSAGE} ({chk['message']})")
    return json.loads(Path(manifest_path).read_text(encoding='utf-8'))


def sealed_race_ids(manifest_path: Path | str = MANIFEST_PATH) -> list[str]:
    """The sealed race ids ('2024_Monza', ...) straight from the manifest; used by every module that must exclude them."""
    p = Path(manifest_path)
    if not p.exists():
        return []
    return sorted(json.loads(p.read_text(encoding='utf-8')).get('race_ids', []))


def load_freeze(freeze_path: Path | str = FREEZE_PATH) -> Optional[dict[str, Any]]:
    p = Path(freeze_path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding='utf-8'))


def reveal_allowed(freeze: Optional[dict[str, Any]]) -> tuple[bool, str]:
    if freeze is None:
        return False, 'no freeze.json: model, feature list, gate threshold and provider are not frozen'
    missing = [k for k in FREEZE_FLAGS if freeze.get(k) is not True]
    if missing:
        return False, 'freeze.json does not assert: ' + ', '.join(missing)
    commit = freeze.get('git_commit')
    if not isinstance(commit, str) or not commit.strip():
        return False, 'freeze.json carries no git_commit'
    return True, f'frozen at commit {commit}'


def post_holdout_tuning(freeze: Optional[dict[str, Any]], current_sha: Optional[str]) -> Optional[bool]:
    """True when a freeze commit is recorded and the working commit differs (short or long SHA accepted); None without a freeze."""
    if freeze is None or not isinstance(freeze.get('git_commit'), str) or not freeze['git_commit'].strip():
        return None
    if current_sha is None:
        return True
    a, b = freeze['git_commit'].strip().lower(), current_sha.strip().lower()
    return not (a.startswith(b) or b.startswith(a))


# ---------------------------------------------------------------- evaluation

def _forecast_summary(rows: pd.DataFrame, bootstrap: bool = True) -> dict[str, Any]:
    iss = rows[rows['issued']]; fb = rows[~rows['issued']]
    out: dict[str, Any] = dict(n_weekends=int(rows['race_id'].nunique()), n_compound_weekends=int(len(rows)), n_issued=int(len(iss)), n_withheld=int(len(fb)), n_no_forecast=int(rows['prediction'].isna().sum()),
                               mae=dict(orb_v1=mae(rows['err']), naive=mae(rows['err_naive']), clean_issued=mae(iss['err_clean']), orb_v1_issued=mae(iss['err']), orb_v1_fallback=mae(fb['err']), naive_issued=mae(iss['err_naive'])),
                               band_coverage90=dict(all=share(rows['covered']), issued=share(iss['covered']), fallback=share(fb['covered']), nominal=0.90),
                               abstention=dict(share_issued=(len(iss) / len(rows)) if len(rows) else None, share_withheld=(len(fb) / len(rows)) if len(rows) else None),
                               by_compound={c: dict(n=int((rows['compound'] == c).sum()), mae_orb_v1=mae(rows[rows['compound'] == c]['err']), mae_naive=mae(rows[rows['compound'] == c]['err_naive'])) for c in COMPS},
                               wins_orb_over_naive=int(((rows['err'] < rows['err_naive']) & rows['err'].notna()).sum()))
    m = rows.dropna(subset=['prediction', 'obs'])
    if len(m) >= 3 and m['prediction'].std() > 0:
        out['calibration'] = dict(slope=float(np.polyfit(m['prediction'], m['obs'], 1)[0]), r=float(np.corrcoef(m['prediction'], m['obs'])[0, 1]), n=int(len(m)))
    if bootstrap and len(rows):
        out['bootstrap'] = dict(mae_orb_v1=weekend_bootstrap(rows, lambda d: mae(d['err'])), mae_naive=weekend_bootstrap(rows, lambda d: mae(d['err_naive'])),
                                band_coverage90=weekend_bootstrap(rows, lambda d: share(d['covered'])), p_orb_beats_naive=paired_probability(rows, 'err', 'err_naive'))
    return out


def evaluate_sealed(manifest: dict[str, Any], season_dirs: dict[int, Path] | None = None, spy: Optional[PoolSpy] = None, bootstrap: bool = True) -> dict[str, Any]:
    """Run the four tests on every sealed weekend. Returns {'per_race': {...}, 'aggregate': {...}, 'leakage': {...}}; the
    caller decides what is written. Nothing here prints."""
    season_dirs = season_dirs or SEASON_DIRS
    spy = spy or PoolSpy()
    ids = sorted(manifest['race_ids'])
    by_season: dict[int, list[str]] = {}
    for rid in ids:
        y, ev = rid.split('_', 1)
        by_season.setdefault(int(y), []).append(rid)
    per_race: dict[str, Any] = {}
    fc_rows: list[dict[str, Any]] = []
    hs_cases: list[dict[str, Any]] = []
    regret_rows: list[dict[str, Any]] = []
    pools: dict[str, list[str]] = {}
    skipped_hs: dict[str, int] = {}
    for season, rids in sorted(by_season.items()):
        F = SeasonForecaster(season_dirs[season], season, sealed=rids, spy=spy)
        pool = F.development_events
        pools[str(season)] = pool
        seen = drivers_seen_in(F, pool)
        for rid in rids:
            ev = rid.split('_', 1)[1]
            if ev not in F.metas:
                # pipeline.py's own rule: fewer than 40 clean practice laps -> no weekend table -> the system abstains for the weekend
                per_race[rid] = dict(error='no weekend table: fewer than 40 clean practice laps (weekend-level abstention by the pipeline rule)')
                continue
            fc = F.forecast(ev, pool, target_obs_in_widening=False)
            ref = F.reference(ev)
            race = load_race(ev, str(F.race_path(ev)))
            rows = score_forecast(fc, ref)
            cases, sk = stop_cases(race, fc, rid, seen)
            for k, v in sk.items():
                skipped_hs[k] = skipped_hs.get(k, 0) + v
            rg = weekend_regret(fc, ref, race)
            md = manifest['metadata'].get(rid, {})
            for r in rows:
                r.update({k: md.get(k) for k in CELL_KEYS})
                r['weather_regime'] = weather_regime(F.metas[ev]['track_temp'].get('R'), F.metas[ev]['rain'].get('R', False))
            fc_rows.extend(rows); hs_cases.extend(cases); regret_rows.append(dict(rg, **{k: md.get(k) for k in CELL_KEYS}))
            per_race[rid] = dict(forecast=fc.as_dict(), reference=ref, forecast_rows=rows, hidden_stop=hs_aggregate(cases, bootstrap=False), hidden_stop_skipped=sk, regret=rg, metadata=md)
    rows_df = pd.DataFrame(fc_rows)
    n_abstained = sum(1 for v in per_race.values() if 'error' in v)
    agg: dict[str, Any] = dict(weekends=dict(sealed=len(ids), forecast=len(ids) - n_abstained, weekend_level_abstention=n_abstained,
                                             abstention_rule='no forecast when the weekend has fewer than 40 clean practice laps (pipeline.py); such a weekend cannot be scored on any test'),
                               forecast=_forecast_summary(rows_df, bootstrap) if len(rows_df) else dict(n_weekends=0),
                               hidden_stop=hs_aggregate(hs_cases, bootstrap=bootstrap, min_weekends_per_cell=MIN_CELL_WEEKENDS), hidden_stop_skipped=skipped_hs,
                               regret=_strip_extremes(regret_aggregate(regret_rows, bootstrap=bootstrap)), cells={})
    for key in CELL_KEYS:
        agg['cells'][key] = {}
        if not len(rows_df):
            continue
        for val, d in rows_df.groupby(key):
            n_w = int(d['race_id'].nunique())
            if n_w < MIN_CELL_WEEKENDS:
                agg['cells'][key][str(val)] = dict(suppressed=f'fewer than {MIN_CELL_WEEKENDS} weekends in the cell (would reveal per-race results)', n_weekends=n_w)
            else:
                rr = [r for r in regret_rows if str(r.get(key)) == str(val)]
                agg['cells'][key][str(val)] = dict(n_weekends=n_w, forecast=_forecast_summary(d, bootstrap=False), regret=_strip_extremes(regret_aggregate(rr, bootstrap=False)))
    leakage: dict[str, Any] = dict(pool_events_by_season=pools, spy_records=len(spy.records))
    # the spy records race ids: no source of any pool read may be a sealed race id (by construction, and checked here)
    sealed_ids = set(ids)
    leaks = [(t, src, w) for t, src, w in spy.records if src in sealed_ids]
    leakage['sealed_never_in_pool'] = not leaks
    leakage['leaks'] = leaks[:20]
    leakage['sources_seen'] = sorted({src for _, src, _ in spy.records})
    return dict(per_race=per_race, aggregate=agg, leakage=leakage, n_weekends=len(per_race))


def _strip_extremes(agg: dict[str, Any]) -> dict[str, Any]:
    """Sealed aggregate hygiene: drop min / max from the regret plans (order statistics that single out one weekend) and
    suppress any plan statistic resting on fewer than MIN_CELL_WEEKENDS scorable weekends; p90 and the worst-decile mean stay."""
    out = dict(agg)
    plans = {}
    for name, d in agg.get('plans', {}).items():
        if d.get('n', 0) < MIN_CELL_WEEKENDS:
            plans[name] = dict(n=d.get('n', 0), suppressed=f'fewer than {MIN_CELL_WEEKENDS} weekends with a scorable {name} plan')
        else:
            plans[name] = {k: v for k, v in d.items() if k not in ('min', 'max')}
    out['plans'] = plans
    for k in ('p_orb_beats_naive', 'p_orb_beats_observed', 'p_orb_beats_default'):
        v = out.get(k)
        if isinstance(v, dict) and v.get('n_weekends', 0) < MIN_CELL_WEEKENDS:
            out[k] = dict(n_weekends=v.get('n_weekends', 0), suppressed=f'fewer than {MIN_CELL_WEEKENDS} weekends with both plans scorable')
    return out


def dry_run_flags(freeze: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The two top-level flags every aggregate file carries. A run without a valid freeze (missing file, any of the four
    flags not true, or no git_commit) is a dry run before the freeze and is not quotable; a valid freeze makes it quotable."""
    allowed, reason = reveal_allowed(freeze)
    return dict(dry_run_before_freeze=not allowed, quotable=allowed, quotable_rule=QUOTABLE_RULE, freeze_status=reason)


def write_outputs(results: dict[str, Any], freeze: Optional[dict[str, Any]], out_dir: Path | str = OUT_DIR, current_sha: Optional[str] = None, manifest_meta: Optional[dict[str, Any]] = None,
                  quiet: bool = False) -> dict[str, Any]:
    """Write holdout_aggregate.json always (flagged dry_run_before_freeze / quotable); holdout_per_race.json only when the freeze allows it.
    Without a valid freeze the dry-run warning goes to stderr (unless quiet) and into the file. Returns the paths, the reveal decision and the flags."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    allowed, reason = reveal_allowed(freeze)
    tuned = post_holdout_tuning(freeze, current_sha)
    flags = dry_run_flags(freeze)
    header = dict(generated_at=now_iso(), git_sha=current_sha, manifest=manifest_meta or {}, freeze=freeze, **flags, reveal=dict(per_race_written=allowed, reason=reason),
                  post_holdout_tuning=tuned, n_weekends=results.get('n_weekends'),
                  data_cutoff='seasons 2023 to 2025 complete; each sealed weekend is forecast from its own practice files and factors from the non-sealed weekends of its season',
                  units=dict(degradation='s/lap per lap of tyre age', hidden_stop='s (next lap) and s over h laps (cumulative)', regret='s over the race', coverage='share inside the 90 % band'),
                  method=dict(forecast='model_v2 stint fixed effects + per-compound slope on tyre age on cleaned practice; transfer factor, fallback floor and conformal widening from the season pool (pipeline.py rules); strict leave-out',
                              reference='race-derived pace-loss reference: model_v2.fit on the race, all drivers (post-race, scoring only)', hidden_stop='evaluation/hidden_stop.py', regret=REGRET_LABEL,
                              cells=f'cells with fewer than {MIN_CELL_WEEKENDS} weekends are suppressed; no per-weekend value is written to the aggregate file'),
                  leakage_check=results.get('leakage'))
    if flags['dry_run_before_freeze']:
        header['warning'] = DRY_RUN_WARNING
        if not quiet:
            print(DRY_RUN_WARNING, file=sys.stderr)
    agg_path = out_dir / 'holdout_aggregate.json'
    write_json(agg_path, dict(header, aggregate=results['aggregate']))
    paths = dict(aggregate=str(agg_path), per_race=None)
    if allowed:
        pr_path = out_dir / 'holdout_per_race.json'
        write_json(pr_path, dict(header, per_race=results['per_race']))
        paths['per_race'] = str(pr_path)
        if not quiet:
            print(f'per-race results revealed under freeze ({reason}); post_holdout_tuning={tuned}')
    else:
        if not quiet:
            print(f'per-race results sealed ({reason})')
    return dict(paths=paths, reveal=allowed, reason=reason, post_holdout_tuning=tuned, **{k: flags[k] for k in ('dry_run_before_freeze', 'quotable')})


def print_aggregate(agg: dict[str, Any]) -> None:
    """Aggregate lines only; never a per-weekend number."""
    w = agg.get('weekends', {})
    if w:
        print(f"sealed weekends {w.get('sealed')}: forecast issued for {w.get('forecast')}, weekend-level abstention {w.get('weekend_level_abstention')} ({w.get('abstention_rule')})")
    f = agg.get('forecast', {})
    if f.get('n_weekends'):
        m, c = f['mae'], f['band_coverage90']
        fmt = lambda v: '—' if v is None else f'{v:.4f}'
        print(f"sealed holdout, {f['n_weekends']} weekends, {f['n_compound_weekends']} compound-weekends ({f['n_issued']} issued, {f['n_withheld']} withheld): "
              f"MAE Orb v1 {fmt(m['orb_v1'])} vs naive {fmt(m['naive'])} s/lap; issued {fmt(m['orb_v1_issued'])} (clean-only {fmt(m['clean_issued'])}), fallback {fmt(m['orb_v1_fallback'])}; "
              f"band coverage {c['all'] if c['all'] is None else round(c['all'], 2)} (nominal 0.90)")
        b = f.get('bootstrap')
        if b:
            print(f"  weekend bootstrap: MAE Orb v1 90 % CI {b['mae_orb_v1']['ci90']}, naive {b['mae_naive']['ci90']}; P(Orb v1 beats naive) {b['p_orb_beats_naive']['p_bootstrap']}")
    h = agg.get('hidden_stop', {}).get('pooled', {})
    if h.get('n_cases'):
        print(f"  hidden-stop: {h['n_cases']} stops; next-lap MAE {h['next1_mae']:.3f} (naive {h['next1_mae_naive']:.3f}); 3-lap cum {h['cum3_mae']:.3f} ({h['cum3_mae_naive']:.3f}); 5-lap cum {h['cum5_mae']:.3f} ({h['cum5_mae_naive']:.3f}); "
              f"cov90 next {h['next1_coverage90']:.2f}, +3 {h['cum3_coverage90']:.2f}, +5 {h['cum5_coverage90']:.2f}")
    r = agg.get('regret', {})
    for name, d in r.get('plans', {}).items():
        if d.get('suppressed'):
            print(f"  regret {name:8s}: n={d.get('n', 0)} suppressed ({d['suppressed']})")
        elif d.get('n'):
            print(f"  regret {name:8s}: n={d['n']} weekends; median {d['median']:.1f} s, mean {d['mean']:.1f} s, p90 {d['p90']:.1f} s, within 2/5/10 s {d['share_within_2s']:.0%}/{d['share_within_5s']:.0%}/{d['share_within_10s']:.0%} ({REGRET_LABEL})")
    for k in ('p_orb_beats_naive', 'p_orb_beats_observed'):
        v = r.get(k)
        if v and v.get('share_rows') is not None:
            print(f"  {k}: share of weekends {v['share_rows']:.2f}, bootstrap P {v['p_bootstrap']} (n={v['n_weekends']})")
        elif v and v.get('suppressed'):
            print(f"  {k}: suppressed ({v['suppressed']})")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--manifest', type=Path, default=MANIFEST_PATH)
    ap.add_argument('--sha', type=Path, default=MANIFEST_SHA_PATH)
    ap.add_argument('--freeze', type=Path, default=FREEZE_PATH)
    ap.add_argument('--out', type=Path, default=OUT_DIR)
    ap.add_argument('--no-bootstrap', action='store_true')
    a = ap.parse_args(argv)
    chk = manifest_check(a.manifest, a.sha)
    if not chk['ok']:
        print(f"{STOP_MESSAGE} ({chk['message']})", file=sys.stderr)
        return 2
    manifest = json.loads(Path(a.manifest).read_text(encoding='utf-8'))
    print(f"manifest {chk['message']} ({chk['sha256'][:16]}...), {manifest['holdout_count']} sealed weekends, version {manifest.get('holdout_version')}")
    freeze = load_freeze(a.freeze)
    results = evaluate_sealed(manifest, bootstrap=not a.no_bootstrap)
    if not results['leakage']['sealed_never_in_pool']:
        print('STOP THE LINE: a sealed race entered a factor pool', file=sys.stderr)
        return 2
    sha = git_sha()
    meta = dict(path=str(Path(a.manifest).relative_to(PROTO)) if Path(a.manifest).is_relative_to(PROTO) else str(a.manifest), sha256=chk['sha256'], holdout_version=manifest.get('holdout_version'),
                holdout_count=manifest.get('holdout_count'), race_ids=manifest.get('race_ids'), selected_at=manifest.get('selected_at'))
    w = write_outputs(results, freeze, a.out, sha, meta)
    print_aggregate(results['aggregate'])
    tag = ' [DRY RUN BEFORE FREEZE: dry_run_before_freeze=true, quotable=false; not to be quoted anywhere]' if w['dry_run_before_freeze'] else ' [under freeze: quotable=true]'
    print(f"wrote {w['paths']['aggregate']}" + (f" and {w['paths']['per_race']}" if w['paths']['per_race'] else '') + tag)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
