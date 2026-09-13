"""Permanent Telegram channel: pairing, webhook auth and approved delivery."""

from __future__ import annotations

import hashlib

import httpx
from fastapi.testclient import TestClient

from app.channels import telegram
from app.storage import db


def _telegram_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "telegram_bot_token", "123456:test-token")
    monkeypatch.setattr(settings, "telegram_bot_username", "PowerCoachTestBot")
    monkeypatch.setattr(settings, "telegram_webhook_secret", "webhook_secret-123")
    monkeypatch.setattr(settings, "telegram_link_secret", "pairing-secret")
    monkeypatch.setattr(settings, "public_base_url", "https://agent.example.com")
    return settings


def test_pairing_tokens_are_signed_and_tamper_evident(monkeypatch):
    _telegram_settings(monkeypatch)
    token = telegram.pairing_token("+919812340001")
    assert telegram.athlete_from_pairing_token(token) == ("+919812340001", 1)
    assert telegram.athlete_from_pairing_token(token + "x") is None
    assert telegram.pairing_url("+919812340001").startswith(
        "https://t.me/PowerCoachTestBot?start="
    )


def test_telegram_send_uses_bot_api_without_markdown_interpretation(monkeypatch):
    _telegram_settings(monkeypatch)
    seen = {}

    class Reply:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True, "result": {"message_id": 42}}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Reply()

    monkeypatch.setattr(telegram.httpx, "post", fake_post)
    sid = telegram.send_outbound("98765", "Coach says: hold at 100kg")
    assert sid == "telegram:98765:42"
    assert seen["url"].endswith("/bot123456:test-token/sendMessage")
    assert seen["json"]["chat_id"] == "98765"
    assert "parse_mode" not in seen["json"]


def test_startup_webhook_configuration_uses_telegram_secret_header(monkeypatch):
    _telegram_settings(monkeypatch)
    seen = {}

    class Reply:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Reply()

    monkeypatch.setattr(telegram.httpx, "post", fake_post)
    telegram.configure_webhook()
    assert seen["url"].endswith("/bot123456:test-token/setWebhook")
    assert seen["json"]["url"] == "https://agent.example.com/webhook/telegram"
    assert seen["json"]["secret_token"] == "webhook_secret-123"


def test_render_generated_webhook_secret_is_hashed_to_telegram_safe_token(monkeypatch):
    settings = _telegram_settings(monkeypatch)
    monkeypatch.setattr(settings, "telegram_webhook_secret", "render/value+with=chars")
    expected = hashlib.sha256(b"render/value+with=chars").hexdigest()
    assert telegram.webhook_secret_token() == expected
    assert telegram.valid_webhook_secret(expected) is True


def test_webhook_diagnostic_identifies_a_rejected_bot_token(monkeypatch):
    settings = _telegram_settings(monkeypatch)
    monkeypatch.setattr(settings, "telegram_bot_token", " 123456:test-token ")

    def rejected(url, **kwargs):
        assert "/bot123456:test-token/setWebhook" in url
        return httpx.Response(401, request=httpx.Request("POST", url))

    monkeypatch.setattr(telegram.httpx, "post", rejected)
    try:
        telegram.configure_webhook()
    except RuntimeError as exc:
        assert str(exc) == "Telegram rejected the bot token"
    else:
        raise AssertionError("an invalid Telegram token was reported as connected")


def test_one_chat_can_pair_to_one_enrolled_athlete(conn):
    db.register_athlete(conn, "+919812340001", "Priya", on="2026-09-13")
    db.register_athlete(conn, "+919812340002", "Rohit", on="2026-09-13")
    db.link_telegram_chat(conn, chat_id="1001", athlete_id="+919812340001")
    assert db.telegram_athlete_id(conn, "1001") == "+919812340001"
    assert db.telegram_chat_id(conn, "+919812340001") == "1001"
    try:
        db.link_telegram_chat(conn, chat_id="1001", athlete_id="+919812340002")
    except ValueError as exc:
        assert "already paired" in str(exc)
    else:
        raise AssertionError("a Telegram chat was allowed to take over another athlete")
    assert db.unlink_telegram_chat(conn, "+919812340001") is True
    assert db.telegram_athlete_id(conn, "1001") is None


def test_signed_pairing_link_is_single_use(conn):
    db.register_athlete(conn, "+919812340001", "Priya", on="2026-09-13")
    version = db.telegram_pairing_version(conn, "+919812340001")
    db.link_telegram_chat(
        conn, chat_id="1001", athlete_id="+919812340001",
        pairing_version=version,
    )
    db.unlink_telegram_chat(conn, "+919812340001")
    try:
        db.link_telegram_chat(
            conn, chat_id="2002", athlete_id="+919812340001",
            pairing_version=version,
        )
    except ValueError as exc:
        assert "already been used" in str(exc)
    else:
        raise AssertionError("a consumed pairing link was accepted again")


def _client(tmp_path, monkeypatch):
    from app import main

    settings = _telegram_settings(monkeypatch)
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "telegram.db"))
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(main.telegram, "configure_webhook", lambda: None)
    counter = iter(range(100, 120))
    monkeypatch.setattr(
        main.telegram,
        "send_outbound",
        lambda chat_id, body: telegram.provider_sid(chat_id, next(counter)),
    )
    main.get_model_client.cache_clear()
    return TestClient(main.app), main, settings


