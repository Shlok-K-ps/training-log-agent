"""The athlete page, the coach's message, and registration.

The roster answers who needs attention. These cover the other half: what the
coach sees about one athlete, and what they say back.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.coach.athlete import athlete_detail, progress_series, suggest_message
from app.coach.athlete_view import render_athlete
from app.coach.demo import DEMO_PREFIX, seed_demo_squad
from app.scheduling.outbox import COACH_NOTE, send_approved_notes
from app.storage import db

TODAY = date(2026, 9, 10)
COACH = "Coach Rao"


@pytest.fixture()
def squad(conn):
    seed_demo_squad(conn, today=TODAY)
    return conn


# --- what the coach sees -------------------------------------------------------


def test_the_page_never_disagrees_with_the_athletes_own_verdict(squad):
    """Every verdict shown comes from the same rules that answered the athlete."""
    from app.decision.rules import evaluate

    athlete = f"{DEMO_PREFIX}002"
    detail = athlete_detail(squad, athlete, today=TODAY)
    for assessment in detail.assessments:
        direct = evaluate(
            athlete, assessment.lift,
            db.session_history(squad, athlete, assessment.lift),
            phase=detail.phase, injured=detail.injured,
        )
        assert assessment.verdict is direct.verdict


def test_an_injured_athlete_shows_the_open_flag(squad):
    detail = athlete_detail(squad, f"{DEMO_PREFIX}001", today=TODAY)
    assert detail.injured is True
    assert detail.clearance_requested is True
    assert detail.injury_days_open == 23


def test_progress_charts_the_top_set_the_rules_compare(squad):
    series = progress_series(athlete_detail(squad, f"{DEMO_PREFIX}004", today=TODAY))
    assert series["squat"] == (
        ("2026-09-01", 102.5), ("2026-09-04", 100.0), ("2026-09-07", 97.5),
    )


def test_a_lift_with_one_session_is_not_charted(conn):
    """Two points make a line; one makes a misleading dot."""
    db.insert_entry(conn, db.Entry(
        athlete_id="+911", athlete_name="Solo", kind="set", lift="squat",
        sets=3, reps=5, weight_kg=140, session_date="2026-09-09"))
    assert progress_series(athlete_detail(conn, "+911", today=TODAY)) == {}


# --- the suggested draft --------------------------------------------------------


def test_a_silent_athlete_is_not_told_we_saw_their_session(squad):
    """The newest row is not today's row. Getting this wrong reads as if
    nobody is paying attention, which is what this console exists to prevent."""
    draft = suggest_message(
        athlete_detail(squad, f"{DEMO_PREFIX}003", today=TODAY), coach=COACH
    )
    assert "saw your session" not in draft
    assert "nothing logged" in draft.lower()


def test_an_injured_athletes_draft_offers_no_load(squad):
    draft = suggest_message(
        athlete_detail(squad, f"{DEMO_PREFIX}001", today=TODAY), coach=COACH
    )
    assert "no load suggestions" in draft
    assert "physio" in draft
    assert "kg" not in draft.split("injury flag open")[1]


def test_the_draft_is_signed_by_the_coach_not_the_agent(squad):
    draft = suggest_message(
        athlete_detail(squad, f"{DEMO_PREFIX}002", today=TODAY), coach=COACH
    )
    assert draft.strip().endswith(f"— {COACH}")


# --- rendering ------------------------------------------------------------------


def test_athlete_supplied_text_is_escaped(conn):
    db.insert_entry(conn, db.Entry(
        athlete_id="+911", athlete_name="<script>alert(1)</script>", kind="status",
        injured=True, injury_note="<img onerror=x>", session_date="2026-09-09"))
    detail = athlete_detail(conn, "+911", today=TODAY)
    html = render_athlete(detail, coach=COACH, suggested=suggest_message(detail, coach=COACH))
    assert "<script>alert(1)</script>" not in html
    assert "<img onerror=x>" not in html
    assert "&lt;script&gt;" in html


def test_the_page_carries_the_draft_and_a_way_to_send_it(squad):
    detail = athlete_detail(squad, f"{DEMO_PREFIX}002", today=TODAY)
    html = render_athlete(detail, coach=COACH, suggested=suggest_message(detail, coach=COACH))
    assert f"/coach/athlete/{DEMO_PREFIX}002/message" in html
    assert "<textarea" in html
    assert "<svg" in html
    assert "Recovery today" in html
    assert "Programming" in html
    assert "Schedule & logistics" in html
    assert "Nutrition & supplements" in html
    assert "Prepared · requires coach approval" in html


# --- registration ----------------------------------------------------------------


def test_registering_puts_an_athlete_on_the_roster_before_they_text(conn):
    db.register_athlete(conn, "+919812340001", "Priya Kulkarni", on="2026-09-10")
    assert db.list_athletes(conn) == ["+919812340001"]
    assert db.athlete_name(conn, "+919812340001") == "Priya Kulkarni"


@pytest.mark.parametrize("bad_id", ["12345", "+9198", "", "not a number"])
def test_an_athlete_id_must_be_a_phone_number(conn, bad_id):
    with pytest.raises(ValueError, match="E.164"):
        db.register_athlete(conn, bad_id, "Someone", on="2026-09-10")


def test_an_athlete_cannot_be_registered_twice(conn):
    db.register_athlete(conn, "+919812340001", "Priya", on="2026-09-10")
    with pytest.raises(ValueError, match="already on the roster"):
        db.register_athlete(conn, "+919812340001", "Priya Again", on="2026-09-10")


def test_a_registered_athlete_needs_a_name(conn):
    with pytest.raises(ValueError, match="needs a name"):
        db.register_athlete(conn, "+919812340001", "   ", on="2026-09-10")


# --- the coach's message goes out ------------------------------------------------


class Outbox(list):
    def __call__(self, athlete_id, body):
        self.append((athlete_id, body))


def test_a_coach_note_is_delivered_as_written(conn):
    db.register_athlete(conn, "+919812340001", "Priya", on="2026-09-10")
    db.create_draft(conn, "+919812340001", COACH_NOTE, "2026-09-10", "Knee check tomorrow?")
    db.review_draft(conn, "+919812340001", COACH_NOTE, "2026-09-10",
                    status="approved", reviewed_by=COACH)

    sent = Outbox()
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    assert send_approved_notes(conn, sent, now_utc=now) == 1
    assert sent == [("+919812340001", "Knee check tomorrow?")]
    assert db.draft(conn, "+919812340001", COACH_NOTE, "2026-09-10")["status"] == "sent"


def test_a_note_is_sent_once(conn):
    db.register_athlete(conn, "+919812340001", "Priya", on="2026-09-10")
    db.create_draft(conn, "+919812340001", COACH_NOTE, "2026-09-10", "Once only")
    db.review_draft(conn, "+919812340001", COACH_NOTE, "2026-09-10",
                    status="approved", reviewed_by=COACH)
    sent = Outbox()
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    send_approved_notes(conn, sent, now_utc=now)
    send_approved_notes(conn, sent, now_utc=now)
    assert len(sent) == 1


def test_a_note_dated_ahead_waits(conn):
    db.register_athlete(conn, "+919812340001", "Priya", on="2026-09-10")
    db.create_draft(conn, "+919812340001", COACH_NOTE, "2026-09-30", "Not yet")
    db.review_draft(conn, "+919812340001", COACH_NOTE, "2026-09-30",
                    status="approved", reviewed_by=COACH)
    sent = Outbox()
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    assert send_approved_notes(conn, sent, now_utc=now) == 0


def test_an_unapproved_note_is_never_sent(conn):
    db.register_athlete(conn, "+919812340001", "Priya", on="2026-09-10")
    db.create_draft(conn, "+919812340001", COACH_NOTE, "2026-09-10", "Draft only")
    sent = Outbox()
    now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    assert send_approved_notes(conn, sent, now_utc=now) == 0
    assert sent == []
