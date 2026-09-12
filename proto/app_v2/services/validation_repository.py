"""Reads Workstream 3's blind-evaluation outputs under proto/out/validation/. Never computes a scientific number.

Files (evaluation/README.md): ghost_scorecard.json, live_scorecard.json, risk_coverage.{json,csv,png},
hidden_stop_<season>.json, regret_<season>.json, holdout_aggregate.json, SCORECARDS.md. Every number a page shows from
here is a value read verbatim from one of these files; the page prints the file's sha256 (services/asset_repository),
Workstream 3's generated_at and git_sha next to it. Two scorecards, never merged (Ghost Strategy / Live Predictor).

Sealed-holdout rule (lead decision 12 Sep 20:57; Workstream 3 review 21:35): a holdout_aggregate.json produced before the
model freeze is a dry run (`dry_run_before_freeze: true`, `quotable: false`, `freeze: null`); its numbers are never
displayed. The block is revealed only when the evaluator wrote `quotable: true` AND `freeze` is non-null AND a
`reveal.per_race_written` record exists, and then only `aggregate.forecast`, always labelled "sealed holdout, aggregate only".
Per-race sealed results are never read here (there is no such file until freeze.json exists, and this module never asks).

Hidden-stop and regret rows are shown for development-pool weekends only; a sealed race id is refused.
"""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Optional
from app_v2.services import paths as P
from app_v2.services import asset_repository as A

try:
    import streamlit as st
    _cache = st.cache_data(show_spinner=False)
except Exception:  # pragma: no cover
    def _cache(fn):
        return fn

VAL_DIR = P.OUT_DIR / 'validation'
REGRET_LABEL = 'held-out strategy replay under a post-race reference model'     # evaluation/regret.py LABEL, rendered verbatim
SEALED_LABEL = 'sealed holdout, aggregate only'
SEALED_PENDING = 'sealed: {n} weekends, aggregate revealed after freeze'
REFERENCE_WORDING = 'race-derived pace-loss reference'
DEV_POOL_SPLIT = 'development pool: leave-one-weekend-out inside each season; sealed weekends excluded from every pool'
FILES = dict(ghost='ghost_scorecard.json', live='live_scorecard.json', risk='risk_coverage.json', risk_png='risk_coverage.png', risk_csv='risk_coverage.csv',
             holdout='holdout_aggregate.json', scorecards_md='SCORECARDS.md')


@_cache
def _read_json(path: str, mtime: float) -> dict:
    with open(path) as f:
        return json.load(f)


def _mtime(p: Path) -> float:
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _load(name: str) -> tuple[Optional[dict], A.Asset]:
    p = VAL_DIR / name
    asset = A.resolve(p)
    if not asset.exists:
        return None, asset
    try:
        return _read_json(str(p), _mtime(p)), asset
    except (json.JSONDecodeError, OSError):
        return None, asset


def ghost_scorecard() -> tuple[Optional[dict], A.Asset]:
    return _load(FILES['ghost'])


def live_scorecard() -> tuple[Optional[dict], A.Asset]:
    return _load(FILES['live'])


def risk_coverage() -> tuple[Optional[dict], A.Asset]:
    return _load(FILES['risk'])


def risk_coverage_png() -> A.Asset:
    return A.resolve(VAL_DIR / FILES['risk_png'])


def risk_coverage_csv() -> A.Asset:
    return A.resolve(VAL_DIR / FILES['risk_csv'])


def scorecards_md() -> A.Asset:
    return A.resolve(VAL_DIR / FILES['scorecards_md'])


def hidden_stop(season: int = P.SEASON_OF_FEAT) -> tuple[Optional[dict], A.Asset]:
    return _load(f'hidden_stop_{season}.json')


def regret(season: int = P.SEASON_OF_FEAT) -> tuple[Optional[dict], A.Asset]:
    return _load(f'regret_{season}.json')


def holdout_aggregate() -> tuple[Optional[dict], A.Asset]:
    return _load(FILES['holdout'])


def provenance(data: Optional[dict], asset: A.Asset, name: str = '') -> str:
    """One line of provenance for a footer: file, sha256, sidecar status, generated_at, git sha."""
    rel = name or Path(asset.path).name
    if not asset.exists:
        return f'out/validation/{rel}: missing'
    gen = (data or {}).get('generated_at', '—'); sha = ((data or {}).get('git_sha') or '')[:7] or '—'
    return f'out/validation/{rel} sha256 {asset.short_hash} · {asset.sidecar_status} · generated {gen} · git {sha}'


