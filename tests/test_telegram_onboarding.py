"""Telegram onboarding as it really happens, and coach messages that can never go out twice.

Every pairing here starts from the invite the athlete page actually offers, so a
token Telegram would refuse to pass on fails these tests instead of passing them.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import deployment
from app.casework import clock
from app.channels import telegram
from app.scheduling import outbox
from app.storage import db

HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "webhook_secret-123"}
TELEGRAM_START_PARAMETER = re.compile(r"[A-Za-z0-9_-]{1,64}")
PRIYA, ROHIT = "+919812340001", "+919812340002"
LATER = datetime.now(timezone.utc) + timedelta(days=1)  # any note dated today is due by then


def _settings(monkeypatch, **extra):
    from app.config import settings

    values = {
        "database_url": "",
        "public_base_url": "https://agent.example.com",
        "coach_link_secret": "",
        "telegram_bot_token": "123456:test-token",
        "telegram_bot_username": "PowerCoachTestBot",
        "telegram_webhook_secret": "webhook_secret-123",
        "telegram_link_secret": "pairing-secret",
        "coach_name": "Coach Rao",
        "gemini_api_key": "",
    }
    values.update(extra)
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    return settings


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from app import main

    settings = _settings(monkeypatch, database_path=str(tmp_path / "onboarding.db"))
    monkeypatch.setattr(main.telegram, "configure_webhook", lambda: None)
    monkeypatch.setattr(deployment, "durable_storage_configured", lambda: True)
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2026, 9, 14, 0, 30, tzinfo=timezone.utc))
    sent: list[tuple[str, str]] = []
    counter = iter(range(900_000, 999_999))

    def fake_send(chat_id, body, **_kwargs):
        sent.append((str(chat_id), body))
        return telegram.provider_sid(chat_id, next(counter))

    monkeypatch.setattr(main.telegram, "send_outbound", fake_send)
    main.get_model_client.cache_clear()
    with TestClient(main.app) as client:
        yield client, settings, sent


def _db(settings):
    conn = db.connect(settings.database_path)
    db.init_db(conn)
    return conn


def _register(settings, athlete_id=PRIYA, name="Priya Nair"):
    conn = _db(settings)
    try:
        db.register_athlete(conn, athlete_id, name, on="2026-09-13")
    finally:
        conn.close()
    return f"/coach/athlete/{athlete_id}"


def _telegram(client, chat_id: int, text: str, message_id: int):
    response = client.post(
        "/webhook/telegram", headers=HEADERS,
        json={"message": {"message_id": message_id, "text": text, "chat": {"id": chat_id, "type": "private"}}},
    )
    assert response.status_code == 200
    return response


def _invite(html: str) -> str:
    """The start parameter of the invite the page asks the coach to copy."""
    button = BeautifulSoup(html, "html.parser").select_one("button[data-copy]")
    assert button is not None, "the page offers an invite to copy"
    return parse_qs(urlparse(button["data-copy"]).query)["start"][0]


def _chat(settings, athlete_id=PRIYA):
    conn = _db(settings)
    try:
        return db.telegram_chat_id(conn, athlete_id)
    finally:
        conn.close()


def _notes(settings, athlete_id=PRIYA):
    conn = _db(settings)
    try:
        return [row for row in db.athlete_drafts(conn, athlete_id, limit=100)
                if str(row["message_kind"]).startswith("coach_note")]
    finally:
        conn.close()


# --- The invite itself ------------------------------------------------------


def test_invites_are_valid_telegram_start_parameters_and_tamper_evident(monkeypatch):
    _settings(monkeypatch)
    ids = [db.new_athlete_id() for _ in range(25)] + [PRIYA, "a" * 30]
    for athlete_id in ids:
        for version in (1, 7, 12345):
            token = telegram.pairing_token(athlete_id, version)
            assert TELEGRAM_START_PARAMETER.fullmatch(token), (athlete_id, version, token)
            assert telegram.athlete_from_pairing_token(token) == (athlete_id, version)
            start = parse_qs(urlparse(telegram.pairing_url(athlete_id, version)).query)["start"][0]
            assert start == token, "the link carries the token unchanged"
            flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
            assert telegram.athlete_from_pairing_token(flipped) is None

    with pytest.raises(ValueError):
        telegram.pairing_token("x" * 60)

    token = telegram.pairing_token(PRIYA)
    monkeypatch.setattr(telegram.settings, "telegram_link_secret", "a-different-secret")
    assert telegram.athlete_from_pairing_token(token) is None, "a token signed elsewhere is refused"


def test_an_old_dotted_invite_pasted_by_hand_still_verifies(monkeypatch):
    _settings(monkeypatch)
    payload = telegram._encoded(f"{PRIYA}|3")
    legacy = f"{payload}.{telegram._legacy_signature(payload)}"
    assert not TELEGRAM_START_PARAMETER.fullmatch(legacy), "this is why old links never reached the bot"
    assert telegram.athlete_from_pairing_token(legacy) == (PRIYA, 3)
    assert telegram.athlete_from_pairing_token(legacy[:-2] + "zz") is None


# --- Pairing through the bot ------------------------------------------------


def test_the_invite_on_the_page_pairs_the_athlete_and_the_bot_confirms_it(env):
    client, settings, sent = env
    url = _register(settings)
    page = client.get(url).text
    token = _invite(page)
    assert TELEGRAM_START_PARAMETER.fullmatch(token)

    _telegram(client, 7001, f"/start {token}", 1)
    assert sent[-1][0] == "7001"
    assert sent[-1][1].startswith("Connected to Power AI as Priya Nair.")
    assert _chat(settings) == "7001"

    status = client.get(f"{url}/status.json")
    assert status.json()["telegram_connected"] is True
    assert status.json()["last_attempt"]["outcome"] == "connected"
    assert "7001" not in status.text, "the Telegram chat id is never exposed"

    connected = client.get(f"{url}?connected=1")
    soup = BeautifulSoup(connected.text, "html.parser")
    assert soup.select_one("#telegram") is None, "no invite once connected"
    assert soup.select_one('[data-status="telegram"]').get_text(strip=True) == "Connected"
    assert soup.select_one(".msg.ok").get_text(strip=True) == (
        "Telegram connected. Priya can now receive the agent's messages.")
    assert "7001" not in connected.text
    assert token not in connected.text, "a used invite is not shown again"

    _telegram(client, 7001, f"/start {token}", 2)
    assert sent[-1][1].startswith("You're already connected to Power AI as Priya Nair.")
    _telegram(client, 8002, f"/start {token}", 3)
    assert "already connected to a different Telegram account" in sent[-1][1]
    assert _chat(settings) == "7001", "a second account cannot take the athlete over"


def test_plain_start_opening_the_bot_or_a_broken_invite_never_pairs(env):
    client, settings, sent = env
    url = _register(settings)

    _telegram(client, 7001, "/start", 1)
    assert "open the private invite link your coach sent you" in sent[-1][1]
    assert "typing /start on its own can't tell me who you are" in sent[-1][1]

    _telegram(client, 7001, "hello?", 2)
    assert "isn't connected to Power AI yet" in sent[-1][1]

    token = _invite(client.get(url).text)
    for index, broken in enumerate((token[:-3], token + "x", "abc.def", "not-a-real-invite-token-at-all"), start=3):
        _telegram(client, 7001, f"/start {broken}", index)
        assert "This invite link isn't valid" in sent[-1][1]

    assert _chat(settings) is None
    status = client.get(f"{url}/status.json").json()
    assert status["telegram_connected"] is False
    assert status["last_attempt"] is None, "nothing reached this athlete, so nothing is recorded against them"


def test_replacing_an_invite_turns_off_every_earlier_one(env):
    client, settings, sent = env
    url = _register(settings)
    old = _invite(client.get(url).text)

    replaced = client.post(f"{url}/telegram/refresh-invite")
    assert "New invite created. Earlier invites for Priya no longer work" in replaced.text
    new = _invite(replaced.text)
    assert new != old

    _telegram(client, 7001, f"/start {old}", 1)
    assert "already been used or was replaced by a newer one" in sent[-1][1]
    assert _chat(settings) is None
    page = client.get(url).text
    assert "Last attempt: Used an invite that had already been used or was replaced by a newer one." in page
    assert client.get(f"{url}/status.json").json()["last_attempt"]["outcome"] == "link_replaced"

    _telegram(client, 7001, f"/start {new}", 2)
    assert sent[-1][1].startswith("Connected to Power AI as Priya Nair.")
    refused = client.post(f"{url}/telegram/refresh-invite")
    assert "Priya is already connected" in refused.text


def test_disconnecting_turns_off_the_invite_that_was_used(env):
    client, settings, sent = env
    url = _register(settings)
    first = _invite(client.get(url).text)
    _telegram(client, 7001, f"/start {first}", 1)

    page = client.post(f"{url}/telegram/unlink").text
    assert "earlier invites stopped working" in page
    _telegram(client, 8002, f"/start {first}", 2)
    assert "already been used or was replaced" in sent[-1][1]
    assert _chat(settings) is None

    _telegram(client, 8002, f"/start {_invite(page)}", 3)
    assert _chat(settings) == "8002"


def test_a_telegram_account_paired_to_one_athlete_cannot_be_paired_to_another(env):
    client, settings, sent = env
    priya_url = _register(settings)
    rohit_url = _register(settings, ROHIT, "Rohit Shah")
    _telegram(client, 7001, f"/start {_invite(client.get(priya_url).text)}", 1)

    _telegram(client, 7001, f"/start {_invite(client.get(rohit_url).text)}", 2)
    assert "already connected to another athlete, so it can't also be connected to Rohit Shah" in sent[-1][1]
    assert _chat(settings, ROHIT) is None
    assert _chat(settings, PRIYA) == "7001"
    rohit_page = client.get(rohit_url).text
    assert "The Telegram account used is already connected to another athlete." in rohit_page
    assert "7001" not in rohit_page


def test_the_connection_card_guides_the_coach_without_exposing_the_link(env):
    client, settings, _ = env
    url = _register(settings)
    soup = BeautifulSoup(client.get(url).text, "html.parser")
    card = soup.select_one("#telegram")
    text = card.get_text(" ")

    assert card.select_one("h2").get_text(strip=True) == "Priya is not connected yet"
    assert card.select_one("button[data-copy]").get_text(strip=True) == "Copy invite for Priya"
    assert card.select_one("button[data-check-connection]").get_text(strip=True) == "Check connection"
    assert unquote(card["data-status-url"]) == f"{url}/status.json"
    assert client.get(card["data-status-url"]).json()["telegram_connected"] is False
    steps = [li.get_text(" ", strip=True) for li in card.select(".invite-steps li")]
    assert len(steps) == 3 and "Connected to Power AI as Priya Nair." in steps[2]
    assert "Opening the bot or typing /start is not enough." in text
    assert "Don’t open the invite with your own Telegram." in text

    assert not soup.select('a[href^="https://t.me/"]'), "the console never opens an invite itself"
    for field in soup.select("input.invite-link"):
        assert field.find_parent("details", class_="invite-raw"), "the raw link hides behind a deliberate expander"

    help_items = [dt.get_text(" ", strip=True) for dt in card.select(".invite-help dt")]
    assert len(help_items) == 5
    for phrase in ("private invite", "isn’t valid", "used or replaced", "expired", "another athlete"):
        assert any(phrase in item for item in help_items), phrase
    form = card.select_one(".invite-help form")
    assert unquote(form["action"]) == f"{url}/telegram/refresh-invite"
    assert form.button.get_text(strip=True) == "Replace with a fresh invite"

    assert client.get(f"{url}/status.json").json()["telegram_connected"] is False
    assert "Telegram connected." not in client.get(f"{url}?connected=1").text, "the banner needs a real connection"


def test_without_a_bot_username_the_card_explains_and_points_at_possible_work(env, monkeypatch):
    client, settings, _ = env
    url = _register(settings)
    monkeypatch.setattr(settings, "telegram_bot_username", "")
    card = BeautifulSoup(client.get(url).text, "html.parser").select_one("#telegram")
    assert card.select_one("h2").get_text(strip=True) == "Telegram isn't set up on this deployment"
    assert card.select_one("button[data-copy]") is None
    links = [unquote(a["href"]) for a in card.select("a")]
    assert links == [f"{url}#agent-plan"], "never a link back to this same card"


# --- Coach notes: queued once, sent once ---------------------------------------


def test_repeated_queue_requests_create_one_scheduled_note(env):
    client, settings, _ = env
    url = _register(settings)
    first = client.post(f"{url}/message", data={"body": "Great squat session today."})
    assert "Queued. It goes out" in first.text
    for body in ("Great squat session today.", "  great squat   SESSION today. "):
        again = client.post(f"{url}/message", data={"body": body})
        assert "already scheduled for today, so it was not added again" in again.text
    assert len(_notes(settings)) == 1

    client.post(f"{url}/message", data={"body": "Sleep well tonight."})
    assert len(_notes(settings)) == 2, "different notes on one day both go out"

    sent = []
    conn = _db(settings)
    try:
        assert outbox.send_approved_notes(conn, lambda a, b: sent.append(b), now_utc=LATER) == 2
        assert outbox.send_approved_notes(conn, lambda a, b: sent.append(b), now_utc=LATER) == 0
    finally:
        conn.close()
    assert sorted(sent) == ["Great squat session today.", "Sleep well tonight."]

    after = client.post(f"{url}/message", data={"body": "Great squat session today."})
    assert "already sent today, so it was not queued again" in after.text
    assert len(_notes(settings)) == 2


def test_simultaneous_queue_requests_still_create_one_note(env):
    from app import main

    _, settings, _ = env
    _register(settings)
    barrier = threading.Barrier(6)
    results = []

    def queue():
        barrier.wait()
        results.append(main._queue_note(PRIYA, "Deload week starts Monday."))

    threads = [threading.Thread(target=queue) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == 6
    assert len(_notes(settings)) == 1


def test_identical_notes_already_in_the_queue_are_delivered_once(env):
    client, settings, _ = env
    url = _register(settings)
    today = datetime.now().date().isoformat()
    conn = _db(settings)
    try:
        # What the old random keys allowed: the same note queued three times.
        for kind, body in (("coach_note:aaa111", "Hold at 140 this week."),
                           ("coach_note:bbb222", "Hold at 140 this week."),
                           ("coach_note:ccc333", "hold at 140  this week.")):
            db.create_draft(conn, PRIYA, kind, today, body)
            db.review_draft(conn, PRIYA, kind, today, status="approved", reviewed_by="Coach", body=body)
        sent = []
        assert outbox.send_approved_notes(conn, lambda a, b: sent.append(b), now_utc=LATER) == 1
        assert outbox.send_approved_notes(conn, lambda a, b: sent.append(b), now_utc=LATER) == 0
        states = sorted((str(r["status"]), r["resolution"]) for r in _notes(settings))
    finally:
        conn.close()
    assert sent == ["Hold at 140 this week."]
    assert states == [("sent", None), ("skipped", "duplicate"), ("skipped", "duplicate")], "kept, not deleted"

    soup = BeautifulSoup(client.get(url).text, "html.parser")
    items = soup.select("#outbox .outbox-item")
    assert len(items) == 1, "duplicates collapse into the note that went out"
    assert items[0].select_one(".delivery-badge").get_text(strip=True) == "Sent"
    assert "2 identical duplicates blocked, not sent." in items[0].get_text(" ")


def test_an_overlapping_send_cannot_deliver_a_note_twice(env):
    _, settings, _ = env
    _register(settings)
    today = datetime.now().date().isoformat()
    conn, other = _db(settings), _db(settings)
    try:
        for kind, body in (("coach_note:one", "Note one."), ("coach_note:two", "Note two."),
                           ("feedback_reply:x", "Reply one.")):
            db.create_draft(conn, PRIYA, kind, today, body)
            db.review_draft(conn, PRIYA, kind, today, status="approved", reviewed_by="Coach", body=body)
        delivered = []

        def sender(_athlete, body):
            delivered.append(body)
            if len(delivered) == 1:  # a second worker runs while the first send is in flight
                outbox.send_approved_notes(other, sender, now_utc=LATER)
                outbox.send_approved_feedback(other, sender)

        outbox.send_approved_notes(conn, sender, now_utc=LATER)
        outbox.send_approved_feedback(conn, sender)
        outbox.send_approved_notes(conn, sender, now_utc=LATER)
        outbox.send_approved_feedback(other, sender)
    finally:
        conn.close()
        other.close()
    assert sorted(delivered) == ["Note one.", "Note two.", "Reply one."]


def test_a_failed_send_stays_approved_for_a_safe_retry(env):
    client, settings, _ = env
    url = _register(settings)
    client.post(f"{url}/message", data={"body": "Check in after training."})
    calls = []

    def broken(_athlete, body):
        calls.append(body)
        raise RuntimeError("Telegram send request failed")

    conn = _db(settings)
    try:
        assert outbox.send_approved_notes(conn, broken, now_utc=LATER) == 0
        assert outbox.send_approved_notes(conn, broken, now_utc=LATER) == 0
    finally:
        conn.close()
    assert calls == ["Check in after training.", "Check in after training."]
    [row] = _notes(settings)
    assert (row["status"], row["resolution"]) == ("approved", None)
    item = BeautifulSoup(client.get(url).text, "html.parser").select_one("#outbox .outbox-item")
    assert item.select_one(".delivery-badge").get_text(strip=True) == "Scheduled"


def test_the_coach_can_cancel_a_scheduled_note(env):
    client, settings, _ = env
    url = _register(settings)
    client.post(f"{url}/message", data={"body": "Rest day tomorrow."})
    soup = BeautifulSoup(client.get(url).text, "html.parser")
    item = soup.select_one("#outbox .outbox-item")
    assert item.select_one(".delivery-badge").get_text(strip=True) == "Scheduled"
    form = item.select_one("form.outbox-cancel")
    fields = {field["name"]: field["value"] for field in form.select("input[type=hidden]")}

    cancelled = client.post(form["action"], data=fields)
    assert "Cancelled. That message will not be sent." in cancelled.text
    item = BeautifulSoup(cancelled.text, "html.parser").select_one("#outbox .outbox-item")
    assert item.select_one(".delivery-badge").get_text(strip=True) == "Cancelled"
    assert item.select_one("form.outbox-cancel") is None
    assert "Nothing to cancel" in client.post(form["action"], data=fields).text

    sent = []
    conn = _db(settings)
    try:
        assert outbox.send_approved_notes(conn, lambda a, b: sent.append(b), now_utc=LATER) == 0
        client.post(f"{url}/message", data={"body": "Rest day tomorrow."})  # the coach changes their mind
        assert outbox.send_approved_notes(conn, lambda a, b: sent.append(b), now_utc=LATER) == 1
    finally:
        conn.close()
    assert sent == ["Rest day tomorrow."]
    states = sorted((str(r["status"]), r["resolution"]) for r in _notes(settings))
    assert states == [("sent", None), ("skipped", "cancelled")], "the cancelled record is kept"


# --- Setup states ---------------------------------------------------------------


def _header(client, url):
    soup = BeautifulSoup(client.get(url).text, "html.parser")
    header = soup.select_one("#agent-status")
    steps = {li["data-step-key"]: li["class"][1] for li in header.select(".stepper-step")}
    return soup, header, steps


def test_setup_steps_show_current_idle_ready_and_blocked(env, monkeypatch):
    client, settings, _ = env
    landed = client.post("/coach/athletes/register", data={
        "name": "Priya Nair", "timezone": "Asia/Kolkata", "checkin_time": "07:30", "training_time": "18:00"})
    url = urlparse(str(landed.url)).path
    athlete_id = url.rsplit("/", 1)[1]

    soup, header, steps = _header(client, url)
    assert header["data-state"] == "setup"
    assert steps == {"telegram": "is-current", "training-plan": "is-todo", "autopilot": "is-todo",
                     "agent-ready": "is-todo"}
    assert header.select_one(".status-badge").get_text(strip=True) == "Setup needed"
    assert not header.select(".status-actions a, .status-actions button"), "the invite card is the next action"
    assert not soup.select(".btn-disabled")
    assert header.select_one("[data-idle]") is None

    client.post(f"{url}/autopilot", data={"enabled": "on"})
    soup, header, steps = _header(client, url)
    assert header.select_one("[data-idle]").get_text(strip=True) == (
        "Autopilot is on but idle—there is no approved plan to run.")
    assert header.select_one('[data-status="autopilot"]').get_text(strip=True) == "On, but idle"
    assert soup.select_one("#autopilot .status-badge").get_text(strip=True) == "On, idle"

    conn = _db(settings)
    db.link_telegram_chat(conn, chat_id="7001", athlete_id=athlete_id)
    conn.close()
    soup, header, steps = _header(client, url)
    assert steps["telegram"] == "is-done" and steps["training-plan"] == "is-current"
    assert [a.get_text(strip=True) for a in header.select(".status-actions a")] == ["Create weekly plan"]

    client.post(f"{url}/plan", data={"weekday": "0", "lift": "squat", "sets": "4", "reps": "5", "rpe": "7"})
    soup, header, steps = _header(client, url)
    assert header["data-state"] == "ready"
    assert steps == {}, "a finished setup collapses from a checklist to a few facts"
    facts = {node["data-status"]: node.get_text(strip=True) for node in header.select(".status-facts [data-status]")}
    assert facts == {"telegram": "Connected", "training-plan": "Mon · 1 lift", "autopilot": "On"}
    assert soup.select_one("#telegram") is None, "onboarding instructions are gone once connected"
    assert header.select_one("[data-idle]") is None
    assert header.select_one('[data-status="next-action"]').get_text(strip=True) == "Check-in today at 07:30."
    assert [a.get_text(strip=True) for a in header.select(".status-actions a")] == ["Run a safe simulated test"]
    plan = soup.select_one("#agent-plan")
    assert "Squat" in plan.select_one(".plan-list").get_text() and "4×5 · RPE 7" in plan.get_text()
    assert plan.select_one("form.plan-form button[type=submit]").get_text(strip=True) == "Add to weekly plan"
    for field in ("plan-weekday", "plan-lift", "plan-sets", "plan-reps", "plan-rpe"):
        assert plan.select_one(f'label[for="{field}"]') and plan.select_one(f"#{field}")

    monkeypatch.setattr(deployment, "durable_storage_configured", lambda: False)
    soup, header, steps = _header(client, url)
    assert header["data-state"] == "blocked"
    assert header.select_one(".status-badge").get_text(strip=True) == "Blocked"
    assert "DATABASE_URL" in header.select_one("[data-status=blocking]").get_text()


def test_the_page_puts_setup_before_evidence_and_messages(env):
    client, settings, _ = env
    url = _register(settings)
    html = client.get(url).text
    order = [html.index(marker) for marker in (
        'id="agent-status"', 'id="telegram"', 'class="athlete-tabs"', 'id="panel-plan"', "id='agent-plan'",
        "id='autopilot'", 'id="panel-evidence"', 'id="panel-messages"', 'id="panel-profile"', 'id="advanced"')]
    assert order == sorted(order)
