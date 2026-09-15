"""The coach console as an operational workspace.

Today answers four questions in order: what needs me, what the agent handled,
what happens next, and which athletes are ready, blocked or awaiting setup. The
athlete page opens on status and the next agent action, then separate tabs.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import deployment
from app.casework import clock, engine, store
from app.channels import telegram
from app.scheduling import outbox
from app.storage import db

HEADERS = {"X-Telegram-Bot-Api-Secret-Token": "webhook_secret-123"}
BEFORE_CHECKIN = datetime(2026, 9, 14, 0, 30, tzinfo=timezone.utc)   # Monday 06:00 in Kolkata
AFTER_CHECKIN = datetime(2026, 9, 14, 2, 1, tzinfo=timezone.utc)     # Monday 07:31 in Kolkata
LATER = datetime.now(timezone.utc) + timedelta(days=1)


class Quiet:
    def send_athlete(self, conn, athlete_id, body, *, kind):
        return "fake"

    def notify_coach(self, conn, **_):
        return None


def _open(tmp_path, monkeypatch, moment):
    from app import main
    from app.config import settings

    for name, value in {
        "database_path": str(tmp_path / "console.db"), "database_url": "",
        "public_base_url": "https://agent.example.com", "coach_link_secret": "",
        "telegram_bot_token": "123456:test-token", "telegram_bot_username": "PowerCoachTestBot",
        "telegram_webhook_secret": "webhook_secret-123", "telegram_link_secret": "pairing-secret",
        "coach_name": "Coach Rao", "gemini_api_key": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(main.telegram, "configure_webhook", lambda: None)
    monkeypatch.setattr(main.telegram, "send_outbound",
                        lambda chat_id, body, **_: telegram.provider_sid(chat_id, 900_001))
    monkeypatch.setattr(main, "LiveTransport", Quiet)
    monkeypatch.setattr(deployment, "durable_storage_configured", lambda: True)
    monkeypatch.setattr(clock, "utcnow", lambda: moment)
    main.get_model_client.cache_clear()
    return TestClient(main.app), settings


@pytest.fixture()
def morning(tmp_path, monkeypatch):
    client, settings = _open(tmp_path, monkeypatch, BEFORE_CHECKIN)
    with client:
        yield client, settings


@pytest.fixture()
def checkin_time(tmp_path, monkeypatch):
    client, settings = _open(tmp_path, monkeypatch, AFTER_CHECKIN)
    with client:
        yield client, settings


def _register(client, name: str) -> tuple[str, str]:
    landed = client.post("/coach/athletes/register", data={
        "name": name, "timezone": "Asia/Kolkata", "checkin_time": "07:30", "training_time": "18:00"})
    url = urlparse(str(landed.url)).path
    return url, url.rsplit("/", 1)[1]


def _connect(settings, athlete_id: str, chat_id: str) -> None:
    conn = db.connect(settings.database_path)
    try:
        db.link_telegram_chat(conn, chat_id=chat_id, athlete_id=athlete_id)
    finally:
        conn.close()


def _ready(client, settings, name: str, chat_id: str, *, autopilot: str = "on") -> tuple[str, str]:
    url, athlete_id = _register(client, name)
    _connect(settings, athlete_id, chat_id)
    client.post(f"{url}/plan", data={"weekday": "0", "lift": "squat", "sets": "4", "reps": "5", "rpe": "7"})
    client.post(f"{url}/autopilot", data={"enabled": autopilot})
    return url, athlete_id


def _soup(client, path: str) -> BeautifulSoup:
    return BeautifulSoup(client.get(path).text, "html.parser")


def _counts(soup: BeautifulSoup) -> dict[str, int]:
    return {node["data-count"]: int(node.select_one(".count-num").get_text()) for node in soup.select("[data-count]")}


# --- Today ------------------------------------------------------------------------


def test_no_athletes_shows_only_the_way_in(morning):
    client, _ = morning
    soup = _soup(client, "/coach")
    assert soup.select_one("#empty-console") is not None
    assert soup.select_one(".ops-counts") is None and soup.select_one("#needs-you") is None
    assert soup.select_one("details#tools") is not None


def test_today_answers_the_four_questions_in_order_with_a_decision_first(checkin_time):
    client, settings = checkin_time
    _, priya = _ready(client, settings, "Priya Kulkarni", "7001", autopilot="off")
    _ready(client, settings, "Rohit Shah", "7002", autopilot="on")
    client.post("/coach/agent/run", data={"return_to": "/coach"})
    conn = db.connect(settings.database_path)
    try:
        engine.observe_message(conn, priya, [engine.LogCheckIn(checked_on="2026-09-14", sleep_hours=8, readiness=8)],
                               raw_text="slept 8h readiness 8", now=clock.utcnow(), transport=Quiet(),
                               coach_name="Coach Rao")
        case = store.case_for_day(conn, priya, "2026-09-14")
    finally:
        conn.close()
    assert case["state"] == "needs_coach"

    html = client.get("/coach").text
    soup = BeautifulSoup(html, "html.parser")
    assert _counts(soup) == {"decisions": 1, "running": 1, "upcoming": 1}
    assert "is-hot" in soup.select_one('[data-count="decisions"]')["class"]
    positions = [html.index(marker) for marker in ('id="needs-you"', 'id="activity"', 'id="next"', 'id="squad"')]
    assert positions == sorted(positions)

    card = soup.select_one('#needs-you .decision[data-kind="case"]')
    assert card.select_one("h3").get_text(strip=True) == "Priya Kulkarni"
    problem = card.select_one(".decision-problem")
    assert problem.contents[0].strip().rstrip("·").strip() == "Session waiting for approval"
    assert problem.select_one("a.decision-timeline")["href"] == f"/coach/case/{case['id']}"
    assert 1 <= len(card.select(".decision-evidence li")) <= 2, "essential evidence only; the rest is behind Why?"
    assert card.select_one("details.why") is not None
    assert "Send the adjusted session" in card.select_one(".rec").get_text()
    buttons = [button.get_text(strip=True) for button in card.select(".decision-controls button")]
    assert buttons[:2] == ["Send the adjusted session", "Rest today"]
    assert {form["action"] for form in card.select(".decision-controls form")} == {f"/coach/case/{case['id']}/decide"}
    assert all(field["value"] == "/coach" for field in card.select('input[name="return_to"]'))
    links = {a.get_text(strip=True): a["href"] for a in card.select(".decision-controls a")}
    assert links["Modify"].endswith("#agent-plan") and links["Message"].endswith("#messages")
    assert "Pause autopilot" not in buttons, "autopilot is already off for Priya"

    assert "Sent the morning check-in." in soup.select_one("#activity").get_text()
    upcoming = soup.select_one("#next").get_text(" ")
    assert "Rohit Shah" in upcoming and "Waiting for athlete check-in" in upcoming
    squad = {node["data-squad"]: node.get_text(strip=True) for node in soup.select("[data-squad]")}
    assert squad == {"attention": "Needs you 1", "running": "Running 1"}

    decided = client.post(f"/coach/case/{case['id']}/decide", data={"option": "send", "return_to": "/coach"})
    after = BeautifulSoup(decided.text, "html.parser")
    assert after.select_one("[data-caught-up]") is not None, "deciding clears the only item"
    assert _counts(after)["decisions"] == 0


def test_all_caught_up_says_what_comes_next(morning):
    client, settings = morning
    _ready(client, settings, "Priya Kulkarni", "7001")
    soup = _soup(client, "/coach")
    caught_up = soup.select_one("[data-caught-up]")
    assert caught_up.select_one("strong").get_text() == "All caught up"
    assert "Priya Kulkarni · Check-in today at 07:30." in caught_up.get_text()
    assert _counts(soup) == {"decisions": 0, "running": 1, "upcoming": 1}
    assert "is-hot" not in soup.select_one('[data-count="decisions"]')["class"]


def test_a_failed_message_is_surfaced_with_a_way_to_act(morning):
    client, settings = morning
    url, _ = _ready(client, settings, "Priya Kulkarni", "7001")
    client.post(f"{url}/message", data={"body": "Check in after training tonight."})

    def broken(_athlete, _body):
        raise RuntimeError("Telegram send request failed")

    conn = db.connect(settings.database_path)
    try:
        outbox.send_approved_notes(conn, broken, now_utc=LATER)
    finally:
        conn.close()
    card = _soup(client, "/coach").select_one('#needs-you .decision[data-kind="failure"]')
    assert card.select_one(".decision-problem").get_text(strip=True) == "Message not delivered"
    assert "Check in after training tonight." in card.get_text()
    assert card.select_one(".decision-controls a")["href"] == f"{url}#messages"


def test_a_failed_telegram_pairing_is_a_coach_item_and_opens_troubleshooting(morning):
    client, settings = morning
    url, _ = _register(client, "Nikash Rao")
    other_url, _ = _register(client, "Rohit Shah")
    page = _soup(client, url)
    assert not page.select_one("details.invite-help").has_attr("open"), "troubleshooting stays folded by default"
    old = parse_qs(urlparse(page.select_one("button[data-copy]")["data-copy"]).query)["start"][0]
    client.post(f"{url}/telegram/refresh-invite")
    client.post("/webhook/telegram", headers=HEADERS, json={"message": {
        "message_id": 1, "text": f"/start {old}", "chat": {"id": 8001, "type": "private"}}})

    card = _soup(client, "/coach").select_one('#needs-you .decision[data-kind="setup"]')
    assert card.select_one("h3").get_text(strip=True) == "Nikash Rao"
    assert card.select_one(".decision-problem").get_text(strip=True) == "Telegram invite didn't work"
    assert card.select_one(".decision-controls a")["href"] == f"{url}#telegram"
    assert _soup(client, url).select_one("details.invite-help").has_attr("open")
    assert not _soup(client, other_url).select_one("details.invite-help").has_attr("open")

    row = _soup(client, "/coach/athletes").select_one(f'tr.athlete-record a[href="{url}"]').find_parent("tr")
    assert row["data-state"] == "attention"
    assert row.select_one('[data-col="connection"]').get_text(strip=True) == "Invite failed"


def test_console_pages_use_labels_not_explanations(morning):
    client, settings = morning
    client.post("/coach/demo/seed")
    url, _ = _ready(client, settings, "Priya Kulkarni", "7001")
    for path in ("/coach", "/coach/athletes", url):
        html = client.get(path).text
        for phrase in ("Daily agent loop", "How to use Coach Desk", "Recommendations shown here",
                       "Each step unlocks the next"):
            assert phrase not in html, (path, phrase)
        soup = BeautifulSoup(html, "html.parser")
        for hidden in soup.select("details, script, style, textarea, blockquote"):
            hidden.decompose()
        long = [p.get_text(" ", strip=True) for p in soup.select("main p") if len(p.get_text(" ", strip=True)) > 140]
        assert long == [], (path, long)


# --- Roster -------------------------------------------------------------------------


def test_the_roster_is_one_dense_row_per_athlete(morning):
    client, settings = morning
    client.post("/coach/demo/seed")
    _register(client, "Nikash Rao")
    _ready(client, settings, "Meera Iyer", "7001")  # not a demo name, so the lookup below is unambiguous
    soup = _soup(client, "/coach/athletes")
    conn = db.connect(settings.database_path)
    try:
        athletes = len(db.list_athletes(conn))
    finally:
        conn.close()
    rows = soup.select("tr.athlete-record")
    assert len(rows) == athletes
    for row in rows:
        assert [cell["data-col"] for cell in row.select("td")] == ["athlete", "connection", "readiness", "next", "status"]
        assert row.select_one('[data-col="status"] .chip').get_text(strip=True) in {
            "Needs you", "Blocked", "Awaiting setup", "Running", "Ready"}
        assert row.select_one('[data-col="next"]').get_text(strip=True)
    states = [row["data-state"] for row in rows]
    order = ["attention", "blocked", "setup", "running", "ready"]
    assert states == sorted(states, key=order.index), "attention first"
    nikash = soup.find("a", string="Nikash Rao").find_parent("tr")
    assert nikash.select_one('[data-col="next"]').get_text(strip=True) == "Send the Telegram invite"
    meera = soup.find("a", string="Meera Iyer").find_parent("tr")
    assert meera["data-state"] == "running"
    assert meera.select_one('[data-col="connection"]').get_text(strip=True) == "Connected"


# --- Athlete page -----------------------------------------------------------------


def test_athlete_page_shows_a_short_checklist_until_setup_is_done(morning):
    client, settings = morning
    url, athlete_id = _register(client, "Nikash Rao")
    soup = _soup(client, url)
    top = soup.select_one(".athlete-top")
    assert top.find(True)["id"] == "agent-status", "status and the next action come first"
    assert top.select_one('[data-status="next-action"]') is not None
    assert len(soup.select(".stepper .stepper-step")) == 4
    assert soup.select_one("#telegram") is not None
    assert [tab.get_text(strip=True) for tab in soup.select(".athlete-tabs [role=tab]")] == [
        "Plan", "Evidence", "Messages", "Profile"]
    assert [panel["id"] for panel in soup.select("[role=tabpanel]")] == [
        "panel-plan", "panel-evidence", "panel-messages", "panel-profile"]
    assert soup.select_one("details.plan-editor").has_attr("open"), "an empty plan opens straight into editing"

    _connect(settings, athlete_id, "7009")
    client.post(f"{url}/plan", data={"weekday": "0", "lift": "squat", "sets": "4", "reps": "5", "rpe": "7"})
    client.post(f"{url}/autopilot", data={"enabled": "on"})
    soup = _soup(client, url)
    assert soup.select_one(".stepper") is None and soup.select_one("#telegram") is None
    assert soup.select_one("#agent-status h2").get_text(strip=True) == "Running automatically"
    editor = soup.select_one("details.plan-editor")
    assert not editor.has_attr("open") and editor.summary.get_text(strip=True) == "Edit plan"
    read_only = soup.select_one("#agent-plan > ul.plan-list")
    assert read_only.select("form") == [], "the plan is read-only until Edit plan"
    assert "Squat" in read_only.get_text() and "4×5 · RPE 7" in read_only.get_text()
    dates = [node.get_text() for node in soup.select(".athlete-top")]
    assert "2026-09-14" not in " ".join(dates), "the top of the page does not repeat the date"


def test_athlete_page_attention_and_latest_evidence_first(morning):
    client, _ = morning
    client.post("/coach/demo/seed")
    injured = _soup(client, "/coach/athlete/+99900000001")
    strip = injured.select_one(".athlete-top").find(True)
    assert strip["id"] == "attention"
    assert strip.select_one("strong").get_text() == "Priya needs a decision"
    assert strip.select_one("a")["href"] == "#clearance-review"

    stalled = _soup(client, "/coach/athlete/+99900000002")
    evidence = stalled.select_one("#evidence")
    assert len(evidence.select("h3 + table tbody tr")) <= 3 or evidence.select_one(".sub-head")
    latest = evidence.find("h3", string="Latest sessions").find_next("table")
    assert len(latest.select("tbody tr")) == 3
    history = evidence.select_one("details.history")
    assert history is not None and not history.has_attr("open")
    assert history.select_one("svg") is not None, "progress charts are preserved behind History"
    assert "squat — stalled" in evidence.select_one(".signal-chips").get_text()
