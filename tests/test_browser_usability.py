"""Browser-level usability: a real headless Chrome drives the running service.

It clicks through the landing page and demo as a visitor, and through setup as a
new coach, using the Chrome DevTools Protocol directly (no extra packages). It is
skipped only when no Chrome or Edge is installed.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest

from app import deployment
from app.casework import clock
from app.channels import telegram
from app.storage import db

CANDIDATES = (
    os.environ.get("CHROME_PATH", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    shutil.which("google-chrome") or "", shutil.which("chromium") or "", shutil.which("chrome") or "",
)
CHROME = next((path for path in CANDIDATES if path and Path(path).exists()), None)

try:
    from websockets.sync.client import connect as ws_connect
except ImportError:  # pragma: no cover
    ws_connect = None

pytestmark = pytest.mark.skipif(CHROME is None or ws_connect is None, reason="needs Chrome or Edge")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Browser:
    def __init__(self, profile: Path):
        port = free_port()
        self.process = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
             "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--remote-allow-origins=*",
             "--window-size=1280,900", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 30
        while True:
            try:
                targets = httpx.get(f"http://127.0.0.1:{port}/json/list", timeout=2).json()
                page = next(t for t in targets if t.get("type") == "page")
                break
            except Exception:  # noqa: BLE001 - Chrome is still starting
                if time.time() > deadline:
                    raise
                time.sleep(0.2)
        self.ws = ws_connect(page["webSocketDebuggerUrl"], max_size=None, open_timeout=20)
        self.counter = 0
        self.send("Page.enable")
        self.send("Runtime.enable")

    def send(self, method: str, **params):
        self.counter += 1
        ident = self.counter
        self.ws.send(json.dumps({"id": ident, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv(timeout=30))
            if message.get("id") == ident:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def eval(self, expression: str):
        result = self.send("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("text", "script error") + ": " + expression[:80])
        return result["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 20):
        deadline = time.time() + timeout
        last_error = None
        while time.time() < deadline:
            try:
                value = self.eval(expression)
                if value:
                    return value
            except RuntimeError as exc:  # navigation in progress
                last_error = exc
            time.sleep(0.15)
        raise AssertionError(f"timed out waiting for {expression!r} ({last_error})")

    def goto(self, url: str):
        self.send("Page.navigate", url=url)
        self.loaded()

    def loaded(self, path_prefix: str = ""):
        self.wait_for(
            f"document.readyState === 'complete' && location.pathname.startsWith({json.dumps(path_prefix)})"
        )

    def text(self, selector: str = "body") -> str:
        return self.eval(f"(document.querySelector({json.dumps(selector)}) || {{innerText: ''}}).innerText")

    def click(self, selector: str):
        self.wait_for(f"!!document.querySelector({json.dumps(selector)})")
        self.eval(f"document.querySelector({json.dumps(selector)}).click(); true")

    def close(self):
        try:
            self.ws.close()
        finally:
            self.process.terminate()
            self.process.wait(timeout=10)


@pytest.fixture()
def site(tmp_path, monkeypatch):
    import uvicorn

    from app import main
    from app.config import settings

    port = free_port()
    base = f"http://127.0.0.1:{port}"
    for name, value in {
        "database_path": str(tmp_path / "browser.db"),
        "database_url": "",
        "public_base_url": base,
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
    monkeypatch.setattr(clock, "utcnow", lambda: datetime(2026, 9, 14, 0, 30, tzinfo=timezone.utc))
    server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started:
        assert time.time() < deadline, "server did not start"
        time.sleep(0.05)
    browser = Browser(tmp_path / "chrome-profile")
    try:
        yield base, browser, settings
    finally:
        browser.close()
        server.should_exit = True
        thread.join(timeout=10)


def test_a_new_visitor_watches_the_agent_work(site):
    base, browser, _ = site
    browser.goto(base + "/")
    assert browser.eval("document.querySelector('[data-primary-cta]').innerText").startswith("Watch the agent work")
    browser.click("[data-primary-cta]")
    browser.loaded("/demo")
    assert "nothing is sent" in browser.text(".sim-pill")

    browser.eval("window.powerDemo.setSpeed(40); true")
    browser.wait_for("document.body.dataset.demoState === 'finished'", timeout=40)
    assert browser.eval("!document.getElementById('demo-report').hidden")
    report = browser.text("#demo-report")
    assert "training days owned from check-in to outcome" in report
    assert "messages typed by the coach" in report
    assert browser.eval("document.querySelectorAll('#demo-timeline .step-item').length") > 25
    assert "paused all training guidance" in browser.text("#chat-arjun")
    assert browser.eval("document.getElementById('case-arjun').dataset.state") == "closed"
    assert browser.eval("document.querySelectorAll('.step-options .chosen').length") == 1, "the coach's choice is shown"
    for kind in ("k-interpret", "k-rule", "k-action", "k-coach"):
        assert browser.eval(f"document.querySelectorAll('#demo-timeline .step-item.{kind}').length") > 0

    browser.click("#demo-replay")
    browser.wait_for("document.getElementById('demo-report').hidden && window.powerDemo.index < 10")
    browser.eval("window.powerDemo.skip(); true")
    browser.wait_for("document.body.dataset.demoState === 'finished'")


def test_a_new_coach_follows_setup_to_a_ready_agent(site, monkeypatch):
    base, browser, settings = site
    browser.goto(base + "/coach")
    assert ("This is your private real-agent console. Start by inviting an athlete, "
            "or watch the fictional demo first.") in browser.text()
    assert browser.eval("document.querySelectorAll('#empty-console .empty-actions a').length") == 2

    browser.click("#empty-console .empty-actions a[href='/coach/athletes/new']")
    browser.loaded("/coach/athletes/new")
    assert browser.eval("document.querySelector('[name=athlete_id]') === null")
    browser.eval("""
      document.querySelector('[name=name]').value = 'Priya Nair';
      document.querySelector('[name=timezone]').value = 'Asia/Kolkata';
      document.querySelector('[name=checkin_time]').value = '07:30';
      document.querySelector('[name=training_time]').value = '18:00';
      document.querySelector('.new-athlete button[type=submit]').click(); true""")
    browser.loaded("/coach/athlete/athlete-")

    assert "Priya Nair added" in browser.text()
    browser.send("Browser.grantPermissions", origin=base,
                 permissions=["clipboardReadWrite", "clipboardSanitizedWrite"])
    browser.click("button[data-copy]")
    copied = browser.wait_for("window.__powerCopied")
    assert copied == browser.eval("document.querySelector('button[data-copy]').dataset.copy")
    athlete_id, _ = telegram.athlete_from_pairing_token(unquote(parse_qs(urlparse(copied).query)["start"][0]))
    assert db.is_generated_athlete_id(athlete_id)
    assert athlete_id not in browser.text(), "the internal ID is not visible on the page"

    assert browser.text('[data-status="telegram"]') == "Not connected"
    assert browser.text("#agent-status .status-badge") == "Blocked"

    conn = db.connect(settings.database_path)
    db.link_telegram_chat(conn, chat_id="7001", athlete_id=athlete_id)  # Priya presses Start
    conn.close()
    browser.wait_for("document.querySelector('[data-telegram-status]').innerText.includes('Connected')", timeout=15)
    assert browser.eval("!document.querySelector('[data-next-step]').hidden")

    browser.goto(base + "/coach")
    assert browser.eval("!!document.querySelector('[data-step-state=\"paired:done\"]')")
    browser.click("a[data-step=plan]")
    browser.loaded("/coach/athlete/")
    browser.eval("""
      const form = document.querySelector('#agent-plan form.plan-form');
      form.querySelector('[name=lift]').value = 'squat';
      form.querySelector('[type=submit]').click(); true""")
    browser.wait_for("!!document.querySelector('.msg.ok')")
    assert browser.text('[data-status="training-plan"]').startswith("Mon")

    browser.eval("""[...document.querySelectorAll('#agent-status button')]
      .find(button => button.innerText === 'Enable autopilot').click(); true""")
    browser.wait_for("document.querySelector('[data-status=\"autopilot\"]')?.innerText === 'On'")
    assert browser.text("#agent-status .status-badge") == "Ready"
    assert browser.text('[data-status="next-action"]') == "Check-in today at 07:30."

    browser.goto(base + "/coach")
    assert browser.eval("!!document.querySelector('[data-step-state=\"ready:done\"]')")
    assert browser.eval("document.querySelector('a[data-step=coach]').getAttribute('href')") == "/coach/setup#coach-telegram"

    # A public deployment without durable storage shows the block plainly.
    monkeypatch.setattr(settings, "public_base_url", "https://agent.example.com")
    browser.goto(base + f"/coach/athlete/{athlete_id}")
    assert browser.text("#agent-status .status-badge") == "Blocked"
    assert "DATABASE_URL" in browser.text("#agent-status")
    assert deployment.agent_blocker() is not None
