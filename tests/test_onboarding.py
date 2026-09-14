"""From an empty console to a ready agent, as a coach experiences it."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import deployment
from app.casework import clock, store
from app.channels import telegram
from app.storage import db


@pytest.fixture()
def coach(tmp_path, monkeypatch):
    from app import main
    from app.config import settings

    for name, value in {
        "database_path": str(tmp_path / "onboarding.db"),
        "database_url": "",
        "public_base_url": "https://agent.example.com",
        "coach_link_secret": "",
        "telegram_bot_token": "123456:test-token",
        "telegram_bot_username": "PowerCoachTestBot",
        "telegram_webhook_secret": "webhook_secret-123",
        "telegram_link_secret": "pairing-secret",
        "coach_name": "Coach Rao",
        "gemini_api_key": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(main.telegram, "configure_webhook", lambda: None)
    monkeypatch.setattr(main.telegram, "send_outbound", lambda *_a, **_k: pytest.fail("nothing may be sent"))
    # Durable storage is what a correctly configured deployment has; the blocked case is tested below.
    monkeypatch.setattr(deployment, "durable_storage_configured", lambda: True)
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2026, 9, 14, 0, 30, tzinfo=timezone.utc))  # 06:00 IST Monday
    with TestClient(main.app) as client:
        yield client, settings


def visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for hidden in soup.select("details, script, style, input, form"):
        hidden.decompose()
    return soup.get_text(" ")


def steps(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    return dict(item["data-step-state"].split(":") for item in soup.select("[data-step-state]"))


def add_athlete(client, **overrides):
    form = {"name": "Priya Nair", "timezone": "Asia/Kolkata", "checkin_time": "07:30", "training_time": "18:00"}
    form.update(overrides)
    return client.post("/coach/athletes/register", data=form)


def test_an_empty_console_offers_exactly_two_ways_in(coach):
    client, _ = coach
    page = client.get("/coach").text
    soup = BeautifulSoup(page, "html.parser")
    assert ("This is your private real-agent console. Start by inviting an athlete, "
            "or watch the fictional demo first.") in page
    primary = [(a.get_text(strip=True), a["href"]) for a in soup.select("#empty-console .empty-actions a")]
    assert primary == [("Set up a real athlete", "/coach/athletes/new"), ("Watch the safe demo", "/demo")]
    assert "Set up your agent" in page and "0 of 6 done" in page
    assert "What happens next" not in page and "ops-counts" not in page, "an empty console shows no empty machinery"


def test_registering_needs_no_identifier_and_ends_on_a_telegram_invite(coach):
    client, settings = coach
    form = client.get("/coach/athletes/new").text
    assert 'name="athlete_id"' not in form

    landed = add_athlete(client)
    assert landed.status_code == 200
    assert "/coach/athlete/athlete-" in str(landed.url) and "welcome=1" in str(landed.url)
    page = landed.text
    soup = BeautifulSoup(page, "html.parser")
    assert "Priya Nair added" in page
    button = soup.select_one("button[data-copy]")
    assert button.get_text(strip=True) == "Copy invite for Priya"
    invite = button["data-copy"]
    assert invite.startswith("https://t.me/PowerCoachTestBot?start=")
    athlete_id, _ = telegram.athlete_from_pairing_token(unquote(parse_qs(urlparse(invite).query)["start"][0]))
    assert db.is_generated_athlete_id(athlete_id)
    assert "Priya is not connected yet" in page
    assert "Waiting for Priya to press Start" in page
    assert athlete_id not in visible_text(page), "the internal identifier stays out of the normal UI"
    assert athlete_id in soup.select_one("details#advanced").get_text()

    conn = db.connect(settings.database_path)
    try:
        schedule = db.latest_schedule_settings(conn, athlete_id)
        assert (schedule["timezone"], schedule["morning_checkin_time"], schedule["training_time"]) == (
            "Asia/Kolkata", "07:30", "18:00")
    finally:
        conn.close()

    refused = add_athlete(client, name="Late Starter", checkin_time="19:00", training_time="18:00")
    assert "/coach/athletes/new" in str(refused.url) and "Not added" in refused.text


def test_the_checklist_detects_each_step_and_links_to_the_right_screen(coach):
    client, settings = coach
    page = add_athlete(client)
    athlete_url = urlparse(str(page.url)).path
    athlete_id = athlete_url.rsplit("/", 1)[1]

    today = client.get("/coach").text
    assert steps(today) == {"coach": "todo", "athlete": "done", "paired": "todo", "plan": "todo",
                            "autopilot": "todo", "ready": "todo"}
    links = {a["data-step"]: a["href"] for a in BeautifulSoup(today, "html.parser").select("a[data-step]")}
    assert links["coach"] == "/coach/setup#coach-telegram"
    assert links["paired"] == f"{athlete_url}#telegram"
    assert "@PowerCoachTestBot" in client.get(links["coach"]).text

    conn = db.connect(settings.database_path)
    db.link_telegram_chat(conn, chat_id="7001", athlete_id=athlete_id)  # the athlete pressed Start
    conn.close()
    status = client.get(f"{athlete_url}/status.json").json()
    assert status["telegram_connected"] is True
    assert status["next_step"] == {"label": "Create weekly plan", "href": f"{athlete_url}#agent-plan"}
    assert steps(client.get("/coach").text)["paired"] == "done"

    client.post(f"{athlete_url}/plan", data={"weekday": "0", "lift": "squat", "sets": "4", "reps": "5", "rpe": "7"})
    assert steps(client.get("/coach").text)["plan"] == "done"
    client.post(f"{athlete_url}/autopilot", data={"enabled": "on"})
    after = steps(client.get("/coach").text)
    assert after["autopilot"] == "done" and after["ready"] == "done"

    conn = db.connect(settings.database_path)
    store.link_coach_chat(conn, "9001", code_fingerprint="x", now=clock.utcnow())
    conn.close()
    assert "Set up your agent" not in client.get("/coach").text, "a finished setup gets out of the way"


def test_the_athlete_page_answers_the_readiness_questions_and_shows_blockers(coach, monkeypatch):
    client, settings = coach
    page = add_athlete(client)
    athlete_url = urlparse(str(page.url)).path
    athlete_id = athlete_url.rsplit("/", 1)[1]

    soup = BeautifulSoup(page.text, "html.parser")
    header = soup.select_one("#agent-status")
    assert header.select_one(".status-badge").get_text(strip=True) == "Setup needed"
    assert header.select_one('[data-status="telegram"]').get_text(strip=True) == "Not connected"
    assert header.select_one('[data-status="training-plan"]').get_text(strip=True) == "Not created"
    assert header.select_one('[data-status="autopilot"]').get_text(strip=True) == "Not decided"
    assert header.select_one('[data-status="next-action"]').get_text(strip=True) == (
        "Nothing until setup is finished.")
    assert not soup.select(".btn-disabled"), "no disabled buttons standing in for next steps"

    conn = db.connect(settings.database_path)
    db.link_telegram_chat(conn, chat_id="7001", athlete_id=athlete_id)
    conn.close()
    client.post(f"{athlete_url}/plan", data={"weekday": "0", "lift": "squat", "sets": "4", "reps": "5", "rpe": "7"})
    client.post(f"{athlete_url}/autopilot", data={"enabled": "on"})
    soup = BeautifulSoup(client.get(athlete_url).text, "html.parser")
    header = soup.select_one("#agent-status")
    assert header.select_one(".status-badge").get_text(strip=True) == "Ready"
    assert header.select_one('[data-status="telegram"]').get_text(strip=True) == "Connected"
    assert header.select_one('[data-status="autopilot"]').get_text(strip=True) == "On"
    assert header.select_one('[data-status="next-action"]').get_text(strip=True) == "Check-in today at 07:30."
    assert header.select_one('[data-status="blocking"]') is None
    assert "Turn autopilot off" in soup.select_one("#autopilot").get_text()

    monkeypatch.setattr(deployment, "durable_storage_configured", lambda: False)
    header = BeautifulSoup(client.get(athlete_url).text, "html.parser").select_one("#agent-status")
    assert header.select_one(".status-badge").get_text(strip=True) == "Blocked"
    assert "DATABASE_URL" in header.get_text()


def test_the_simulated_test_is_safe_and_uses_the_athletes_own_plan(coach):
    client, settings = coach
    page = add_athlete(client)
    athlete_url = urlparse(str(page.url)).path
    assert "Add a training plan first" in client.get(f"{athlete_url}/simulate").text

    client.post(f"{athlete_url}/plan", data={"weekday": "0", "lift": "squat", "sets": "4", "reps": "5", "rpe": "7"})
    client.post(f"{athlete_url}/autopilot", data={"enabled": "on"})
    simulated = client.get(f"{athlete_url}/simulate").text
    assert "Safe simulated test. Nothing was sent and nothing was saved." in simulated
    assert "What the agent would do" in simulated
    assert "Squat 4×5 @ RPE 7" in simulated
    assert "sample reply from Priya" in simulated

    conn = db.connect(settings.database_path)
    try:
        for table in ("agent_cases", "agent_events", "whatsapp_messages"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    finally:
        conn.close()


def test_demo_athletes_are_marked_as_simulator_only(coach):
    client, _ = coach
    client.post("/coach/demo/seed")
    page = BeautifulSoup(client.get("/coach/athlete/+99900000006").text, "html.parser")
    assert page.select_one('[data-status="telegram"]').get_text(strip=True) == "Simulator (demo athlete)"
    assert page.select_one("#telegram") is None
