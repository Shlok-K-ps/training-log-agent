"""SQLite storage: one file, one append-only coaching timeline.

Why SQLite: the data is small, structured, and single-writer. A 20-athlete team
generates a few thousand rows a year. Postgres solves concurrency problems this
project does not have, at the cost of a server to run and a connection string to
keep secret. One file that you can copy, diff, and open in any client is worth
more here than horizontal scale that will never be used.

Why one timeline table: every entry row is one observation about one athlete at one point in
time. Sets carry a lift; status updates (phase change, injury) carry none. Both
are facts on a timeline, so both live on the same timeline. State — "what phase
is Priya in right now?" — is derived by reading the latest row, never stored
separately, so it can never drift out of sync with the log. OAuth credentials,
saved places and athlete-approved calendar proposals use dedicated tables: they
are operational integration state, not coaching observations.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Literal

from app.config import settings
from app.security import SecretCipher
from app.storage.lifts import normalize_lift

EntryKind = Literal["set", "status"]
Phase = Literal["cut", "maintain", "bulk"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id    TEXT    NOT NULL,
    athlete_name  TEXT,
    kind          TEXT    NOT NULL CHECK (kind IN ('set', 'status')),
    lift          TEXT,
    sets          INTEGER,
    reps          INTEGER,
    weight_kg     REAL,
    rpe           REAL,
    phase         TEXT    CHECK (phase IS NULL OR phase IN ('cut', 'maintain', 'bulk')),
    injured       INTEGER CHECK (injured IS NULL OR injured IN (0, 1)),
    injury_note   TEXT,
    injury_cleared_by TEXT,
    injury_cleared_at TEXT,
    injury_clearance_reason TEXT,
    injury_clearance_requested INTEGER,
    sleep_hours   REAL,
    sleep_quality INTEGER,
    readiness     INTEGER,
    soreness      INTEGER,
    stress        INTEGER,
    bodyweight_kg REAL,
    protein_g     REAL,
    calories      REAL,
    nutrition_adherence INTEGER,
    nap_minutes   INTEGER,
    planned_lift  TEXT,
    planned_training_time TEXT,
    methodology   TEXT,
    experience    TEXT,
    days_per_week INTEGER,
    meet_date     TEXT,
    has_specialty_equipment INTEGER,
    timezone      TEXT,
    morning_checkin_time TEXT,
    training_time TEXT,
    bedtime       TEXT,
    nap_window_start TEXT,
    nap_window_end TEXT,
    diet_style TEXT,
    foods_available TEXT,
    allergies TEXT,
    cooking_access TEXT,
    meals_per_day INTEGER,
    protein_target_g REAL,
    calorie_target REAL,
    nutrition_approved_by TEXT,
    supplement_name TEXT,
    supplement_dose REAL,
    supplement_unit TEXT,
    supplement_timing TEXT,
    supplement_approved_by TEXT,
    supplement_batch_tested INTEGER,
    supplement_active INTEGER,
    supplement_taken INTEGER,
    session_date  TEXT    NOT NULL,
    raw_text      TEXT,
    created_at    TEXT    NOT NULL,
    CHECK (kind = 'status' OR lift IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_entries_athlete_lift_date
    ON entries (athlete_id, lift, session_date);

CREATE INDEX IF NOT EXISTS idx_entries_athlete_date
    ON entries (athlete_id, session_date);

CREATE TABLE IF NOT EXISTS scheduled_deliveries (
    athlete_id   TEXT NOT NULL,
    message_kind TEXT NOT NULL,
    local_date   TEXT NOT NULL,
    sent_at      TEXT NOT NULL,
    PRIMARY KEY (athlete_id, message_kind, local_date)
);

CREATE TABLE IF NOT EXISTS outbound_drafts (
    athlete_id    TEXT NOT NULL,
    message_kind  TEXT NOT NULL,
    local_date    TEXT NOT NULL,
    body          TEXT NOT NULL,
    original_body TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('pending','approved','skipped','sent')),
    reviewed_by   TEXT,
    reviewed_at   TEXT,
    evidence_version INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (athlete_id, message_kind, local_date)
);

CREATE TABLE IF NOT EXISTS whatsapp_messages (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id     TEXT NOT NULL,
    provider_sid   TEXT UNIQUE,
    direction      TEXT NOT NULL CHECK (direction IN ('inbound','outbound')),
    body           TEXT NOT NULL,
    message_kind   TEXT NOT NULL DEFAULT 'general',
    status         TEXT NOT NULL CHECK (status IN
                       ('received','queued','sent','delivered','read','failed')),
    occurred_at    TEXT NOT NULL,
    scheduled_for  TEXT,
    reply_to_sid   TEXT,
    error_code     TEXT,
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_athlete_time
    ON whatsapp_messages (athlete_id, occurred_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_whatsapp_messages_status
    ON whatsapp_messages (status, occurred_at DESC);

CREATE TABLE IF NOT EXISTS whatsapp_conversation_state (
    athlete_id            TEXT PRIMARY KEY,
    work_state            TEXT NOT NULL DEFAULT 'needs_coach'
                          CHECK (work_state IN ('needs_coach','awaiting_athlete','resolved')),
    last_read_message_id  INTEGER NOT NULL DEFAULT 0,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS athlete_profile_revisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id      TEXT NOT NULL,
    bodyweight_kg   REAL,
    squat_1rm_kg    REAL,
    bench_1rm_kg    REAL,
    deadlift_1rm_kg REAL,
    training_days   INTEGER,
    experience      TEXT,
    goal_lift       TEXT,
    goal_target_kg  REAL,
    goal_start_date TEXT,
    goal_target_date TEXT,
    created_by      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_athlete_profile_revision
    ON athlete_profile_revisions (athlete_id, id DESC);

CREATE TABLE IF NOT EXISTS injury_plan_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    athlete_id      TEXT NOT NULL,
    injury_entry_id INTEGER NOT NULL,
    option_code     TEXT NOT NULL,
    plan_text       TEXT NOT NULL,
    approved_by     TEXT NOT NULL,
    approved_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_injury_plan_athlete
    ON injury_plan_decisions (athlete_id, injury_entry_id, id DESC);

CREATE TABLE IF NOT EXISTS oauth_connections (
    athlete_id        TEXT NOT NULL,
    provider          TEXT NOT NULL,
    access_token      TEXT NOT NULL,
    refresh_token     TEXT,
    expires_at        TEXT,
    scopes            TEXT NOT NULL,
    provider_calendar_id TEXT,
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (athlete_id, provider)
);

CREATE TABLE IF NOT EXISTS saved_places (
    athlete_id TEXT NOT NULL,
    label      TEXT NOT NULL,
    location   TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (athlete_id, label)
);

CREATE TABLE IF NOT EXISTS scheduling_preferences (
    athlete_id TEXT PRIMARY KEY,
    preferred_start TEXT NOT NULL DEFAULT '06:00',
    preferred_end TEXT NOT NULL DEFAULT '21:00',
    session_minutes INTEGER NOT NULL DEFAULT 90,
    pre_buffer_minutes INTEGER NOT NULL DEFAULT 15,
    post_buffer_minutes INTEGER NOT NULL DEFAULT 30,
    unknown_location_buffer_minutes INTEGER NOT NULL DEFAULT 30,
    bedtime_buffer_minutes INTEGER NOT NULL DEFAULT 90,
    travel_mode TEXT NOT NULL DEFAULT 'DRIVE',
    default_location_label TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_proposals (
    id TEXT PRIMARY KEY,
    athlete_id TEXT NOT NULL,
    local_date TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    gym_label TEXT NOT NULL,
    lift TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'cancelled', 'expired', 'superseded')),
    reasons TEXT NOT NULL,
    calendar_event_id TEXT,
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_schedule_proposals_athlete_status
    ON schedule_proposals (athlete_id, status, created_at);
"""

