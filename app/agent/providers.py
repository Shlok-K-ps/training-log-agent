"""Alternative model backends, behind the same `ModelClient` protocol.

Layer 1 is the only part of the system that touches a model, and it talks to the
rest of the code through one method. That makes the provider a swappable
detail — which is the point of putting the boundary there, and the reason a
change in Google's free tier is an afternoon rather than a rewrite.

Every provider here except Gemini speaks the OpenAI chat-completions dialect, so
one adapter covers all of them. The tool schema is *converted* from the single
definition in `schemas.py` rather than restated, so the two can never drift.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.agent.schemas import TOOL


# --- schema conversion --------------------------------------------------------


def _schema_to_json(schema: Any) -> dict[str, Any]:
    """google-genai `types.Schema` -> plain JSON Schema."""
    if schema is None:
        return {}
    type_name = getattr(schema.type, "value", schema.type)
    out: dict[str, Any] = {"type": str(type_name).lower()}
    if schema.description:
        out["description"] = schema.description
    if getattr(schema, "enum", None):
        out["enum"] = list(schema.enum)
    if getattr(schema, "properties", None):
        out["properties"] = {k: _schema_to_json(v) for k, v in schema.properties.items()}
    if getattr(schema, "required", None):
        out["required"] = list(schema.required)
    if getattr(schema, "items", None):
        out["items"] = _schema_to_json(schema.items)
    return out


def openai_tools() -> list[dict[str, Any]]:
    """Every Gemini declaration, converted to OpenAI function-calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": decl.name,
                "description": decl.description,
                "parameters": _schema_to_json(decl.parameters),
            },
        }
        for decl in TOOL.function_declarations
    ]


# --- providers ----------------------------------------------------------------


@dataclass(frozen=True)
class Provider:
    name: str
    env_var: str
    base_url: str
    model: str
    tool_choice: str = "required"
    note: str = ""


PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        "groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1",
        "llama-3.3-70b-versatile", note="fastest free tier, ~1000 req/day",
    ),
    "cerebras": Provider(
        "cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1",
        "llama-3.3-70b", note="very high tokens/sec",
    ),
    "mistral": Provider(
        "mistral", "MISTRAL_API_KEY", "https://api.mistral.ai/v1",
        "mistral-small-latest", tool_choice="any", note="generous token allowance",
    ),
    "openrouter": Provider(
        "openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1",
        "meta-llama/llama-3.3-70b-instruct:free", note="one key, many models; ~50 req/day",
    ),
    "github": Provider(
        "github", "GITHUB_MODELS_TOKEN", "https://models.github.ai/inference",
        "openai/gpt-4o-mini", note="free with a GitHub account",
    ),
    "openai": Provider(
        "openai", "OPENAI_API_KEY", "https://api.openai.com/v1",
        "gpt-4o-mini", note="paid, included as a reference point",
    ),
}


class OpenAICompatClient:
    """One adapter for every provider that speaks OpenAI chat-completions."""

    def __init__(
        self,
        provider: Provider,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 45.0,
    ) -> None:
        self.provider = provider
        self.model = model or provider.model
        self._key = api_key or os.getenv(provider.env_var, "")
        if not self._key:
            raise RuntimeError(f"{provider.env_var} is not set")
        self._timeout = timeout

    def call(self, text: str, system_instruction: str) -> list[tuple[str, dict[str, Any]]]:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": text},
            ],
            "tools": openai_tools(),
            "tool_choice": self.provider.tool_choice,
        }
        response = httpx.post(
            f"{self.provider.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()
        body = response.json()

        calls: list[tuple[str, dict[str, Any]]] = []
        for choice in body.get("choices", []):
            for call in (choice.get("message") or {}).get("tool_calls") or []:
                function = call.get("function") or {}
                raw_args = function.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except json.JSONDecodeError:
                    args = {"__unparseable__": raw_args}
                calls.append((function.get("name", ""), args))
        return calls


def available() -> list[Provider]:
    """Providers whose key is present in the environment."""
    return [p for p in PROVIDERS.values() if os.getenv(p.env_var)]
