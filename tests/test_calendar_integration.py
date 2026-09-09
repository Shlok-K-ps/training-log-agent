from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet

from app.integrations.google_calendar import (
    CalendarIntegrationError,
    GoogleCalendarOAuth,
    OAuthStateSigner,
    SCOPES,
    TokenCipher,
)
from app.config import settings
from app.storage import db


NOW = datetime(2026, 9, 9, 8, 0, tzinfo=timezone.utc)


def test_oauth_state_is_signed_short_lived_and_bound_to_the_athlete():
    signer = OAuthStateSigner("a-secret-longer-than-twenty-four-characters")
    token = signer.issue("+91999", now=NOW)
    assert signer.verify(token, now=NOW + timedelta(minutes=14)) == "+91999"
    with pytest.raises(CalendarIntegrationError, match="expired"):
        signer.verify(token, now=NOW + timedelta(minutes=16))
    with pytest.raises(CalendarIntegrationError, match="Invalid"):
        signer.verify(token[:-1] + ("A" if token[-1] != "A" else "B"), now=NOW)


def test_tokens_are_encrypted_at_rest():
    cipher = TokenCipher(Fernet.generate_key().decode())
    encrypted = cipher.encrypt("secret-access-token")
    assert "secret-access-token" not in encrypted
    assert cipher.decrypt(encrypted) == "secret-access-token"


def test_saved_places_are_encrypted_when_the_integration_key_is_configured(conn, monkeypatch):
    monkeypatch.setattr(settings, "calendar_token_encryption_key", Fernet.generate_key().decode())
    db.save_place(conn, "+91999", "home", "42 Private Road")
    raw = conn.execute("SELECT location FROM saved_places").fetchone()[0]
    assert raw.startswith("fernet:") and "Private Road" not in raw
    assert db.saved_places(conn, "+91999")["home"] == "42 Private Road"


def test_authorization_requests_read_only_events_and_an_app_owned_calendar():
    oauth = GoogleCalendarOAuth(
        client_id="client",
        client_secret="secret",
        redirect_uri="https://coach.example/callback",
    )
    query = parse_qs(urlparse(oauth.authorization_url("signed-state")).query)
    assert set(query["scope"][0].split()) == set(SCOPES)
    assert query["access_type"] == ["offline"]
    assert query["state"] == ["signed-state"]
    assert "https://www.googleapis.com/auth/calendar" not in set(query["scope"][0].split())
