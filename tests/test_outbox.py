"""The outbox gate: nothing proactive reaches an athlete unreviewed.

The agent messages first, which is the useful part and the risky part. These
tests pin the rule that makes it safe: an unreviewed draft produces silence, not
an unsupervised broadcast.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.coach import pending_reviews
from app.config import settings
from app.scheduling.morning import send_due_morning_prompts
from app.scheduling.outbox import MORNING, draft_upcoming_prompts, send_approved_prompts
from app.storage import db

ATHLETE = "+911"
# 21:00 in Asia/Kolkata on the 10th → drafting window for the 11th.
EVENING = datetime(2026, 9, 10, 15, 30, tzinfo=timezone.utc)
# 08:05 in Asia/Kolkata on the 11th → the check-in is due.
NEXT_MORNING = datetime(2026, 9, 11, 2, 35, tzinfo=timezone.utc)


@pytest.fixture()
def scheduled(conn):
    db.insert_entry(
        conn,
        db.Entry(
            athlete_id=ATHLETE, athlete_name="Priya", kind="status",
            timezone="Asia/Kolkata", morning_checkin_time="08:00",
            training_time="18:30", session_date="2026-09-10",
        ),
    )
    return conn


class Outbox(list):
    def __call__(self, athlete_id, body):
        self.append((athlete_id, body))


# --- drafting ------------------------------------------------------------------


def test_the_evening_before_queues_tomorrows_message(scheduled):
    drafted = draft_upcoming_prompts(scheduled, now_utc=EVENING)
    assert [d.local_date for d in drafted] == ["2026-09-11"]
    row = db.draft(scheduled, ATHLETE, MORNING, "2026-09-11")
    assert row["status"] == "pending"
    assert "18:30" in row["body"], "the draft carries the athlete's real training time"


def test_nothing_is_queued_before_the_athletes_evening(scheduled):
    morning_utc = datetime(2026, 9, 10, 4, 0, tzinfo=timezone.utc)  # 09:30 local
    assert draft_upcoming_prompts(scheduled, now_utc=morning_utc) == []


def test_drafting_twice_does_not_overwrite_a_coachs_edit(scheduled):
    draft_upcoming_prompts(scheduled, now_utc=EVENING)
    db.review_draft(scheduled, ATHLETE, MORNING, "2026-09-11",
                    status="approved", reviewed_by="Coach Rao",
                    body="Morning Priya — how's the knee?")
    assert draft_upcoming_prompts(scheduled, now_utc=EVENING) == []
    row = db.draft(scheduled, ATHLETE, MORNING, "2026-09-11")
    assert row["body"] == "Morning Priya — how's the knee?"
    assert row["status"] == "approved"


# --- the gate ------------------------------------------------------------------


def test_an_unreviewed_draft_is_never_sent(scheduled, monkeypatch):
    monkeypatch.setattr(settings, "coach_approval_required", True)
    draft_upcoming_prompts(scheduled, now_utc=EVENING)
    sent = Outbox()
    assert send_approved_prompts(scheduled, sent, now_utc=NEXT_MORNING) == 0
    assert sent == [], "silence, not an unsupervised broadcast"


def test_a_skipped_draft_is_never_sent(scheduled, monkeypatch):
    monkeypatch.setattr(settings, "coach_approval_required", True)
    draft_upcoming_prompts(scheduled, now_utc=EVENING)
    db.review_draft(scheduled, ATHLETE, MORNING, "2026-09-11",
                    status="skipped", reviewed_by="Coach Rao")
    sent = Outbox()
    assert send_approved_prompts(scheduled, sent, now_utc=NEXT_MORNING) == 0
    assert sent == []


def test_the_athlete_receives_the_coachs_wording_not_the_agents(scheduled, monkeypatch):
    monkeypatch.setattr(settings, "coach_approval_required", True)
    draft_upcoming_prompts(scheduled, now_utc=EVENING)
    db.review_draft(scheduled, ATHLETE, MORNING, "2026-09-11",
                    status="approved", reviewed_by="Coach Rao",
                    body="Morning Priya — knee first, then tell me how you slept.")
    sent = Outbox()
    assert send_approved_prompts(scheduled, sent, now_utc=NEXT_MORNING) == 1
    assert sent[0] == (ATHLETE, "Morning Priya — knee first, then tell me how you slept.")
    assert db.draft(scheduled, ATHLETE, MORNING, "2026-09-11")["status"] == "sent"


def test_an_approved_message_is_sent_once_even_if_the_loop_ticks_again(scheduled, monkeypatch):
    monkeypatch.setattr(settings, "coach_approval_required", True)
    draft_upcoming_prompts(scheduled, now_utc=EVENING)
    db.review_draft(scheduled, ATHLETE, MORNING, "2026-09-11",
                    status="approved", reviewed_by="Coach Rao")
    sent = Outbox()
    send_approved_prompts(scheduled, sent, now_utc=NEXT_MORNING)
    send_approved_prompts(scheduled, sent, now_utc=NEXT_MORNING)
    assert len(sent) == 1


def test_approval_can_be_turned_off_for_an_unattended_deployment(scheduled, monkeypatch):
    monkeypatch.setattr(settings, "coach_approval_required", False)
    sent = Outbox()
    assert send_approved_prompts(scheduled, sent, now_utc=NEXT_MORNING) == 1


def test_a_review_must_record_who_made_it(scheduled):
    draft_upcoming_prompts(scheduled, now_utc=EVENING)
    with pytest.raises(ValueError, match="who made it"):
        db.review_draft(scheduled, ATHLETE, MORNING, "2026-09-11",
                        status="approved", reviewed_by="")


def test_an_empty_message_cannot_be_approved(scheduled):
    draft_upcoming_prompts(scheduled, now_utc=EVENING)
    with pytest.raises(ValueError, match="cannot be empty"):
        db.review_draft(scheduled, ATHLETE, MORNING, "2026-09-11",
                        status="approved", reviewed_by="Coach Rao", body="   ")


# --- the review screen ---------------------------------------------------------


def test_the_queue_shows_why_each_message_is_going_out(scheduled):
    """Approving a message is a judgement about the athlete, so the summary
    travels with the draft rather than living on another screen."""
    for day, weight in [("2026-09-01", 140), ("2026-09-04", 140), ("2026-09-07", 140)]:
        db.insert_entry(scheduled, db.Entry(athlete_id=ATHLETE, kind="set", lift="squat",
                                            sets=3, reps=5, weight_kg=weight, session_date=day))
    draft_upcoming_prompts(scheduled, now_utc=EVENING)

    from datetime import date
    pending = pending_reviews(scheduled, today=date(2026, 9, 10))
    assert len(pending) == 1
    assert pending[0].athlete.display_name == "Priya"
    assert any(f.kind == "stalled" for f in pending[0].athlete.flags)
    assert pending[0].edited is False


def test_reviewed_drafts_leave_the_queue(scheduled):
    from datetime import date
    draft_upcoming_prompts(scheduled, now_utc=EVENING)
    assert len(pending_reviews(scheduled, today=date(2026, 9, 10))) == 1
    db.review_draft(scheduled, ATHLETE, MORNING, "2026-09-11",
                    status="approved", reviewed_by="Coach Rao")
    assert pending_reviews(scheduled, today=date(2026, 9, 10)) == ()


# --- the old unguarded path ----------------------------------------------------


def test_the_legacy_sender_still_exists_but_is_no_longer_wired_in(scheduled):
    """send_due_morning_prompts bypasses the gate. main.py must not call it."""
    from pathlib import Path

    main = (Path(__file__).resolve().parent.parent / "app" / "main.py").read_text()
    assert "send_due_morning_prompts" not in main
    assert "send_approved_prompts" in main
    sent = Outbox()
    assert send_due_morning_prompts(scheduled, sent, now_utc=NEXT_MORNING) == 1