def sealed_ids() -> list[str]:
    """Race ids of the sealed holdout as Workstream 3 lists them in the scorecard (never read from the manifest here)."""
    g, _ = ghost_scorecard()
    if g and g.get('sealed_excluded'):
        return list(g['sealed_excluded'])
    r, _ = risk_coverage()
    return list((r or {}).get('sealed_excluded') or [])


def is_sealed(event: str, season: int = P.SEASON_OF_FEAT) -> bool:
    return f'{season}_{event}' in set(sealed_ids())


# ---- sealed holdout (gated) ----------------------------------------------------------------------------------------------
def sealed_block() -> dict:
    """The only view of holdout_aggregate.json a page may render.

    revealed=False: `status_text` is the pending sentence and no number from the file is exposed.
    revealed=True: `forecast` is the aggregate.forecast block (MAE Orb v1 vs naive, coverage, calibration, by compound)
    and `label` is the mandatory caption. `weekends` counts (sealed / forecast / abstention) are exposed only when revealed."""
    agg, asset = holdout_aggregate()
    n = len(sealed_ids()) or 6
    out = dict(revealed=False, label=SEALED_LABEL, status_text=SEALED_PENDING.format(n=n), n_weekends=n, forecast=None, weekends=None, reason='', asset=asset,
               generated_at=None, git_sha=None, post_holdout_tuning=None, quotable=None, dry_run_before_freeze=None)
    if agg is None:
        out['reason'] = 'holdout_aggregate.json not present'
        return out
    out.update(quotable=agg.get('quotable'), dry_run_before_freeze=agg.get('dry_run_before_freeze'))
    freeze = agg.get('freeze')
    reveal = agg.get('reveal') or {}
    if agg.get('quotable') is not True:
        out['reason'] = ('holdout_aggregate.json is a dry run before the model freeze (quotable: false); its numbers are not displayed anywhere'
                         if agg.get('dry_run_before_freeze') or agg.get('quotable') is False else 'holdout_aggregate.json carries no quotable: true flag from the evaluator; its numbers are not displayed')
        return out
    if freeze is None:
        out['reason'] = 'holdout_aggregate.json was produced before the model freeze (freeze: null); its numbers are not displayed'
        return out
    if 'per_race_written' not in reveal:
        out['reason'] = 'holdout_aggregate.json carries no reveal record'
        return out
    fc = (agg.get('aggregate') or {}).get('forecast')
    if not fc:
        out['reason'] = 'holdout_aggregate.json has no aggregate.forecast block'
        return out
    out.update(revealed=True, forecast=dict(fc), weekends=dict((agg.get('aggregate') or {}).get('weekends') or {}), status_text=SEALED_LABEL,
               generated_at=agg.get('generated_at'), git_sha=agg.get('git_sha'), post_holdout_tuning=agg.get('post_holdout_tuning'), freeze=dict(freeze) if isinstance(freeze, dict) else freeze)
    return out


# ---- Ghost Strategy scorecard: development-pool cells --------------------------------------------------------------------
def _cell(name: str, blk: dict, source: str, kind: str) -> dict:
    fc = blk.get('forecast') or {}; hs = blk.get('hidden_stop') or {}; hs = hs.get('pooled', hs); rg = ((blk.get('regret') or {}).get('plans') or {}).get('orb') or {}
    mae = (fc.get('mae') or {})
    return dict(cell=name, kind=kind, source=source, status='development pool, leave-one-weekend-out',
                n_weekends=fc.get('n_weekends'), n_compound_weekends=fc.get('n_compound_weekends'), n_issued=fc.get('n_issued'), n_withheld=fc.get('n_withheld'),
                mae=mae.get('orb_v1'), mae_naive=mae.get('naive'), coverage=(fc.get('band_coverage90') or {}).get('all'), wins=fc.get('wins_orb_over_naive'),
                hidden_n=hs.get('n_cases'), hidden_next1=hs.get('next1_mae'), hidden_next1_naive=hs.get('next1_mae_naive'), hidden_cov=hs.get('next1_coverage90'),
                regret_median=rg.get('median'), regret_n=rg.get('n'), note=blk.get('note', ''))


