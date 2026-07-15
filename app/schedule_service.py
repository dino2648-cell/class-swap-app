from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
import json
import sqlite3
from typing import Any

from fastapi import HTTPException

from app.config import Settings
from app.security import hash_password, validate_password_strength, verify_password


DAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
DAY_PERIOD_LIMITS = {0: 7, 1: 7, 2: 7, 3: 7, 4: 6}
ACTIVE_SWAP_STATUSES = {"pending", "accepted"}
ACTIVE_COVERAGE_STATUSES = {"pending", "accepted"}


def now_local() -> datetime:
    return datetime.now().replace(microsecond=0)


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="날짜는 YYYY-MM-DD 형식이어야 합니다.") from exc


def format_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def row_bool(row: sqlite3.Row, key: str) -> bool:
    return bool(row[key]) if key in row.keys() and row[key] is not None else False


def seed_default_admin(connection: sqlite3.Connection, settings: Settings) -> None:
    existing = connection.execute(
        "SELECT id FROM teachers WHERE username = ?",
        (settings.default_admin_username,),
    ).fetchone()
    if existing:
        return
    timestamp = format_dt(now_local())
    connection.execute(
        """
        INSERT INTO teachers (
            username, display_name, schedule_label, role, password_hash,
            must_change_password, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, 'admin', ?, 1, 1, ?, ?)
        """,
        (
            settings.default_admin_username,
            "관리자",
            "관리자",
            hash_password(settings.default_admin_password),
            timestamp,
            timestamp,
        ),
    )


def get_setting(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(connection: sqlite3.Connection, key: str, value: str) -> None:
    timestamp = format_dt(now_local())
    connection.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (key, value, timestamp),
    )


def get_user_by_id(connection: sqlite3.Connection, user_id: int) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM teachers WHERE id = ? AND is_active = 1",
        (user_id,),
    ).fetchone()


def get_user_by_username(connection: sqlite3.Connection, username: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM teachers WHERE username = ? AND is_active = 1",
        (username,),
    ).fetchone()


def serialize_user(user: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "schedule_label": user["schedule_label"],
        "role": user["role"],
        "must_change_password": bool(user["must_change_password"]),
    }


def login_user(connection: sqlite3.Connection, username: str, password: str) -> dict[str, Any]:
    user = get_user_by_username(connection, username)
    if not user or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    return serialize_user(user)


