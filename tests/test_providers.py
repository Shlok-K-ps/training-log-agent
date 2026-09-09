"""The provider seam: one tool definition, many dialects, and a scored harness.

The point of these tests is that swapping model providers cannot silently change
what the model is allowed to say. The OpenAI-format tools are *derived* from the
same declarations Gemini gets, so the two can never drift apart.
"""

from __future__ import annotations

import pytest

from app.agent.offline import OfflineClient
from app.agent.providers import PROVIDERS, _schema_to_json, openai_tools
from app.agent.schemas import LOG_SET, TOOL_NAMES


def test_every_tool_is_offered_in_both_dialects():
    names = [t["function"]["name"] for t in openai_tools()]
    assert names == list(TOOL_NAMES)


def test_every_openai_tool_is_a_well_formed_function_definition():
    for tool in openai_tools():
        assert tool["type"] == "function"
        function = tool["function"]
        assert function["name"] and function["description"]
        assert function["parameters"]["type"] == "object"


def test_the_converted_schema_keeps_types_enums_and_required_fields():
    params = _schema_to_json(LOG_SET.parameters)
    assert params["required"] == ["lift"]
    assert params["properties"]["sets"]["type"] == "integer"
    assert params["properties"]["weight"]["type"] == "number"
    assert params["properties"]["unit"]["enum"] == ["kg", "lb"]
    assert params["properties"]["phase"]["enum"] == ["cut", "maintain", "bulk"]


def test_descriptions_survive_conversion():
    """The descriptions are the prompt. Losing them silently degrades parsing."""
    params = _schema_to_json(LOG_SET.parameters)
    assert "RPE" in params["properties"]["rpe"]["description"]
    assert "never estimate" in LOG_SET.description or "never invent" in LOG_SET.description


@pytest.mark.parametrize("name", list(PROVIDERS))
def test_every_provider_declares_a_key_and_an_endpoint(name):
    provider = PROVIDERS[name]
    assert provider.env_var.endswith(("_KEY", "_TOKEN"))
    assert provider.base_url.startswith("https://")
    assert provider.model
    assert provider.tool_choice in {"required", "any", "auto"}


def test_a_missing_key_fails_loudly_rather_than_silently(monkeypatch):
    from app.agent.providers import OpenAICompatClient

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        OpenAICompatClient(PROVIDERS["groq"])


# --- the benchmark's own scoring ---------------------------------------------


def test_the_benchmark_scores_the_regex_stub_as_partially_failing():
    """A guard on the harness itself: if the stub ever scores full marks, the
    checks have gone soft and the benchmark is measuring nothing."""
    from scripts.bench_providers import CASES, run

    passed, _ = run("stub", OfflineClient(), verbose=False)
    assert 0 < passed < len(CASES)


def test_the_benchmark_covers_the_cases_that_matter():
    from scripts.bench_providers import CASES

    texts = " ".join(c.text for c in CASES).lower()
    assert "one forty" in texts       # spelled-out weight
    assert "225lb" in texts           # unit conversion
    assert "yesterday" in texts       # relative date
    assert "tweaked" in texts         # injury in passing
    assert "did some squats" in texts  # must ask, not invent
