"""Layer 1 — the model call itself.

One responsibility: messy English in, validated structured actions out. The model
is configured with `temperature=0` and `mode="ANY"`, which forces it to answer
with a tool call rather than prose. Anything it returns that fails
`schemas.validate_call` is dropped before it can reach storage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol, Sequence

from google import genai
from google.genai import types

from app.agent.schemas import TOOL, Action, ValidationError, validate_call
from app.config import settings

log = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """\
You are the parsing layer of a powerlifting training-log system. You do not
coach, you do not encourage, and you never state whether an athlete is
progressing — a separate deterministic engine decides that from the database.

Your only job is to turn the athlete's message into tool calls.

Rules:
- Always respond with one or more tool calls. Never reply in prose.
- Call log_set once per distinct lift in the message. "Squat 3x5 at 140, bench
  3x8 at 80" is two calls.
- Only record what was said. If a weight, rep count or RPE is missing, omit that
  field — never estimate it. "Felt heavy" is not an RPE.
- Pain, tweaks, niggles or injuries go to log_status with injured=true, even when
  mentioned in passing alongside a set. Log the set as well.
- Questions like "am I stalling on squat?" and "how's my bench going?" are
  query_progress. Explicit workout requests like "what should I squat today?"
  are ask_prescription. Do not answer either yourself.
- Sleep, readiness, soreness, stress, bodyweight, calories, protein and stated
  nutrition adherence go to log_checkin. Record only explicit numbers; never
  translate "slept badly" or "feel great" into a score.
- Explicit programming facts such as novice/intermediate/advanced, training
  days per week, a meet date, specialty equipment, or a named method go to
  configure_program. Never infer experience from a lift number.
- If the message is not parseable without guessing, call clarify with one short
  question.

Today's date is {today}. Resolve "today", "yesterday", "Monday" against it.
{known_lifts}"""


@dataclass
class ParseResult:
    """What came back from one model call."""

    actions: list[Action] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    raw_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.actions)


class ModelClient(Protocol):
    """The seam the tests mock — no network in the test suite."""

    def call(self, text: str, system_instruction: str) -> list[tuple[str, dict[str, Any]]]:
        ...


class GeminiClient:
    """Thin wrapper over google-genai, kept boring on purpose."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key or settings.require_gemini())
        self._model = model or settings.gemini_model

    def call(self, text: str, system_instruction: str) -> list[tuple[str, dict[str, Any]]]:
        response = self._client.models.generate_content(
            model=self._model,
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                tools=[TOOL],
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(mode="ANY")
                ),
                temperature=0.0,
            ),
        )
        return _extract_calls(response)


def _extract_calls(response: Any) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    for call in getattr(response, "function_calls", None) or []:
        calls.append((call.name, dict(call.args or {})))
    if calls:
        return calls
    # Older/edge responses: walk the parts.
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            fc = getattr(part, "function_call", None)
            if fc is not None:
                calls.append((fc.name, dict(fc.args or {})))
    return calls


def build_system_instruction(today: date, known_lifts: Sequence[str] = ()) -> str:
    hint = ""
    if known_lifts:
        hint = (
            "\nLifts this athlete has logged before, for name matching: "
            + ", ".join(known_lifts)
            + "."
        )
    return SYSTEM_INSTRUCTION.format(today=today.isoformat(), known_lifts=hint)


def parse_message(
    text: str,
    client: ModelClient,
    *,
    today: date | None = None,
    known_lifts: Sequence[str] = (),
) -> ParseResult:
    """Run one message through the model and validate everything it returns."""
    today = today or date.today()
    instruction = build_system_instruction(today, known_lifts)
    result = ParseResult()

    try:
        raw_calls = client.call(text, instruction)
    except Exception as exc:  # noqa: BLE001 - surfaced to the athlete, not swallowed
        log.exception("model call failed")
        result.rejected.append(f"model call failed: {exc}")
        return result

    result.raw_calls = raw_calls
    for name, args in raw_calls:
        try:
            result.actions.append(validate_call(name, args, today))
        except ValidationError as exc:
            log.warning("rejected tool call %s(%s): %s", name, args, exc)
            result.rejected.append(str(exc))
    return result