def dev_pool_cells(g: Optional[dict]) -> list[dict]:
    """Cells exactly as Workstream 3 wrote them (by circuit class, weather regime, driver support) plus the pooled development pool."""
    if not g:
        return []
    dp = g.get('development_pool') or {}
    cells = [_cell('development pool, all cells', dp, 'ghost_scorecard · development pool', 'pooled')]
    for k, blk in (dp.get('by_circuit_class') or {}).items():
        cells.append(_cell(f'{k} circuit', blk, f'ghost_scorecard · development pool · by circuit class · {k}', 'circuit'))
    for k, blk in (dp.get('by_weather_regime') or {}).items():
        cells.append(_cell(f'{k.replace("_", " ")} weather', blk, f'ghost_scorecard · development pool · by weather regime · {k}', 'weather'))
    for k, blk in (dp.get('by_driver_support') or {}).items():
        cells.append(_cell(f'driver {k} in a pool race', blk, f'ghost_scorecard · development pool · by driver support · {k}', 'driver'))
    return cells


def dev_pool_headline(g: Optional[dict]) -> Optional[dict]:
    if not g:
        return None
    dp = g.get('development_pool') or {}; fc = dp.get('forecast') or {}; bs = fc.get('bootstrap') or {}; hs = dp.get('hidden_stop') or {}; hp = hs.get('pooled') or {}; hb = hs.get('bootstrap') or {}
    rg = dp.get('regret') or {}; ro = (rg.get('plans') or {}).get('orb') or {}; rn = (rg.get('plans') or {}).get('naive') or {}
    return dict(split=dp.get('split', DEV_POOL_SPLIT), n_weekends=fc.get('n_weekends'), n_compound_weekends=fc.get('n_compound_weekends'), n_issued=fc.get('n_issued'), n_withheld=fc.get('n_withheld'),
                mae=(fc.get('mae') or {}).get('orb_v1'), mae_ci=(bs.get('mae_orb_v1') or {}).get('ci90'), mae_naive=(fc.get('mae') or {}).get('naive'), mae_naive_ci=(bs.get('mae_naive') or {}).get('ci90'),
                coverage=(fc.get('band_coverage90') or {}).get('all'), coverage_ci=(bs.get('band_coverage90') or {}).get('ci90'), p_beats_naive=(bs.get('p_orb_beats_naive') or {}).get('p_bootstrap'),
                calibration=fc.get('calibration') or {}, by_compound=fc.get('by_compound') or {}, abstention=dp.get('abstention_coverage') or fc.get('abstention') or {},
                hidden_n=hp.get('n_cases'), hidden_weekends=hp.get('n_weekends'), hidden_next1=hp.get('next1_mae'), hidden_next1_ci=(hb.get('next1_mae') or {}).get('ci90'), hidden_next1_naive=hp.get('next1_mae_naive'),
                hidden_cum3=hp.get('cum3_mae'), hidden_cum3_naive=hp.get('cum3_mae_naive'), hidden_cum5=hp.get('cum5_mae'), hidden_cum5_naive=hp.get('cum5_mae_naive'),
                hidden_cov1=hp.get('next1_coverage90'), hidden_cov3=hp.get('cum3_coverage90'), hidden_cov5=hp.get('cum5_coverage90'),
                regret_label=rg.get('label', REGRET_LABEL), regret_n=ro.get('n'), regret_median=ro.get('median'), regret_mean=ro.get('mean'), regret_mean_ci=(ro.get('ci90_mean') or {}).get('ci90'),
                regret_p90=ro.get('p90'), regret_within5=ro.get('share_within_5s'), regret_naive_median=rn.get('median'), regret_naive_n=rn.get('n'),
                p_orb_beats_naive_regret=(rg.get('p_orb_beats_naive') or {}).get('p_bootstrap'), p_orb_beats_observed_regret=(rg.get('p_orb_beats_observed') or {}).get('p_bootstrap'),
                plans=rg.get('plans') or {}, wording=g.get('wording') or {}, data_cutoff=g.get('data_cutoff', ''), seasons=g.get('seasons') or [], sealed_excluded=g.get('sealed_excluded') or [])


def rolling_origin(g: Optional[dict]) -> Optional[dict]:
    if not g or not g.get('rolling_origin_2026'):
        return None
    ro = g['rolling_origin_2026']
    return dict(method=ro.get('method', ''), series=list(ro.get('series') or []), pooled=ro.get('pooled') or {}, pooled_from_round_4=ro.get('pooled_from_round_4') or {})


