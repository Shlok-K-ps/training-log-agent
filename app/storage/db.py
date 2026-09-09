"""SQLite storage: one file, one table.

Why SQLite: the data is small, structured, and single-writer. A 20-athlete team
generates a few thousand rows a year. Postgres solves concurrency problems this
project does not have, at the cost of a server to run and a connection string to
keep secret. One file that you can copy, diff, and open in any client is worth
more here than horizontal scale that will never be used.

Why one table: every row is one observation about one athlete at one point in
time. Sets carry a lift; status updates (phase change, injury) carry none. Both
are facts on a timeline, so both live on the same timeline. State — "what phase
is Priya in right now?" — is derived by reading the latest row, never stored
separately, so it can never drift out of sync with the log.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Literal

from app.config import settings
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
"""

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
    for name, column_type in (CHECKIN_COLUMNS | PROGRAM_COLUMNS | SCHEDULE_COLUMNS).items():
        if name not in existing:
            conn.execute(f"ALTER TABLE entries ADD COLUMN {name} {column_type}")
    conn.commit()


def insert_entry(conn: sqlite3.Connection, entry: Entry) -> int:
    e = entry.with_defaults()
    cur = conn.execute(
        """
        INSERT INTO entries (
            athlete_id, athlete_name, kind, lift, sets, reps, weight_kg, rpe,
            phase, injured, injury_note, sleep_hours, sleep_quality, readiness,
            soreness, stress, bodyweight_kg, protein_g, calories,
            nutrition_adherence, nap_minutes, planned_lift, planned_training_time,
            methodology, experience, days_per_week, meet_date,
            has_specialty_equipment, timezone, morning_checkin_time, training_time,
            bedtime, nap_window_start, nap_window_end, session_date, raw_text, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
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
            e.session_date,
            e.raw_text,
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
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
    """(is_injured, note) from the most recent row that recorded injury status."""
    row = conn.execute(
        """
        SELECT injured, injury_note FROM entries
        WHERE athlete_id = ? AND injured IS NOT NULL
        ORDER BY session_date DESC, id DESC
        LIMIT 1
        """,
        (athlete_id,),
    ).fetchone()
    if row is None:
        return False, None
    return bool(row["injured"]), row["injury_note"]


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