def test_pair_then_log_training_through_the_real_pipeline(tmp_path, monkeypatch):
    client, main, settings = _client(tmp_path, monkeypatch)
    conn = db.connect(settings.database_path)
    try:
        db.init_db(conn)
        db.register_athlete(conn, "+919812340001", "Priya", on="2026-09-13")
    finally:
        conn.close()
    token = telegram.pairing_token("+919812340001")
    headers = {"X-Telegram-Bot-Api-Secret-Token": "webhook_secret-123"}
    with client as c:
        athlete_page = main._render_athlete("+919812340001", None)
        assert "Connect this athlete to Telegram" in athlete_page
        assert ">Connect Telegram</a>" in athlete_page
        assert token in athlete_page
        paired = c.post(
            "/webhook/telegram",
            headers=headers,
            json={"message": {"message_id": 1, "text": f"/start {token}",
                              "chat": {"id": 7001, "type": "private"}}},
        )
        assert paired.status_code == 200
        logged = c.post(
            "/webhook/telegram",
            headers=headers,
            json={"message": {"message_id": 2,
                              "text": "squat 3x5 at 140kg rpe 8",
                              "chat": {"id": 7001, "type": "private"}}},
        )
        assert logged.status_code == 200
        health = c.get("/health").json()
        assert health["telegram_integration"] is True
        assert health["telegram_webhook_ready"] is True
        assert health["telegram_webhook_error"] is None
        assert "Telegram" in health["messaging_transport"]
        assert "Telegram connected" in main._render_athlete("+919812340001", None)

        desk = c.get("/coach/whatsapp")
        assert "Telegram is active" in desk.text
        assert "Open an athlete profile to connect their Telegram chat" in desk.text
        directory = c.get("/coach/athletes")
        assert "Telegram bot is connected" in directory.text
        assert "Telegram connected" in directory.text

    conn = db.connect(settings.database_path)
    try:
        db.init_db(conn)
        assert db.telegram_chat_id(conn, "+919812340001") == "7001"
        assert len(db.session_history(conn, "+919812340001", "squat")) == 1
        assert len(db.pending_drafts(conn)) == 1
        messages = db.whatsapp_messages(conn, "+919812340001")
        assert any(row["channel"] == "telegram" for row in messages)
    finally:
        conn.close()


def test_plain_start_explains_that_an_athlete_pairing_link_is_required(
    tmp_path, monkeypatch
):
    client, main, _ = _client(tmp_path, monkeypatch)
    sent = []
    monkeypatch.setattr(
        main.telegram,
        "send_outbound",
        lambda chat_id, body: sent.append((chat_id, body)) or "telegram:7001:100",
    )
    headers = {"X-Telegram-Bot-Api-Secret-Token": "webhook_secret-123"}

    with client as c:
        response = c.post(
            "/webhook/telegram",
            headers=headers,
            json={"message": {"message_id": 1, "text": "/start",
                              "chat": {"id": 7001, "type": "private"}}},
        )

    assert response.status_code == 200
    assert sent[0][0] == "7001"
    assert "plain /start cannot identify your athlete profile" in sent[0][1]
    assert "press Connect Telegram" in sent[0][1]


def test_bad_telegram_webhook_secret_is_rejected(tmp_path, monkeypatch):
    client, _, _ = _client(tmp_path, monkeypatch)
    with client as c:
        response = c.post(
            "/webhook/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            json={"message": {"message_id": 1, "text": "hello",
                              "chat": {"id": 1, "type": "private"}}},
        )
    assert response.status_code == 403


def test_health_does_not_claim_webhook_ready_when_registration_fails(
    tmp_path, monkeypatch
):
    from app import main

    settings = _telegram_settings(monkeypatch)
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "failed-webhook.db"))
    monkeypatch.setattr(
        main.telegram,
        "configure_webhook",
        lambda: (_ for _ in ()).throw(RuntimeError("Telegram rejected webhook")),
    )
    with TestClient(main.app) as client:
        health = client.get("/health").json()
    assert health["telegram_integration"] is True
    assert health["telegram_webhook_ready"] is False
    assert health["telegram_webhook_error"] == "Telegram rejected webhook"


def test_approved_message_prefers_the_paired_telegram_chat(tmp_path, monkeypatch):
    client, main, settings = _client(tmp_path, monkeypatch)
    with client:
        pass
    conn = db.connect(settings.database_path)
    try:
        db.init_db(conn)
        db.register_athlete(conn, "+919812340001", "Priya", on="2026-09-13")
        db.link_telegram_chat(conn, chat_id="7001", athlete_id="+919812340001")
        kind = "feedback_reply:test"
        db.create_draft(conn, "+919812340001", kind, "2026-09-13", "Approved advice")
        db.review_draft(
            conn, "+919812340001", kind, "2026-09-13",
            status="approved", reviewed_by="Coach", body="Approved advice",
        )
    finally:
        conn.close()
    sent = []
    monkeypatch.setattr(
        main.telegram,
        "send_outbound",
        lambda chat_id, body: sent.append((chat_id, body)) or "telegram:7001:200",
    )
    monkeypatch.setattr(
        main.whatsapp,
        "send_outbound",
        lambda athlete_id, body: (_ for _ in ()).throw(
            AssertionError("WhatsApp should not be used for a Telegram-paired athlete")
        ),
    )
    assert main._send_morning_prompts() == 1
    assert sent == [("7001", "Approved advice")]
    conn = db.connect(settings.database_path)
    try:
        row = db.whatsapp_message_by_sid(conn, "telegram:7001:200")
        assert row["channel"] == "telegram"
    finally:
        conn.close()