INJURY_COLUMNS = {
    "injury_cleared_by": "TEXT",
    "injury_cleared_at": "TEXT",
    "injury_clearance_reason": "TEXT",
    "injury_clearance_requested": "INTEGER",
}

CHECKIN_COLUMNS = {
    "sleep_hours": "REAL",
    "sleep_quality": "INTEGER",
    "readiness": "INTEGER",
    "soreness": "INTEGER",
    "stress": "INTEGER",
    "bodyweight_kg": "REAL",
    "protein_g": "REAL",
    "calories": "REAL",
    "nutrition_adherence": "INTEGER",
    "nap_minutes": "INTEGER",
    "planned_lift": "TEXT",
    "planned_training_time": "TEXT",
}

PROGRAM_COLUMNS = {
    "methodology": "TEXT",
    "experience": "TEXT",
    "days_per_week": "INTEGER",
    "meet_date": "TEXT",
    "has_specialty_equipment": "INTEGER",
}

SCHEDULE_COLUMNS = {
    "timezone": "TEXT",
    "morning_checkin_time": "TEXT",
    "training_time": "TEXT",
    "bedtime": "TEXT",
    "nap_window_start": "TEXT",
    "nap_window_end": "TEXT",
}

NUTRITION_COLUMNS = {
    "diet_style": "TEXT",
    "foods_available": "TEXT",
    "allergies": "TEXT",
    "cooking_access": "TEXT",
    "meals_per_day": "INTEGER",
    "protein_target_g": "REAL",
    "calorie_target": "REAL",
    "nutrition_approved_by": "TEXT",
}

SUPPLEMENT_COLUMNS = {
    "supplement_name": "TEXT",
    "supplement_dose": "REAL",
    "supplement_unit": "TEXT",
    "supplement_timing": "TEXT",
    "supplement_approved_by": "TEXT",
    "supplement_batch_tested": "INTEGER",
    "supplement_active": "INTEGER",
    "supplement_taken": "INTEGER",
}

OUTBOUND_DRAFT_COLUMNS = {
    "evidence_version": "INTEGER NOT NULL DEFAULT 0",
}

ATHLETE_PROFILE_COLUMNS = {
    "goal_start_date": "TEXT",
}


