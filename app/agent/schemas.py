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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.genai import types

from app.reference import LB_TO_KG, ceiling_for
from app.nutrition.planner import COOKING_ACCESS, DIET_STYLES, SUPPLEMENT_TIMINGS
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
    training_lift: str | None = None
    training_time: str | None = None


@dataclass(frozen=True)
class LogNap:
    checked_on: str
    nap_minutes: int
    readiness: int | None = None
    soreness: int | None = None


@dataclass(frozen=True)
class ConfigureSchedule:
    timezone: str | None = None
    morning_checkin_time: str | None = None
    training_time: str | None = None
    bedtime: str | None = None
    nap_window_start: str | None = None
    nap_window_end: str | None = None


@dataclass(frozen=True)
class ConfigureNutrition:
    diet_style: str | None = None
    foods_available: tuple[str, ...] = ()
    allergies: tuple[str, ...] = ()
    cooking_access: str | None = None
    meals_per_day: int | None = None
    protein_target_g: float | None = None
    calorie_target: float | None = None
    approved_by: str | None = None


@dataclass(frozen=True)
class ConfigureSupplement:
    name: str
    dose: float
    unit: str
    timing: str
    approved_by: str | None = None
    batch_tested: bool | None = None
    active: bool = True


@dataclass(frozen=True)
class LogSupplementTaken:
    name: str
    taken_on: str


@dataclass(frozen=True)
class AskNutritionPlan:
    training_time: str | None = None


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
class ConfigurePlace:
    label: str
    location: str


@dataclass(frozen=True)
class ConfigureCalendarPlanning:
    preferred_start: str | None = None
    preferred_end: str | None = None
    session_minutes: int | None = None
    pre_buffer_minutes: int | None = None
    post_buffer_minutes: int | None = None
    travel_mode: str | None = None
    default_location_label: str | None = None


@dataclass(frozen=True)
class ConnectCalendar:
    pass


@dataclass(frozen=True)
class DisconnectCalendar:
    pass


@dataclass(frozen=True)
class ForgetPlaces:
    pass


@dataclass(frozen=True)
class AskTrainingSchedule:
    scheduled_on: str
    lift: str | None = None
    gym_label: str = "gym"


@dataclass(frozen=True)
class ConfirmTrainingSchedule:
    proposal_id: str


@dataclass(frozen=True)
class Clarify:
    question: str


Action = (
    LogSet
    | LogStatus
    | QueryProgress
    | LogCheckIn
    | LogNap
    | ConfigureSchedule
    | ConfigureNutrition
    | ConfigureSupplement
    | LogSupplementTaken
    | AskNutritionPlan
    | AskPrescription
    | ConfigureProgram
    | ConfigurePlace
    | ConfigureCalendarPlanning
    | ConnectCalendar
    | DisconnectCalendar
    | ForgetPlaces
    | AskTrainingSchedule
    | ConfirmTrainingSchedule
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
            "training_lift": types.Schema(
                type=types.Type.STRING,
                description="The lift planned for today, only when explicitly stated.",
            ),
            "training_time": types.Schema(
                type=types.Type.STRING,
                description="Today's planned training time as local HH:MM.",
            ),
            "checked_on": types.Schema(
                type=types.Type.STRING,
                description="Check-in date as YYYY-MM-DD. Default to today when unstated.",
            ),
        },
    ),
)

LOG_NAP = types.FunctionDeclaration(
    name="log_nap",
    description=(
        "Record a completed daytime nap and explicit post-nap readiness or soreness. "
        "Never infer improvement merely because a nap was planned."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "nap_minutes": types.Schema(type=types.Type.INTEGER, description="Minutes actually slept."),
            "readiness": types.Schema(type=types.Type.INTEGER, description="Post-nap readiness 1-10."),
            "soreness": types.Schema(type=types.Type.INTEGER, description="Post-nap soreness 1-10."),
            "checked_on": types.Schema(type=types.Type.STRING, description="Date as YYYY-MM-DD."),
        },
        required=["nap_minutes"],
    ),
)

