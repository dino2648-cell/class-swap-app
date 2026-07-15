from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LoginPayload(BaseModel):
    username: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=1, max_length=120)


class PasswordChangePayload(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=120)
    new_password: str = Field(..., min_length=4, max_length=120)


class CalendarSpecialDayPayload(BaseModel):
    date: str
    label: str = Field(..., min_length=1, max_length=80)
    kind: str = Field(..., min_length=1, max_length=40)


class CalendarSettingsPayload(BaseModel):
    semester_start: str
    semester_end: str
    special_days: list[CalendarSpecialDayPayload] = Field(default_factory=list)


class SwapRequestCreatePayload(BaseModel):
    source_date: str
    source_period: int = Field(..., ge=1, le=7)
    target_date: str
    target_period: int = Field(..., ge=1, le=7)


class CoverageRequestCreatePayload(BaseModel):
    class_date: str
    period: int = Field(..., ge=1, le=7)
    responder_id: int = Field(..., ge=1)


class EventCoveragePreviewPayload(BaseModel):
    title: str = Field(default="", max_length=120)
    start_date: str
    end_date: str
    absent_teacher_ids: list[int] = Field(default_factory=list)


class EventCoverageAssignmentPayload(BaseModel):
    requester_id: int = Field(..., ge=1)
    class_date: str
    period: int = Field(..., ge=1, le=7)
    responder_id: int = Field(..., ge=1)


class EventCoverageCreatePayload(BaseModel):
    title: str = Field(default="", max_length=120)
    assignments: list[EventCoverageAssignmentPayload] = Field(default_factory=list)


class SwapDecisionPayload(BaseModel):
    note: str = Field(default="", max_length=300)


class NotificationReadPayload(BaseModel):
    notification_ids: list[int] = Field(default_factory=list)
    mark_all: bool = False


class NotificationDeletePayload(BaseModel):
    notification_ids: list[int] = Field(default_factory=list)
    delete_read: bool = False


class TeacherCreatePayload(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=80)
    username: str = Field(..., min_length=1, max_length=80)
    role: str = Field(default="teacher")

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"admin", "teacher"}:
            raise ValueError("role은 admin 또는 teacher여야 합니다.")
        return value


class TeacherUpdatePayload(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=80)
    username: str = Field(..., min_length=1, max_length=80)
    role: str = Field(..., min_length=1, max_length=20)
    schedule_label: str = Field(default="", max_length=80)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in {"admin", "teacher"}:
            raise ValueError("role은 admin 또는 teacher여야 합니다.")
        return value


class TimetableSlotPayload(BaseModel):
    teacher_id: int = Field(..., ge=1)
    weekday: int = Field(..., ge=0, le=4)
    period: int = Field(..., ge=1, le=7)
    slot_type: str = Field(default="class")
    class_code: str = Field(default="", max_length=20)
    subject: str = Field(default="", max_length=80)
    location_label: str = Field(default="", max_length=80)

    @field_validator("slot_type")
    @classmethod
    def validate_slot_type(cls, value: str) -> str:
        if value not in {"class", "travel"}:
            raise ValueError("slot_type은 class 또는 travel이어야 합니다.")
        return value


class TimetableCorrectionPayload(BaseModel):
    cell_ref: str = Field(..., min_length=2, max_length=10)
    value: str = Field(default="", max_length=120)


class MissingTeacherActionPayload(BaseModel):
    teacher_id: int = Field(..., ge=1)
    action: str = Field(default="keep")

    @field_validator("action")
    @classmethod
    def validate_action(cls, value: str) -> str:
        if value not in {"keep", "deactivate", "delete"}:
            raise ValueError("action은 keep, deactivate, delete 중 하나여야 합니다.")
        return value


class TimetableConfirmPayload(BaseModel):
    preview_id: str = Field(..., min_length=1, max_length=80)
    corrections: list[TimetableCorrectionPayload] = Field(default_factory=list)
    missing_teacher_actions: list[MissingTeacherActionPayload] = Field(default_factory=list)


class SemesterResetPayload(BaseModel):
    confirm_text: str = Field(..., min_length=1, max_length=40)
