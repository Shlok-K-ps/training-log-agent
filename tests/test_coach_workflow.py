"""The coach's approval loop through the console: decisions, approvals, schedule."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.scheduling.outbox import FEEDBACK_REPLY, send_approved_notes
from app.storage import db

ATHLETE = "+919812340001"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "workflow.db"))
    monkeypatch.setattr(settings, "coach_name", "Coach Rao")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    conn = db.connect()
    try:
        db.init_db(conn)
        db.register_athlete(
            conn, ATHLETE, "Priya Kulkarni", on=date.today().isoformat(),
            injury_note="left knee pain when squatting",
        )
    finally:
        conn.close()
    with TestClient(app) as test_client:
        yield test_client


def test_a_coach_action_redirects_so_a_refresh_cannot_repeat_it(client):
    response = client.post(
        f"/coach/athlete/{ATHLETE}/message", data={"body": "Film your top set."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/coach/athlete/")

    landed = client.get(response.headers["location"])
    assert "Queued. It goes out" in landed.text
    assert "Queued. It goes out" not in client.get(f"/coach/athlete/{ATHLETE}").text, (
        "the confirmation is shown once, not on every later visit"
    )


def test_two_notes_on_the_same_day_are_both_kept_and_sent(client):
    for body in ("First note: film your top set.", "Second note: add a pause squat."):
        client.post(f"/coach/athlete/{ATHLETE}/message", data={"body": body})

    scheduled = client.get("/coach/whatsapp?tab=scheduled").text
    assert "First note" in scheduled
    assert "Second note" in scheduled

    conn = db.connect()
    try:
        sent: list[str] = []
        tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
        assert send_approved_notes(conn, lambda _athlete, body: sent.append(body), now_utc=tomorrow) == 2
    finally:
        conn.close()
    assert sorted(sent) == ["First note: film your top set.", "Second note: add a pause squat."]


def test_the_injury_plan_shows_its_message_and_marks_the_choice(client):
    today_page = client.get("/coach").text
    assert "Choose an injury plan" in today_page

    page = client.get(f"/coach/athlete/{ATHLETE}").text
    assert 'id="injury-plan"' in page
    assert "Training update from Coach Rao" in page, "each option carries the message it sends"

    conn = db.connect()
    try:
        entry_id = db.open_injury_entry_id(conn, ATHLETE)
    finally:
        conn.close()

    response = client.post(
        f"/coach/athlete/{ATHLETE}/injury-plan",
        data={
            "injury_entry_id": str(entry_id),
            "option_code": "unaffected_only",
            "body": "Priya, upper body only this week with an RPE 6 cap.",
        },
    )
    assert response.status_code == 200
    assert "is now the plan" in response.text
    assert "Current plan" in response.text
    assert "Choose an injury plan" not in client.get("/coach").text

    scheduled = client.get("/coach/whatsapp?tab=scheduled").text
    assert "Injury plan" in scheduled
    assert "upper body only this week" in scheduled, "the coach's edited wording is what is scheduled"

    conn = db.connect()
    try:
        assert db.injury_state(conn, ATHLETE)[0] is True, "choosing a plan never clears the injury"
        assert db.latest_injury_plan_decision(conn, ATHLETE)["option_code"] == "unaffected_only"
    finally:
        conn.close()


def test_an_injury_plan_needs_a_chosen_option(client):
    conn = db.connect()
    try:
        entry_id = db.open_injury_entry_id(conn, ATHLETE)
    finally:
        conn.close()
    response = client.post(
        f"/coach/athlete/{ATHLETE}/injury-plan",
        data={"injury_entry_id": str(entry_id), "option_code": ""},
    )
    assert "Choose one of the injury plans first" in response.text


def test_approved_replies_appear_in_scheduled(client):
    today = date.today().isoformat()
    conn = db.connect()
    try:
        db.create_draft(conn, ATHLETE, FEEDBACK_REPLY + "SM1", today, "Hold squat at 130 kg today.")
        db.review_draft(
            conn, ATHLETE, FEEDBACK_REPLY + "SM1", today,
            status="approved", reviewed_by="Coach Rao",
        )
    finally:
        conn.close()
    scheduled = client.get("/coach/whatsapp?tab=scheduled").text
    assert "Hold squat at 130 kg today." in scheduled
    assert "Reply to athlete" in scheduled
    assert "Priya Kulkarni" in scheduled, "athletes appear by name, not phone number"


def test_a_review_returns_only_to_a_console_page(client):
    today = date.today().isoformat()
    conn = db.connect()
    try:
        for suffix in ("A", "B"):
            db.create_draft(conn, ATHLETE, FEEDBACK_REPLY + suffix, today, f"Reply {suffix}")
    finally:
        conn.close()

    home = client.post(
        "/coach/whatsapp/review",
        data={"athlete_id": ATHLETE, "message_kind": FEEDBACK_REPLY + "A", "local_date": today,
              "decision": "approved", "body": "Reply A", "return_to": "/coach"},
        follow_redirects=False,
    )
    assert home.headers["location"] == "/coach"

    elsewhere = client.post(
        "/coach/whatsapp/review",
        data={"athlete_id": ATHLETE, "message_kind": FEEDBACK_REPLY + "B", "local_date": today,
              "decision": "skipped", "body": "Reply B", "return_to": "https://example.com/"},
        follow_redirects=False,
    )
    assert elsewhere.headers["location"] == "/coach/whatsapp?tab=approval"


def test_today_puts_drafted_messages_in_the_approval_queue(client):
    today = date.today().isoformat()
    conn = db.connect()
    try:
        db.create_draft(conn, ATHLETE, FEEDBACK_REPLY + "SM9", today, "Knee first: how did it feel?")
    finally:
        conn.close()
    page = client.get("/coach").text
    assert 'data-kind="approval"' in page and "Needs you" in page
    assert "Knee first: how did it feel?" in page
    assert 'name="return_to" value="/coach"' in page
