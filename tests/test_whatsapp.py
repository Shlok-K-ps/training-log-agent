"""Transport tests: identity, chunking, TwiML, and the signature gate."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

from app.channels import whatsapp


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


def test_the_webhook_logs_a_set_and_replies_with_twiml(client):
    response = client.post(
        "/webhook/whatsapp",
        data={"From": "whatsapp:+919000000001", "Body": "squat 3x5 at 140kg rpe 8"},
    )
    assert response.status_code == 200
    assert "<Response>" in response.text
    assert "Logged" in response.text


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
    assert "Logged" in response.text