CONFIGURE_SCHEDULE = types.FunctionDeclaration(
    name="configure_schedule",
    description=(
        "Record the athlete's explicit local schedule for proactive morning check-ins "
        "and nap planning. Never guess times or timezone."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "timezone": types.Schema(
                type=types.Type.STRING,
                description="IANA timezone such as Asia/Kolkata or Europe/London.",
            ),
            "morning_checkin_time": types.Schema(type=types.Type.STRING, description="Local HH:MM."),
            "training_time": types.Schema(type=types.Type.STRING, description="Usual local training HH:MM."),
            "bedtime": types.Schema(type=types.Type.STRING, description="Usual local bedtime HH:MM."),
            "nap_window_start": types.Schema(type=types.Type.STRING, description="Earliest local nap HH:MM."),
            "nap_window_end": types.Schema(type=types.Type.STRING, description="Latest local nap end HH:MM."),
        },
    ),
)

CONFIGURE_NUTRITION = types.FunctionDeclaration(
    name="configure_nutrition",
    description=(
        "Record explicit diet constraints and foods the athlete can actually access. "
        "Targets must already come from the athlete, coach, dietitian, or clinician."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "diet_style": types.Schema(type=types.Type.STRING, enum=sorted(DIET_STYLES)),
            "foods_available": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="Foods the athlete says are regularly available.",
            ),
            "allergies": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
                description="Explicit allergies or excluded ingredients.",
            ),
            "cooking_access": types.Schema(
                type=types.Type.STRING, enum=sorted(COOKING_ACCESS)
            ),
            "meals_per_day": types.Schema(type=types.Type.INTEGER),
            "protein_target_g": types.Schema(
                type=types.Type.NUMBER,
                description="Existing daily protein target; never invent one.",
            ),
            "calorie_target": types.Schema(
                type=types.Type.NUMBER,
                description="Existing approved calorie target; never invent one.",
            ),
            "approved_by": types.Schema(
                type=types.Type.STRING,
                description="Who set or approved the targets, if stated.",
            ),
        },
    ),
)

CONFIGURE_SUPPLEMENT = types.FunctionDeclaration(
    name="configure_supplement",
    description=(
        "Record a supplement the athlete already takes or has been told to take. "
        "Never recommend a new supplement or invent its dose."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "name": types.Schema(type=types.Type.STRING),
            "dose": types.Schema(type=types.Type.NUMBER),
            "unit": types.Schema(type=types.Type.STRING),
            "timing": types.Schema(type=types.Type.STRING, enum=sorted(SUPPLEMENT_TIMINGS)),
            "approved_by": types.Schema(type=types.Type.STRING),
            "batch_tested": types.Schema(type=types.Type.BOOLEAN),
            "active": types.Schema(type=types.Type.BOOLEAN),
        },
        required=["name", "dose", "unit", "timing"],
    ),
)

LOG_SUPPLEMENT_TAKEN = types.FunctionDeclaration(
    name="log_supplement_taken",
    description="Record that the athlete explicitly says they took a configured supplement.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "name": types.Schema(type=types.Type.STRING),
            "taken_on": types.Schema(type=types.Type.STRING, description="Date as YYYY-MM-DD."),
        },
        required=["name"],
    ),
)

