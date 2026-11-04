import datetime as dt
import uuid
from typing import Any, ClassVar, Self

from pydantic import BaseModel, Field, model_validator

from app.models.enums import AttendanceAuditAction, AttendanceSource, AttendanceStatus
from app.schemas.common import APIModel
from app.schemas.fields import InputModel, PatchModel, ShortText


class StudentRef(BaseModel):
    """학원 내 학생 표시 정보 (이메일 등 계정 정보는 포함하지 않음)."""

    membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    avatar_path: str | None


class AttendanceRead(APIModel):
    id: uuid.UUID
    academy_id: uuid.UUID
    student_membership_id: uuid.UUID
    attendance_date: dt.date = Field(description="출석일 (Asia/Seoul)")
    status: AttendanceStatus
    source: AttendanceSource
    checked_in_at: dt.datetime | None
    note: str | None
    updated_by: uuid.UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime


class TodayAttendance(BaseModel):
    date: dt.date
    checked_in: bool
    record: AttendanceRead | None


class StudentAttendance(BaseModel):
    """날짜별 출석 현황의 학생 1명. 기록이 없으면 record=null (미출석)."""

    student: StudentRef
    record: AttendanceRead | None


class AttendanceCreate(InputModel):
    """강사가 학생 출석을 직접 기록 (학생이 체크인하지 않은 날)."""

    student_membership_id: uuid.UUID
    attendance_date: dt.date
    status: AttendanceStatus
    note: ShortText | None = None
    reason: ShortText | None = Field(default=None, description="수정 이력에 남길 사유")


class AttendanceUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"status"})

    status: AttendanceStatus | None = None
    note: ShortText | None = None
    reason: ShortText | None = Field(default=None, description="수정 이력에 남길 사유")

    @model_validator(mode="after")
    def _has_change(self) -> Self:
        if not ({"status", "note"} & self.model_fields_set):
            raise ValueError("status or note is required")
        return self


class AttendanceAuditRead(APIModel):
    id: uuid.UUID
    attendance_record_id: uuid.UUID
    action: AttendanceAuditAction
    changed_by: uuid.UUID | None
    changed_by_name: str | None = None
    previous: dict[str, Any] | None
    current: dict[str, Any]
    reason: str | None
    created_at: dt.datetime
