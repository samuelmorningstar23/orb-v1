"""Claim audit: wording rules (roadmap v5 9.2) and every quoted number against the lock.

Sources: app_v2 pages / ui / services and live/viewmodel.py (rendered strings), out/talk_track.md, out/THE_CASE.md,
out/ROADMAP_v5.md and the deck text (markitdown over out/Orb_v1_Mentor_Briefing.pptx, slide-numbered).

Wording rules (each hit is a `reword` verdict unless its allowed context is present):
    'ground truth' / 'true degradation'      race estimates are "race-derived pace-loss references"
    'tread'                                   public mode never displays tread; allowed when describing private team data / a missing channel
    'observed race time saved'                the regret table is a held-out strategy replay under a post-race reference
    'finishing position' / 'finish position'  only in frozen-field mode and only as distributions
    'no published method' / 'nobody else'     novelty reads "in the public methods we reviewed, we did not find ..."
    energy price 'constant' / 'the same'      the lock records practice vs race betas that differ (Austria -0.601 vs -0.590)
    'works under any weather'                 never, unless negated
    position claims on the live path          'P5 -> ~P9' rejoin positions are point position claims outside frozen-field mode
Number claims: the figures the deck quotes (MAE 0.137 / 0.023, r 0.20 / 0.78, 28 of 29, 13 of 13, 16 issued, sensitivity range,
Madrid, the strategy replay costs, Hungary, the fallback error, the push share, the liquid ablation) are each mapped to a lock
path (or another artefact), recomputed here and given a verdict: verified | mismatch | exceeds_evidence | unverifiable.

    python evaluation/red_team/claim_audit.py [--out PATH]
Writes evaluation/red_team/claim_evidence_map.json. Exit 0 when nothing needs rewording, 1 otherwise.
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import statistics as S
import sys
from pathlib import Path
from typing import Any, Optional

HERE = Path(__file__).resolve().parent
if str(HERE.parents[1]) not in sys.path:
    sys.path.insert(0, str(HERE.parents[1]))
from evaluation.red_team import PROTO, RT_DIR, LOCK_V1, now_iso, owner_of, read_json, write_json  # noqa: E402

MAP_PATH = RT_DIR / 'claim_evidence_map.json'
DECK = PROTO / 'out' / 'Orb_v1_Mentor_Briefing.pptx'
CHALLENGE_DECK = PROTO / 'out' / 'Orb_v1_ChallengeDay.pdf'
DOC_SOURCES = ('README.md', 'out/talk_track.md', 'out/THE_CASE.md', 'out/ROADMAP_v5.md')
CODE_SOURCES = ('app_v2/pages/*.py', 'app_v2/ui/*.py', 'app_v2/services/*.py', 'live/viewmodel.py', 'decision/optimizer.py')

# (rule id, regex, allowed-context regex (same line / slide) or None, note)
WORDING_RULES = [
    ('ground_truth', r'ground[\s-]truth', None, 'wording rule 9.2: race estimates are "race-derived pace-loss references", never ground truth'),
    ('true_degradation', r'\btrue degradation\b', None, 'no unobserved truth is claimed; say "race-derived reference"'),
    ('tread', r'\btread\b', r'private|team[\s-]only|team data|missing channel|tread_depth|never|no tread|not (?:shown|displayed)', 'public mode never displays physical tread (roadmap 7); allowed only when describing private team data or a missing channel'),
    ('observed_race_time_saved', r'observed race[\s-]?time saved|race time saved', r'never|not', 'the regret table is a held-out strategy replay under a post-race reference model (evaluation/__init__.py wording)'),
    ('finishing_position', r'finish(?:ing)? position', r'frozen[\s_-]field|only in frozen|never|not simulated|no position', 'position claims only in frozen-field mode and only as distributions (9.2)'),
    ('novelty_unqualified', r'no published method|nobody else|no one else|no[\s-]one else|first (?:and only|to deliver)|only (?:system|entry|team) (?:that|to)', r'public methods we reviewed|we did not find|in the (?:public )?(?:methods|repositories) we reviewed|checked \d+ september|public repositories', 'novelty reads "in the public methods we reviewed, we did not find ..." (9.2)'),
    ('energy_price_constant', r'(?:price of lap time|energy price|per megajoule|s/MJ|s per MJ)[^.]{0,120}(?:\bconstant\b|the same|identical|to two decimals)|(?:\bconstant\b|the same|identical)[^.]{0,120}(?:price of lap time|energy price|per megajoule)', r'consistent scale|tight at|within', 'the lock push_diagnostic betas differ Friday vs Sunday (Austria -0.601 vs -0.590, Barcelona -0.578 vs -0.575): "consistent scale" is supportable, "the same to two decimals" is not'),
    ('any_weather', r'works under any weather|under any weather', r'never|not', 'never "it works under any weather" (roadmap 8)'),
    ('live_position_claim', r'P\{[^}]*position_now[^}]*\}|~P\{|projected_rejoin_position|rejoin ~P\d|P\d+ (?:now|→)', r'frozen[\s_-]field', 'a point rejoin position on the Live Predictor / decision board is a position claim outside frozen-field mode; show the observed gap structure without a projected P-number, or label it "not a position forecast"'),
    ('every_number_measured', r'every number on (?:our|the) screens? is measured and scored|computes nothing itself', None, 'the live path computes the posterior and ranked actions in-process (deterministic replay, but not lock numbers) and the Ghost page shows FIXTURE / pending values: say "every number on screen is traceable to the lock, a hashed sidecar or a labelled placeholder"'),
]


def _slides() -> list[tuple[str, str]]:
    """(source label, text) per slide of the deck through markitdown."""
    if not DECK.exists():
        raise FileNotFoundError(f'Required presentation missing: {DECK}')
    try:
        from markitdown import MarkItDown
        text = MarkItDown().convert(str(DECK)).text_content
    except Exception as e:
        raise RuntimeError(f'Cannot audit presentation {DECK.name}: {e}') from e
    parts = re.split(r'<!-- Slide number: (\d+) -->', text)
    out = []
    for i in range(1, len(parts) - 1, 2):
        out.append((f'{DECK.relative_to(PROTO)}#slide-{parts[i]}', parts[i + 1]))
    if not out:
        raise RuntimeError(f'No slides extracted from {DECK.name}')
    return out


def _pdf_pages() -> list[tuple[str, str]]:
    """ChallengeDay is a presentation surface; missing/empty extraction fails loudly."""
    if not CHALLENGE_DECK.exists():
        raise FileNotFoundError(f'Required presentation missing: {CHALLENGE_DECK}')
    from pypdf import PdfReader
    document = PdfReader(CHALLENGE_DECK)
    pages = [(f'{CHALLENGE_DECK.relative_to(PROTO)}#page-{i + 1}', page.extract_text() or '')
             for i, page in enumerate(document.pages)]
    if not pages or any(not text.strip() for _, text in pages):
        raise RuntimeError('ChallengeDay PDF contains a page without auditable text')
    return pages


def load_sources(extra: Optional[list[tuple[str, str]]] = None) -> list[tuple[str, list[tuple[int, str]]]]:
    """[(source, [(line_no, line), ...])]; slides are one 'line' per text line but keep the slide as their source."""
    srcs: list[tuple[str, list[tuple[int, str]]]] = []
    for rel in DOC_SOURCES:
        p = PROTO / rel
        if p.exists():
            srcs.append((rel, list(enumerate(p.read_text(encoding='utf-8').splitlines(), 1))))
    for pat in CODE_SOURCES:
        for p in sorted(PROTO.glob(pat)):
            srcs.append((str(p.relative_to(PROTO)), list(enumerate(p.read_text(encoding='utf-8').splitlines(), 1))))
    for label, text in _slides() + _pdf_pages():
        srcs.append((label, list(enumerate(text.splitlines(), 1))))
    for label, text in (extra or []):
        srcs.append((label, list(enumerate(text.splitlines(), 1))))
    return srcs


def audit_wording(sources: list[tuple[str, list[tuple[int, str]]]]) -> list[dict]:
    flags = []
    for src, lines in sources:
        is_code = src.endswith('.py')
        slide_text = ' '.join(l for _, l in lines) if ('#slide-' in src or '#page-' in src) else ''
        for no, line in lines:
            for rule, pattern, allowed, note in WORDING_RULES:
                if rule == 'live_position_claim' and not is_code:
                    continue
                if is_code and rule in ('novelty_unqualified', 'energy_price_constant'):
                    continue
                for m in re.finditer(pattern, line, flags=re.I):
                    ctx = line if not slide_text else slide_text
                    ok = bool(allowed and re.search(allowed, ctx, flags=re.I))
                    flags.append(dict(rule=rule, source=src, line=no, excerpt=line.strip()[:220], verdict='allowed_with_context' if ok else 'reword', note=note, owner=owner_of(src)))
    return flags


# ---------------------------------------------------------------- number claims
def _fmt(v, d):
    return None if v is None else float(f'{v:.{d}f}')


def number_claims(lock: dict) -> list[dict]:
    v = lock['validation']; rows = lock['validation_rows']; strat = lock['strategy']; live = lock['live']
    wh = [r for r in rows if not r['issued']]; iss = [r for r in rows if r['issued']]
    sens = read_json(PROTO / 'out' / 'sensitivity.json') if (PROTO / 'out' / 'sensitivity.json').exists() else None
    liquid = read_json(PROTO / 'out' / 'liquid.json') if (PROTO / 'out' / 'liquid.json').exists() else None
    claims: list[dict] = []

    def add(cid, claim, pattern, evidence_path, value, verdict, note='', sources=('deck', 'talk_track', 'THE_CASE', 'ROADMAP_v5'), severity='MEDIUM', qualified_by=(), disqualified_by=(),
            counts_only_unqualified=False):
        """`qualified_by`: regexes that must ALL appear in the same READER UNIT (one document line, or one slide) for an
        occurrence to count as stated-with-its-qualification; `disqualified_by`: any match there cancels that.

        `counts_only_unqualified=True` makes the claim a BARE-FORM guard: qualified occurrences are not counted as
        occurrences of it at all (they are listed under `qualified_not_counted`, so the reclassification stays visible),
        and the claim fires the moment the number is printed without its basis. A bare-form guard is paired with a
        separate claim that states the qualified sentence and carries its own evidence path and verdict, so the audit
        never has to record a flagged verdict against a sentence that the evidence does support (C4 rework)."""
        claims.append(dict(id=cid, claim=claim, pattern=pattern, evidence_path=evidence_path, evidence_value=value, verdict=verdict, note=note, search_in=list(sources) + (['README'] if any(k in sources for k in ('deck', 'talk_track', 'THE_CASE')) else []), severity=severity,
                           qualified_by=list(qualified_by), disqualified_by=list(disqualified_by), counts_only_unqualified=bool(counts_only_unqualified)))

    mae_n, mae_c = v['mae_all_with_fallback']['naive'], v['mae_all_with_fallback']['clearstint']
    add('mae_naive_0.137', 'naive MAE 0.137 s/lap', r'0\.137', 'lock.validation.mae_all_with_fallback.naive', mae_n, 'verified' if _fmt(mae_n, 3) == 0.137 else 'mismatch')
    add('mae_orb_0.023', 'Orb v1 MAE 0.023 s/lap (all cases, and issued)', r'0\.023', 'lock.validation.mae_all_with_fallback.clearstint (0.02273) and mae_issued.clearstint (0.02258)', mae_c, 'verified' if _fmt(mae_c, 3) == 0.023 and _fmt(v['mae_issued']['clearstint'], 3) == 0.023 else 'mismatch')
    r_n, r_a = v['calibration']['naive']['r'], v['calibration']['all_with_fallback']['r']
    add('r_naive_0.20', 'correlation with the race 0.20 (naive)', r'\b0\.20?\b', 'lock.validation.calibration.naive.r', r_n, 'verified' if _fmt(r_n, 2) == 0.20 else 'mismatch')
    add('r_orb_0.78', 'correlation 0.78 (Orb v1, all cases)', r'0\.78', 'lock.validation.calibration.all_with_fallback.r', r_a, 'verified' if _fmt(r_a, 2) == 0.78 else 'mismatch')
    add('slope_0.77', 'calibration slope 0.77', r'0\.77', 'lock.validation.calibration.all_with_fallback.slope', v['calibration']['all_with_fallback']['slope'], 'verified' if _fmt(v['calibration']['all_with_fallback']['slope'], 2) == 0.77 else 'mismatch')
    wins = v['wins_clearstint_over_naive']; recount = sum(1 for r in rows if abs(r['err_cs']) < abs(r['err_naive']))
    add('wins_28_of_29', '28 of 29 cases beat the naive line', r'28\s*(?:of|/)\s*29', 'lock.validation.wins_clearstint_over_naive / n_compound_weekends (recounted from validation_rows err_cs vs err_naive)', dict(lock=wins, recount=recount, n=v['n_compound_weekends']),
        'verified' if wins == 28 == recount and v['n_compound_weekends'] == 29 else 'mismatch')
    add('issued_16', '16 issued, 13 withheld', r'\b16 issued|sixteen issued|16 / 13|\b13 withheld|thirteen withheld', 'lock.validation.n_issued / n_withheld', dict(n_issued=v['n_issued'], n_withheld=v['n_withheld']), 'verified' if v['n_issued'] == 16 and v['n_withheld'] == 13 else 'mismatch')
    ci = v['ci90_mae_clearstint_all']
    add('ci_0.016_0.030', '90% bootstrap interval 0.016 to 0.030', r'0\.016 to 0\.030', 'lock.validation.ci90_mae_clearstint_all', ci, 'verified' if _fmt(ci[0], 3) == 0.016 and _fmt(ci[1], 3) == 0.030 else 'mismatch')
    # 13 of 13 low-degradation
    wh_obs = sorted(((r['event'], r['compound'], r['obs']) for r in wh), key=lambda x: -x[2])
    all_obs = sorted(r['obs'] for r in rows)
    rank = {f'{e} {c}': sum(1 for x in all_obs if x > o) + 1 for e, c, o in wh_obs}
    high = [(e, c, o, rank[f'{e} {c}']) for e, c, o in wh_obs if o > S.median(r['obs'] for r in iss)]
    add('withheld_13_of_13_low_deg', '13 of 13 withheld cases were low-degradation races', r'13\s*(?:of|/)\s*13|thirteen (?:times )?out of thirteen|thirteen of thirteen',
        'lock.validation_rows: obs of the 13 withheld rows vs the 29-case distribution',
        dict(withheld_obs_sorted=[(e, c, o) for e, c, o in wh_obs], withheld_median=S.median(o for _, _, o in wh_obs), issued_median=S.median(r['obs'] for r in iss), all_median=S.median(all_obs),
             above_issued_median=[(e, c, o, f'rank {k}/29') for e, c, o, k in high], below_0_05=sum(1 for _, _, o in wh_obs if o < 0.05), below_0_06=sum(1 for _, _, o in wh_obs if o < 0.06),
             fallback_band_covers=sum(1 for r in wh if r['lo'] <= r['obs'] <= r['hi'])),
        'exceeds_evidence' if high else 'verified',
        note=('"low-degradation race" has no definition in the lock; Barcelona HARD (withheld, too few clean laps) degraded at +0.100 s/lap, the 4th highest of all 29 cases, and Zandvoort MEDIUM at +0.073 (7th): '
              'say "withheld compounds degraded at a median 0.028 s/lap in the race (range -0.009 to +0.100); 11 of 13 below 0.06 s/lap; the fallback band covered 9 of 13"'), severity='HIGH')
    # fallback error 0.028 vs 0.082 naive
    push5 = [r for r in wh if r.get('pred_push') is not None]
    fb5 = S.mean(abs(r['err_cs']) for r in push5) if push5 else None; nv5 = S.mean(abs(r['err_naive']) for r in push5) if push5 else None
    fb13 = S.mean(abs(r['err_cs']) for r in wh); nv13 = S.mean(abs(r['err_naive']) for r in wh)
    add('fallback_0.028_vs_naive_0.082', 'fallback error 0.028 s/lap against 0.082 naive (withheld cases)', r'0\.028 s/lap against 0\.082|0\.082 naive',
        'lock.validation.path_b_push_adjusted.mae_fallback (5 withheld cases with a push signal) and validation_rows err_naive / err_cs over the withheld rows',
        dict(mae_fallback_path_b=v['path_b_push_adjusted']['mae_fallback'], n_push_signal=v['path_b_push_adjusted']['n_withheld_with_push_signal'], naive_on_those_5=nv5, fallback_on_those_5=fb5, naive_on_all_13=nv13, fallback_on_all_13=fb13),
        'unverifiable', note='0.028 is the path-B fallback MAE over the 5 withheld cases with a push signal; the naive MAE is 0.068 on those 5 and 0.106 on all 13 withheld: no subset in the lock gives 0.082. Quote a pair from one subset: "0.023 fallback vs 0.106 naive over the 13 withheld cases"')
    # Hungary slide 2 / 4
    hm = next(r for r in rows if r['event'] == 'Hungary' and r['compound'] == 'MEDIUM')
    add('hungary_0.285', 'Hungary medium naive +0.285 s/lap', r'0\.285', 'validation_rows[Hungary,MEDIUM].naive', hm['naive'], 'verified' if _fmt(hm['naive'], 3) == 0.285 else 'mismatch')
    add('hungary_0.042', 'Hungary medium race +0.042', r'0\.042', 'validation_rows[Hungary,MEDIUM].obs', hm['obs'], 'verified' if _fmt(hm['obs'], 3) == 0.042 else 'mismatch')
    add('hungary_0.122', 'Hungary medium cleaned 0.122', r'0\.122', 'validation_rows[Hungary,MEDIUM].clean', hm['clean'], 'verified' if _fmt(hm['clean'], 3) == 0.122 else 'mismatch')
    add('hungary_0.055_after_ratio', 'Hungary medium 0.055 after the learned Sunday ratio 0.45', r'0\.055', 'validation_rows[Hungary,MEDIUM].pred_clearstint (= clean x its own leave-one-weekend-out factor k)',
        dict(pred_clearstint=hm['pred_clearstint'], k_hungary=hm['k'], k_median_medium=v['by_compound']['MEDIUM']['k_median'], clean_x_kmedian=hm['clean'] * v['by_compound']['MEDIUM']['k_median']),
        'mismatch' if _fmt(hm['pred_clearstint'], 3) != 0.055 else 'verified',
        note='slide 4 multiplies by the pooled medium factor 0.45 (0.1216 x 0.4518 = 0.055) but the lock forecast for Hungary uses its own held-out factor 0.474: pred_clearstint = 0.058. Show 0.058 (or say "x 0.47 (Hungary held-out factor)")')
    naive_cost_h = strat['Hungary']['views']['Naive fit']['cost_under_truth_vs_best_s']
    add('hungary_plus_74', 'Hungary naive plan costs +74 s', r'\+74 s', 'lock.strategy.Hungary.views["Naive fit"].cost_under_truth_vs_best_s', naive_cost_h, 'verified' if round(naive_cost_h) == 74 else 'mismatch')
    # transfer factors slide 6
    km = v['by_compound']
    add('factors_0.97_0.45', 'season transfer factor x0.97 soft, x0.45 medium, hard not applied', r'×0\.97|x0\.97|×0\.45|x0\.45', 'lock.validation.by_compound.*.k_median; HARD issued rows k_applied',
        dict(SOFT=km['SOFT']['k_median'], MEDIUM=km['MEDIUM']['k_median'], HARD=km['HARD']['k_median'], hard_issued_applied=[(r['event'], r['k_applied']) for r in iss if r['compound'] == 'HARD']),
        'verified' if _fmt(km['SOFT']['k_median'], 2) == 0.97 and _fmt(km['MEDIUM']['k_median'], 2) == 0.45 and not any(r['k_applied'] for r in iss if r['compound'] == 'HARD') else 'mismatch')
    # sensitivity
    if sens:
        maes = [r['mae'] for r in sens['runs'].values()]
        add('sensitivity_0.021_0.027', 'sensitivity range 0.021 to 0.027', r'0\.021\s*(?:-|to|–)\s*0\.027', 'out/sensitivity.json runs[*].mae (unsigned asset, not in the lock)', dict(min=min(maes), max=max(maes)), 'verified' if _fmt(min(maes), 3) == 0.021 and _fmt(max(maes), 3) == 0.027 else 'mismatch',
            note='out/sensitivity.json carries no .sha256 sidecar and is not a lock block')
        table = {'fuel 0.9 kg/lap': (14, 0.026, 0.74), 'fuel 1.3 kg/lap': (16, 0.023, 0.76), '0.025 s/kg': (14, 0.025, 0.75), '0.035 s/kg': (16, 0.023, 0.78), 'traffic ≤20%': (15, 0.027, 0.59), 'traffic ≤40%': (16, 0.021, 0.79), 'runs ≥4 laps': (15, 0.026, 0.70), 'runs ≥7 laps': (13, 0.027, 0.65)}
        bad = {k: (sens['runs'][k]['issued'], _fmt(sens['runs'][k]['mae'], 3), _fmt(sens['runs'][k]['r'], 2)) for k, want in table.items() if k in sens['runs'] and (sens['runs'][k]['issued'], _fmt(sens['runs'][k]['mae'], 3), _fmt(sens['runs'][k]['r'], 2)) != want}
        add('sensitivity_table', 'deck slide 8 sensitivity table (issued / MAE / r per variant)', r'Fuel prior 0\.9 or 1\.3', 'out/sensitivity.json runs', {k: (sens['runs'][k]['issued'], sens['runs'][k]['mae'], sens['runs'][k]['r']) for k in table if k in sens['runs']}, 'verified' if not bad else 'mismatch', note=f'differences: {bad}' if bad else '')
    # Madrid
    md = live['Madrid']; soft = next(c for c in md['compounds'] if c['compound'] == 'SOFT'); med = next(c for c in md['compounds'] if c['compound'] == 'MEDIUM')
    add('madrid_soft_0.098', 'Madrid soft +0.098 s/lap, band -0.10 to +0.30, 41 clean laps', r'0\.098|\+0\.10 with|−0\.10 to \+0\.30|-0\.10 to \+0\.30', 'lock.live.Madrid.compounds[SOFT]', dict(prediction=soft['prediction'], band90=soft['band90'], n_prac=soft['n_prac']),
        'verified' if _fmt(soft['prediction'], 3) == 0.098 and _fmt(soft['band90'][0], 2) == -0.10 and _fmt(soft['band90'][1], 2) == 0.30 and soft['n_prac'] == 41 else 'mismatch')
    add('madrid_medium_0.028', 'Madrid medium +0.028 withheld, second opinion +0.033, energy +0.48 MJ per lap', r'0\.028 s/lap|\+0\.033|0\.48 MJ', 'lock.live.Madrid.compounds[MEDIUM] (prediction, second_opinion.prediction, energy_trend)',
        dict(prediction=med['prediction'], second_opinion=(med.get('second_opinion') or {}).get('prediction'), energy_trend=med['energy_trend'], issued=med['issued']),
        'verified' if _fmt(med['prediction'], 3) == 0.028 and _fmt((med.get('second_opinion') or {}).get('prediction', 0), 3) == 0.033 and _fmt(med['energy_trend'], 2) == 0.48 and not med['issued'] else 'mismatch')
    ms = strat['Madrid']['views']['Orb v1']
    add('madrid_plan_18_38', 'Madrid plan one stop soft then medium 18 / 38 laps; top of the band says two stops', r'18 / 38|18/38', 'lock.strategy.Madrid.views["Orb v1"] (+ band high plan)', dict(plan=ms['plan'], stints=ms['stints'], band_high=strat['Madrid']['views'].get('Orb v1, band high', {}).get('plan')),
        'verified' if ms['plan'] == 'S-M' and ms['stints'] == [18, 38] and (strat['Madrid']['views'].get('Orb v1, band high', {}).get('plan', '').count('-') == 2) else 'mismatch')
    add('madrid_hard_four_laps', 'Madrid hard: no curve, four clean laps on Friday', r'four clean laps', 'lock.live.Madrid (no HARD compound entry; the clean-lap count is not in the lock)', None, 'unverifiable', note='the lock carries no HARD row for Madrid; the four-lap count must come from the excluded-laps table (out/excluded_Madrid.csv) if it is to be quoted', severity='LOW')
    # strategy replay table
    def cost(ev, view):
        return (strat.get(ev, {}).get('views', {}).get(view) or {}).get('cost_under_truth_vs_best_s')
    table = {'Hungary': ('M-H-H', 74, 'S-M-M', 24, 'S-S-M'), 'Monza': ('M-H', 47, 'S-M', 0, 'S-M'), 'Zandvoort': ('S-M', 155, 'S-S-M', 2, 'S-S-H'), 'Miami': ('M-H-H', 80, 'S-M', 6, 'S-M'), 'Canada': ('S-H', 75, 'S-S-H', 30, 'S-H'), 'Barcelona': ('S-H-H', 0, 'S-H', 55, 'S-H-H')}
    got, bad = {}, []
    for ev, (np_, nc, op, oc, best) in table.items():
        vs = strat[ev]['views']
        got[ev] = dict(naive=(vs['Naive fit']['plan'], vs['Naive fit']['cost_under_truth_vs_best_s']), orb=(vs['Orb v1']['plan'], vs['Orb v1']['cost_under_truth_vs_best_s']), best=vs['Orb v1']['best_under_truth']['plan'])
        if vs['Naive fit']['plan'] != np_ or round(vs['Naive fit']['cost_under_truth_vs_best_s']) != nc or vs['Orb v1']['plan'] != op or round(vs['Orb v1']['cost_under_truth_vs_best_s']) != oc or vs['Orb v1']['best_under_truth']['plan'] != best:
            bad.append(ev)
    add('strategy_table', 'deck slide 9 strategy replay table (six races)', r'Naive plan', 'lock.strategy[event].views["Naive fit" | "Orb v1"].cost_under_truth_vs_best_s and best_under_truth', got, 'verified' if not bad else 'mismatch', note=f'rows differing: {bad}' if bad else '')
    scored = {ev: (cost(ev, 'Naive fit'), cost(ev, 'Orb v1')) for ev in strat if cost(ev, 'Naive fit') is not None and cost(ev, 'Orb v1') is not None}
    beats = [ev for ev, (n, o) in scored.items() if o < n]; loses = [ev for ev, (n, o) in scored.items() if o >= n]
    fmt = {ev: lock['events'][ev].get('format') for ev in scored}
    add('beats_naive_7_of_8', 'beats the naive plan on 7 of 8 (conventional) races; Orb v1 costs 0 to 30 s; naive 47 to 155 s', r'7 of 8|seven of eight|0 to 30|47 to 155',
        'lock.strategy[*].views cost_under_truth_vs_best_s for every scored weekend',
        dict(scored_weekends=len(scored), beats=beats, loses={ev: dict(naive=scored[ev][0], orb=scored[ev][1]) for ev in loses}, orb_cost_range=(min(o for _, o in scored.values()), max(o for _, o in scored.values())),
             naive_cost_range=(min(n for n, _ in scored.values()), max(n for n, _ in scored.values())), formats=fmt),
        'exceeds_evidence', severity='HIGH',
        note=f'the lock scores {len(scored)} weekends: Orb v1 beats naive on {len(beats)} of {len(scored)} and loses on {loses} (Australia naive +14.5 vs Orb +25.1 is a second, undisclosed miss); Orb costs range 0 to 55 s (Barcelona), naive 0 to 155 s; '
             f'Zandvoort, Miami and Canada are sprint weekends in the lock, so "conventional" is wrong too. Say "8 of the 10 scored weekends; the two misses are Barcelona (+55 s) and Australia (+25 s vs +14 s)"')
    # push share
    shares = [((r['clean'] - r['push_adj']) / (r['clean'] - r['obs'])) for r in iss if r.get('push_adj') is not None and abs(r['clean'] - r['obs']) > 1e-9]
    pooled = sum(r['clean'] - r['push_adj'] for r in iss if r.get('push_adj') is not None) / sum(r['clean'] - r['obs'] for r in iss if r.get('push_adj') is not None)
    add('push_share_52_68', 'push profile explains a median 52% of the Friday-to-Sunday gap (68% pooled)', r'52%|68% pooled|about half', 'validation_rows issued: (clean - push_adj) / (clean - obs), median and pooled',
        dict(median_share=S.median(shares), pooled_share=pooled, shares_range=(min(shares), max(shares))), 'unverifiable' if _fmt(S.median(shares), 2) != 0.52 else 'verified',
        note=f'the pooled share reproduces (68%); the per-case median under the natural definition is {S.median(shares):.0%} with shares from {min(shares):.1f} to {max(shares):.1f}: the 52% needs its definition stated or should be dropped ("about two-thirds pooled")')
    pd_ = v['push_diagnostic']
    add('energy_trend_0.10', 'median energy trend +0.10 MJ per lap on withheld compounds, 0.00 on issued', r'\+0\.10\b|0\.10 MJ', 'lock.validation.push_diagnostic.energy_trend_withheld["50%"] / energy_trend_issued["50%"]', dict(withheld=pd_['energy_trend_withheld'], issued=pd_['energy_trend_issued']),
        'verified' if _fmt(pd_['energy_trend_withheld']['50%'], 2) == 0.10 and _fmt(pd_['energy_trend_issued']['50%'], 2) == 0.0 else 'mismatch')
    neg = [(r['event'], r['compound'], r['energy_trend'], r['gate']) for r in wh if r['energy_trend'] is not None and r['energy_trend'] < 0]
    wrong_way = [(r['event'], r['compound'], r['energy_trend']) for r in wh if r['clean'] < 0]
    add('every_withheld_rises', 'energy rises through the run on every withheld compound / the push profile explains every withheld case', r'on every withheld compound|explains every withheld case|every withheld',
        'validation_rows withheld: energy_trend per row', dict(withheld_with_negative_energy_trend=neg, wrong_way_slope_cases=wrong_way, all_wrong_way_positive=all(t > 0 for _, _, t in wrong_way)),
        'exceeds_evidence' if neg else 'verified', severity='HIGH',
        note='4 of the 13 withheld compounds (all withheld for too few clean laps: Barcelona HARD -0.33, Belgium HARD -0.17, Canada SOFT -0.15, Miami SOFT -0.57 MJ per lap) have a falling energy trend; the true statement is the deck slide 5 one: '
             '"where the cleaned slope pointed the wrong way (9 cases), the driver was ramping up in every case"')
    betas = {b['event']: (b['practice'], b['race']) for b in pd_['beta_practice_vs_race']}
    add('beta_same_two_decimals', 'the energy price of lap time is the same Friday and Sunday at Austria and Barcelona to two decimals', r'to two decimals|same on Friday and Sunday', 'lock.validation.push_diagnostic.beta_practice_vs_race',
        dict(Austria=betas.get('Austria'), Barcelona=betas.get('Barcelona')), 'mismatch', severity='HIGH',
        note='Austria -0.601 vs -0.590 (-0.60 vs -0.59), Barcelona -0.578 vs -0.575: consistent within 0.01 s/MJ, not "the same to two decimals"; the deck wording "consistent scale, tight at Austria and Barcelona" is the supportable one')
    # liquid ablation
    if liquid:
        cells = [(ev, c, m['mae_linear'], m['mae_quadratic'], m['mae_linear_cov'], m['mae_liquid'], m['n_heldout_laps']) for ev, d in liquid.items() for c, m in d['by_compound'].items()]
        full = [x for x in cells if all(y is not None for y in x[2:6])]
        no_h = [x for x in full if x[0] != 'Hungary']
        def red(sub, weighted):
            if weighted:
                w = sum(x[6] for x in sub); return 1 - sum(x[4] * x[6] for x in sub) / w / (sum(x[2] * x[6] for x in sub) / w)
            return 1 - S.mean(x[4] for x in sub) / S.mean(x[2] for x in sub)
        wins = sum(1 for x in full if x[5] < min(x[2], x[3], x[4]))
        degenerate = [(x[0], x[1], x[4]) for x in full if x[4] < 1e-6]
        # Four claims, not one (C4 rework). The documents print the qualified sentence, which the evidence DOES support,
        # so it gets its own claim and its own verified verdict; the bare number, the wrong count and the real count are
        # separate claims. Before the split, one claim carried the bare canonical text ("23%; 10 of 31"), a verdict of
        # `unverifiable`, and three occurrences in THE_CASE / talk_track / the deck that were excused as `qualified` -
        # which read as a flagged claim standing in the presentation documents.
        lw_noh, lw_all, mean_all, mean_noh = red(no_h, True), red(full, True), red(full, False), red(no_h, False)
        ev_liquid = dict(reduction_mean_all=mean_all, reduction_lapweighted_all=lw_all, reduction_mean_no_hungary=mean_noh, reduction_lapweighted_no_hungary=lw_noh,
                         liquid_beats_best=f'{wins} of {len(full)}', n_complete_cells=len(full), degenerate_cells=degenerate)
        pct_noh, pct_all, count_str = f'{lw_noh:.0%}', f'{lw_all:.0%}', f'{wins} of {len(full)}'
        basis = (rf'{re.escape(pct_noh)} lap-weighted', r'Hungary', re.escape(count_str))       # the basis the evidence requires, all of it on one line / slide
        wrong_count = rf'\b10 of {len(full)}\b'          # the count an earlier draft printed; it must appear nowhere
        # (a) the sentence the documents actually print, with its basis -- verified against out/liquid.json
        add('liquid_reduction_lapweighted_ex_hungary',
            f'per-lap inputs cut the age-only error by {pct_noh} lap-weighted with the three degenerate Hungary cells excluded ({pct_all} with them); '
            f'the network beat the best baseline in {count_str} cells',
            rf'{re.escape(pct_noh)} lap-weighted[^()]{{0,90}}Hungary[^()]{{0,40}}excluded,? {re.escape(pct_all)} with them',
            'out/liquid.json by_compound mae_linear vs mae_linear_cov (31 complete cells), lap-weighted by n_heldout_laps, Hungary excluded', ev_liquid,
            'verified' if (pct_noh == '23%' and pct_all == '31%' and len(degenerate) == 3 and all(d[0] == 'Hungary' for d in degenerate)) else 'mismatch',
            note=f'reproduces exactly as printed: {pct_noh} lap-weighted over the {len(no_h)} non-Hungary cells, {pct_all} over all {len(full)}. '
                 f'Basis sensitivity, disclosed because the printed basis is the most favourable one: unweighted it is {mean_noh:.0%} (ex Hungary) / {mean_all:.0%} (all). '
                 f'The three Hungary cells are excluded because mae_linear_cov = {degenerate[0][2]:.1e} s/lap on held-out laps is a degenerate fit (the covariate baseline reproduces the target); '
                 f'the sentence says so. The network itself beats the best baseline in only {count_str} cells, which the same sentence states.')
        # (b) the bare number with no basis: counted ONLY where the basis is absent, so it fires the moment someone prints it alone
        add('liquid_bare_reduction_pct_without_basis', f'the liquid ablation reduction stated as a bare "{pct_noh}" with no weighting, no excluded cells and no win count',
            re.escape(pct_noh), 'none: the bare percentage has no evidence path (the lap-weighted ex-Hungary basis does)', ev_liquid, 'unverifiable', severity='HIGH',
            note=f'{pct_noh} is only the lap-weighted reduction with the three degenerate Hungary cells removed; unweighted it is {mean_noh:.0%}, and with Hungary it is {pct_all} (lap-weighted) / {mean_all:.0%} (mean). '
                 f'Stated bare it implies a single measured improvement that does not exist. Say it with the basis, as THE_CASE.md and the talk track do.',
            qualified_by=basis, disqualified_by=(wrong_count,), counts_only_unqualified=True)
        # (c) the wrong count that an earlier draft carried
        add('liquid_beats_best_10_of_31', f'the network beat the best baseline 10 of {len(full)}', wrong_count, 'out/liquid.json: mae_liquid < min(mae_linear, mae_quadratic, mae_linear_cov) per cell', ev_liquid,
            'mismatch' if wins != 10 else 'verified', severity='HIGH', note=f'the real count is {count_str}; "10 of {len(full)}" appears in no current document and must not return')
        # (d) the real count
        add('liquid_beats_best_9_of_31', f'the network beat the best baseline in only {count_str} cells', re.escape(count_str),
            'out/liquid.json: mae_liquid < min(mae_linear, mae_quadratic, mae_linear_cov) per cell', ev_liquid,
            'verified' if wins == 9 and len(full) == 31 else 'mismatch', note=f'{wins} of {len(full)} complete cells; the honest reading of the ablation and the one the documents print')
    # holdout
    man = read_json(PROTO / 'evaluation' / 'holdout' / 'sealed_holdout_manifest.json')
    add('holdout_6', 'sealed holdout: 6 weekends = clamp(round(0.18 x 41), 4, 6): Canada 2023, Bahrain 2024, Monza 2024, Saudi Arabia 2024, Zandvoort 2024, Qatar 2025', r'Canada 2023, Bahrain 2024',
        'evaluation/holdout/sealed_holdout_manifest.json race_ids / eligible_weekends', dict(race_ids=man['race_ids'], eligible=man['eligible_weekends'], count=man['holdout_count']),
        'verified' if man['race_ids'] == ['2023_Canada', '2024_Bahrain', '2024_Monza', '2024_SaudiArabia', '2024_Zandvoort', '2025_Qatar'] and man['holdout_count'] == 6 else 'mismatch')
    # offsets from qualifying
    srcs = {ev: s.get('offsets_source') for ev, s in strat.items()}
    q_only = [ev for ev, s in srcs.items() if s and all('qualifying' in str(x) for x in s.values())]
    add('offsets_from_qualifying', 'compound offsets come from qualifying', r'Offsets from qualifying|from that weekend\'s qualifying|qualifying-based offsets|qualifying offsets', 'lock.strategy[event].offsets_source',
        srcs, 'exceeds_evidence', note=f'the lock sources the offsets from practice medians for most weekends (Monza: practice, 23 / 21 drivers; Madrid HARD: nominal Pirelli-range step); qualifying is used only for the MEDIUM offset at Britain, Canada, Miami and Zandvoort; no weekend has both offsets from qualifying ({q_only}). Say "offsets from practice or qualifying medians, nominal step where implausible"')
    # roadmap illustrative numbers
    add('roadmap_illustrative', 'roadmap section 8 / 10 readouts (0.081 vs 0.061, trend 1.33x, gain 3.8 s, 76%, 31% faster)', r'0\.081|3\.8 seconds|76%|31% faster', 'none: illustrative example readouts, not lock numbers', None, 'unverifiable', severity='LOW',
        note='the roadmap marks these as examples of the screen; they must not be spoken as results', sources=('ROADMAP_v5',))
    add('madrid_timing', 'Madrid anchors as they happened: FP3 refresh landed 18:11 IST (refresh_fp3.log); the qualifying refresh attempted 21:03 found the session not run yet (refresh_q.log) and was scheduled again for 21:32; '
        'the hashed forecast was published 21:03:23 from the FP3 lock (out/forecast_Madrid_2026.json issued_at) and is re-published after the second refresh', r'17:40|21:00|17:30|20:45|05:04|refreshes pending', 'refresh_fp3.log, refresh_q.log, out/forecast_Madrid_2026.json', None, 'mismatch', severity='LOW', note='a stated time that did not happen: 17:40 (FP3; landed 18:11), 21:00 (qualifying; the 21:03 attempt found Q not run, second attempt 21:32), 05:04 / refreshes pending (stale status); say what happened or drop the time', sources=('deck', 'ROADMAP_v5'))
    add('rival_field_none_held_out', 'every number on our screens is measured and scored / the lock file every screen reads from and computes nothing itself', r'measured and scored|computes nothing itself', 'consistency_probe_report.json (46 unhashed live values reproduced in-process; FIXTURE / pending values on the Ghost page)', None, 'exceeds_evidence',
        note='the Live Predictor computes the posterior and ranked actions in-process (deterministic replay of the frozen prior and the hashed race file, but not lock numbers) and the Ghost page shows labelled FIXTURE / pending values: say "every number on screen traces to the lock, a hashed sidecar or a labelled placeholder"')
    return claims


PRESENTATION_KINDS = ('deck', 'talk_track', 'THE_CASE', 'README')      # what is said on stage; ROADMAP_v5 is a build contract, not a claim surface
BLOCKING_VERDICTS = ('mismatch', 'exceeds_evidence', 'unverifiable')


def source_kind(src: str) -> str:
    if src == 'README.md':
        return 'README'
    return 'deck' if ('#slide-' in src or '#page-' in src) else ('talk_track' if 'talk_track' in src else ('THE_CASE' if 'THE_CASE' in src else ('ROADMAP_v5' if 'ROADMAP' in src else 'code')))


def locate(claims: list[dict], sources: list[tuple[str, list[tuple[int, str]]]]) -> None:
    """Stamp each claim with where it occurs and whether each occurrence carries its basis.

    The qualification scope is the READER UNIT: one line of a document (a sentence a reader takes whole) or one slide of
    the deck. It used to be the whole document, which let a caveat anywhere in THE_CASE.md qualify a bare number twenty
    lines away; the tighter scope is what the gate test already re-checked by re-reading the cited line (C4 rework)."""
    for c in claims:
        counted, suppressed = [], []
        quals, disquals = c.get('qualified_by') or [], c.get('disqualified_by') or []
        only_unqualified = bool(c.get('counts_only_unqualified'))
        for src, lines in sources:
            kind = source_kind(src)
            if kind not in c['search_in']:
                continue
            slide_text = ' '.join(l for _, l in lines) if ('#slide-' in src or '#page-' in src) else None
            for no, line in lines:
                if not re.search(c['pattern'], line):
                    continue
                def _ok(text: str) -> bool:
                    return bool(quals) and all(re.search(q, text, flags=re.I) for q in quals) and not any(re.search(d, text, flags=re.I) for d in disquals)
                same_line = _ok(line)
                qualified = same_line or (slide_text is not None and _ok(slide_text))
                rec = dict(source=src, line=no, excerpt=line.strip()[:200], kind=kind, qualified=qualified, qualified_same_line=same_line)
                (suppressed if (only_unqualified and qualified) else counted).append(rec)
        c['found_in'] = counted[:12]
        c['n_occurrences'] = len(counted)
        c['n_occurrences_unqualified'] = sum(1 for w in counted if not w['qualified'])
        c['n_presentation_occurrences'] = sum(1 for w in counted if w['kind'] in PRESENTATION_KINDS)       # the C4 criterion's quantity
        c['n_presentation_unqualified'] = sum(1 for w in counted if not w['qualified'] and w['kind'] in PRESENTATION_KINDS)
        c['n_presentation_qualified'] = sum(1 for w in counted if w['qualified'] and w['kind'] in PRESENTATION_KINDS)
        # a bare-form guard does not count its qualified occurrences, but it records them, so the reclassification is auditable
        c['qualified_not_counted'] = suppressed[:12]
        c['n_qualified_not_counted'] = len(suppressed)
        c['owner'] = 'lead'


def run(extra_sources: Optional[list[tuple[str, str]]] = None, out: Path | str | None = MAP_PATH) -> dict:
    lock = read_json(LOCK_V1)
    sources = load_sources(extra_sources)
    wording = audit_wording(sources)
    claims = number_claims(lock)
    locate(claims, sources)
    n_reword = sum(1 for w in wording if w['verdict'] == 'reword')
    verdicts = {}
    for c in claims:
        verdicts[c['verdict']] = verdicts.get(c['verdict'], 0) + 1
    # C4 acceptance, as written: NO claim whose verdict is mismatch / exceeds_evidence / unverifiable may occur at all in
    # THE_CASE.md, talk_track.md or the pptx -- qualified or not. (C3 ignored `unverifiable` and counted ROADMAP_v5; the
    # C4 rework dropped the earlier "unqualified only" relaxation: a sentence the evidence supports is now its own claim
    # with its own verified verdict, so the gate never has to excuse a flagged one. `qualified_in_presentation` stays as
    # a disclosure of every occurrence a bare-form guard did not count.)
    must_fix = [c for c in claims if c['verdict'] in BLOCKING_VERDICTS and c['n_presentation_occurrences'] > 0]
    qualified = [dict(id=c['id'], verdict=c['verdict'], n=c['n_presentation_qualified'] + sum(1 for w in c['qualified_not_counted'] if w['kind'] in PRESENTATION_KINDS),
                      counted=c['n_presentation_qualified'], not_counted=sum(1 for w in c['qualified_not_counted'] if w['kind'] in PRESENTATION_KINDS), qualified_by=c['qualified_by'],
                      where=[f"{w['source']}:{w['line']}" for w in (c['found_in'] + c['qualified_not_counted']) if w['qualified'] and w['kind'] in PRESENTATION_KINDS])
                 for c in claims if (c['n_presentation_qualified'] + sum(1 for w in c['qualified_not_counted'] if w['kind'] in PRESENTATION_KINDS)) > 0]
    rep = dict(generated_at=now_iso(), sources=[s for s, _ in sources], wording_rules=[dict(rule=r, pattern=p, allowed_context=a, note=n) for r, p, a, n in WORDING_RULES],
               summary=dict(wording_hits=len(wording), reword=n_reword, allowed_with_context=len(wording) - n_reword, number_claims=len(claims), verdicts=verdicts, must_reword_before_presentation=[c['id'] for c in must_fix], qualified_in_presentation=qualified),
               wording_flags=wording, claims=claims)
    rep['exit_code'] = 0 if (n_reword == 0 and not must_fix) else 1
    if out:
        write_json(out, rep)
    return rep


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=str(MAP_PATH))
    a = ap.parse_args(argv)
    rep = run(out=a.out)
    s = rep['summary']
    print(f"claim audit: {s['wording_hits']} wording hits ({s['reword']} to reword), {s['number_claims']} number claims {s['verdicts']} -> exit {rep['exit_code']}")
    for w in rep['wording_flags']:
        if w['verdict'] == 'reword':
            print(f"  REWORD [{w['rule']}] {w['source']}:{w['line']}: {w['excerpt'][:110]}")
    for c in rep['claims']:
        if c['verdict'] != 'verified':
            print(f"  {c['verdict'].upper():<16} {c['id']:<28} ({c['n_occurrences']} occurrences) {c['note'][:150]}")
    print(f"map: {a.out}")
    return rep['exit_code']


if __name__ == '__main__':
    sys.exit(main())
