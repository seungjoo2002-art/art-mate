import datetime as dt
import uuid
from typing import Annotated, ClassVar, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.models.enums import (
    ClassMemberRole,
    ClassMemberStatus,
    ClassStatus,
    OccurrenceKind,
    OccurrenceStatus,
    ScheduleExceptionKind,
)
from app.schemas.common import APIModel
from app.schemas.fields import InputModel, Location, PatchModel, ShortText, WallTime

ClassName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ClassDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Subject = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Weekday = Annotated[int, Field(ge=0, le=6, description="0=월요일 ... 6=일요일")]


# ----------------------------------------------------------------------------- classes


class ClassCreate(InputModel):
    name: ClassName
    description: ClassDescription | None = None
    subject: Subject | None = Field(default=None, examples=["소묘"])


class ClassUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"name", "status"})

    name: ClassName | None = None
    description: ClassDescription | None = None
    subject: Subject | None = None
    status: ClassStatus | None = None


class ClassInstructor(BaseModel):
    membership_id: uuid.UUID
    display_name: str


class ClassRead(APIModel):
    id: uuid.UUID
    academy_id: uuid.UUID
    name: str
    description: str | None
    subject: str | None
    status: ClassStatus
    student_count: int
    instructors: list[ClassInstructor]
    # 요청자의 반 역할 (반에 배정되지 않았으면 null)
    my_role: ClassMemberRole | None = None
    created_at: dt.datetime


class ClassMemberCreate(InputModel):
    membership_id: uuid.UUID = Field(description="학원 멤버 ID (GET /academies/{id}/members 의 id)")


class ClassMemberRead(BaseModel):
    id: uuid.UUID
    class_id: uuid.UUID
    membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    avatar_path: str | None
    role: ClassMemberRole
    status: ClassMemberStatus
    joined_at: dt.datetime
    ended_at: dt.datetime | None


# ----------------------------------------------------------------------------- schedules


class ScheduleCreate(InputModel):
    weekday: Weekday
    start_time: WallTime = Field(examples=["16:00"])
    end_time: WallTime = Field(examples=["18:00"])
    effective_from: dt.date | None = Field(default=None, description="기본값: 오늘 (Asia/Seoul)")
    effective_until: dt.date | None = None
    location: Location | None = None

    @model_validator(mode="after")
    def _check_ranges(self) -> Self:
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        if (
            self.effective_from
            and self.effective_until
            and self.effective_until < self.effective_from
        ):
            raise ValueError("effective_until must be on or after effective_from")
        return self


class ScheduleUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset(
        {"weekday", "start_time", "end_time", "effective_from"}
    )

    weekday: Weekday | None = None
    start_time: WallTime | None = None
    end_time: WallTime | None = None
    effective_from: dt.date | None = None
    effective_until: dt.date | None = None
    location: Location | None = None


class ScheduleRead(APIModel):
    id: uuid.UUID
    class_id: uuid.UUID
    weekday: int
    start_time: dt.time
    end_time: dt.time
    effective_from: dt.date
    effective_until: dt.date | None
    location: str | None
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class ScheduleExceptionCreate(InputModel):
    """kind별 필수 필드

    - CANCELLATION: schedule_id, original_date
    - RESCHEDULE: schedule_id, original_date, session_date, start_time, end_time
    - MAKEUP: session_date, start_time, end_time (+ student_membership_id: 개인 보강)
    """

    kind: ScheduleExceptionKind
    schedule_id: uuid.UUID | None = None
    original_date: dt.date | None = None
    session_date: dt.date | None = None
    start_time: WallTime | None = None
    end_time: WallTime | None = None
    location: Location | None = None
    student_membership_id: uuid.UUID | None = None
    reason: ShortText | None = None

    @model_validator(mode="after")
    def _check_kind_fields(self) -> Self:
        moves = self.kind in {ScheduleExceptionKind.RESCHEDULE, ScheduleExceptionKind.MAKEUP}
        targets_regular = self.kind != ScheduleExceptionKind.MAKEUP
        timing = (self.session_date, self.start_time, self.end_time)
        if targets_regular and (self.schedule_id is None or self.original_date is None):
            raise ValueError(f"{self.kind} requires schedule_id and original_date")
        if not targets_regular and (self.schedule_id or self.original_date):
            raise ValueError("MAKEUP must not have schedule_id or original_date")
        if moves and any(v is None for v in timing):
            raise ValueError(f"{self.kind} requires session_date, start_time and end_time")
        if not moves and any(v is not None for v in timing):
            raise ValueError("CANCELLATION must not have session_date, start_time or end_time")
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        if self.student_membership_id and self.kind != ScheduleExceptionKind.MAKEUP:
            raise ValueError("student_membership_id is only allowed for MAKEUP")
        return self


class ScheduleExceptionUpdate(PatchModel):
    """RESCHEDULE·MAKEUP의 날짜·시간·장소·사유 수정 (CANCELLATION은 reason만)."""

    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"session_date", "start_time", "end_time"})

    session_date: dt.date | None = None
    start_time: WallTime | None = None
    end_time: WallTime | None = None
    location: Location | None = None
    reason: ShortText | None = None


class ScheduleExceptionRead(APIModel):
    id: uuid.UUID
    class_id: uuid.UUID
    kind: ScheduleExceptionKind
    schedule_id: uuid.UUID | None
    original_date: dt.date | None
    session_date: dt.date | None
    start_time: dt.time | None
    end_time: dt.time | None
    location: str | None
    student_membership_id: uuid.UUID | None
    reason: str | None
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class Occurrence(BaseModel):
    """특정 날짜의 수업 1회 (정규 수업을 펼친 결과 + 예외 적용)."""

    class_id: uuid.UUID
    class_name: str
    kind: OccurrenceKind
    status: OccurrenceStatus
    date: dt.date = Field(description="수업 날짜 (Asia/Seoul)")
    starts_at: dt.datetime = Field(description="ISO 8601, +09:00")
    ends_at: dt.datetime
    original_date: dt.date | None = Field(default=None, description="RESCHEDULED: 원래 수업 날짜")
    schedule_id: uuid.UUID | None = None
    exception_id: uuid.UUID | None = None
    location: str | None = None
    reason: str | None = None
    student_membership_id: uuid.UUID | None = Field(
        default=None, description="개인 보강 대상 학생 (반 전체 보강이면 null)"
    )
