"""Composition helpers kept outside the pure decision modules."""

from __future__ import annotations

import sqlite3
from urllib.parse import urlencode

from app.config import settings
from app.integrations.google_calendar import (
    CalendarIntegrationError,
    GoogleCalendarClient,
    GoogleCalendarOAuth,
    OAuthStateSigner,
    TokenCipher,
)
from app.integrations.google_routes import GoogleRoutesClient
from app.scheduling.service import SchedulingService


def state_signer() -> OAuthStateSigner:
    return OAuthStateSigner(settings.oauth_state_secret)


def calendar_oauth() -> GoogleCalendarOAuth:
    return GoogleCalendarOAuth(
        client_id=settings.google_calendar_client_id,
        client_secret=settings.google_calendar_client_secret,
        redirect_uri=settings.google_calendar_redirect_uri,
    )


def calendar_client(conn: sqlite3.Connection) -> GoogleCalendarClient:
    return GoogleCalendarClient(
        conn,
        oauth=calendar_oauth(),
        cipher=TokenCipher(settings.calendar_token_encryption_key),
    )


def scheduling_service(conn: sqlite3.Connection) -> SchedulingService:
    if not settings.calendar_configured:
        raise CalendarIntegrationError("Calendar and routing credentials are not configured")
    return SchedulingService(
        calendar_client(conn), GoogleRoutesClient(settings.google_maps_api_key)
    )


def connection_link(athlete_id: str) -> str | None:
    if not settings.calendar_configured:
        return None
    token = state_signer().issue(athlete_id)
    return (
        settings.public_base_url.rstrip("/")
        + "/integrations/google/calendar/start?"
        + urlencode({"token": token})
    )