@dataclass(frozen=True)
class Entry:
    """One row of the log."""

    athlete_id: str
    kind: EntryKind = "set"
    athlete_name: str | None = None
    lift: str | None = None
    sets: int | None = None
    reps: int | None = None
    weight_kg: float | None = None
    rpe: float | None = None
    phase: Phase | None = None
    injured: bool | None = None
    injury_note: str | None = None
    injury_cleared_by: str | None = None
    injury_cleared_at: str | None = None
    injury_clearance_reason: str | None = None
    injury_clearance_requested: bool | None = None
    sleep_hours: float | None = None
    sleep_quality: int | None = None
    readiness: int | None = None
    soreness: int | None = None
    stress: int | None = None
    bodyweight_kg: float | None = None
    protein_g: float | None = None
    calories: float | None = None
    nutrition_adherence: int | None = None
    nap_minutes: int | None = None
    planned_lift: str | None = None
    planned_training_time: str | None = None
    methodology: str | None = None
    experience: str | None = None
    days_per_week: int | None = None
    meet_date: str | None = None
    has_specialty_equipment: bool | None = None
    timezone: str | None = None
    morning_checkin_time: str | None = None
    training_time: str | None = None
    bedtime: str | None = None
    nap_window_start: str | None = None
    nap_window_end: str | None = None
    diet_style: str | None = None
    foods_available: str | None = None
    allergies: str | None = None
    cooking_access: str | None = None
    meals_per_day: int | None = None
    protein_target_g: float | None = None
    calorie_target: float | None = None
    nutrition_approved_by: str | None = None
    supplement_name: str | None = None
    supplement_dose: float | None = None
    supplement_unit: str | None = None
    supplement_timing: str | None = None
    supplement_approved_by: str | None = None
    supplement_batch_tested: bool | None = None
    supplement_active: bool | None = None
    supplement_taken: bool | None = None
    session_date: str = ""
    raw_text: str | None = None
    id: int | None = None

    def with_defaults(self) -> "Entry":
        return Entry(
            athlete_id=self.athlete_id,
            kind=self.kind,
            athlete_name=self.athlete_name,
            lift=normalize_lift(self.lift),
            sets=self.sets,
            reps=self.reps,
            weight_kg=self.weight_kg,
            rpe=self.rpe,
            phase=self.phase,
            injured=self.injured,
            injury_note=self.injury_note,
            injury_cleared_by=self.injury_cleared_by,
            injury_cleared_at=self.injury_cleared_at,
            injury_clearance_reason=self.injury_clearance_reason,
            injury_clearance_requested=self.injury_clearance_requested,
            sleep_hours=self.sleep_hours,
            sleep_quality=self.sleep_quality,
            readiness=self.readiness,
            soreness=self.soreness,
            stress=self.stress,
            bodyweight_kg=self.bodyweight_kg,
            protein_g=self.protein_g,
            calories=self.calories,
            nutrition_adherence=self.nutrition_adherence,
            nap_minutes=self.nap_minutes,
            planned_lift=normalize_lift(self.planned_lift),
            planned_training_time=self.planned_training_time,
            methodology=self.methodology,
            experience=self.experience,
            days_per_week=self.days_per_week,
            meet_date=self.meet_date,
            has_specialty_equipment=self.has_specialty_equipment,
            timezone=self.timezone,
            morning_checkin_time=self.morning_checkin_time,
            training_time=self.training_time,
            bedtime=self.bedtime,
            nap_window_start=self.nap_window_start,
            nap_window_end=self.nap_window_end,
            diet_style=self.diet_style,
            foods_available=self.foods_available,
            allergies=self.allergies,
            cooking_access=self.cooking_access,
            meals_per_day=self.meals_per_day,
            protein_target_g=self.protein_target_g,
            calorie_target=self.calorie_target,
            nutrition_approved_by=self.nutrition_approved_by,
            supplement_name=self.supplement_name,
            supplement_dose=self.supplement_dose,
            supplement_unit=self.supplement_unit,
            supplement_timing=self.supplement_timing,
            supplement_approved_by=self.supplement_approved_by,
            supplement_batch_tested=self.supplement_batch_tested,
            supplement_active=self.supplement_active,
            supplement_taken=self.supplement_taken,
            session_date=self.session_date or date.today().isoformat(),
            raw_text=self.raw_text,
            id=self.id,
        )


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open the database, creating the file and schema if needed."""
    path = Path(db_path) if db_path is not None else settings.db_file
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(entries)")}
    for name, column_type in (
        CHECKIN_COLUMNS
        | INJURY_COLUMNS
        | PROGRAM_COLUMNS
        | SCHEDULE_COLUMNS
        | NUTRITION_COLUMNS
        | SUPPLEMENT_COLUMNS
    ).items():
        if name not in existing:
            conn.execute(f"ALTER TABLE entries ADD COLUMN {name} {column_type}")
    draft_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(outbound_drafts)")
    }
    for name, column_type in OUTBOUND_DRAFT_COLUMNS.items():
        if name not in draft_columns:
            conn.execute(f"ALTER TABLE outbound_drafts ADD COLUMN {name} {column_type}")
    profile_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(athlete_profile_revisions)")
    }
    for name, column_type in ATHLETE_PROFILE_COLUMNS.items():
        if name not in profile_columns:
            conn.execute(
                f"ALTER TABLE athlete_profile_revisions ADD COLUMN {name} {column_type}"
            )
    conn.commit()


def insert_entry(conn: sqlite3.Connection, entry: Entry) -> int:
    e = entry.with_defaults()
    columns = (
        "athlete_id", "athlete_name", "kind", "lift", "sets", "reps", "weight_kg", "rpe",
        "phase", "injured", "injury_note", "injury_cleared_by", "injury_cleared_at",
        "injury_clearance_reason", "injury_clearance_requested",
        "sleep_hours", "sleep_quality", "readiness",
        "soreness", "stress", "bodyweight_kg", "protein_g", "calories", "nutrition_adherence",
        "nap_minutes", "planned_lift", "planned_training_time", "methodology", "experience",
        "days_per_week", "meet_date", "has_specialty_equipment", "timezone",
        "morning_checkin_time", "training_time", "bedtime", "nap_window_start", "nap_window_end",
        "diet_style", "foods_available", "allergies", "cooking_access", "meals_per_day",
        "protein_target_g", "calorie_target", "nutrition_approved_by", "supplement_name",
        "supplement_dose", "supplement_unit", "supplement_timing", "supplement_approved_by",
        "supplement_batch_tested", "supplement_active", "supplement_taken", "session_date",
        "raw_text", "created_at",
    )
    values = (
            e.athlete_id,
            e.athlete_name,
            e.kind,
            e.lift,
            e.sets,
            e.reps,
            e.weight_kg,
            e.rpe,
            e.phase,
            None if e.injured is None else int(e.injured),
            e.injury_note,
            e.injury_cleared_by,
            e.injury_cleared_at,
            e.injury_clearance_reason,
            None if e.injury_clearance_requested is None else int(e.injury_clearance_requested),
            e.sleep_hours,
            e.sleep_quality,
            e.readiness,
            e.soreness,
            e.stress,
            e.bodyweight_kg,
            e.protein_g,
            e.calories,
            e.nutrition_adherence,
            e.nap_minutes,
            e.planned_lift,
            e.planned_training_time,
            e.methodology,
            e.experience,
            e.days_per_week,
            e.meet_date,
            None if e.has_specialty_equipment is None else int(e.has_specialty_equipment),
            e.timezone,
            e.morning_checkin_time,
            e.training_time,
            e.bedtime,
            e.nap_window_start,
            e.nap_window_end,
            e.diet_style,
            e.foods_available,
            e.allergies,
            e.cooking_access,
            e.meals_per_day,
            e.protein_target_g,
            e.calorie_target,
            e.nutrition_approved_by,
            e.supplement_name,
            e.supplement_dose,
            e.supplement_unit,
            e.supplement_timing,
            e.supplement_approved_by,
            None if e.supplement_batch_tested is None else int(e.supplement_batch_tested),
            None if e.supplement_active is None else int(e.supplement_active),
            None if e.supplement_taken is None else int(e.supplement_taken),
            e.session_date,
            e.raw_text,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    placeholders = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"INSERT INTO entries ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_many(conn: sqlite3.Connection, entries: Iterable[Entry]) -> list[int]:
    return [insert_entry(conn, entry) for entry in entries]


def _row_to_entry(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"],
        athlete_id=row["athlete_id"],
        athlete_name=row["athlete_name"],
        kind=row["kind"],
        lift=row["lift"],
        sets=row["sets"],
        reps=row["reps"],
        weight_kg=row["weight_kg"],
        rpe=row["rpe"],
        phase=row["phase"],
        injured=None if row["injured"] is None else bool(row["injured"]),
        injury_note=row["injury_note"],
        injury_cleared_by=row["injury_cleared_by"],
        injury_cleared_at=row["injury_cleared_at"],
        injury_clearance_reason=row["injury_clearance_reason"],
        injury_clearance_requested=(
            None if row["injury_clearance_requested"] is None
            else bool(row["injury_clearance_requested"])
        ),
        sleep_hours=row["sleep_hours"],
        sleep_quality=row["sleep_quality"],
        readiness=row["readiness"],
        soreness=row["soreness"],
        stress=row["stress"],
        bodyweight_kg=row["bodyweight_kg"],
        protein_g=row["protein_g"],
        calories=row["calories"],
        nutrition_adherence=row["nutrition_adherence"],
        nap_minutes=row["nap_minutes"],
        planned_lift=row["planned_lift"],
        planned_training_time=row["planned_training_time"],
        methodology=row["methodology"],
        experience=row["experience"],
        days_per_week=row["days_per_week"],
        meet_date=row["meet_date"],
        has_specialty_equipment=(
            None
            if row["has_specialty_equipment"] is None
            else bool(row["has_specialty_equipment"])
        ),
        timezone=row["timezone"],
        morning_checkin_time=row["morning_checkin_time"],
        training_time=row["training_time"],
        bedtime=row["bedtime"],
        nap_window_start=row["nap_window_start"],
        nap_window_end=row["nap_window_end"],
        diet_style=row["diet_style"],
        foods_available=row["foods_available"],
        allergies=row["allergies"],
        cooking_access=row["cooking_access"],
        meals_per_day=row["meals_per_day"],
        protein_target_g=row["protein_target_g"],
        calorie_target=row["calorie_target"],
        nutrition_approved_by=row["nutrition_approved_by"],
        supplement_name=row["supplement_name"],
        supplement_dose=row["supplement_dose"],
        supplement_unit=row["supplement_unit"],
        supplement_timing=row["supplement_timing"],
        supplement_approved_by=row["supplement_approved_by"],
        supplement_batch_tested=(
            None if row["supplement_batch_tested"] is None else bool(row["supplement_batch_tested"])
        ),
        supplement_active=(
            None if row["supplement_active"] is None else bool(row["supplement_active"])
        ),
        supplement_taken=(
            None if row["supplement_taken"] is None else bool(row["supplement_taken"])
        ),
        session_date=row["session_date"],
        raw_text=row["raw_text"],
    )


def session_history(
    conn: sqlite3.Connection, athlete_id: str, lift: str
) -> list[Entry]:
    """All logged sets for one athlete and one lift, oldest first."""
    canonical = normalize_lift(lift)
    rows = conn.execute(
        """
        SELECT * FROM entries
        WHERE athlete_id = ? AND kind = 'set' AND lift = ?
        ORDER BY session_date ASC, id ASC
        """,
        (athlete_id, canonical),
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def list_lifts(conn: sqlite3.Connection, athlete_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT lift, MAX(session_date) AS last_seen
        FROM entries
        WHERE athlete_id = ? AND kind = 'set' AND lift IS NOT NULL
        GROUP BY lift
        ORDER BY last_seen DESC
        """,
        (athlete_id,),
    ).fetchall()
    return [r["lift"] for r in rows]


def latest_phase(conn: sqlite3.Connection, athlete_id: str) -> str:
    """Current training phase — the most recently recorded one, else 'maintain'."""
    row = conn.execute(
        """
        SELECT phase FROM entries
        WHERE athlete_id = ? AND phase IS NOT NULL
        ORDER BY session_date DESC, id DESC
        LIMIT 1
        """,
        (athlete_id,),
    ).fetchone()
    return row["phase"] if row else "maintain"


