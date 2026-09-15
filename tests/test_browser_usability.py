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
    assert browser.text("#telegram h2") == "Priya is not connected yet"
    assert browser.eval("!document.querySelector('.invite-raw').open && "
                        "!document.querySelector('input.invite-link').checkVisibility()"), "raw link stays folded away"
    browser.send("Browser.grantPermissions", origin=base,
                 permissions=["clipboardReadWrite", "clipboardSanitizedWrite"])
    assert browser.text("button[data-copy]") == "Copy invite for Priya"
    browser.click("button[data-copy]")
    copied = browser.wait_for("window.__powerCopied")
    assert copied == browser.eval("document.querySelector('button[data-copy]').dataset.copy")
    athlete_id, _ = telegram.athlete_from_pairing_token(unquote(parse_qs(urlparse(copied).query)["start"][0]))
    assert db.is_generated_athlete_id(athlete_id)
    assert athlete_id not in browser.text(), "the internal ID is not visible on the page"

    assert browser.text('[data-status="telegram"]') == "Not connected"
    assert browser.text("#agent-status .status-badge") == "Setup needed"
    browser.click("button[data-check-connection]")
    browser.wait_for("document.querySelector('[data-telegram-status]').innerText.startsWith('Not connected yet')")

    conn = db.connect(settings.database_path)
    db.link_telegram_chat(conn, chat_id="7001", athlete_id=athlete_id)  # Priya presses Start
    conn.close()
    # The page notices by itself and reloads, so every section shows the connection.
    browser.wait_for("location.search.includes('connected=1') && document.readyState === 'complete' && "
                     "document.querySelector('[data-status=\"telegram\"]')?.innerText === 'Connected'", timeout=15)
    assert browser.eval("document.getElementById('telegram') === null")
    assert "Telegram connected." in browser.text(".msg.ok")

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

    assert browser.text("#agent-status .status-actions a") == "Choose autopilot"
    browser.eval("""[...document.querySelectorAll('#autopilot button')]
      .find(button => button.innerText === 'Turn autopilot on').click(); true""")
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


LAYOUT_CHECK = """(() => {
  const width = window.innerWidth;
  const box = (selector) => {
    const node = document.querySelector(selector);
    return node ? node.getBoundingClientRect() : {width: 0, left: 0, right: 0, top: 0};
  };
  const inside = (selector) => { const r = box(selector); return r.width > 0 && r.left >= -1 && r.right <= width + 1; };
  const top = (selector) => box(selector).top + window.scrollY;
  return {
    overflow: document.documentElement.scrollWidth - width,
    copyInside: inside('button[data-copy]'),
    checkInside: inside('button[data-check-connection]'),
    fieldsInside: ['#plan-weekday', '#plan-lift', '#plan-sets', '#plan-reps', '#plan-rpe'].every(inside),
    addInside: inside('#agent-plan form.plan-form button[type=submit]'),
    liftWidth: box('#plan-lift').width, setsWidth: box('#plan-sets').width,
    labelled: ['plan-weekday', 'plan-lift', 'plan-sets', 'plan-reps', 'plan-rpe']
      .every(id => document.querySelector('label[for="' + id + '"]')),
    order: ['#agent-status', '#telegram', '.athlete-tabs', '#agent-plan', '#autopilot'].map(top),
    visiblePanels: [...document.querySelectorAll('[data-panel]')].filter((panel) => !panel.hidden)
      .map((panel) => panel.dataset.panel),
    sticky: [...document.querySelectorAll('.athlete-top *, .athlete-lower *')]
      .filter(node => ['sticky', 'fixed'].includes(getComputedStyle(node).position)).length,
    stepperColumns: getComputedStyle(document.querySelector('.stepper')).gridTemplateColumns.split(' ').length,
  };
})()"""


