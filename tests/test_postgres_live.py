"""The whole agent loop on a real, disposable Postgres, through the real service.

Runs only when TEST_DATABASE_URL points at a database you are happy to lose:
it drops and recreates this application's tables (and nothing else).

    TEST_DATABASE_URL=postgresql://... python -m pytest tests/test_postgres_live.py

It checks schema creation and repeated initialisation, athlete registration and
Telegram pairing, coach identity, plan and autopilot through the console,
duplicate signed ticks, athlete webhooks, a coach button decision, the console
pages, and a simulated restart with fresh connections — then that nothing was
duplicated and everything survived.
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import access, deployment
from app.casework import clock
from app.storage import db, pg

URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_DATABASE_URL to a disposable Postgres database")

APP_TABLES = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", db.SCHEMA)
ROUTINE, INJURED = "+919812340001", "+919812340003"
CHATS = {ROUTINE: 7001, INJURED: 7003}
COACH_CHAT = 9001
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "webhook_secret-123"}


def _drop_app_tables() -> None:
    import psycopg

    with psycopg.connect(URL, autocommit=True) as raw:
        for table in APP_TABLES:
            raw.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    pg._ready_urls.discard(URL)


def _one(sql: str, *params):
    conn = db.connect()
    try:
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


@pytest.fixture()
def live(monkeypatch):
    from app import main
    from app.config import settings

    for name, value in {
        "database_url": URL,
        "public_base_url": "https://agent.example.com",
        "coach_link_secret": "link-secret",
        "agent_tick_secret": "tick-secret",
        "coach_setup_code": "setup-code-7731",
        "telegram_bot_token": "123456:test-token",
        "telegram_bot_username": "PowerCoachTestBot",
        "telegram_webhook_secret": "webhook_secret-123",
        "telegram_link_secret": "pairing-secret",
        "coach_name": "Coach Rao",
        "gemini_api_key": "",
        "enable_agent_loop": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    sent: list[dict] = []

    def fake_send(chat_id, body, reply_markup=None):
        sent.append({"chat": str(chat_id), "body": body, "markup": reply_markup})
        # Telegram numbers messages uniquely within a chat across both directions, so
        # simulated outbound ids use their own range and never collide with inbound ones.
        return f"telegram:{chat_id}:{900000 + len(sent)}"

    monkeypatch.setattr(main.telegram, "send_outbound", fake_send)
    monkeypatch.setattr(main.telegram, "answer_callback_query", lambda *_: None)
    monkeypatch.setattr(main.telegram, "configure_webhook", lambda: None)
    moment = {"now": datetime(2026, 9, 14, 2, 1, tzinfo=timezone.utc)}  # 07:31 in Kolkata
    monkeypatch.setattr(clock, "utcnow", lambda: moment["now"])
    main.get_model_client.cache_clear()
    _drop_app_tables()
    yield main, sent, moment
    _drop_app_tables()


def _tick(client):
    stamp = str(int(time.time()))
    return client.post("/internal/agent/tick", headers={
        "X-Agent-Timestamp": stamp, "X-Agent-Signature": access.tick_signature(stamp)})


def _say(client, chat: int, text: str, message_id: int):
    return client.post("/webhook/telegram", headers=HEADERS, json={"message": {
        "message_id": message_id, "text": text, "chat": {"id": chat, "type": "private"}}})


def test_onboarding_on_real_postgres(live):
    """Simple registration, generated IDs, pairing, the checklist and a real case, all on Postgres."""
    from urllib.parse import parse_qs, unquote, urlparse

    from bs4 import BeautifulSoup

    from app.channels import telegram

    main, sent, _ = live
    with TestClient(main.app) as client:
        assert "This is your private real-agent console." in client.get("/coach").text

        landed = client.post("/coach/athletes/register", data={
            "name": "Priya Nair", "timezone": "Asia/Kolkata", "checkin_time": "07:30", "training_time": "18:00"})
        assert landed.status_code == 200 and "Priya Nair added" in landed.text
        athlete_url = urlparse(str(landed.url)).path
        athlete_id = athlete_url.rsplit("/", 1)[1]
        assert db.is_generated_athlete_id(athlete_id)
        assert _one("SELECT COUNT(*) FROM entries WHERE athlete_id = ?", athlete_id) == 2

        invite = BeautifulSoup(landed.text, "html.parser").select_one("button[data-copy]")["data-copy"]
        token = unquote(parse_qs(urlparse(invite).query)["start"][0])
        assert telegram.athlete_from_pairing_token(token)[0] == athlete_id

        def checklist(path: str = "/coach") -> dict[str, str]:
            soup = BeautifulSoup(client.get(path).text, "html.parser")
            return dict(item["data-step-state"].split(":") for item in soup.select("[data-step-state]"))

        assert checklist() == {"coach": "todo", "athlete": "done", "paired": "todo", "plan": "todo",
                               "autopilot": "todo", "ready": "todo"}

        # The athlete opens the invite and presses Start: the real webhook pairs the chat.
        paired = _say(client, 7101, f"/start {token}", 1)
        assert paired.status_code == 200 and sent[-1]["body"].startswith("Connected to Power AI as Priya Nair")
        assert client.get(f"{athlete_url}/status.json").json()["telegram_connected"] is True
        _say(client, COACH_CHAT, "/coach setup-code-7731", 2)
        client.post(f"{athlete_url}/plan", data={"weekday": "0", "lift": "squat", "sets": "4", "reps": "5", "rpe": "7"})
        client.post(f"{athlete_url}/autopilot", data={"enabled": "on"})
        assert checklist() == {}, "a finished setup is hidden from Today"
        assert "Set up your agent" not in client.get("/coach").text
        assert set(checklist("/coach/setup").values()) == {"done"} and len(checklist("/coach/setup")) == 6

        header = BeautifulSoup(client.get(athlete_url).text, "html.parser").select_one("#agent-status")
        assert header.select_one(".status-badge").get_text(strip=True) == "Ready"

        cases_before = _one("SELECT COUNT(*) FROM agent_cases")
        simulated = client.get(f"{athlete_url}/simulate").text
        assert "Safe simulated test. Nothing was sent and nothing was saved." in simulated
        assert _one("SELECT COUNT(*) FROM agent_cases") == cases_before == 0

        report = _tick(client).json()
        assert report["opened"] == 1 and report["actions"] == 1
        assert _tick(client).json()["actions"] == 0
        assert _one("SELECT athlete_id FROM agent_cases") == athlete_id
        assert _one("SELECT state FROM agent_cases") == "awaiting_checkin"
        assert sent[-1]["chat"] == "7101" and "training day" in sent[-1]["body"]

        _say(client, 7101, "slept 8h readiness 8", 3)
        assert _one("SELECT state FROM agent_cases") == "awaiting_outcome"
        assert "Squat 4×5 @ RPE 7" in sent[-1]["body"]
        assert "Awaiting" not in BeautifulSoup(client.get(athlete_url).text, "html.parser").select_one(
            '[data-status="next-action"]').get_text()


def test_the_agent_loop_survives_restarts_on_real_postgres(live):
    main, sent, moment = live
    assert deployment.status()["storage_backend"] == "postgres"

    # Schema creation, then initialisation again on a fresh connection.
    for _ in range(2):
        pg._ready_urls.discard(URL)
        conn = db.connect()
        try:
            db.init_db(conn)
        finally:
            conn.close()
    assert _one("SELECT COUNT(*) FROM agent_cases") == 0

    conn = db.connect()
    try:
        for athlete, name in ((ROUTINE, "Priya Kulkarni"), (INJURED, "Vikram Iyer")):
            db.register_athlete(conn, athlete, name, on="2026-09-01")
            db.insert_entry(conn, db.Entry(athlete_id=athlete, kind="status", timezone="Asia/Kolkata",
                                           morning_checkin_time="07:30", training_time="18:00",
                                           session_date="2026-09-01"))
            db.link_telegram_chat(conn, chat_id=str(CHATS[athlete]), athlete_id=athlete)
    finally:
        conn.close()

    with TestClient(main.app) as client:
        health = client.get("/health").json()
        assert (health["status"], health["agent_loop"], health["agent_memory_durable"]) == ("ok", "active", True)

        _say(client, COACH_CHAT, "/coach setup-code-7731", 1)
        assert sent[-1]["body"].startswith("Linked.")
        for athlete in (ROUTINE, INJURED):
            for weekday in range(7):
                client.post(f"/coach/athlete/{athlete}/plan", data={
                    "weekday": str(weekday), "lift": "squat", "sets": "4", "reps": "5", "rpe": "7"})
            client.post(f"/coach/athlete/{athlete}/autopilot", data={"enabled": "on"})

        reports = [_tick(client).json() for _ in range(3)]
        assert sum(report["actions"] for report in reports) == 2

        _say(client, CHATS[ROUTINE], "slept 8h readiness 8", 10)
        _say(client, CHATS[ROUTINE], "slept 8h readiness 8", 10)  # Telegram retry
        _say(client, CHATS[INJURED], "slept 7h readiness 7", 11)
        _say(client, CHATS[INJURED], "tweaked my knee, pain on stairs", 12)
        alert = next(item for item in reversed(sent) if item["chat"] == str(COACH_CHAT) and item["markup"])
        rest = next(button[0]["callback_data"] for button in alert["markup"]["inline_keyboard"]
                    if button[0].get("text") == "Rest today")
        decided = client.post("/webhook/telegram", headers=HEADERS, json={"callback_query": {
            "id": "cb-1", "data": rest, "message": {"chat": {"id": COACH_CHAT}}}})
        assert decided.text == "decided"

        today = client.get("/coach")
        assert today.status_code == 200 and "What happens next" in today.text
        case_id = _one("SELECT id FROM agent_cases WHERE athlete_id = ?", ROUTINE)
        assert client.get(f"/coach/case/{case_id}").status_code == 200
        assert client.get(f"/coach/athlete/{ROUTINE}").status_code == 200

    messages_before_restart = len(sent)
    ledger_before_restart = _one("SELECT COUNT(*) FROM whatsapp_messages")

    # Restart: a new process has no schema cache and opens new connections.
    pg._ready_urls.discard(URL)
    with TestClient(main.app) as client:
        for _ in range(2):
            assert _tick(client).status_code == 200
        assert len(sent) == messages_before_restart, "no message repeated after the restart"
        assert _one("SELECT COUNT(*) FROM whatsapp_messages") == ledger_before_restart

        moment["now"] = datetime(2026, 9, 14, 15, 1, tzinfo=timezone.utc)  # 20:31 in Kolkata
        _tick(client)
        _tick(client)
        _say(client, CHATS[ROUTINE], "done", 20)

    assert _one("SELECT COUNT(*) FROM agent_cases") == 2
    assert _one("SELECT state FROM agent_cases WHERE athlete_id = ?", ROUTINE) == "closed"
    assert _one("SELECT outcome FROM agent_cases WHERE athlete_id = ?", ROUTINE) == "done"
    assert _one("SELECT outcome FROM agent_cases WHERE athlete_id = ?", INJURED) == "rest_day"
    assert _one("SELECT chat_id FROM coach_channel WHERE id = 1") == str(COACH_CHAT)
    assert _one("SELECT COUNT(*) FROM plan_sessions WHERE retired_at IS NULL") == 14
    assert _one("SELECT COUNT(*) FROM agent_settings WHERE autopilot = 1") == 2
    assert _one("SELECT COUNT(idempotency_key) FROM agent_events") == _one(
        "SELECT COUNT(DISTINCT idempotency_key) FROM agent_events")
    assert _one(
        "SELECT COUNT(*) FROM (SELECT athlete_id, message_kind FROM whatsapp_messages "
        "WHERE direction = 'outbound' AND message_kind LIKE 'agent:%' "
        "GROUP BY athlete_id, message_kind HAVING COUNT(*) > 1) duplicates"
    ) == 0
    assert _one("SELECT COUNT(*) FROM whatsapp_messages WHERE provider_sid = ?", "telegram:7001:10") == 1