ASK_NUTRITION_PLAN = types.FunctionDeclaration(
    name="ask_nutrition_plan",
    description=(
        "The athlete asks what or when to eat or take today. The deterministic planner "
        "uses recorded access, exclusions, training time, and approved supplements."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "training_time": types.Schema(type=types.Type.STRING, description="Local HH:MM."),
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

CONFIGURE_PLACE = types.FunctionDeclaration(
    name="configure_place",
    description=(
        "Save a place the athlete explicitly names, such as gym, home, or office. "
        "Store an address or a value prefixed place_id: exactly as supplied; never infer live location."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "label": types.Schema(type=types.Type.STRING),
            "location": types.Schema(type=types.Type.STRING),
        },
        required=["label", "location"],
    ),
)

CONFIGURE_CALENDAR_PLANNING = types.FunctionDeclaration(
    name="configure_calendar_planning",
    description=(
        "Record explicit preferences for finding training slots around calendar events and travel."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "preferred_start": types.Schema(type=types.Type.STRING, description="Local HH:MM."),
            "preferred_end": types.Schema(type=types.Type.STRING, description="Local HH:MM."),
            "session_minutes": types.Schema(type=types.Type.INTEGER),
            "pre_buffer_minutes": types.Schema(type=types.Type.INTEGER),
            "post_buffer_minutes": types.Schema(type=types.Type.INTEGER),
            "travel_mode": types.Schema(
                type=types.Type.STRING,
                enum=["drive", "walk", "bicycle", "transit", "two_wheeler"],
            ),
            "default_location_label": types.Schema(
                type=types.Type.STRING,
                description="Saved place used before the first and after the last event, e.g. home.",
            ),
        },
    ),
)

CONNECT_CALENDAR = types.FunctionDeclaration(
    name="connect_calendar",
    description="The athlete explicitly asks to connect or link Google Calendar.",
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)

DISCONNECT_CALENDAR = types.FunctionDeclaration(
    name="disconnect_calendar",
    description="The athlete explicitly asks to disconnect Google Calendar and delete stored tokens.",
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)

FORGET_PLACES = types.FunctionDeclaration(
    name="forget_places",
    description="The athlete explicitly asks to delete all saved home, office and gym locations.",
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)

ASK_TRAINING_SCHEDULE = types.FunctionDeclaration(
    name="ask_training_schedule",
    description=(
        "The athlete asks the system to find calendar-aware times for a workout. "
        "Do not choose a time yourself; deterministic Python checks sleep, events and travel."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "scheduled_on": types.Schema(type=types.Type.STRING, description="Date as YYYY-MM-DD."),
            "lift": types.Schema(type=types.Type.STRING),
            "gym_label": types.Schema(type=types.Type.STRING),
        },
    ),
)

CONFIRM_TRAINING_SCHEDULE = types.FunctionDeclaration(
    name="confirm_training_schedule",
    description=(
        "The athlete explicitly confirms one proposed workout option using its short ID."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={"proposal_id": types.Schema(type=types.Type.STRING)},
        required=["proposal_id"],
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
        LOG_NAP,
        CONFIGURE_SCHEDULE,
        CONFIGURE_NUTRITION,
        CONFIGURE_SUPPLEMENT,
        LOG_SUPPLEMENT_TAKEN,
        ASK_NUTRITION_PLAN,
        ASK_PRESCRIPTION,
        CONFIGURE_PROGRAM,
        CONFIGURE_PLACE,
        CONFIGURE_CALENDAR_PLANNING,
        CONNECT_CALENDAR,
        DISCONNECT_CALENDAR,
        FORGET_PLACES,
        ASK_TRAINING_SCHEDULE,
        CONFIRM_TRAINING_SCHEDULE,
        CLARIFY,
    ]
)