# ---- Live Predictor scorecard ---------------------------------------------------------------------------------------------
def live_headline(l: Optional[dict]) -> Optional[dict]:
    if not l:
        return None
    p = l.get('pooled') or {}; pr = l.get('pooled_as_reported') or {}
    est = lambda k: (p.get(k) or {}).get('estimate', pr.get(k))
    ci = lambda k: (p.get(k) or {}).get('ci90')
    return dict(races=list(l.get('races') or []), source=l.get('source') or {}, note=l.get('note', ''), units=l.get('units') or {},
                next1=est('next1_mae'), next1_ci=ci('next1_mae'), next1_prior=est('next1_mae_prior_only'), next1_prior_ci=ci('next1_mae_prior_only'),
                cum3=est('cum3_mae'), cum3_prior=est('cum3_mae_prior_only'), cum5=est('cum5_mae'), cum5_prior=est('cum5_mae_prior_only'),
                cov1=est('coverage90_next1'), cov1_ci=ci('coverage90_next1'), cov1_prior=est('coverage90_next1_prior_only'), cov3=est('coverage90_next3'),
                cliff5_brier=est('cliff5_brier'), cliff5_brier_ci=ci('cliff5_brier'), cliff5_clim=est('cliff5_brier_climatology'), cliff5_clim_ci=ci('cliff5_brier_climatology'),
                aw_rate=est('aw_detection_rate'), aw_rate_ci=ci('aw_detection_rate'), aw_lead=est('aw_lead_laps_median'), false_alerts=est('aw_false_alert_episodes_per_stint'), reco_change=est('recommendation_change_rate'),
                laps=pr.get('laps'), drivers=pr.get('drivers'), lap_pairs=pr.get('lap_pairs'), ablation=l.get('driver_feedback_ablation') or {}, per_race=l.get('per_race') or {})


# ---- risk-coverage (abstention gate sweep) ---------------------------------------------------------------------------------
def risk_gate_rows(rc: Optional[dict]) -> list[dict]:
    """The production gate and the best-MAE gate exactly as tabulated by Workstream 3 (no re-derivation)."""
    if not rc:
        return []
    out = []
    for name, key in (('production gate (pipeline.py)', 'production_gate'), ('lowest MAE over all cases in the sweep', 'best_mae_all')):
        r = rc.get(key) or {}
        if r:
            out.append(dict(name=name, min_laps=r.get('min_laps'), min_slope=r.get('min_slope'), coverage=r.get('coverage'), mae_issued=r.get('mae_issued'), mae_fallback=r.get('mae_fallback'), mae_all=r.get('mae_all'), mae_naive=r.get('mae_naive'), n_issued=r.get('n_issued'), n_cases=r.get('n_cases'), n_weekends=r.get('n_weekends')))
    return out


# ---- per-weekend hidden-stop and regret (development pool only) ------------------------------------------------------------
def hidden_stop_for(event: str, driver: Optional[str] = None, season: int = P.SEASON_OF_FEAT) -> Optional[dict]:
    """The selected weekend's hidden-stop-response record and the selected driver's own scored stops (values verbatim)."""
    if is_sealed(event, season):
        return None
    h, asset = hidden_stop(season)
    if not h:
        return None
    race_id = f'{season}_{event}'
    pw = (h.get('per_weekend') or {}).get(race_id)
    if pw is None:
        return None
    cases = [c for c in (h.get('cases') or []) if c.get('race_id') == race_id and (driver is None or c.get('driver') == driver)]
    rows = [dict(driver=c.get('driver'), in_lap=c.get('in_lap'), compound_old=c.get('compound_old'), compound_new=c.get('compound_new'), set_status=c.get('set_status'), stop_regime=c.get('stop_regime'),
                 n_post=c.get('n_post'), err1=c.get('err1'), err1_naive=c.get('err1_naive'), cov1=c.get('cov1'), err3=c.get('err3'), err3_naive=c.get('err3_naive'), cov3=c.get('cov3'), err5=c.get('err5'), err5_naive=c.get('err5_naive'), cov5=c.get('cov5'), issued_new=c.get('issued_new')) for c in cases]
    pooled = (h.get('aggregate') or {}).get('pooled') or {}
    return dict(race_id=race_id, n_cases=pw.get('n_cases'), skipped=dict(pw.get('skipped') or {}), weather=pw.get('weather'), cases=rows, split=h.get('split', ''),
                season_pooled=dict(n_cases=pooled.get('n_cases'), n_weekends=pooled.get('n_weekends'), next1_mae=pooled.get('next1_mae'), next1_mae_naive=pooled.get('next1_mae_naive'), next1_coverage90=pooled.get('next1_coverage90'),
                                   cum3_mae=pooled.get('cum3_mae'), cum3_mae_naive=pooled.get('cum3_mae_naive'), cum5_mae=pooled.get('cum5_mae'), cum5_mae_naive=pooled.get('cum5_mae_naive')),
                asset=asset, generated_at=h.get('generated_at'), git_sha=h.get('git_sha'))


