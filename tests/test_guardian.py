"""The Safety Guardian: the only thing that may open the gate to load advice.

Every test here fails on 4f4430f, the commit where a model-generated
`log_status{injured: false}` could close an injury and restore load advice on
the same message.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.agent.schemas import LogStatus, RequestInjuryClearance, validate_call
from app.config import settings
from app.decision.guardian import (
    ClearanceForged,
    InjuryVeto,
    SafetyClearance,
    assess,
    clearance_for_tests,
    is_cleared,
)
from app.decision.prescribe import prescribe_next
from app.storage import db

ATHLETE = "+911"
TODAY = date(2026, 9, 10)


def _injure(conn, on="2026-09-01", note="left knee"):
    db.insert_entry(
        conn,
        db.Entry(athlete_id=ATHLETE, kind="status", injured=True,
                 injury_note=note, session_date=on),
    )


# --- the model has no authority to clear -------------------------------------


def test_the_model_cannot_emit_a_clearance():
    """log_status{injured:false} is downgraded to a request, never a clearance."""
    action = validate_call("log_status", {"injured": False, "injury_note": "fine now"}, TODAY)
    assert isinstance(action, RequestInjuryClearance)
    assert not isinstance(action, LogStatus)


def test_a_clearance_row_without_an_actor_leaves_the_flag_open(conn):
    """Fails closed: an injured=0 row that names nobody is not a clearance."""
    _injure(conn)
    db.insert_entry(
        conn,
        db.Entry(athlete_id=ATHLETE, kind="status", injured=False, session_date="2026-09-05"),
    )
    assert db.injury_state(conn, ATHLETE)[0] is True
    assert isinstance(assess(conn, ATHLETE, today=TODAY), InjuryVeto)


def test_an_athlete_cannot_clear_their_own_injury(conn):
    _injure(conn)
    with pytest.raises(ValueError, match="cannot clear their own"):
        db.clear_injury(conn, ATHLETE, actor=ATHLETE, reason="feel fine")


def test_clearing_requires_an_actor_and_a_reason(conn):
    _injure(conn)
    with pytest.raises(ValueError, match="named actor"):
        db.clear_injury(conn, ATHLETE, actor="", reason="physio signed off")
    with pytest.raises(ValueError, match="recorded reason"):
        db.clear_injury(conn, ATHLETE, actor="Coach Rao", reason="")


def test_a_named_clearance_opens_the_gate_and_is_auditable(conn):
    _injure(conn)
    db.clear_injury(conn, ATHLETE, actor="Coach Rao", reason="physio signed off",
                    on="2026-09-06")
    assert is_cleared(assess(conn, ATHLETE, today=TODAY))
    row = conn.execute(
        "SELECT injury_cleared_by, injury_cleared_at, injury_clearance_reason "
        "FROM entries WHERE injury_cleared_by IS NOT NULL"
    ).fetchone()
    assert row["injury_cleared_by"] == "Coach Rao"
    assert row["injury_clearance_reason"] == "physio signed off"
    assert row["injury_cleared_at"]


# --- the clearance object cannot be forged -----------------------------------


def test_a_clearance_cannot_be_constructed_outside_the_guardian():
    with pytest.raises(ClearanceForged):
        SafetyClearance(ATHLETE, TODAY, object())


def test_prescribe_next_cannot_be_called_without_a_clearance():
    """The gate is a required argument, not a branch someone might forget."""
    with pytest.raises(TypeError):
        prescribe_next(None, [], None, session_number=1, today=TODAY)  # type: ignore[call-arg]


def test_no_application_module_imports_the_test_door():
    """`clearance_for_tests` is the one door around the gate. Keep it in tests."""
    app_dir = Path(__file__).resolve().parent.parent / "app"
    offenders = [
        path.relative_to(app_dir).as_posix()
        for path in app_dir.rglob("*.py")
        if path.name != "guardian.py"
        and "clearance_for_tests" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"application code must not bypass the gate: {offenders}"


# --- staleness ----------------------------------------------------------------


def test_an_untouched_injury_flag_eventually_goes_stale(conn):
    _injure(conn, on="2026-09-01")
    fresh = assess(conn, ATHLETE, today=date(2026, 9, 10))
    assert isinstance(fresh, InjuryVeto) and fresh.stale is False

    stale = assess(conn, ATHLETE, today=date(2026, 10, 20))
    assert isinstance(stale, InjuryVeto)
    assert stale.stale is True
    assert stale.days_open == 49


def test_a_stale_flag_still_vetoes_it_only_asks(conn):
    """Going stale prompts a human. It never opens the gate on its own."""
    _injure(conn, on="2026-01-01")
    outcome = assess(conn, ATHLETE, today=TODAY)
    assert isinstance(outcome, InjuryVeto)
    assert outcome.stale is True
    assert not is_cleared(outcome)


def test_the_staleness_threshold_is_configurable(conn, monkeypatch):
    _injure(conn, on="2026-09-01")
    monkeypatch.setattr(settings, "injury_stale_after_days", 3)
    outcome = assess(conn, ATHLETE, today=date(2026, 9, 10))
    assert isinstance(outcome, InjuryVeto) and outcome.stale is True


# --- the episode boundary ------------------------------------------------------


def test_open_since_tracks_the_current_episode_not_the_first_ever(conn):
    _injure(conn, on="2026-01-01", note="old knee")
    db.clear_injury(conn, ATHLETE, actor="Coach Rao", reason="resolved", on="2026-02-01")
    _injure(conn, on="2026-09-05", note="new back")
    outcome = assess(conn, ATHLETE, today=TODAY)
    assert isinstance(outcome, InjuryVeto)
    assert outcome.open_since == "2026-09-05"
    assert outcome.days_open == 5


def test_a_clearance_request_is_recorded_but_changes_nothing(conn):
    _injure(conn)
    db.request_injury_clearance(conn, ATHLETE, note="feels fine", on="2026-09-08")
    outcome = assess(conn, ATHLETE, today=TODAY)
    assert isinstance(outcome, InjuryVeto)
    assert outcome.clearance_requested is True
    assert not is_cleared(outcome)