TOOL_NAMES = (
    "log_set",
    "log_status",
    "query_progress",
    "log_checkin",
    "log_nap",
    "configure_schedule",
    "configure_nutrition",
    "configure_supplement",
    "log_supplement_taken",
    "ask_nutrition_plan",
    "ask_prescription",
    "configure_program",
    "configure_place",
    "configure_calendar_planning",
    "connect_calendar",
    "disconnect_calendar",
    "forget_places",
    "ask_training_schedule",
    "confirm_training_schedule",
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


def _resolve_schedule_date(value: Any, today: date) -> str:
    if not value:
        return today.isoformat()
    try:
        parsed = date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError(f"scheduled_on is not YYYY-MM-DD: {value!r}") from None
    if parsed < today or parsed > today + timedelta(days=30):
        raise ValidationError("scheduled_on must be between today and 30 days ahead")
    return parsed.isoformat()


def _clock(value: Any, field: str) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    try:
        hour, minute = (int(piece) for piece in raw.split(":"))
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be local HH:MM: {value!r}") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValidationError(f"{field} must be local HH:MM: {value!r}")
    return f"{hour:02d}:{minute:02d}"


def _timezone(value: Any) -> str | None:
    if value is None:
        return None
    result = str(value).strip()
    try:
        ZoneInfo(result)
    except ZoneInfoNotFoundError:
        raise ValidationError(f"unknown IANA timezone: {result!r}") from None
    return result


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    values = value if isinstance(value, (list, tuple)) else str(value).split(",")
    result = tuple(
        dict.fromkeys(str(item).strip().lower() for item in values if str(item).strip())
    )
    if len(result) > 30:
        raise ValidationError(f"{field} has too many values")
    return result


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
            training_lift=normalize_lift(args.get("training_lift")),
            training_time=_clock(args.get("training_time"), "training_time"),
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
            action.training_lift,
            action.training_time,
        )
        if all(value is None for value in metrics):
            raise ValidationError("log_checkin carried no usable field")
        return action

    if name == "log_nap":
        minutes = _int(args.get("nap_minutes"), "nap_minutes", 180)
        if minutes is None:
            raise ValidationError("log_nap requires nap_minutes")
        return LogNap(
            checked_on=_resolve_date(args.get("checked_on"), today),
            nap_minutes=minutes,
            readiness=_int(args.get("readiness"), "readiness", 10),
            soreness=_int(args.get("soreness"), "soreness", 10),
        )

    if name == "configure_schedule":
        action = ConfigureSchedule(
            timezone=_timezone(args.get("timezone")),
            morning_checkin_time=_clock(
                args.get("morning_checkin_time"), "morning_checkin_time"
            ),
            training_time=_clock(args.get("training_time"), "training_time"),
            bedtime=_clock(args.get("bedtime"), "bedtime"),
            nap_window_start=_clock(args.get("nap_window_start"), "nap_window_start"),
            nap_window_end=_clock(args.get("nap_window_end"), "nap_window_end"),
        )
        if all(value is None for value in action.__dict__.values()):
            raise ValidationError("configure_schedule carried no usable field")
        if (
            action.nap_window_start
            and action.nap_window_end
            and action.nap_window_start >= action.nap_window_end
        ):
            raise ValidationError("nap window start must be before nap window end")
        return action

    if name == "configure_nutrition":
        diet_style = str(args.get("diet_style") or "").strip().lower() or None
        cooking = str(args.get("cooking_access") or "").strip().lower() or None
        if diet_style is not None and diet_style not in DIET_STYLES:
            raise ValidationError(f"unknown diet style: {diet_style!r}")
        if cooking is not None and cooking not in COOKING_ACCESS:
            raise ValidationError(f"unknown cooking access: {cooking!r}")
        approved = str(args.get("approved_by") or "").strip()[:80] or None
        action = ConfigureNutrition(
            diet_style=diet_style,
            foods_available=_string_list(args.get("foods_available"), "foods_available"),
            allergies=_string_list(args.get("allergies"), "allergies"),
            cooking_access=cooking,
            meals_per_day=_int(args.get("meals_per_day"), "meals_per_day", 8),
            protein_target_g=_bounded_num(
                args.get("protein_target_g"), "protein_target_g", 0, 600
            ),
            calorie_target=_bounded_num(args.get("calorie_target"), "calorie_target", 0, 15000),
            approved_by=approved,
        )
        if all(value in {None, ()} for value in action.__dict__.values()):
            raise ValidationError("configure_nutrition carried no usable field")
        return action

    if name == "configure_supplement":
        supplement_name = str(args.get("name") or "").strip()[:80]
        dose = _bounded_num(args.get("dose"), "dose", 0.001, 100000)
        unit = str(args.get("unit") or "").strip().lower()[:20]
        timing = str(args.get("timing") or "").strip().lower()
        if not supplement_name or dose is None or not unit:
            raise ValidationError("configure_supplement requires name, dose, and unit")
        if timing not in SUPPLEMENT_TIMINGS:
            raise ValidationError(f"unknown supplement timing: {timing!r}")
        active = args.get("active", True)
        if not isinstance(active, bool):
            active = str(active).strip().lower() in {"true", "1", "yes"}
        batch_tested = args.get("batch_tested")
        if batch_tested is not None and not isinstance(batch_tested, bool):
            batch_tested = str(batch_tested).strip().lower() in {"true", "1", "yes"}
        return ConfigureSupplement(
            name=supplement_name,
            dose=dose,
            unit=unit,
            timing=timing,
            approved_by=str(args.get("approved_by") or "").strip()[:80] or None,
            batch_tested=batch_tested,
            active=active,
        )

    if name == "log_supplement_taken":
        supplement_name = str(args.get("name") or "").strip()[:80]
        if not supplement_name:
            raise ValidationError("log_supplement_taken requires a name")
        return LogSupplementTaken(
            name=supplement_name,
            taken_on=_resolve_date(args.get("taken_on"), today),
        )

    if name == "ask_nutrition_plan":
        return AskNutritionPlan(
            training_time=_clock(args.get("training_time"), "training_time")
        )

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

    if name == "configure_place":
        label = str(args.get("label") or "").strip().lower()[:40]
        location = str(args.get("location") or "").strip()[:500]
        if not label or not location:
            raise ValidationError("configure_place requires a label and location")
        return ConfigurePlace(label=label, location=location)

    if name == "configure_calendar_planning":
        mode = str(args.get("travel_mode") or "").strip().upper() or None
        if mode is not None and mode not in {
            "DRIVE", "WALK", "BICYCLE", "TRANSIT", "TWO_WHEELER"
        }:
            raise ValidationError(f"unknown travel mode: {mode!r}")
        action = ConfigureCalendarPlanning(
            preferred_start=_clock(args.get("preferred_start"), "preferred_start"),
            preferred_end=_clock(args.get("preferred_end"), "preferred_end"),
            session_minutes=_int(args.get("session_minutes"), "session_minutes", 300),
            pre_buffer_minutes=_int(args.get("pre_buffer_minutes"), "pre_buffer_minutes", 180),
            post_buffer_minutes=_int(args.get("post_buffer_minutes"), "post_buffer_minutes", 180),
            travel_mode=mode,
            default_location_label=(
                str(args.get("default_location_label") or "").strip().lower()[:40] or None
            ),
        )
        if all(value is None for value in action.__dict__.values()):
            raise ValidationError("configure_calendar_planning carried no usable field")
        if action.preferred_start and action.preferred_end and action.preferred_start >= action.preferred_end:
            raise ValidationError("preferred training start must be before preferred end")
        return action

    if name == "connect_calendar":
        return ConnectCalendar()

    if name == "disconnect_calendar":
        return DisconnectCalendar()

    if name == "forget_places":
        return ForgetPlaces()

    if name == "ask_training_schedule":
        gym_label = str(args.get("gym_label") or "gym").strip().lower()[:40] or "gym"
        return AskTrainingSchedule(
            scheduled_on=_resolve_schedule_date(args.get("scheduled_on"), today),
            lift=normalize_lift(args.get("lift")),
            gym_label=gym_label,
        )

    if name == "confirm_training_schedule":
        proposal_id = str(args.get("proposal_id") or "").strip().upper()
        if not proposal_id or len(proposal_id) > 20:
            raise ValidationError("confirm_training_schedule requires a proposal ID")
        return ConfirmTrainingSchedule(proposal_id)

    if name == "clarify":
        question = str(args.get("question") or "").strip()
        if not question:
            raise ValidationError("clarify requires a question")
        return Clarify(question=question[:200])

    raise ValidationError(f"unknown tool: {name!r}")
