"""Tests for the coach web front end and authentication flow."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.coach import COOKIE_NAME
from app.config import settings
from app.main import _goal_date_from_form, app
from app.storage import db

TOKEN = "s3cret-coach-token"


@pytest.fixture(autouse=True)
def configure_coach_token(monkeypatch):
    monkeypatch.setattr(settings, "coach_access_token", TOKEN)
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


def test_login_page_renders_form():
    with TestClient(app) as client:
        resp = client.get("/coach/login")
        assert resp.status_code == 200
        assert '<form method="post" action="/coach/login">' in resp.text
        assert 'name="token"' in resp.text


def test_login_with_invalid_token_returns_401():
    with TestClient(app) as client:
        resp = client.post("/coach/login", data={"token": "wrong-token"})
        assert resp.status_code == 401
        assert "Invalid coach token" in resp.text


def test_login_with_valid_token_sets_cookie_and_redirects():
    with TestClient(app) as client:
        resp = client.post("/coach/login", data={"token": TOKEN}, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/coach"
        assert COOKIE_NAME in resp.cookies
        assert resp.cookies[COOKIE_NAME] == TOKEN


def test_unauthenticated_coach_console_redirects_to_login():
    with TestClient(app) as client:
        resp = client.get("/coach", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/coach/login"


def test_authenticated_coach_console_with_cookie():
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, TOKEN)
        resp = client.get("/coach")
        assert resp.status_code == 200
        assert "Coach Rao" in resp.text
        assert "Roster" in resp.text
        assert "Overview" in resp.text
        assert "Daily agent loop" in resp.text
        assert "Approval queue" in resp.text
        assert "Load a demo squad" in resp.text or "Remove demo athletes" in resp.text
        assert "Open tutorial" in resp.text
        assert "/coach/logout" in resp.text


def test_athlete_directory_is_a_separate_authenticated_workspace():
    with TestClient(app) as client:
        assert client.get("/coach/athletes", follow_redirects=False).status_code == 303
        client.cookies.set(COOKIE_NAME, TOKEN)
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
        assert 'name="goal_day"' in resp.text
        assert 'name="goal_month"' in resp.text
        assert 'name="goal_year"' in resp.text


def test_goal_date_controls_build_a_real_calendar_date():
    assert _goal_date_from_form({
        "goal_day": "29", "goal_month": "2", "goal_year": "2028",
    }) == "2028-02-29"
    with pytest.raises(ValueError, match="valid calendar date"):
        _goal_date_from_form({
            "goal_day": "31", "goal_month": "2", "goal_year": "2027",
        })
    with pytest.raises(ValueError, match="day, month, and year"):
        _goal_date_from_form({"goal_day": "12", "goal_month": "", "goal_year": "2027"})


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
        client.cookies.set(COOKIE_NAME, TOKEN)
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


def test_whatsapp_desk_is_a_separate_authenticated_workspace():
    with TestClient(app) as client:
        assert client.get("/coach/whatsapp", follow_redirects=False).status_code == 303
        client.cookies.set(COOKIE_NAME, TOKEN)
        resp = client.get("/coach/whatsapp")
        assert resp.status_code == 200
        assert "WhatsApp Desk" in resp.text
        assert "New feedback" in resp.text
        assert "Needs approval" in resp.text
        assert "Scheduled" in resp.text
        assert "Sent" in resp.text
        assert "/coach/whatsapp/bulk-approve" in client.get(
            "/coach/whatsapp?tab=approval"
        ).text


def test_goal_analytics_is_a_separate_authenticated_workspace():
    with TestClient(app) as client:
        assert client.get("/coach/analytics", follow_redirects=False).status_code == 303
        client.cookies.set(COOKIE_NAME, TOKEN)
        resp = client.get("/coach/analytics")
        assert resp.status_code == 200
        assert "Goal Analytics" in resp.text
        assert "Ahead of track" in resp.text
        assert "On track" in resp.text
        assert "Lagging" in resp.text


def test_authenticated_coach_console_with_query_param_fallback():
    with TestClient(app) as client:
        resp = client.get(f"/coach?token={TOKEN}", follow_redirects=False)
        assert resp.status_code == 200
        assert "Coach Rao" in resp.text
        # Also sets cookie for future visits
        assert COOKIE_NAME in resp.cookies


def test_invalid_query_param_returns_403():
    with TestClient(app) as client:
        resp = client.get("/coach?token=wrong-token")
        assert resp.status_code == 403
        assert "Invalid coach token" in resp.text


def test_logout_clears_cookie_and_redirects():
    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, TOKEN)
        resp = client.get("/coach/logout", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/coach/login"


def test_outbox_requires_authentication():
    with TestClient(app) as client:
        resp = client.get("/coach/outbox", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/coach/login"

        client.cookies.set(COOKIE_NAME, TOKEN)
        resp = client.get("/coach/outbox")
        assert resp.status_code == 200
        assert "Coach Rao" in resp.text
        assert "Outbox" in resp.text


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