def injury_state(conn: sqlite3.Connection, athlete_id: str) -> tuple[bool, str | None]:
    """(is_injured, note) from the most recent row that recorded injury status.

    A row that says `injured = 0` only counts as a clearance when it also names
    who cleared it. Anything else — including a row written by a model that
    decided the athlete sounded better — leaves the flag open. The gate fails
    closed on purpose: the cost of a wrong clearance is somebody getting hurt.
    """
    row = conn.execute(
        """
        SELECT injured, injury_note, injury_cleared_by FROM entries
        WHERE athlete_id = ? AND injured IS NOT NULL
        ORDER BY session_date DESC, id DESC
        LIMIT 1
        """,
        (athlete_id,),
    ).fetchone()
    if row is None:
        return False, None
    if not bool(row["injured"]) and not row["injury_cleared_by"]:
        return True, row["injury_note"]
    return bool(row["injured"]), row["injury_note"]


def injury_opened_on(conn: sqlite3.Connection, athlete_id: str) -> str | None:
    """Session date the currently-open injury episode was first reported."""
    row = conn.execute(
        """
        SELECT session_date FROM entries
        WHERE athlete_id = ? AND injured = 1
          AND id > COALESCE((
              SELECT MAX(id) FROM entries
              WHERE athlete_id = ? AND injured = 0 AND injury_cleared_by IS NOT NULL
          ), 0)
        ORDER BY session_date ASC, id ASC
        LIMIT 1
        """,
        (athlete_id, athlete_id),
    ).fetchone()
    return None if row is None else str(row["session_date"])


def open_injury_entry_id(conn: sqlite3.Connection, athlete_id: str) -> int | None:
    """Newest report in the currently open injury episode."""
    row = conn.execute(
        """
        SELECT id FROM entries
        WHERE athlete_id = ? AND injured = 1
          AND id > COALESCE((
              SELECT MAX(id) FROM entries
              WHERE athlete_id = ? AND injured = 0 AND injury_cleared_by IS NOT NULL
          ), 0)
        ORDER BY id DESC LIMIT 1
        """,
        (athlete_id, athlete_id),
    ).fetchone()
    return None if row is None else int(row["id"])


def record_injury_plan_decision(
    conn: sqlite3.Connection,
    *,
    athlete_id: str,
    injury_entry_id: int,
    option_code: str,
    plan_text: str,
    approved_by: str,
) -> int:
    approved_by = (approved_by or "").strip()
    if not approved_by:
        raise ValueError("an injury plan must record the approving coach")
    if open_injury_entry_id(conn, athlete_id) != injury_entry_id:
        raise ValueError("the injury changed; review the current options again")
    cur = conn.execute(
        """
        INSERT INTO injury_plan_decisions
            (athlete_id, injury_entry_id, option_code, plan_text, approved_by, approved_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            athlete_id, injury_entry_id, option_code, plan_text.strip(), approved_by,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def latest_injury_plan_decision(
    conn: sqlite3.Connection, athlete_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM injury_plan_decisions WHERE athlete_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (athlete_id,),
    ).fetchone()


def clearance_requested_on(conn: sqlite3.Connection, athlete_id: str) -> str | None:
    """Most recent date the athlete asked to be cleared, within this episode."""
    row = conn.execute(
        """
        SELECT session_date FROM entries
        WHERE athlete_id = ? AND injury_clearance_requested = 1
        ORDER BY session_date DESC, id DESC
        LIMIT 1
        """,
        (athlete_id,),
    ).fetchone()
    return None if row is None else str(row["session_date"])


def request_injury_clearance(
    conn: sqlite3.Connection, athlete_id: str, *, note: str | None, on: str, raw_text: str | None = None
) -> None:
    """Record that the athlete says they feel better. Does not close the flag."""
    insert_entry(
        conn,
        Entry(
            athlete_id=athlete_id,
            kind="status",
            session_date=on,
            raw_text=raw_text,
            injury_clearance_requested=True,
            injury_note=note,
        ),
    )


def clear_injury(
    conn: sqlite3.Connection,
    athlete_id: str,
    *,
    actor: str,
    reason: str,
    on: str | None = None,
) -> None:
    """Close an injury. Requires a named actor who is not the athlete.

    There is deliberately no path to this function from an inbound WhatsApp
    message. It is called by an operator tool, and the actor it records is a
    person who can be asked why they cleared it.
    """
    actor = (actor or "").strip()
    reason = (reason or "").strip()
    if not actor:
        raise ValueError("clearing an injury requires a named actor")
    if actor == athlete_id.strip():
        raise ValueError("an athlete cannot clear their own injury")
    if not reason:
        raise ValueError("clearing an injury requires a recorded reason")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    insert_entry(
        conn,
        Entry(
            athlete_id=athlete_id,
            kind="status",
            session_date=on or date.today().isoformat(),
            injured=False,
            injury_note=None,
            injury_cleared_by=actor,
            injury_cleared_at=now,
            injury_clearance_reason=reason,
        ),
    )


def athlete_name(conn: sqlite3.Connection, athlete_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT athlete_name FROM entries
        WHERE athlete_id = ? AND athlete_name IS NOT NULL
        ORDER BY id DESC LIMIT 1
        """,
        (athlete_id,),
    ).fetchone()
    return row["athlete_name"] if row else None


def last_weight(conn: sqlite3.Connection, athlete_id: str, lift: str) -> float | None:
    """Top weight from this athlete's most recent session on this lift."""
    row = conn.execute(
        """
        SELECT MAX(weight_kg) AS w FROM entries
        WHERE athlete_id = ? AND kind = 'set' AND lift = ? AND weight_kg IS NOT NULL
          AND session_date = (
              SELECT MAX(session_date) FROM entries
              WHERE athlete_id = ? AND kind = 'set' AND lift = ? AND weight_kg IS NOT NULL
          )
        """,
        (athlete_id, normalize_lift(lift), athlete_id, normalize_lift(lift)),
    ).fetchone()
    return row["w"] if row and row["w"] is not None else None


def best_weight(conn: sqlite3.Connection, athlete_id: str, lift: str) -> float | None:
    """Heaviest this athlete has ever logged for this lift."""
    row = conn.execute(
        """
        SELECT MAX(weight_kg) AS w FROM entries
        WHERE athlete_id = ? AND kind = 'set' AND lift = ?
        """,
        (athlete_id, normalize_lift(lift)),
    ).fetchone()
    return row["w"] if row and row["w"] is not None else None


def recent_entries(
    conn: sqlite3.Connection, athlete_id: str, limit: int = 10
) -> list[Entry]:
    rows = conn.execute(
        """
        SELECT * FROM entries
        WHERE athlete_id = ? AND kind = 'set'
        ORDER BY session_date DESC, id DESC
        LIMIT ?
        """,
        (athlete_id, limit),
    ).fetchall()
    return [_row_to_entry(r) for r in rows]


def latest_checkin(
    conn: sqlite3.Connection, athlete_id: str, checked_on: str
) -> Entry | None:
    """Latest check-in on an exact date; stale recovery data never carries forward."""
    columns = " OR ".join(f"{name} IS NOT NULL" for name in CHECKIN_COLUMNS)
    row = conn.execute(
        f"""
        SELECT * FROM entries
        WHERE athlete_id = ? AND kind = 'status' AND session_date = ?
          AND ({columns})
        ORDER BY id DESC LIMIT 1
        """,
        (athlete_id, checked_on),
    ).fetchone()
    return _row_to_entry(row) if row else None


