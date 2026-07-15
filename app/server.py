from __future__ import annotations

from pathlib import Path
import hashlib
import hmac
import json
import uuid
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.db import db_session, initialize_database
from app.excel_parser import TimetableValidationError, apply_preview_corrections, parse_timetable_workbook
from app.plan_export import build_plan_pdf, build_plan_xlsx, build_school_weekly_timetable_xlsx
from app.schemas import (
    CalendarSettingsPayload,
    CoverageRequestCreatePayload,
    EventCoverageCreatePayload,
    EventCoveragePreviewPayload,
    LoginPayload,
    NotificationDeletePayload,
    NotificationReadPayload,
    PasswordChangePayload,
    SemesterResetPayload,
    SwapDecisionPayload,
    SwapRequestCreatePayload,
    TeacherCreatePayload,
    TeacherUpdatePayload,
    TimetableConfirmPayload,
    TimetableSlotPayload,
)
from app.schedule_service import (
    analyze_timetable_teacher_sync,
    cancel_confirmed_coverage,
    cancel_confirmed_swap,
    cancel_user_coverage_request,
    cancel_user_swap_request,
    check_schedule_impacts,
    change_password,
    create_admin_timetable_slot,
    create_coverage_request,
    create_event_coverage_requests,
    create_swap_request,
    create_teacher,
    delete_admin_timetable_slot,
    delete_admin_coverage_request,
    delete_admin_swap_request,
    delete_notifications,
    dismiss_sent_coverage_request,
    dismiss_sent_swap_request,
    find_swap_candidates,
    get_available_coverage_teachers,
    get_calendar_settings,
    get_coverage_source_classes,
    get_school_month_schedule,
    get_school_weekly_schedule,
    get_schedule_debug_report,
    get_teacher_day_schedule,
    get_teacher_month_schedule,
    get_monthly_coverage_allowances,
    get_weekly_schedule,
    get_weekly_coverage_candidates,
    get_weekly_plan,
    get_semester_reset_status,
    get_user_by_id,
    import_preview_into_database,
    list_admin_timetable_slots,
    list_admin_swap_requests,
    list_coverage_requests_for_user,
    list_notifications,
    list_swap_requests_for_user,
    list_teachers,
    login_user,
    mark_notifications_read,
    perform_semester_reset,
    preview_event_coverage_plan,
    reset_teacher_password,
    restore_semester_reset_backup,
    seed_default_admin,
    serialize_user,
    update_calendar_settings,
    update_admin_timetable_slot,
    update_teacher_account,
    delete_teacher,
    respond_to_coverage_request,
    respond_to_swap_request,
)


BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


