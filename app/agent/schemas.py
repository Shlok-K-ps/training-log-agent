"""Layer 1 — the schema the model must answer in, and the validation behind it.

A tool call is the model returning *arguments matching a schema you defined*
instead of a paragraph. `{"lift": "bench press", "sets": 3, "reps": 5,
"weight": 100, "unit": "kg", "rpe": 8}` can be range-checked, type-checked and
rejected before it reaches the database. A sentence cannot.

Everything the model is allowed to say is in this file. If it tries to say
anything else, `validate_call` throws it away.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from google.genai import types

from app.storage.lifts import normalize_lift

# --- Bounds. A model that hallucinates a 900 kg bench gets stopped here. -------

MIN_WEIGHT_KG = 0.0
MAX_WEIGHT_KG = 600.0
MAX_SETS = 30
MAX_REPS = 100
MIN_RPE = 1.0
MAX_RPE = 10.0
MAX_PAST_DAYS = 400
MAX_FUTURE_DAYS = 1
LB_TO_KG = 0.45359237

PHASES = ("cut", "maintain", "bulk")


class ValidationError(ValueError):
    """The model returned something outside the schema. Nothing gets stored."""


# --- Actions: the validated, in-Python result of a tool call ------------------


@dataclass(frozen=True)
class LogSet:
    lift: str
    sets: int | None
    reps: int | None
    weight_kg: float | None
    rpe: float | None
    session_date: str
    phase: str | None = None


@dataclass(frozen=True)
class LogStatus:
    phase: str | None = None
    injured: bool | None = None
    injury_note: str | None = None
    athlete_name: str | None = None


@dataclass(frozen=True)
class QueryProgress:
    lift: str | None = None


@dataclass(frozen=True)
class Clarify:
    question: str


Action = LogSet | LogStatus | QueryProgress | Clarify


# --- Declarations handed to Gemini --------------------------------------------

LOG_SET = types.FunctionDeclaration(
    name="log_set",
    description=(
        "Record one lift the athlete performed in one training session. Call this "
        "once per distinct lift mentioned. If the athlete lists several lifts in one "
        "message, call it several times. Only use values the athlete actually stated "
        "or clearly implied; never invent a weight, an RPE or a rep count."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "lift": types.Schema(
                type=types.Type.STRING,
                description=(
                    "The exercise, as the athlete named it, e.g. 'squat', 'bench press', "
                    "'deadlift', 'OHP'. Do not expand abbreviations you are unsure of."
                ),
            ),
            "sets": types.Schema(
                type=types.Type.INTEGER,
                description="Number of working sets, e.g. 3 in '3x5'.",
            ),
            "reps": types.Schema(
                type=types.Type.INTEGER,
                description="Reps per set, e.g. 5 in '3x5'.",
            ),
            "weight": types.Schema(
                type=types.Type.NUMBER,
                description="Load on the bar, in the unit given by `unit`.",
            ),
            "unit": types.Schema(
                type=types.Type.STRING,
                enum=["kg", "lb"],
                description=(
                    "Unit of `weight`. Use 'lb' only when the athlete says pounds or lbs. "
                    "Default is 'kg'."
                ),
            ),
            "rpe": types.Schema(
                type=types.Type.NUMBER,
                description=(
                    "Rate of Perceived Exertion, 1-10, if stated. Omit if the athlete "
                    "did not give one. 'felt easy'/'felt hard' is NOT an RPE — omit it."
                ),
            ),
            "session_date": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Date of the session as YYYY-MM-DD. Resolve relative words like "
                    "'today', 'yesterday', 'last Monday' against the current date given "
                    "in the system instruction. Default to today when unstated."
                ),
            ),
            "phase": types.Schema(
                type=types.Type.STRING,
                enum=list(PHASES),
                description=(
                    "Only include if the athlete states their nutrition phase in this "
                    "same message. Otherwise omit — the stored phase carries forward."
                ),
            ),
        },
        required=["lift"],
    ),
)

LOG_STATUS = types.FunctionDeclaration(
    name="log_status",
    description=(
        "Record something about the athlete rather than a set: a change of "
        "nutrition phase, an injury being reported or cleared, or their name."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "phase": types.Schema(
                type=types.Type.STRING,
                enum=list(PHASES),
                description="Nutrition phase the athlete says they are in.",
            ),
            "injured": types.Schema(
                type=types.Type.BOOLEAN,
                description=(
                    "true when the athlete reports pain or an injury, false when they "
                    "say they are recovered or cleared. Report it; do not judge how bad "
                    "it is."
                ),
            ),
            "injury_note": types.Schema(
                type=types.Type.STRING,
                description="Short quote of what they said hurts, e.g. 'left knee, squatting'.",
            ),
            "athlete_name": types.Schema(
                type=types.Type.STRING,
                description="The athlete's name, if they introduce themselves.",
            ),
        },
    ),
)

QUERY_PROGRESS = types.FunctionDeclaration(
    name="query_progress",
    description=(
        "The athlete is asking how a lift is going, whether they are stalled, or "
        "what to do next. Call this instead of answering — the verdict is computed "
        "outside the model."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "lift": types.Schema(
                type=types.Type.STRING,
                description="Lift they are asking about. Omit to cover every lift they log.",
            ),
        },
    ),
)

CLARIFY = types.FunctionDeclaration(
    name="clarify",
    description=(
        "The message cannot be turned into a set, a status or a question without "
        "guessing. Ask one short question for the single most important missing "
        "detail. Never guess a weight."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "question": types.Schema(
                type=types.Type.STRING,
                description="One short question, under 20 words.",
            ),
        },
        required=["question"],
    ),
)

TOOL = types.Tool(
    function_declarations=[LOG_SET, LOG_STATUS, QUERY_PROGRESS, CLARIFY]
)

TOOL_NAMES = ("log_set", "log_status", "query_progress", "clarify")


# --- Validation ---------------------------------------------------------------


def _num(value: Any, field: str) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} is not a number: {value!r}") from None


def _int(value: Any, field: str, maximum: int) -> int | None:
    number = _num(value, field)
    if number is None:
        return None
    if number != int(number):
        raise ValidationError(f"{field} must be a whole number, got {number}")
    result = int(number)
    if result <= 0 or result > maximum:
        raise ValidationError(f"{field} out of range (1-{maximum}): {result}")
    return result


def _resolve_date(value: Any, today: date) -> str:
    if not value:
        return today.isoformat()
    try:
        parsed = date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError(f"session_date is not YYYY-MM-DD: {value!r}") from None
    if parsed > today + timedelta(days=MAX_FUTURE_DAYS):
        raise ValidationError(f"session_date is in the future: {parsed}")
    if parsed < today - timedelta(days=MAX_PAST_DAYS):
        raise ValidationError(f"session_date is implausibly old: {parsed}")
    return parsed.isoformat()


def _to_kg(weight: float | None, unit: Any) -> float | None:
    if weight is None:
        return None
    unit_str = str(unit or "kg").strip().lower()
    if unit_str in {"lb", "lbs", "pound", "pounds"}:
        weight = weight * LB_TO_KG
    elif unit_str not in {"kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"}:
        raise ValidationError(f"unknown weight unit: {unit!r}")
    weight = round(weight, 2)
    if not (MIN_WEIGHT_KG < weight <= MAX_WEIGHT_KG):
        raise ValidationError(f"weight out of range (0-{MAX_WEIGHT_KG} kg): {weight}")
    return weight


def _phase(value: Any) -> str | None:
    if value is None:
        return None
    phase = str(value).strip().lower()
    if phase not in PHASES:
        raise ValidationError(f"phase must be one of {PHASES}: {value!r}")
    return phase


def validate_call(name: str, args: dict[str, Any], today: date) -> Action:
    """Turn one raw tool call into a validated Action, or raise ValidationError."""
    args = args or {}

    if name == "log_set":
        lift = normalize_lift(args.get("lift"))
        if not lift:
            raise ValidationError("log_set requires a lift name")
        rpe = _num(args.get("rpe"), "rpe")
        if rpe is not None and not (MIN_RPE <= rpe <= MAX_RPE):
            raise ValidationError(f"rpe out of range ({MIN_RPE}-{MAX_RPE}): {rpe}")
        return LogSet(
            lift=lift,
            sets=_int(args.get("sets"), "sets", MAX_SETS),
            reps=_int(args.get("reps"), "reps", MAX_REPS),
            weight_kg=_to_kg(_num(args.get("weight"), "weight"), args.get("unit")),
            rpe=rpe,
            session_date=_resolve_date(args.get("session_date"), today),
            phase=_phase(args.get("phase")),
        )

    if name == "log_status":
        injured = args.get("injured")
        if injured is not None and not isinstance(injured, bool):
            injured = str(injured).strip().lower() in {"true", "1", "yes"}
        note = args.get("injury_note")
        athlete = args.get("athlete_name")
        status = LogStatus(
            phase=_phase(args.get("phase")),
            injured=injured,
            injury_note=str(note).strip()[:200] if note else None,
            athlete_name=str(athlete).strip()[:60] if athlete else None,
        )
        if status.phase is None and status.injured is None and status.athlete_name is None:
            raise ValidationError("log_status carried no usable field")
        return status

    if name == "query_progress":
        return QueryProgress(lift=normalize_lift(args.get("lift")))

    if name == "clarify":
        question = str(args.get("question") or "").strip()
        if not question:
            raise ValidationError("clarify requires a question")
        return Clarify(question=question[:200])

    raise ValidationError(f"unknown tool: {name!r}")
