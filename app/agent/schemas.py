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

from app.reference import LB_TO_KG, ceiling_for
from app.storage.lifts import normalize_lift

# --- Bounds. A model that hallucinates a 900 kg bench gets stopped here. -------
#
# The ceilings are per-lift and empirical: see app/reference.py, where they are
# derived from the top ~115 competition totals of all time. One global cap would
# have to sit above the heaviest squat ever (500 kg) and would therefore wave
# through a 500 kg bench, which is nearly twice the world record.

MIN_WEIGHT_KG = 0.0
MAX_SETS = 30
MAX_REPS = 100
MIN_RPE = 1.0
MAX_RPE = 10.0
MAX_PAST_DAYS = 400
MAX_FUTURE_DAYS = 1

PHASES = ("cut", "maintain", "bulk")
METHODOLOGIES = (
    "auto",
    "linear_progression",
    "five_three_one",
    "block_periodization",
    "autoregulated_rpe",
    "conjugate",
)
EXPERIENCE_LEVELS = ("novice", "intermediate", "advanced")


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
class LogCheckIn:
    checked_on: str
    sleep_hours: float | None = None
    sleep_quality: int | None = None
    readiness: int | None = None
    soreness: int | None = None
    stress: int | None = None
    bodyweight_kg: float | None = None
    protein_g: float | None = None
    calories: float | None = None
    nutrition_adherence: int | None = None


@dataclass(frozen=True)
class AskPrescription:
    lift: str | None = None


@dataclass(frozen=True)
class ConfigureProgram:
    methodology: str | None = None
    experience: str | None = None
    days_per_week: int | None = None
    meet_date: str | None = None
    has_specialty_equipment: bool | None = None


@dataclass(frozen=True)
class Clarify:
    question: str


Action = (
    LogSet
    | LogStatus
    | QueryProgress
    | LogCheckIn
    | AskPrescription
    | ConfigureProgram
    | Clarify
)


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

LOG_CHECKIN = types.FunctionDeclaration(
    name="log_checkin",
    description=(
        "Record today's recovery and nutrition facts exactly as the athlete reports them. "
        "Do not estimate missing values and do not convert vague feelings into scores."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "sleep_hours": types.Schema(type=types.Type.NUMBER, description="Hours slept."),
            "sleep_quality": types.Schema(type=types.Type.INTEGER, description="Sleep quality 1-5."),
            "readiness": types.Schema(type=types.Type.INTEGER, description="Training readiness 1-10."),
            "soreness": types.Schema(type=types.Type.INTEGER, description="Whole-body soreness 1-10."),
            "stress": types.Schema(type=types.Type.INTEGER, description="Current stress 1-10."),
            "bodyweight_kg": types.Schema(type=types.Type.NUMBER, description="Bodyweight in kilograms."),
            "protein_g": types.Schema(type=types.Type.NUMBER, description="Protein eaten today in grams."),
            "calories": types.Schema(type=types.Type.NUMBER, description="Calories eaten today."),
            "nutrition_adherence": types.Schema(
                type=types.Type.INTEGER,
                description="Athlete-rated adherence to their existing nutrition plan, 1-10.",
            ),
            "checked_on": types.Schema(
                type=types.Type.STRING,
                description="Check-in date as YYYY-MM-DD. Default to today when unstated.",
            ),
        },
    ),
)

ASK_PRESCRIPTION = types.FunctionDeclaration(
    name="ask_prescription",
    description=(
        "The athlete explicitly asks what load or workout to do next. Call this instead "
        "of answering; deterministic Python applies history, method, and same-day readiness."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "lift": types.Schema(
                type=types.Type.STRING,
                description="Lift they want prescribed. Omit only if they ask for the full session.",
            ),
        },
    ),
)

