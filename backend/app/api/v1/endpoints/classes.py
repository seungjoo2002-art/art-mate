"""반(Class)·반 배정·담당 강사·정규 수업·일정 예외 API (F-04).

접근 규칙
- 반 생성·수정·보관(ARCHIVED): OWNER/MANAGER
- 반 목록·상세·정규 수업 조회: 강사 이상은 학원 전체, 학생은 배정된 반만 (그 외 404)
- 반 멤버 목록: 강사 이상
- 학생 배정·해제, 정규 수업·휴강·변경·보강 등록: OWNER/MANAGER 또는 그 반 담당 강사
- 담당 강사 지정·해제: OWNER/MANAGER
"""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AcademyAdmin, AcademyMember, AcademyStaff, DbSession
from app.api.responses import AUTH_ERRORS, error_responses
from app.core import timezone as clock
from app.models.enums import ClassMemberRole, ClassMemberStatus, ClassStatus
from app.schemas.classes import (
    ClassCreate,
    ClassMemberCreate,
    ClassMemberRead,
    ClassRead,
    ClassUpdate,
    ScheduleCreate,
    ScheduleExceptionCreate,
    ScheduleExceptionRead,
    ScheduleExceptionUpdate,
    ScheduleRead,
    ScheduleUpdate,
)
from app.schemas.common import Page, PaginationQuery
from app.services.classes import ClassService
from app.services.schedules import ScheduleService

router = APIRouter(prefix="/academies/{academy_id}/classes", tags=["classes"])

READ_ERRORS = AUTH_ERRORS | error_responses(404)
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422)


# ----------------------------------------------------------------------------- classes


