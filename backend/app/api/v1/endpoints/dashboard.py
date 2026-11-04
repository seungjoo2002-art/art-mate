"""강사 수업 현황 대시보드(F-09, v0.3 범위)와 학생 '오늘 할 일' 통합 조회.

집계 화면 응답이므로 페이지네이션이 없다. 대상 규모는 담당 반 학생 수로 제한되고,
학생 '오늘' 목록은 각 200건 상한이다.
"""

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from app.api.deps import AcademyStaff, DbSession, require_user_types
from app.api.responses import AUTH_ERRORS, error_responses
from app.models.enums import UserType
from app.models.profile import Profile
from app.schemas.dashboard import InstructorDashboard, StudentToday
from app.services.dashboard import DashboardService

router = APIRouter(tags=["dashboard"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
DayQuery = Annotated[dt.date | None, Query(alias="date", description="기본: 오늘 (Asia/Seoul)")]


@router.get(
    "/academies/{academy_id}/dashboard",
    summary="강사 수업 현황 대시보드",
    description=(
        "담당 반 목록·반별 학생 수, 오늘 수업 일정, 학생별 출석 상태, 미완료 학원 과제 수, "
        "오늘 배포한 과제.\n\n"
        "`scope`: 강사는 항상 mine(담당 반). OWNER/MANAGER는 기본 all(학원 전체), mine 선택 가능."
    ),
    responses=AUTH_ERRORS | error_responses(404, 422),
)
async def instructor_dashboard(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    day: DayQuery = None,
    scope: Literal["mine", "all"] = "all",
) -> InstructorDashboard:
    return await DashboardService(session).instructor(actor, day, mine=scope == "mine")


@router.get(
    "/users/me/today",
    summary="오늘 할 일 통합 조회 (학생)",
    description=(
        "학원 과제 + 개인 할 일 + 오늘 수업 주제. 각 목록에 포함되는 항목: 그날 마감(날짜), "
        "마감이 지난 미완료, 마감 없는 미완료, 그날 완료한 항목. 미완료가 먼저 온다.\n\n"
        "개인 할 일은 본인에게만 보이며 강사 API로는 조회되지 않는다. "
        "`academy_id`로 한 학원의 과제·주제만 볼 수 있다."
    ),
    responses=AUTH_ERRORS | error_responses(422),
)
async def student_today(
    owner: Student,
    session: DbSession,
    day: DayQuery = None,
    academy_id: uuid.UUID | None = None,
) -> StudentToday:
    return await DashboardService(session).student_today(owner, day, academy_id)
