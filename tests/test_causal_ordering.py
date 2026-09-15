"""The athlete's conversation stays causal: nothing asks for what was already said.

Reproduces the live sequence from Nikash's pairing day:

  15:06  pairs on Telegram partway through a planned training day
  15:09  "reverse a linked list"
  15:10  "Slept 6 hours, readiness 5/10, slight knee pain today."
  15:11  the coach approves the queued check-in and an automated reply
  later  ticks run, possibly at the same time

and asserts that the stale check-in and reply are never sent, stay in history with
a reason, the pain report pauses guidance and reaches the coach, and a coach-written
note still goes out exactly once. Every test runs on SQLite, and on Postgres when
TEST_DATABASE_URL points at a disposable database.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import deployment
from app.casework import clock, store
from app.channels import telegram
from app.scheduling import outbox
from app.storage import db

PG_URL = os.getenv("TEST_DATABASE_URL", "")
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "webhook_secret-123"}
IST = ZoneInfo("Asia/Kolkata")
DAY = "2026-09-14"  # a Monday
CHECKIN_PROMPT = "hours slept"  # every agent check-in asks for this
STALE_REPLY = "Meet in 2 weeks: keep the squat at RPE 7 this week."
LEGACY_CHECKIN = "Good morning — how many hours did you sleep, and how ready do you feel?"


def at(hour: int, minute: int) -> datetime:
    return datetime(2026, 9, 14, hour, minute, tzinfo=IST).astimezone(timezone.utc)


def _drop_pg_tables() -> None:
    import re

    import psycopg

    from app.storage import pg

    with psycopg.connect(PG_URL, autocommit=True) as raw:
        for table in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", db.SCHEMA):
            raw.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    pg._ready_urls.discard(PG_URL)


@dataclass
class World:
    client: TestClient
    main: object
    settings: object
    moment: dict
    sent: list = field(default_factory=list)

    def db(self):
        conn = db.connect()
        db.init_db(conn)
        return conn

    def bodies(self, chat_id: int) -> list[str]:
        return [item["body"] for item in self.sent if item["chat"] == str(chat_id)]

    def say(self, chat_id: int, text: str, message_id: int):
        response = self.client.post("/webhook/telegram", headers=HEADERS, json={"message": {
            "message_id": message_id, "text": text, "chat": {"id": chat_id, "type": "private"}}})
        assert response.status_code == 200, response.text
        return response

    def register(self, name: str, *, autopilot: str = "off", plan: bool = True) -> tuple[str, str]:
        landed = self.client.post("/coach/athletes/register", data={
            "name": name, "timezone": "Asia/Kolkata", "checkin_time": "07:30", "training_time": "18:00"})
        url = urlparse(str(landed.url)).path
        if plan:
            self.client.post(f"{url}/plan", data={"weekday": "0", "lift": "squat", "sets": "4", "reps": "5", "rpe": "7"})
            self.client.post(f"{url}/autopilot", data={"enabled": autopilot})
        return url, url.rsplit("/", 1)[1]

    def pair(self, url: str, chat_id: int, message_id: int) -> None:
        button = BeautifulSoup(self.client.get(url).text, "html.parser").select_one("button[data-copy]")
        token = parse_qs(urlparse(button["data-copy"]).query)["start"][0]
        self.say(chat_id, f"/start {token}", message_id)

    def draft(self, athlete_id: str, kind: str, local_date: str = DAY):
        conn = self.db()
        try:
            return db.draft(conn, athlete_id, kind, local_date)
        finally:
            conn.close()

    def approve(self, athlete_id: str, kind: str, local_date: str = DAY, body: str = "") -> str:
        data = {"athlete_id": athlete_id, "message_kind": kind, "local_date": local_date,
                "decision": "approved", "return_to": "/coach/whatsapp?tab=approval"}
        if body:
            data["body"] = body  # otherwise the drafted wording is approved as written
        return self.client.post("/coach/whatsapp/review", data=data).text


BACKENDS = [
    "sqlite",
    pytest.param("postgres", marks=pytest.mark.skipif(not PG_URL, reason="set TEST_DATABASE_URL for Postgres")),
]


@pytest.fixture(params=BACKENDS)
def world(request, tmp_path, monkeypatch):
    from app import main
    from app.config import settings

    values = {
        "public_base_url": "https://agent.example.com", "coach_link_secret": "",
        "telegram_bot_token": "123456:test-token", "telegram_bot_username": "PowerCoachTestBot",
        "telegram_webhook_secret": "webhook_secret-123", "telegram_link_secret": "pairing-secret",
        "coach_name": "Coach Rao", "gemini_api_key": "", "enable_agent_loop": True,
    }
    if request.param == "postgres":
        values["database_url"] = PG_URL
        _drop_pg_tables()
    else:
        values.update(database_url="", database_path=str(tmp_path / "causal.db"))
        monkeypatch.setattr(deployment, "durable_storage_configured", lambda: True)
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)
    moment = {"now": at(14, 50)}
    monkeypatch.setattr(clock, "utcnow", lambda: moment["now"])
    sent: list[dict] = []
    lock = threading.Lock()

    def fake_send(chat_id, body, reply_markup=None):
        with lock:
            sent.append({"chat": str(chat_id), "body": body})
            return telegram.provider_sid(chat_id, 900_000 + len(sent))

    monkeypatch.setattr(main.telegram, "send_outbound", fake_send)
    monkeypatch.setattr(main.telegram, "configure_webhook", lambda: None)
    main.get_model_client.cache_clear()
    with TestClient(main.app) as client:
        yield World(client=client, main=main, settings=settings, moment=moment, sent=sent)
    if request.param == "postgres":
        _drop_pg_tables()


def _send_ticks_concurrently(world: World, workers: int = 4) -> None:
    barrier = threading.Barrier(workers)
    errors: list[BaseException] = []

    def run():
        try:
            barrier.wait()
            world.main._send_approved_coach_messages()
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not errors, errors


# --- The exact live sequence ---------------------------------------------------------


def test_nikash_pairing_day_stays_causal(world):
    url, nikash = world.register("Nikash Rao")
    conn = world.db()
    try:
        # A backlog prepared before Telegram existed for Nikash.
        db.create_draft(conn, nikash, "morning_checkin", DAY, LEGACY_CHECKIN)
        db.create_draft(conn, nikash, "feedback_reply:before-pairing", DAY, "Welcome! Log your first session.")
    finally:
        conn.close()

    world.moment["now"] = at(15, 6)
    world.pair(url, 7001, 1)
    assert world.bodies(7001)[-1].startswith("Connected to Power AI as Nikash Rao.")
    for kind in ("morning_checkin", "feedback_reply:before-pairing"):
        row = world.draft(nikash, kind)
        assert (row["status"], row["resolution"]) == ("skipped", "superseded"), "the pre-pairing backlog is retired"
        assert row["reason"]

    world.moment["now"] = at(15, 9)
    world.say(7001, "reverse a linked list", 2)
    conn = world.db()
    try:
        case = store.case_for_day(conn, nikash, DAY)
        assert case is not None, "a planned day still before training opens as soon as Nikash writes"
        assert [row for row in db.athlete_drafts(conn, nikash) if str(row["status"]) == "pending"] == [], (
            "the agent owns the day, so no generic automated reply is queued")
        # What the old pipeline queued at this point, and which the coach later approves.
        db.create_draft(conn, nikash, "feedback_reply:tg-2", DAY, STALE_REPLY)
        db.create_draft(conn, nikash, "morning_checkin", "2026-09-15", LEGACY_CHECKIN)
    finally:
        conn.close()
    assert world.bodies(7001)[-1] == world.main.CASE_ACK

    world.moment["now"] = at(15, 10)
    world.say(7001, "Slept 6 hours, readiness 5/10, slight knee pain today.", 3)
    conn = world.db()
    try:
        case = store.case_for_day(conn, nikash, DAY)
        assert case["state"] == "needs_coach"
        assert '"injury_open"' in str(case["escalation_json"]), "the pain report moves the case to the coach"
        assert db.injury_state(conn, nikash)[0] is True
    finally:
        conn.close()
    hold = world.bodies(7001)[-1]
    assert "coach" in hold.lower() and CHECKIN_PROMPT not in hold, "guidance pauses with the fixed injury hold"

    world.moment["now"] = at(15, 11)
    refused = world.approve(nikash, "feedback_reply:tg-2")
    assert "Not approved" in refused and "Outdated" in refused
    row = world.draft(nikash, "feedback_reply:tg-2")
    assert (row["status"], row["resolution"]) == ("skipped", "superseded")
    assert row["reason"] in {db.INJURY_REASON, db.NEW_EVIDENCE_REASON}
    assert "Not approved" in world.approve(nikash, "morning_checkin", "2026-09-15")
    assert world.draft(nikash, "morning_checkin", "2026-09-15")["reason"] == db.LEGACY_CHECKIN_REASON
    assert "already sent or retired" in world.approve(nikash, "feedback_reply:tg-2"), "a repeated submission changes nothing"

    world.client.post(f"{url}/message", data={"body": "Ice the knee tonight. I'll call you at 7."})
    world.moment["now"] = at(15, 12)
    world.main._run_agent_tick()
    _send_ticks_concurrently(world)
    world.main._run_agent_tick()
    world.main._send_approved_coach_messages()

    conversation = world.bodies(7001)
    assert conversation.count("Ice the knee tonight. I'll call you at 7.") == 1, "the coach's note goes out once"
    assert not any(CHECKIN_PROMPT in body for body in conversation), "no check-in after sleep, readiness and pain"
    assert STALE_REPLY not in conversation and LEGACY_CHECKIN not in conversation
    assert conversation[0].startswith("Connected to Power AI") and conversation[-1].startswith("Ice the knee")
    assert conversation.index(world.main.CASE_ACK) < conversation.index(hold)


def test_readiness_before_a_queued_check_in_is_approved_never_triggers_it(world, monkeypatch):
    monkeypatch.setattr(world.settings, "enable_agent_loop", False)  # the legacy scheduler's own path
    url, athlete = world.register("Meera Iyer", plan=False)
    conn = world.db()
    try:
        db.link_telegram_chat(conn, chat_id="7002", athlete_id=athlete)
        db.create_draft(conn, athlete, "morning_checkin", DAY, LEGACY_CHECKIN)
    finally:
        conn.close()
    world.moment["now"] = at(7, 0)
    world.say(7002, "slept 7 hours, readiness 8", 1)
    assert "Not approved" in world.approve(athlete, "morning_checkin")
    assert world.draft(athlete, "morning_checkin")["reason"] in {db.CHECKIN_RECEIVED_REASON, db.NEW_EVIDENCE_REASON}

    world.moment["now"] = at(7, 31)
    world.main._send_morning_prompts()
    assert not any(CHECKIN_PROMPT in body or body == LEGACY_CHECKIN for body in world.bodies(7002))


def test_an_approved_reply_that_goes_stale_is_refused_at_send_time(world):
    url, athlete = world.register("Rohit Shah", plan=False)
    conn = world.db()
    try:
        db.link_telegram_chat(conn, chat_id="7003", athlete_id=athlete)
    finally:
        conn.close()
    world.moment["now"] = at(19, 30)
    world.say(7003, "squat 3x5 at 140kg", 1)
    assert world.bodies(7003)[-1] == world.main.FEEDBACK_ACK, "no case, so an honest receipt and no check-in"
    conn = world.db()
    try:
        [reply] = [row for row in db.athlete_drafts(conn, athlete) if str(row["status"]) == "pending"]
    finally:
        conn.close()
    kind, reply_date = str(reply["message_kind"]), str(reply["local_date"])
    assert "Message approved" in world.approve(athlete, kind, reply_date)

    world.say(7003, "slept 5 hours, readiness 4", 2)
    _send_ticks_concurrently(world)
    world.main._send_approved_coach_messages()
    row = world.draft(athlete, kind, reply_date)
    assert (row["status"], row["resolution"]) == ("skipped", "superseded")
    assert row["reason"] in {db.NEW_EVIDENCE_REASON, db.NEW_MESSAGE_REASON}
    assert world.bodies(7003)[-1] == world.main.FEEDBACK_ACK, "nothing further reached the athlete"
    assert not any(CHECKIN_PROMPT in body for body in world.bodies(7003)), "training time passed: no retroactive check-in"


def test_a_fresh_approved_reply_goes_out_once_despite_repeated_approvals_and_simultaneous_ticks(world):
    url, athlete = world.register("Kavya Suresh", plan=False)
    conn = world.db()
    try:
        db.link_telegram_chat(conn, chat_id="7004", athlete_id=athlete)
    finally:
        conn.close()
    world.moment["now"] = at(19, 30)
    world.say(7004, "bench 5x5 at 60kg", 1)
    conn = world.db()
    try:
        [reply] = [row for row in db.athlete_drafts(conn, athlete) if str(row["status"]) == "pending"]
    finally:
        conn.close()
    kind, body, reply_date = str(reply["message_kind"]), str(reply["body"]), str(reply["local_date"])
    for _ in range(3):
        world.approve(athlete, kind, reply_date)
    _send_ticks_concurrently(world, workers=6)
    world.main._send_approved_coach_messages()
    assert world.bodies(7004).count(body) == 1
    row = world.draft(athlete, kind, reply_date)
    assert row["status"] == "sent" and row["reason"] == outbox.REPLY_SENT_REASON


def test_a_coach_note_stays_valid_across_new_evidence_while_the_automated_reply_does_not(world):
    url, athlete = world.register("Dev Patel", plan=False)
    conn = world.db()
    try:
        db.link_telegram_chat(conn, chat_id="7005", athlete_id=athlete)
        db.create_draft(conn, athlete, "feedback_reply:auto", DAY, STALE_REPLY)
        db.review_draft(conn, athlete, "feedback_reply:auto", DAY, status="approved", reviewed_by="Coach Rao")
        drafted_from = int(db.draft(conn, athlete, "feedback_reply:auto", DAY)["evidence_version"])
    finally:
        conn.close()
    world.client.post(f"{url}/message", data={"body": "Proud of this week. Rest well."})
    world.moment["now"] = at(19, 45)
    world.say(7005, "slept 8 hours, readiness 9", 1)
    world.main._send_approved_coach_messages()
    conversation = world.bodies(7005)
    assert "Proud of this week. Rest well." in conversation
    assert STALE_REPLY not in conversation
    row = world.draft(athlete, "feedback_reply:auto")
    assert int(row["evidence_version"]) == drafted_from, "approval never re-dates the evidence a draft came from"


def test_approved_messages_leave_in_the_order_they_were_written(world):
    url, athlete = world.register("Ananya Rao", plan=False)
    conn = world.db()
    try:
        db.link_telegram_chat(conn, chat_id="7006", athlete_id=athlete)
        # Paired before both messages were written, so neither is a pre-pairing backlog.
        conn.execute("UPDATE telegram_links SET linked_at = ? WHERE athlete_id = ?",
                     ("2026-09-14T08:00:00+00:00", athlete))
        conn.commit()
        for kind, body, created in (("coach_note:later", "Second, written later.", "2026-09-14T10:00:00+00:00"),
                                    ("feedback_reply:earlier", "First, written earlier.", "2026-09-14T09:00:00+00:00")):
            db.create_draft(conn, athlete, kind, DAY, body)
            conn.execute("UPDATE outbound_drafts SET created_at = ? WHERE athlete_id = ? AND message_kind = ?",
                         (created, athlete, kind))
            conn.commit()
            db.review_draft(conn, athlete, kind, DAY, status="approved", reviewed_by="Coach Rao")
    finally:
        conn.close()
    world.moment["now"] = at(19, 0)
    world.main._send_approved_coach_messages()
    assert world.bodies(7006) == ["First, written earlier.", "Second, written later."]


def test_legacy_morning_drafts_are_retired_at_startup_without_losing_history(world):
    conn = world.db()
    try:
        db.register_athlete(conn, "+919812340099", "Legacy Athlete", on="2026-09-01")
        for local_date, status in (("2026-09-12", "sent"), ("2026-09-13", "approved"), ("2026-09-14", "pending")):
            db.create_draft(conn, "+919812340099", "morning_checkin", local_date, LEGACY_CHECKIN)
            if status != "pending":
                conn.execute("UPDATE outbound_drafts SET status = ? WHERE athlete_id = ? AND local_date = ?",
                             (status, "+919812340099", local_date))
                conn.commit()
    finally:
        conn.close()
    with TestClient(world.main.app):
        pass  # a restart runs the cleanup
    rows = {date: world.draft("+919812340099", "morning_checkin", date) for date in ("2026-09-12", "2026-09-13", "2026-09-14")}
    assert rows["2026-09-12"]["status"] == "sent", "delivered history is untouched"
    for date in ("2026-09-13", "2026-09-14"):
        assert (rows[date]["status"], rows[date]["resolution"]) == ("skipped", "superseded")
        assert rows[date]["reason"] == db.LEGACY_CHECKIN_REASON


def test_stale_drafts_cannot_look_like_approvable_messages(world):
    url, athlete = world.register("Sameer Bhat", plan=False)
    conn = world.db()
    try:
        db.link_telegram_chat(conn, chat_id="7007", athlete_id=athlete)
        db.create_draft(conn, athlete, "feedback_reply:auto", DAY, STALE_REPLY)
    finally:
        conn.close()
    world.moment["now"] = at(19, 0)
    world.say(7007, "slept 6 hours, knee pain on stairs", 1)

    today = BeautifulSoup(world.client.get("/coach").text, "html.parser")
    card = today.select_one('#needs-you .decision[data-kind="stale"]')
    assert card is not None
    assert card.select_one(".decision-problem").get_text(strip=True) == "Outdated—new athlete information received"
    assert card.select('button[value="approved"]') == []
    desk = BeautifulSoup(world.client.get("/coach/whatsapp?tab=approval").text, "html.parser")
    stale = desk.select_one("article.approval-card.is-stale")
    assert "Outdated—new athlete information received" in stale.get_text(" ")
    assert stale.select('button[value="approved"]') == [] and stale.select("textarea") == []
    athlete_page = BeautifulSoup(world.client.get(url).text, "html.parser")
    item = next(li for li in athlete_page.select("#outbox .outbox-item") if STALE_REPLY in li.get_text())
    assert item.select_one(".delivery-badge").get_text(strip=True) == "Outdated—new athlete information received"
