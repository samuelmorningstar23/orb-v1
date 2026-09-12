"""The C6 rehearsal must never discard a concurrent feedback writer."""
import json
import pytest
from evaluation.rehearsal_runner import appended_event, restore_feedback, digest


def test_restore_exact_existing_feedback(tmp_path):
    p=tmp_path/'feedback.jsonl';before=b'{"earlier":"untouched"}\n';after=before+b'{"raw_message":"test"}\n';p.write_bytes(after)
    assert appended_event(before,after,'test')=={'raw_message':'test'}
    assert restore_feedback(p,before,True,after)==digest(before)
    assert p.read_bytes()==before


def test_concurrent_append_refuses_restore(tmp_path):
    p=tmp_path/'feedback.jsonl';ours=b'{"raw_message":"test"}\n';concurrent=ours+b'{"raw_message":"someone else"}\n';p.write_bytes(concurrent)
    with pytest.raises(RuntimeError,match='CAS'):restore_feedback(p,b'',False,ours)
    assert p.read_bytes()==concurrent
    with pytest.raises(RuntimeError,match='exactly one'):appended_event(b'',concurrent,'test')


def test_wrong_marker_and_changed_prefix_refused():
    with pytest.raises(RuntimeError,match='not this'):appended_event(b'',b'{"raw_message":"other"}\n','test')
    with pytest.raises(RuntimeError,match='prefix'):appended_event(b'old',b'new','test')


def test_prior_missing_file_restored_to_missing(tmp_path):
    p=tmp_path/'feedback.jsonl';after=b'{"raw_message":"test"}\n';p.write_bytes(after)
    assert restore_feedback(p,b'',False,after)==digest(b'')
    assert not p.exists()


def test_actual_frames_serialization_matches_player_payload():
    import re
    from app_v2.components.race_twin.player import load_assets,player_html
    frames,track,pit=load_assets('Monza','NOR',scenario_id='monza_nor_lap24_to_medium_new_tyre_only')
    assert frames is not None
    html=player_html(frames,track,pit)
    data=json.loads(re.search(r'const D = (.*?);\s*if \(!D\)',html,re.S)[1])
    assert frames.to_player_dict()==data['frames']