CONFIGURE_PROGRAM = types.FunctionDeclaration(
    name="configure_program",
    description=(
        "Record explicit programming facts: experience, schedule, meet horizon, "
        "equipment, or a chosen method. Never infer these from strength numbers."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "methodology": types.Schema(
                type=types.Type.STRING,
                enum=list(METHODOLOGIES),
                description="Chosen method, or auto to let deterministic policy select it.",
            ),
            "experience": types.Schema(
                type=types.Type.STRING,
                enum=list(EXPERIENCE_LEVELS),
                description="Athlete-declared training experience.",
            ),
            "days_per_week": types.Schema(type=types.Type.INTEGER, description="Training days per week, 1-7."),
            "meet_date": types.Schema(
                type=types.Type.STRING,
                description="Next competition date as YYYY-MM-DD. Resolve relative dates against today.",
            ),
            "has_specialty_equipment": types.Schema(
                type=types.Type.BOOLEAN,
                description="Whether specialty bars, bands or chains are available.",
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
    function_declarations=[
        LOG_SET,
        LOG_STATUS,
        QUERY_PROGRESS,
        LOG_CHECKIN,
        ASK_PRESCRIPTION,
        CONFIGURE_PROGRAM,
        CLARIFY,
    ]
)

TOOL_NAMES = (
    "log_set",
    "log_status",
    "query_progress",
    "log_checkin",
    "ask_prescription",
    "configure_program",
    "clarify",
)


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


def _bounded_num(value: Any, field: str, minimum: float, maximum: float) -> float | None:
    number = _num(value, field)
    if number is not None and not minimum <= number <= maximum:
        raise ValidationError(f"{field} out of range ({minimum:g}-{maximum:g}): {number:g}")
    return number


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


def _resolve_meet_date(value: Any, today: date) -> str | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError(f"meet_date is not YYYY-MM-DD: {value!r}") from None
    if parsed < today:
        raise ValidationError(f"meet_date is in the past: {parsed}")
    if parsed > today + timedelta(days=730):
        raise ValidationError(f"meet_date is implausibly far away: {parsed}")
    return parsed.isoformat()


def _to_kg(weight: float | None, unit: Any, lift: str) -> float | None:
    """Convert to kilograms and range-check against this lift's own ceiling."""
    if weight is None:
        return None
    unit_str = str(unit or "kg").strip().lower()
    if unit_str in {"lb", "lbs", "pound", "pounds"}:
        weight = weight * LB_TO_KG
    elif unit_str not in {"kg", "kgs", "kilo", "kilos", "kilogram", "kilograms"}:
        raise ValidationError(f"unknown weight unit: {unit!r}")
    weight = round(weight, 2)
    ceiling = ceiling_for(lift)
    if not (MIN_WEIGHT_KG < weight <= ceiling):
        raise ValidationError(
            f"weight out of range for {lift} (0-{ceiling:g} kg): {weight}"
        )
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
            weight_kg=_to_kg(_num(args.get("weight"), "weight"), args.get("unit"), lift),
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

    if name == "log_checkin":
        action = LogCheckIn(
            checked_on=_resolve_date(args.get("checked_on"), today),
            sleep_hours=_bounded_num(args.get("sleep_hours"), "sleep_hours", 0, 24),
            sleep_quality=_int(args.get("sleep_quality"), "sleep_quality", 5),
            readiness=_int(args.get("readiness"), "readiness", 10),
            soreness=_int(args.get("soreness"), "soreness", 10),
            stress=_int(args.get("stress"), "stress", 10),
            bodyweight_kg=_bounded_num(args.get("bodyweight_kg"), "bodyweight_kg", 20, 400),
            protein_g=_bounded_num(args.get("protein_g"), "protein_g", 0, 600),
            calories=_bounded_num(args.get("calories"), "calories", 0, 15000),
            nutrition_adherence=_int(
                args.get("nutrition_adherence"), "nutrition_adherence", 10
            ),
        )
        metrics = (
            action.sleep_hours,
            action.sleep_quality,
            action.readiness,
            action.soreness,
            action.stress,
            action.bodyweight_kg,
            action.protein_g,
            action.calories,
            action.nutrition_adherence,
        )
        if all(value is None for value in metrics):
            raise ValidationError("log_checkin carried no usable field")
        return action

    if name == "ask_prescription":
        return AskPrescription(lift=normalize_lift(args.get("lift")))

    if name == "configure_program":
        methodology = args.get("methodology")
        experience = args.get("experience")
        if methodology is not None:
            methodology = str(methodology).strip().lower()
            if methodology not in METHODOLOGIES:
                raise ValidationError(f"unknown methodology: {methodology!r}")
        if experience is not None:
            experience = str(experience).strip().lower()
            if experience not in EXPERIENCE_LEVELS:
                raise ValidationError(f"unknown experience level: {experience!r}")
        equipment = args.get("has_specialty_equipment")
        if equipment is not None and not isinstance(equipment, bool):
            equipment = str(equipment).strip().lower() in {"true", "1", "yes"}
        action = ConfigureProgram(
            methodology=methodology,
            experience=experience,
            days_per_week=_int(args.get("days_per_week"), "days_per_week", 7),
            meet_date=_resolve_meet_date(args.get("meet_date"), today),
            has_specialty_equipment=equipment,
        )
        if all(value is None for value in action.__dict__.values()):
            raise ValidationError("configure_program carried no usable field")
        return action

    if name == "clarify":
        question = str(args.get("question") or "").strip()
        if not question:
            raise ValidationError("clarify requires a question")
        return Clarify(question=question[:200])

    raise ValidationError(f"unknown tool: {name!r}")
