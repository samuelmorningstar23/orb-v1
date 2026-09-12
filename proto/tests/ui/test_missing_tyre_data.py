"""Regression coverage for recorded laps with missing tyre metadata."""
import math
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app_v2.services import lock_repository as LR, replay_service as RS, view_models as VM

APP = Path(__file__).resolve().parents[2] / "app_v2" / "streamlit_app.py"


def test_hungary_missing_tyre_metadata_has_no_stint_estimate():
    lock = LR.load_lock()
    cursor = RS.ReplayCursor("Hungary", "PER", lock.n_laps("Hungary"))
    corr = VM.corrections_for(lock, "Hungary")
    prior = VM.prior_for(lock, "Hungary", "MEDIUM")
    assert RS.stint_state(cursor.seek(21), prior, corr) is not None
    for lap in (22, 23, 46):
        assert RS.stint_state(cursor.seek(lap), prior, corr) is None


@pytest.mark.parametrize("event", LR.load_lock().event_names())
def test_weekend_shell_without_driver_does_not_crash(event):
    at = AppTest.from_file(str(APP))
    at.query_params.update(ev=event, mode="live")
    at.run(timeout=30)
    assert not at.exception, [e.value for e in at.exception]
    assert at.session_state["ev"] == event
    if RS.drivers_for(event):
        assert at.session_state["drv"] in RS.drivers_for(event)


@pytest.mark.parametrize("lap", [22, 23, 46])
def test_live_missing_tyre_data_keeps_replay_controls(lap, monkeypatch):
    from app_v2.services import live_bridge as LB
    def must_not_estimate(*args, **kwargs):
        pytest.fail("Missing compound/age must not produce a tyre prediction")
    monkeypatch.setattr(LB, "build", must_not_estimate)
    script = f"""
import streamlit as st
from app_v2.pages import live_predictor
st.session_state.update(ev='Hungary', drv='PER', lap={lap}, mode='live')
live_predictor.render()
"""
    at = AppTest.from_string(script).run(timeout=30)
    assert not at.exception, [e.value for e in at.exception]
    messages = " ".join(str(el.value) for el in at.get("html"))
    assert "Prediction unavailable: tyre compound and tyre age missing" in messages
    assert any(b.label == "Step +1" for b in at.button)
    assert any(s.label == "Lap scrubber" for s in at.slider)


def test_missing_pit_compound_does_not_use_future_rows():
    lock = LR.load_lock()
    cursor = RS.ReplayCursor("Monza", "NOR", lock.n_laps("Monza"))
    # Missing metadata on a historical pit exit must not crash a later valid lap.
    cursor._df.loc[cursor._df.LapNumber == 1, ["Compound", "TyreLife"]] = float("nan")
    cursor._df.loc[cursor._df.LapNumber == 1, "pit_out"] = True
    corr = VM.corrections_for(lock, "Monza")
    prior = VM.prior_for(lock, "Monza", "MEDIUM")
    assert RS.stint_state(cursor.seek(1), prior, corr) is None
    state = RS.stint_state(cursor.seek(5), prior, corr)
    assert state is not None
    assert state.events_in_stint[0]["detail"] == "tyre compound unavailable"
    assert all(math.isfinite(age) for age in state.ages)
    cursor._df.loc[cursor._df.LapNumber > 5, ["Compound", "TyreLife"]] = float("nan")
    again = RS.stint_state(cursor, prior, corr)
    assert again.post_slope == state.post_slope
    assert again.events_in_stint == state.events_in_stint


@pytest.mark.parametrize("page", ["live_predictor", "decision_board", "driver_feedback"])
@pytest.mark.parametrize("lap", [22, 48])
def test_live_pages_do_not_estimate_incomplete_history(page, lap, monkeypatch):
    from app_v2.services import live_bridge as LB
    def must_not_estimate(*args, **kwargs):
        pytest.fail("Incomplete tyre history must not reach the estimator")
    monkeypatch.setattr(LB, "build", must_not_estimate)
    script = f"""
import streamlit as st
from app_v2.pages import {page}
st.session_state.update(ev='Hungary', drv='PER', lap={lap}, mode='live')
{page}.render()
"""
    at = AppTest.from_string(script).run(timeout=30)
    assert not at.exception, [e.value for e in at.exception]
    messages = " ".join(str(el.value) for el in at.get("html"))
    assert "Prediction unavailable" in messages
    if lap == 48:
        assert "earlier lap 22" in messages


def test_prediction_availability_uses_only_the_visible_prefix():
    cursor = RS.ReplayCursor("Hungary", "PER", 70)
    assert RS.prediction_unavailable_reason(cursor.seek(21)) == ""
    assert "this recorded lap" in RS.prediction_unavailable_reason(cursor.seek(22))
    assert "earlier lap 22" in RS.prediction_unavailable_reason(cursor.seek(48))
    assert RS.prediction_unavailable_reason(cursor.seek(21)) == ""
