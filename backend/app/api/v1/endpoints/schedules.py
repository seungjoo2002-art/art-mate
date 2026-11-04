"""날짜 범위 수업 일정 조회 API (학생별·강사별, F-04)."""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AcademyMember, DbSession
from app.api.responses import AUTH_ERRORS, error_responses
from app.core import timezone as clock
from app.schemas.classes import Occurrence
from app.schemas.common import Page, PaginationQuery
from app.services.schedules import MAX_SCHEDULE_RANGE_DAYS, ScheduleService

router = APIRouter(prefix="/academies/{academy_id}/schedules", tags=["schedules"])


@router.get(
    "",
    summary="수업 일정 조회 (정규 + 휴강·변경·보강 적용)",
    description=(
        "정규 수업을 [from, to] 범위로 펼쳐 시작 시각 순으로 반환한다 "
        f"(기본: 오늘부터 7일, 최대 {MAX_SCHEDULE_RANGE_DAYS}일).\n\n"
        "- 학생: 배정된 반 + 본인 개인 보강\n"
        "- 강사 이상: 기본 학원 전체 / `mine=true` 담당 반 / "
        "`instructor_membership_id` 그 강사의 담당 반 / `student_membership_id` 그 학생 일정"
        "(담당 학생만)"
    ),
    responses=AUTH_ERRORS | error_responses(404, 422),
)
async def list_occurrences(
    academy_id: uuid.UUID,
    actor: AcademyMember,
    session: DbSession,
    pagination: PaginationQuery,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
    class_id: uuid.UUID | None = None,
    student_membership_id: uuid.UUID | None = None,
    instructor_membership_id: uuid.UUID | None = None,
    mine: bool = False,
) -> Page[Occurrence]:
    start = date_from or clock.local_today()
    end = date_to or start + dt.timedelta(days=6)
    occurrences = await ScheduleService(session).occurrences(
        actor,
        start,
        end,
        class_id=class_id,
        student_membership_id=student_membership_id,
        instructor_membership_id=instructor_membership_id,
        mine=mine,
    )
    window = occurrences[pagination.offset : pagination.offset + pagination.limit]
    return Page(
        items=window, total=len(occurrences), limit=pagination.limit, offset=pagination.offset
    )
