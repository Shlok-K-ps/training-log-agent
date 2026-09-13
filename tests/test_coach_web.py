"""Tests for the coach web front end."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app.main import _goal_date_from_form, app
from app.storage import db


@pytest.fixture(autouse=True)
def configure_coach(monkeypatch):
    monkeypatch.setattr(settings, "coach_name", "Coach Rao")


def test_landing_page_renders_complete_product_story():
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        html = resp.text
        assert "Training Log Agent" in html
        assert "The coach reads exceptions" in html
        # WhatsApp conversation
        assert "squat 3x5 at 140 today" in html
        assert "Squat — Stalled" in html
        # Core 3-layer architecture
        assert "Gemini Flash" in html
        assert "Single SQLite Timeline" in html
        assert "Pure Python Rules" in html
        # Transparent student engineering note
        assert "student-built engineering project" in html
        # Authority boundaries
        assert "Close an injury flag" in html
        assert "Coach Only" in html
        assert "WHY THIS IS AN AGENT, NOT A CHAT WINDOW" in html
        assert "This system keeps working" in html
        # The desk opens directly; there is no sign-in step
        assert 'href="/coach"' in html
        assert "/coach/login" not in html


def test_retired_sign_in_link_lands_on_the_desk():
    with TestClient(app) as client:
        resp = client.get("/coach/login", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/coach"


def test_sign_out_ends_the_console_session():
    with TestClient(app) as client:
        resp = client.get("/coach/logout", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
        assert "coach_session" in resp.headers.get("set-cookie", "")


def test_coach_console_opens_without_signing_in():
    with TestClient(app) as client:
        resp = client.get("/coach")
        assert resp.status_code == 200
        assert "Coach Rao" in resp.text
        assert "Roster" in resp.text
        assert "Today" in resp.text
        assert "Daily agent loop" in resp.text
        assert "Approval queue" in resp.text
        assert "Load a demo squad" in resp.text or "Remove demo athletes" in resp.text
        assert "Open tutorial" in resp.text
        assert "Sign out" not in resp.text


def test_athlete_directory_is_a_separate_workspace():
    with TestClient(app) as client:
        resp = client.get("/coach/athletes")
        assert resp.status_code == 200
        assert "Current status, recent progress and readiness" in resp.text
        assert 'id="athlete-search"' in resp.text
        assert 'id="athlete-filter"' in resp.text
        assert "/coach/whatsapp" in resp.text
        assert 'name="squat_1rm_kg"' in resp.text
        assert 'name="bench_1rm_kg"' in resp.text
        assert 'name="deadlift_1rm_kg"' in resp.text
        assert 'name="bodyweight_kg"' in resp.text
        assert 'type="date" name="goal_target_date"' in resp.text
        assert "showPicker" in resp.text
        assert ">Choose date</button>" in resp.text
        assert 'min="' in resp.text
        assert 'max="' in resp.text


def test_goal_date_controls_build_a_real_calendar_date():
    assert _goal_date_from_form({"goal_target_date": "2028-02-29"}) == "2028-02-29"
    assert _goal_date_from_form({
        "goal_day": "29", "goal_month": "2", "goal_year": "2028",
    }) == "2028-02-29"
    with pytest.raises(ValueError, match="valid calendar date"):
        _goal_date_from_form({
            "goal_day": "31", "goal_month": "2", "goal_year": "2027",
        })
    with pytest.raises(ValueError, match="day, month, and year"):
        _goal_date_from_form({"goal_day": "12", "goal_month": "", "goal_year": "2027"})


def test_onboarding_accepts_spaced_phone_and_nothing_means_no_injury(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "onboarding.db"))
    with TestClient(app) as client:
        response = client.post("/coach/athletes/register", data={
            "name": "Nikash",
            "athlete_id": "+91 88846 84004",
            "bodyweight_kg": "62",
            "squat_1rm_kg": "60",
            "bench_1rm_kg": "60",
            "deadlift_1rm_kg": "60",
            "training_days": "3",
            "experience": "novice",
            "goal_lift": "bench press",
            "goal_target_kg": "80",
            "goal_target_date": "2028-02-29",
            "injury_note": "nothing",
        })
        assert response.status_code == 200
        assert "Nikash added" in response.text

    conn = db.connect()
    try:
        assert "+918884684004" in db.list_athletes(conn)
        assert db.injury_state(conn, "+918884684004")[0] is False
    finally:
        conn.close()


def test_clearance_review_rejects_self_clearance_and_records_source(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "clearance.db"))
    conn = db.connect()
    try:
        db.init_db(conn)
        db.register_athlete(
            conn, "+919812340001", "Priya Kulkarni", on="2026-09-10",
            injury_note="left knee pain",
        )
        db.request_injury_clearance(
            conn, "+919812340001", note="feels better", on="2026-09-11"
        )
    finally:
        conn.close()

    with TestClient(app) as client:
        self_clearance = client.post("/coach/clear-injury", data={
            "athlete_id": "+919812340001",
            "clearance_source": "Priya Kulkarni",
            "reason": "I feel fine",
            "independent_confirmation": "confirmed",
        })
        assert self_clearance.status_code == 200
        assert "athlete cannot be their own clearance source" in self_clearance.text

        cleared = client.post("/coach/clear-injury", data={
            "athlete_id": "+919812340001",
            "clearance_source": "Dr Mehta, sports physio",
            "reason": "Pain-free assessment with a staged return-to-load limit",
            "independent_confirmation": "confirmed",
        })
        assert cleared.status_code == 200
        assert "Injury flag cleared" in cleared.text

    conn = db.connect()
    try:
        assert db.injury_state(conn, "+919812340001")[0] is False
        latest = conn.execute(
            "SELECT injury_clearance_reason FROM entries WHERE athlete_id = ? "
            "ORDER BY id DESC LIMIT 1",
            ("+919812340001",),
        ).fetchone()
        assert "Dr Mehta" in latest["injury_clearance_reason"]
        assert "Coach Rao" in latest["injury_clearance_reason"]
    finally:
        conn.close()


def test_whatsapp_desk_is_a_separate_workspace():
    with TestClient(app) as client:
        resp = client.get("/coach/whatsapp")
        assert resp.status_code == 200
        assert "Messaging Desk" in resp.text
        assert "New feedback" in resp.text
        assert "Needs approval" in resp.text
        assert "Scheduled" in resp.text
        assert "Sent" in resp.text
        assert "/coach/whatsapp/bulk-approve" in client.get(
            "/coach/whatsapp?tab=approval"
        ).text


def test_goal_analytics_is_a_separate_workspace():
    with TestClient(app) as client:
        resp = client.get("/coach/analytics")
        assert resp.status_code == 200
        assert "Goal Analytics" in resp.text
        assert "Ahead of track" in resp.text
        assert "On track" in resp.text
        assert "Lagging" in resp.text


def test_outbox_now_lives_in_the_messaging_desk():
    with TestClient(app) as client:
        resp = client.get("/coach/outbox", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/coach/whatsapp?tab=approval"
        page = client.get("/coach/outbox")
        assert page.status_code == 200
        assert "Needs approval" in page.text


def test_privacy_and_terms_pages_render_with_styling():
    with TestClient(app) as client:
        privacy_resp = client.get("/privacy")
        assert privacy_resp.status_code == 200
        assert "Privacy Policy" in privacy_resp.text
        assert "OAuth tokens and saved places are encrypted at rest" in privacy_resp.text

        terms_resp = client.get("/terms")
        assert terms_resp.status_code == 200
        assert "Terms of Service" in terms_resp.text
        assert "not medical care" in terms_resp.text
