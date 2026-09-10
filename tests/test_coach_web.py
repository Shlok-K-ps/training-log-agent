"""Tests for the coach web front end and authentication flow."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.coach import COOKIE_NAME
from app.config import settings
from app.main import app

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
        assert "/coach/logout" in resp.text


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
