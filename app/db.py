from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from app.config import Settings


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    schedule_label TEXT,
    role TEXT NOT NULL CHECK (role IN ('admin', 'teacher')),
    password_hash TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS timetable_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 4),
    period INTEGER NOT NULL CHECK (period BETWEEN 1 AND 7),
    slot_type TEXT NOT NULL CHECK (slot_type IN ('class', 'travel')),
    class_code TEXT,
    subject TEXT,
    location_label TEXT,
    duration INTEGER NOT NULL DEFAULT 1,
    source_text TEXT NOT NULL,
    UNIQUE (teacher_id, weekday, period)
);

CREATE TABLE IF NOT EXISTS calendar_days (
    date TEXT PRIMARY KEY,
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    is_school_day INTEGER NOT NULL,
    kind TEXT NOT NULL,
    label TEXT
);

CREATE TABLE IF NOT EXISTS swap_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    responder_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    source_teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    target_teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    source_date TEXT NOT NULL,
    target_date TEXT NOT NULL,
    source_weekday INTEGER NOT NULL CHECK (source_weekday BETWEEN 0 AND 4),
    target_weekday INTEGER NOT NULL CHECK (target_weekday BETWEEN 0 AND 4),
    source_period INTEGER NOT NULL CHECK (source_period BETWEEN 1 AND 7),
    target_period INTEGER NOT NULL CHECK (target_period BETWEEN 1 AND 7),
    source_class_code TEXT NOT NULL,
    target_class_code TEXT NOT NULL,
    source_subject TEXT NOT NULL,
    target_subject TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected', 'expired', 'cancelled')),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    responded_at TEXT,
    cancelled_at TEXT,
    response_note TEXT,
    requester_hidden INTEGER NOT NULL DEFAULT 0,
    responder_hidden INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS coverage_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    responder_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    class_date TEXT NOT NULL,
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 4),
    period INTEGER NOT NULL CHECK (period BETWEEN 1 AND 7),
    class_code TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected', 'expired', 'cancelled')),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    responded_at TEXT,
    response_note TEXT,
    requester_hidden INTEGER NOT NULL DEFAULT 0,
    responder_hidden INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS swap_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    swap_request_id INTEGER NOT NULL REFERENCES swap_requests(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    actor_id INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_timetable_slots_lookup
    ON timetable_slots (teacher_id, weekday, period);
CREATE INDEX IF NOT EXISTS idx_swap_requests_status
    ON swap_requests (status, source_date, target_date);
CREATE INDEX IF NOT EXISTS idx_coverage_requests_status
    ON coverage_requests (status, class_date, period);
CREATE INDEX IF NOT EXISTS idx_notifications_teacher
    ON notifications (teacher_id, is_read, created_at);
"""


def connect_db(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def db_session(settings: Settings) -> Iterator[sqlite3.Connection]:
    connection = connect_db(settings.database_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(settings: Settings) -> None:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    settings.preview_dir.mkdir(parents=True, exist_ok=True)
    connection = connect_db(settings.database_path)
    try:
        connection.executescript(SCHEMA)
        _ensure_column(connection, "swap_requests", "requester_hidden", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "swap_requests", "responder_hidden", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "coverage_requests", "requester_hidden", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(connection, "coverage_requests", "responder_hidden", "INTEGER NOT NULL DEFAULT 0")
        connection.commit()
    finally:
        connection.close()


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
