"""A simulated week through the real service: Telegram webhooks, signed ticks, coach buttons.

Nothing here calls the engine directly. Athletes talk to the bot, the external
scheduler calls the signed tick endpoint, and the coach presses Telegram
buttons, exactly as in production. Only the clock and Telegram's HTTP API are
simulated.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import access, deployment
from app.casework import clock, store
from app.storage import db

TZ = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 9, 14)
ROUTINE, QUIET, INJURED = "+919812340001", "+919812340002", "+919812340003"
CHATS = {ROUTINE: "7001", QUIET: "7002", INJURED: "7003"}
COACH_CHAT = "9001"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "webhook_secret-123"}


class World:
    def __init__(self, main, settings, monkeypatch):
        self.main = main
        self.settings = settings
        self.now = datetime(2026, 9, 14, 0, 0, tzinfo=TZ)
        self.sent: list[dict] = []
        self.message_id = 1000
        monkeypatch.setattr(clock, "utcnow", lambda: self.now)
        monkeypatch.setattr(main.telegram, "send_outbound", self._send)
        monkeypatch.setattr(main.telegram, "answer_callback_query", lambda *_: None)
        self.client = TestClient(main.app)

    def _send(self, chat_id, body, reply_markup=None):
        self.sent.append({"chat": str(chat_id), "body": body, "markup": reply_markup})
        return f"telegram:{chat_id}:{len(self.sent)}"

    def at(self, day: date, clock_time: str) -> None:
        hour, minute = (int(piece) for piece in clock_time.split(":"))
        self.now = datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)

    def tick(self, day: date, clock_time: str) -> dict:
        self.at(day, clock_time)
        stamp = str(int(time.time()))
        response = self.client.post("/internal/agent/tick", headers={
            "X-Agent-Timestamp": stamp, "X-Agent-Signature": access.tick_signature(stamp)})
        assert response.status_code == 200
        return response.json()

    def say(self, athlete_id: str, text: str, day: date, clock_time: str, *, message_id=None):
        self.at(day, clock_time)
        if message_id is None:
            self.message_id += 1
            message_id = self.message_id
        chat = CHATS.get(athlete_id, athlete_id)
        return self.client.post("/webhook/telegram", headers=HEADERS, json={"message": {
            "message_id": message_id, "text": text, "chat": {"id": int(chat), "type": "private"}}})

    def to(self, athlete_id: str) -> list[str]:
        return [item["body"] for item in self.sent if item["chat"] == CHATS[athlete_id]]

    def coach_messages(self) -> list[dict]:
        return [item for item in self.sent if item["chat"] == COACH_CHAT]

    def db(self):
        conn = db.connect(self.settings.database_path)
        db.init_db(conn)
        return conn


@pytest.fixture()
def world(tmp_path, monkeypatch):
    from app import main
    from app.config import settings

    for name, value in {
        "database_path": str(tmp_path / "scenario.db"),
        "gemini_api_key": "",
        "coach_name": "Coach Rao",
        "public_base_url": "https://agent.example.com",
        "coach_link_secret": "link-secret",
        "agent_tick_secret": "tick-secret",
        "coach_setup_code": "setup-code-7731",
        "telegram_bot_token": "123456:test-token",
        "telegram_bot_username": "PowerCoachTestBot",
        "telegram_webhook_secret": "webhook_secret-123",
        "telegram_link_secret": "pairing-secret",
        "enable_agent_loop": True,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(main.telegram, "configure_webhook", lambda: None)
    # Stands in for durable Postgres so the week runs on a local file; the live
    # Postgres test runs the same path against a real database.
    monkeypatch.setattr(deployment, "durable_storage_configured", lambda: True)
    main.get_model_client.cache_clear()

    conn = db.connect(settings.database_path)
    db.init_db(conn)
    start = datetime(2026, 9, 13, 12, 0, tzinfo=TZ)
    for athlete_id, name in ((ROUTINE, "Priya Kulkarni"), (QUIET, "Neha Desai"), (INJURED, "Vikram Iyer")):
        db.register_athlete(conn, athlete_id, name, on="2026-09-01")
        db.insert_entry(conn, db.Entry(
            athlete_id=athlete_id, kind="status", timezone="Asia/Kolkata",
            morning_checkin_time="07:30", training_time="18:00", session_date="2026-09-01"))
        db.link_telegram_chat(conn, chat_id=CHATS[athlete_id], athlete_id=athlete_id)
        for weekday in range(7):
            store.add_plan_session(conn, athlete_id=athlete_id, weekday=weekday, lift="squat",
                                   sets=4, reps=5, rpe=7, approved_by="Coach Rao", now=start)
        store.set_autopilot(conn, athlete_id, True, updated_by="Coach Rao", now=start)
    conn.close()

    simulated = World(main, settings, monkeypatch)
    with simulated.client:
        simulated.say(COACH_CHAT, "/coach setup-code-7731", MONDAY, "06:00")
        yield simulated


def test_a_week_owned_by_the_agent(world):
    w = world
    assert w.coach_messages()[-1]["body"].startswith("Linked."), "the coach linked Telegram with the setup code"

    # --- Monday morning: the agent opens three training days and checks in on its own.
    w.tick(MONDAY, "07:00")
    assert w.to(ROUTINE) == [], "nothing before the check-in time"
    report = w.tick(MONDAY, "07:31")
    assert report["actions"] == 3
    assert all("training day" in w.to(a)[0] for a in (ROUTINE, QUIET, INJURED))

    # 1. Routine athlete: reply → session delivered with no coach involvement.
    w.say(ROUTINE, "slept 8h readiness 8", MONDAY, "08:05")
    session = w.to(ROUTINE)[-1]
    assert "Squat 4×5 @ RPE 7" in session and "from Coach Rao's approved plan" in session

    # A Telegram retry of the same update produces nothing new.
    retried = len(w.sent)
    w.say(ROUTINE, "slept 8h readiness 8", MONDAY, "08:06", message_id=w.message_id)
    assert len(w.sent) == retried

    # 3. Injury: session sent, then pain reported → guidance stops at once, coach gets buttons.
    w.say(INJURED, "slept 7h readiness 7", MONDAY, "08:10")
    assert "Squat 4×5" in w.to(INJURED)[-1]
    w.say(INJURED, "tweaked my knee, pain on stairs", MONDAY, "08:20")
    assert "paused all training guidance" in w.to(INJURED)[-1]
    assert "don't train the session I sent earlier" in w.to(INJURED)[-1]
    alert = w.coach_messages()[-1]
    assert "Injury reported" in alert["body"] and "Vikram Iyer" in alert["body"]
    buttons = [row[0] for row in alert["markup"]["inline_keyboard"]]
    assert any(button.get("url", "").startswith("https://agent.example.com/coach/enter?token=") for button in buttons)
    choices = {button["text"]: button["callback_data"] for button in buttons if "callback_data" in button}
    assert "Rest today" in choices

    # A new check-in cannot restart autonomous guidance while the decision is pending:
    # the athlete gets only the neutral "guidance is paused" receipt, never a session.
    before = len(w.to(INJURED))
    w.say(INJURED, "slept 9h readiness 9", MONDAY, "08:25")
    after = w.to(INJURED)[before:]
    assert after and all("Squat" not in body and "RPE" not in body for body in after)
    assert "Training guidance is paused" in after[-1]

    # 5. Restart: a fresh process at the same moment repeats nothing.
    sent_before_restart = len(w.sent)
    w.client.__exit__(None, None, None)
    w.client = TestClient(w.main.app)
    w.client.__enter__()
    w.tick(MONDAY, "08:25")
    w.tick(MONDAY, "08:25")
    assert len(w.sent) == sent_before_restart

    # 4. The coach decides from Telegram; the case continues rather than ending.
    pivot = next(data for text, data in choices.items() if text != "Rest today")
    decided = w.client.post("/webhook/telegram", headers=HEADERS, json={"callback_query": {
        "id": "cb-1", "data": pivot, "message": {"chat": {"id": int(COACH_CHAT)}}}})
    assert decided.text == "decided"
    assert w.coach_messages()[-1]["body"].startswith("Done:")
    again = w.client.post("/webhook/telegram", headers=HEADERS, json={"callback_query": {
        "id": "cb-2", "data": pivot, "message": {"chat": {"id": int(COACH_CHAT)}}}})
    assert again.text == "refused", "a second press cannot decide twice"
    forged = w.client.post("/webhook/telegram", headers=HEADERS, json={"callback_query": {
        "id": "cb-3", "data": pivot, "message": {"chat": {"id": 7003}}}})
    assert forged.text == "not the coach chat"

    # 2. Unresponsive athlete: exactly two follow-ups, then the day closes without guidance.
    for moment in ("09:02", "11:02", "13:32"):
        w.tick(MONDAY, moment)
    quiet = w.to(QUIET)
    assert len(quiet) == 3 and "Quick nudge" in quiet[1] and "Last check" in quiet[2]
    assert not any("Squat 4×5" in body for body in quiet)

    # Evening: the agent asks whether training happened and closes only on the answer.
    w.tick(MONDAY, "20:31")
    assert "How did today go" in w.to(ROUTINE)[-1]
    assert "adjusted plan" in w.to(INJURED)[-1]
    w.say(ROUTINE, "squat 4x5 at 140kg rpe 7", MONDAY, "21:00")
    assert w.to(ROUTINE)[-1].startswith("Logged, Priya")
    w.say(INJURED, "done", MONDAY, "21:05")

    conn = w.db()
    try:
        outcomes = {a: store.case_for_day(conn, a, "2026-09-14") for a in (ROUTINE, QUIET, INJURED)}
        assert (outcomes[ROUTINE]["state"], outcomes[ROUTINE]["outcome"]) == ("closed", "completed")
        assert (outcomes[QUIET]["state"], outcomes[QUIET]["outcome"]) == ("closed", "no_response")
        assert (outcomes[INJURED]["state"], outcomes[INJURED]["outcome"]) == ("closed", "done")
        assert db.injury_state(conn, INJURED)[0] is True, "only independent clearance closes an injury"
        routine_events = store.case_events(conn, outcomes[ROUTINE]["id"])
        assert not any(row["kind"] in {"escalation", "coach"} for row in routine_events)
        assert {row["kind"] for row in routine_events} >= {
            "observation", "decision", "action", "expectation", "outcome"}
        keys = [row["idempotency_key"] for row in conn.execute(
            "SELECT idempotency_key FROM agent_events WHERE idempotency_key IS NOT NULL")]
        assert len(keys) == len(set(keys))
    finally:
        conn.close()

    # 6. Adaptation: Priya answers late Tuesday to Thursday. With four measured days
    #    (34, 99, 99, 99 minutes) Friday's check-in moves later, visibly and within limits.
    for offset in range(1, 4):
        day = MONDAY + timedelta(days=offset)
        w.tick(day, "07:31")
        w.say(ROUTINE, "slept 8h readiness 8", day, "09:10")
        w.say(ROUTINE, "done", day, "19:00")
    friday = MONDAY + timedelta(days=4)
    report = w.tick(friday, "07:00")
    assert report["adaptations"] == 1
    checkins_before = sum("training day" in body for body in w.to(ROUTINE))
    w.tick(friday, "07:31")
    assert sum("training day" in body for body in w.to(ROUTINE)) == checkins_before
    w.tick(friday, "08:01")
    assert sum("training day" in body for body in w.to(ROUTINE)) == checkins_before + 1
    saturday = MONDAY + timedelta(days=5)
    assert w.tick(saturday, "07:00")["adaptations"] == 0, "it needs new evidence before moving again"

    today = w.client.get("/coach").text
    assert "Handled by the agent" in today
    assert "Priya Kulkarni: check-in 07:30 → 08:00" in today
    assert "median 99 minutes" in today
    assert "Silent on consecutive training days" in today, "Neha's second silent day reached the coach"

    conn = w.db()
    try:
        record = store.latest_adaptation(conn, ROUTINE, "checkin_time")
        assert (record["old_value"], record["new_value"]) == ("07:30", "08:00")
        assert "never be earlier than the coach's 07:30" in record["explanation"]
    finally:
        conn.close()
