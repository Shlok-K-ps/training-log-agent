"""Capture the README screenshots from a private, fictional local instance.

Starts the service on a temporary database with no real credentials, drives it
with headless Chrome or Edge, and writes PNGs to docs/screenshots/. Nothing is
sent anywhere.

    python scripts/capture_screenshots.py
"""

from __future__ import annotations

import base64
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "screenshots"


def main() -> int:
    import uvicorn

    from app import main as service
    from app.config import settings
    from tests.test_browser_usability import CHROME, Browser, free_port

    if CHROME is None:
        print("Chrome or Edge is required.", file=sys.stderr)
        return 1
    workdir = Path(tempfile.mkdtemp(prefix="power-ai-shots-"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    for name, value in {
        "database_path": str(workdir / "screenshots.db"), "database_url": "", "public_base_url": base,
        "coach_link_secret": "", "telegram_bot_token": "123456:placeholder", "telegram_bot_username": "PowerAICoachBot",
        "telegram_webhook_secret": "placeholder", "telegram_link_secret": "placeholder", "coach_name": "Coach Rao",
        "gemini_api_key": "", "agent_background_ticks": False, "enable_morning_scheduler": False,
    }.items():
        setattr(settings, name, value)

    def refuse(*_args, **_kwargs):
        raise RuntimeError("screenshots never send messages")

    service.telegram.configure_webhook = lambda: None
    service.telegram.send_outbound = refuse

    server = uvicorn.Server(uvicorn.Config(service.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    OUT.mkdir(parents=True, exist_ok=True)
    browser = Browser(workdir / "profile")

    def shot(name: str) -> None:
        time.sleep(0.6)
        data = browser.send("Page.captureScreenshot", format="png")["data"]
        (OUT / f"{name}.png").write_bytes(base64.b64decode(data))
        print("saved", OUT / f"{name}.png")

    try:
        browser.goto(base + "/")
        shot("01-landing")

        browser.goto(base + "/demo?autoplay=0")
        browser.eval("window.powerDemo.setSpeed(8); window.powerDemo.play(); true")
        browser.wait_for("window.powerDemo.index >= 27", timeout=60)
        browser.eval("window.powerDemo.pause(); document.querySelector('.demo-grid').scrollIntoView(); true")
        shot("02-demo-in-progress")
        browser.eval("window.powerDemo.skip(); true")
        browser.wait_for("document.body.dataset.demoState === 'finished'")
        shot("03-demo-report")

        browser.goto(base + "/coach")
        shot("04-empty-console")
        browser.goto(base + "/coach/athletes/new")
        shot("05-add-athlete")
        browser.eval("""
          document.querySelector('[name=name]').value = 'Priya Nair';
          document.querySelector('[name=timezone]').value = 'Asia/Kolkata';
          document.querySelector('.new-athlete button[type=submit]').click(); true""")
        browser.loaded("/coach/athlete/athlete-")
        browser.eval("window.scrollTo(0, 0); true")
        shot("06-athlete-status-and-invite")
        browser.goto(base + "/coach")
        shot("07-setup-checklist")
    finally:
        browser.close()
        server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