def regret_for(event: str, season: int = P.SEASON_OF_FEAT) -> Optional[dict]:
    """The selected weekend's strategy-regret record: four plans and the hindsight oracle under the post-race reference."""
    if is_sealed(event, season):
        return None
    r, asset = regret(season)
    if not r:
        return None
    race_id = f'{season}_{event}'
    w = next((x for x in (r.get('weekends') or []) if x.get('race_id') == race_id), None)
    if w is None:
        return None
    plans = {}
    for name, pl in (w.get('plans') or {}).items():
        plans[name] = dict(plan=pl.get('plan'), stints=list(pl.get('stints') or []), stops=pl.get('stops'), regret=pl.get('regret'), cost=pl.get('cost_under_reference'), unscorable=pl.get('unscorable'), drivers=pl.get('drivers'))
    o = w.get('oracle') or {}
    agg = r.get('aggregate') or {}
    return dict(race_id=race_id, label=w.get('label') or r.get('label') or REGRET_LABEL, plans=plans, oracle=dict(plan=o.get('plan'), stints=list(o.get('stints') or []), stops=o.get('stops'), cost=o.get('cost')),
                pit_loss=w.get('pit_loss'), n_laps=w.get('n_laps'), reference_slopes=dict(w.get('reference_slopes') or {}), pre_race_slopes=dict(w.get('pre_race_slopes') or {}), split=r.get('split', ''),
                season_n=agg.get('n_weekends'), season_plans={k: dict(n=v.get('n'), median=v.get('median'), mean=v.get('mean'), p90=v.get('p90'), within5=v.get('share_within_5s')) for k, v in (agg.get('plans') or {}).items()},
                asset=asset, generated_at=r.get('generated_at'), git_sha=r.get('git_sha'))


# ---- per-season blocks and the scorecard-vs-lock consistency check (ghost_scorecard.json, 21:27 regeneration) -----------
def by_season_rows(g: Optional[dict]) -> list[dict]:
    """development_pool.by_season[<season>].forecast, verbatim: one row per season."""
    if not g:
        return []
    out = []
    for season, blk in sorted(((g.get('development_pool') or {}).get('by_season') or {}).items()):
        fc = blk.get('forecast') or {}; mae = fc.get('mae') or {}; bs = fc.get('bootstrap') or {}
        out.append(dict(season=season, split=blk.get('split', ''), n_weekends=fc.get('n_weekends'), n_compound_weekends=fc.get('n_compound_weekends'), n_issued=fc.get('n_issued'), n_withheld=fc.get('n_withheld'),
                        mae=mae.get('orb_v1'), mae_ci=(bs.get('mae_orb_v1') or {}).get('ci90'), mae_naive=mae.get('naive'), coverage=(fc.get('band_coverage90') or {}).get('all'), wins=fc.get('wins_orb_over_naive'),
                        calibration_r=(fc.get('calibration') or {}).get('r')))
    return out


def lock_consistency(g: Optional[dict]) -> Optional[dict]:
    """development_pool.lock_consistency_2026: Workstream 3's check that the scorecard's 2026 leave-one-weekend-out numbers equal the lock's."""
    lc = ((g or {}).get('development_pool') or {}).get('lock_consistency_2026')
    if not lc:
        return None
    return dict(all_match=lc.get('all_match'), n_compared=lc.get('n_compared'), tolerance=lc.get('tolerance'), note=lc.get('note', ''), lock_generated_at=(lc.get('lock') or {}).get('generated_at'),
                metrics={k: dict(scorecard=v.get('scorecard'), lock=v.get('lock'), match=v.get('match')) for k, v in (lc.get('metrics') or {}).items()})
