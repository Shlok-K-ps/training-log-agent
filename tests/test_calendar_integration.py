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
    payload, signature = token.split(".", 1)
    changed_payload = ("A" if payload[0] != "A" else "B") + payload[1:]
    with pytest.raises(CalendarIntegrationError, match="Invalid"):
        signer.verify(changed_payload + "." + signature, now=NOW)


def test_noncanonical_base64_signature_is_rejected_even_if_bytes_match():
    signer = OAuthStateSigner("a-secret-longer-than-twenty-four-characters")
    token = signer.issue("+91999", now=NOW)
    payload, signature = token.split(".", 1)
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    original = alphabet.index(signature[-1])
    alias = alphabet[(original & 0b111100) | ((original + 1) & 0b000011)]
    if alias == signature[-1]:
        alias = alphabet[(original & 0b111100) | ((original + 2) & 0b000011)]
    with pytest.raises(CalendarIntegrationError, match="Invalid"):
        signer.verify(payload + "." + signature[:-1] + alias, now=NOW)


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


def test_saved_place_write_fails_closed_without_an_encryption_key(conn, monkeypatch):
    monkeypatch.setattr(settings, "calendar_token_encryption_key", "")
    with pytest.raises(RuntimeError, match="disabled"):
        db.save_place(conn, "+91999", "home", "42 Private Road")
    assert conn.execute("SELECT COUNT(*) FROM saved_places").fetchone()[0] == 0


def test_legacy_plaintext_place_is_migrated_and_never_read_without_a_key(conn, monkeypatch):
    conn.execute(
        """
        INSERT INTO saved_places (athlete_id, label, location, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        ("+91999", "home", "42 Legacy Road", NOW.isoformat()),
    )
    conn.commit()
    assert db.saved_places(conn, "+91999")["home"] == "42 Legacy Road"
    raw = conn.execute("SELECT location FROM saved_places").fetchone()[0]
    assert raw.startswith("fernet:") and "Legacy Road" not in raw
    monkeypatch.setattr(settings, "calendar_token_encryption_key", "")
    with pytest.raises(RuntimeError, match="cannot be read"):
        db.saved_places(conn, "+91999")


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
