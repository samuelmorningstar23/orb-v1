"""Consolidated red-team report: evaluation/red_team/red_team_report.json and .md, the file the checkpoint
runner (build_control.py) copies into checkpoints/Cn/red_team_report.json.

Per check: consistency probe, leakage audit, identity checks, claim audit, the tests/red_team acceptance suite, the
hashed-forecast leakage audit (out/forecast_<event>_2026.json must contain only practice-, qualifying- and rule-derived
inputs, no race data, and must point at the current lock while the event is prospective), forecast-hash provenance across
the on-disk sidecars, the Madrid anchors stated in the documents against what the logs record, and the blocking list.
Plus the wording flags still outstanding with an owner, counts, and a one-paragraph verdict for the next checkpoint.

    python -m evaluation.red_team.build_report [--event Madrid] [--rerun leakage,claims,identity,probe] [--skip-tests] [--out PATH]

Default re-runs: leakage audit and claim audit (seconds); identity checks and the consistency probe are read from their
last report unless named in --rerun (minutes). Exit 0 when nothing blocks and no check FAILs, 1 otherwise."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from evaluation.red_team import PROTO, RT_DIR, LOCK_V1, LOCK_V2, now_iso, read_json, write_json

REPORT_JSON = RT_DIR / 'red_team_report.json'
REPORT_MD = RT_DIR / 'red_team_report.md'
POST_RACE_KEYS = {'obs', 'obs_se', 'obs_push', 'n_race', 'ratio', 'z', 'err_naive', 'err_clean', 'err_cs', 'err_push', 'cost_under_truth_vs_best_s', 'best_under_truth', 'observed', 'observed_se', 'race', 'race_reference'}
PRE_RACE_SESSIONS = {'FP1', 'FP2', 'FP3', 'Q', 'S', 'SQ'}
TIME_RE = re.compile(r'\b([01]?\d|2[0-3]):[0-5]\d\b')
ANCHOR_CTX_RE = re.compile(r'refresh|qualif|FP3|hash|publish|forecast|landed|pending', re.I)


# ---------------------------------------------------------------- inputs
def _report(name: str) -> Optional[dict]:
    p = RT_DIR / name
    return read_json(p) if p.exists() else None


def run_or_load(rerun: set[str]) -> dict[str, Optional[dict]]:
    out: dict[str, Optional[dict]] = {}
    if 'leakage' in rerun:
        from evaluation.red_team import leakage_audit
        out['leakage'] = leakage_audit.run()
    else:
        out['leakage'] = _report('leakage_audit_report.json')
    if 'claims' in rerun:
        from evaluation.red_team import claim_audit
        out['claims'] = claim_audit.run()
    else:
        out['claims'] = _report('claim_evidence_map.json')
    if 'identity' in rerun:
        from evaluation.red_team import identity_checks
        out['identity'] = identity_checks.run()
    else:
        out['identity'] = _report('identity_checks_report.json')
    if 'probe' in rerun:
        from evaluation.red_team import consistency_probe
        out['probe'] = consistency_probe.run()
    else:
        out['probe'] = _report('consistency_probe_report.json')
    return out


def run_acceptance_suite() -> dict:
    """pytest tests/red_team with a junit file: counts and the names/messages of anything not green."""
    with tempfile.TemporaryDirectory() as td:
        junit = Path(td) / 'red_team.xml'
        cmd = [sys.executable, '-m', 'pytest', 'tests/red_team', '-q', '-p', 'no:cacheprovider', f'--junitxml={junit}']
        res = subprocess.run(cmd, cwd=str(PROTO), capture_output=True, text=True, timeout=600)
        counts = dict(passed=0, failed=0, errors=0, skipped=0, xfailed=0, xpassed=0)
        not_green = []
        if junit.exists():
            for tc in ET.parse(junit).getroot().iter('testcase'):
                name = f"{tc.get('classname', '')}::{tc.get('name')}"
                fail, err, skip = tc.find('failure'), tc.find('error'), tc.find('skipped')
                if fail is not None:
                    counts['failed'] += 1; not_green.append(dict(test=name, status='FAILED', message=(fail.get('message') or '')[:600]))
                elif err is not None:
                    counts['errors'] += 1; not_green.append(dict(test=name, status='ERROR', message=(err.get('message') or '')[:600]))
                elif skip is not None:
                    if (skip.get('type') or '') == 'pytest.xfail':
                        counts['xfailed'] += 1; not_green.append(dict(test=name, status='XFAIL (documented defect)', message=(skip.get('message') or '')[:400]))
                    else:
                        counts['skipped'] += 1; not_green.append(dict(test=name, status='SKIPPED', message=(skip.get('message') or '')[:300]))
                else:
                    counts['passed'] += 1
        m = re.search(r'in ([\d.]+)s', res.stdout)
        status = 'PASS' if res.returncode == 0 else 'FAIL'
        return dict(status=status, command=' '.join(cmd[:-1]), returncode=res.returncode, seconds=float(m.group(1)) if m else None, counts=counts, not_green=not_green,
                    summary_line=(res.stdout.strip().splitlines() or [''])[-1][:200])


# ---------------------------------------------------------------- hashed forecast audit
def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _walk(o, path='$'):
    if isinstance(o, dict):
        for k, v in o.items():
            yield f'{path}.{k}', k, v
            yield from _walk(v, f'{path}.{k}')
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, f'{path}[{i}]')


def forecast_audit(event: str = 'Madrid') -> dict:
    """The published pre-race forecast: practice / qualifying / rule inputs only, numbers equal the lock, pointers resolve."""
    fp = PROTO / 'out' / f'forecast_{event}_2026.json'
    if not fp.exists():
        return dict(status='SKIP', note=f'{fp.relative_to(PROTO)} not published yet')
    fc = read_json(fp)
    lock = read_json(LOCK_V1)
    v2 = read_json(LOCK_V2) if LOCK_V2.exists() else {}
    problems, notes = [], []
    live = (lock.get('live') or {}).get(event)
    strat = (lock.get('strategy') or {}).get(event) or {}
    if not live:
        return dict(status='FAIL', problems=[f'lock.live has no {event} block'])
    # 1. no race data: keys, sessions, and the event's own race meta
    leaked = sorted({k for _, k, _ in _walk(fc) if k in POST_RACE_KEYS})
    if leaked:
        problems.append(f'post-race keys inside the forecast: {leaked}')
    sess = set(fc.get('sessions_used') or [])
    if not sess or not sess <= PRE_RACE_SESSIONS or 'R' in sess:
        problems.append(f'sessions_used is not a pre-race set: {sorted(sess)}')
    if live['meta'].get('race') not in (None, {}) or live['meta'].get('completed'):
        problems.append('the lock live block for the event already carries race data')
    # 2. every compound number equals the lock live block (practice-derived); every strategy number equals the lock strategy block
    by = {c['compound']: c for c in live['compounds']}
    for c in fc.get('compounds', []):
        L = by.get(c['compound'])
        if L is None:
            problems.append(f"{c['compound']}: not in the lock live block"); continue
        if c['prediction_s_per_lap'] != round(L['prediction'], 4) or c['band90'] != [round(b, 4) for b in L['band90']]:
            problems.append(f"{c['compound']}: prediction / band differ from the lock ({c['prediction_s_per_lap']} {c['band90']} vs {round(L['prediction'], 4)} {[round(b, 4) for b in L['band90']]})")
        if (c['issued'], c['gate'], c['basis'], c['clean_practice_laps']) != (L['issued'], L['gate'], L['basis'], L['n_prac']):
            problems.append(f"{c['compound']}: issued / gate / basis / clean laps differ from the lock")
        so = c.get('second_opinion'); Lso = (L.get('second_opinion') or {}).get('prediction') if isinstance(L.get('second_opinion'), dict) else L.get('second_opinion')
        if so is not None and Lso is not None and so != round(Lso, 4):
            problems.append(f"{c['compound']}: second opinion differs from the lock")
    st = fc.get('strategy') or {}
    plan = (strat.get('views') or {}).get('Orb v1') or {}
    if st.get('central', {}).get('plan') != plan.get('plan') or st.get('central', {}).get('stints') != plan.get('stints'):
        problems.append(f"central plan {st.get('central', {}).get('plan')} {st.get('central', {}).get('stints')} differs from the lock {plan.get('plan')} {plan.get('stints')}")
    if st.get('offsets_s') != strat.get('offsets') or st.get('pit_loss_s') != strat.get('pit_loss') or st.get('race_laps') != strat.get('n_laps'):
        problems.append('offsets / pit loss / race laps differ from the lock strategy block')
    for view in ('Orb v1', 'Orb v1, band low', 'Orb v1, band high'):
        if 'cost_under_truth_vs_best_s' in ((strat.get('views') or {}).get(view) or {}):
            problems.append(f'lock strategy view {view!r} carries a race-scored cost for a prospective event')
    notes.append('offsets and pit loss are pre-race inputs: ' + '; '.join(f'{k}: {v}' for k, v in (strat.get('offsets_source') or {}).items()) + f"; pit loss {strat.get('pit_loss')} s (stated standard)")
    notes.append(f"clean practice laps {live['meta'].get('practice_laps_clean')} of {live['meta'].get('practice_laps_total')} over {live['meta'].get('sessions')}; rain in practice {live['meta'].get('rain')}")
    # 3. integrity and pointers
    side = PROTO / 'out' / f'forecast_{event}_2026.sha256'
    if side.exists():
        rec = side.read_text().split()
        if not rec or rec[0] != _sha(fp):
            problems.append('JSON sha256 does not match the .sha256 sidecar (edited after publication?)')
        pdf = PROTO / 'out' / f'forecast_{event}_2026.pdf'
        if pdf.exists() and len(rec) >= 3 and rec[2] != _sha(pdf):
            problems.append('PDF sha256 does not match the .sha256 sidecar')
    else:
        problems.append('no .sha256 sidecar')
    prospective = not lock['events'].get(event, {}).get('completed') and ((v2.get('pre_race_forecast') or {}).get('events', {}).get(event, {}).get('status') == 'prospective')
    pointers = dict(lock_v2_forecast_hash=fc.get('lock_v2_forecast_hash') == (v2.get('shared') or {}).get('forecast_hash'),
                    lock_sha256=fc.get('lock_sha256') == _sha(LOCK_V1), lock_v2_sha256=(fc.get('lock_v2_sha256') == _sha(LOCK_V2)) if LOCK_V2.exists() else None)
    if prospective and not all(v for v in pointers.values() if v is not None):
        problems.append(f"the published forecast points at an earlier lock build ({ {k: v for k, v in pointers.items() if not v} }); issued {fc.get('issued_at')} from lock {fc.get('lock_generated_at')}, current lock {lock.get('generated_at')}: re-run build_forecast.py after the last pre-race refresh")
    return dict(status='PASS' if not problems else 'FAIL', file=str(fp.relative_to(PROTO)), issued_at=fc.get('issued_at'), lock_generated_at=fc.get('lock_generated_at'), sessions_used=sorted(sess),
                current_lock_generated_at=lock.get('generated_at'), prospective=prospective, pointers_resolve=pointers, json_sha256=_sha(fp), problems=problems, notes=notes,
                compounds=[dict(compound=c['compound'], prediction=c['prediction_s_per_lap'], band90=c['band90'], issued=c['issued'], clean_practice_laps=c['clean_practice_laps']) for c in fc.get('compounds', [])],
                central_plan=st.get('central'))


# ---------------------------------------------------------------- forecast-hash provenance on disk
def hash_provenance(leakage: Optional[dict]) -> dict:
    v2 = read_json(LOCK_V2) if LOCK_V2.exists() else {}
    h = (v2.get('shared') or {}).get('forecast_hash')
    stale, agree = [], []
    chk = (leakage or {}).get('checks') or {}
    src = (chk.get('one_forecast_hash') or chk.get('forecast_hash') or {}).get('sources') or []
    for s in src:
        (agree if s.get('agrees') else stale).append(f"{s.get('source')}: {str(s.get('hash'))[7:15]}")
    proof = None
    try:
        import copy
        from schemas.lock_v2 import compute_forecast_hash
        b = copy.deepcopy(v2['pre_race_forecast'])
        for ev in b['events'].values():
            ev['data_cutoff'] = '2000-01-01T00:00:00'
        proof = dict(hash_with_data_cutoff_reset=compute_forecast_hash(b), equals_lock=compute_forecast_hash(b) == h,
                     note='if unequal, the hash depends on the per-event data_cutoff stamp (build time), not only on the forecast numbers')
    except Exception as e:      # pragma: no cover
        proof = dict(error=repr(e))
    runtime_ok = all(s.get('agrees') for s in src if any(t in str(s.get('source')) for t in ('compute_forecast_hash', 'ProviderA', 'LockView', 'load_priors')))
    return dict(status='PASS' if not stale else ('WARN' if runtime_ok else 'FAIL'), lock_v2_forecast_hash=h, runtime_readers_agree=runtime_ok, agree=agree, stale_sidecars=stale, content_only_proof=proof,
                note='runtime readers (live.priors, counterfactual.provider, LockView, recomputation) are what the screens render; stale entries are provenance pointers inside on-disk sidecars written under an earlier lock build')


# ---------------------------------------------------------------- Madrid anchors
def _log_facts() -> dict:
    facts: dict[str, Any] = {}
    fp3 = PROTO / 'refresh_fp3.log'
    if fp3.exists():
        txt = fp3.read_text(errors='replace')
        m = re.search(r'lock rebuilt: \w+ \w+ +\d+ (\d\d:\d\d):\d\d', txt)
        facts['fp3_refresh_landed'] = m.group(1) if m else None
    q = PROTO / 'refresh_q.log'
    if q.exists():
        txt = q.read_text(errors='replace')
        attempts = re.findall(r'== Q refresh.*?start \w+ \w+ +\d+ (\d\d:\d\d):\d\d', txt)
        facts['qualifying_refresh_attempts'] = attempts
        facts['qualifying_not_run_at'] = [a for a, blk in zip(attempts, re.split(r'== Q refresh.*?start', txt)[1:]) if 'Q: not run yet' in blk]
        facts['qualifying_imported_at'] = [a for a, blk in zip(attempts, re.split(r'== Q refresh.*?start', txt)[1:]) if re.search(r'Madrid Q: \d+ laps', blk)]
        facts['forecast_published_at'] = [a for a, blk in zip(attempts, re.split(r'== Q refresh.*?start', txt)[1:]) if 'published forecast_' in blk]
    fc = PROTO / 'out' / 'forecast_Madrid_2026.json'
    if fc.exists():
        d = read_json(fc)
        facts['forecast_issued_at'] = d.get('issued_at'); facts['forecast_sessions'] = d.get('sessions_used'); facts['forecast_lock_generated_at'] = d.get('lock_generated_at')
    return facts


def _deck_slides() -> list[tuple[str, str]]:
    deck = PROTO / 'out' / 'Orb_v1_Mentor_Briefing.pptx'
    if not deck.exists():
        return []
    try:
        from markitdown import MarkItDown
        text = MarkItDown().convert(str(deck)).text_content
    except Exception as e:
        return [('out/Orb_v1_Mentor_Briefing.pptx', f'(markitdown failed: {e!r})')]
    parts = re.split(r'<!-- Slide number: (\d+) -->', text)
    return [(f'out/Orb_v1_Mentor_Briefing.pptx#slide-{parts[i]}', ' '.join(parts[i + 1].split())) for i in range(1, len(parts) - 1, 2)]


def madrid_anchors() -> dict:
    facts = _log_facts()
    happened = set(filter(None, [facts.get('fp3_refresh_landed')] + list(facts.get('qualifying_refresh_attempts') or []) + list(facts.get('forecast_published_at') or [])))
    if facts.get('forecast_issued_at'):
        happened.add(facts['forecast_issued_at'][11:16])
    docs = [PROTO / 'out' / 'talk_track.md', PROTO / 'out' / 'THE_CASE.md', PROTO / 'deck_src' / 'build_deck.js', PROTO / 'build_case.py', PROTO / 'build_manual.py', PROTO / 'build_deck_v5.py']
    stated = []
    sources: list[tuple[str, list[tuple[int, str]]]] = [(str(p.relative_to(PROTO)), list(enumerate(p.read_text(errors='replace').splitlines(), 1))) for p in docs if p.exists()]
    sources += [(label, [(1, text)]) for label, text in _deck_slides()]
    for label, lines in sources:
        for no, line in lines:
            if not ANCHOR_CTX_RE.search(line) or 'Madrid' not in line and 'FP3' not in line and 'qualif' not in line.lower():
                continue
            for m in TIME_RE.finditer(line):
                t = m.group(0).zfill(5)
                before = line[max(0, m.start() - 45):m.start()].lower()
                after = line[m.end():m.end() + 45].lower()
                ctx = line[max(0, m.start() - 60):m.end() + 40].strip()
                # a claim about what happened: 'FP3 refresh landed 18:11', 'qualifying refresh 21:00', '21:00. Madrid qualifying lands',
                # 'published 21:03'; session windows ('FP3 runs 16:00 to 17:00'), race start and slot plans are schedule, not claims
                claim = bool(re.search(r'(refresh\w*|landed|publish\w*|hashed|re-issued?)[^.;]{0,30}$', before)) or bool(re.search(r'^\W{0,3}(madrid )?(qualifying|fp3)? ?(lands|refresh)', after))
                if not claim or t == '18:30':
                    continue
                verdict = 'consistent' if t in happened else 'stale'
                stated.append(dict(document=label, line=no, time=t, verdict=verdict, context=ctx[:160]))
            if 'refreshes pending' in line and 'FP3' in line:
                stated.append(dict(document=label, line=no, time=None, verdict='stale', context=line.strip()[:160]))
    stale = [s for s in stated if s['verdict'] == 'stale']
    return dict(status='PASS' if not stale else 'WARN', facts=facts, stated=stated, stale=stale,
                reality=(f"FP3 refresh landed {facts.get('fp3_refresh_landed')} IST; qualifying refresh attempts {facts.get('qualifying_refresh_attempts')} "
                         f"(session not run yet at {facts.get('qualifying_not_run_at')}, imported at {facts.get('qualifying_imported_at')}); hashed forecast published at "
                         f"{facts.get('forecast_published_at')} (current file issued {facts.get('forecast_issued_at')} from sessions {facts.get('forecast_sessions')})"))


# ---------------------------------------------------------------- wording flags outstanding
def _unqualified_hits(c: dict) -> list[dict]:
    """Occurrences of a flagged claim on a PRESENTATION surface that do not carry the qualification its evidence
    requires. claim_audit stamps `qualified` / `kind` per occurrence (C4); for an older map without those fields
    every occurrence counts, which is the pre-C4 behaviour."""
    found = c.get('found_in') or []
    if not found or 'qualified' not in found[0]:
        return list(found)
    return [f for f in found if not f.get('qualified') and f.get('kind') in ('deck', 'talk_track', 'THE_CASE')]


def wording_outstanding(claims: Optional[dict]) -> list[dict]:
    out = []
    if not claims:
        return out
    for w in claims.get('wording_flags', []):
        if w.get('verdict') == 'reword':
            out.append(dict(kind='wording', rule=w['rule'], source=f"{w['source']}:{w.get('line')}", excerpt=(w.get('excerpt') or '')[:140], owner=w.get('owner'), note=(w.get('note') or '')[:200]))
    for c in claims.get('claims', []):
        # C4: `unverifiable` counts too (it did not at C3), but only where the claim is stated WITHOUT its qualification.
        if c.get('verdict') in ('mismatch', 'exceeds_evidence', 'unverifiable'):
            for f in _unqualified_hits(c):
                out.append(dict(kind='number_claim', rule=c['id'], source=f"{f.get('source')}:{f.get('line')}", excerpt=(f.get('excerpt') or '')[:140], owner=c.get('owner', 'lead'), note=(c.get('note') or '')[:240], verdict=c['verdict']))
    return out


# ---------------------------------------------------------------- consolidation
def _probe_summary(probe: Optional[dict]) -> dict:
    if not probe:
        return dict(status='SKIP', note='no consistency_probe_report.json')
    s = probe.get('summary') or {}
    failing = [dict(route=r['route'], mismatches=len(r.get('mismatches') or []), example=(r.get('mismatches') or [{}])[0].get('shown')) for r in probe.get('routes', []) if r.get('mismatches')]
    return dict(status='PASS' if probe.get('exit_code') == 0 else 'FAIL', generated_at=probe.get('generated_at'), exit_code=probe.get('exit_code'), counts=s, failing_routes=failing, notes=probe.get('notes'))


def _leakage_summary(leak: Optional[dict]) -> dict:
    if not leak:
        return dict(status='SKIP', note='no leakage_audit_report.json')
    checks = leak.get('checks') or {}
    return dict(status=leak.get('status'), generated_at=leak.get('generated_at'), per_check={k: (v.get('status') if isinstance(v, dict) else None) for k, v in checks.items()},
                future_read=dict(laps=(checks.get('future_read') or {}).get('laps_processed'), feed_calls=(checks.get('future_read') or {}).get('feed_calls'), violations=(checks.get('future_read') or {}).get('violations')),
                self_test_inject=(checks.get('future_read_inject') or checks.get('self_test') or {}).get('status'))


def _identity_summary(ident: Optional[dict]) -> dict:
    if not ident:
        return dict(status='SKIP', note='no identity_checks_report.json')
    fails = [c['check'] + (f" ({c.get('event')} {c.get('driver')})" if c.get('event') else '') for c in ident.get('checks', []) if c.get('status') != 'PASS']
    return dict(status=ident.get('status'), generated_at=ident.get('generated_at'), counts=ident.get('summary'), failing=fails)


def _claims_summary(claims: Optional[dict]) -> dict:
    if not claims:
        return dict(status='SKIP', note='no claim_evidence_map.json')
    s = claims.get('summary') or {}
    survivors = [dict(id=c['id'], verdict=c['verdict'], where=[f"{f.get('source')}:{f.get('line')}" for f in _unqualified_hits(c)][:4], note=(c.get('note') or '')[:200])
                 for c in claims.get('claims', []) if c.get('verdict') in ('mismatch', 'exceeds_evidence', 'unverifiable') and _unqualified_hits(c)]
    qualified = s.get('qualified_in_presentation') or []
    return dict(status='PASS' if claims.get('exit_code') == 0 else 'WARN', generated_at=claims.get('generated_at'), counts=s, survivors=survivors, qualified_in_presentation=qualified,
                note='WARN, not FAIL: wording is a presentation gate (roadmap 9.2), not a 14.3 stop-the-line condition unless a claim exceeds the selected support, fidelity or sensor mode on a screen')


def verdict(checks: dict, blocking: dict) -> tuple[str, str]:
    open_issues = blocking.get('issues') or []
    fails = [k for k, v in checks.items() if v.get('status') == 'FAIL']
    warns = [k for k, v in checks.items() if v.get('status') == 'WARN']
    if open_issues:
        return 'HOLD', f"{len(open_issues)} open stop-the-line issue(s): {[i.get('id') for i in open_issues]}."
    if fails:
        dec = 'GO_WITH_REASSIGNMENT'
    elif warns:
        dec = 'GO_WITH_REASSIGNMENT' if any(k in warns for k in ('hash_provenance',)) else 'GO'
    else:
        dec = 'GO'
    return dec, ''


def build(event: str = 'Madrid', rerun: Optional[set[str]] = None, skip_tests: bool = False, out: Path | str | None = REPORT_JSON) -> dict:
    rerun = rerun if rerun is not None else {'leakage', 'claims'}
    inputs = run_or_load(rerun)
    blocking = _report('blocking_issues.json') or dict(issues=[], resolved=[])
    checks = dict(
        consistency_probe=_probe_summary(inputs['probe']),
        leakage_audit=_leakage_summary(inputs['leakage']),
        identity_checks=_identity_summary(inputs['identity']),
        claim_audit=_claims_summary(inputs['claims']),
        acceptance_suite=(dict(status='SKIP', note='--skip-tests') if skip_tests else run_acceptance_suite()),
        forecast_file_audit=forecast_audit(event),
        hash_provenance=hash_provenance(inputs['leakage']),
        madrid_anchors=madrid_anchors(),
        blocking=dict(status='PASS' if not blocking.get('issues') else 'FAIL', open=[i.get('id') for i in blocking.get('issues') or []], resolved=[r.get('id') for r in blocking.get('resolved') or []],
                      observations=[o.get('id') for o in blocking.get('observations_not_blocking') or []]),
    )
    wording = wording_outstanding(inputs['claims'])
    dec, why = verdict(checks, blocking)
    lock = read_json(LOCK_V1) if LOCK_V1.exists() else {}
    v2 = read_json(LOCK_V2) if LOCK_V2.exists() else {}
    counts = dict(checks=len(checks), pass_=sum(1 for v in checks.values() if v.get('status') == 'PASS'), warn=sum(1 for v in checks.values() if v.get('status') == 'WARN'),
                  fail=sum(1 for v in checks.values() if v.get('status') == 'FAIL'), skip=sum(1 for v in checks.values() if v.get('status') == 'SKIP'),
                  blocking_open=len(blocking.get('issues') or []), blocking_resolved=len(blocking.get('resolved') or []), wording_outstanding=len(wording),
                  acceptance_tests=(checks['acceptance_suite'].get('counts') or {}))
    para = _verdict_paragraph(dec, why, checks, counts, wording)
    rep = dict(generated_at=now_iso(), workstream=7, checkpoint_target='C4', lock=dict(generated_at=lock.get('generated_at'), forecast_hash=(v2.get('shared') or {}).get('forecast_hash')),
               verdict=dict(decision=dec, paragraph=para), counts=counts, checks=checks, blocking=blocking, wording_flags_outstanding=wording,
               inputs={k: (v.get('generated_at') if isinstance(v, dict) else None) for k, v in inputs.items()}, rerun=sorted(rerun))
    rep['exit_code'] = 0 if (dec in ('GO', 'GO_WITH_REASSIGNMENT') and counts['fail'] == 0) else 1
    if out:
        write_json(out, rep)
        Path(out).with_suffix('.md').write_text(render_md(rep), encoding='utf-8')
    return rep


def _verdict_paragraph(dec: str, why: str, checks: dict, counts: dict, wording: list[dict]) -> str:
    bits = []
    fa = checks['forecast_file_audit']; hp = checks['hash_provenance']; pr = checks['consistency_probe']; ac = checks['acceptance_suite']; an = checks['madrid_anchors']
    bits.append(f"Red team verdict for C4: {dec}." + (f' {why}' if why else ''))
    bits.append(f"Blocking list: {counts['blocking_open']} open, {counts['blocking_resolved']} resolved (RT-BLK-1 closed at the live_bridge boundary with guarding tests).")
    bits.append(f"Acceptance suite tests/red_team: {ac.get('counts', {}).get('passed', '?')} passed, {ac.get('counts', {}).get('failed', '?')} failed, {ac.get('counts', {}).get('xfailed', '?')} xfailed in {ac.get('seconds', '?')} s"
                + (f" (failing: {', '.join(n['test'].split('::')[-1] for n in ac.get('not_green', []) if n['status'] in ('FAILED', 'ERROR'))})" if any(n['status'] in ('FAILED', 'ERROR') for n in ac.get('not_green', [])) else '') + '.')
    bits.append(f"Consistency probe: {pr.get('status')} ({(pr.get('counts') or {}).get('numbers')} rendered numbers, {(pr.get('counts') or {}).get('mismatches')} mismatches"
                + (f"; failing routes {[r['route'] for r in pr.get('failing_routes', [])]}" if pr.get('failing_routes') else '') + ').')
    lk = checks['leakage_audit'].get('per_check') or {}
    bits.append(f"Leakage audit {checks['leakage_audit'].get('status')} ({sum(1 for v in lk.values() if v == 'PASS')} of {len(lk)} checks pass"
                + (f"; failing: {[k for k, v in lk.items() if v != 'PASS']}" if any(v != 'PASS' for v in lk.values()) else '') + f"); identity checks {checks['identity_checks'].get('status')} {checks['identity_checks'].get('counts')}.")
    bits.append(f"Hashed forecast {fa.get('file')}: {fa.get('status')} (issued {fa.get('issued_at')} from sessions {fa.get('sessions_used')}; pointers resolve {fa.get('pointers_resolve')}"
                + (f"; problems: {fa.get('problems')}" if fa.get('problems') else '') + ').')
    bits.append(f"Forecast-hash provenance: {hp.get('status')} (runtime readers agree: {hp.get('runtime_readers_agree')}; stale sidecars: {len(hp.get('stale_sidecars') or [])}"
                + ('; content-only proof: the hash changes with the per-event data_cutoff stamp alone' if hp.get('content_only_proof', {}).get('equals_lock') is False else '') + ').')
    bits.append(f"Madrid anchors: {an.get('status')} ({len(an.get('stale') or [])} stated times that did not happen as written). Wording flags outstanding: {len(wording)} (owners: {sorted({str(w.get('owner')) for w in wording})}).")
    return ' '.join(bits)


def render_md(rep: dict) -> str:
    L = [f"# Red team report for {rep['checkpoint_target']}", '', f"generated {rep['generated_at']} · lock {rep['lock'].get('generated_at')} · forecast hash {str(rep['lock'].get('forecast_hash'))[:22]}...", '',
         f"## Verdict: {rep['verdict']['decision']}", '', rep['verdict']['paragraph'], '', '## Checks', '', '| check | status | detail |', '|---|---|---|']
    for k, v in rep['checks'].items():
        detail = {
            'consistency_probe': f"{(v.get('counts') or {}).get('numbers')} numbers, {(v.get('counts') or {}).get('mismatches')} mismatches, {(v.get('counts') or {}).get('unhashed_live_values')} unhashed live values; failing routes {[r['route'] for r in v.get('failing_routes', [])]}",
            'leakage_audit': f"{v.get('per_check')}",
            'identity_checks': f"{v.get('counts')} {v.get('failing') or ''}",
            'claim_audit': f"{(v.get('counts') or {}).get('verdicts')}; survivors {[s['id'] for s in v.get('survivors', [])]}"
                           + (f"; stated WITH their required qualification (audit this): " + '; '.join(f"{q['id']} x{q['n']} at {', '.join(q['where'])}" for q in v.get('qualified_in_presentation', [])) if v.get('qualified_in_presentation') else ''),
            'acceptance_suite': f"{v.get('counts')} in {v.get('seconds')} s; not green: {[n['test'].split('::')[-1] + ' ' + n['status'] for n in v.get('not_green', [])]}",
            'forecast_file_audit': f"{v.get('file')} issued {v.get('issued_at')} sessions {v.get('sessions_used')} pointers {v.get('pointers_resolve')}; problems {v.get('problems')}",
            'hash_provenance': f"runtime readers agree {v.get('runtime_readers_agree')}; stale sidecars {v.get('stale_sidecars')}",
            'madrid_anchors': f"{v.get('reality')}; stale statements {[(s['document'], s['line'], s['time']) for s in v.get('stale', [])]}",
            'blocking': f"open {v.get('open')} resolved {v.get('resolved')} observations {v.get('observations')}",
        }.get(k, '')
        L.append(f"| {k} | {v.get('status')} | {str(detail).replace('|', '/')[:600]} |")
    L += ['', '## Wording flags outstanding (owner)', '']
    for w in rep['wording_flags_outstanding'] or []:
        L.append(f"- [{w.get('owner')}] {w['rule']} at {w['source']}: {w.get('excerpt', '')[:120]}" + (f" — {w.get('note')}" if w.get('note') else ''))
    if not rep['wording_flags_outstanding']:
        L.append('- none')
    L += ['', '## Blocking issues', '', f"open: {rep['blocking'].get('issues')}", '']
    for r in rep['blocking'].get('resolved') or []:
        L.append(f"- resolved {r['id']}: {r.get('resolution', '')[:300]}")
    for o in rep['blocking'].get('observations_not_blocking') or []:
        L.append(f"- observation {o['id']} ({o.get('severity')}): {o.get('title')} — owner {o.get('owner')}")
    L += ['', '## Inputs', '', ', '.join(f'{k}: {v}' for k, v in rep['inputs'].items()), '']
    return '\n'.join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--event', default='Madrid'); ap.add_argument('--rerun', default='leakage,claims', help='comma list of leakage,claims,identity,probe (or none)')
    ap.add_argument('--skip-tests', action='store_true'); ap.add_argument('--out', default=str(REPORT_JSON))
    a = ap.parse_args(argv)
    rerun = {x.strip() for x in a.rerun.split(',') if x.strip() and x.strip() != 'none'}
    rep = build(a.event, rerun, a.skip_tests, a.out)
    print(rep['verdict']['paragraph'])
    for k, v in rep['checks'].items():
        print(f"  {v.get('status'):5s} {k}")
    print(f"report: {a.out} (+ .md) -> exit {rep['exit_code']}")
    return rep['exit_code']


if __name__ == '__main__':
    sys.exit(main())
