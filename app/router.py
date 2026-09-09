"""The seam between the three layers.

Nothing here decides anything and nothing here talks to a model. It takes the
validated actions from Layer 1, writes them through Layer 2, asks Layer 3 for a
verdict, and stitches the templated reply together.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from app.agent.parser import ModelClient, parse_message
from app.agent.schemas import (
    Action,
    AskNutritionPlan,
    AskPrescription,
    AskTrainingSchedule,
    Clarify,
    ConfigureCalendarPlanning,
    ConfigurePlace,
    ConfigureProgram,
    ConfigureNutrition,
    ConfigureSchedule,
    ConfigureSupplement,
    ConfirmTrainingSchedule,
    ConnectCalendar,
    DisconnectCalendar,
    ForgetPlaces,
    LogCheckIn,
    LogNap,
    LogSupplementTaken,
    LogSet,
    LogStatus,
    QueryProgress,
)
from app.decision.format import (
    format_assessment,
    format_checkin,
    format_logged,
    format_nap_logged,
    format_nap_plan,
    format_nutrition_plan,
    format_prescription,
    format_schedule_confirmation,
    format_schedule_proposal,
    format_status,
)
from app.decision.plausibility import review
from app.decision.prescribe import prescribe_next
from app.decision.readiness import DailyCheckIn, evaluate_readiness
from app.decision.sleep import SleepSchedule, plan_nap
from app.decision.rules import evaluate
from app.programming import Experience, Methodology, ProgrammingProfile, choose_methodology
from app.nutrition import NutritionProfile, Supplement, build_daily_plan
from app.integrations.factory import connection_link, scheduling_service
from app.integrations.google_calendar import CalendarIntegrationError
from app.integrations.google_routes import RoutingIntegrationError
from app.scheduling import SchedulingService
from app.storage import db

MAX_VERDICTS_PER_REPLY = 3

FALLBACK = (
    "I couldn't turn that into a training entry. Try something like:\n"
    "  _squat 3x5 at 140kg, RPE 8_\n"
    "  _bench felt heavy today, 3x5 100kg rpe 9_\n"
    "  _am I stalling on deadlift?_"
)

HELP = (
    "*Training log*\n"
    "Send me your sessions in plain English and I'll track every lift.\n\n"
    "• _squat 3x5 @ 140kg rpe 8_  — logs a session\n"
    "• _bench 3x5 225lb yesterday_  — pounds and dates both work\n"
    "• _am I stalling on squat?_  — verdict from your history\n"
    "• _i'm on a cut now_  — flat weight in a cut counts as holding\n"
    "• _tweaked my left knee_  — flags an injury; I stop suggesting loads\n"
    "• _how's my bench going?_  — progressing, stalled, or deload\n\n"
    "• _slept 7h, readiness 6, soreness 4, protein 150g_  — daily check-in\n"
    "• _morning check-in 7:30, timezone Asia/Kolkata, train 18:30_ — schedule\n"
    "• _napped 30 minutes, readiness 7_ — post-nap reassessment\n"
    "• _vegetarian; I have rice, dal, paneer, bananas_ — food access\n"
    "• _creatine 5g after training, approved by my coach_ — supplement setup\n"
    "• _what should I eat today?_ — meal and approved-supplement timing\n"
    "• _connect my calendar_ — private Google Calendar connection link\n"
    "• _my gym is 123 High Street_ — saves a travel-planning place\n"
    "• _schedule my squat today_ — sleep + calendar + commute options\n"
    "• _confirm A1B2C3_ — writes only that option to the coach calendar\n"
    "• _I'm intermediate and train 4 days/week_  — configures programming\n"
    "• _what should I squat today?_  — deterministic next-session plan\n\n"
    "Verdicts come from fixed rules over your own log, not from a chatbot's opinion."
)


def handle_message(
    conn: sqlite3.Connection,
    athlete_id: str,
    text: str,
    client: ModelClient,
    *,
    today: date | None = None,
    scheduling: SchedulingService | None = None,
) -> str:
    """One inbound WhatsApp message in, one reply out."""
    today = today or date.today()
    text = (text or "").strip()

    if not text:
        return FALLBACK
    if text.lower() in {"help", "/help", "?", "start", "hi", "hello"}:
        return HELP

    known = db.list_lifts(conn, athlete_id)
    parsed = parse_message(text, client, today=today, known_lifts=known)

    if not parsed.actions:
        if parsed.rejected:
            return FALLBACK + "\n\n_(rejected: " + parsed.rejected[0] + ")_"
        return FALLBACK

    return _apply(conn, athlete_id, text, parsed.actions, today, scheduling=scheduling)


def _apply(
    conn: sqlite3.Connection,
    athlete_id: str,
    raw_text: str,
    actions: list[Action],
    today: date,
    *,
    scheduling: SchedulingService | None = None,
) -> str:
    name = db.athlete_name(conn, athlete_id)
    confirmations: list[str] = []
    questions: list[str] = []
    lifts_to_assess: list[str] = []
    lifts_to_prescribe: list[str] = []
    assess_all = False
    nutrition_plan_requests: list[
        tuple[str | None, tuple[tuple[str, str], ...]]
    ] = []
    schedule_requests: list[AskTrainingSchedule] = []
    schedule_confirmations: list[str] = []

    warnings: list[str] = []

    for action in actions:
        if isinstance(action, LogSet):
            # Read the athlete's own history *before* inserting, so "last session"
            # means the one before this message, not this message.
            flags = review(
                action.lift,
                action.weight_kg,
                last_weight_kg=db.last_weight(conn, athlete_id, action.lift),
                best_squat_kg=db.best_weight(conn, athlete_id, "squat"),
            )
            warnings.extend(f"⚠️ {f.message}" for f in flags)
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="set",
                    lift=action.lift,
                    sets=action.sets,
                    reps=action.reps,
                    weight_kg=action.weight_kg,
                    rpe=action.rpe,
                    phase=action.phase,
                    session_date=action.session_date,
                    raw_text=raw_text,
                ),
            )
            confirmations.append(
                format_logged(
                    action.lift,
                    action.sets,
                    action.reps,
                    action.weight_kg,
                    action.rpe,
                    action.session_date,
                )
            )
            if action.lift not in lifts_to_assess:
                lifts_to_assess.append(action.lift)

        elif isinstance(action, LogStatus):
            if action.athlete_name:
                name = action.athlete_name
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="status",
                    phase=action.phase,
                    injured=action.injured,
                    injury_note=action.injury_note,
                    session_date=today.isoformat(),
                    raw_text=raw_text,
                ),
            )
            if action.phase or action.injured is not None:
                confirmations.append(
                    format_status(action.phase, action.injured, action.injury_note)
                )
            elif action.athlete_name:
                confirmations.append(f"✅ Got it, {action.athlete_name}.")

        elif isinstance(action, QueryProgress):
            if action.lift:
                if action.lift not in lifts_to_assess:
                    lifts_to_assess.append(action.lift)
            else:
                assess_all = True

        elif isinstance(action, LogCheckIn):
            checkin = DailyCheckIn(
                checked_on=action.checked_on,
                sleep_hours=action.sleep_hours,
                sleep_quality=action.sleep_quality,
                readiness=action.readiness,
                soreness=action.soreness,
                stress=action.stress,
                bodyweight_kg=action.bodyweight_kg,
                protein_g=action.protein_g,
                calories=action.calories,
                nutrition_adherence=action.nutrition_adherence,
            )
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="status",
                    session_date=action.checked_on,
                    raw_text=raw_text,
                    sleep_hours=action.sleep_hours,
                    sleep_quality=action.sleep_quality,
                    readiness=action.readiness,
                    soreness=action.soreness,
                    stress=action.stress,
                    bodyweight_kg=action.bodyweight_kg,
                    protein_g=action.protein_g,
                    calories=action.calories,
                    nutrition_adherence=action.nutrition_adherence,
                    planned_lift=action.training_lift,
                    planned_training_time=action.training_time,
                ),
            )
            confirmations.append(format_checkin(checkin, evaluate_readiness(checkin)))
            if action.sleep_hours is not None:
                schedule_values = db.latest_schedule_settings(conn, athlete_id)
                schedule = SleepSchedule(
                    timezone=str(schedule_values.get("timezone", "UTC")),
                    morning_checkin_time=str(
                        schedule_values.get("morning_checkin_time", "08:00")
                    ),
                    training_time=(
                        action.training_time
                        or (
                            str(schedule_values["training_time"])
                            if schedule_values.get("training_time")
                            else None
                        )
                    ),
                    bedtime=(
                        str(schedule_values["bedtime"])
                        if schedule_values.get("bedtime")
                        else None
                    ),
                    nap_window_start=str(schedule_values.get("nap_window_start", "13:00")),
                    nap_window_end=str(schedule_values.get("nap_window_end", "16:00")),
                )
                confirmations.append(format_nap_plan(plan_nap(checkin, schedule)))
            if action.training_time and db.latest_nutrition_settings(conn, athlete_id):
                nutrition_plan_requests.append((action.training_time, ()))
            if action.training_lift and db.oauth_connection(conn, athlete_id):
                schedule_requests.append(
                    AskTrainingSchedule(
                        scheduled_on=action.checked_on,
                        lift=action.training_lift,
                        gym_label="gym",
                    )
                )

        elif isinstance(action, LogNap):
            previous = db.latest_checkin(conn, athlete_id, action.checked_on)
            checkin = DailyCheckIn(
                checked_on=action.checked_on,
                sleep_hours=previous.sleep_hours if previous else None,
                sleep_quality=previous.sleep_quality if previous else None,
                readiness=(
                    action.readiness
                    if action.readiness is not None
                    else previous.readiness if previous else None
                ),
                soreness=(
                    action.soreness
                    if action.soreness is not None
                    else previous.soreness if previous else None
                ),
                stress=previous.stress if previous else None,
                bodyweight_kg=previous.bodyweight_kg if previous else None,
                protein_g=previous.protein_g if previous else None,
                calories=previous.calories if previous else None,
                nutrition_adherence=previous.nutrition_adherence if previous else None,
            )
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="status",
                    session_date=action.checked_on,
                    raw_text=raw_text,
                    sleep_hours=checkin.sleep_hours,
                    sleep_quality=checkin.sleep_quality,
                    readiness=checkin.readiness,
                    soreness=checkin.soreness,
                    stress=checkin.stress,
                    bodyweight_kg=checkin.bodyweight_kg,
                    protein_g=checkin.protein_g,
                    calories=checkin.calories,
                    nutrition_adherence=checkin.nutrition_adherence,
                    nap_minutes=action.nap_minutes,
                    planned_lift=previous.planned_lift if previous else None,
                    planned_training_time=(
                        previous.planned_training_time if previous else None
                    ),
                ),
            )
            confirmations.append(
                format_nap_logged(action.nap_minutes, checkin, evaluate_readiness(checkin))
            )
            if previous and previous.planned_lift:
                lifts_to_prescribe.append(previous.planned_lift)
                if db.oauth_connection(conn, athlete_id):
                    schedule_requests.append(
                        AskTrainingSchedule(
                            scheduled_on=action.checked_on,
                            lift=previous.planned_lift,
                            gym_label="gym",
                        )
                    )
            else:
                questions.append(
                    "❓ Which lift is planned today? I need it to recalculate the workout."
                )

        elif isinstance(action, ConfigureSchedule):
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="status",
                    session_date=today.isoformat(),
                    raw_text=raw_text,
                    timezone=action.timezone,
                    morning_checkin_time=action.morning_checkin_time,
                    training_time=action.training_time,
                    bedtime=action.bedtime,
                    nap_window_start=action.nap_window_start,
                    nap_window_end=action.nap_window_end,
                ),
            )
            pieces = [
                f"timezone {action.timezone}" if action.timezone else None,
                (
                    f"morning check-in {action.morning_checkin_time}"
                    if action.morning_checkin_time
                    else None
                ),
                f"training {action.training_time}" if action.training_time else None,
                f"bedtime {action.bedtime}" if action.bedtime else None,
                (
                    f"nap window {action.nap_window_start}–{action.nap_window_end}"
                    if action.nap_window_start and action.nap_window_end
                    else None
                ),
            ]
            confirmations.append(
                "✅ Recovery schedule: " + ", ".join(piece for piece in pieces if piece) + "."
            )

        elif isinstance(action, ConfigureNutrition):
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="status",
                    session_date=today.isoformat(),
                    raw_text=raw_text,
                    diet_style=action.diet_style,
                    foods_available=(
                        json.dumps(action.foods_available) if action.foods_available else None
                    ),
                    allergies=json.dumps(action.allergies) if action.allergies else None,
                    cooking_access=action.cooking_access,
                    meals_per_day=action.meals_per_day,
                    protein_target_g=action.protein_target_g,
                    calorie_target=action.calorie_target,
                    nutrition_approved_by=action.approved_by,
                ),
            )
            confirmations.append(
                "✅ Nutrition access saved. Plans will use only recorded foods and exclusions."
            )

        elif isinstance(action, ConfigureSupplement):
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="status",
                    session_date=today.isoformat(),
                    raw_text=raw_text,
                    supplement_name=action.name,
                    supplement_dose=action.dose,
                    supplement_unit=action.unit,
                    supplement_timing=action.timing,
                    supplement_approved_by=action.approved_by,
                    supplement_batch_tested=action.batch_tested,
                    supplement_active=action.active,
                ),
            )
            state = "active" if action.active else "paused"
            confirmations.append(
                f"✅ Supplement {state}: {action.name} {action.dose:g} {action.unit}."
            )
            if action.active and not action.approved_by:
                warnings.append(
                    "⚠️ It will not be scheduled until you record who approved the dose."
                )
            if action.batch_tested is False:
                warnings.append(
                    "⚠️ This product is not recorded as batch-tested; competitive athletes should review anti-doping risk."
                )

        elif isinstance(action, LogSupplementTaken):
            configured = {
                entry.supplement_name.lower(): entry
                for entry in db.active_supplements(conn, athlete_id)
                if entry.supplement_name
            }
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="status",
                    session_date=action.taken_on,
                    raw_text=raw_text,
                    supplement_name=action.name,
                    supplement_taken=True,
                ),
            )
            confirmations.append(f"✅ Taken: {action.name} ({action.taken_on}).")
            if action.name.lower() not in configured:
                questions.append(
                    "❓ That supplement has no active dose schedule. Tell me its dose, timing, and who approved it."
                )

        elif isinstance(action, AskNutritionPlan):
            nutrition_plan_requests.append((action.training_time, ()))

        elif isinstance(action, ConfigureProgram):
            db.insert_entry(
                conn,
                db.Entry(
                    athlete_id=athlete_id,
                    athlete_name=name,
                    kind="status",
                    session_date=today.isoformat(),
                    raw_text=raw_text,
                    methodology=action.methodology,
                    experience=action.experience,
                    days_per_week=action.days_per_week,
                    meet_date=action.meet_date,
                    has_specialty_equipment=action.has_specialty_equipment,
                ),
            )
            pieces = [
                f"method {action.methodology}" if action.methodology else None,
                f"experience {action.experience}" if action.experience else None,
                f"{action.days_per_week} days/week" if action.days_per_week else None,
                f"meet {action.meet_date}" if action.meet_date else None,
                (
                    "specialty equipment available"
                    if action.has_specialty_equipment is True
                    else "no specialty equipment"
                    if action.has_specialty_equipment is False
                    else None
                ),
            ]
            confirmations.append("✅ Program profile: " + ", ".join(p for p in pieces if p) + ".")

        elif isinstance(action, ConfigurePlace):
            db.save_place(conn, athlete_id, action.label, action.location)
            confirmations.append(
                f"✅ Saved {action.label}. I use it only for travel-time planning."
            )

        elif isinstance(action, ConfigureCalendarPlanning):
            db.save_scheduling_preferences(
                conn,
                athlete_id,
                preferred_start=action.preferred_start,
                preferred_end=action.preferred_end,
                session_minutes=action.session_minutes,
                pre_buffer_minutes=action.pre_buffer_minutes,
                post_buffer_minutes=action.post_buffer_minutes,
                travel_mode=action.travel_mode,
                default_location_label=action.default_location_label,
            )
            confirmations.append(
                "✅ Calendar-planning preferences saved. Sleep and travel remain hard constraints."
            )

        elif isinstance(action, ConnectCalendar):
            link = connection_link(athlete_id)
            if link:
                confirmations.append(
                    "Connect Google Calendar with this private 15-minute link:\n" + link
                )
            else:
                questions.append(
                    "❓ Calendar credentials are not configured on the server yet. See the deployment setup."
                )

        elif isinstance(action, DisconnectCalendar):
            try:
                planner = scheduling or scheduling_service(conn)
                planner.calendar.disconnect(athlete_id)
                confirmations.append(
                    "✅ Google Calendar disconnected and its stored tokens were deleted; saved places remain."
                )
            except (CalendarIntegrationError, RoutingIntegrationError) as exc:
                db.delete_oauth_connection(conn, athlete_id)
                confirmations.append("✅ Stored Google Calendar tokens were deleted locally.")
                warnings.append(f"⚠️ {exc}")

        elif isinstance(action, ForgetPlaces):
            db.delete_saved_places(conn, athlete_id)
            confirmations.append("✅ Saved home, office, and gym locations were deleted.")

        elif isinstance(action, AskTrainingSchedule):
            schedule_requests.append(action)

        elif isinstance(action, ConfirmTrainingSchedule):
            schedule_confirmations.append(action.proposal_id)

        elif isinstance(action, AskPrescription):
            if action.lift:
                lifts_to_prescribe.append(action.lift)
            else:
                known_lifts = db.list_lifts(conn, athlete_id)
                if known_lifts:
                    lifts_to_prescribe.extend(known_lifts)
                else:
                    questions.append("❓ Which lift do you want prescribed?")

        elif isinstance(action, Clarify):
            questions.append(f"❓ {action.question}")

    schedule_blocks: list[str] = []
    if schedule_requests or schedule_confirmations:
        try:
            planner = scheduling or scheduling_service(conn)
            for request in schedule_requests[:1]:
                result = planner.propose(
                    conn,
                    athlete_id,
                    day=date.fromisoformat(request.scheduled_on),
                    lift=request.lift,
                    gym_label=request.gym_label,
                )
                schedule_blocks.append(format_schedule_proposal(result))
                if result.actionable and result.slots:
                    nutrition_plan_requests.append(
                        (
                            result.slots[0].starts_at.strftime("%H:%M"),
                            result.busy_windows,
                        )
                    )
                    if request.lift:
                        lifts_to_prescribe.append(request.lift)
            for proposal_id in schedule_confirmations[:1]:
                confirmed = planner.confirm(conn, athlete_id, proposal_id)
                schedule_blocks.append(format_schedule_confirmation(confirmed))
                nutrition_plan_requests.append(
                    (confirmed.starts_at.strftime("%H:%M"), confirmed.busy_windows)
                )
                if confirmed.lift:
                    lifts_to_prescribe.append(confirmed.lift)
        except (CalendarIntegrationError, RoutingIntegrationError, ValueError) as exc:
            questions.append(f"❓ {exc}")

    if assess_all:
        for lift in db.list_lifts(conn, athlete_id):
            if lift not in lifts_to_assess:
                lifts_to_assess.append(lift)

    phase = db.latest_phase(conn, athlete_id)
    injured, injury_note = db.injury_state(conn, athlete_id)

    verdicts: list[str] = []
    for lift in lifts_to_assess[:MAX_VERDICTS_PER_REPLY]:
        history = db.session_history(conn, athlete_id, lift)
        assessment = evaluate(
            athlete_id,
            lift,
            history,
            phase=phase,
            injured=injured,
            injury_note=injury_note,
        )
        verdicts.append(format_assessment(assessment, athlete_name=None))

    prescriptions: list[str] = []
    settings = db.latest_program_settings(conn, athlete_id)
    if lifts_to_prescribe and not {"experience", "days_per_week"} <= settings.keys():
        questions.append(
            "❓ Before I choose a method, tell me your experience level and training days per week."
        )
    else:
        preferred_value = settings.get("methodology")
        preferred = (
            None
            if preferred_value in {None, "auto"}
            else Methodology(str(preferred_value))
        )
        profile = (
            ProgrammingProfile(
                experience=Experience(str(settings["experience"])),
                days_per_week=int(settings["days_per_week"]),
                weeks_to_meet=(
                    max(0, (date.fromisoformat(str(settings["meet_date"])) - today).days // 7)
                    if settings.get("meet_date") is not None
                    else None
                ),
                rpe_logging_ratio=db.rpe_logging_ratio(conn, athlete_id),
                has_specialty_equipment=bool(settings.get("has_specialty_equipment", False)),
                preferred=preferred,
                injured=injured,
            )
            if lifts_to_prescribe
            else None
        )
        choice = choose_methodology(profile) if profile else None
        checkin_row = db.latest_checkin(conn, athlete_id, today.isoformat())
        checkin = (
            DailyCheckIn(
                checked_on=checkin_row.session_date,
                sleep_hours=checkin_row.sleep_hours,
                sleep_quality=checkin_row.sleep_quality,
                readiness=checkin_row.readiness,
                soreness=checkin_row.soreness,
                stress=checkin_row.stress,
                bodyweight_kg=checkin_row.bodyweight_kg,
                protein_g=checkin_row.protein_g,
                calories=checkin_row.calories,
                nutrition_adherence=checkin_row.nutrition_adherence,
            )
            if checkin_row
            else None
        )
        for lift in dict.fromkeys(lifts_to_prescribe):
            history = db.session_history(conn, athlete_id, lift)
            assessment = evaluate(
                athlete_id,
                lift,
                history,
                phase=phase,
                injured=injured,
                injury_note=injury_note,
            )
            prescription = prescribe_next(
                assessment,
                history,
                choice,
                session_number=len(history) + 1,
                today=today,
                checkin=checkin,
            )
            prescriptions.append(format_prescription(prescription))

    nutrition_plans: list[str] = []
    for requested_time, busy_windows in nutrition_plan_requests[:1]:
        nutrition = db.latest_nutrition_settings(conn, athlete_id)
        if not {"diet_style", "foods_available"} <= nutrition.keys():
            questions.append(
                "❓ Tell me your diet style and foods you can regularly access before I build the day."
            )
            continue
        schedule = db.latest_schedule_settings(conn, athlete_id)
        training_time = requested_time or (
            str(schedule["training_time"]) if schedule.get("training_time") else None
        )
        foods = tuple(json.loads(str(nutrition["foods_available"])))
        allergies = (
            tuple(json.loads(str(nutrition["allergies"])))
            if nutrition.get("allergies")
            else ()
        )
        profile = NutritionProfile(
            diet_style=str(nutrition["diet_style"]),
            foods_available=foods,
            allergies=allergies,
            cooking_access=str(nutrition.get("cooking_access", "basic")),
            meals_per_day=int(nutrition.get("meals_per_day", 4)),
            protein_target_g=(
                float(nutrition["protein_target_g"])
                if nutrition.get("protein_target_g") is not None
                else None
            ),
            calorie_target=(
                float(nutrition["calorie_target"])
                if nutrition.get("calorie_target") is not None
                else None
            ),
            approved_by=(
                str(nutrition["nutrition_approved_by"])
                if nutrition.get("nutrition_approved_by")
                else None
            ),
        )
        supplements = tuple(
            Supplement(
                name=str(entry.supplement_name),
                dose=float(entry.supplement_dose),
                unit=str(entry.supplement_unit),
                timing=str(entry.supplement_timing),
                approved_by=entry.supplement_approved_by,
                batch_tested=entry.supplement_batch_tested,
            )
            for entry in db.active_supplements(conn, athlete_id)
            if entry.supplement_name
            and entry.supplement_dose is not None
            and entry.supplement_unit
            and entry.supplement_timing
        )
        nutrition_plans.append(
            format_nutrition_plan(
                build_daily_plan(
                    profile,
                    training_time=training_time,
                    supplements=supplements,
                    busy_windows=busy_windows,
                    bedtime=(str(schedule["bedtime"]) if schedule.get("bedtime") else None),
                )
            )
        )

    blocks = [
        b
        for b in [
            "\n".join(confirmations),
            "\n".join(warnings),
            "\n\n".join(verdicts),
            "\n\n".join(prescriptions),
            "\n\n".join(schedule_blocks),
            "\n\n".join(nutrition_plans),
            "\n".join(questions),
        ]
        if b
    ]
    return "\n\n".join(blocks) if blocks else FALLBACK