@router.post(
    "",
    summary="반 생성 (OWNER/MANAGER)",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_class(
    academy_id: uuid.UUID, data: ClassCreate, actor: AcademyAdmin, session: DbSession
) -> ClassRead:
    return await ClassService(session).create(actor, data)


@router.get(
    "",
    summary="반 목록",
    description="강사 이상: 학원 전체 (`mine=true`: 담당 반). 학생: 배정된 반만. "
    "`status` 생략 시 ACTIVE.",
    responses=READ_ERRORS,
)
async def list_classes(
    academy_id: uuid.UUID,
    actor: AcademyMember,
    session: DbSession,
    pagination: PaginationQuery,
    class_status: Annotated[ClassStatus, Query(alias="status")] = ClassStatus.ACTIVE,
    mine: bool = False,
) -> Page[ClassRead]:
    items, total = await ClassService(session).list_classes(
        actor, pagination, status=class_status, mine=mine
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.get("/{class_id}", summary="반 상세", responses=READ_ERRORS)
async def get_class(
    academy_id: uuid.UUID, class_id: uuid.UUID, actor: AcademyMember, session: DbSession
) -> ClassRead:
    return await ClassService(session).get(actor, class_id)


@router.patch(
    "/{class_id}",
    summary="반 수정·보관 (OWNER/MANAGER)",
    description="`status: ARCHIVED`로 반을 종료한다 (기록 유지, 새 배정·과제·일정 불가).",
    responses=WRITE_ERRORS,
)
async def update_class(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    data: ClassUpdate,
    actor: AcademyAdmin,
    session: DbSession,
) -> ClassRead:
    return await ClassService(session).update(actor, class_id, data)


# ----------------------------------------------------------------------------- members


@router.get("/{class_id}/members", summary="반 멤버 목록 (강사 이상)", responses=READ_ERRORS)
async def list_class_members(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    pagination: PaginationQuery,
    role: ClassMemberRole | None = None,
    member_status: Annotated[ClassMemberStatus, Query(alias="status")] = ClassMemberStatus.ACTIVE,
) -> Page[ClassMemberRead]:
    items, total = await ClassService(session).list_members(
        actor, class_id, pagination, status=member_status, role=role
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.post(
    "/{class_id}/members",
    summary="학생 배정 / 담당 강사 지정",
    description="학원 멤버 ID로 배정한다. 학생 멤버는 STUDENT, 강사 이상은 담당 강사(INSTRUCTOR)가 "
    "된다. 담당 강사 지정은 OWNER/MANAGER만. 이미 배정됨 → 409 ALREADY_IN_CLASS.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def add_class_member(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    data: ClassMemberCreate,
    actor: AcademyStaff,
    session: DbSession,
) -> ClassMemberRead:
    return await ClassService(session).add_member(actor, class_id, data.membership_id)


@router.delete(
    "/{class_id}/members/{class_member_id}",
    summary="반 배정 해제",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def remove_class_member(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    class_member_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
) -> None:
    await ClassService(session).remove_member(actor, class_id, class_member_id)


# ----------------------------------------------------------------------------- schedules


@router.post(
    "/{class_id}/schedules",
    summary="정규 수업 등록 (매주 반복)",
    description="요일(0=월)과 학원 현지 시간(Asia/Seoul). 같은 반의 겹치는 정규 수업 → 409.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_schedule(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    data: ScheduleCreate,
    actor: AcademyMember,
    session: DbSession,
) -> ScheduleRead:
    schedule = await ScheduleService(session).create_schedule(actor, class_id, data)
    return ScheduleRead.model_validate(schedule)


@router.get("/{class_id}/schedules", summary="정규 수업 목록", responses=READ_ERRORS)
async def list_schedules(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    actor: AcademyMember,
    session: DbSession,
    pagination: PaginationQuery,
    include_inactive: bool = False,
) -> Page[ScheduleRead]:
    items, total = await ScheduleService(session).list_schedules(
        actor, class_id, pagination, include_inactive=include_inactive
    )
    return Page(
        items=[ScheduleRead.model_validate(s) for s in items],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.patch(
    "/{class_id}/schedules/{schedule_id}",
    summary="정규 수업 변경",
    description="모든 회차(과거 포함)에 적용된다. 특정 날짜부터 바꾸려면 기존 일정의 "
    "`effective_until`을 정하고 새 정규 수업을 등록하세요. 1회만 바꾸려면 schedule-exceptions.",
    responses=WRITE_ERRORS,
)
async def update_schedule(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    schedule_id: uuid.UUID,
    data: ScheduleUpdate,
    actor: AcademyMember,
    session: DbSession,
) -> ScheduleRead:
    schedule = await ScheduleService(session).update_schedule(actor, class_id, schedule_id, data)
    return ScheduleRead.model_validate(schedule)


@router.delete(
    "/{class_id}/schedules/{schedule_id}",
    summary="정규 수업 삭제 (비활성화)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def delete_schedule(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    schedule_id: uuid.UUID,
    actor: AcademyMember,
    session: DbSession,
) -> None:
    await ScheduleService(session).delete_schedule(actor, class_id, schedule_id)


# ----------------------------------------------------------------------------- exceptions


@router.post(
    "/{class_id}/schedule-exceptions",
    summary="휴강 / 1회 일정 변경 / 보강 등록",
    description="kind=CANCELLATION(휴강), RESCHEDULE(1회 변경), MAKEUP(보강, "
    "`student_membership_id`가 있으면 개인 보강). 같은 회차에 휴강·변경이 이미 있으면 409.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_schedule_exception(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    data: ScheduleExceptionCreate,
    actor: AcademyMember,
    session: DbSession,
) -> ScheduleExceptionRead:
    exception = await ScheduleService(session).create_exception(actor, class_id, data)
    return ScheduleExceptionRead.model_validate(exception)


@router.get(
    "/{class_id}/schedule-exceptions",
    summary="일정 예외 목록 (강사 이상)",
    description="session_date 또는 original_date가 [from, to]에 있는 예외. 기본: 오늘부터 30일.",
    responses=READ_ERRORS | error_responses(422),
)
async def list_schedule_exceptions(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    pagination: PaginationQuery,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
) -> Page[ScheduleExceptionRead]:
    start = date_from or clock.local_today()
    end = date_to or start + dt.timedelta(days=29)
    items, total = await ScheduleService(session).list_exceptions(
        actor, class_id, start, end, pagination
    )
    return Page(
        items=[ScheduleExceptionRead.model_validate(e) for e in items],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.patch(
    "/{class_id}/schedule-exceptions/{exception_id}",
    summary="일정 예외 수정 (변경·보강 날짜·시간·사유)",
    responses=WRITE_ERRORS,
)
async def update_schedule_exception(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    exception_id: uuid.UUID,
    data: ScheduleExceptionUpdate,
    actor: AcademyMember,
    session: DbSession,
) -> ScheduleExceptionRead:
    exception = await ScheduleService(session).update_exception(actor, class_id, exception_id, data)
    return ScheduleExceptionRead.model_validate(exception)


@router.delete(
    "/{class_id}/schedule-exceptions/{exception_id}",
    summary="일정 예외 취소",
    description="휴강·1회 변경을 취소하면 원래 정규 수업으로 돌아간다. 보강을 취소하면 일정 "
    "조회에 status=CANCELLED로 표시된다.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def delete_schedule_exception(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    exception_id: uuid.UUID,
    actor: AcademyMember,
    session: DbSession,
) -> None:
    await ScheduleService(session).delete_exception(actor, class_id, exception_id)
