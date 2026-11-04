"""학원 출석 API (F-03).

- 학생: 출석 버튼(check-in), 오늘 출석 여부, 본인 출석 기록
- 강사 이상: 담당 학생 출석 현황(날짜별), 출석 기록 조회·생성·수정, 수정 이력
  (학원 관리자 OWNER/MANAGER는 학원의 모든 학생)
"""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AcademyStaff, AcademyStudent, DbSession
from app.api.responses import AUTH_ERRORS, error_responses
from app.schemas.attendance import (
    AttendanceAuditRead,
    AttendanceCreate,
    AttendanceRead,
    AttendanceUpdate,
    StudentAttendance,
    StudentRef,
    TodayAttendance,
)
from app.schemas.common import Page, PaginationQuery
from app.services.attendance import AttendanceService

router = APIRouter(prefix="/academies/{academy_id}/attendance", tags=["attendance"])

READ_ERRORS = AUTH_ERRORS | error_responses(404, 422)
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422)
DateFrom = Annotated[dt.date | None, Query(alias="from", description="기본: to - 29일")]
DateTo = Annotated[dt.date | None, Query(alias="to", description="기본: 오늘 (Asia/Seoul)")]


class AttendanceDayPage(Page[StudentAttendance]):
    date: dt.date


# ----------------------------------------------------------------------------- student


@router.post(
    "/check-in",
    summary="출석하기 (학생)",
    description="오늘(Asia/Seoul) 출석을 PRESENT로 기록하고 체크인 시각을 저장한다. "
    "이미 오늘 기록이 있으면 409 ALREADY_CHECKED_IN.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def check_in(
    academy_id: uuid.UUID, student: AcademyStudent, session: DbSession
) -> AttendanceRead:
    record = await AttendanceService(session).check_in(student)
    return AttendanceRead.model_validate(record)


@router.get("/me/today", summary="오늘 출석 여부 (학생)", responses=READ_ERRORS)
async def my_today(
    academy_id: uuid.UUID, student: AcademyStudent, session: DbSession
) -> TodayAttendance:
    today, record = await AttendanceService(session).today(student)
    return TodayAttendance(
        date=today,
        checked_in=record is not None,
        record=AttendanceRead.model_validate(record) if record else None,
    )


@router.get("/me", summary="내 출석 기록 (학생, 최근 날짜순)", responses=READ_ERRORS)
async def my_records(
    academy_id: uuid.UUID,
    student: AcademyStudent,
    session: DbSession,
    pagination: PaginationQuery,
    date_from: DateFrom = None,
    date_to: DateTo = None,
) -> Page[AttendanceRead]:
    records, total = await AttendanceService(session).my_records(
        student, pagination, date_from, date_to
    )
    return Page(
        items=[AttendanceRead.model_validate(r) for r in records],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


# ----------------------------------------------------------------------------- staff


@router.get(
    "",
    summary="날짜별 출석 현황 (강사 이상)",
    description="담당 학생 전원(이름순)과 그날 기록. 기록이 없으면 `record: null`(미출석). "
    "`class_id`로 한 반만 볼 수 있다 (그 반 담당 강사 또는 OWNER/MANAGER).",
    responses=READ_ERRORS,
)
async def day_status(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    pagination: PaginationQuery,
    day: Annotated[dt.date | None, Query(alias="date", description="기본: 오늘")] = None,
    class_id: uuid.UUID | None = None,
) -> AttendanceDayPage:
    resolved, rows, total = await AttendanceService(session).day_status(
        actor, day, pagination, class_id
    )
    items = [
        StudentAttendance(
            student=StudentRef(
                membership_id=membership.id,
                user_id=profile.id,
                display_name=profile.display_name,
                avatar_path=profile.avatar_path,
            ),
            record=AttendanceRead.model_validate(record) if record else None,
        )
        for membership, profile, record in rows
    ]
    return AttendanceDayPage(
        date=resolved, items=items, total=total, limit=pagination.limit, offset=pagination.offset
    )


@router.get(
    "/records",
    summary="출석 기록 목록 (강사 이상)",
    description="담당 학생들의 기록 (최근 날짜순). `student_membership_id`로 한 학생만.",
    responses=READ_ERRORS,
)
async def list_records(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    pagination: PaginationQuery,
    date_from: DateFrom = None,
    date_to: DateTo = None,
    student_membership_id: uuid.UUID | None = None,
) -> Page[AttendanceRead]:
    records, total = await AttendanceService(session).list_records(
        actor,
        pagination,
        start=date_from,
        end=date_to,
        student_membership_id=student_membership_id,
    )
    return Page(
        items=[AttendanceRead.model_validate(r) for r in records],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.post(
    "/records",
    summary="출석 기록 생성 (강사 이상, 담당 학생)",
    description="학생이 체크인하지 않은 날의 출석·결석을 기록한다. 이미 있으면 409 "
    "ATTENDANCE_ALREADY_RECORDED (→ PATCH로 수정). 수정 이력(CREATED)이 남는다.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_record(
    academy_id: uuid.UUID, data: AttendanceCreate, actor: AcademyStaff, session: DbSession
) -> AttendanceRead:
    record = await AttendanceService(session).create_record(actor, data)
    return AttendanceRead.model_validate(record)


@router.patch(
    "/records/{record_id}",
    summary="출석 기록 수정 (강사 이상, 담당 학생)",
    description="status·note 변경. 변경 전·후 값과 사유(reason)가 수정 이력에 남는다.",
    responses=WRITE_ERRORS,
)
async def update_record(
    academy_id: uuid.UUID,
    record_id: uuid.UUID,
    data: AttendanceUpdate,
    actor: AcademyStaff,
    session: DbSession,
) -> AttendanceRead:
    record = await AttendanceService(session).update_record(actor, record_id, data)
    return AttendanceRead.model_validate(record)


@router.get(
    "/records/{record_id}/history",
    summary="출석 수정 이력 (강사 이상, 오래된 순)",
    responses=READ_ERRORS,
)
async def record_history(
    academy_id: uuid.UUID,
    record_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    pagination: PaginationQuery,
) -> Page[AttendanceAuditRead]:
    rows, total = await AttendanceService(session).history(actor, record_id, pagination)
    items = [
        AttendanceAuditRead(
            **AttendanceAuditRead.model_validate(log).model_dump(exclude={"changed_by_name"}),
            changed_by_name=name,
        )
        for log, name in rows
    ]
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)