def latest_program_settings(conn: sqlite3.Connection, athlete_id: str) -> dict[str, object]:
    """Derive each current programming setting from the latest row that states it."""
    result: dict[str, object] = {}
    for column in PROGRAM_COLUMNS:
        row = conn.execute(
            f"""
            SELECT {column} AS value FROM entries
            WHERE athlete_id = ? AND {column} IS NOT NULL
            ORDER BY session_date DESC, id DESC LIMIT 1
            """,
            (athlete_id,),
        ).fetchone()
        if row is not None:
            value = row["value"]
            if column == "has_specialty_equipment":
                value = bool(value)
            result[column] = value
    return result


def latest_schedule_settings(conn: sqlite3.Connection, athlete_id: str) -> dict[str, object]:
    """Derive current local schedule settings from the athlete's event log."""
    result: dict[str, object] = {}
    for column in SCHEDULE_COLUMNS:
        row = conn.execute(
            f"""
            SELECT {column} AS value FROM entries
            WHERE athlete_id = ? AND {column} IS NOT NULL
            ORDER BY session_date DESC, id DESC LIMIT 1
            """,
            (athlete_id,),
        ).fetchone()
        if row is not None:
            result[column] = row["value"]
    return result


def latest_nutrition_settings(conn: sqlite3.Connection, athlete_id: str) -> dict[str, object]:
    """Derive each current nutrition constraint from the latest row that states it."""
    result: dict[str, object] = {}
    for column in NUTRITION_COLUMNS:
        row = conn.execute(
            f"""
            SELECT {column} AS value FROM entries
            WHERE athlete_id = ? AND {column} IS NOT NULL
            ORDER BY session_date DESC, id DESC LIMIT 1
            """,
            (athlete_id,),
        ).fetchone()
        if row is not None:
            result[column] = row["value"]
    return result


def active_supplements(conn: sqlite3.Connection, athlete_id: str) -> list[Entry]:
    """Latest configured row for every active supplement, ordered by name."""
    rows = conn.execute(
        """
        SELECT e.* FROM entries e
        JOIN (
            SELECT supplement_name, MAX(id) AS latest_id
            FROM entries
            WHERE athlete_id = ? AND supplement_dose IS NOT NULL
            GROUP BY supplement_name
        ) latest ON latest.latest_id = e.id
        WHERE e.supplement_active = 1
        ORDER BY e.supplement_name
        """,
        (athlete_id,),
    ).fetchall()
    return [_row_to_entry(row) for row in rows]


def list_athletes(conn: sqlite3.Connection) -> list[str]:
    """Every athlete who has ever sent anything. The coach's roster."""
    return [
        str(row["athlete_id"])
        for row in conn.execute(
            "SELECT DISTINCT athlete_id FROM entries ORDER BY athlete_id"
        )
    ]


def last_activity(conn: sqlite3.Connection, athlete_id: str) -> str | None:
    """Most recent session_date this athlete recorded anything on.

    Silence is a signal no athlete will ever send you, so it has to be read out
    of the absence of rows.
    """
    row = conn.execute(
        "SELECT MAX(session_date) AS last FROM entries WHERE athlete_id = ?",
        (athlete_id,),
    ).fetchone()
    return None if row is None or row["last"] is None else str(row["last"])


# --- outbound drafts: nothing proactive leaves without a coach seeing it ------


def create_draft(
    conn: sqlite3.Connection,
    athlete_id: str,
    message_kind: str,
    local_date: str,
    body: str,
) -> bool:
    """Queue a message for review. Idempotent: re-drafting never overwrites an
    edit or an approval the coach has already made."""
    evidence_version = latest_evidence_version(conn, athlete_id)
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO outbound_drafts
            (athlete_id, message_kind, local_date, body, original_body,
             status, evidence_version, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            athlete_id, message_kind, local_date, body, body,
            evidence_version,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return cur.rowcount > 0


def draft(
    conn: sqlite3.Connection, athlete_id: str, message_kind: str, local_date: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM outbound_drafts "
        "WHERE athlete_id = ? AND message_kind = ? AND local_date = ?",
        (athlete_id, message_kind, local_date),
    ).fetchone()


def approved_drafts(conn: sqlite3.Connection, message_kind: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM outbound_drafts WHERE status = 'approved' AND message_kind = ? "
            "ORDER BY local_date, athlete_id",
            (message_kind,),
        )
    )


