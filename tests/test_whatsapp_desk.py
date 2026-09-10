"""WhatsApp Desk persistence and the guarded unchanged-message shortcut."""

from __future__ import annotations

from app.scheduling.outbox import COACH_NOTE, MORNING
from app.storage import db


def _athlete(conn, athlete_id: str = "+911") -> None:
    db.insert_entry(
        conn,
        db.Entry(
            athlete_id=athlete_id, athlete_name="Priya", kind="status",
            timezone="Asia/Kolkata", morning_checkin_time="08:00",
            session_date="2026-09-10",
        ),
    )


def test_whatsapp_message_sid_makes_webhook_retries_idempotent(conn):
    first = db.record_whatsapp_message(
        conn, athlete_id="+911", provider_sid="SM123", direction="inbound",
        body="Slept seven hours", status="received", message_kind="athlete_feedback",
    )
    retry = db.record_whatsapp_message(
        conn, athlete_id="+911", provider_sid="SM123", direction="inbound",
        body="Slept seven hours", status="received", message_kind="athlete_feedback",
    )
    assert first == retry
    assert len(db.whatsapp_messages(conn)) == 1


def test_delivery_callback_updates_the_recorded_message(conn):
    db.record_whatsapp_message(
        conn, athlete_id="+911", provider_sid="SM456", direction="outbound",
        body="Morning check-in", status="queued", message_kind=MORNING,
    )
    assert db.update_whatsapp_status(conn, "SM456", "delivered") is True
    assert db.whatsapp_message_by_sid(conn, "SM456")["status"] == "delivered"
    assert db.update_whatsapp_status(conn, "unknown", "read") is False


def test_only_untouched_morning_drafts_are_bulk_eligible(conn):
    _athlete(conn)
    db.create_draft(conn, "+911", MORNING, "2026-09-11", "How did you sleep?")
    morning = db.draft(conn, "+911", MORNING, "2026-09-11")
    assert db.draft_is_bulk_eligible(conn, morning) is True

    db.create_draft(conn, "+911", COACH_NOTE, "2026-09-11", "Custom note")
    note = db.draft(conn, "+911", COACH_NOTE, "2026-09-11")
    assert db.draft_is_bulk_eligible(conn, note) is False


def test_new_athlete_evidence_invalidates_bulk_approval(conn):
    _athlete(conn)
    db.create_draft(conn, "+911", MORNING, "2026-09-11", "How did you sleep?")
    db.insert_entry(
        conn,
        db.Entry(
            athlete_id="+911", kind="status", injured=True,
            injury_note="knee pain", session_date="2026-09-10",
        ),
    )
    row = db.draft(conn, "+911", MORNING, "2026-09-11")
    assert db.draft_is_bulk_eligible(conn, row) is False
    assert db.bulk_approve_unchanged(conn, reviewed_by="Coach Rao") == 0
    assert db.draft(conn, "+911", MORNING, "2026-09-11")["status"] == "pending"


def test_bulk_approval_approves_only_the_safe_subset(conn):
    _athlete(conn, "+911")
    _athlete(conn, "+922")
    db.create_draft(conn, "+911", MORNING, "2026-09-11", "Morning A")
    db.create_draft(conn, "+922", MORNING, "2026-09-11", "Morning B")
    db.insert_entry(
        conn,
        db.Entry(athlete_id="+922", kind="status", readiness=3, session_date="2026-09-10"),
    )

    assert db.bulk_approve_unchanged(conn, reviewed_by="Coach Rao") == 1
    assert db.draft(conn, "+911", MORNING, "2026-09-11")["status"] == "approved"
    assert db.draft(conn, "+922", MORNING, "2026-09-11")["status"] == "pending"


def test_conversation_list_prefers_latest_inbound_feedback(conn):
    _athlete(conn)
    db.record_whatsapp_message(
        conn, athlete_id="+911", direction="inbound", body="Readiness is 5",
        status="received", provider_sid="SM789", occurred_at="2026-09-10T06:00:00+00:00",
    )
    conversations = db.whatsapp_conversations(conn)
    assert conversations[0]["athlete_name"] == "Priya"
    assert conversations[0]["body"] == "Readiness is 5"
    assert conversations[0]["unread_count"] == 1

    db.mark_whatsapp_conversation_reviewed(conn, "+911")
    assert db.whatsapp_conversations(conn)[0]["unread_count"] == 0

    db.record_whatsapp_message(
        conn, athlete_id="+911", direction="inbound", body="Knee feels sore",
        status="received", provider_sid="SM790", occurred_at="2026-09-10T07:00:00+00:00",
    )
    assert db.whatsapp_conversations(conn)[0]["unread_count"] == 1