def change_password(
    connection: sqlite3.Connection,
    user_id: int,
    current_password: str,
    new_password: str,
) -> dict[str, Any]:
    user = get_user_by_id(connection, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾지 못했습니다.")
    if not verify_password(current_password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 일치하지 않습니다.")
    validate_password_strength(new_password)
    timestamp = format_dt(now_local())
    connection.execute(
        """
        UPDATE teachers
        SET password_hash = ?, must_change_password = 0, updated_at = ?
        WHERE id = ?
        """,
        (hash_password(new_password), timestamp, user_id),
    )
    return serialize_user(get_user_by_id(connection, user_id))


def create_notification(
    connection: sqlite3.Connection,
    teacher_id: int,
    category: str,
    title: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO notifications (teacher_id, category, title, message, payload_json, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (
            teacher_id,
            category,
            title,
            message,
            json.dumps(payload, ensure_ascii=False) if payload is not None else None,
            format_dt(now_local()),
        ),
    )


def add_swap_history(
    connection: sqlite3.Connection,
    swap_request_id: int,
    action: str,
    actor_id: int | None,
    details: dict[str, Any],
) -> None:
    connection.execute(
        """
        INSERT INTO swap_history (swap_request_id, action, actor_id, created_at, details_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            swap_request_id,
            action,
            actor_id,
            format_dt(now_local()),
            json.dumps(details, ensure_ascii=False),
        ),
    )


def get_calendar_settings(connection: sqlite3.Connection) -> dict[str, Any]:
    semester_start = get_setting(connection, "semester_start")
    semester_end = get_setting(connection, "semester_end")
    special_rows = connection.execute(
        """
        SELECT date, label, kind
        FROM calendar_days
        WHERE kind IN ('holiday', 'closure')
        ORDER BY date
        """
    ).fetchall()
    return {
        "semester_start": semester_start,
        "semester_end": semester_end,
        "special_days": [dict(row) for row in special_rows],
    }


def update_calendar_settings(
    connection: sqlite3.Connection,
    semester_start_raw: str,
    semester_end_raw: str,
    special_days: list[dict[str, Any]],
) -> dict[str, Any]:
    semester_start = parse_date(semester_start_raw)
    semester_end = parse_date(semester_end_raw)
    if semester_end < semester_start:
        raise HTTPException(status_code=400, detail="학기 종료일은 시작일 이후여야 합니다.")

    special_map: dict[str, dict[str, str]] = {}
    for item in special_days:
        special_date = parse_date(item["date"])
        if special_date < semester_start or special_date > semester_end:
            raise HTTPException(status_code=400, detail="휴업일은 학기 범위 안에 있어야 합니다.")
        special_map[item["date"]] = {
            "label": item["label"],
            "kind": item["kind"],
        }

    connection.execute("DELETE FROM calendar_days")
    current = semester_start
    while current <= semester_end:
        iso_date = current.isoformat()
        weekday = current.weekday()
        if iso_date in special_map:
            kind = special_map[iso_date]["kind"]
            label = special_map[iso_date]["label"]
            is_school_day = 0
        elif weekday >= 5:
            kind = "weekend"
            label = "주말"
            is_school_day = 0
        else:
            kind = "school_day"
            label = ""
            is_school_day = 1
        connection.execute(
            """
            INSERT INTO calendar_days (date, weekday, is_school_day, kind, label)
            VALUES (?, ?, ?, ?, ?)
            """,
            (iso_date, weekday, is_school_day, kind, label),
        )
        current += timedelta(days=1)

    set_setting(connection, "semester_start", semester_start.isoformat())
    set_setting(connection, "semester_end", semester_end.isoformat())
    return get_calendar_settings(connection)


def list_teachers(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            t.*,
            COUNT(ts.id) AS slot_count,
            SUM(CASE WHEN ts.slot_type = 'class' THEN 1 ELSE 0 END) AS class_slot_count,
            SUM(CASE WHEN ts.slot_type = 'travel' THEN 1 ELSE 0 END) AS travel_slot_count
        FROM teachers t
        LEFT JOIN timetable_slots ts ON ts.teacher_id = t.id
        WHERE t.is_active = 1
        GROUP BY t.id
        ORDER BY CASE WHEN t.role = 'admin' THEN 0 ELSE 1 END, t.display_name
        """
    ).fetchall()
    return [
        {
            **serialize_user(row),
            "slot_count": row["slot_count"],
            "class_slot_count": row["class_slot_count"] or 0,
            "travel_slot_count": row["travel_slot_count"] or 0,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def _serialize_admin_timetable_slot(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "teacher_id": row["teacher_id"],
        "teacher_name": row["teacher_name"],
        "weekday": row["weekday"],
        "day_label": DAY_LABELS[row["weekday"]],
        "period": row["period"],
        "slot_type": row["slot_type"],
        "class_code": row["class_code"] or "",
        "subject": row["subject"] or "",
        "location_label": row["location_label"] or "",
        "duration": row["duration"],
        "source_text": row["source_text"],
    }


def list_admin_timetable_slots(
    connection: sqlite3.Connection,
    teacher_id: int | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    where = "WHERE t.is_active = 1"
    if teacher_id is not None:
        teacher = get_user_by_id(connection, teacher_id)
        if not teacher:
            raise HTTPException(status_code=404, detail="교사를 찾지 못했습니다.")
        where += " AND ts.teacher_id = ?"
        params.append(teacher_id)
    rows = connection.execute(
        f"""
        SELECT
            ts.*,
            t.display_name AS teacher_name
        FROM timetable_slots ts
        JOIN teachers t ON t.id = ts.teacher_id
        {where}
        ORDER BY t.display_name, ts.weekday, ts.period
        """,
        params,
    ).fetchall()
    return {"slots": [_serialize_admin_timetable_slot(row) for row in rows]}


def _validate_timetable_slot_payload(
    connection: sqlite3.Connection,
    teacher_id: int,
    weekday: int,
    period: int,
    slot_type: str,
    class_code: str,
    subject: str,
    location_label: str,
    existing_slot_id: int | None = None,
) -> dict[str, Any]:
    teacher = get_user_by_id(connection, teacher_id)
    if not teacher or teacher["role"] != "teacher":
        raise HTTPException(status_code=404, detail="시간표를 배정할 교사를 찾지 못했습니다.")
    period_limit = DAY_PERIOD_LIMITS.get(weekday)
    if period_limit is None or period > period_limit:
        raise HTTPException(status_code=400, detail=f"{DAY_LABELS[weekday]}요일은 {period_limit}교시까지만 등록할 수 있습니다.")

    duplicate = connection.execute(
        """
        SELECT id
        FROM timetable_slots
        WHERE teacher_id = ?
          AND weekday = ?
          AND period = ?
          AND (? IS NULL OR id != ?)
        """,
        (teacher_id, weekday, period, existing_slot_id, existing_slot_id),
    ).fetchone()
    if duplicate:
        raise HTTPException(status_code=400, detail="해당 교사의 같은 요일·교시에 이미 등록된 수업이 있습니다.")

    cleaned_class_code = class_code.strip()
    cleaned_subject = subject.strip()
    cleaned_location = location_label.strip()

    if slot_type == "class":
        if not cleaned_class_code or not cleaned_subject:
            raise HTTPException(status_code=400, detail="정규 수업은 학반과 과목명을 모두 입력해야 합니다.")
        return {
            "class_code": cleaned_class_code,
            "subject": cleaned_subject,
            "location_label": None,
            "duration": 1,
            "source_text": f"{cleaned_class_code} {cleaned_subject}",
        }

    if not cleaned_location:
        raise HTTPException(status_code=400, detail="순회 일정은 학교명을 입력해야 합니다.")
    return {
        "class_code": None,
        "subject": None,
        "location_label": cleaned_location,
        "duration": 1,
        "source_text": f"{cleaned_location}(1시간)",
    }


def _get_admin_timetable_slot(connection: sqlite3.Connection, slot_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            ts.*,
            t.display_name AS teacher_name
        FROM timetable_slots ts
        JOIN teachers t ON t.id = ts.teacher_id
        WHERE ts.id = ?
        """,
        (slot_id,),
    ).fetchone()


def create_admin_timetable_slot(
    connection: sqlite3.Connection,
    teacher_id: int,
    weekday: int,
    period: int,
    slot_type: str,
    class_code: str,
    subject: str,
    location_label: str,
) -> dict[str, Any]:
    values = _validate_timetable_slot_payload(
        connection,
        teacher_id,
        weekday,
        period,
        slot_type,
        class_code,
        subject,
        location_label,
    )
    connection.execute(
        """
        INSERT INTO timetable_slots (
            teacher_id, weekday, period, slot_type, class_code, subject,
            location_label, duration, source_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            teacher_id,
            weekday,
            period,
            slot_type,
            values["class_code"],
            values["subject"],
            values["location_label"],
            values["duration"],
            values["source_text"],
        ),
    )
    connection.execute("UPDATE teachers SET updated_at = ? WHERE id = ?", (format_dt(now_local()), teacher_id))
    slot_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    return _serialize_admin_timetable_slot(_get_admin_timetable_slot(connection, slot_id))


def update_admin_timetable_slot(
    connection: sqlite3.Connection,
    slot_id: int,
    teacher_id: int,
    weekday: int,
    period: int,
    slot_type: str,
    class_code: str,
    subject: str,
    location_label: str,
) -> dict[str, Any]:
    existing = _get_admin_timetable_slot(connection, slot_id)
    if not existing:
        raise HTTPException(status_code=404, detail="수정할 수업을 찾지 못했습니다.")
    values = _validate_timetable_slot_payload(
        connection,
        teacher_id,
        weekday,
        period,
        slot_type,
        class_code,
        subject,
        location_label,
        slot_id,
    )
    connection.execute(
        """
        UPDATE timetable_slots
        SET teacher_id = ?,
            weekday = ?,
            period = ?,
            slot_type = ?,
            class_code = ?,
            subject = ?,
            location_label = ?,
            duration = ?,
            source_text = ?
        WHERE id = ?
        """,
        (
            teacher_id,
            weekday,
            period,
            slot_type,
            values["class_code"],
            values["subject"],
            values["location_label"],
            values["duration"],
            values["source_text"],
            slot_id,
        ),
    )
    timestamp = format_dt(now_local())
    connection.execute("UPDATE teachers SET updated_at = ? WHERE id IN (?, ?)", (timestamp, existing["teacher_id"], teacher_id))
    return _serialize_admin_timetable_slot(_get_admin_timetable_slot(connection, slot_id))


def delete_admin_timetable_slot(connection: sqlite3.Connection, slot_id: int) -> None:
    existing = _get_admin_timetable_slot(connection, slot_id)
    if not existing:
        raise HTTPException(status_code=404, detail="삭제할 수업을 찾지 못했습니다.")
    connection.execute("DELETE FROM timetable_slots WHERE id = ?", (slot_id,))
    connection.execute("UPDATE teachers SET updated_at = ? WHERE id = ?", (format_dt(now_local()), existing["teacher_id"]))


def create_teacher(
    connection: sqlite3.Connection,
    display_name: str,
    username: str,
    role: str,
    default_password: str,
) -> dict[str, Any]:
    existing = connection.execute(
        "SELECT id FROM teachers WHERE username = ?",
        (username,),
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="이미 사용 중인 아이디입니다.")
    timestamp = format_dt(now_local())
    connection.execute(
        """
        INSERT INTO teachers (
            username, display_name, schedule_label, role, password_hash,
            must_change_password, is_active, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
        """,
        (
            username,
            display_name,
            display_name,
            role,
            hash_password(default_password),
            timestamp,
            timestamp,
        ),
    )
    teacher_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    return serialize_user(get_user_by_id(connection, teacher_id))


def update_teacher_account(
    connection: sqlite3.Connection,
    actor_id: int,
    teacher_id: int,
    display_name: str,
    username: str,
    role: str,
    schedule_label: str,
) -> dict[str, Any]:
    teacher = get_user_by_id(connection, teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="교사를 찾지 못했습니다.")

    username_owner = connection.execute(
        "SELECT id FROM teachers WHERE username = ? AND id != ? AND is_active = 1",
        (username, teacher_id),
    ).fetchone()
    if username_owner:
        raise HTTPException(status_code=400, detail="이미 사용 중인 아이디입니다.")

    if teacher["role"] == "admin" and role != "admin":
        admin_count = connection.execute(
            "SELECT COUNT(*) AS count FROM teachers WHERE role = 'admin' AND is_active = 1"
        ).fetchone()["count"]
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="마지막 관리자 권한은 해제할 수 없습니다.")
        if teacher_id == actor_id:
            raise HTTPException(status_code=400, detail="자기 자신의 관리자 권한은 해제할 수 없습니다.")

    cleaned_schedule_label = schedule_label.strip() or display_name
    timestamp = format_dt(now_local())
    connection.execute(
        """
        UPDATE teachers
        SET display_name = ?,
            username = ?,
            role = ?,
            schedule_label = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            display_name,
            username,
            role,
            cleaned_schedule_label,
            timestamp,
            teacher_id,
        ),
    )
    return serialize_user(get_user_by_id(connection, teacher_id))


def reset_teacher_password(
    connection: sqlite3.Connection,
    teacher_id: int,
    default_password: str,
) -> None:
    teacher = get_user_by_id(connection, teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="교사를 찾지 못했습니다.")
    connection.execute(
        """
        UPDATE teachers
        SET password_hash = ?, must_change_password = 1, updated_at = ?
        WHERE id = ?
        """,
        (hash_password(default_password), format_dt(now_local()), teacher_id),
    )


def delete_teacher(connection: sqlite3.Connection, actor_id: int, teacher_id: int) -> None:
    teacher = get_user_by_id(connection, teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="교사를 찾지 못했습니다.")
    if teacher["id"] == actor_id:
        raise HTTPException(status_code=400, detail="자기 계정은 삭제할 수 없습니다.")
    if teacher["role"] == "admin":
        admin_count = connection.execute(
            "SELECT COUNT(*) AS count FROM teachers WHERE role = 'admin' AND is_active = 1"
        ).fetchone()["count"]
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="마지막 관리자 계정은 삭제할 수 없습니다.")
    connection.execute("DELETE FROM timetable_slots WHERE teacher_id = ?", (teacher_id,))
    connection.execute("UPDATE teachers SET is_active = 0, updated_at = ? WHERE id = ?", (format_dt(now_local()), teacher_id))


def _find_existing_import_teacher(connection: sqlite3.Connection, teacher: dict[str, Any]) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT *
        FROM teachers
        WHERE role = 'teacher'
          AND (schedule_label = ? OR username = ?)
        ORDER BY
          CASE WHEN schedule_label = ? THEN 0 ELSE 1 END,
          is_active DESC,
          id
        LIMIT 1
        """,
        (
            teacher["raw_name"],
            teacher["suggested_username"],
            teacher["raw_name"],
        ),
    ).fetchone()


def _serialize_import_teacher(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "username": row["username"],
        "schedule_label": row["schedule_label"],
        "slot_count": row["slot_count"] or 0,
        "class_slot_count": row["class_slot_count"] or 0,
        "travel_slot_count": row["travel_slot_count"] or 0,
    }


def analyze_timetable_teacher_sync(connection: sqlite3.Connection, preview: dict[str, Any]) -> dict[str, Any]:
    matched_active_ids: set[int] = set()
    matched_existing_count = 0
    new_teacher_count = 0

    for teacher in preview["teachers"]:
        existing = _find_existing_import_teacher(connection, teacher)
        if existing:
            matched_existing_count += 1
            if existing["is_active"]:
                matched_active_ids.add(existing["id"])
        else:
            new_teacher_count += 1

    active_rows = connection.execute(
        """
        SELECT
            t.*,
            COUNT(ts.id) AS slot_count,
            SUM(CASE WHEN ts.slot_type = 'class' THEN 1 ELSE 0 END) AS class_slot_count,
            SUM(CASE WHEN ts.slot_type = 'travel' THEN 1 ELSE 0 END) AS travel_slot_count
        FROM teachers t
        LEFT JOIN timetable_slots ts ON ts.teacher_id = t.id
        WHERE t.is_active = 1
          AND t.role = 'teacher'
        GROUP BY t.id
        ORDER BY t.display_name
        """
    ).fetchall()
    missing_teachers = [
        _serialize_import_teacher(row)
        for row in active_rows
        if row["id"] not in matched_active_ids
    ]
    return {
        "uploaded_teacher_count": len(preview["teachers"]),
        "matched_existing_count": matched_existing_count,
        "new_teacher_count": new_teacher_count,
        "missing_teacher_count": len(missing_teachers),
        "missing_teachers": missing_teachers,
    }


def import_preview_into_database(
    connection: sqlite3.Connection,
    preview: dict[str, Any],
    default_teacher_password: str,
    missing_teacher_actions: dict[int, str] | None = None,
) -> dict[str, Any]:
    if preview["failed_cells"]:
        raise HTTPException(status_code=400, detail="인식 실패 셀이 남아 있어 시간표를 확정할 수 없습니다.")

    teacher_rows = preview["teachers"]
    teacher_id_by_schedule_label: dict[str, int] = {}
    missing_teacher_actions = missing_teacher_actions or {}

    for teacher in teacher_rows:
        existing = _find_existing_import_teacher(connection, teacher)
        timestamp = format_dt(now_local())
        if existing:
            connection.execute(
                """
                UPDATE teachers
                SET display_name = ?, schedule_label = ?, username = ?, updated_at = ?, is_active = 1
                WHERE id = ?
                """,
                (
                    teacher["display_name"],
                    teacher["raw_name"],
                    teacher["suggested_username"],
                    timestamp,
                    existing["id"],
                ),
            )
            teacher_id_by_schedule_label[teacher["raw_name"]] = existing["id"]
        else:
            connection.execute(
                """
                INSERT INTO teachers (
                    username, display_name, schedule_label, role, password_hash,
                    must_change_password, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, 'teacher', ?, 1, 1, ?, ?)
                """,
                (
                    teacher["suggested_username"],
                    teacher["display_name"],
                    teacher["raw_name"],
                    hash_password(default_teacher_password),
                    timestamp,
                    timestamp,
                ),
            )
            teacher_id_by_schedule_label[teacher["raw_name"]] = connection.execute(
                "SELECT last_insert_rowid()"
            ).fetchone()[0]

    processed_missing = {
        "kept_count": 0,
        "deactivated_count": 0,
        "deleted_count": 0,
    }
    uploaded_teacher_ids = set(teacher_id_by_schedule_label.values())
    active_missing_rows = connection.execute(
        """
        SELECT *
        FROM teachers
        WHERE is_active = 1
          AND role = 'teacher'
        """
    ).fetchall()
    timestamp = format_dt(now_local())
    for row in active_missing_rows:
        if row["id"] in uploaded_teacher_ids:
            continue
        action = missing_teacher_actions.get(row["id"], "keep")
        if action == "deactivate":
            connection.execute(
                "UPDATE teachers SET is_active = 0, updated_at = ? WHERE id = ?",
                (timestamp, row["id"]),
            )
            processed_missing["deactivated_count"] += 1
        elif action == "delete":
            connection.execute(
                """
                UPDATE teachers
                SET username = ?,
                    schedule_label = ?,
                    is_active = 0,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    f"deleted-{row['id']}-{row['username']}",
                    f"{row['schedule_label'] or row['display_name']} (삭제됨)",
                    timestamp,
                    row["id"],
                ),
            )
            processed_missing["deleted_count"] += 1
        else:
            processed_missing["kept_count"] += 1

    connection.execute("DELETE FROM timetable_slots")
    for slot in preview["slots"]:
        teacher_id = teacher_id_by_schedule_label[slot["teacher_schedule_label"]]
        connection.execute(
            """
            INSERT INTO timetable_slots (
                teacher_id, weekday, period, slot_type, class_code, subject,
                location_label, duration, source_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                teacher_id,
                slot["weekday"],
                slot["period"],
                slot["slot_type"],
                slot["class_code"],
                slot["subject"],
                slot["location_label"],
                slot["duration"],
                slot["source_text"],
            ),
        )

    pending_rows = connection.execute(
        "SELECT id, requester_id, responder_id FROM swap_requests WHERE status = 'pending'"
    ).fetchall()
    for row in pending_rows:
        connection.execute(
            """
            UPDATE swap_requests
            SET status = 'cancelled', cancelled_at = ?, responded_at = ?, response_note = ?
            WHERE id = ?
            """,
            (
                format_dt(now_local()),
                format_dt(now_local()),
                "시간표 재업로드로 자동 취소됨",
                row["id"],
            ),
        )
        add_swap_history(
            connection,
            row["id"],
            "cancelled_by_reimport",
            None,
            {"reason": "time-table-reimport"},
        )
        create_notification(
            connection,
            row["requester_id"],
            "swap",
            "교체 요청 자동 취소",
            "시간표가 재업로드되어 대기 중이던 교체 요청이 자동 취소되었습니다.",
            {"swap_request_id": row["id"]},
        )
        create_notification(
            connection,
            row["responder_id"],
            "swap",
            "교체 요청 자동 취소",
            "시간표가 재업로드되어 대기 중이던 교체 요청이 자동 취소되었습니다.",
            {"swap_request_id": row["id"]},
        )

    pending_coverage_rows = connection.execute(
        "SELECT id, requester_id, responder_id FROM coverage_requests WHERE status = 'pending'"
    ).fetchall()
    for row in pending_coverage_rows:
        connection.execute(
            """
            UPDATE coverage_requests
            SET status = 'cancelled', responded_at = ?, response_note = ?
            WHERE id = ?
            """,
            (
                format_dt(now_local()),
                "시간표 재업로드로 자동 취소됨",
                row["id"],
            ),
        )
        create_notification(
            connection,
            row["requester_id"],
            "coverage",
            "보강 요청 자동 취소",
            "시간표가 재업로드되어 대기 중이던 보강 요청이 자동 취소되었습니다.",
            {"coverage_request_id": row["id"]},
        )
        create_notification(
            connection,
            row["responder_id"],
            "coverage",
            "보강 요청 자동 취소",
            "시간표가 재업로드되어 대기 중이던 보강 요청이 자동 취소되었습니다.",
            {"coverage_request_id": row["id"]},
        )

    return {
        "teacher_count": len(teacher_rows),
        "slot_count": len(preview["slots"]),
        "summary": preview["summary"],
        "teacher_sync": {
            **processed_missing,
            "missing_teacher_count": sum(processed_missing.values()),
        },
    }


def _get_calendar_day(connection: sqlite3.Connection, target_date: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM calendar_days WHERE date = ?",
        (target_date,),
    ).fetchone()


def _load_base_slots(connection: sqlite3.Connection) -> dict[tuple[int, int, int], dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            ts.*,
            t.display_name AS teacher_name
        FROM timetable_slots ts
        JOIN teachers t ON t.id = ts.teacher_id
        """
    ).fetchall()
    slots: dict[tuple[int, int, int], dict[str, Any]] = {}
    for row in rows:
        slots[(row["teacher_id"], row["weekday"], row["period"])] = {
            "teacher_id": row["teacher_id"],
            "teacher_name": row["teacher_name"],
            "weekday": row["weekday"],
            "period": row["period"],
            "slot_type": row["slot_type"],
            "class_code": row["class_code"],
            "subject": row["subject"],
            "location_label": row["location_label"],
            "source_text": row["source_text"],
        }
    return slots


def _load_active_requests_in_range(
    connection: sqlite3.Connection,
    start_date: str,
    end_date: str,
    statuses: tuple[str, ...] = ("pending", "accepted"),
) -> list[sqlite3.Row]:
    placeholders = ", ".join("?" for _ in statuses)
    params: list[Any] = list(statuses) + [start_date, end_date, start_date, end_date]
    return connection.execute(
        f"""
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            requester.is_active AS requester_is_active,
            responder.display_name AS responder_name,
            responder.is_active AS responder_is_active
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.status IN ({placeholders})
          AND (
            sr.source_date BETWEEN ? AND ?
            OR sr.target_date BETWEEN ? AND ?
          )
        """,
        params,
    ).fetchall()


def _load_active_coverage_requests_in_range(
    connection: sqlite3.Connection,
    start_date: str,
    end_date: str,
    statuses: tuple[str, ...] = ("pending", "accepted"),
) -> list[sqlite3.Row]:
    placeholders = ", ".join("?" for _ in statuses)
    params: list[Any] = list(statuses) + [start_date, end_date]
    return connection.execute(
        f"""
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            requester.is_active AS requester_is_active,
            responder.display_name AS responder_name,
            responder.is_active AS responder_is_active
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.status IN ({placeholders})
          AND cr.class_date BETWEEN ? AND ?
        """,
        params,
    ).fetchall()


def _build_personal_swap_maps(rows: list[sqlite3.Row]) -> tuple[dict[tuple[int, str, int], dict[str, Any]], dict[tuple[int, str, int], dict[str, Any]]]:
    incoming: dict[tuple[int, str, int], dict[str, Any]] = {}
    outgoing: dict[tuple[int, str, int], dict[str, Any]] = {}
    for row in rows:
        source_slot = {
            "slot_type": "class",
            "class_code": row["source_class_code"],
            "subject": row["source_subject"],
            "from_teacher_id": row["source_teacher_id"],
            "from_teacher_name": row["requester_name"],
            "to_teacher_id": row["target_teacher_id"],
            "to_teacher_name": row["responder_name"],
        }
        target_slot = {
            "slot_type": "class",
            "class_code": row["target_class_code"],
            "subject": row["target_subject"],
            "from_teacher_id": row["target_teacher_id"],
            "from_teacher_name": row["responder_name"],
            "to_teacher_id": row["source_teacher_id"],
            "to_teacher_name": row["requester_name"],
        }
        outgoing[(row["source_teacher_id"], row["source_date"], row["source_period"])] = source_slot
        incoming[(row["responder_id"], row["source_date"], row["source_period"])] = source_slot
        outgoing[(row["target_teacher_id"], row["target_date"], row["target_period"])] = target_slot
        incoming[(row["requester_id"], row["target_date"], row["target_period"])] = target_slot
    return incoming, outgoing


def _build_personal_coverage_maps(
    rows: list[sqlite3.Row],
) -> tuple[dict[tuple[int, str, int], dict[str, Any]], dict[tuple[int, str, int], dict[str, Any]]]:
    incoming: dict[tuple[int, str, int], dict[str, Any]] = {}
    outgoing: dict[tuple[int, str, int], dict[str, Any]] = {}
    for row in rows:
        slot = {
            "slot_type": "class",
            "class_code": row["class_code"],
            "subject": row["subject"],
            "request_id": row["id"],
            "status": row["status"],
            "requester_id": row["requester_id"],
            "requester_name": row["requester_name"],
            "responder_id": row["responder_id"],
            "responder_name": row["responder_name"],
        }
        incoming[(row["responder_id"], row["class_date"], row["period"])] = slot
        outgoing[(row["requester_id"], row["class_date"], row["period"])] = slot
    return incoming, outgoing


def _slot_for_personal_view(
    base_slots: dict[tuple[int, int, int], dict[str, Any]],
    incoming: dict[tuple[int, str, int], dict[str, Any]],
    outgoing: dict[tuple[int, str, int], dict[str, Any]],
    teacher_id: int,
    target_date: str,
    weekday: int,
    period: int,
    coverage_incoming: dict[tuple[int, str, int], dict[str, Any]] | None = None,
    coverage_outgoing: dict[tuple[int, str, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = base_slots.get((teacher_id, weekday, period))
    incoming_slot = incoming.get((teacher_id, target_date, period))
    outgoing_slot = outgoing.get((teacher_id, target_date, period))
    coverage_incoming_slot = (coverage_incoming or {}).get((teacher_id, target_date, period))
    coverage_outgoing_slot = (coverage_outgoing or {}).get((teacher_id, target_date, period))

    if incoming_slot:
        return {
            "period": period,
            "status": "swapped-in",
            "effective": {
                "slot_type": incoming_slot["slot_type"],
                "class_code": incoming_slot["class_code"],
                "subject": incoming_slot["subject"],
                "location_label": None,
                "from_teacher_name": incoming_slot["from_teacher_name"],
                "swap_with_name": incoming_slot["from_teacher_name"],
            },
            "original": {
                "slot_type": base["slot_type"],
                "class_code": base["class_code"],
                "subject": base["subject"],
                "location_label": base["location_label"],
            }
            if base
            else None,
        }

    if outgoing_slot:
        return {
            "period": period,
            "status": "swapped-out",
            "effective": None,
            "original": {
                "slot_type": outgoing_slot["slot_type"],
                "class_code": outgoing_slot["class_code"],
                "subject": outgoing_slot["subject"],
                "location_label": None,
                "swap_with_name": outgoing_slot["to_teacher_name"],
            },
        }

    if coverage_incoming_slot:
        is_pending = coverage_incoming_slot["status"] == "pending"
        return {
            "period": period,
            "status": "coverage-pending-in" if is_pending else "coverage-in",
            "effective": {
                "slot_type": "class",
                "class_code": coverage_incoming_slot["class_code"],
                "subject": coverage_incoming_slot["subject"],
                "location_label": None,
                "from_teacher_name": coverage_incoming_slot["requester_name"],
                "coverage_request_id": coverage_incoming_slot["request_id"],
            },
            "original": {
                "slot_type": base["slot_type"],
                "class_code": base["class_code"],
                "subject": base["subject"],
                "location_label": base["location_label"],
            }
            if base
            else None,
        }

    if coverage_outgoing_slot:
        is_pending = coverage_outgoing_slot["status"] == "pending"
        return {
            "period": period,
            "status": "coverage-pending-out" if is_pending else "coverage-out",
            "effective": None,
            "original": {
                "slot_type": "class",
                "class_code": coverage_outgoing_slot["class_code"],
                "subject": coverage_outgoing_slot["subject"],
                "location_label": None,
                "covered_by_name": coverage_outgoing_slot["responder_name"],
                "coverage_request_id": coverage_outgoing_slot["request_id"],
            },
        }

    if not base:
        return {
            "period": period,
            "status": "free",
            "effective": None,
            "original": None,
        }

    return {
        "period": period,
        "status": base["slot_type"],
        "effective": {
            "slot_type": base["slot_type"],
            "class_code": base["class_code"],
            "subject": base["subject"],
            "location_label": base["location_label"],
            "from_teacher_name": None,
        },
        "original": {
            "slot_type": base["slot_type"],
            "class_code": base["class_code"],
            "subject": base["subject"],
            "location_label": base["location_label"],
        },
    }


def _is_busy(cell: dict[str, Any]) -> bool:
    return cell["status"] in {
        "class",
        "travel",
        "swapped-in",
        "coverage-in",
        "coverage-out",
        "coverage-pending-in",
        "coverage-pending-out",
        "locked",
    }


def expire_pending_swap_requests(connection: sqlite3.Connection) -> int:
    pending = connection.execute(
        """
        SELECT * FROM swap_requests
        WHERE status = 'pending'
          AND expires_at <= ?
        """,
        (format_dt(now_local()),),
    ).fetchall()
    for row in pending:
        connection.execute(
            """
            UPDATE swap_requests
            SET status = 'expired', responded_at = ?
            WHERE id = ?
            """,
            (format_dt(now_local()), row["id"]),
        )
        add_swap_history(connection, row["id"], "expired", None, {"reason": "deadline"})
        create_notification(
            connection,
            row["requester_id"],
            "swap",
            "교체 요청 자동 만료",
            "응답이 없어 교체 요청이 자동 만료되었습니다.",
            {"swap_request_id": row["id"]},
        )
        create_notification(
            connection,
            row["responder_id"],
            "swap",
            "교체 요청 만료",
            "응답하지 않은 교체 요청이 자동 만료되었습니다.",
            {"swap_request_id": row["id"]},
        )
    return len(pending)


def expire_pending_coverage_requests(connection: sqlite3.Connection) -> int:
    pending = connection.execute(
        """
        SELECT * FROM coverage_requests
        WHERE status = 'pending'
          AND expires_at <= ?
        """,
        (format_dt(now_local()),),
    ).fetchall()
    for row in pending:
        connection.execute(
            """
            UPDATE coverage_requests
            SET status = 'expired', responded_at = ?
            WHERE id = ?
            """,
            (format_dt(now_local()), row["id"]),
        )
        create_notification(
            connection,
            row["requester_id"],
            "coverage",
            "보강 요청 자동 만료",
            "응답이 없어 보강 요청이 자동 만료되었습니다.",
            {"coverage_request_id": row["id"]},
        )
        create_notification(
            connection,
            row["responder_id"],
            "coverage",
            "보강 요청 만료",
            "응답하지 않은 보강 요청이 자동 만료되었습니다.",
            {"coverage_request_id": row["id"]},
        )
    return len(pending)


def _request_lock_points(row: sqlite3.Row | dict[str, Any]) -> set[tuple[int, str, int]]:
    return {
        (row["requester_id"], row["source_date"], row["source_period"]),
        (row["responder_id"], row["target_date"], row["target_period"]),
        (row["responder_id"], row["source_date"], row["source_period"]),
        (row["requester_id"], row["target_date"], row["target_period"]),
    }


def _coverage_lock_points(row: sqlite3.Row | dict[str, Any]) -> set[tuple[int, str, int]]:
    return {
        (row["requester_id"], row["class_date"], row["period"]),
        (row["responder_id"], row["class_date"], row["period"]),
    }


def _status_korean(status: str) -> str:
    return {
        "pending": "대기 중",
        "accepted": "확정됨",
        "rejected": "거절됨",
        "expired": "만료됨",
        "cancelled": "취소됨",
    }.get(status, status)


def _swap_lock_message(row: sqlite3.Row | dict[str, Any]) -> str:
    requester_name = row.get("requester_name") if isinstance(row, dict) else row["requester_name"]
    responder_name = row.get("responder_name") if isinstance(row, dict) else row["responder_name"]
    return (
        f"{requester_name}↔{responder_name} "
        f"{row['source_date']} {row['source_period']}교시와 "
        f"{row['target_date']} {row['target_period']}교시 교체가 {_status_korean(row['status'])}입니다."
    )


def _coverage_lock_message(row: sqlite3.Row | dict[str, Any]) -> str:
    requester_name = row.get("requester_name") if isinstance(row, dict) else row["requester_name"]
    responder_name = row.get("responder_name") if isinstance(row, dict) else row["responder_name"]
    return (
        f"{requester_name}→{responder_name} "
        f"{row['class_date']} {row['period']}교시 보강이 {_status_korean(row['status'])}입니다."
    )


def _base_class_slot_or_error(
    connection: sqlite3.Connection,
    teacher_id: int,
    target_date: str,
    period: int,
) -> sqlite3.Row:
    calendar_day = _get_calendar_day(connection, target_date)
    if not calendar_day or not calendar_day["is_school_day"]:
        raise HTTPException(status_code=400, detail="해당 날짜는 수업일이 아닙니다.")
    base_slot = connection.execute(
        """
        SELECT *
        FROM timetable_slots
        WHERE teacher_id = ? AND weekday = ? AND period = ? AND slot_type = 'class'
        """,
        (teacher_id, calendar_day["weekday"], period),
    ).fetchone()
    if not base_slot:
        raise HTTPException(status_code=400, detail="선택한 교시는 현재 교사의 정규 수업이 아닙니다.")
    return base_slot


def _week_bounds(target: date) -> tuple[date, date]:
    monday = target - timedelta(days=target.weekday())
    friday = monday + timedelta(days=4)
    return monday, friday


def _swap_expires_at(source_date: str, target_date: str) -> str:
    earliest_date = min(parse_date(source_date), parse_date(target_date))
    deadline_date = earliest_date - timedelta(days=1)
    return datetime.combine(deadline_date, time(23, 59, 59)).isoformat()


def _ensure_swap_deadline_is_open(source_date: str, target_date: str) -> None:
    expires_at = datetime.fromisoformat(_swap_expires_at(source_date, target_date))
    if expires_at <= now_local():
        raise HTTPException(
            status_code=400,
            detail="이 교체 요청은 응답 마감 시간이 이미 지나 신청할 수 없습니다.",
        )


def _ensure_coverage_deadline_is_open(class_date: str) -> None:
    expires_at = datetime.fromisoformat(_swap_expires_at(class_date, class_date))
    if expires_at <= now_local():
        raise HTTPException(
            status_code=400,
            detail="이 보강 요청은 응답 마감 시간이 이미 지나 신청할 수 없습니다.",
        )


def _serialize_swap_request(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "requester_hidden": row_bool(row, "requester_hidden"),
        "responder_hidden": row_bool(row, "responder_hidden"),
        "requester_id": row["requester_id"],
        "requester_name": row["requester_name"],
        "responder_id": row["responder_id"],
        "responder_name": row["responder_name"],
        "source_date": row["source_date"],
        "source_period": row["source_period"],
        "source_class_code": row["source_class_code"],
        "source_subject": row["source_subject"],
        "target_date": row["target_date"],
        "target_period": row["target_period"],
        "target_class_code": row["target_class_code"],
        "target_subject": row["target_subject"],
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
        "responded_at": row["responded_at"],
        "response_note": row["response_note"],
    }


def _serialize_coverage_request(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "status": row["status"],
        "requester_hidden": row_bool(row, "requester_hidden"),
        "responder_hidden": row_bool(row, "responder_hidden"),
        "requester_id": row["requester_id"],
        "requester_name": row["requester_name"],
        "responder_id": row["responder_id"],
        "responder_name": row["responder_name"],
        "class_date": row["class_date"],
        "weekday": row["weekday"],
        "day_label": DAY_LABELS[row["weekday"]],
        "period": row["period"],
        "class_code": row["class_code"],
        "subject": row["subject"],
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
        "responded_at": row["responded_at"],
        "response_note": row["response_note"],
    }


def _fetch_swap_request(connection: sqlite3.Connection, swap_request_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.id = ?
        """,
        (swap_request_id,),
    ).fetchone()


def _fetch_coverage_request(connection: sqlite3.Connection, coverage_request_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.id = ?
        """,
        (coverage_request_id,),
    ).fetchone()


def _plan_row_sort_key(row: dict[str, Any]) -> tuple[str, int, str, str]:
    return (row["date"], row["period"], row["type"], row["original_teacher_name"])


def get_weekly_plan(
    connection: sqlite3.Connection,
    anchor_date_raw: str,
    teacher_id: int | None = None,
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    anchor_date = parse_date(anchor_date_raw)
    week_start, week_end = _week_bounds(anchor_date)
    start_text = week_start.isoformat()
    end_text = week_end.isoformat()

    swap_teacher_filter = ""
    swap_params: list[Any] = [start_text, end_text, start_text, end_text]
    if teacher_id is not None:
        swap_teacher_filter = "AND (sr.requester_id = ? OR sr.responder_id = ?)"
        swap_params.extend([teacher_id, teacher_id])
    swap_rows = connection.execute(
        f"""
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.status = 'accepted'
          AND (
            sr.source_date BETWEEN ? AND ?
            OR sr.target_date BETWEEN ? AND ?
          )
          {swap_teacher_filter}
        ORDER BY sr.source_date, sr.source_period, sr.target_date, sr.target_period
        """,
        swap_params,
    ).fetchall()
    coverage_teacher_filter = ""
    coverage_params: list[Any] = [start_text, end_text]
    if teacher_id is not None:
        coverage_teacher_filter = "AND (cr.requester_id = ? OR cr.responder_id = ?)"
        coverage_params.extend([teacher_id, teacher_id])
    coverage_rows = connection.execute(
        f"""
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.status = 'accepted'
          AND cr.class_date BETWEEN ? AND ?
          {coverage_teacher_filter}
        ORDER BY cr.class_date, cr.period, requester.display_name
        """,
        coverage_params,
    ).fetchall()

    items: list[dict[str, Any]] = []
    for row in swap_rows:
        if start_text <= row["source_date"] <= end_text:
            items.append(
                {
                    "id": f"swap-{row['id']}",
                    "request_id": row["id"],
                    "type": "교체",
                    "date": row["source_date"],
                    "weekday": row["source_weekday"],
                    "day_label": DAY_LABELS[row["source_weekday"]],
                    "period": row["source_period"],
                    "class_code": row["source_class_code"],
                    "subject": row["source_subject"],
                    "original_teacher_name": row["requester_name"],
                    "assigned_teacher_name": row["responder_name"],
                    "detail": f"{row['target_date']} {row['target_period']}교시와 맞교환",
                    "note": row["response_note"] or "",
                }
            )

    for row in coverage_rows:
        items.append(
            {
                "id": f"coverage-{row['id']}",
                "request_id": row["id"],
                "type": "보강",
                "date": row["class_date"],
                "weekday": row["weekday"],
                "day_label": DAY_LABELS[row["weekday"]],
                "period": row["period"],
                "class_code": row["class_code"],
                "subject": row["subject"],
                "original_teacher_name": row["requester_name"],
                "assigned_teacher_name": row["responder_name"],
                "detail": "원 수업 담당 교사 부재에 따른 보강",
                "note": row["response_note"] or "",
            }
        )

    items.sort(key=_plan_row_sort_key)
    for index, item in enumerate(items, start=1):
        item["sequence"] = index

    return {
        "week_start": start_text,
        "week_end": end_text,
        "anchor_date": anchor_date.isoformat(),
        "scope": "teacher" if teacher_id is not None else "all",
        "generated_at": format_dt(now_local()),
        "summary": {
            "swap_request_count": len(swap_rows),
            "coverage_request_count": len(coverage_rows),
            "row_count": len(items),
        },
        "items": items,
    }


def get_weekly_schedule(
    connection: sqlite3.Connection,
    teacher_id: int,
    anchor_date_raw: str | None = None,
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    anchor_date = parse_date(anchor_date_raw) if anchor_date_raw else date.today()
    week_start, week_end = _week_bounds(anchor_date)

    calendar_rows = connection.execute(
        """
        SELECT *
        FROM calendar_days
        WHERE date BETWEEN ? AND ?
        ORDER BY date
        """,
        (week_start.isoformat(), week_end.isoformat()),
    ).fetchall()
    calendar_by_date = {row["date"]: row for row in calendar_rows}
    base_slots = _load_base_slots(connection)
    accepted_swaps = _load_active_requests_in_range(
        connection,
        week_start.isoformat(),
        week_end.isoformat(),
        ("accepted",),
    )
    incoming, outgoing = _build_personal_swap_maps(accepted_swaps)
    accepted_coverage = _load_active_coverage_requests_in_range(
        connection,
        week_start.isoformat(),
        week_end.isoformat(),
        ("accepted",),
    )
    coverage_incoming, coverage_outgoing = _build_personal_coverage_maps(accepted_coverage)

    days: list[dict[str, Any]] = []
    for weekday in range(5):
        target_date = week_start + timedelta(days=weekday)
        iso_date = target_date.isoformat()
        calendar_day = calendar_by_date.get(iso_date)
        is_school_day = bool(calendar_day["is_school_day"]) if calendar_day else True
        period_limit = DAY_PERIOD_LIMITS[weekday]
        periods = []
        for period in range(1, period_limit + 1):
            if not is_school_day:
                periods.append(
                    {
                        "period": period,
                        "status": "holiday",
                        "effective": None,
                        "original": None,
                        "label": calendar_day["label"] if calendar_day else "수업 없음",
                    }
                )
                continue
            periods.append(
                _slot_for_personal_view(
                    base_slots,
                    incoming,
                    outgoing,
                    teacher_id,
                    iso_date,
                    weekday,
                    period,
                    coverage_incoming,
                    coverage_outgoing,
                )
            )
        days.append(
            {
                "date": iso_date,
                "weekday": weekday,
                "day_label": DAY_LABELS[weekday],
                "is_school_day": is_school_day,
                "kind": calendar_day["kind"] if calendar_day else "school_day",
                "label": calendar_day["label"] if calendar_day else "",
                "periods": periods,
            }
        )
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "anchor_date": anchor_date.isoformat(),
        "days": days,
    }


def get_school_weekly_schedule(connection: sqlite3.Connection, anchor_date_raw: str) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    anchor_date = parse_date(anchor_date_raw)
    week_start, week_end = _week_bounds(anchor_date)
    teachers = connection.execute(
        "SELECT id, display_name FROM teachers WHERE is_active = 1 AND role = 'teacher' ORDER BY display_name"
    ).fetchall()
    teacher_rows = []
    sample_days: list[dict[str, Any]] = []
    for teacher in teachers:
        weekly = get_weekly_schedule(connection, teacher["id"], anchor_date.isoformat())
        if not sample_days:
            sample_days = weekly["days"]
        teacher_rows.append(
            {
                "teacher_id": teacher["id"],
                "teacher_name": teacher["display_name"],
                "days": weekly["days"],
            }
        )
    if not sample_days:
        sample_days = [
            {
                "date": (week_start + timedelta(days=weekday)).isoformat(),
                "weekday": weekday,
                "day_label": DAY_LABELS[weekday],
                "is_school_day": True,
                "kind": "school_day",
                "label": "",
                "periods": [],
            }
            for weekday in range(5)
        ]
    return {
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "anchor_date": anchor_date.isoformat(),
        "generated_at": format_dt(now_local()),
        "days": sample_days,
        "teachers": teacher_rows,
        "summary": {
            "teacher_count": len(teacher_rows),
            "day_count": len(sample_days),
        },
    }


def _teacher_month_schedule(
    connection: sqlite3.Connection,
    teacher_id: int,
    month: str,
) -> dict[str, Any]:
    try:
        year, month_number = [int(piece) for piece in month.split("-", 1)]
        month_start = date(year, month_number, 1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="month는 YYYY-MM 형식이어야 합니다.") from exc
    if month_number == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month_number + 1, 1) - timedelta(days=1)

    days = connection.execute(
        """
        SELECT *
        FROM calendar_days
        WHERE date BETWEEN ? AND ?
        ORDER BY date
        """,
        (month_start.isoformat(), month_end.isoformat()),
    ).fetchall()
    base_slots = _load_base_slots(connection)
    accepted = _load_active_requests_in_range(connection, month_start.isoformat(), month_end.isoformat(), ("accepted",))
    incoming, outgoing = _build_personal_swap_maps(accepted)
    accepted_coverage = _load_active_coverage_requests_in_range(
        connection,
        month_start.isoformat(),
        month_end.isoformat(),
        ("accepted",),
    )
    coverage_incoming, coverage_outgoing = _build_personal_coverage_maps(accepted_coverage)

    items = []
    for day in days:
        weekday = day["weekday"]
        period_limit = DAY_PERIOD_LIMITS.get(weekday, 0)
        periods = []
        if weekday <= 4:
            for period in range(1, period_limit + 1):
                periods.append(
                    _slot_for_personal_view(
                        base_slots,
                        incoming,
                        outgoing,
                        teacher_id,
                        day["date"],
                        weekday,
                        period,
                        coverage_incoming,
                        coverage_outgoing,
                    )
                )
        items.append(
            {
                "date": day["date"],
                "weekday": weekday,
                "day_label": DAY_LABELS[weekday],
                "is_school_day": bool(day["is_school_day"]),
                "kind": day["kind"],
                "label": day["label"],
                "periods": periods,
            }
        )
    return {"month": month, "days": items}


def get_teacher_day_schedule(connection: sqlite3.Connection, teacher_id: int, target_date: str) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    calendar_day = _get_calendar_day(connection, target_date)
    if not calendar_day:
        raise HTTPException(status_code=404, detail="학사일정에 없는 날짜입니다.")
    if calendar_day["weekday"] > 4:
        return {
            "date": target_date,
            "day_label": DAY_LABELS[calendar_day["weekday"]],
            "is_school_day": False,
            "periods": [],
        }
    month_data = _teacher_month_schedule(connection, teacher_id, target_date[:7])
    for item in month_data["days"]:
        if item["date"] == target_date:
            pending_locks: dict[tuple[int, str, int], dict[str, Any]] = {}
            for row in _load_active_requests_in_range(connection, target_date, target_date, ("pending",)):
                for point in _request_lock_points(row):
                    pending_locks[point] = {
                        "lock_type": "swap",
                        "lock_status": row["status"],
                        "lock_label": "교체 요청 대기 중",
                        "lock_message": _swap_lock_message(row),
                        "request_id": row["id"],
                    }
            for row in _load_active_coverage_requests_in_range(connection, target_date, target_date, ("pending",)):
                for point in _coverage_lock_points(row):
                    pending_locks[point] = {
                        "lock_type": "coverage",
                        "lock_status": row["status"],
                        "lock_label": "보강 요청 대기 중",
                        "lock_message": _coverage_lock_message(row),
                        "request_id": row["id"],
                    }

            periods = []
            for cell in item["periods"]:
                lock = pending_locks.get((teacher_id, target_date, cell["period"]))
                if lock and cell["status"] == "class":
                    periods.append(
                        {
                            **cell,
                            "status": "locked",
                            **lock,
                        }
                    )
                else:
                    periods.append(cell)
            item = {**item, "periods": periods}
            return item
    raise HTTPException(status_code=404, detail="해당 날짜의 시간표를 찾지 못했습니다.")


def get_available_coverage_teachers(
    connection: sqlite3.Connection,
    target_date: str,
    period: int,
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    calendar_day = _get_calendar_day(connection, target_date)
    if not calendar_day:
        raise HTTPException(status_code=404, detail="학사일정에 없는 날짜입니다.")
    if not calendar_day["is_school_day"] or calendar_day["weekday"] > 4:
        return {
            "date": target_date,
            "period": period,
            "weekday": calendar_day["weekday"],
            "day_label": DAY_LABELS[calendar_day["weekday"]],
            "is_school_day": False,
            "available_teachers": [],
            "busy_teachers": [],
        }
    if period < 1 or period > DAY_PERIOD_LIMITS[calendar_day["weekday"]]:
        raise HTTPException(status_code=400, detail="해당 요일에 없는 교시입니다.")

    teachers = connection.execute(
        """
        SELECT id, display_name, username, schedule_label
        FROM teachers
        WHERE is_active = 1 AND role = 'teacher'
        ORDER BY display_name
        """
    ).fetchall()
    base_slots = _load_base_slots(connection)
    active_swaps = _load_active_requests_in_range(connection, target_date, target_date)
    accepted = [row for row in active_swaps if row["status"] == "accepted"]
    incoming, outgoing = _build_personal_swap_maps(accepted)
    swap_lock_points = set().union(*(_request_lock_points(row) for row in active_swaps)) if active_swaps else set()
    active_coverage = _load_active_coverage_requests_in_range(connection, target_date, target_date)
    coverage_incoming, coverage_outgoing = _build_personal_coverage_maps(active_coverage)

    def day_load_for_teacher(teacher_id: int) -> dict[str, int]:
        class_count = 0
        travel_count = 0
        for day_period in range(1, DAY_PERIOD_LIMITS[calendar_day["weekday"]] + 1):
            day_cell = _slot_for_personal_view(
                base_slots,
                incoming,
                outgoing,
                teacher_id,
                target_date,
                calendar_day["weekday"],
                day_period,
                coverage_incoming,
                coverage_outgoing,
            )
            if day_cell["status"] in {"class", "swapped-in", "coverage-in", "coverage-pending-in"}:
                class_count += 1
            elif day_cell["status"] == "travel":
                travel_count += 1
        return {
            "day_class_count": class_count,
            "day_travel_count": travel_count,
            "day_busy_count": class_count + travel_count,
        }

    available_teachers: list[dict[str, Any]] = []
    busy_teachers: list[dict[str, Any]] = []
    for teacher in teachers:
        cell = _slot_for_personal_view(
            base_slots,
            incoming,
            outgoing,
            teacher["id"],
            target_date,
            calendar_day["weekday"],
            period,
            coverage_incoming,
            coverage_outgoing,
        )
        if not _is_busy(cell) and (teacher["id"], target_date, period) in swap_lock_points:
            cell = {
                "period": period,
                "status": "locked",
                "effective": None,
                "original": cell["effective"] or cell["original"],
            }
        teacher_payload = {
            "teacher_id": teacher["id"],
            "teacher_name": teacher["display_name"],
            "username": teacher["username"],
            "schedule_label": teacher["schedule_label"],
            "status": cell["status"],
            "slot": cell,
            **day_load_for_teacher(teacher["id"]),
        }
        if _is_busy(cell):
            busy_teachers.append(teacher_payload)
        else:
            available_teachers.append(teacher_payload)

    return {
        "date": target_date,
        "period": period,
        "weekday": calendar_day["weekday"],
        "day_label": DAY_LABELS[calendar_day["weekday"]],
        "is_school_day": True,
        "available_teachers": available_teachers,
        "busy_teachers": busy_teachers,
    }


def get_coverage_source_classes(
    connection: sqlite3.Connection,
    teacher_id: int,
    target_date: str,
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    calendar_day = _get_calendar_day(connection, target_date)
    if not calendar_day:
        raise HTTPException(status_code=404, detail="학사일정에 없는 날짜입니다.")
    if not calendar_day["is_school_day"] or calendar_day["weekday"] > 4:
        return {
            "date": target_date,
            "weekday": calendar_day["weekday"],
            "day_label": DAY_LABELS[calendar_day["weekday"]],
            "is_school_day": False,
            "sources": [],
        }

    day_schedule = get_teacher_day_schedule(connection, teacher_id, target_date)
    active_coverage = _load_active_coverage_requests_in_range(connection, target_date, target_date)
    active_swaps = _load_active_requests_in_range(connection, target_date, target_date)
    coverage_lock_by_period: dict[int, sqlite3.Row] = {}
    for row in active_coverage:
        if (teacher_id, target_date, row["period"]) in _coverage_lock_points(row):
            coverage_lock_by_period[row["period"]] = row
    swap_locked_periods = {
        period
        for period in range(1, DAY_PERIOD_LIMITS[calendar_day["weekday"]] + 1)
        if any((teacher_id, target_date, period) in _request_lock_points(row) for row in active_swaps)
    }

    now_deadline_open = datetime.fromisoformat(_swap_expires_at(target_date, target_date)) > now_local()
    sources: list[dict[str, Any]] = []
    for cell in day_schedule["periods"]:
        effective = cell.get("effective")
        if cell["status"] != "class" or not effective or effective.get("slot_type") != "class":
            continue
        coverage_lock = coverage_lock_by_period.get(cell["period"])
        is_locked = bool(coverage_lock) or cell["period"] in swap_locked_periods
        lock_status = coverage_lock["status"] if coverage_lock else ("swap_locked" if cell["period"] in swap_locked_periods else None)
        sources.append(
            {
                "date": target_date,
                "weekday": calendar_day["weekday"],
                "day_label": DAY_LABELS[calendar_day["weekday"]],
                "period": cell["period"],
                "class_code": effective["class_code"],
                "subject": effective["subject"],
                "locked": is_locked,
                "lock_status": lock_status,
                "coverage_request_id": coverage_lock["id"] if coverage_lock else None,
                "can_request": not is_locked and now_deadline_open and parse_date(target_date) >= date.today(),
            }
        )

    return {
        "date": target_date,
        "weekday": calendar_day["weekday"],
        "day_label": DAY_LABELS[calendar_day["weekday"]],
        "is_school_day": True,
        "sources": sources,
    }


def get_weekly_coverage_candidates(
    connection: sqlite3.Connection,
    requester_id: int,
    source_date_raw: str,
    source_period: int,
    week_offset: int = 0,
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    if week_offset not in {0, 1}:
        raise HTTPException(status_code=400, detail="보강 후보는 이번 주 또는 다음 주만 조회할 수 있습니다.")

    source_date = parse_date(source_date_raw)
    if source_date < date.today():
        raise HTTPException(status_code=400, detail="지난 날짜의 수업은 보강 후보를 조회할 수 없습니다.")

    source_slot = _base_class_slot_or_error(connection, requester_id, source_date.isoformat(), source_period)
    source_calendar_day = _get_calendar_day(connection, source_date.isoformat())
    if not source_calendar_day or not source_calendar_day["is_school_day"]:
        raise HTTPException(status_code=400, detail="해당 날짜는 수업일이 아닙니다.")

    source_week_start, source_week_end = _week_bounds(source_date)
    target_week_start = source_week_start + timedelta(days=week_offset * 7)
    target_week_end = source_week_end + timedelta(days=week_offset * 7)
    target_date = target_week_start + timedelta(days=source_calendar_day["weekday"])
    target_date_text = target_date.isoformat()

    slots: list[dict[str, Any]] = []
    if target_date >= date.today():
        try:
            _ensure_coverage_deadline_is_open(target_date_text)
            target_slot = _base_class_slot_or_error(connection, requester_id, target_date_text, source_period)
            calendar_day = _get_calendar_day(connection, target_date_text)
        except HTTPException:
            target_slot = None
            calendar_day = None
        if calendar_day and calendar_day["is_school_day"] and calendar_day["weekday"] <= 4 and target_slot:
            source_point = (requester_id, target_date_text, source_period)
            active_coverage = _load_active_coverage_requests_in_range(connection, target_date_text, target_date_text)
            active_swaps = _load_active_requests_in_range(connection, target_date_text, target_date_text)
            is_locked = any(source_point in _coverage_lock_points(item) for item in active_coverage) or any(
                source_point in _request_lock_points(item) for item in active_swaps
            )
            if not is_locked:
                availability = get_available_coverage_teachers(connection, target_date_text, source_period)
                slots.append(
                    {
                        "date": target_date_text,
                        "weekday": calendar_day["weekday"],
                        "day_label": DAY_LABELS[calendar_day["weekday"]],
                        "period": source_period,
                        "class_code": target_slot["class_code"],
                        "subject": target_slot["subject"],
                        "available_teachers": availability["available_teachers"],
                        "busy_teachers": availability["busy_teachers"],
                        "available_count": len(availability["available_teachers"]),
                        "busy_count": len(availability["busy_teachers"]),
                    }
                )

    return {
        "source": {
            "date": source_date.isoformat(),
            "weekday": source_calendar_day["weekday"],
            "day_label": DAY_LABELS[source_calendar_day["weekday"]],
            "period": source_period,
            "class_code": source_slot["class_code"],
            "subject": source_slot["subject"],
        },
        "week": {
            "offset": week_offset,
            "label": "이번 주" if week_offset == 0 else "다음 주",
            "start_date": target_week_start.isoformat(),
            "end_date": target_week_end.isoformat(),
        },
        "slots": slots,
        "available_count": sum(slot["available_count"] for slot in slots),
        "busy_count": sum(slot["busy_count"] for slot in slots),
    }


def create_coverage_request(
    connection: sqlite3.Connection,
    requester_id: int,
    class_date: str,
    period: int,
    responder_id: int,
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    parsed_date = parse_date(class_date)
    if parsed_date < date.today():
        raise HTTPException(status_code=400, detail="지난 날짜의 수업은 보강 요청을 만들 수 없습니다.")
    _ensure_coverage_deadline_is_open(class_date)
    if requester_id == responder_id:
        raise HTTPException(status_code=400, detail="자기 자신에게 보강을 요청할 수 없습니다.")

    source_slot = _base_class_slot_or_error(connection, requester_id, class_date, period)
    calendar_day = _get_calendar_day(connection, class_date)
    if not calendar_day or not calendar_day["is_school_day"]:
        raise HTTPException(status_code=400, detail="해당 날짜는 수업일이 아닙니다.")

    active_coverage = _load_active_coverage_requests_in_range(connection, class_date, class_date)
    source_point = (requester_id, class_date, period)
    if any(source_point in _coverage_lock_points(row) for row in active_coverage):
        raise HTTPException(status_code=400, detail="선택한 수업은 이미 보강 요청과 겹칩니다.")

    active_swaps = _load_active_requests_in_range(connection, class_date, class_date)
    if any(source_point in _request_lock_points(row) for row in active_swaps):
        raise HTTPException(status_code=400, detail="선택한 수업은 이미 교체 요청과 겹칩니다.")

    available_payload = get_available_coverage_teachers(connection, class_date, period)
    matched_teacher = next(
        (item for item in available_payload["available_teachers"] if item["teacher_id"] == responder_id),
        None,
    )
    if matched_teacher is None:
        raise HTTPException(status_code=400, detail="선택한 선생님은 현재 이 수업의 보강 후보가 아닙니다.")

    requester = get_user_by_id(connection, requester_id)
    responder = get_user_by_id(connection, responder_id)
    if not requester or not responder:
        raise HTTPException(status_code=404, detail="교사를 찾지 못했습니다.")

    created_at = format_dt(now_local())
    expires_at = _swap_expires_at(class_date, class_date)
    connection.execute(
        """
        INSERT INTO coverage_requests (
            requester_id, responder_id, class_date, weekday, period,
            class_code, subject, status, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            requester_id,
            responder_id,
            class_date,
            calendar_day["weekday"],
            period,
            source_slot["class_code"],
            source_slot["subject"],
            expires_at,
            created_at,
        ),
    )
    request_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    create_notification(
        connection,
        responder_id,
        "coverage",
        "새 보강 요청",
        f"{requester['display_name']} 선생님이 {class_date} {period}교시 보강을 요청했습니다.",
        {"coverage_request_id": request_id},
    )
    create_notification(
        connection,
        requester_id,
        "coverage",
        "보강 요청 전송",
        f"{responder['display_name']} 선생님에게 보강 요청을 보냈습니다.",
        {"coverage_request_id": request_id},
    )
    row = connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.id = ?
        """,
        (request_id,),
    ).fetchone()
    return _serialize_coverage_request(row)


def list_coverage_requests_for_user(connection: sqlite3.Connection, teacher_id: int) -> dict[str, Any]:
    expire_pending_coverage_requests(connection)
    rows = connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.requester_id = ? OR cr.responder_id = ?
        ORDER BY cr.created_at DESC
        """,
        (teacher_id, teacher_id),
    ).fetchall()
    received = []
    sent = []
    status_received = []
    status_sent = []
    for row in rows:
        serialized = _serialize_coverage_request(row)
        if row["responder_id"] == teacher_id and (
            not row["responder_hidden"] or row["status"] in ACTIVE_COVERAGE_STATUSES
        ):
            received.append(serialized)
            status_received.append(serialized)
        if row["requester_id"] == teacher_id and (
            not row["requester_hidden"] or row["status"] in ACTIVE_COVERAGE_STATUSES
        ):
            status_sent.append(serialized)
        if row["requester_id"] == teacher_id and not row["requester_hidden"]:
            sent.append(serialized)
    return {
        "received": received,
        "sent": sent,
        "status_received": status_received,
        "status_sent": status_sent,
    }


def dismiss_sent_swap_request(connection: sqlite3.Connection, teacher_id: int, swap_request_id: int) -> dict[str, Any]:
    row = _fetch_swap_request(connection, swap_request_id)
    if not row:
        raise HTTPException(status_code=404, detail="교체 요청을 찾지 못했습니다.")
    if row["requester_id"] != teacher_id and row["responder_id"] != teacher_id:
        raise HTTPException(status_code=403, detail="내가 관련된 요청만 삭제할 수 있습니다.")
    if row["status"] == "pending":
        raise HTTPException(status_code=400, detail="대기 중인 요청은 응답 후 삭제할 수 있습니다.")
    hidden_column = "requester_hidden" if row["requester_id"] == teacher_id else "responder_hidden"
    connection.execute(
        f"UPDATE swap_requests SET {hidden_column} = 1 WHERE id = ?",
        (swap_request_id,),
    )
    return _serialize_swap_request(_fetch_swap_request(connection, swap_request_id))


def cancel_user_swap_request(
    connection: sqlite3.Connection,
    teacher_id: int,
    swap_request_id: int,
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    row = connection.execute(
        """
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.id = ?
        """,
        (swap_request_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="교체 요청을 찾지 못했습니다.")
    if teacher_id not in {row["requester_id"], row["responder_id"]}:
        raise HTTPException(status_code=403, detail="이 교체 요청을 취소할 권한이 없습니다.")
    if row["status"] not in {"pending", "accepted"}:
        raise HTTPException(status_code=400, detail="대기 중이거나 확정된 교체만 취소할 수 있습니다.")
    if row["status"] == "pending" and row["requester_id"] != teacher_id:
        raise HTTPException(status_code=400, detail="대기 중인 교체 요청은 요청자만 취소할 수 있습니다.")

    actor_name = row["requester_name"] if teacher_id == row["requester_id"] else row["responder_name"]
    other_teacher_id = row["responder_id"] if teacher_id == row["requester_id"] else row["requester_id"]
    cancelled_at = format_dt(now_local())
    connection.execute(
        """
        UPDATE swap_requests
        SET status = 'cancelled', cancelled_at = ?, responded_at = ?, response_note = ?
        WHERE id = ?
        """,
        (cancelled_at, cancelled_at, f"{actor_name} 선생님이 교체 요청을 취소했습니다.", swap_request_id),
    )
    add_swap_history(
        connection,
        swap_request_id,
        "cancelled_by_teacher",
        teacher_id,
        {"actor_name": actor_name, "previous_status": row["status"]},
    )
    create_notification(
        connection,
        other_teacher_id,
        "swap",
        "교체 요청 취소",
        f"{actor_name} 선생님이 수업 교체 요청을 취소했습니다.",
        {"swap_request_id": swap_request_id},
    )
    updated = connection.execute(
        """
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.id = ?
        """,
        (swap_request_id,),
    ).fetchone()
    return _serialize_swap_request(updated)


def respond_to_coverage_request(
    connection: sqlite3.Connection,
    teacher_id: int,
    coverage_request_id: int,
    accept: bool,
    note: str,
) -> dict[str, Any]:
    expire_pending_coverage_requests(connection)
    row = connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.id = ?
        """,
        (coverage_request_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="보강 요청을 찾지 못했습니다.")
    if row["responder_id"] != teacher_id:
        raise HTTPException(status_code=403, detail="이 요청에 응답할 권한이 없습니다.")
    if row["status"] != "pending":
        raise HTTPException(status_code=400, detail="이미 처리된 보강 요청입니다.")

    if accept:
        calendar_day = _get_calendar_day(connection, row["class_date"])
        if not calendar_day or not calendar_day["is_school_day"]:
            raise HTTPException(status_code=400, detail="해당 날짜는 수업일이 아닙니다.")
        active_swaps = _load_active_requests_in_range(connection, row["class_date"], row["class_date"])
        if any((teacher_id, row["class_date"], row["period"]) in _request_lock_points(item) for item in active_swaps):
            raise HTTPException(status_code=400, detail="현재 이 시간에는 보강을 수락할 수 없습니다.")
        other_coverage = [
            item
            for item in _load_active_coverage_requests_in_range(connection, row["class_date"], row["class_date"])
            if item["id"] != coverage_request_id
        ]
        coverage_incoming, coverage_outgoing = _build_personal_coverage_maps(other_coverage)
        accepted_swaps = [item for item in active_swaps if item["status"] == "accepted"]
        incoming, outgoing = _build_personal_swap_maps(accepted_swaps)
        cell = _slot_for_personal_view(
            _load_base_slots(connection),
            incoming,
            outgoing,
            teacher_id,
            row["class_date"],
            calendar_day["weekday"],
            row["period"],
            coverage_incoming,
            coverage_outgoing,
        )
        if _is_busy(cell):
            raise HTTPException(status_code=400, detail="현재 이 시간에는 보강을 수락할 수 없습니다.")

    action = "accepted" if accept else "rejected"
    connection.execute(
        """
        UPDATE coverage_requests
        SET status = ?, responded_at = ?, response_note = ?
        WHERE id = ?
        """,
        (action, format_dt(now_local()), note.strip(), coverage_request_id),
    )
    if accept:
        create_notification(
            connection,
            row["requester_id"],
            "coverage",
            "보강 요청 수락",
            f"{row['responder_name']} 선생님이 보강 요청을 수락했습니다.",
            {"coverage_request_id": coverage_request_id},
        )
        create_notification(
            connection,
            row["responder_id"],
            "coverage",
            "보강 확정",
            f"{row['class_date']} {row['period']}교시 보강이 확정되었습니다.",
            {"coverage_request_id": coverage_request_id},
        )
    else:
        create_notification(
            connection,
            row["requester_id"],
            "coverage",
            "보강 요청 거절",
            f"{row['responder_name']} 선생님이 보강 요청을 거절했습니다.",
            {"coverage_request_id": coverage_request_id},
        )

    updated = connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.id = ?
        """,
        (coverage_request_id,),
    ).fetchone()
    return _serialize_coverage_request(updated)


def get_teacher_month_schedule(connection: sqlite3.Connection, teacher_id: int, month: str) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    return _teacher_month_schedule(connection, teacher_id, month)


def get_school_month_schedule(connection: sqlite3.Connection, month: str) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    teachers = connection.execute(
        "SELECT id, display_name FROM teachers WHERE is_active = 1 AND role = 'teacher' ORDER BY display_name"
    ).fetchall()
    teacher_months = {teacher["id"]: _teacher_month_schedule(connection, teacher["id"], month) for teacher in teachers}
    days: list[dict[str, Any]] = []
    if not teachers:
        return {"month": month, "days": []}

    sample_days = teacher_months[teachers[0]["id"]]["days"]
    for day_index, day in enumerate(sample_days):
        teacher_rows = []
        for teacher in teachers:
            teacher_day = teacher_months[teacher["id"]]["days"][day_index]
            teacher_rows.append(
                {
                    "teacher_id": teacher["id"],
                    "teacher_name": teacher["display_name"],
                    "periods": teacher_day["periods"],
                }
            )
        days.append(
            {
                "date": day["date"],
                "weekday": day["weekday"],
                "day_label": day["day_label"],
                "is_school_day": day["is_school_day"],
                "kind": day["kind"],
                "label": day["label"],
                "teachers": teacher_rows,
            }
        )
    return {"month": month, "days": days}


def find_swap_candidates(
    connection: sqlite3.Connection,
    requester_id: int,
    source_date_raw: str,
    source_period: int,
    week_offset: int = 0,
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    if week_offset not in {0, 1}:
        raise HTTPException(status_code=400, detail="교체 후보는 이번 주 또는 다음 주만 조회할 수 있습니다.")
    source_date = parse_date(source_date_raw)
    if source_date < date.today():
        raise HTTPException(status_code=400, detail="지난 날짜의 수업은 교체 요청을 만들 수 없습니다.")
    _ensure_swap_deadline_is_open(source_date.isoformat(), source_date.isoformat())
    source_slot = _base_class_slot_or_error(connection, requester_id, source_date.isoformat(), source_period)
    source_calendar_day = _get_calendar_day(connection, source_date.isoformat())
    if not source_calendar_day or not source_calendar_day["is_school_day"]:
        raise HTTPException(status_code=400, detail="해당 날짜는 수업일이 아닙니다.")

    source_week_start, source_week_end = _week_bounds(source_date)
    target_week_start = source_week_start + timedelta(days=week_offset * 7)
    target_week_end = source_week_end + timedelta(days=week_offset * 7)
    range_start = min(source_week_start, target_week_start)
    range_end = max(source_week_end, target_week_end)
    base_slots = _load_base_slots(connection)
    active_rows = _load_active_requests_in_range(connection, range_start.isoformat(), range_end.isoformat())
    active_coverage_rows = _load_active_coverage_requests_in_range(
        connection,
        range_start.isoformat(),
        range_end.isoformat(),
    )
    accepted_rows = [row for row in active_rows if row["status"] == "accepted"]
    incoming, outgoing = _build_personal_swap_maps(accepted_rows)
    active_lock_rows = [row for row in active_rows if row["status"] in ACTIVE_SWAP_STATUSES]

    requester_source_lock = {
        (requester_id, source_date.isoformat(), source_period),
    }
    for row in active_lock_rows:
        if _request_lock_points(row) & requester_source_lock:
            if row["status"] == "accepted":
                raise HTTPException(
                    status_code=400,
                    detail=f"이미 확정된 교체에 포함된 수업은 다시 교체할 수 없습니다. {_swap_lock_message(row)}",
                )
            raise HTTPException(
                status_code=400,
                detail=f"선택한 수업은 이미 다른 교체 요청과 겹칩니다. {_swap_lock_message(row)}",
            )
    for row in active_coverage_rows:
        if _coverage_lock_points(row) & requester_source_lock:
            raise HTTPException(
                status_code=400,
                detail=f"선택한 수업은 이미 보강 요청과 겹칩니다. {_coverage_lock_message(row)}",
            )

    candidate_rows = connection.execute(
        """
        SELECT
            ts.*,
            t.display_name AS teacher_name
        FROM timetable_slots ts
        JOIN teachers t ON t.id = ts.teacher_id
        WHERE ts.class_code = ?
          AND ts.slot_type = 'class'
          AND ts.teacher_id != ?
        ORDER BY ts.weekday, ts.period, t.display_name
        """,
        (source_slot["class_code"], requester_id),
    ).fetchall()

    candidates = []
    for row in candidate_rows:
        candidate_date = target_week_start + timedelta(days=row["weekday"])
        if candidate_date < date.today():
            continue
        try:
            _ensure_swap_deadline_is_open(source_date.isoformat(), candidate_date.isoformat())
        except HTTPException:
            continue
        calendar_day = _get_calendar_day(connection, candidate_date.isoformat())
        if not calendar_day or not calendar_day["is_school_day"]:
            continue

        requester_target_cell = _slot_for_personal_view(
            base_slots,
            incoming,
            outgoing,
            requester_id,
            candidate_date.isoformat(),
            row["weekday"],
            row["period"],
        )
        responder_source_cell = _slot_for_personal_view(
            base_slots,
            incoming,
            outgoing,
            row["teacher_id"],
            source_date.isoformat(),
            source_calendar_day["weekday"],
            source_period,
        )
        if _is_busy(requester_target_cell) or _is_busy(responder_source_cell):
            continue

        proposed = {
            "requester_id": requester_id,
            "responder_id": row["teacher_id"],
            "source_date": source_date.isoformat(),
            "source_period": source_period,
            "target_date": candidate_date.isoformat(),
            "target_period": row["period"],
        }
        proposed_points = _request_lock_points(proposed)
        if any(_request_lock_points(active_row) & proposed_points for active_row in active_lock_rows):
            continue
        if any(_coverage_lock_points(active_row) & proposed_points for active_row in active_coverage_rows):
            continue

        candidates.append(
            {
                "teacher_id": row["teacher_id"],
                "teacher_name": row["teacher_name"],
                "target_date": candidate_date.isoformat(),
                "target_weekday": row["weekday"],
                "target_day_label": DAY_LABELS[row["weekday"]],
                "target_period": row["period"],
                "class_code": row["class_code"],
                "subject": row["subject"],
            }
        )

    return {
        "source": {
            "date": source_date.isoformat(),
            "weekday": source_calendar_day["weekday"],
            "day_label": DAY_LABELS[source_calendar_day["weekday"]],
            "period": source_period,
            "class_code": source_slot["class_code"],
            "subject": source_slot["subject"],
        },
        "week": {
            "offset": week_offset,
            "label": "이번 주" if week_offset == 0 else "다음 주",
            "start_date": target_week_start.isoformat(),
            "end_date": target_week_end.isoformat(),
        },
        "candidates": candidates,
    }


def _schedule_debug_api_check(label: str, callback) -> dict[str, Any]:
    try:
        payload = callback()
        return {"label": label, "ok": True, **payload}
    except HTTPException as exc:
        return {"label": label, "ok": False, "error": exc.detail}


def _debug_swap_lock_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "type": "swap",
        "id": row["id"],
        "status": row["status"],
        "message": _swap_lock_message(row),
        "source_date": row["source_date"],
        "source_period": row["source_period"],
        "target_date": row["target_date"],
        "target_period": row["target_period"],
        "requester_name": row["requester_name"],
        "responder_name": row["responder_name"],
    }


def _debug_coverage_lock_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "type": "coverage",
        "id": row["id"],
        "status": row["status"],
        "message": _coverage_lock_message(row),
        "class_date": row["class_date"],
        "period": row["period"],
        "requester_name": row["requester_name"],
        "responder_name": row["responder_name"],
    }


def get_schedule_debug_report(
    connection: sqlite3.Connection,
    teacher_id: int,
    target_date_raw: str,
    period: int,
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    teacher = get_user_by_id(connection, teacher_id)
    if not teacher:
        raise HTTPException(status_code=404, detail="교사를 찾지 못했습니다.")

    target_date = parse_date(target_date_raw).isoformat()
    calendar_day = _get_calendar_day(connection, target_date)
    if not calendar_day:
        raise HTTPException(status_code=404, detail="학사일정에 없는 날짜입니다.")

    day_schedule = get_teacher_day_schedule(connection, teacher_id, target_date)
    selected_cell = next((cell for cell in day_schedule.get("periods", []) if cell["period"] == period), None)
    if not selected_cell and calendar_day["weekday"] <= 4:
        selected_cell = {
            "period": period,
            "status": "free",
            "effective": None,
            "original": None,
        }

    point = (teacher_id, target_date, period)
    active_swaps = _load_active_requests_in_range(connection, target_date, target_date)
    active_coverage = _load_active_coverage_requests_in_range(connection, target_date, target_date)
    swap_locks = [row for row in active_swaps if point in _request_lock_points(row)]
    coverage_locks = [row for row in active_coverage if point in _coverage_lock_points(row)]

    issues: list[dict[str, str]] = []
    if not calendar_day["is_school_day"]:
        issues.append({"level": "error", "message": "선택한 날짜는 수업일이 아닙니다."})
    elif calendar_day["weekday"] > 4:
        issues.append({"level": "error", "message": "주말은 교체·보강 대상이 아닙니다."})
    elif period < 1 or period > DAY_PERIOD_LIMITS[calendar_day["weekday"]]:
        issues.append({"level": "error", "message": "해당 요일에 없는 교시입니다."})

    status = selected_cell["status"] if selected_cell else "free"
    if status != "class":
        issues.append({"level": "info", "message": "선택 교시는 정규수업이 아니므로 교체·보강 신청 출발점이 아닙니다."})
    if any(row["status"] == "accepted" for row in swap_locks):
        issues.append({"level": "error", "message": "이미 확정된 교체에 포함된 교시라 재교체할 수 없습니다."})
    elif swap_locks:
        issues.append({"level": "warning", "message": "대기 중인 교체 요청과 겹쳐 현재 잠금 상태입니다."})
    if coverage_locks:
        issues.append({"level": "warning", "message": "대기/확정 보강 요청과 겹쳐 현재 잠금 상태입니다."})
    if not issues:
        issues.append({"level": "ok", "message": "현재 선택 교시에 즉시 감지된 잠금이나 일정 오류가 없습니다."})

    api_checks: list[dict[str, Any]] = []
    def availability_check() -> dict[str, Any]:
        payload = get_available_coverage_teachers(connection, target_date, period)
        return {
            "available_count": len(payload["available_teachers"]),
            "busy_count": len(payload["busy_teachers"]),
        }

    def weekly_coverage_check(week_offset: int) -> dict[str, Any]:
        payload = get_weekly_coverage_candidates(connection, teacher_id, target_date, period, week_offset)
        return {
            "available_count": payload["available_count"],
            "busy_count": payload["busy_count"],
        }

    if calendar_day["is_school_day"] and calendar_day["weekday"] <= 4 and 1 <= period <= DAY_PERIOD_LIMITS[calendar_day["weekday"]]:
        api_checks.append(
            _schedule_debug_api_check(
                "현재 교시 보강 가능 교사",
                availability_check,
            )
        )
    for week_offset, label in [(0, "이번 주 교체 후보"), (1, "다음 주 교체 후보")]:
        api_checks.append(
            _schedule_debug_api_check(
                label,
                lambda week_offset=week_offset: {
                    "candidate_count": len(find_swap_candidates(connection, teacher_id, target_date, period, week_offset)["candidates"])
                },
            )
        )
    for week_offset, label in [(0, "이번 주 보강 후보"), (1, "다음 주 보강 후보")]:
        api_checks.append(
            _schedule_debug_api_check(
                label,
                lambda week_offset=week_offset: weekly_coverage_check(week_offset),
            )
        )

    return {
        "teacher": serialize_user(teacher),
        "date": target_date,
        "period": period,
        "day": {
            "weekday": calendar_day["weekday"],
            "day_label": DAY_LABELS[calendar_day["weekday"]],
            "is_school_day": bool(calendar_day["is_school_day"]),
            "kind": calendar_day["kind"],
            "label": calendar_day["label"],
        },
        "selected_cell": selected_cell,
        "issues": issues,
        "locks": {
            "swaps": [_debug_swap_lock_payload(row) for row in swap_locks],
            "coverage": [_debug_coverage_lock_payload(row) for row in coverage_locks],
        },
        "api_checks": api_checks,
    }


def _event_date_range(start_date_raw: str, end_date_raw: str) -> list[date]:
    start_date = parse_date(start_date_raw)
    end_date = parse_date(end_date_raw)
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="종료일은 시작일보다 빠를 수 없습니다.")
    if (end_date - start_date).days > 30:
        raise HTTPException(status_code=400, detail="행사 보강 계획은 한 번에 최대 31일까지만 조회할 수 있습니다.")
    return [start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)]


def preview_event_coverage_plan(
    connection: sqlite3.Connection,
    title: str,
    start_date_raw: str,
    end_date_raw: str,
    absent_teacher_ids: list[int],
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    absent_ids = sorted(set(absent_teacher_ids))
    if not absent_ids:
        raise HTTPException(status_code=400, detail="부재 교사를 1명 이상 선택해 주세요.")
    dates = _event_date_range(start_date_raw, end_date_raw)
    placeholders = ",".join("?" for _ in absent_ids)
    absent_teachers = connection.execute(
        f"""
        SELECT id, display_name, username
        FROM teachers
        WHERE id IN ({placeholders}) AND is_active = 1 AND role = 'teacher'
        ORDER BY display_name
        """,
        absent_ids,
    ).fetchall()
    if len(absent_teachers) != len(absent_ids):
        raise HTTPException(status_code=400, detail="선택한 부재 교사 중 활성 교사가 아닌 계정이 있습니다.")
    absent_id_set = set(absent_ids)
    absent_teacher_map = {row["id"]: row for row in absent_teachers}

    affected_slots: list[dict[str, Any]] = []
    skipped_days: list[dict[str, Any]] = []
    for current_date in dates:
        date_text = current_date.isoformat()
        calendar_day = _get_calendar_day(connection, date_text)
        if not calendar_day or not calendar_day["is_school_day"] or calendar_day["weekday"] > 4:
            skipped_days.append(
                {
                    "date": date_text,
                    "reason": calendar_day["label"] if calendar_day and calendar_day["label"] else "수업일이 아닙니다.",
                }
            )
            continue
        for teacher_id in absent_ids:
            source_payload = get_coverage_source_classes(connection, teacher_id, date_text)
            for source in source_payload["sources"]:
                availability = get_available_coverage_teachers(connection, date_text, source["period"])
                candidates = [
                    candidate
                    for candidate in availability["available_teachers"]
                    if candidate["teacher_id"] not in absent_id_set and candidate["teacher_id"] != teacher_id
                ]
                candidates.sort(key=lambda item: (item.get("day_busy_count", 0), item.get("day_class_count", 0), item["teacher_name"]))
                recommended = candidates[0] if candidates else None
                affected_slots.append(
                    {
                        "id": f"{teacher_id}-{date_text}-{source['period']}",
                        "requester_id": teacher_id,
                        "requester_name": absent_teacher_map[teacher_id]["display_name"],
                        "class_date": date_text,
                        "weekday": source["weekday"],
                        "day_label": source["day_label"],
                        "period": source["period"],
                        "class_code": source["class_code"],
                        "subject": source["subject"],
                        "locked": source["locked"],
                        "can_request": source["can_request"],
                        "candidate_count": len(candidates),
                        "recommended_teacher_id": recommended["teacher_id"] if recommended else None,
                        "recommended_teacher_name": recommended["teacher_name"] if recommended else None,
                        "candidates": candidates,
                    }
                )

    assignable_slots = [slot for slot in affected_slots if slot["can_request"] and slot["candidate_count"] > 0]
    return {
        "title": title.strip(),
        "start_date": dates[0].isoformat(),
        "end_date": dates[-1].isoformat(),
        "absent_teachers": [
            {"teacher_id": row["id"], "teacher_name": row["display_name"], "username": row["username"]}
            for row in absent_teachers
        ],
        "affected_slots": affected_slots,
        "skipped_days": skipped_days,
        "summary": {
            "absent_teacher_count": len(absent_teachers),
            "affected_slot_count": len(affected_slots),
            "assignable_slot_count": len(assignable_slots),
            "no_candidate_count": len([slot for slot in affected_slots if slot["candidate_count"] == 0]),
            "locked_slot_count": len([slot for slot in affected_slots if slot["locked"] or not slot["can_request"]]),
        },
    }


def create_event_coverage_requests(
    connection: sqlite3.Connection,
    title: str,
    assignments: list[dict[str, Any]],
) -> dict[str, Any]:
    if not assignments:
        raise HTTPException(status_code=400, detail="보강 요청으로 전송할 배정이 없습니다.")
    created: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for assignment in assignments:
        try:
            request_row = create_coverage_request(
                connection,
                assignment["requester_id"],
                assignment["class_date"],
                assignment["period"],
                assignment["responder_id"],
            )
            created.append(request_row)
        except HTTPException as exc:
            errors.append(
                {
                    "requester_id": assignment["requester_id"],
                    "class_date": assignment["class_date"],
                    "period": assignment["period"],
                    "responder_id": assignment["responder_id"],
                    "error": exc.detail,
                }
            )
    return {
        "title": title.strip(),
        "created": created,
        "errors": errors,
        "summary": {
            "requested_count": len(assignments),
            "created_count": len(created),
            "error_count": len(errors),
        },
    }


def _swap_candidate_week_offset(source_date: str, target_date: str) -> int:
    source_week_start, _ = _week_bounds(parse_date(source_date))
    target_week_start, _ = _week_bounds(parse_date(target_date))
    week_delta = (target_week_start - source_week_start).days
    if week_delta == 0:
        return 0
    if week_delta == 7:
        return 1
    raise HTTPException(status_code=400, detail="교체 요청은 선택한 수업의 이번 주 또는 다음 주 후보로만 신청할 수 있습니다.")


def create_swap_request(
    connection: sqlite3.Connection,
    requester_id: int,
    source_date: str,
    source_period: int,
    target_date: str,
    target_period: int,
) -> dict[str, Any]:
    week_offset = _swap_candidate_week_offset(source_date, target_date)
    candidates_payload = find_swap_candidates(connection, requester_id, source_date, source_period, week_offset)
    matched_candidate = next(
        (
            item
            for item in candidates_payload["candidates"]
            if item["target_date"] == target_date and item["target_period"] == target_period
        ),
        None,
    )
    if matched_candidate is None:
        raise HTTPException(status_code=400, detail="선택한 교체 후보는 현재 유효하지 않습니다.")

    source_slot = _base_class_slot_or_error(connection, requester_id, source_date, source_period)
    responder_id = matched_candidate["teacher_id"]
    target_slot = _base_class_slot_or_error(connection, responder_id, target_date, target_period)
    expires_at = _swap_expires_at(source_date, target_date)
    _ensure_swap_deadline_is_open(source_date, target_date)
    requester = get_user_by_id(connection, requester_id)
    responder = get_user_by_id(connection, responder_id)
    if not requester or not responder:
        raise HTTPException(status_code=404, detail="교사를 찾지 못했습니다.")

    created_at = format_dt(now_local())
    connection.execute(
        """
        INSERT INTO swap_requests (
            requester_id, responder_id, source_teacher_id, target_teacher_id,
            source_date, target_date, source_weekday, target_weekday,
            source_period, target_period, source_class_code, target_class_code,
            source_subject, target_subject, status, expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """,
        (
            requester_id,
            responder_id,
            requester_id,
            responder_id,
            source_date,
            target_date,
            parse_date(source_date).weekday(),
            parse_date(target_date).weekday(),
            source_period,
            target_period,
            source_slot["class_code"],
            target_slot["class_code"],
            source_slot["subject"],
            target_slot["subject"],
            expires_at,
            created_at,
        ),
    )
    request_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    add_swap_history(
        connection,
        request_id,
        "requested",
        requester_id,
        {
            "source_date": source_date,
            "source_period": source_period,
            "target_date": target_date,
            "target_period": target_period,
        },
    )
    create_notification(
        connection,
        responder_id,
        "swap",
        "새 교체 요청",
        f"{requester['display_name']} 선생님이 {source_date} {source_period}교시 수업 교체를 요청했습니다.",
        {"swap_request_id": request_id},
    )
    create_notification(
        connection,
        requester_id,
        "swap",
        "교체 요청 전송",
        f"{responder['display_name']} 선생님에게 교체 요청을 보냈습니다.",
        {"swap_request_id": request_id},
    )
    row = connection.execute(
        """
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.id = ?
        """,
        (request_id,),
    ).fetchone()
    return _serialize_swap_request(row)


def list_swap_requests_for_user(connection: sqlite3.Connection, teacher_id: int) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    rows = connection.execute(
        """
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.requester_id = ? OR sr.responder_id = ?
        ORDER BY sr.created_at DESC
        """,
        (teacher_id, teacher_id),
    ).fetchall()
    received = []
    sent = []
    status_received = []
    status_sent = []
    for row in rows:
        serialized = _serialize_swap_request(row)
        if row["responder_id"] == teacher_id and (
            not row["responder_hidden"] or row["status"] in ACTIVE_SWAP_STATUSES
        ):
            received.append(serialized)
            status_received.append(serialized)
        if row["requester_id"] == teacher_id and (
            not row["requester_hidden"] or row["status"] in ACTIVE_SWAP_STATUSES
        ):
            status_sent.append(serialized)
        if row["requester_id"] == teacher_id and not row["requester_hidden"]:
            sent.append(serialized)
    return {
        "received": received,
        "sent": sent,
        "status_received": status_received,
        "status_sent": status_sent,
    }


def dismiss_sent_coverage_request(
    connection: sqlite3.Connection,
    teacher_id: int,
    coverage_request_id: int,
) -> dict[str, Any]:
    row = _fetch_coverage_request(connection, coverage_request_id)
    if not row:
        raise HTTPException(status_code=404, detail="보강 요청을 찾지 못했습니다.")
    if row["requester_id"] != teacher_id and row["responder_id"] != teacher_id:
        raise HTTPException(status_code=403, detail="내가 관련된 요청만 삭제할 수 있습니다.")
    if row["status"] == "pending":
        raise HTTPException(status_code=400, detail="대기 중인 요청은 응답 후 삭제할 수 있습니다.")
    hidden_column = "requester_hidden" if row["requester_id"] == teacher_id else "responder_hidden"
    connection.execute(
        f"UPDATE coverage_requests SET {hidden_column} = 1 WHERE id = ?",
        (coverage_request_id,),
    )
    return _serialize_coverage_request(_fetch_coverage_request(connection, coverage_request_id))


def cancel_user_coverage_request(
    connection: sqlite3.Connection,
    teacher_id: int,
    coverage_request_id: int,
) -> dict[str, Any]:
    expire_pending_coverage_requests(connection)
    row = connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.id = ?
        """,
        (coverage_request_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="보강 요청을 찾지 못했습니다.")
    if teacher_id not in {row["requester_id"], row["responder_id"]}:
        raise HTTPException(status_code=403, detail="이 보강 요청을 취소할 권한이 없습니다.")
    if row["status"] not in {"pending", "accepted"}:
        raise HTTPException(status_code=400, detail="대기 중이거나 확정된 보강만 취소할 수 있습니다.")
    if row["status"] == "pending" and row["requester_id"] != teacher_id:
        raise HTTPException(status_code=400, detail="대기 중인 보강 요청은 요청자만 취소할 수 있습니다.")

    actor_name = row["requester_name"] if teacher_id == row["requester_id"] else row["responder_name"]
    other_teacher_id = row["responder_id"] if teacher_id == row["requester_id"] else row["requester_id"]
    cancelled_at = format_dt(now_local())
    connection.execute(
        """
        UPDATE coverage_requests
        SET status = 'cancelled', responded_at = ?, response_note = ?
        WHERE id = ?
        """,
        (cancelled_at, f"{actor_name} 선생님이 보강 요청을 취소했습니다.", coverage_request_id),
    )
    create_notification(
        connection,
        other_teacher_id,
        "coverage",
        "보강 요청 취소",
        f"{actor_name} 선생님이 보강 요청을 취소했습니다.",
        {"coverage_request_id": coverage_request_id},
    )
    updated = connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.id = ?
        """,
        (coverage_request_id,),
    ).fetchone()
    return _serialize_coverage_request(updated)


def _validate_swap_acceptance(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    swap_request_id: int,
) -> None:
    source_day = _get_calendar_day(connection, row["source_date"])
    target_day = _get_calendar_day(connection, row["target_date"])
    if not source_day or not source_day["is_school_day"]:
        raise HTTPException(status_code=400, detail="교체 원 수업 날짜가 현재 수업일이 아니어서 수락할 수 없습니다.")
    if not target_day or not target_day["is_school_day"]:
        raise HTTPException(status_code=400, detail="교체 상대 수업 날짜가 현재 수업일이 아니어서 수락할 수 없습니다.")

    base_slots = _load_base_slots(connection)
    for issue in [
        _impact_base_slot_issue(
            base_slots,
            row["source_teacher_id"],
            row["source_weekday"],
            row["source_period"],
            row["source_class_code"],
            row["source_subject"],
            row["requester_name"],
        ),
        _impact_base_slot_issue(
            base_slots,
            row["target_teacher_id"],
            row["target_weekday"],
            row["target_period"],
            row["target_class_code"],
            row["target_subject"],
            row["responder_name"],
        ),
    ]:
        if issue:
            raise HTTPException(status_code=400, detail=f"현재 시간표가 변경되어 교체를 수락할 수 없습니다. {issue}")

    range_start = min(row["source_date"], row["target_date"])
    range_end = max(row["source_date"], row["target_date"])
    active_swaps = [
        item
        for item in _load_active_requests_in_range(connection, range_start, range_end)
        if item["id"] != swap_request_id
    ]
    active_coverage = _load_active_coverage_requests_in_range(connection, range_start, range_end)
    proposed_points = _request_lock_points(row)
    if any(_request_lock_points(item) & proposed_points for item in active_swaps):
        raise HTTPException(status_code=400, detail="현재 다른 교체 요청과 시간이 겹쳐 수락할 수 없습니다.")
    if any(_coverage_lock_points(item) & proposed_points for item in active_coverage):
        raise HTTPException(status_code=400, detail="현재 보강 요청과 시간이 겹쳐 수락할 수 없습니다.")

    accepted_swaps = [item for item in active_swaps if item["status"] == "accepted"]
    incoming, outgoing = _build_personal_swap_maps(accepted_swaps)
    coverage_incoming, coverage_outgoing = _build_personal_coverage_maps(active_coverage)
    requester_target_cell = _slot_for_personal_view(
        base_slots,
        incoming,
        outgoing,
        row["requester_id"],
        row["target_date"],
        row["target_weekday"],
        row["target_period"],
        coverage_incoming,
        coverage_outgoing,
    )
    responder_source_cell = _slot_for_personal_view(
        base_slots,
        incoming,
        outgoing,
        row["responder_id"],
        row["source_date"],
        row["source_weekday"],
        row["source_period"],
        coverage_incoming,
        coverage_outgoing,
    )
    if _is_busy(requester_target_cell):
        raise HTTPException(status_code=400, detail="요청 교사가 상대 수업 시각에 현재 비어 있지 않아 수락할 수 없습니다.")
    if _is_busy(responder_source_cell):
        raise HTTPException(status_code=400, detail="상대 교사가 원 수업 시각에 현재 비어 있지 않아 수락할 수 없습니다.")


def respond_to_swap_request(
    connection: sqlite3.Connection,
    teacher_id: int,
    swap_request_id: int,
    accept: bool,
    note: str,
) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    row = connection.execute(
        """
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.id = ?
        """,
        (swap_request_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="교체 요청을 찾지 못했습니다.")
    if row["responder_id"] != teacher_id:
        raise HTTPException(status_code=403, detail="이 요청에 응답할 권한이 없습니다.")
    if row["status"] != "pending":
        raise HTTPException(status_code=400, detail="이미 처리된 교체 요청입니다.")

    if accept:
        _validate_swap_acceptance(connection, row, swap_request_id)

    action = "accepted" if accept else "rejected"
    connection.execute(
        """
        UPDATE swap_requests
        SET status = ?, responded_at = ?, response_note = ?
        WHERE id = ?
        """,
        (action, format_dt(now_local()), note.strip(), swap_request_id),
    )
    add_swap_history(connection, swap_request_id, action, teacher_id, {"note": note.strip()})

    if accept:
        create_notification(
            connection,
            row["requester_id"],
            "swap",
            "교체 요청 수락",
            f"{row['responder_name']} 선생님이 교체 요청을 수락했습니다.",
            {"swap_request_id": swap_request_id},
        )
        create_notification(
            connection,
            row["responder_id"],
            "swap",
            "교체 확정",
            "수업 교체가 확정되어 월간 시간표에 반영되었습니다.",
            {"swap_request_id": swap_request_id},
        )
    else:
        create_notification(
            connection,
            row["requester_id"],
            "swap",
            "교체 요청 거절",
            f"{row['responder_name']} 선생님이 교체 요청을 거절했습니다.",
            {"swap_request_id": swap_request_id},
        )
    updated = connection.execute(
        """
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.id = ?
        """,
        (swap_request_id,),
    ).fetchone()
    return _serialize_swap_request(updated)


def list_notifications(connection: sqlite3.Connection, teacher_id: int) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    connection.execute(
        "DELETE FROM notifications WHERE teacher_id = ? AND is_read = 1",
        (teacher_id,),
    )
    rows = connection.execute(
        """
        SELECT *
        FROM notifications
        WHERE teacher_id = ?
        ORDER BY created_at DESC
        LIMIT 100
        """,
        (teacher_id,),
    ).fetchall()
    return {
        "items": [
            {
                "id": row["id"],
                "category": row["category"],
                "title": row["title"],
                "message": row["message"],
                "is_read": bool(row["is_read"]),
                "created_at": row["created_at"],
                "payload": json.loads(row["payload_json"]) if row["payload_json"] else None,
            }
            for row in rows
        ]
    }


def mark_notifications_read(
    connection: sqlite3.Connection,
    teacher_id: int,
    notification_ids: list[int],
    mark_all: bool,
) -> None:
    if mark_all:
        connection.execute(
            "DELETE FROM notifications WHERE teacher_id = ?",
            (teacher_id,),
        )
        return
    if not notification_ids:
        return
    placeholders = ", ".join("?" for _ in notification_ids)
    connection.execute(
        f"""
        DELETE FROM notifications
        WHERE teacher_id = ? AND id IN ({placeholders})
        """,
        [teacher_id, *notification_ids],
    )


def delete_notifications(
    connection: sqlite3.Connection,
    teacher_id: int,
    notification_ids: list[int],
    delete_read: bool,
) -> None:
    if delete_read:
        connection.execute(
            "DELETE FROM notifications WHERE teacher_id = ? AND is_read = 1",
            (teacher_id,),
        )
        return
    if not notification_ids:
        return
    placeholders = ", ".join("?" for _ in notification_ids)
    connection.execute(
        f"""
        DELETE FROM notifications
        WHERE teacher_id = ? AND id IN ({placeholders})
        """,
        [teacher_id, *notification_ids],
    )


def list_admin_swap_requests(connection: sqlite3.Connection) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    swap_rows = connection.execute(
        """
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        ORDER BY sr.created_at DESC
        """
    ).fetchall()
    coverage_rows = connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        ORDER BY cr.created_at DESC
        """
    ).fetchall()
    history_rows = connection.execute(
        """
        SELECT
            sh.*,
            actor.display_name AS actor_name
        FROM swap_history sh
        LEFT JOIN teachers actor ON actor.id = sh.actor_id
        ORDER BY sh.created_at DESC
        LIMIT 300
        """
    ).fetchall()
    active_items: list[dict[str, Any]] = []
    for row in swap_rows:
        if row["status"] != "accepted":
            continue
        swap_dates = [row["source_date"], row["target_date"]]
        swap_class_codes = [row["source_class_code"], row["target_class_code"]]
        active_items.append(
            {
                "id": f"swap-{row['id']}",
                "type": "swap",
                "type_label": "교체",
                "request_id": row["id"],
                "status": row["status"],
                "requester_name": row["requester_name"],
                "responder_name": row["responder_name"],
                "date": row["source_date"],
                "dates": swap_dates,
                "period": row["source_period"],
                "source_date": row["source_date"],
                "source_period": row["source_period"],
                "source_class_code": row["source_class_code"],
                "source_subject": row["source_subject"],
                "target_date": row["target_date"],
                "target_period": row["target_period"],
                "target_class_code": row["target_class_code"],
                "target_subject": row["target_subject"],
                "class_codes": swap_class_codes,
                "subjects": [row["source_subject"], row["target_subject"]],
                "summary": (
                    f"{row['source_date']} {row['source_period']}교시 "
                    f"{row['source_class_code']} {row['source_subject']} ↔ "
                    f"{row['target_date']} {row['target_period']}교시 "
                    f"{row['target_class_code']} {row['target_subject']}"
                ),
                "created_at": row["created_at"],
                "responded_at": row["responded_at"],
            }
        )
    for row in coverage_rows:
        if row["status"] != "accepted":
            continue
        active_items.append(
            {
                "id": f"coverage-{row['id']}",
                "type": "coverage",
                "type_label": "보강",
                "request_id": row["id"],
                "status": row["status"],
                "requester_name": row["requester_name"],
                "responder_name": row["responder_name"],
                "date": row["class_date"],
                "dates": [row["class_date"]],
                "period": row["period"],
                "class_date": row["class_date"],
                "day_label": DAY_LABELS[row["weekday"]],
                "class_code": row["class_code"],
                "subject": row["subject"],
                "class_codes": [row["class_code"]],
                "subjects": [row["subject"]],
                "summary": (
                    f"{row['class_date']} {DAY_LABELS[row['weekday']]} {row['period']}교시 "
                    f"{row['class_code']} {row['subject']}"
                ),
                "created_at": row["created_at"],
                "responded_at": row["responded_at"],
            }
        )
    today_date = now_local().date()
    active_items.sort(
        key=lambda item: (
            date.fromisoformat(item["date"]) < today_date,
            date.fromisoformat(item["date"]).toordinal()
            if date.fromisoformat(item["date"]) >= today_date
            else -date.fromisoformat(item["date"]).toordinal(),
            item["period"],
            item["type_label"],
        )
    )
    return {
        "active": active_items,
        "requests": [_serialize_swap_request(row) for row in swap_rows],
        "coverage_requests": [_serialize_coverage_request(row) for row in coverage_rows],
        "history": [
            {
                "id": row["id"],
                "swap_request_id": row["swap_request_id"],
                "action": row["action"],
                "actor_name": row["actor_name"],
                "created_at": row["created_at"],
                "details": json.loads(row["details_json"]),
            }
            for row in history_rows
        ],
    }


def get_monthly_coverage_allowances(
    connection: sqlite3.Connection,
    month: str,
    rate: int,
) -> dict[str, Any]:
    expire_pending_coverage_requests(connection)
    try:
        year, month_number = [int(piece) for piece in month.split("-", 1)]
        month_start = date(year, month_number, 1)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="month는 YYYY-MM 형식이어야 합니다.") from exc
    if month_number == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month_number + 1, 1) - timedelta(days=1)
    if rate < 0:
        raise HTTPException(status_code=400, detail="보결 수당 단가는 0원 이상이어야 합니다.")

    rows = connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name,
            responder.username AS responder_username
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.status = 'accepted'
          AND cr.class_date BETWEEN ? AND ?
        ORDER BY responder.display_name, cr.class_date, cr.period
        """,
        (month_start.isoformat(), month_end.isoformat()),
    ).fetchall()

    teacher_map: dict[int, dict[str, Any]] = {}
    for row in rows:
        bucket = teacher_map.setdefault(
            row["responder_id"],
            {
                "teacher_id": row["responder_id"],
                "teacher_name": row["responder_name"],
                "username": row["responder_username"],
                "coverage_count": 0,
                "amount": 0,
                "details": [],
            },
        )
        bucket["coverage_count"] += 1
        bucket["amount"] = bucket["coverage_count"] * rate
        bucket["details"].append(
            {
                "id": row["id"],
                "class_date": row["class_date"],
                "weekday": row["weekday"],
                "day_label": DAY_LABELS[row["weekday"]],
                "period": row["period"],
                "class_code": row["class_code"],
                "subject": row["subject"],
                "requester_name": row["requester_name"],
                "responded_at": row["responded_at"],
            }
        )

    teachers = sorted(
        teacher_map.values(),
        key=lambda item: (-item["coverage_count"], item["teacher_name"]),
    )
    total_count = sum(item["coverage_count"] for item in teachers)
    return {
        "month": month,
        "month_start": month_start.isoformat(),
        "month_end": month_end.isoformat(),
        "rate": rate,
        "teachers": teachers,
        "summary": {
            "teacher_count": len(teachers),
            "coverage_count": total_count,
            "total_amount": total_count * rate,
        },
    }


def _impact_base_slot_issue(
    base_slots: dict[tuple[int, int, int], dict[str, Any]],
    teacher_id: int,
    weekday: int,
    period: int,
    expected_class_code: str,
    expected_subject: str,
    teacher_name: str,
) -> str | None:
    base = base_slots.get((teacher_id, weekday, period))
    if not base:
        return f"{teacher_name} 선생님의 원 시간표에서 해당 수업을 찾을 수 없습니다."
    if base["slot_type"] != "class":
        return f"{teacher_name} 선생님의 해당 교시는 정규수업이 아니라 {base['slot_type']} 상태입니다."
    if base["class_code"] != expected_class_code or base["subject"] != expected_subject:
        return (
            f"{teacher_name} 선생님의 원 수업이 {base['class_code']} {base['subject']}로 변경되었습니다."
        )
    return None


def _impact_request_summary(row: sqlite3.Row, request_type: str) -> dict[str, Any]:
    if request_type == "swap":
        return {
            "type": "swap",
            "type_label": "교체",
            "request_id": row["id"],
            "status": row["status"],
            "requester_name": row["requester_name"],
            "responder_name": row["responder_name"],
            "date": row["source_date"],
            "period": row["source_period"],
            "class_code": row["source_class_code"],
            "subject": row["source_subject"],
            "summary": (
                f"{row['source_date']} {row['source_period']}교시 "
                f"{row['source_class_code']} {row['source_subject']} ↔ "
                f"{row['target_date']} {row['target_period']}교시 "
                f"{row['target_class_code']} {row['target_subject']}"
            ),
        }
    return {
        "type": "coverage",
        "type_label": "보강",
        "request_id": row["id"],
        "status": row["status"],
        "requester_name": row["requester_name"],
        "responder_name": row["responder_name"],
        "date": row["class_date"],
        "period": row["period"],
        "class_code": row["class_code"],
        "subject": row["subject"],
        "summary": (
            f"{row['class_date']} {DAY_LABELS[row['weekday']]} {row['period']}교시 "
            f"{row['class_code']} {row['subject']}"
        ),
    }


def _impact_issue(row: sqlite3.Row, request_type: str, severity: str, message: str) -> dict[str, Any]:
    return {
        **_impact_request_summary(row, request_type),
        "severity": severity,
        "message": message,
    }


def _impact_request_short_label(request_type: str, row: sqlite3.Row) -> str:
    return f"{'교체' if request_type == 'swap' else '보강'} #{row['id']}"


def _impact_teacher_name_for_point(request_type: str, row: sqlite3.Row, teacher_id: int) -> str:
    if teacher_id == row["requester_id"]:
        return row["requester_name"]
    if teacher_id == row["responder_id"]:
        return row["responder_name"]
    return "해당 교사"


def _impact_inactive_teacher_issues(row: sqlite3.Row, request_type: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if "requester_is_active" in row.keys() and not row["requester_is_active"]:
        issues.append(
            _impact_issue(
                row,
                request_type,
                "error",
                f"요청자 {row['requester_name']} 선생님 계정이 현재 비활성화되어 있습니다.",
            )
        )
    if "responder_is_active" in row.keys() and not row["responder_is_active"]:
        issues.append(
            _impact_issue(
                row,
                request_type,
                "error",
                f"수락자 {row['responder_name']} 선생님 계정이 현재 비활성화되어 있습니다.",
            )
        )
    return issues


def _impact_lock_conflict_issues(
    swap_rows: list[sqlite3.Row],
    coverage_rows: list[sqlite3.Row],
) -> list[dict[str, Any]]:
    point_entries: dict[tuple[int, str, int], list[tuple[str, sqlite3.Row]]] = defaultdict(list)
    for row in swap_rows:
        for point in _request_lock_points(row):
            point_entries[point].append(("swap", row))
    for row in coverage_rows:
        for point in _coverage_lock_points(row):
            point_entries[point].append(("coverage", row))

    issues: list[dict[str, Any]] = []
    seen: set[tuple[str, int, tuple[int, str, int]]] = set()
    for point, entries in point_entries.items():
        if len(entries) < 2:
            continue
        teacher_id, target_date, period = point
        for request_type, row in entries:
            issue_key = (request_type, row["id"], point)
            if issue_key in seen:
                continue
            seen.add(issue_key)
            teacher_name = _impact_teacher_name_for_point(request_type, row, teacher_id)
            other_labels = [
                _impact_request_short_label(other_type, other_row)
                for other_type, other_row in entries
                if not (other_type == request_type and other_row["id"] == row["id"])
            ]
            issues.append(
                _impact_issue(
                    row,
                    request_type,
                    "error",
                    (
                        f"{teacher_name} 선생님의 {target_date} {period}교시에 "
                        f"확정된 다른 교체·보강과 일정이 겹칩니다: {', '.join(other_labels)}"
                    ),
                )
            )
    return issues


def check_schedule_impacts(connection: sqlite3.Connection) -> dict[str, Any]:
    expire_pending_swap_requests(connection)
    expire_pending_coverage_requests(connection)
    base_slots = _load_base_slots(connection)
    swap_rows = _load_active_requests_in_range(connection, "0001-01-01", "9999-12-31", ("accepted",))
    coverage_rows = _load_active_coverage_requests_in_range(connection, "0001-01-01", "9999-12-31", ("accepted",))
    issues: list[dict[str, Any]] = []
    issues.extend(_impact_lock_conflict_issues(swap_rows, coverage_rows))

    for row in swap_rows:
        issues.extend(_impact_inactive_teacher_issues(row, "swap"))
        source_day = _get_calendar_day(connection, row["source_date"])
        target_day = _get_calendar_day(connection, row["target_date"])
        if not source_day or not source_day["is_school_day"]:
            issues.append(_impact_issue(row, "swap", "error", "교체 원 수업 날짜가 현재 수업일이 아닙니다."))
        if not target_day or not target_day["is_school_day"]:
            issues.append(_impact_issue(row, "swap", "error", "교체 상대 수업 날짜가 현재 수업일이 아닙니다."))
        if source_day:
            issue = _impact_base_slot_issue(
                base_slots,
                row["source_teacher_id"],
                row["source_weekday"],
                row["source_period"],
                row["source_class_code"],
                row["source_subject"],
                row["requester_name"],
            )
            if issue:
                issues.append(_impact_issue(row, "swap", "warning", issue))
        if target_day:
            issue = _impact_base_slot_issue(
                base_slots,
                row["target_teacher_id"],
                row["target_weekday"],
                row["target_period"],
                row["target_class_code"],
                row["target_subject"],
                row["responder_name"],
            )
            if issue:
                issues.append(_impact_issue(row, "swap", "warning", issue))

        other_swaps = [item for item in swap_rows if item["id"] != row["id"]]
        incoming, outgoing = _build_personal_swap_maps(other_swaps)
        coverage_incoming, coverage_outgoing = _build_personal_coverage_maps(coverage_rows)
        if source_day and source_day["is_school_day"]:
            responder_source_cell = _slot_for_personal_view(
                base_slots,
                incoming,
                outgoing,
                row["responder_id"],
                row["source_date"],
                row["source_weekday"],
                row["source_period"],
                coverage_incoming,
                coverage_outgoing,
            )
            if _is_busy(responder_source_cell):
                issues.append(_impact_issue(row, "swap", "error", "상대 교사가 원 수업 시각에 현재 비어 있지 않습니다."))
        if target_day and target_day["is_school_day"]:
            requester_target_cell = _slot_for_personal_view(
                base_slots,
                incoming,
                outgoing,
                row["requester_id"],
                row["target_date"],
                row["target_weekday"],
                row["target_period"],
                coverage_incoming,
                coverage_outgoing,
            )
            if _is_busy(requester_target_cell):
                issues.append(_impact_issue(row, "swap", "error", "요청 교사가 상대 수업 시각에 현재 비어 있지 않습니다."))

    accepted_swaps_incoming, accepted_swaps_outgoing = _build_personal_swap_maps(swap_rows)
    for row in coverage_rows:
        issues.extend(_impact_inactive_teacher_issues(row, "coverage"))
        calendar_day = _get_calendar_day(connection, row["class_date"])
        if not calendar_day or not calendar_day["is_school_day"]:
            issues.append(_impact_issue(row, "coverage", "error", "보강 날짜가 현재 수업일이 아닙니다."))
            continue

        issue = _impact_base_slot_issue(
            base_slots,
            row["requester_id"],
            row["weekday"],
            row["period"],
            row["class_code"],
            row["subject"],
            row["requester_name"],
        )
        if issue:
            issues.append(_impact_issue(row, "coverage", "warning", issue))

        other_coverage = [item for item in coverage_rows if item["id"] != row["id"]]
        coverage_incoming, coverage_outgoing = _build_personal_coverage_maps(other_coverage)
        responder_cell = _slot_for_personal_view(
            base_slots,
            accepted_swaps_incoming,
            accepted_swaps_outgoing,
            row["responder_id"],
            row["class_date"],
            row["weekday"],
            row["period"],
            coverage_incoming,
            coverage_outgoing,
        )
        if _is_busy(responder_cell):
            issues.append(_impact_issue(row, "coverage", "error", "보강 담당 교사가 해당 시각에 현재 비어 있지 않습니다."))

    severity_order = {"error": 0, "warning": 1}
    issues.sort(key=lambda item: (severity_order.get(item["severity"], 9), item["date"], item["period"], item["type"]))
    return {
        "checked_at": format_dt(now_local()),
        "summary": {
            "accepted_swap_count": len(swap_rows),
            "accepted_coverage_count": len(coverage_rows),
            "issue_count": len(issues),
            "error_count": sum(1 for item in issues if item["severity"] == "error"),
            "warning_count": sum(1 for item in issues if item["severity"] == "warning"),
        },
        "issues": issues,
    }


def cancel_confirmed_swap(
    connection: sqlite3.Connection,
    actor_id: int,
    swap_request_id: int,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.id = ?
        """,
        (swap_request_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="교체 요청을 찾지 못했습니다.")
    if row["status"] != "accepted":
        raise HTTPException(status_code=400, detail="확정된 교체만 취소할 수 있습니다.")

    cancelled_at = format_dt(now_local())
    connection.execute(
        """
        UPDATE swap_requests
        SET status = 'cancelled', cancelled_at = ?, responded_at = ?
        WHERE id = ?
        """,
        (cancelled_at, cancelled_at, swap_request_id),
    )
    add_swap_history(connection, swap_request_id, "cancelled", actor_id, {"reason": "admin-rollback"})
    create_notification(
        connection,
        row["requester_id"],
        "swap",
        "확정된 교체 취소",
        "관리자가 확정된 수업 교체를 취소했습니다.",
        {"swap_request_id": swap_request_id},
    )
    create_notification(
        connection,
        row["responder_id"],
        "swap",
        "확정된 교체 취소",
        "관리자가 확정된 수업 교체를 취소했습니다.",
        {"swap_request_id": swap_request_id},
    )
    updated = connection.execute(
        """
        SELECT
            sr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM swap_requests sr
        JOIN teachers requester ON requester.id = sr.requester_id
        JOIN teachers responder ON responder.id = sr.responder_id
        WHERE sr.id = ?
        """,
        (swap_request_id,),
    ).fetchone()
    return _serialize_swap_request(updated)


def cancel_confirmed_coverage(
    connection: sqlite3.Connection,
    actor_id: int,
    coverage_request_id: int,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.id = ?
        """,
        (coverage_request_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="보강 요청을 찾지 못했습니다.")
    if row["status"] != "accepted":
        raise HTTPException(status_code=400, detail="확정된 보강만 취소할 수 있습니다.")

    cancelled_at = format_dt(now_local())
    connection.execute(
        """
        UPDATE coverage_requests
        SET status = 'cancelled', responded_at = ?, response_note = ?
        WHERE id = ?
        """,
        (cancelled_at, "관리자가 확정 보강을 취소했습니다.", coverage_request_id),
    )
    create_notification(
        connection,
        row["requester_id"],
        "coverage",
        "확정된 보강 취소",
        "관리자가 확정된 보강 배정을 취소했습니다.",
        {"coverage_request_id": coverage_request_id},
    )
    create_notification(
        connection,
        row["responder_id"],
        "coverage",
        "확정된 보강 취소",
        "관리자가 확정된 보강 배정을 취소했습니다.",
        {"coverage_request_id": coverage_request_id},
    )
    updated = connection.execute(
        """
        SELECT
            cr.*,
            requester.display_name AS requester_name,
            responder.display_name AS responder_name
        FROM coverage_requests cr
        JOIN teachers requester ON requester.id = cr.requester_id
        JOIN teachers responder ON responder.id = cr.responder_id
        WHERE cr.id = ?
        """,
        (coverage_request_id,),
    ).fetchone()
    return _serialize_coverage_request(updated)


def delete_admin_swap_request(connection: sqlite3.Connection, swap_request_id: int) -> None:
    row = connection.execute("SELECT status FROM swap_requests WHERE id = ?", (swap_request_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="교체 요청을 찾지 못했습니다.")
    if row["status"] == "accepted":
        raise HTTPException(status_code=400, detail="확정된 교체는 먼저 취소한 뒤 삭제할 수 있습니다.")
    connection.execute("DELETE FROM swap_requests WHERE id = ?", (swap_request_id,))


def delete_admin_coverage_request(connection: sqlite3.Connection, coverage_request_id: int) -> None:
    row = connection.execute("SELECT status FROM coverage_requests WHERE id = ?", (coverage_request_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="보강 요청을 찾지 못했습니다.")
    if row["status"] == "accepted":
        raise HTTPException(status_code=400, detail="확정된 보강은 먼저 취소한 뒤 삭제할 수 있습니다.")
    connection.execute("DELETE FROM coverage_requests WHERE id = ?", (coverage_request_id,))
