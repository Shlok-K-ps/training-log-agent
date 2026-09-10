"""Transport tests: identity, chunking, TwiML, and the signature gate."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.channels import whatsapp
from app.storage import db


def test_the_phone_number_is_the_athlete_id():
    assert whatsapp.athlete_id_from_sender("whatsapp:+919000000001") == "+919000000001"
    assert whatsapp.athlete_id_from_sender("  whatsapp:+14155238886 ") == "+14155238886"
    assert whatsapp.athlete_id_from_sender("") == ""


def test_short_replies_are_not_split():
    assert whatsapp.chunk("hello") == ["hello"]


def test_long_replies_split_on_paragraph_boundaries():
    text = "\n\n".join(["x" * 400] * 6)
    parts = whatsapp.chunk(text, limit=1000)
    assert len(parts) > 1
    assert all(len(p) <= 1000 for p in parts)
    assert "".join(p.replace("\n", "") for p in parts).count("x") == 2400


def test_a_single_oversized_paragraph_is_hard_split():
    parts = whatsapp.chunk("y" * 5000, limit=1000)
    assert all(len(p) <= 1000 for p in parts)
    assert sum(len(p) for p in parts) == 5000


def test_twiml_escapes_markup_from_the_athlete():
    xml = whatsapp.twiml(["5 < 6 & <b>bold</b>"])
    assert "<b>" not in xml
    assert "&lt;b&gt;" in xml
    assert xml.startswith("<?xml")


def test_twiml_emits_one_message_element_per_chunk():
    assert whatsapp.twiml(["a", "b"]).count("<Message>") == 2


def test_the_signed_url_is_rebuilt_from_the_public_base_url(monkeypatch):
    monkeypatch.setattr(whatsapp.settings, "public_base_url", "https://agent.example.com")
    assert (
        whatsapp.webhook_url("http://10.0.0.4:8000/webhook/whatsapp")
        == "https://agent.example.com/webhook/whatsapp"
    )


# --- the webhook itself -------------------------------------------------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "database_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(app_settings, "validate_twilio_signature", False)
    monkeypatch.setattr(app_settings, "gemini_api_key", "")

    from app import main

    main.get_model_client.cache_clear()
    with TestClient(main.app) as test_client:
        yield test_client


def test_health_reports_which_parser_is_live(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["model"] == "offline-stub"
    assert body["whatsapp_integration"] is False


def test_the_webhook_logs_a_set_and_queues_coaching_for_review(client):
    response = client.post(
        "/webhook/whatsapp",
        data={"From": "whatsapp:+919000000001", "Body": "squat 3x5 at 140kg rpe 8"},
    )
    assert response.status_code == 200
    assert "<Response>" in response.text
    assert "sent it to your coach for review" in response.text

    from app.config import settings as app_settings
    conn = db.connect(app_settings.database_path)
    try:
        db.init_db(conn)
        assert len(db.session_history(conn, "+919000000001", "squat")) == 1
        pending = db.pending_drafts(conn)
        assert len(pending) == 1
        assert str(pending[0]["message_kind"]).startswith("feedback_reply:")
        assert "Logged" in pending[0]["body"]
    finally:
        conn.close()


def test_coach_can_simulate_the_whatsapp_flow_with_demo_athletes(client, monkeypatch):
    from app.coach import COOKIE_NAME
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "coach_access_token", "coach-test-token")
    client.cookies.set(COOKIE_NAME, "coach-test-token")
    assert client.post("/coach/demo/seed").status_code == 200
    response = client.post(
        "/coach/whatsapp/simulate",
        data={
            "athlete_id": "+99900000002",
            "body": "slept 5h, readiness 4, soreness 6, stress 7",
        },
    )
    assert response.status_code == 200
    assert "Simulated athlete message received" in response.text
    assert "slept 5h" in response.text
    assert "Test the WhatsApp workflow" in response.text

    approval = client.get("/coach/whatsapp?tab=approval")
    assert approval.status_code == 200
    assert "Needs approval" in approval.text
    assert "Rohit Sharma" in approval.text
    assert 'action="/coach/whatsapp/review"' in approval.text


def test_twilio_delivery_callback_updates_the_whatsapp_desk_ledger(client):
    from app.config import settings as app_settings

    conn = db.connect(app_settings.database_path)
    try:
        db.init_db(conn)
        db.record_whatsapp_message(
            conn, athlete_id="+919000000001", direction="outbound",
            body="Approved plan", status="queued", provider_sid="SM-CALLBACK",
        )
    finally:
        conn.close()
    response = client.post(
        "/webhook/whatsapp/status",
        data={"MessageSid": "SM-CALLBACK", "MessageStatus": "delivered"},
    )
    assert response.status_code == 204
    conn = db.connect(app_settings.database_path)
    try:
        db.init_db(conn)
        assert db.whatsapp_message_by_sid(conn, "SM-CALLBACK")["status"] == "delivered"
    finally:
        conn.close()


def test_an_unsigned_request_is_rejected_when_validation_is_on(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "database_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(app_settings, "validate_twilio_signature", True)
    monkeypatch.setattr(app_settings, "twilio_auth_token", "secret-token")
    monkeypatch.setattr(app_settings, "public_base_url", "")

    from app import main

    main.get_model_client.cache_clear()
    with TestClient(main.app) as c:
        response = c.post("/webhook/whatsapp", data={"From": "whatsapp:+91", "Body": "hi"})
    assert response.status_code == 403


def test_a_correctly_signed_request_is_accepted(tmp_path, monkeypatch):
    from app.config import settings as app_settings

    token = "secret-token"
    monkeypatch.setattr(app_settings, "database_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(app_settings, "validate_twilio_signature", True)
    monkeypatch.setattr(app_settings, "twilio_auth_token", token)
    monkeypatch.setattr(app_settings, "public_base_url", "http://testserver")
    monkeypatch.setattr(app_settings, "gemini_api_key", "")

    from app import main

    main.get_model_client.cache_clear()
    form = {"From": "whatsapp:+919000000001", "Body": "squat 3x5 at 140kg"}
    signature = RequestValidator(token).compute_signature(
        "http://testserver/webhook/whatsapp", form
    )
    with TestClient(main.app) as c:
        response = c.post(
            "/webhook/whatsapp", data=form, headers={"X-Twilio-Signature": signature}
        )
    assert response.status_code == 200
    assert "sent it to your coach for review" in response.text