def register_athlete(
    conn: sqlite3.Connection,
    athlete_id: str,
    name: str,
    *,
    on: str,
    bodyweight_kg: float | None = None,
    squat_1rm_kg: float | None = None,
    bench_1rm_kg: float | None = None,
    deadlift_1rm_kg: float | None = None,
    training_days: int | None = None,
    experience: str | None = None,
    injury_note: str | None = None,
    goal_lift: str | None = None,
    goal_target_kg: float | None = None,
    goal_target_date: str | None = None,
    created_by: str = "Coach",
) -> None:
    """Create an athlete before they have texted, so the coach can set the roster up."""
    athlete_id = athlete_id.strip()
    name = name.strip()
    if not athlete_id.startswith("+") or len(athlete_id) < 8:
        raise ValueError("an athlete id must be a phone number in E.164 form, e.g. +919812340001")
    if not name:
        raise ValueError("an athlete needs a name")
    if athlete_id in list_athletes(conn):
        raise ValueError("that athlete is already on the roster")
    numeric = {
        "bodyweight": (bodyweight_kg, 30, 400),
        "squat 1RM": (squat_1rm_kg, 1, 600),
        "bench 1RM": (bench_1rm_kg, 1, 400),
        "deadlift 1RM": (deadlift_1rm_kg, 1, 600),
        "goal target": (goal_target_kg, 1, 700),
    }
    for label, (value, low, high) in numeric.items():
        if value is not None and not low <= float(value) <= high:
            raise ValueError(f"{label} must be between {low} and {high} kg")
    if training_days is not None and not 1 <= int(training_days) <= 7:
        raise ValueError("training frequency must be between 1 and 7 days")
    if experience and experience not in {"novice", "intermediate", "advanced"}:
        raise ValueError("experience must be novice, intermediate, or advanced")
    goal_lift = normalize_lift(goal_lift)
    if goal_lift and goal_lift not in {"squat", "bench press", "deadlift"}:
        raise ValueError("goal lift must be squat, bench press, or deadlift")
    goal_parts = (goal_lift, goal_target_kg, goal_target_date)
    if any(part not in (None, "") for part in goal_parts) and not all(
        part not in (None, "") for part in goal_parts
    ):
        raise ValueError("a goal needs a lift, target weight, and target date")
    if goal_target_date:
        try:
            date.fromisoformat(goal_target_date)
        except ValueError as exc:
            raise ValueError("goal date must be a valid date") from exc

    note = (injury_note or "").strip() or None
    insert_entry(
        conn,
        Entry(
            athlete_id=athlete_id,
            athlete_name=name,
            kind="status",
            injured=True if note else None,
            injury_note=note,
            bodyweight_kg=bodyweight_kg,
            experience=experience,
            days_per_week=training_days,
            meet_date=goal_target_date,
            session_date=on,
        ),
    )
    conn.execute(
        """
        INSERT INTO athlete_profile_revisions
            (athlete_id, bodyweight_kg, squat_1rm_kg, bench_1rm_kg,
             deadlift_1rm_kg, training_days, experience, goal_lift,
             goal_target_kg, goal_start_date, goal_target_date, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            athlete_id, bodyweight_kg, squat_1rm_kg, bench_1rm_kg,
            deadlift_1rm_kg, training_days, experience, goal_lift,
            goal_target_kg, on, goal_target_date, (created_by or "Coach").strip(),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def latest_athlete_profile(
    conn: sqlite3.Connection, athlete_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM athlete_profile_revisions WHERE athlete_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (athlete_id,),
    ).fetchone()


def pending_drafts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM outbound_drafts WHERE status = 'pending' "
            "ORDER BY local_date, athlete_id"
        )
    )


def approved_drafts_with_prefix(
    conn: sqlite3.Connection, message_kind_prefix: str
) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM outbound_drafts WHERE status = 'approved' "
            "AND message_kind LIKE ? ORDER BY local_date, athlete_id",
            (message_kind_prefix + "%",),
        )
    )


def latest_evidence_version(conn: sqlite3.Connection, athlete_id: str) -> int:
    """Monotonic version of the facts used to prepare an athlete's draft."""
    row = conn.execute(
        "SELECT COALESCE(MAX(id), 0) AS version FROM entries WHERE athlete_id = ?",
        (athlete_id,),
    ).fetchone()
    return int(row["version"] if row is not None else 0)


def draft_is_bulk_eligible(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Only untouched morning prompts over unchanged evidence may be bulk approved."""
    return (
        str(row["status"]) == "pending"
        and str(row["message_kind"]) == "morning_checkin"
        and str(row["body"]).strip() == str(row["original_body"]).strip()
        and int(row["evidence_version"] or 0)
        == latest_evidence_version(conn, str(row["athlete_id"]))
    )


def bulk_approve_unchanged(conn: sqlite3.Connection, *, reviewed_by: str) -> int:
    """Approve only low-risk, untouched drafts whose supporting facts did not move."""
    reviewed_by = (reviewed_by or "").strip()
    if not reviewed_by:
        raise ValueError("a review must record who made it")
    eligible = [row for row in pending_drafts(conn) if draft_is_bulk_eligible(conn, row)]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for row in eligible:
        conn.execute(
            """
            UPDATE outbound_drafts
               SET status = 'approved', reviewed_by = ?, reviewed_at = ?
             WHERE athlete_id = ? AND message_kind = ? AND local_date = ?
               AND status = 'pending'
            """,
            (
                reviewed_by,
                now,
                str(row["athlete_id"]),
                str(row["message_kind"]),
                str(row["local_date"]),
            ),
        )
    conn.commit()
    return len(eligible)


# --- WhatsApp conversation ledger -------------------------------------------


def record_whatsapp_message(
    conn: sqlite3.Connection,
    *,
    athlete_id: str,
    direction: str,
    body: str,
    status: str,
    provider_sid: str | None = None,
    message_kind: str = "general",
    occurred_at: str | None = None,
    scheduled_for: str | None = None,
    reply_to_sid: str | None = None,
) -> int:
    """Append a transport event once; Twilio retries are idempotent by MessageSid."""
    if direction not in {"inbound", "outbound"}:
        raise ValueError("message direction must be inbound or outbound")
    if status not in {"received", "queued", "sent", "delivered", "read", "failed"}:
        raise ValueError("unsupported WhatsApp message status")
    body = (body or "").strip()
    if not body:
        raise ValueError("a WhatsApp message cannot be empty")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if provider_sid:
        existing = conn.execute(
            "SELECT id FROM whatsapp_messages WHERE provider_sid = ?", (provider_sid,)
        ).fetchone()
        if existing is not None:
            return int(existing["id"])
    cur = conn.execute(
        """
        INSERT INTO whatsapp_messages
            (athlete_id, provider_sid, direction, body, message_kind, status,
             occurred_at, scheduled_for, reply_to_sid, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            athlete_id, provider_sid or None, direction, body, message_kind, status,
            occurred_at or now, scheduled_for, reply_to_sid, now,
        ),
    )
    if direction == "inbound":
        conn.execute(
            """
            INSERT INTO whatsapp_conversation_state
                (athlete_id, work_state, last_read_message_id, updated_at)
            VALUES (?, 'needs_coach', 0, ?)
            ON CONFLICT(athlete_id) DO UPDATE SET
                work_state = 'needs_coach', updated_at = excluded.updated_at
            """,
            (athlete_id, now),
        )
    conn.commit()
    return int(cur.lastrowid)


def whatsapp_messages(
    conn: sqlite3.Connection, athlete_id: str | None = None, *, limit: int = 200
) -> list[sqlite3.Row]:
    limit = max(1, min(int(limit), 500))
    if athlete_id:
        return list(
            conn.execute(
                "SELECT * FROM whatsapp_messages WHERE athlete_id = ? "
                "ORDER BY occurred_at DESC, id DESC LIMIT ?",
                (athlete_id, limit),
            )
        )
    return list(
        conn.execute(
            "SELECT * FROM whatsapp_messages ORDER BY occurred_at DESC, id DESC LIMIT ?",
            (limit,),
        )
    )


def whatsapp_message_by_sid(
    conn: sqlite3.Connection, provider_sid: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM whatsapp_messages WHERE provider_sid = ?", (provider_sid,)
    ).fetchone()


def whatsapp_reply_to(
    conn: sqlite3.Connection, provider_sid: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM whatsapp_messages WHERE reply_to_sid = ? "
        "AND direction = 'outbound' ORDER BY id DESC LIMIT 1",
        (provider_sid,),
    ).fetchone()


def attach_whatsapp_reply_sid(
    conn: sqlite3.Connection, reply_to_sid: str, provider_sid: str
) -> bool:
    """Attach a REST-send UUID to the receipt created while handling inbound.

    Vonage receives a webhook and sends the acknowledgement through a separate
    API request. Linking both IDs keeps retries idempotent and status callbacks
    attached to the exact conversation event.
    """
    if not reply_to_sid or not provider_sid:
        return False
    existing = whatsapp_message_by_sid(conn, provider_sid)
    if existing is not None:
        return True
    row = conn.execute(
        "SELECT id FROM whatsapp_messages WHERE reply_to_sid = ? "
        "AND direction = 'outbound' ORDER BY id DESC LIMIT 1",
        (reply_to_sid,),
    ).fetchone()
    if row is None:
        return False
    conn.execute(
        "UPDATE whatsapp_messages SET provider_sid = ?, status = 'sent' WHERE id = ?",
        (provider_sid, int(row["id"])),
    )
    conn.commit()
    return True


def whatsapp_conversations(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Latest message per athlete, ordered as a working inbox."""
    return list(
        conn.execute(
            """
            SELECT m.*,
                   COALESCE(
                     (SELECT e.athlete_name FROM entries e
                       WHERE e.athlete_id = m.athlete_id AND e.athlete_name IS NOT NULL
                       ORDER BY e.id DESC LIMIT 1),
                     m.athlete_id
                   ) AS athlete_name,
                   COALESCE(s.work_state, 'resolved') AS work_state,
                   (SELECT COUNT(*) FROM whatsapp_messages unread
                     WHERE unread.athlete_id = m.athlete_id
                       AND unread.direction = 'inbound'
                       AND unread.id > COALESCE(s.last_read_message_id, 0)) AS unread_count
              FROM whatsapp_messages m
            JOIN (
                SELECT athlete_id, MAX(id) AS latest_id
                FROM whatsapp_messages GROUP BY athlete_id
            ) latest ON latest.latest_id = m.id
            LEFT JOIN whatsapp_conversation_state s ON s.athlete_id = m.athlete_id
            ORDER BY CASE WHEN (SELECT COUNT(*) FROM whatsapp_messages unread
                                  WHERE unread.athlete_id = m.athlete_id
                                    AND unread.direction = 'inbound'
                                    AND unread.id > COALESCE(s.last_read_message_id, 0)) > 0
                          THEN 0 ELSE 1 END,
                     m.occurred_at DESC, m.id DESC
            """
        )
    )


def mark_whatsapp_conversation_reviewed(
    conn: sqlite3.Connection, athlete_id: str
) -> int:
    """A coach explicitly clears the unread feedback marker for one athlete."""
    row = conn.execute(
        "SELECT COALESCE(MAX(id), 0) AS latest FROM whatsapp_messages "
        "WHERE athlete_id = ? AND direction = 'inbound'",
        (athlete_id,),
    ).fetchone()
    latest = int(row["latest"] if row is not None else 0)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO whatsapp_conversation_state
            (athlete_id, work_state, last_read_message_id, updated_at)
        VALUES (?, 'resolved', ?, ?)
        ON CONFLICT(athlete_id) DO UPDATE SET
            work_state = 'resolved', last_read_message_id = excluded.last_read_message_id,
            updated_at = excluded.updated_at
        """,
        (athlete_id, latest, now),
    )
    conn.commit()
    return latest


def update_whatsapp_status(
    conn: sqlite3.Connection,
    provider_sid: str,
    status: str,
    *,
    error_code: str | None = None,
) -> bool:
    if status not in {"queued", "sent", "delivered", "read", "failed"}:
        return False
    cur = conn.execute(
        "UPDATE whatsapp_messages SET status = ?, error_code = ? WHERE provider_sid = ?",
        (status, error_code or None, provider_sid),
    )
    conn.commit()
    return cur.rowcount > 0


def review_draft(
    conn: sqlite3.Connection,
    athlete_id: str,
    message_kind: str,
    local_date: str,
    *,
    status: str,
    reviewed_by: str,
    body: str | None = None,
) -> None:
    """Approve (optionally with the coach's own wording) or skip a draft."""
    if status not in {"approved", "skipped"}:
        raise ValueError("a review is either 'approved' or 'skipped'")
    reviewed_by = (reviewed_by or "").strip()
    if not reviewed_by:
        raise ValueError("a review must record who made it")
    row = draft(conn, athlete_id, message_kind, local_date)
    if row is None:
        raise ValueError("no such draft")
    if status == "approved" and not (body or str(row["body"])).strip():
        raise ValueError("an approved message cannot be empty")
    conn.execute(
        """
        UPDATE outbound_drafts
           SET status = ?, body = ?, reviewed_by = ?, reviewed_at = ?,
               evidence_version = ?
         WHERE athlete_id = ? AND message_kind = ? AND local_date = ?
        """,
        (
            status,
            (body if body is not None else str(row["body"])).strip(),
            reviewed_by,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            latest_evidence_version(conn, athlete_id),
            athlete_id, message_kind, local_date,
        ),
    )
    conn.commit()


def invalidate_draft_if_evidence_changed(
    conn: sqlite3.Connection, athlete_id: str, message_kind: str, local_date: str
) -> bool:
    """Return an approved agent draft to review when newer athlete facts arrive."""
    row = draft(conn, athlete_id, message_kind, local_date)
    if row is None or str(row["status"]) != "approved":
        return False
    if int(row["evidence_version"] or 0) == latest_evidence_version(conn, athlete_id):
        return False
    conn.execute(
        """
        UPDATE outbound_drafts
           SET status = 'pending', reviewed_by = NULL, reviewed_at = NULL
         WHERE athlete_id = ? AND message_kind = ? AND local_date = ?
        """,
        (athlete_id, message_kind, local_date),
    )
    conn.commit()
    return True


def mark_draft_sent(
    conn: sqlite3.Connection, athlete_id: str, message_kind: str, local_date: str
) -> None:
    conn.execute(
        "UPDATE outbound_drafts SET status = 'sent' "
        "WHERE athlete_id = ? AND message_kind = ? AND local_date = ?",
        (athlete_id, message_kind, local_date),
    )
    conn.commit()


def list_scheduled_athletes(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT athlete_id FROM entries
        WHERE morning_checkin_time IS NOT NULL
        ORDER BY athlete_id
        """
    ).fetchall()
    return [str(row["athlete_id"]) for row in rows]


def scheduled_delivery_exists(
    conn: sqlite3.Connection, athlete_id: str, message_kind: str, local_date: str
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM scheduled_deliveries
        WHERE athlete_id = ? AND message_kind = ? AND local_date = ?
        """,
        (athlete_id, message_kind, local_date),
    ).fetchone()
    return row is not None


def mark_scheduled_delivery(
    conn: sqlite3.Connection, athlete_id: str, message_kind: str, local_date: str
) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO scheduled_deliveries
            (athlete_id, message_kind, local_date, sent_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            athlete_id,
            message_kind,
            local_date,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def rpe_logging_ratio(conn: sqlite3.Connection, athlete_id: str, limit: int = 20) -> float:
    """Fraction of recent set rows with an explicit RPE."""
    rows = conn.execute(
        """
        SELECT rpe FROM entries
        WHERE athlete_id = ? AND kind = 'set'
        ORDER BY session_date DESC, id DESC LIMIT ?
        """,
        (athlete_id, limit),
    ).fetchall()
    return sum(row["rpe"] is not None for row in rows) / len(rows) if rows else 0.0


def iter_all(conn: sqlite3.Connection) -> Iterator[Entry]:
    for row in conn.execute("SELECT * FROM entries ORDER BY id"):
        yield _row_to_entry(row)


# External OAuth tokens are encrypted before they reach these functions.  Calendar
# event contents are deliberately not persisted; only athlete-approved workout
# proposals and opaque provider event IDs are stored.


def save_oauth_connection(
    conn: sqlite3.Connection,
    *,
    athlete_id: str,
    provider: str,
    access_token: str,
    refresh_token: str | None,
    expires_at: str | None,
    scopes: str,
) -> None:
    existing = oauth_connection(conn, athlete_id, provider)
    retained_refresh = refresh_token or (str(existing["refresh_token"]) if existing else None)
    conn.execute(
        """
        INSERT INTO oauth_connections
            (athlete_id, provider, access_token, refresh_token, expires_at, scopes, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(athlete_id, provider) DO UPDATE SET
            access_token = excluded.access_token,
            refresh_token = excluded.refresh_token,
            expires_at = excluded.expires_at,
            scopes = excluded.scopes,
            updated_at = excluded.updated_at
        """,
        (
            athlete_id,
            provider,
            access_token,
            retained_refresh,
            expires_at,
            scopes,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def oauth_connection(
    conn: sqlite3.Connection, athlete_id: str, provider: str = "google_calendar"
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM oauth_connections WHERE athlete_id = ? AND provider = ?",
        (athlete_id, provider),
    ).fetchone()


def update_oauth_calendar_id(
    conn: sqlite3.Connection, athlete_id: str, calendar_id: str
) -> None:
    conn.execute(
        """
        UPDATE oauth_connections SET provider_calendar_id = ?, updated_at = ?
        WHERE athlete_id = ? AND provider = 'google_calendar'
        """,
        (
            calendar_id,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            athlete_id,
        ),
    )
    conn.commit()


def delete_oauth_connection(
    conn: sqlite3.Connection, athlete_id: str, provider: str = "google_calendar"
) -> None:
    conn.execute(
        "DELETE FROM oauth_connections WHERE athlete_id = ? AND provider = ?",
        (athlete_id, provider),
    )
    conn.commit()


def save_place(conn: sqlite3.Connection, athlete_id: str, label: str, location: str) -> None:
    if not settings.calendar_token_encryption_key:
        raise RuntimeError(
            "Saved locations are disabled until CALENDAR_TOKEN_ENCRYPTION_KEY is configured"
        )
    stored_location = "fernet:" + SecretCipher(
        settings.calendar_token_encryption_key
    ).encrypt(location.strip())
    conn.execute(
        """
        INSERT INTO saved_places (athlete_id, label, location, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(athlete_id, label) DO UPDATE SET
            location = excluded.location, updated_at = excluded.updated_at
        """,
        (
            athlete_id,
            label.strip().lower(),
            stored_location,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def saved_places(conn: sqlite3.Connection, athlete_id: str) -> dict[str, str]:
    rows = conn.execute(
        "SELECT label, location FROM saved_places WHERE athlete_id = ? ORDER BY label",
        (athlete_id,),
    ).fetchall()
    if rows and not settings.calendar_token_encryption_key:
        raise RuntimeError(
            "Saved locations cannot be read until CALENDAR_TOKEN_ENCRYPTION_KEY is configured"
        )
    cipher = (
        SecretCipher(settings.calendar_token_encryption_key)
        if settings.calendar_token_encryption_key
        else None
    )
    result: dict[str, str] = {}
    for row in rows:
        value = str(row["location"])
        if value.startswith("fernet:"):
            value = cipher.decrypt(value.removeprefix("fernet:"))
        elif cipher is not None:
            # One-time migration for places written by the earlier fail-open version.
            plaintext = value
            encrypted = "fernet:" + cipher.encrypt(plaintext)
            conn.execute(
                """
                UPDATE saved_places SET location = ?, updated_at = ?
                WHERE athlete_id = ? AND label = ?
                """,
                (
                    encrypted,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    athlete_id,
                    str(row["label"]),
                ),
            )
            value = plaintext
        result[str(row["label"])] = value
    conn.commit()
    return result


def delete_saved_places(conn: sqlite3.Connection, athlete_id: str) -> None:
    conn.execute("DELETE FROM saved_places WHERE athlete_id = ?", (athlete_id,))
    conn.commit()


def save_scheduling_preferences(
    conn: sqlite3.Connection,
    athlete_id: str,
    **updates: object,
) -> None:
    allowed = {
        "preferred_start",
        "preferred_end",
        "session_minutes",
        "pre_buffer_minutes",
        "post_buffer_minutes",
        "unknown_location_buffer_minutes",
        "bedtime_buffer_minutes",
        "travel_mode",
        "default_location_label",
    }
    current = scheduling_preferences(conn, athlete_id)
    values = {
        "preferred_start": "06:00",
        "preferred_end": "21:00",
        "session_minutes": 90,
        "pre_buffer_minutes": 15,
        "post_buffer_minutes": 30,
        "unknown_location_buffer_minutes": 30,
        "bedtime_buffer_minutes": 90,
        "travel_mode": "DRIVE",
        "default_location_label": None,
        **current,
        **{key: value for key, value in updates.items() if key in allowed and value is not None},
    }
    conn.execute(
        """
        INSERT INTO scheduling_preferences
            (athlete_id, preferred_start, preferred_end, session_minutes,
             pre_buffer_minutes, post_buffer_minutes, unknown_location_buffer_minutes,
             bedtime_buffer_minutes, travel_mode, default_location_label, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(athlete_id) DO UPDATE SET
            preferred_start = excluded.preferred_start,
            preferred_end = excluded.preferred_end,
            session_minutes = excluded.session_minutes,
            pre_buffer_minutes = excluded.pre_buffer_minutes,
            post_buffer_minutes = excluded.post_buffer_minutes,
            unknown_location_buffer_minutes = excluded.unknown_location_buffer_minutes,
            bedtime_buffer_minutes = excluded.bedtime_buffer_minutes,
            travel_mode = excluded.travel_mode,
            default_location_label = excluded.default_location_label,
            updated_at = excluded.updated_at
        """,
        (
            athlete_id,
            values["preferred_start"],
            values["preferred_end"],
            values["session_minutes"],
            values["pre_buffer_minutes"],
            values["post_buffer_minutes"],
            values["unknown_location_buffer_minutes"],
            values["bedtime_buffer_minutes"],
            values["travel_mode"],
            values["default_location_label"],
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def scheduling_preferences(conn: sqlite3.Connection, athlete_id: str) -> dict[str, object]:
    row = conn.execute(
        "SELECT * FROM scheduling_preferences WHERE athlete_id = ?", (athlete_id,)
    ).fetchone()
    if row is None:
        return {}
    return {
        key: row[key]
        for key in (
            "preferred_start",
            "preferred_end",
            "session_minutes",
            "pre_buffer_minutes",
            "post_buffer_minutes",
            "unknown_location_buffer_minutes",
            "bedtime_buffer_minutes",
            "travel_mode",
            "default_location_label",
        )
    }


def create_schedule_proposal(
    conn: sqlite3.Connection,
    *,
    proposal_id: str,
    athlete_id: str,
    local_date: str,
    starts_at: str,
    ends_at: str,
    gym_label: str,
    lift: str | None,
    reasons: str,
) -> None:
    conn.execute(
        """
        INSERT INTO schedule_proposals
            (id, athlete_id, local_date, starts_at, ends_at, gym_label, lift,
             status, reasons, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            proposal_id,
            athlete_id,
            local_date,
            starts_at,
            ends_at,
            gym_label,
            lift,
            reasons,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def schedule_proposal(
    conn: sqlite3.Connection, athlete_id: str, proposal_id: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM schedule_proposals WHERE athlete_id = ? AND id = ?",
        (athlete_id, proposal_id.upper()),
    ).fetchone()


def confirmed_schedule_for_date(
    conn: sqlite3.Connection, athlete_id: str, local_date: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT * FROM schedule_proposals
        WHERE athlete_id = ? AND local_date = ? AND status = 'confirmed'
          AND calendar_event_id IS NOT NULL
        ORDER BY confirmed_at DESC LIMIT 1
        """,
        (athlete_id, local_date),
    ).fetchone()


def confirm_schedule_proposal(
    conn: sqlite3.Connection, athlete_id: str, proposal_id: str, event_id: str
) -> None:
    row = schedule_proposal(conn, athlete_id, proposal_id)
    if row is not None:
        conn.execute(
            """
            UPDATE schedule_proposals SET status = 'superseded'
            WHERE athlete_id = ? AND local_date = ? AND status = 'confirmed'
              AND id <> ?
            """,
            (athlete_id, row["local_date"], proposal_id.upper()),
        )
        conn.execute(
            """
            UPDATE schedule_proposals SET status = 'cancelled'
            WHERE athlete_id = ? AND local_date = ? AND status = 'pending'
              AND id <> ?
            """,
            (athlete_id, row["local_date"], proposal_id.upper()),
        )
    conn.execute(
        """
        UPDATE schedule_proposals
        SET status = 'confirmed', calendar_event_id = ?, confirmed_at = ?
        WHERE athlete_id = ? AND id = ? AND status = 'pending'
        """,
        (
            event_id,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            athlete_id,
            proposal_id.upper(),
        ),
    )
    conn.commit()
