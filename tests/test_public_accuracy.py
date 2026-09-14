"""Public-facing technical claims stay accurate and consistent.

Fails if inactive WhatsApp providers are advertised as active, if production
storage is described as SQLite, if the old inaccurate transparency note returns,
or if the landing page, demo, README, setup files and /health drift apart.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app import public_demo
from app.coach.demo_view import render_public_demo
from app.coach.landing_view import render_landing
from app.coach.view import render_privacy, render_terms

ROOT = Path(__file__).resolve().parents[1]
INACTIVE_PROVIDERS = ("Twilio", "Vonage")
OLD_NOTE_PHRASES = (
    "venture-backed", "runtime framework beyond", "Transparent Note", "Pure Python &amp; SQLite",
    "no runtime framework",
)
LOCAL_ONLY = re.compile(r"local|test|demo|development|in-memory|temporary", re.I)
HISTORICAL = re.compile(r"historical|never used|not used|not part of the deployed", re.I)


@pytest.fixture(scope="module")
def pages() -> dict[str, str]:
    public_demo.public_demo.cache_clear()
    return {
        "landing": render_landing(),
        "demo": render_public_demo(public_demo.public_demo()),
        "privacy": render_privacy(),
        "terms": render_terms(),
    }


def readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def visible(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style"):
        node.decompose()
    # Inline tags such as <strong>SQLite</strong> must stay inside their sentence.
    return re.sub(r"\s+", " ", soup.get_text(" "))


def paragraphs(markdown: str) -> list[str]:
    return [block for block in re.split(r"\n\s*\n", markdown) if block.strip()]


def sections(config: str) -> list[str]:
    """Split a commented config file into blocks at its '# ---' section headers."""
    blocks, current = [], []
    for line in config.splitlines():
        if line.strip().startswith("# ---") and current:
            blocks.append("\n".join(current))
            current = []
        current.append(line)
    blocks.append("\n".join(current))
    return blocks


def test_inactive_whatsapp_providers_are_not_advertised(pages):
    for name, html in pages.items():
        for provider in INACTIVE_PROVIDERS:
            assert provider not in html, f"{provider} appears on the public {name} page"
    assert "Telegram" in pages["landing"]

    for block in paragraphs(readme()):
        if any(provider in block for provider in INACTIVE_PROVIDERS):
            assert HISTORICAL.search(block), f"README presents an inactive provider as usable:\n{block}"

    for filename in ("render.yaml", ".env.example"):
        for block in sections((ROOT / filename).read_text(encoding="utf-8")):
            if re.search("twilio|vonage", block, re.I):
                header = block.strip().splitlines()[0]
                assert "Historical" in header, f"{filename} offers an inactive provider:\n{header}"


def test_production_storage_is_never_described_as_sqlite(pages):
    for name, html in pages.items():
        for sentence in re.split(r"(?<=[.!?])\s+", visible(html)):
            if "SQLite" in sentence:
                assert LOCAL_ONLY.search(sentence), f"{name}: {sentence!r}"
    for block in paragraphs(readme()):
        if "SQLite" in block:
            assert LOCAL_ONLY.search(block), f"README storage claim:\n{block}"
    assert "SQLite Timeline" not in pages["landing"]
    assert "Neon Postgres" in readme()
    assert "mounted volume in production" not in (ROOT / "Dockerfile").read_text(encoding="utf-8")


def test_the_old_transparency_note_is_gone_and_the_public_boundary_is_clear(pages):
    for phrase in OLD_NOTE_PHRASES:
        assert phrase not in pages["landing"], phrase
        assert phrase not in readme(), phrase
    for component in ("Telegram", "FastAPI", "Neon Postgres", "Gemini", "tested Python rules"):
        assert component in readme()
    assert "The public demo is fictional. The real coach console is private." in pages["landing"]


def test_the_landing_is_plain_and_the_repository_keeps_the_technical_detail(pages):
    landing, text = pages["landing"], readme()
    for component in ("Telegram", "Gemini 2.5 Flash", "Neon Postgres", "SQLite", "FastAPI", "Uvicorn",
                      "Render", "GitHub Actions"):
        assert component in text, f"README is missing {component}"
    assert "Telegram" in landing
    for implementation_detail in ("Neon Postgres", "SQLite", "FastAPI", "Uvicorn", "GitHub Actions"):
        assert implementation_detail not in landing, f"landing should leave {implementation_detail} to GitHub"
    for ambiguous in ("Pure Python Rules", "Active &middot; Deterministic", "Gemini Flash<"):
        assert ambiguous not in landing
    for explanation in (
        "Checks in first", "Handles the routine", "Escalates the exception",
        "The language model reads the message. Tested rules decide",
    ):
        assert explanation in landing
    assert "It does not independently" in text and "clear injuries, invent training loads or change safety policies" in text
    for part in ("RECEIVE", "REASON", "ACT", "REMEMBER"):
        assert part in landing
    for part in ("**Perceive**", "**Reason**", "**Act**", "**Remember and adapt**"):
        assert part in text


def test_the_demo_duration_is_stated_consistently(pages):
    stale = ("60 seconds", "60-second", "one minute", "about a minute", "in a minute")
    for name, content in (("landing", pages["landing"]), ("demo", pages["demo"]), ("README", readme())):
        for phrase in stale:
            assert phrase not in content, f"{name} still says {phrase!r}"
    assert "90-second" in pages["landing"] and "See it in 90 seconds" in readme()
    assert "about 90 seconds" in pages["demo"]
    # The slower pacing from commit 55dd36b.
    assert "const scale = 90000 / total;" in pages["demo"]
    assert "coach: 3600" in pages["demo"] and "interpret: 2200" in pages["demo"]


def test_health_and_api_description_name_telegram_and_no_inactive_provider(tmp_path, monkeypatch):
    from app import main
    from app.config import settings

    for name, value in {
        "database_path": str(tmp_path / "accuracy.db"), "public_base_url": "https://agent.example.com",
        "telegram_bot_token": "123456:test-token", "telegram_bot_username": "PowerCoachTestBot",
        "telegram_webhook_secret": "webhook_secret-123", "telegram_link_secret": "pairing-secret",
        "vonage_api_key": "", "vonage_api_secret": "", "vonage_sandbox_number": "",
        "vonage_webhook_secret": "", "twilio_account_sid": "", "twilio_auth_token": "",
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(main.telegram, "configure_webhook", lambda: None)
    with TestClient(main.app) as client:
        health = client.get("/health").json()
        api = client.get("/openapi.json").json()["info"]
    assert health["messaging_channel"] == "telegram"
    assert health["legacy_whatsapp_adapter"] == "inactive"
    assert "whatsapp_transport" not in health and "signature_validation" not in health
    serialized = json.dumps(health)
    for provider in INACTIVE_PROVIDERS:
        assert provider not in serialized
        assert provider not in api["description"]
    assert "WhatsApp" not in api["description"] and "Telegram" in api["description"]


def test_the_readme_lift_figures_match_the_reference_data(pages):
    from app.reference import OBSERVED_MAX_KG

    technical_readme = readme()
    for lift, label in (("squat", "squat"), ("bench press", "bench"), ("deadlift", "deadlift")):
        assert f"{OBSERVED_MAX_KG[lift]:.1f} kg" in technical_readme, f"README {label} figure is stale"
    assert "Max Plausible" not in pages["landing"]