def test_athlete_onboarding_page_works_on_a_laptop_and_a_phone(site):
    base, browser, _ = site
    registered = httpx.post(f"{base}/coach/athletes/register", data={
        "name": "Nikash Rao", "timezone": "Asia/Kolkata", "checkin_time": "07:30", "training_time": "18:00",
    })
    athlete_url = base + urlparse(registered.headers["location"]).path
    try:
        for width, height, mobile, columns in ((1280, 900, False, 4), (375, 812, True, 2)):
            browser.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                         deviceScaleFactor=1, mobile=mobile)
            browser.goto(athlete_url)
            layout = browser.eval(LAYOUT_CHECK)
            assert layout["overflow"] <= 1, (width, layout)
            assert layout["copyInside"] and layout["checkInside"], (width, layout)
            assert layout["fieldsInside"] and layout["addInside"] and layout["labelled"], (width, layout)
            assert layout["order"] == sorted(layout["order"]), (width, "status and setup come before the tabs")
            assert layout["visiblePanels"] == ["plan"], (width, "one tab at a time, Plan first")
            assert layout["sticky"] == 0, (width, "nothing sticks over the setup cards or conversation")
            assert layout["stepperColumns"] == columns, (width, layout)
            if not mobile:
                assert layout["liftWidth"] > 1.8 * layout["setsWidth"], layout
            assert browser.text("#telegram h2") == "Nikash is not connected yet"

            browser.click("#tab-evidence")
            browser.wait_for("!document.getElementById('panel-evidence').hidden")
            assert browser.eval("document.getElementById('panel-plan').hidden")
            assert browser.eval("document.getElementById('tab-evidence').getAttribute('aria-selected')") == "true"
            browser.goto(athlete_url + "#messages")  # a deep link opens the tab that holds it
            browser.wait_for("!document.getElementById('panel-messages').hidden")
    finally:
        browser.send("Emulation.clearDeviceMetricsOverride")


TODAY_CHECK = """(() => {
  const width = window.innerWidth;
  const rect = (node) => node.getBoundingClientRect();
  const counts = [...document.querySelectorAll('.ops-counts .count')].map(rect);
  const top = (selector) => rect(document.querySelector(selector)).top + window.scrollY;
  const left = (selector) => rect(document.querySelector(selector)).left;
  return {
    overflow: document.documentElement.scrollWidth - width,
    counts: counts.length,
    countsInside: counts.every((r) => r.left >= -1 && r.right <= width + 1),
    countsOneRow: new Set(counts.map((r) => Math.round(r.top))).size === 1,
    needsTop: top('#needs-you'), activityTop: top('#activity'), nextTop: top('#next'), squadTop: top('#squad'),
    needsLeft: left('#needs-you'), activityLeft: left('#activity'),
    controlsInside: [...document.querySelectorAll('.decision-controls .btn')]
      .every((node) => rect(node).right <= width + 1),
  };
})()"""


def test_today_puts_decisions_first_on_a_laptop_and_a_phone(site):
    base, browser, _ = site
    httpx.post(f"{base}/coach/demo/seed", data={"return_to": "/coach"})
    try:
        for width, height, mobile in ((1280, 900, False), (390, 844, True)):
            browser.send("Emulation.setDeviceMetricsOverride", width=width, height=height,
                         deviceScaleFactor=1, mobile=mobile)
            browser.goto(base + "/coach")
            layout = browser.eval(TODAY_CHECK)
            assert layout["overflow"] <= 1, (width, layout)
            assert layout["counts"] == 3 and layout["countsInside"] and layout["countsOneRow"], (width, layout)
            assert layout["controlsInside"], (width, layout)
            if mobile:
                assert layout["needsTop"] < layout["activityTop"] < layout["nextTop"] < layout["squadTop"], layout
            else:
                assert layout["activityLeft"] > layout["needsLeft"], "the agent's work sits beside the decisions"
            assert browser.eval("document.querySelectorAll('#needs-you .decision').length") > 0
            assert browser.eval("!document.getElementById('tools').open"), "simulation tools stay folded away"
    finally:
        browser.send("Emulation.clearDeviceMetricsOverride")
