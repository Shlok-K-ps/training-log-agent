"""Vonage Sandbox transport tests — all HTTP is mocked; no network is used."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.channels import vonage, whatsapp
from app.storage import db


def test_vonage_normalises_phone_numbers_and_delivery_states():
    assert vonage.athlete_id_from_sender("919000000001") == "+919000000001"
    assert vonage.athlete_id_from_sender("+1 (415) 555-0100") == "+14155550100"
    assert vonage.athlete_id_from_sender("") == ""
    assert vonage.ledger_status("submitted") == "sent"
    assert vonage.ledger_status("undeliverable") == "failed"
    assert vonage.ledger_status("unknown") is None


def test_vonage_send_uses_the_official_messages_api_shape(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "vonage_api_key", "api-key")
    monkeypatch.setattr(settings, "vonage_api_secret", "api-secret")
    monkeypatch.setattr(settings, "vonage_sandbox_number", "14157386102")
    seen = {}

    class Reply:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message_uuid": "vng-out-1"}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Reply()

    monkeypatch.setattr(vonage.httpx, "post", fake_post)
    assert vonage.send_outbound("+919000000001", "Approved plan") == "vng-out-1"
    assert seen["url"] == "https://messages-sandbox.nexmo.com/v1/messages"
    assert seen["auth"] == ("api-key", "api-secret")
    assert seen["json"] == {
        "from": "14157386102",
        "to": "919000000001",
        "channel": "whatsapp",
        "message_type": "text",
        "text": "Approved plan",
    }


def test_outbound_transport_activates_vonage_automatically(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "vonage_api_key", "key")
    monkeypatch.setattr(settings, "vonage_api_secret", "secret")
    monkeypatch.setattr(settings, "vonage_sandbox_number", "14157386102")
    monkeypatch.setattr(settings, "vonage_webhook_secret", "webhook-secret")
    monkeypatch.setattr(vonage, "send_outbound", lambda athlete, body: "automatic")
    assert settings.whatsapp_transport_name == "Vonage Sandbox"
    assert whatsapp.send_outbound("+9190", "hello") == "automatic"


def _client(tmp_path, monkeypatch):
    from app import main
    from app.config import settings

    monkeypatch.setattr(settings, "database_path", str(tmp_path / "vonage.db"))
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(settings, "vonage_api_key", "key")
    monkeypatch.setattr(settings, "vonage_api_secret", "secret")
    monkeypatch.setattr(settings, "vonage_sandbox_number", "14157386102")
    monkeypatch.setattr(settings, "vonage_webhook_secret", "webhook-secret")
    main.get_model_client.cache_clear()
    return TestClient(main.app), main, settings


def test_signed_inbound_message_runs_the_real_coaching_pipeline(tmp_path, monkeypatch):
    client, main, settings = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(main.whatsapp, "send_outbound", lambda athlete, body: "vng-out-2")
    with client as c:
        response = c.post(
            "/webhook/vonage/inbound?token=webhook-secret",
            json={
                "channel": "whatsapp",
                "from": "919000000001",
                "to": "14157386102",
                "message_uuid": "vng-in-1",
                "message_type": "text",
                "text": "squat 3x5 at 140kg rpe 8",
            },
        )
        assert response.status_code == 200
        assert c.get("/health").json()["whatsapp_transport"] == "Vonage Sandbox"

    conn = db.connect(settings.database_path)
    try:
        db.init_db(conn)
        assert len(db.session_history(conn, "+919000000001", "squat")) == 1
        inbound = db.whatsapp_message_by_sid(conn, "vng-in-1")
        outbound = db.whatsapp_message_by_sid(conn, "vng-out-2")
        assert inbound["direction"] == "inbound"
        assert outbound["direction"] == "outbound"
        assert outbound["reply_to_sid"] == "vng-in-1"
        assert outbound["status"] == "sent"
        assert len(db.pending_drafts(conn)) == 1
    finally:
        conn.close()


def test_vonage_status_callback_updates_the_shared_ledger(tmp_path, monkeypatch):
    client, _, settings = _client(tmp_path, monkeypatch)
    conn = db.connect(settings.database_path)
    try:
        db.init_db(conn)
        db.record_whatsapp_message(
            conn,
            athlete_id="+919000000001",
            direction="outbound",
            body="Approved plan",
            status="sent",
            provider_sid="vng-status-1",
        )
    finally:
        conn.close()
    with client as c:
        response = c.post(
            "/webhook/vonage/status?token=webhook-secret",
            json={"message_uuid": "vng-status-1", "status": "read"},
        )
    assert response.status_code == 200
    conn = db.connect(settings.database_path)
    try:
        assert db.whatsapp_message_by_sid(conn, "vng-status-1")["status"] == "read"
    finally:
        conn.close()


def test_vonage_webhooks_reject_the_wrong_secret(tmp_path, monkeypatch):
    client, _, _ = _client(tmp_path, monkeypatch)
    with client as c:
        response = c.post(
            "/webhook/vonage/inbound?token=wrong",
            json={"from": "9190", "message_uuid": "x", "text": "hello"},
        )
    assert response.status_code == 403
