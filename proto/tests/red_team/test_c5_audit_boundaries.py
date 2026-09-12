"""C5 audit must cover both presentations without reading sealed per-race evidence."""
from pathlib import Path

import pytest

from evaluation.red_team import consistency_probe as probe
from evaluation.red_team import claim_audit as claims


def test_public_probe_never_reads_per_race_holdout(monkeypatch):
    """Trap any file read, including helper opens; no protected content is opened."""
    import builtins
    original_open, original_builtin = Path.open, builtins.open
    forbidden_attempts = []
    def deny(path):
        if isinstance(path, (str, Path)) and Path(path).name == 'holdout_per_race.json':
            forbidden_attempts.append(str(path))
            raise AssertionError('per-race holdout read is forbidden')
    def guarded_open(path, *args, **kwargs):
        deny(path)
        return original_open(path, *args, **kwargs)
    def guarded_builtin(path, *args, **kwargs):
        deny(path)
        return original_builtin(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded_open)
    monkeypatch.setattr(builtins, 'open', guarded_builtin)
    refs = probe.build_base_references({}, [])
    assert not forbidden_attempts, 'even caught attempts to read the per-race file must fail'
    assert not any('holdout_per_race' in key for key in refs.values)
    assert any('holdout_aggregate' in key for key in refs.values)


def test_challenge_pdf_is_a_presentation_surface():
    c = dict(id='bare', pattern=r'23%', search_in=['deck'], qualified_by=[], disqualified_by=[])
    claims.locate([c], [('out/Orb_v1_ChallengeDay.pdf#page-2', [(1, '23% reduction')])])
    assert c['n_presentation_unqualified'] == 1
    assert c['found_in'][0]['kind'] == 'deck'


def test_missing_challenge_pdf_fails_loudly(monkeypatch, tmp_path):
    monkeypatch.setattr(claims, 'CHALLENGE_DECK', tmp_path / 'absent.pdf')
    with pytest.raises(FileNotFoundError):
        claims._pdf_pages()


def test_browser_health_failure_is_not_a_skip(monkeypatch):
    from evaluation.red_team import browser_consistency as browser
    def unavailable(*args, **kwargs):
        raise ConnectionError('dashboard unavailable')
    monkeypatch.setattr(browser, 'urlopen', unavailable)
    report = browser.run(out=None)
    assert report['exit_code'] == 2
    assert 'dashboard unavailable' in report['error']


def test_browser_inventory_covers_all_app_modules_and_acceptance_routes():
    from evaluation.red_team.browser_consistency import browser_routes, PAGE_PATHS
    routes = browser_routes()
    assert {r[1] for r in routes} == set(PAGE_PATHS)
    assert len(routes) >= len(probe.ROUTES) + 19
    assert any(r[0] == 'acceptance/degraded_feed' for r in routes)


def test_c5_report_rejects_partial_browser_matrix():
    from evaluation.red_team.build_report import _browser_summary
    assert _browser_summary(dict(exit_code=0, routes=[]))['status'] == 'FAIL'


def test_requested_checkpoint_appears_in_verdict():
    from evaluation.red_team.build_report import _verdict_paragraph
    checks = {key: {} for key in ('forecast_file_audit', 'hash_provenance', 'consistency_probe',
              'acceptance_suite', 'madrid_anchors', 'leakage_audit', 'identity_checks')}
    counts = dict(blocking_open=0, blocking_resolved=0)
    assert _verdict_paragraph('GO', '', checks, counts, [], 'C5').startswith('Red team verdict for C5: GO.')


def test_actual_challenge_pdf_extracts_all_pages():
    from pypdf import PdfReader
    pages = claims._pdf_pages()
    assert len(pages) == len(PdfReader(claims.CHALLENGE_DECK).pages)
    assert pages and all(text.strip() for _, text in pages)
    assert all(claims.source_kind(label) == 'deck' for label, _ in pages)


def test_digit_only_asset_hash_is_not_a_metric_and_real_errors_still_fail():
    from app_v2.pages.ghost_strategy import audit_evidence_html
    from types import SimpleNamespace
    sc = SimpleNamespace(mode='fixed_context', generated_at='2026-09-12',
        finish_delta_s=-37.2, q10=-40.0, q90=-30.0, probability_of_gain=0.9,
        oracle_regret_s=None, actual_plan={}, cf_plan={}, curves={}, validation={}, claim_scope='audit')
    fc = SimpleNamespace(err=None, covered=None, observed=None, n_race=None)
    vm = SimpleNamespace(forecast=fc, hidden_stop=None, regret_s=None, event="Monza", driver="VER")
    # Exercise the actual page's evidence formatter, not a hand-written hash label.
    raw = audit_evidence_html(sc, None, vm, {'ghost_replay': {'short': '685860', 'status': 'verified'}})
    assert 'ghost_replay sha256 685860 verified' in raw
    rec = dict(route='regression', status='ok', numbers=0, matched={},
               ambiguous=[], placeholders=[], unclassified=[], unhashed_live=[], mismatches=[])
    refs = probe.ReferenceSet()
    surface = dict(kind='browser:stHtml', widget='assets', cells=[], raw='',
                   text='ghost_replay sha256 685860 verified; finish delta 685860 s')
    probe.match_surfaces(rec, [surface], refs)
    assert rec['numbers'] == 1
    assert rec['status'] == 'mismatch'
    assert [m['value'] for m in rec['mismatches']] == [685860.0]
