from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
import warnings
from zipfile import ZipFile

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.",
)

from fastapi.testclient import TestClient

from app.config import Settings
from app.db import db_session
from app.security import hash_password
from app.server import create_app


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"


class ClassSwapAppTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        temp_root = Path(self.temp_dir.name)
        self.settings = Settings(
            app_env="test",
            allow_origins=["http://localhost:8000"],
            secret_key="test-secret",
            session_cookie_name="test-session",
            session_max_age_seconds=3600,
            database_path=temp_root / "app.db",
            preview_dir=temp_root / "previews",
            template_path=FIXTURE_DIR / "주간시간표_표준양식.xlsx",
            default_admin_username="admin",
            default_admin_password="1234",
            default_teacher_password="1234",
        )
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _login(self, username: str, password: str = "1234") -> dict:
        response = self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["user"]

    def _logout(self) -> None:
        self.client.post("/api/auth/logout")

    def _insert_teacher(self, username: str, display_name: str, role: str = "teacher") -> int:
        with db_session(self.settings) as connection:
            connection.execute(
                """
                INSERT INTO teachers (
                    username, display_name, schedule_label, role, password_hash,
                    must_change_password, is_active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, 1, '2026-01-01T00:00:00', '2026-01-01T00:00:00')
                """,
                (
                    username,
                    display_name,
                    display_name,
                    role,
                    hash_password("1234"),
                ),
            )
            teacher_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        return teacher_id

    def _insert_slot(
        self,
        teacher_id: int,
        weekday: int,
        period: int,
        slot_type: str,
        class_code: str | None = None,
        subject: str | None = None,
        location_label: str | None = None,
    ) -> None:
        with db_session(self.settings) as connection:
            connection.execute(
                """
                INSERT INTO timetable_slots (
                    teacher_id, weekday, period, slot_type, class_code, subject,
                    location_label, duration, source_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    teacher_id,
                    weekday,
                    period,
                    slot_type,
                    class_code,
                    subject,
                    location_label,
                    f"{class_code or location_label or slot_type} {subject or ''}".strip(),
                ),
            )

    def _write_preview(self, preview_id: str, teachers: list[dict], slots: list[dict]) -> None:
        preview = {
            "uploaded_filename": f"{preview_id}.xlsx",
            "teachers": teachers,
            "slots": slots,
            "failed_cells": [],
            "warnings": [],
            "summary": {
                "teacher_count": len(teachers),
                "class_slot_count": sum(1 for slot in slots if slot["slot_type"] == "class"),
                "travel_slot_count": sum(1 for slot in slots if slot["slot_type"] == "travel"),
                "failed_cell_count": 0,
                "warning_count": 0,
            },
        }
        (self.settings.preview_dir / f"{preview_id}.json").write_text(
            json.dumps(preview, ensure_ascii=False),
            encoding="utf-8",
        )

    def _seed_swap_scenario(self) -> tuple[int, int, int]:
        alice_id = self._insert_teacher("alice", "Alice")
        bob_id = self._insert_teacher("bob", "Bob")
        carol_id = self._insert_teacher("carol", "Carol")

        self._insert_slot(alice_id, weekday=0, period=1, slot_type="class", class_code="101", subject="국어")
        self._insert_slot(bob_id, weekday=2, period=2, slot_type="class", class_code="101", subject="영어")
        self._insert_slot(carol_id, weekday=4, period=3, slot_type="class", class_code="101", subject="과학")

        self._login("admin", "1234")
        calendar_response = self.client.put(
            "/api/admin/calendar-settings",
            json={
                "semester_start": "2026-09-07",
                "semester_end": "2026-09-11",
                "special_days": [],
            },
        )
        self.assertEqual(calendar_response.status_code, 200, calendar_response.text)
        self._logout()

        return alice_id, bob_id, carol_id

    def test_health_and_forced_password_change(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["default_admin_username"], "admin")

        user = self._login("admin", "1234")
        self.assertTrue(user["must_change_password"])

        change_response = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "1234", "new_password": "5678"},
        )
        self.assertEqual(change_response.status_code, 200, change_response.text)
        self.assertFalse(change_response.json()["user"]["must_change_password"])

    def test_timetable_preview_with_real_fixture(self) -> None:
        self._login("admin", "1234")
        fixture_path = FIXTURE_DIR / "2026학년도_1학기_임시시간표_최종.xlsx"
        with fixture_path.open("rb") as file_handle:
            response = self.client.post(
                "/api/admin/timetable/preview",
                files={"file": (fixture_path.name, file_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        self.assertEqual(response.status_code, 200, response.text)
        preview = response.json()["preview"]
        self.assertEqual(preview["summary"]["teacher_count"], 39)
        self.assertEqual(preview["summary"]["failed_cell_count"], 0)
        self.assertGreater(preview["summary"]["class_slot_count"], 400)
        self.assertGreaterEqual(preview["summary"]["warning_count"], 1)

    def test_timetable_confirm_handles_missing_teacher_actions_and_reimport(self) -> None:
        alice_id = self._insert_teacher("alice", "Alice")
        bob_id = self._insert_teacher("bob", "Bob")
        carol_id = self._insert_teacher("carol", "Carol")
        self._insert_slot(bob_id, weekday=0, period=1, slot_type="class", class_code="101", subject="영어")
        self._insert_slot(carol_id, weekday=1, period=2, slot_type="class", class_code="102", subject="수학")

        self._write_preview(
            "sync-first",
            [
                {"row_index": 4, "raw_name": "Alice", "display_name": "Alice", "suggested_username": "alice"},
            ],
            [
                {
                    "teacher_row_index": 4,
                    "teacher_schedule_label": "Alice",
                    "teacher_display_name": "Alice",
                    "teacher_username": "alice",
                    "weekday": 0,
                    "day_label": "월",
                    "period": 1,
                    "slot_type": "class",
                    "class_code": "101",
                    "subject": "국어",
                    "location_label": None,
                    "duration": 1,
                    "source_text": "101 국어",
                },
            ],
        )

        self._login("admin", "1234")
        preview_response = self.client.get("/api/admin/timetable/previews/sync-first")
        self.assertEqual(preview_response.status_code, 200, preview_response.text)
        missing_names = {
            item["display_name"]
            for item in preview_response.json()["preview"]["teacher_sync"]["missing_teachers"]
        }
        self.assertEqual(missing_names, {"Bob", "Carol"})

        confirm_response = self.client.post(
            "/api/admin/timetable/confirm",
            json={
                "preview_id": "sync-first",
                "missing_teacher_actions": [
                    {"teacher_id": bob_id, "action": "deactivate"},
                    {"teacher_id": carol_id, "action": "delete"},
                ],
            },
        )
        self.assertEqual(confirm_response.status_code, 200, confirm_response.text)
        self.assertEqual(confirm_response.json()["result"]["teacher_sync"]["deactivated_count"], 1)
        self.assertEqual(confirm_response.json()["result"]["teacher_sync"]["deleted_count"], 1)

        with db_session(self.settings) as connection:
            bob = connection.execute("SELECT * FROM teachers WHERE id = ?", (bob_id,)).fetchone()
            carol = connection.execute("SELECT * FROM teachers WHERE id = ?", (carol_id,)).fetchone()
        self.assertEqual(bob["is_active"], 0)
        self.assertEqual(bob["username"], "bob")
        self.assertEqual(carol["is_active"], 0)
        self.assertEqual(carol["username"], f"deleted-{carol_id}-carol")
        self.assertTrue(carol["schedule_label"].endswith("(삭제됨)"))

        self._write_preview(
            "sync-second",
            [
                {"row_index": 4, "raw_name": "Bob", "display_name": "Bob", "suggested_username": "bob"},
                {"row_index": 5, "raw_name": "Carol", "display_name": "Carol", "suggested_username": "carol"},
            ],
            [
                {
                    "teacher_row_index": 4,
                    "teacher_schedule_label": "Bob",
                    "teacher_display_name": "Bob",
                    "teacher_username": "bob",
                    "weekday": 0,
                    "day_label": "월",
                    "period": 1,
                    "slot_type": "class",
                    "class_code": "101",
                    "subject": "영어",
                    "location_label": None,
                    "duration": 1,
                    "source_text": "101 영어",
                },
                {
                    "teacher_row_index": 5,
                    "teacher_schedule_label": "Carol",
                    "teacher_display_name": "Carol",
                    "teacher_username": "carol",
                    "weekday": 1,
                    "day_label": "화",
                    "period": 2,
                    "slot_type": "class",
                    "class_code": "102",
                    "subject": "수학",
                    "location_label": None,
                    "duration": 1,
                    "source_text": "102 수학",
                },
            ],
        )
        reimport_response = self.client.post(
            "/api/admin/timetable/confirm",
            json={"preview_id": "sync-second"},
        )
        self.assertEqual(reimport_response.status_code, 200, reimport_response.text)

        with db_session(self.settings) as connection:
            bob = connection.execute("SELECT * FROM teachers WHERE id = ?", (bob_id,)).fetchone()
            active_carol = connection.execute(
                "SELECT * FROM teachers WHERE username = ? AND is_active = 1",
                ("carol",),
            ).fetchone()
        self.assertEqual(bob["is_active"], 1)
        self.assertEqual(bob["username"], "bob")
        self.assertIsNotNone(active_carol)
        self.assertNotEqual(active_carol["id"], carol_id)

    def test_admin_can_update_teacher_member_profile(self) -> None:
        teacher_id = self._insert_teacher("kim", "김교사")
        self._login("admin", "1234")

        response = self.client.put(
            f"/api/admin/teachers/{teacher_id}",
            json={
                "display_name": "김수업",
                "username": "kim-teacher",
                "role": "admin",
                "schedule_label": "김수업(01)",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

        list_response = self.client.get("/api/admin/teachers")
        self.assertEqual(list_response.status_code, 200, list_response.text)
        updated = next(item for item in list_response.json()["teachers"] if item["id"] == teacher_id)
        self.assertEqual(updated["display_name"], "김수업")
        self.assertEqual(updated["username"], "kim-teacher")
        self.assertEqual(updated["role"], "admin")
        self.assertEqual(updated["schedule_label"], "김수업(01)")

    def test_admin_can_manage_teacher_timetable_slots(self) -> None:
        teacher_id = self._insert_teacher("slot-user", "시간표교사")
        self._login("admin", "1234")

        create_response = self.client.post(
            "/api/admin/timetable/slots",
            json={
                "teacher_id": teacher_id,
                "weekday": 0,
                "period": 1,
                "slot_type": "class",
                "class_code": "101",
                "subject": "국어",
                "location_label": "",
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        slot = create_response.json()["slot"]
        self.assertEqual(slot["teacher_name"], "시간표교사")
        self.assertEqual(slot["source_text"], "101 국어")

        update_response = self.client.put(
            f"/api/admin/timetable/slots/{slot['id']}",
            json={
                "teacher_id": teacher_id,
                "weekday": 1,
                "period": 2,
                "slot_type": "class",
                "class_code": "102",
                "subject": "수학",
                "location_label": "",
            },
        )
        self.assertEqual(update_response.status_code, 200, update_response.text)
        updated = update_response.json()["slot"]
        self.assertEqual(updated["day_label"], "화")
        self.assertEqual(updated["period"], 2)
        self.assertEqual(updated["source_text"], "102 수학")

        invalid_response = self.client.post(
            "/api/admin/timetable/slots",
            json={
                "teacher_id": teacher_id,
                "weekday": 4,
                "period": 7,
                "slot_type": "class",
                "class_code": "103",
                "subject": "과학",
                "location_label": "",
            },
        )
        self.assertEqual(invalid_response.status_code, 400)

        delete_response = self.client.delete(f"/api/admin/timetable/slots/{slot['id']}")
        self.assertEqual(delete_response.status_code, 200, delete_response.text)

        list_response = self.client.get("/api/admin/timetable/slots", params={"teacher_id": teacher_id})
        self.assertEqual(list_response.status_code, 200, list_response.text)
        self.assertEqual(list_response.json()["slots"], [])

    def test_user_can_delete_checked_notifications(self) -> None:
        teacher_id = self._insert_teacher("notice-user", "알림교사")
        with db_session(self.settings) as connection:
            connection.execute(
                """
                INSERT INTO notifications (teacher_id, category, title, message, payload_json, is_read, created_at)
                VALUES (?, 'swap', '교체 확인', '확인한 교체 알림입니다.', NULL, 0, '2026-01-01T00:00:00')
                """,
                (teacher_id,),
            )
        self._login("notice-user", "1234")

        notifications_response = self.client.get("/api/notifications")
        self.assertEqual(notifications_response.status_code, 200, notifications_response.text)
        notification_id = notifications_response.json()["items"][0]["id"]

        read_response = self.client.post(
            "/api/notifications/read",
            json={"notification_ids": [notification_id], "mark_all": False},
        )
        self.assertEqual(read_response.status_code, 200, read_response.text)

        empty_response = self.client.get("/api/notifications")
        self.assertEqual(empty_response.status_code, 200, empty_response.text)
        self.assertEqual(empty_response.json()["items"], [])

    def test_swap_candidates_require_same_class_and_reciprocal_free_time(self) -> None:
        self._seed_swap_scenario()
        self._login("alice", "1234")

        response = self.client.get("/api/swaps/candidates", params={"date": "2026-09-07", "period": 1})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        candidate_names = {item["teacher_name"] for item in payload["candidates"]}
        self.assertEqual(candidate_names, {"Bob", "Carol"})

    def test_swap_candidates_can_search_next_week_and_create_request(self) -> None:
        self._seed_swap_scenario()
        self._login("admin", "1234")
        calendar_response = self.client.put(
            "/api/admin/calendar-settings",
            json={
                "semester_start": "2026-09-07",
                "semester_end": "2026-09-18",
                "special_days": [],
            },
        )
        self.assertEqual(calendar_response.status_code, 200, calendar_response.text)
        self._logout()
        self._login("alice", "1234")

        invalid_response = self.client.get(
            "/api/swaps/candidates",
            params={"date": "2026-09-07", "period": 1, "week_offset": 2},
        )
        self.assertEqual(invalid_response.status_code, 400, invalid_response.text)

        response = self.client.get(
            "/api/swaps/candidates",
            params={"date": "2026-09-07", "period": 1, "week_offset": 1},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["week"]["offset"], 1)
        self.assertEqual(payload["week"]["start_date"], "2026-09-14")
        self.assertEqual(payload["week"]["end_date"], "2026-09-18")
        candidate_dates = {item["target_date"] for item in payload["candidates"]}
        self.assertEqual(candidate_dates, {"2026-09-16", "2026-09-18"})

        create_response = self.client.post(
            "/api/swaps/requests",
            json={
                "source_date": "2026-09-07",
                "source_period": 1,
                "target_date": "2026-09-16",
                "target_period": 2,
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        self.assertEqual(create_response.json()["request"]["target_date"], "2026-09-16")

    def test_coverage_candidates_show_teachers_without_class_or_travel(self) -> None:
        _, bob_id, _ = self._seed_swap_scenario()
        self._insert_slot(bob_id, weekday=0, period=4, slot_type="class", class_code="102", subject="수학")
        dave_id = self._insert_teacher("dave", "Dave")
        self._insert_slot(dave_id, weekday=0, period=1, slot_type="travel", location_label="다인중학교")
        self._login("alice", "1234")

        response = self.client.get("/api/coverage/available", params={"date": "2026-09-07", "period": 1})
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        available_names = {item["teacher_name"] for item in payload["available_teachers"]}
        busy_names = {item["teacher_name"] for item in payload["busy_teachers"]}
        self.assertEqual(available_names, {"Bob", "Carol"})
        self.assertEqual(busy_names, {"Alice", "Dave"})
        bob_payload = next(item for item in payload["available_teachers"] if item["teacher_name"] == "Bob")
        dave_payload = next(item for item in payload["busy_teachers"] if item["teacher_name"] == "Dave")
        self.assertEqual(bob_payload["day_class_count"], 1)
        self.assertEqual(bob_payload["day_travel_count"], 0)
        self.assertEqual(dave_payload["day_class_count"], 0)
        self.assertEqual(dave_payload["day_travel_count"], 1)

    def test_weekly_coverage_candidates_can_search_next_week_and_create_request(self) -> None:
        alice_id, bob_id, _ = self._seed_swap_scenario()
        self._insert_slot(alice_id, weekday=3, period=4, slot_type="class", class_code="101", subject="국어")
        self._login("admin", "1234")
        calendar_response = self.client.put(
            "/api/admin/calendar-settings",
            json={
                "semester_start": "2026-09-07",
                "semester_end": "2026-09-18",
                "special_days": [],
            },
        )
        self.assertEqual(calendar_response.status_code, 200, calendar_response.text)
        self._logout()
        self._login("alice", "1234")

        invalid_response = self.client.get(
            "/api/coverage/candidates",
            params={"date": "2026-09-07", "period": 1, "week_offset": 2},
        )
        self.assertEqual(invalid_response.status_code, 400, invalid_response.text)

        this_week_response = self.client.get(
            "/api/coverage/candidates",
            params={"date": "2026-09-07", "period": 1, "week_offset": 0},
        )
        self.assertEqual(this_week_response.status_code, 200, this_week_response.text)
        this_week_payload = this_week_response.json()
        self.assertEqual(this_week_payload["week"]["start_date"], "2026-09-07")
        self.assertEqual([slot["date"] for slot in this_week_payload["slots"]], ["2026-09-07"])
        this_week_names = {item["teacher_name"] for item in this_week_payload["slots"][0]["available_teachers"]}
        self.assertEqual(this_week_names, {"Bob", "Carol"})

        next_week_response = self.client.get(
            "/api/coverage/candidates",
            params={"date": "2026-09-07", "period": 1, "week_offset": 1},
        )
        self.assertEqual(next_week_response.status_code, 200, next_week_response.text)
        next_week_payload = next_week_response.json()
        self.assertEqual(next_week_payload["week"]["start_date"], "2026-09-14")
        self.assertEqual([slot["date"] for slot in next_week_payload["slots"]], ["2026-09-14"])
        next_week_names = {item["teacher_name"] for item in next_week_payload["slots"][0]["available_teachers"]}
        self.assertEqual(next_week_names, {"Bob", "Carol"})

        create_response = self.client.post(
            "/api/coverage/requests",
            json={
                "class_date": "2026-09-14",
                "period": 1,
                "responder_id": bob_id,
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        self.assertEqual(create_response.json()["request"]["class_date"], "2026-09-14")

    def test_admin_event_coverage_preview_and_bulk_request_excludes_absent_teachers(self) -> None:
        alice_id, bob_id, carol_id = self._seed_swap_scenario()
        self._login("admin", "1234")

        preview_response = self.client.post(
            "/api/admin/event-coverage/preview",
            json={
                "title": "기능경기대회",
                "start_date": "2026-09-07",
                "end_date": "2026-09-11",
                "absent_teacher_ids": [alice_id, bob_id],
            },
        )
        self.assertEqual(preview_response.status_code, 200, preview_response.text)
        preview_payload = preview_response.json()
        self.assertEqual(preview_payload["summary"]["absent_teacher_count"], 2)
        self.assertEqual(preview_payload["summary"]["affected_slot_count"], 2)
        alice_slot = next(
            slot
            for slot in preview_payload["affected_slots"]
            if slot["requester_id"] == alice_id and slot["class_date"] == "2026-09-07"
        )
        candidate_ids = {candidate["teacher_id"] for candidate in alice_slot["candidates"]}
        self.assertNotIn(bob_id, candidate_ids)
        self.assertIn(carol_id, candidate_ids)

        create_response = self.client.post(
            "/api/admin/event-coverage/requests",
            json={
                "title": "기능경기대회",
                "assignments": [
                    {
                        "requester_id": alice_id,
                        "class_date": "2026-09-07",
                        "period": 1,
                        "responder_id": carol_id,
                    }
                ],
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        self.assertEqual(create_response.json()["summary"]["created_count"], 1)
        self.assertEqual(create_response.json()["created"][0]["requester_id"], alice_id)
        self.assertEqual(create_response.json()["created"][0]["responder_id"], carol_id)

    def test_coverage_request_starts_from_own_class_and_reflects_after_accept(self) -> None:
        _, bob_id, _ = self._seed_swap_scenario()
        self._login("alice", "1234")

        source_response = self.client.get("/api/coverage/sources", params={"date": "2026-09-07"})
        self.assertEqual(source_response.status_code, 200, source_response.text)
        sources = source_response.json()["sources"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["period"], 1)
        self.assertEqual(sources[0]["class_code"], "101")
        self.assertEqual(sources[0]["subject"], "국어")

        create_response = self.client.post(
            "/api/coverage/requests",
            json={
                "class_date": "2026-09-07",
                "period": 1,
                "responder_id": bob_id,
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["request"]["id"]
        self.assertEqual(create_response.json()["request"]["status"], "pending")
        self._logout()

        self._login("bob", "1234")
        received_response = self.client.get("/api/coverage/requests")
        self.assertEqual(received_response.status_code, 200, received_response.text)
        self.assertEqual(received_response.json()["received"][0]["id"], request_id)

        accept_response = self.client.post(
            f"/api/coverage/requests/{request_id}/accept",
            json={"note": "보강 가능합니다."},
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.text)
        self.assertEqual(accept_response.json()["request"]["status"], "accepted")

        bob_monthly = self.client.get("/api/schedule/monthly", params={"month": "2026-09"})
        self.assertEqual(bob_monthly.status_code, 200, bob_monthly.text)
        bob_days = {item["date"]: item for item in bob_monthly.json()["days"]}
        bob_monday_first = next(item for item in bob_days["2026-09-07"]["periods"] if item["period"] == 1)
        self.assertEqual(bob_monday_first["status"], "coverage-in")
        self.assertEqual(bob_monday_first["effective"]["class_code"], "101")
        self.assertEqual(bob_monday_first["effective"]["subject"], "국어")
        bob_weekly = self.client.get("/api/schedule/weekly", params={"date": "2026-09-07"})
        self.assertEqual(bob_weekly.status_code, 200, bob_weekly.text)
        bob_weekly_monday = next(item for item in bob_weekly.json()["days"] if item["date"] == "2026-09-07")
        bob_weekly_first = next(item for item in bob_weekly_monday["periods"] if item["period"] == 1)
        self.assertEqual(bob_weekly_first["status"], "coverage-in")
        self._logout()

        self._login("alice", "1234")
        alice_monthly = self.client.get("/api/schedule/monthly", params={"month": "2026-09"})
        self.assertEqual(alice_monthly.status_code, 200, alice_monthly.text)
        alice_days = {item["date"]: item for item in alice_monthly.json()["days"]}
        alice_monday_first = next(item for item in alice_days["2026-09-07"]["periods"] if item["period"] == 1)
        self.assertEqual(alice_monday_first["status"], "coverage-out")
        self.assertEqual(alice_monday_first["original"]["class_code"], "101")
        self.assertEqual(alice_monday_first["original"]["covered_by_name"], "Bob")
        alice_weekly = self.client.get("/api/schedule/weekly", params={"date": "2026-09-07"})
        self.assertEqual(alice_weekly.status_code, 200, alice_weekly.text)
        alice_weekly_monday = next(item for item in alice_weekly.json()["days"] if item["date"] == "2026-09-07")
        alice_weekly_first = next(item for item in alice_weekly_monday["periods"] if item["period"] == 1)
        self.assertEqual(alice_weekly_first["status"], "coverage-out")

        dismiss_response = self.client.post(f"/api/coverage/requests/{request_id}/dismiss")
        self.assertEqual(dismiss_response.status_code, 200, dismiss_response.text)
        self.assertTrue(dismiss_response.json()["request"]["requester_hidden"])
        sent_after_dismiss = self.client.get("/api/coverage/requests")
        self.assertEqual(sent_after_dismiss.status_code, 200, sent_after_dismiss.text)
        coverage_status_payload = sent_after_dismiss.json()
        self.assertEqual(coverage_status_payload["sent"], [])
        self.assertEqual(len(coverage_status_payload["status_sent"]), 1)
        self.assertEqual(coverage_status_payload["status_sent"][0]["id"], request_id)
        self.assertEqual(coverage_status_payload["status_sent"][0]["status"], "accepted")
        self.assertTrue(coverage_status_payload["status_sent"][0]["requester_hidden"])
        reflected_after_dismiss = self.client.get("/api/schedule/weekly", params={"date": "2026-09-07"})
        self.assertEqual(reflected_after_dismiss.status_code, 200, reflected_after_dismiss.text)
        reflected_monday = next(item for item in reflected_after_dismiss.json()["days"] if item["date"] == "2026-09-07")
        reflected_first = next(item for item in reflected_monday["periods"] if item["period"] == 1)
        self.assertEqual(reflected_first["status"], "coverage-out")

        plan_response = self.client.get("/api/plans/weekly", params={"date": "2026-09-07"})
        self.assertEqual(plan_response.status_code, 200, plan_response.text)
        plan_payload = plan_response.json()
        self.assertEqual(plan_payload["summary"]["coverage_request_count"], 1)
        self.assertEqual(plan_payload["summary"]["row_count"], 1)
        self.assertEqual(plan_payload["items"][0]["type"], "보강")
        self.assertEqual(plan_payload["items"][0]["original_teacher_name"], "Alice")
        self.assertEqual(plan_payload["items"][0]["assigned_teacher_name"], "Bob")

        download_response = self.client.get("/api/plans/weekly/download", params={"date": "2026-09-07"})
        self.assertEqual(download_response.status_code, 200, download_response.text)
        self.assertEqual(
            download_response.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(download_response.content.startswith(b"PK"))
        pdf_response = self.client.get("/api/plans/weekly/download.pdf", params={"date": "2026-09-07"})
        self.assertEqual(pdf_response.status_code, 200, pdf_response.text)
        self.assertEqual(pdf_response.headers["content-type"], "application/pdf")
        self.assertTrue(pdf_response.content.startswith(b"%PDF-1.4"))

        self._logout()
        self._login("admin", "1234")
        allowance_response = self.client.get(
            "/api/admin/coverage-allowances",
            params={"month": "2026-09", "rate": 15000},
        )
        self.assertEqual(allowance_response.status_code, 200, allowance_response.text)
        allowance_payload = allowance_response.json()
        self.assertEqual(allowance_payload["summary"]["coverage_count"], 1)
        self.assertEqual(allowance_payload["summary"]["total_amount"], 15000)
        self.assertEqual(allowance_payload["teachers"][0]["teacher_name"], "Bob")
        self.assertEqual(allowance_payload["teachers"][0]["coverage_count"], 1)
        self.assertEqual(allowance_payload["teachers"][0]["amount"], 15000)
        self.assertEqual(allowance_payload["teachers"][0]["details"][0]["class_code"], "101")
        full_week_response = self.client.get(
            "/api/admin/schedule/weekly/download",
            params={"date": "2026-09-07"},
        )
        self.assertEqual(full_week_response.status_code, 200, full_week_response.text)
        self.assertEqual(
            full_week_response.headers["content-type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertTrue(full_week_response.content.startswith(b"PK"))
        with ZipFile(BytesIO(full_week_response.content)) as workbook:
            sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("주간 전체 시간표", sheet_xml)
        self.assertIn("보강", sheet_xml)

    def test_weekly_plan_is_scoped_to_current_teacher_for_non_admins(self) -> None:
        _, bob_id, _ = self._seed_swap_scenario()
        dave_id = self._insert_teacher("dave", "Dave")

        self._login("alice", "1234")
        alice_request = self.client.post(
            "/api/coverage/requests",
            json={"class_date": "2026-09-07", "period": 1, "responder_id": bob_id},
        )
        self.assertEqual(alice_request.status_code, 200, alice_request.text)
        alice_request_id = alice_request.json()["request"]["id"]
        self._logout()

        self._login("bob", "1234")
        alice_accept = self.client.post(
            f"/api/coverage/requests/{alice_request_id}/accept",
            json={"note": "가능합니다."},
        )
        self.assertEqual(alice_accept.status_code, 200, alice_accept.text)
        self._logout()

        self._login("carol", "1234")
        carol_request = self.client.post(
            "/api/coverage/requests",
            json={"class_date": "2026-09-11", "period": 3, "responder_id": dave_id},
        )
        self.assertEqual(carol_request.status_code, 200, carol_request.text)
        carol_request_id = carol_request.json()["request"]["id"]
        self._logout()

        self._login("dave", "1234")
        carol_accept = self.client.post(
            f"/api/coverage/requests/{carol_request_id}/accept",
            json={"note": "가능합니다."},
        )
        self.assertEqual(carol_accept.status_code, 200, carol_accept.text)
        self._logout()

        self._login("alice", "1234")
        alice_plan = self.client.get("/api/plans/weekly", params={"date": "2026-09-07"})
        self.assertEqual(alice_plan.status_code, 200, alice_plan.text)
        alice_payload = alice_plan.json()
        self.assertEqual(alice_payload["scope"], "teacher")
        self.assertEqual(alice_payload["summary"]["coverage_request_count"], 1)
        self.assertEqual(alice_payload["summary"]["row_count"], 1)
        self.assertEqual(alice_payload["items"][0]["original_teacher_name"], "Alice")
        self._logout()

        self._login("admin", "1234")
        admin_plan = self.client.get("/api/plans/weekly", params={"date": "2026-09-07"})
        self.assertEqual(admin_plan.status_code, 200, admin_plan.text)
        admin_payload = admin_plan.json()
        self.assertEqual(admin_payload["scope"], "all")
        self.assertEqual(admin_payload["summary"]["coverage_request_count"], 2)
        self.assertEqual(admin_payload["summary"]["row_count"], 2)

    def test_weekly_plan_lists_swap_once_by_requester_source_class(self) -> None:
        self._seed_swap_scenario()

        self._login("alice", "1234")
        create_response = self.client.post(
            "/api/swaps/requests",
            json={
                "source_date": "2026-09-07",
                "source_period": 1,
                "target_date": "2026-09-09",
                "target_period": 2,
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["request"]["id"]
        self._logout()

        self._login("bob", "1234")
        accept_response = self.client.post(
            f"/api/swaps/requests/{request_id}/accept",
            json={"note": "가능합니다."},
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.text)
        self._logout()

        self._login("admin", "1234")
        plan_response = self.client.get("/api/plans/weekly", params={"date": "2026-09-07"})
        self.assertEqual(plan_response.status_code, 200, plan_response.text)
        payload = plan_response.json()
        self.assertEqual(payload["summary"]["swap_request_count"], 1)
        self.assertEqual(payload["summary"]["row_count"], 1)
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["id"], f"swap-{request_id}")
        self.assertEqual(item["type"], "교체")
        self.assertEqual(item["date"], "2026-09-07")
        self.assertEqual(item["period"], 1)
        self.assertEqual(item["class_code"], "101")
        self.assertEqual(item["subject"], "국어")
        self.assertEqual(item["original_teacher_name"], "Alice")
        self.assertEqual(item["assigned_teacher_name"], "Bob")
        self.assertIn("2026-09-09 2교시", item["detail"])

        pdf_response = self.client.get("/api/plans/weekly/download.pdf", params={"date": "2026-09-07"})
        self.assertEqual(pdf_response.status_code, 200, pdf_response.text)
        self.assertTrue(pdf_response.content.startswith(b"%PDF-1.4"))
        self.assertIn(b"1.00 0.95 0.95 rg", pdf_response.content)
        self.assertIn(b"0.73 0.11 0.11 rg", pdf_response.content)

        full_week_response = self.client.get(
            "/api/admin/schedule/weekly/download",
            params={"date": "2026-09-07"},
        )
        self.assertEqual(full_week_response.status_code, 200, full_week_response.text)
        self.assertTrue(full_week_response.content.startswith(b"PK"))
        with ZipFile(BytesIO(full_week_response.content)) as workbook:
            sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")
            styles_xml = workbook.read("xl/styles.xml").decode("utf-8")
        self.assertIn('s="11"><is><t>교체됨', sheet_xml)
        self.assertIn('color rgb="FFB91C1C"', styles_xml)

    def test_admin_can_cancel_and_delete_coverage_history(self) -> None:
        _, bob_id, _ = self._seed_swap_scenario()
        self._login("alice", "1234")
        create_response = self.client.post(
            "/api/coverage/requests",
            json={
                "class_date": "2026-09-07",
                "period": 1,
                "responder_id": bob_id,
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["request"]["id"]
        self._logout()

        self._login("bob", "1234")
        accept_response = self.client.post(
            f"/api/coverage/requests/{request_id}/accept",
            json={"note": "보강 가능합니다."},
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.text)
        self._logout()

        self._login("admin", "1234")
        admin_response = self.client.get("/api/admin/swaps")
        self.assertEqual(admin_response.status_code, 200, admin_response.text)
        active_items = admin_response.json()["active"]
        self.assertTrue(any(item["type"] == "coverage" and item["request_id"] == request_id for item in active_items))

        impact_response = self.client.get("/api/admin/impact-check")
        self.assertEqual(impact_response.status_code, 200, impact_response.text)
        self.assertEqual(impact_response.json()["summary"]["accepted_coverage_count"], 1)
        self.assertEqual(impact_response.json()["summary"]["issue_count"], 0)
        with db_session(self.settings) as connection:
            connection.execute(
                "UPDATE calendar_days SET is_school_day = 0, kind = 'closure', label = '임시휴업' WHERE date = ?",
                ("2026-09-07",),
            )
        impacted_response = self.client.get("/api/admin/impact-check")
        self.assertEqual(impacted_response.status_code, 200, impacted_response.text)
        self.assertEqual(impacted_response.json()["summary"]["error_count"], 1)
        self.assertIn("수업일이 아닙니다", impacted_response.json()["issues"][0]["message"])
        with db_session(self.settings) as connection:
            connection.execute(
                "UPDATE calendar_days SET is_school_day = 1, kind = 'school_day', label = '' WHERE date = ?",
                ("2026-09-07",),
            )

        cancel_response = self.client.post(f"/api/admin/coverage/{request_id}/cancel")
        self.assertEqual(cancel_response.status_code, 200, cancel_response.text)
        self.assertEqual(cancel_response.json()["request"]["status"], "cancelled")

        delete_response = self.client.delete(f"/api/admin/coverage/{request_id}")
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        admin_after_delete = self.client.get("/api/admin/swaps")
        self.assertEqual(admin_after_delete.status_code, 200, admin_after_delete.text)
        coverage_ids = {item["id"] for item in admin_after_delete.json()["coverage_requests"]}
        self.assertNotIn(request_id, coverage_ids)
        self._logout()

        self._login("alice", "1234")
        restored_weekly = self.client.get("/api/schedule/weekly", params={"date": "2026-09-07"})
        self.assertEqual(restored_weekly.status_code, 200, restored_weekly.text)
        monday = next(item for item in restored_weekly.json()["days"] if item["date"] == "2026-09-07")
        monday_first = next(item for item in monday["periods"] if item["period"] == 1)
        self.assertEqual(monday_first["status"], "class")

    def test_impact_check_detects_accepted_schedule_lock_conflicts(self) -> None:
        alice_id, _, carol_id = self._seed_swap_scenario()

        self._login("alice", "1234")
        create_swap = self.client.post(
            "/api/swaps/requests",
            json={
                "source_date": "2026-09-07",
                "source_period": 1,
                "target_date": "2026-09-09",
                "target_period": 2,
            },
        )
        self.assertEqual(create_swap.status_code, 200, create_swap.text)
        swap_request_id = create_swap.json()["request"]["id"]
        self._logout()

        self._login("bob", "1234")
        accept_swap = self.client.post(
            f"/api/swaps/requests/{swap_request_id}/accept",
            json={"note": "가능합니다."},
        )
        self.assertEqual(accept_swap.status_code, 200, accept_swap.text)
        self._logout()

        with db_session(self.settings) as connection:
            connection.execute(
                """
                INSERT INTO coverage_requests (
                    requester_id, responder_id, class_date, weekday, period,
                    class_code, subject, status, expires_at, created_at, responded_at, response_note
                ) VALUES (?, ?, '2026-09-07', 0, 1, '101', '국어', 'accepted',
                    '2026-09-06T23:59:59', '2026-09-01T09:00:00', '2026-09-01T09:05:00', 'legacy conflict')
                """,
                (alice_id, carol_id),
            )

        self._login("admin", "1234")
        impact_response = self.client.get("/api/admin/impact-check")
        self.assertEqual(impact_response.status_code, 200, impact_response.text)
        payload = impact_response.json()
        self.assertGreaterEqual(payload["summary"]["error_count"], 1)
        self.assertTrue(
            any("확정된 다른 교체·보강과 일정이 겹칩니다" in issue["message"] for issue in payload["issues"]),
            payload["issues"],
        )

    def test_teacher_can_cancel_accepted_coverage_and_counterpart_gets_notification(self) -> None:
        _, bob_id, _ = self._seed_swap_scenario()
        self._login("alice", "1234")
        create_response = self.client.post(
            "/api/coverage/requests",
            json={
                "class_date": "2026-09-07",
                "period": 1,
                "responder_id": bob_id,
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["request"]["id"]
        self._logout()

        self._login("bob", "1234")
        accept_response = self.client.post(
            f"/api/coverage/requests/{request_id}/accept",
            json={"note": "보강 가능합니다."},
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.text)
        cancel_response = self.client.post(f"/api/coverage/requests/{request_id}/cancel")
        self.assertEqual(cancel_response.status_code, 200, cancel_response.text)
        self.assertEqual(cancel_response.json()["request"]["status"], "cancelled")
        bob_weekly = self.client.get("/api/schedule/weekly", params={"date": "2026-09-07"})
        self.assertEqual(bob_weekly.status_code, 200, bob_weekly.text)
        bob_monday = next(item for item in bob_weekly.json()["days"] if item["date"] == "2026-09-07")
        bob_first = next(item for item in bob_monday["periods"] if item["period"] == 1)
        self.assertEqual(bob_first["status"], "free")
        self._logout()

        self._login("alice", "1234")
        alice_weekly = self.client.get("/api/schedule/weekly", params={"date": "2026-09-07"})
        self.assertEqual(alice_weekly.status_code, 200, alice_weekly.text)
        alice_monday = next(item for item in alice_weekly.json()["days"] if item["date"] == "2026-09-07")
        alice_first = next(item for item in alice_monday["periods"] if item["period"] == 1)
        self.assertEqual(alice_first["status"], "class")
        notifications = self.client.get("/api/notifications")
        self.assertEqual(notifications.status_code, 200, notifications.text)
        titles = [item["title"] for item in notifications.json()["items"]]
        self.assertIn("보강 요청 취소", titles)

    def test_pending_request_locks_same_source_slot(self) -> None:
        self._seed_swap_scenario()
        self._login("alice", "1234")

        first_response = self.client.post(
            "/api/swaps/requests",
            json={
                "source_date": "2026-09-07",
                "source_period": 1,
                "target_date": "2026-09-09",
                "target_period": 2,
            },
        )
        self.assertEqual(first_response.status_code, 200, first_response.text)
        self.assertEqual(first_response.json()["request"]["expires_at"], "2026-09-06T23:59:59")

        second_response = self.client.post(
            "/api/swaps/requests",
            json={
                "source_date": "2026-09-07",
                "source_period": 1,
                "target_date": "2026-09-11",
                "target_period": 3,
            },
        )
        self.assertEqual(second_response.status_code, 400, second_response.text)

    def test_pending_swap_marks_day_source_as_locked_until_cancelled(self) -> None:
        self._seed_swap_scenario()
        self._login("alice", "1234")

        create_response = self.client.post(
            "/api/swaps/requests",
            json={
                "source_date": "2026-09-07",
                "source_period": 1,
                "target_date": "2026-09-09",
                "target_period": 2,
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["request"]["id"]

        day_response = self.client.get("/api/schedule/day", params={"target_date": "2026-09-07"})
        self.assertEqual(day_response.status_code, 200, day_response.text)
        first_period = next(item for item in day_response.json()["periods"] if item["period"] == 1)
        self.assertEqual(first_period["status"], "locked")
        self.assertEqual(first_period["lock_type"], "swap")
        self.assertEqual(first_period["lock_label"], "교체 요청 대기 중")
        self.assertIn("Alice↔Bob", first_period["lock_message"])

        candidate_response = self.client.get("/api/swaps/candidates", params={"date": "2026-09-07", "period": 1})
        self.assertEqual(candidate_response.status_code, 400, candidate_response.text)
        self.assertIn("Alice↔Bob", candidate_response.text)

        cancel_response = self.client.post(f"/api/swaps/requests/{request_id}/cancel")
        self.assertEqual(cancel_response.status_code, 200, cancel_response.text)

        unlocked_day_response = self.client.get("/api/schedule/day", params={"target_date": "2026-09-07"})
        self.assertEqual(unlocked_day_response.status_code, 200, unlocked_day_response.text)
        unlocked_first = next(item for item in unlocked_day_response.json()["periods"] if item["period"] == 1)
        self.assertEqual(unlocked_first["status"], "class")

        refreshed_candidates = self.client.get("/api/swaps/candidates", params={"date": "2026-09-07", "period": 1})
        self.assertEqual(refreshed_candidates.status_code, 200, refreshed_candidates.text)
        self.assertTrue(refreshed_candidates.json()["candidates"])

    def test_responder_can_dismiss_closed_received_requests(self) -> None:
        _, bob_id, _ = self._seed_swap_scenario()
        self._login("alice", "1234")
        swap_response = self.client.post(
            "/api/swaps/requests",
            json={
                "source_date": "2026-09-07",
                "source_period": 1,
                "target_date": "2026-09-09",
                "target_period": 2,
            },
        )
        self.assertEqual(swap_response.status_code, 200, swap_response.text)
        swap_request_id = swap_response.json()["request"]["id"]
        self._logout()

        self._login("carol", "1234")
        coverage_response = self.client.post(
            "/api/coverage/requests",
            json={
                "class_date": "2026-09-11",
                "period": 3,
                "responder_id": bob_id,
            },
        )
        self.assertEqual(coverage_response.status_code, 200, coverage_response.text)
        coverage_request_id = coverage_response.json()["request"]["id"]
        coverage_cancel = self.client.post(f"/api/coverage/requests/{coverage_request_id}/cancel")
        self.assertEqual(coverage_cancel.status_code, 200, coverage_cancel.text)
        self._logout()

        self._login("bob", "1234")
        reject_response = self.client.post(
            f"/api/swaps/requests/{swap_request_id}/reject",
            json={"note": "어렵습니다."},
        )
        self.assertEqual(reject_response.status_code, 200, reject_response.text)

        before_swap_dismiss = self.client.get("/api/swaps/requests")
        self.assertEqual(before_swap_dismiss.status_code, 200, before_swap_dismiss.text)
        self.assertTrue(any(item["id"] == swap_request_id for item in before_swap_dismiss.json()["received"]))
        swap_dismiss = self.client.post(f"/api/swaps/requests/{swap_request_id}/dismiss")
        self.assertEqual(swap_dismiss.status_code, 200, swap_dismiss.text)
        self.assertTrue(swap_dismiss.json()["request"]["responder_hidden"])
        after_swap_dismiss = self.client.get("/api/swaps/requests")
        self.assertEqual(after_swap_dismiss.status_code, 200, after_swap_dismiss.text)
        self.assertFalse(any(item["id"] == swap_request_id for item in after_swap_dismiss.json()["received"]))

        before_coverage_dismiss = self.client.get("/api/coverage/requests")
        self.assertEqual(before_coverage_dismiss.status_code, 200, before_coverage_dismiss.text)
        self.assertTrue(any(item["id"] == coverage_request_id for item in before_coverage_dismiss.json()["received"]))
        coverage_dismiss = self.client.post(f"/api/coverage/requests/{coverage_request_id}/dismiss")
        self.assertEqual(coverage_dismiss.status_code, 200, coverage_dismiss.text)
        self.assertTrue(coverage_dismiss.json()["request"]["responder_hidden"])
        after_coverage_dismiss = self.client.get("/api/coverage/requests")
        self.assertEqual(after_coverage_dismiss.status_code, 200, after_coverage_dismiss.text)
        self.assertFalse(
            any(item["id"] == coverage_request_id for item in after_coverage_dismiss.json()["received"])
        )

    def test_accept_swap_reflects_in_monthly_schedule_and_admin_can_cancel(self) -> None:
        self._seed_swap_scenario()

        self._login("alice", "1234")
        create_response = self.client.post(
            "/api/swaps/requests",
            json={
                "source_date": "2026-09-07",
                "source_period": 1,
                "target_date": "2026-09-09",
                "target_period": 2,
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["request"]["id"]
        self._logout()

        self._login("bob", "1234")
        accept_response = self.client.post(
            f"/api/swaps/requests/{request_id}/accept",
            json={"note": "가능합니다."},
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.text)
        self._logout()

        self._login("alice", "1234")
        alice_monthly = self.client.get("/api/schedule/monthly", params={"month": "2026-09"})
        self.assertEqual(alice_monthly.status_code, 200, alice_monthly.text)
        days = {item["date"]: item for item in alice_monthly.json()["days"]}
        monday = days["2026-09-07"]
        wednesday = days["2026-09-09"]
        monday_first = next(item for item in monday["periods"] if item["period"] == 1)
        wednesday_second = next(item for item in wednesday["periods"] if item["period"] == 2)
        self.assertEqual(monday_first["status"], "swapped-out")
        self.assertEqual(wednesday_second["status"], "swapped-in")
        self.assertEqual(wednesday_second["effective"]["class_code"], "101")
        self.assertEqual(wednesday_second["effective"]["subject"], "영어")
        self.assertEqual(monday_first["original"]["swap_with_name"], "Bob")
        self.assertEqual(wednesday_second["effective"]["swap_with_name"], "Bob")
        dismiss_response = self.client.post(f"/api/swaps/requests/{request_id}/dismiss")
        self.assertEqual(dismiss_response.status_code, 200, dismiss_response.text)
        self.assertTrue(dismiss_response.json()["request"]["requester_hidden"])
        sent_after_dismiss = self.client.get("/api/swaps/requests")
        self.assertEqual(sent_after_dismiss.status_code, 200, sent_after_dismiss.text)
        swap_status_payload = sent_after_dismiss.json()
        self.assertEqual(swap_status_payload["sent"], [])
        self.assertEqual(len(swap_status_payload["status_sent"]), 1)
        self.assertEqual(swap_status_payload["status_sent"][0]["id"], request_id)
        self.assertEqual(swap_status_payload["status_sent"][0]["status"], "accepted")
        self.assertTrue(swap_status_payload["status_sent"][0]["requester_hidden"])
        still_reflected = self.client.get("/api/schedule/weekly", params={"date": "2026-09-07"})
        self.assertEqual(still_reflected.status_code, 200, still_reflected.text)
        reflected_monday = next(item for item in still_reflected.json()["days"] if item["date"] == "2026-09-07")
        reflected_first = next(item for item in reflected_monday["periods"] if item["period"] == 1)
        self.assertEqual(reflected_first["status"], "swapped-out")
        repeated_swap = self.client.get(
            "/api/swaps/candidates",
            params={"date": "2026-09-07", "period": 1},
        )
        self.assertEqual(repeated_swap.status_code, 400, repeated_swap.text)
        self.assertIn("다시 교체할 수 없습니다", repeated_swap.text)
        self._logout()

        self._login("admin", "1234")
        cancel_response = self.client.post(f"/api/admin/swaps/{request_id}/cancel")
        self.assertEqual(cancel_response.status_code, 200, cancel_response.text)
        delete_response = self.client.delete(f"/api/admin/swaps/{request_id}")
        self.assertEqual(delete_response.status_code, 200, delete_response.text)
        admin_after_delete = self.client.get("/api/admin/swaps")
        self.assertEqual(admin_after_delete.status_code, 200, admin_after_delete.text)
        swap_ids = {item["id"] for item in admin_after_delete.json()["requests"]}
        self.assertNotIn(request_id, swap_ids)
        self._logout()

        self._login("alice", "1234")
        restored_monthly = self.client.get("/api/schedule/monthly", params={"month": "2026-09"})
        self.assertEqual(restored_monthly.status_code, 200, restored_monthly.text)
        days = {item["date"]: item for item in restored_monthly.json()["days"]}
        monday_first = next(item for item in days["2026-09-07"]["periods"] if item["period"] == 1)
        wednesday_second = next(item for item in days["2026-09-09"]["periods"] if item["period"] == 2)
        self.assertEqual(monday_first["status"], "class")
        self.assertEqual(wednesday_second["status"], "free")

    def test_admin_schedule_debug_report_summarizes_slot_state(self) -> None:
        alice_id, _, _ = self._seed_swap_scenario()

        self._login("admin", "1234")
        response = self.client.get(
            "/api/admin/debug/schedule",
            params={"teacher_id": alice_id, "date": "2026-09-07", "period": 1},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["teacher"]["id"], alice_id)
        self.assertEqual(payload["selected_cell"]["status"], "class")
        labels = {item["label"] for item in payload["api_checks"]}
        self.assertIn("이번 주 교체 후보", labels)
        self.assertIn("현재 교시 보강 가능 교사", labels)

    def test_accept_swap_revalidates_calendar_before_confirming(self) -> None:
        self._seed_swap_scenario()

        self._login("alice", "1234")
        create_response = self.client.post(
            "/api/swaps/requests",
            json={
                "source_date": "2026-09-07",
                "source_period": 1,
                "target_date": "2026-09-09",
                "target_period": 2,
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["request"]["id"]
        self._logout()

        with db_session(self.settings) as connection:
            connection.execute(
                "UPDATE calendar_days SET is_school_day = 0, kind = 'closure', label = '임시휴업' WHERE date = ?",
                ("2026-09-09",),
            )

        self._login("bob", "1234")
        accept_response = self.client.post(
            f"/api/swaps/requests/{request_id}/accept",
            json={"note": "가능합니다."},
        )
        self.assertEqual(accept_response.status_code, 400, accept_response.text)
        self.assertIn("수업일", accept_response.text)

    def test_teacher_can_cancel_accepted_swap(self) -> None:
        self._seed_swap_scenario()

        self._login("alice", "1234")
        create_response = self.client.post(
            "/api/swaps/requests",
            json={
                "source_date": "2026-09-07",
                "source_period": 1,
                "target_date": "2026-09-09",
                "target_period": 2,
            },
        )
        self.assertEqual(create_response.status_code, 200, create_response.text)
        request_id = create_response.json()["request"]["id"]
        self._logout()

        self._login("bob", "1234")
        accept_response = self.client.post(
            f"/api/swaps/requests/{request_id}/accept",
            json={"note": "가능합니다."},
        )
        self.assertEqual(accept_response.status_code, 200, accept_response.text)
        cancel_response = self.client.post(f"/api/swaps/requests/{request_id}/cancel")
        self.assertEqual(cancel_response.status_code, 200, cancel_response.text)
        self.assertEqual(cancel_response.json()["request"]["status"], "cancelled")
        self._logout()

        self._login("alice", "1234")
        weekly = self.client.get("/api/schedule/weekly", params={"date": "2026-09-07"})
        self.assertEqual(weekly.status_code, 200, weekly.text)
        monday = next(item for item in weekly.json()["days"] if item["date"] == "2026-09-07")
        wednesday = next(item for item in weekly.json()["days"] if item["date"] == "2026-09-09")
        monday_first = next(item for item in monday["periods"] if item["period"] == 1)
        wednesday_second = next(item for item in wednesday["periods"] if item["period"] == 2)
        self.assertEqual(monday_first["status"], "class")
        self.assertEqual(wednesday_second["status"], "free")
        notifications = self.client.get("/api/notifications")
        self.assertEqual(notifications.status_code, 200, notifications.text)
        titles = [item["title"] for item in notifications.json()["items"]]
        self.assertIn("교체 요청 취소", titles)


if __name__ == "__main__":
    unittest.main()
