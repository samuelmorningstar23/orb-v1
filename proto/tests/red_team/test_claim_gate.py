"""The claim gate (C4 acceptance: no flagged claim in THE_CASE.md, talk_track.md or the pptx).

`evaluation/red_team/claim_audit.py` matches each contested number by regex. A regex cannot tell the bare claim
("cut the error by 23%") from the same number stated with the qualification its evidence requires ("23% lap-weighted
with the three degenerate Hungary cells excluded, 31% with them ... 9 of 31 cells"), so at C4 a claim that the lead
had already corrected still counted as an occurrence. `locate()` now records, per occurrence, whether every
`qualified_by` pattern is present in that source, and the gate blocks only UNQUALIFIED occurrences on the
presentation surfaces - while newly counting `unverifiable` verdicts, which the C3 gate ignored entirely.

That reclassification must not become a way to launder a claim, so these tests check it from both ends:
  - the mechanism still blocks the bare sentence, and a wrong count cancels the qualification (synthetic);
  - every reclassification in the written map is real: the qualifiers genuinely appear in the cited file at the
    cited line, and the map is not older than the documents it audited (a stale map proves nothing)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pytest

from rt_helpers import PROTO

MAP = PROTO / 'evaluation' / 'red_team' / 'claim_evidence_map.json'
DOCS = ('README.md', 'out/THE_CASE.md', 'out/talk_track.md', 'out/Orb_v1_Mentor_Briefing.pptx', 'out/Orb_v1_ChallengeDay.pdf')
BLOCKING_VERDICTS = ('mismatch', 'exceeds_evidence', 'unverifiable')


@pytest.fixture(scope='module')
def claim_map() -> dict:
    if not MAP.exists():
        pytest.skip('claim_evidence_map.json not generated (../.venv/bin/python -m evaluation.red_team.claim_audit)')
    return json.loads(MAP.read_text(encoding='utf-8'))


def _lines(source: str) -> dict[int, str]:
    """Line number -> text for a claim-audit source label (a file path, or a '...pptx#slide-N' label)."""
    if '#slide-' in source or '#page-' in source:
        from evaluation.red_team.claim_audit import _slides, _pdf_pages
        for label, text in _slides() + _pdf_pages():
            if label == source:
                return dict(enumerate(text.splitlines(), 1))
        return {}
    p = PROTO / source
    return dict(enumerate(p.read_text(encoding='utf-8').splitlines(), 1)) if p.exists() else {}


def test_no_flagged_claim_is_unqualified_in_a_presentation_document(claim_map):
    """C4 acceptance criterion 3."""
    assert claim_map['summary']['must_reword_before_presentation'] == [], (
        'claims still exceed their evidence on a presentation surface: ' + ', '.join(claim_map['summary']['must_reword_before_presentation']))
    offenders = []
    for c in claim_map['claims']:
        if c['verdict'] in BLOCKING_VERDICTS:
            for w in c.get('found_in', []):
                if w.get('kind') in ('deck', 'talk_track', 'THE_CASE', 'README') and not w.get('qualified'):
                    offenders.append(f"{c['id']} ({c['verdict']}) at {w['source']}:{w['line']}: {w['excerpt'][:90]}")
    assert not offenders, 'flagged claims present unqualified:\n  ' + '\n  '.join(offenders)


def test_every_reclassified_claim_really_carries_its_qualifiers(claim_map):
    """A `qualified` occurrence must be provable by re-reading the cited line, not trusted from the report."""
    reclassified = claim_map['summary'].get('qualified_in_presentation', [])
    by_id = {c['id']: c for c in claim_map['claims']}
    checked = 0
    for entry in reclassified:
        c = by_id[entry['id']]
        quals = c.get('qualified_by') or []
        assert quals, f"{c['id']} is reported qualified but declares no qualified_by patterns"
        for w in c['found_in']:
            if not (w.get('qualified') and w.get('kind') in ('deck', 'talk_track', 'THE_CASE', 'README')):
                continue
            text = _lines(w['source']).get(w['line'], '')
            assert text, f"{c['id']}: {w['source']}:{w['line']} no longer exists - the map is stale, re-run the claim audit"
            missing = [q for q in quals if not re.search(q, text, flags=re.I)]
            forbidden = [d for d in (c.get('disqualified_by') or []) if re.search(d, text, flags=re.I)]
            assert not missing and not forbidden, (
                f"{c['id']} at {w['source']}:{w['line']} is counted as qualified but the line is missing {missing} "
                f"and/or contains {forbidden}:\n    {text.strip()[:300]}")
            checked += 1
    if reclassified:
        assert checked, 'reclassified claims were reported but no occurrence could be re-read'


def test_claim_map_is_not_older_than_the_documents_it_audited(claim_map):
    """A gate computed before the last document rebuild says nothing about what will be presented."""
    gen = datetime.fromisoformat(claim_map['generated_at'])
    stale = []
    for rel in DOCS:
        p = PROTO / rel
        if p.exists() and datetime.fromtimestamp(p.stat().st_mtime) > gen:
            stale.append(f'{rel} rebuilt {datetime.fromtimestamp(p.stat().st_mtime):%H:%M:%S} after the audit ran {gen:%H:%M:%S}')
    assert not stale, 'the claim map predates a document rebuild; re-run evaluation.red_team.claim_audit:\n  ' + '\n  '.join(stale)


# ------------------------------------------------------------------ self-tests of the qualification mechanism
def _locate_one(claim: dict, source_label: str, text: str) -> dict:
    from evaluation.red_team.claim_audit import locate
    c = dict(claim)
    locate([c], [(source_label, list(enumerate(text.splitlines(), 1)))])
    return c


LIQUID = dict(id='synthetic_liquid', claim='x', pattern=r'23%|10 of 31', evidence_path='-', evidence_value=None, verdict='unverifiable', note='',
              search_in=['talk_track', 'THE_CASE', 'deck'], severity='MEDIUM', qualified_by=[r'lap-weighted', r'Hungary', r'9 of 31'], disqualified_by=[r'10 of 31'])


def test_gate_still_blocks_the_bare_claim():
    c = _locate_one(LIQUID, 'out/talk_track.md', 'Per-lap inputs cut the age-only error by 23%.')
    assert c['n_occurrences'] == 1 and c['n_presentation_unqualified'] == 1 and c['n_presentation_qualified'] == 0, c


def test_gate_accepts_the_fully_qualified_sentence():
    c = _locate_one(LIQUID, 'out/talk_track.md',
                    'Per-lap inputs cut the age-only error by about a quarter (23% lap-weighted with the three degenerate Hungary cells excluded, 31% with them); '
                    'the network beat the best baseline in only 9 of 31 cells.')
    assert c['n_presentation_unqualified'] == 0 and c['n_presentation_qualified'] == 1 and c['found_in'][0]['qualified_same_line'], c


def test_a_wrong_count_cancels_the_qualification():
    """The caveat is present but the count is the old wrong one: this must still block."""
    c = _locate_one(LIQUID, 'out/talk_track.md',
                    '23% lap-weighted with the three degenerate Hungary cells excluded; the network beat the best baseline 10 of 31 cells.')
    assert c['n_presentation_unqualified'] == 1 and c['n_presentation_qualified'] == 0, c


def test_a_partial_caveat_does_not_qualify():
    c = _locate_one(LIQUID, 'out/THE_CASE.md', 'Per-lap inputs cut the age-only error by 23% lap-weighted.')     # no Hungary exclusion, no count
    assert c['n_presentation_unqualified'] == 1, c


def test_a_claim_without_qualifiers_can_never_be_qualified():
    """Only claims that declare qualified_by may be reclassified; every other claim keeps the old strict behaviour."""
    bare = dict(LIQUID, id='no_quals', qualified_by=[], disqualified_by=[])
    c = _locate_one(bare, 'out/THE_CASE.md', '23% lap-weighted with the three degenerate Hungary cells excluded and 9 of 31 cells.')
    assert c['n_presentation_qualified'] == 0 and c['n_presentation_unqualified'] == 1, c


def test_roadmap_is_not_a_presentation_surface():
    """ROADMAP_v5 is the build contract; its illustrative readouts must not block the presentation gate."""
    c = dict(LIQUID, id='roadmap_only', search_in=['ROADMAP_v5'])
    c = _locate_one(c, 'out/ROADMAP_v5.md', 'example screen: 23% reduction')
    assert c['n_occurrences'] == 1 and c['n_presentation_unqualified'] == 0, c