def _write_preview_file(settings: Settings, preview: dict) -> str:
    preview_id = uuid.uuid4().hex
    preview_path = settings.preview_dir / f"{preview_id}.json"
    preview_path.write_text(
        json.dumps(preview, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return preview_id


def _load_preview_file(settings: Settings, preview_id: str) -> dict:
    preview_path = settings.preview_dir / f"{preview_id}.json"
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="시간표 미리보기를 찾지 못했습니다.")
    return json.loads(preview_path.read_text(encoding="utf-8"))


def _preview_with_teacher_sync(settings: Settings, preview: dict) -> dict:
    with db_session(settings) as connection:
        teacher_sync = analyze_timetable_teacher_sync(connection, preview)
    return {**preview, "teacher_sync": teacher_sync}


def _build_session_cookie(settings: Settings, user_id: int) -> str:
    payload = str(user_id)
    signature = hmac.new(
        settings.secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}.{signature}"


def _read_session_cookie(settings: Settings, raw_cookie: str | None) -> int | None:
    if not raw_cookie or "." not in raw_cookie:
        return None
    payload, signature = raw_cookie.rsplit(".", 1)
    expected = hmac.new(
        settings.secret_key.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        return int(payload)
    except ValueError:
        return None


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    initialize_database(resolved_settings)
    with db_session(resolved_settings) as connection:
        seed_default_admin(connection, resolved_settings)

    app = FastAPI(
        title="결보강 관리 시스템",
        version="1.0.0",
        description="중·고등학교 교사용 수업 교체(결보강) 관리 웹사이트",
    )
    app.state.settings = resolved_settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    def current_user(request: Request) -> dict:
        user_id = _read_session_cookie(
            resolved_settings,
            request.cookies.get(resolved_settings.session_cookie_name),
        )
        if not user_id:
            raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
        with db_session(resolved_settings) as connection:
            user = get_user_by_id(connection, user_id)
            if not user:
                raise HTTPException(status_code=401, detail="세션이 만료되었습니다. 다시 로그인해 주세요.")
            return serialize_user(user)

    def admin_user(user: dict = Depends(current_user)) -> dict:
        if user["role"] != "admin":
            raise HTTPException(status_code=403, detail="관리자 권한이 필요합니다.")
        return user

    @app.api_route("/", methods=["GET", "HEAD"])
    def serve_index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/api/health")
    def health() -> dict:
        with db_session(resolved_settings) as connection:
            teacher_count = connection.execute(
                "SELECT COUNT(*) AS count FROM teachers WHERE role = 'teacher' AND is_active = 1"
            ).fetchone()["count"]
            pending_count = connection.execute(
                "SELECT COUNT(*) AS count FROM swap_requests WHERE status = 'pending'"
            ).fetchone()["count"]
        return {
            "status": "ok",
            "environment": resolved_settings.app_env,
            "teacher_count": teacher_count,
            "pending_swap_count": pending_count,
            "default_admin_username": resolved_settings.default_admin_username,
        }

    @app.get("/api/template")
    def download_template() -> FileResponse:
        if not resolved_settings.template_path.exists():
            raise HTTPException(status_code=404, detail="표준 양식 파일을 찾지 못했습니다.")
        return FileResponse(
            resolved_settings.template_path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=resolved_settings.template_path.name,
        )

    @app.post("/api/auth/login")
    def login(payload: LoginPayload, response: Response) -> dict:
        with db_session(resolved_settings) as connection:
            user = login_user(connection, payload.username.strip(), payload.password)
        response.set_cookie(
            key=resolved_settings.session_cookie_name,
            value=_build_session_cookie(resolved_settings, user["id"]),
            max_age=resolved_settings.session_max_age_seconds,
            httponly=True,
            samesite="lax",
        )
        return {"user": user}

    @app.post("/api/auth/logout")
    def logout(response: Response) -> dict:
        response.delete_cookie(resolved_settings.session_cookie_name)
        return {"ok": True}

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)) -> dict:
        return {"user": user}

    @app.post("/api/auth/change-password")
    def update_password(
        payload: PasswordChangePayload,
        user: dict = Depends(current_user),
    ) -> dict:
        with db_session(resolved_settings) as connection:
            updated = change_password(
                connection,
                user["id"],
                payload.current_password,
                payload.new_password,
            )
        return {"user": updated}

    @app.get("/api/schedule/weekly")
    def weekly_schedule(date: str | None = None, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return get_weekly_schedule(connection, user["id"], date)

    @app.get("/api/schedule/day")
    def day_schedule(target_date: str, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return get_teacher_day_schedule(connection, user["id"], target_date)

    @app.get("/api/schedule/monthly")
    def monthly_schedule(month: str, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return get_teacher_month_schedule(connection, user["id"], month)

    @app.get("/api/plans/weekly")
    def weekly_plan(date: str, user: dict = Depends(current_user)) -> dict:
        teacher_filter_id = None if user["role"] == "admin" else user["id"]
        with db_session(resolved_settings) as connection:
            return get_weekly_plan(connection, date, teacher_filter_id)

    @app.get("/api/plans/weekly/download")
    def weekly_plan_download(date: str, user: dict = Depends(current_user)) -> Response:
        teacher_filter_id = None if user["role"] == "admin" else user["id"]
        with db_session(resolved_settings) as connection:
            plan = get_weekly_plan(connection, date, teacher_filter_id)
        file_bytes = build_plan_xlsx(plan)
        filename = f"결보강계획서_{plan['week_start']}_{plan['week_end']}.xlsx"
        encoded_filename = quote(filename)
        return Response(
            content=file_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
        )

    @app.get("/api/plans/weekly/download.pdf")
    def weekly_plan_pdf_download(date: str, user: dict = Depends(current_user)) -> Response:
        teacher_filter_id = None if user["role"] == "admin" else user["id"]
        with db_session(resolved_settings) as connection:
            plan = get_weekly_plan(connection, date, teacher_filter_id)
        file_bytes = build_plan_pdf(plan)
        filename = f"결보강계획서_{plan['week_start']}_{plan['week_end']}.pdf"
        encoded_filename = quote(filename)
        return Response(
            content=file_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
        )

    @app.get("/api/school/monthly")
    def school_monthly_schedule(month: str, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return get_school_month_schedule(connection, month)

    @app.get("/api/admin/schedule/weekly/download")
    def admin_school_weekly_schedule_download(date: str, user: dict = Depends(admin_user)) -> Response:
        with db_session(resolved_settings) as connection:
            weekly = get_school_weekly_schedule(connection, date)
        file_bytes = build_school_weekly_timetable_xlsx(weekly)
        filename = f"주간전체시간표_반영본_{weekly['week_start']}_{weekly['week_end']}.xlsx"
        encoded_filename = quote(filename)
        return Response(
            content=file_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"},
        )

    @app.get("/api/admin/debug/schedule")
    def admin_schedule_debug(teacher_id: int, date: str, period: int, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return get_schedule_debug_report(connection, teacher_id, date, period)

    @app.get("/api/admin/coverage-allowances")
    def admin_coverage_allowances(month: str, rate: int, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return get_monthly_coverage_allowances(connection, month, rate)

    @app.post("/api/admin/event-coverage/preview")
    def admin_event_coverage_preview(payload: EventCoveragePreviewPayload, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return preview_event_coverage_plan(
                connection,
                payload.title,
                payload.start_date,
                payload.end_date,
                payload.absent_teacher_ids,
            )

    @app.post("/api/admin/event-coverage/requests")
    def admin_event_coverage_requests(payload: EventCoverageCreatePayload, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return create_event_coverage_requests(
                connection,
                payload.title,
                [assignment.model_dump() for assignment in payload.assignments],
            )

    @app.get("/api/swaps/candidates")
    def swap_candidates(date: str, period: int, week_offset: int = 0, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return find_swap_candidates(connection, user["id"], date, period, week_offset)

    @app.get("/api/swaps/requests")
    def my_swap_requests(user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return list_swap_requests_for_user(connection, user["id"])

    @app.get("/api/coverage/available")
    def coverage_available_teachers(date: str, period: int, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return get_available_coverage_teachers(connection, date, period)

    @app.get("/api/coverage/candidates")
    def coverage_candidates(date: str, period: int, week_offset: int = 0, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return get_weekly_coverage_candidates(connection, user["id"], date, period, week_offset)

    @app.get("/api/coverage/sources")
    def coverage_sources(date: str, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return get_coverage_source_classes(connection, user["id"], date)

    @app.get("/api/coverage/requests")
    def my_coverage_requests(user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return list_coverage_requests_for_user(connection, user["id"])

    @app.post("/api/coverage/requests")
    def create_coverage(payload: CoverageRequestCreatePayload, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = create_coverage_request(
                connection,
                user["id"],
                payload.class_date,
                payload.period,
                payload.responder_id,
            )
        return {"request": request_row}

    @app.post("/api/coverage/requests/{coverage_request_id}/accept")
    def accept_coverage(
        coverage_request_id: int,
        payload: SwapDecisionPayload,
        user: dict = Depends(current_user),
    ) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = respond_to_coverage_request(
                connection,
                user["id"],
                coverage_request_id,
                True,
                payload.note,
            )
        return {"request": request_row}

    @app.post("/api/coverage/requests/{coverage_request_id}/reject")
    def reject_coverage(
        coverage_request_id: int,
        payload: SwapDecisionPayload,
        user: dict = Depends(current_user),
    ) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = respond_to_coverage_request(
                connection,
                user["id"],
                coverage_request_id,
                False,
                payload.note,
            )
        return {"request": request_row}

    @app.post("/api/coverage/requests/{coverage_request_id}/dismiss")
    def dismiss_coverage_request(coverage_request_id: int, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = dismiss_sent_coverage_request(connection, user["id"], coverage_request_id)
        return {"request": request_row}

    @app.post("/api/coverage/requests/{coverage_request_id}/cancel")
    def cancel_coverage_request(coverage_request_id: int, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = cancel_user_coverage_request(connection, user["id"], coverage_request_id)
        return {"request": request_row}

    @app.post("/api/swaps/requests")
    def create_swap(payload: SwapRequestCreatePayload, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = create_swap_request(
                connection,
                user["id"],
                payload.source_date,
                payload.source_period,
                payload.target_date,
                payload.target_period,
            )
        return {"request": request_row}

    @app.post("/api/swaps/requests/{swap_request_id}/accept")
    def accept_swap(
        swap_request_id: int,
        payload: SwapDecisionPayload,
        user: dict = Depends(current_user),
    ) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = respond_to_swap_request(connection, user["id"], swap_request_id, True, payload.note)
        return {"request": request_row}

    @app.post("/api/swaps/requests/{swap_request_id}/reject")
    def reject_swap(
        swap_request_id: int,
        payload: SwapDecisionPayload,
        user: dict = Depends(current_user),
    ) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = respond_to_swap_request(connection, user["id"], swap_request_id, False, payload.note)
        return {"request": request_row}

    @app.post("/api/swaps/requests/{swap_request_id}/dismiss")
    def dismiss_swap_request(swap_request_id: int, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = dismiss_sent_swap_request(connection, user["id"], swap_request_id)
        return {"request": request_row}

    @app.post("/api/swaps/requests/{swap_request_id}/cancel")
    def cancel_swap_request(swap_request_id: int, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = cancel_user_swap_request(connection, user["id"], swap_request_id)
        return {"request": request_row}

    @app.get("/api/notifications")
    def notifications(user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return list_notifications(connection, user["id"])

    @app.post("/api/notifications/read")
    def read_notifications(payload: NotificationReadPayload, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            mark_notifications_read(connection, user["id"], payload.notification_ids, payload.mark_all)
        return {"ok": True}

    @app.post("/api/notifications/delete")
    def remove_notifications(payload: NotificationDeletePayload, user: dict = Depends(current_user)) -> dict:
        with db_session(resolved_settings) as connection:
            delete_notifications(connection, user["id"], payload.notification_ids, payload.delete_read)
        return {"ok": True}

    @app.get("/api/admin/calendar-settings")
    def admin_calendar_settings(user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return get_calendar_settings(connection)

    @app.put("/api/admin/calendar-settings")
    def save_calendar_settings(payload: CalendarSettingsPayload, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            data = update_calendar_settings(
                connection,
                payload.semester_start,
                payload.semester_end,
                [item.model_dump() for item in payload.special_days],
            )
        return data

    @app.get("/api/admin/teachers")
    def admin_teachers(user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return {"teachers": list_teachers(connection)}

    @app.post("/api/admin/teachers")
    def admin_create_teacher(payload: TeacherCreatePayload, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            teacher = create_teacher(
                connection,
                payload.display_name.strip(),
                payload.username.strip(),
                payload.role,
                resolved_settings.default_teacher_password,
            )
        return {"teacher": teacher}

    @app.put("/api/admin/teachers/{teacher_id}")
    def admin_update_teacher(
        teacher_id: int,
        payload: TeacherUpdatePayload,
        user: dict = Depends(admin_user),
    ) -> dict:
        with db_session(resolved_settings) as connection:
            teacher = update_teacher_account(
                connection,
                user["id"],
                teacher_id,
                payload.display_name.strip(),
                payload.username.strip(),
                payload.role,
                payload.schedule_label.strip(),
            )
        return {"teacher": teacher}

    @app.post("/api/admin/teachers/{teacher_id}/reset-password")
    def admin_reset_teacher_password(teacher_id: int, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            reset_teacher_password(connection, teacher_id, resolved_settings.default_teacher_password)
        return {"ok": True}

    @app.delete("/api/admin/teachers/{teacher_id}")
    def admin_delete_teacher(teacher_id: int, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            delete_teacher(connection, user["id"], teacher_id)
        return {"ok": True}

    @app.get("/api/admin/semester-reset")
    def admin_semester_reset_status(user: dict = Depends(admin_user)) -> dict:
        return get_semester_reset_status(resolved_settings)

    @app.post("/api/admin/semester-reset")
    def admin_semester_reset(payload: SemesterResetPayload, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            result = perform_semester_reset(connection, resolved_settings, payload.confirm_text)
        return result

    @app.post("/api/admin/semester-reset/undo")
    def admin_semester_reset_undo(user: dict = Depends(admin_user)) -> dict:
        restore_semester_reset_backup(resolved_settings)
        return {"ok": True}

    @app.post("/api/admin/timetable/preview")
    async def admin_preview_timetable(
        file: UploadFile = File(...),
        user: dict = Depends(admin_user),
    ) -> dict:
        if not file.filename or not file.filename.lower().endswith(".xlsx"):
            raise HTTPException(status_code=400, detail="시간표는 .xlsx 파일만 업로드할 수 있습니다.")
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="업로드한 파일이 비어 있습니다.")
        try:
            preview = parse_timetable_workbook(file_bytes, file.filename)
        except TimetableValidationError as exc:
            raise HTTPException(status_code=400, detail={"errors": exc.errors}) from exc
        preview_id = _write_preview_file(resolved_settings, preview)
        return {"preview_id": preview_id, "preview": _preview_with_teacher_sync(resolved_settings, preview)}

    @app.get("/api/admin/timetable/previews/{preview_id}")
    def admin_get_preview(preview_id: str, user: dict = Depends(admin_user)) -> dict:
        preview = _load_preview_file(resolved_settings, preview_id)
        return {"preview_id": preview_id, "preview": _preview_with_teacher_sync(resolved_settings, preview)}

    @app.post("/api/admin/timetable/confirm")
    def admin_confirm_timetable(payload: TimetableConfirmPayload, user: dict = Depends(admin_user)) -> dict:
        preview = _load_preview_file(resolved_settings, payload.preview_id)
        corrected = apply_preview_corrections(
            preview,
            [item.model_dump() for item in payload.corrections],
        )
        missing_teacher_actions = {
            item.teacher_id: item.action
            for item in payload.missing_teacher_actions
        }
        with db_session(resolved_settings) as connection:
            result = import_preview_into_database(
                connection,
                corrected,
                resolved_settings.default_teacher_password,
                missing_teacher_actions,
            )
        _write_preview_file(resolved_settings, corrected)
        return {"ok": True, "result": result, "preview": _preview_with_teacher_sync(resolved_settings, corrected)}

    @app.get("/api/admin/timetable/slots")
    def admin_timetable_slots(teacher_id: int | None = None, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return list_admin_timetable_slots(connection, teacher_id)

    @app.post("/api/admin/timetable/slots")
    def admin_create_timetable_slot(payload: TimetableSlotPayload, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            slot = create_admin_timetable_slot(
                connection,
                payload.teacher_id,
                payload.weekday,
                payload.period,
                payload.slot_type,
                payload.class_code,
                payload.subject,
                payload.location_label,
            )
        return {"slot": slot}

    @app.put("/api/admin/timetable/slots/{slot_id}")
    def admin_update_timetable_slot(
        slot_id: int,
        payload: TimetableSlotPayload,
        user: dict = Depends(admin_user),
    ) -> dict:
        with db_session(resolved_settings) as connection:
            slot = update_admin_timetable_slot(
                connection,
                slot_id,
                payload.teacher_id,
                payload.weekday,
                payload.period,
                payload.slot_type,
                payload.class_code,
                payload.subject,
                payload.location_label,
            )
        return {"slot": slot}

    @app.delete("/api/admin/timetable/slots/{slot_id}")
    def admin_delete_timetable_slot(slot_id: int, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            delete_admin_timetable_slot(connection, slot_id)
        return {"ok": True}

    @app.get("/api/admin/swaps")
    def admin_swaps(user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return list_admin_swap_requests(connection)

    @app.get("/api/admin/impact-check")
    def admin_impact_check(user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            return check_schedule_impacts(connection)

    @app.post("/api/admin/swaps/{swap_request_id}/cancel")
    def admin_cancel_swap(swap_request_id: int, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = cancel_confirmed_swap(connection, user["id"], swap_request_id)
        return {"request": request_row}

    @app.delete("/api/admin/swaps/{swap_request_id}")
    def admin_delete_swap(swap_request_id: int, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            delete_admin_swap_request(connection, swap_request_id)
        return {"ok": True}

    @app.post("/api/admin/coverage/{coverage_request_id}/cancel")
    def admin_cancel_coverage(coverage_request_id: int, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            request_row = cancel_confirmed_coverage(connection, user["id"], coverage_request_id)
        return {"request": request_row}

    @app.delete("/api/admin/coverage/{coverage_request_id}")
    def admin_delete_coverage(coverage_request_id: int, user: dict = Depends(admin_user)) -> dict:
        with db_session(resolved_settings) as connection:
            delete_admin_coverage_request(connection, coverage_request_id)
        return {"ok": True}

    return app
