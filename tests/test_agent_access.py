"""Coach identity without passwords, and the signed agent clock."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app import access
from app.casework import store
from app.storage import db


@pytest.fixture()
def deployed(tmp_path, monkeypatch):
    from app import main
    from app.config import settings

    monkeypatch.setattr(settings, "database_path", str(tmp_path / "access.db"))
    monkeypatch.setattr(settings, "public_base_url", "https://agent.example.com")
    monkeypatch.setattr(settings, "coach_link_secret", "link-secret-for-tests")
    monkeypatch.setattr(settings, "agent_tick_secret", "tick-secret-for-tests")
    monkeypatch.setattr(settings, "coach_setup_code", "setup-code-7731")
    monkeypatch.setattr(settings, "telegram_bot_token", "123456:test-token")
    monkeypatch.setattr(settings, "telegram_bot_username", "PowerCoachTestBot")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "webhook_secret-123")
    monkeypatch.setattr(settings, "telegram_link_secret", "pairing-secret")
    monkeypatch.setattr(main.telegram, "configure_webhook", lambda: None)
    sent: list[tuple[str, str]] = []

    def fake_send(chat_id, body, reply_markup=None):
        sent.append((str(chat_id), body))
        return f"telegram:{chat_id}:{len(sent)}"

    monkeypatch.setattr(main.telegram, "send_outbound", fake_send)
    monkeypatch.setattr(main.telegram, "answer_callback_query", lambda *_: None)
    return main, settings, sent


def test_console_tokens_are_signed_scoped_and_expire(deployed):
    token = access.console_token("/coach/athletes", now=1000)
    assert access.verify_console_token(token, now=1001) == "/coach/athletes"
    assert access.verify_console_token(token + "x", now=1001) is None
    assert access.verify_console_token(token, now=1000 + access.LINK_TTL_SECONDS + 1) is None
    session = access.session_value(now=1000)
    assert access.valid_session(session, now=1001)
    assert not access.valid_session(access.console_token(now=1000), now=1001), "a link is not a session"


@pytest.mark.console_locked
def test_a_deployed_console_is_locked_until_a_signed_link_is_opened(deployed):
    main, _, _ = deployed
    # The session cookie is Secure on an https deployment, so talk https.
    with TestClient(main.app, base_url="https://testserver") as client:
        locked = client.get("/coach")
        assert locked.status_code == 401
        assert "Open the console from Telegram" in locked.text
        assert client.get("/coach/enter?token=forged").status_code == 401

        opened = client.get(
            "/coach/enter?token=" + access.console_token("/coach/athletes"), follow_redirects=False
        )
        assert opened.status_code == 303
        assert opened.headers["location"] == "/coach/athletes"
        assert client.get("/coach/athletes").status_code == 200
        assert client.get("/").status_code == 200, "the public landing page stays public"


def test_the_tick_endpoint_requires_a_fresh_signature(deployed):
    main, _, _ = deployed
    with TestClient(main.app) as client:
        assert client.post("/internal/agent/tick").status_code == 403
        stale = str(int(time.time()) - 3600)
        assert client.post("/internal/agent/tick", headers={
            "X-Agent-Timestamp": stale, "X-Agent-Signature": access.tick_signature(stale),
        }).status_code == 403
        fresh = str(int(time.time()))
        response = client.post("/internal/agent/tick", headers={
            "X-Agent-Timestamp": fresh, "X-Agent-Signature": access.tick_signature(fresh),
        })
        assert response.status_code == 200
        assert set(response.json()) >= {"opened", "actions", "closed", "escalated"}


def test_the_coach_links_telegram_once_with_the_setup_code(deployed):
    main, settings, sent = deployed
    headers = {"X-Telegram-Bot-Api-Secret-Token": "webhook_secret-123"}

    def say(chat, text, message_id):
        return client.post("/webhook/telegram", headers=headers, json={"message": {
            "message_id": message_id, "text": text, "chat": {"id": chat, "type": "private"}}})

    with TestClient(main.app) as client:
        say(9001, "/coach wrong-code", 1)
        assert "not valid" in sent[-1][1]
        say(9001, "/coach setup-code-7731", 2)
        assert sent[-1][1].startswith("Linked.")
        assert "https://agent.example.com/coach/enter?token=" in sent[-1][1]
        say(9002, "/coach setup-code-7731", 3)
        assert "already linked another Telegram account" in sent[-1][1]
        say(9001, "/console", 4)
        assert "/coach/enter?token=" in sent[-1][1]

        refused = client.post("/webhook/telegram", headers=headers, json={"callback_query": {
            "id": "cb1", "data": "d:1:rest", "message": {"chat": {"id": 9002}}}})
        assert refused.text == "not the coach chat"

    conn = db.connect(settings.database_path)
    try:
        assert store.coach_chat_id(conn) == "9001"
    finally:
        conn.close()
