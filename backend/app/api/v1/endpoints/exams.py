"""시험 타이머 API (F-10).

- 템플릿: 강사 이상 조회·생성, 만든 사람 또는 OWNER/MANAGER가 수정·보관
- 세션: 그 반 담당 강사 또는 OWNER/MANAGER가 생성·시작·종료·현황 조회
- 학생: 참가 중인 시험 타이머, 본인 작업 단계 변경

모든 시간 응답에는 `timer.server_time`이 있다. 프론트는 이 값으로 기기 시계 오차를 보정하고
로컬에서 카운트다운한다 (매초 API 호출 금지). 새로고침·다른 기기에서도 같은 API로 상태를 복원한다.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AcademyStaff, AcademyStudent, DbSession
from app.api.responses import AUTH_ERRORS, error_responses
from app.models.enums import ExamSessionStatus
from app.schemas.common import Page, PaginationQuery
from app.schemas.exams import (
    ExamSessionCreate,
    ExamSessionDetail,
    ExamSessionSummary,
    ExamTemplateCreate,
    ExamTemplateRead,
    ExamTemplateUpdate,
    MyExam,
    StageChange,
    StageTargetsUpdate,
)
from app.services.exams import ExamService

templates = APIRouter(prefix="/academies/{academy_id}/exam-templates", tags=["exams"])
sessions = APIRouter(prefix="/academies/{academy_id}/exam-sessions", tags=["exams"])

READ_ERRORS = AUTH_ERRORS | error_responses(404)
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422)


# ----------------------------------------------------------------------------- templates


@templates.post(
    "",
    summary="시험 템플릿 생성 (강사 이상)",
    description="stage_targets: SKETCH·PROGRESS·FINAL의 목표 시각(시작 후 분). "
    "SKETCH < PROGRESS < FINAL ≤ total_minutes.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_template(
    academy_id: uuid.UUID, data: ExamTemplateCreate, actor: AcademyStaff, session: DbSession
) -> ExamTemplateRead:
    return await ExamService(session).create_template(actor, data)


@templates.get("", summary="시험 템플릿 목록 (강사 이상)", responses=READ_ERRORS)
async def list_templates(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    pagination: PaginationQuery,
    include_archived: bool = False,
) -> Page[ExamTemplateRead]:
    items, total = await ExamService(session).list_templates(
        actor, pagination, include_archived=include_archived
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@templates.get("/{template_id}", summary="시험 템플릿 상세", responses=READ_ERRORS)
async def get_template(
    academy_id: uuid.UUID, template_id: uuid.UUID, actor: AcademyStaff, session: DbSession
) -> ExamTemplateRead:
    return await ExamService(session).get_template(actor, template_id)


@templates.patch(
    "/{template_id}",
    summary="시험 템플릿 수정 (만든 사람 / OWNER·MANAGER)",
    description="이미 만든 시험 세션에는 영향이 없다 (세션은 생성 시점 설정을 복사).",
    responses=WRITE_ERRORS,
)
async def update_template(
    academy_id: uuid.UUID,
    template_id: uuid.UUID,
    data: ExamTemplateUpdate,
    actor: AcademyStaff,
    session: DbSession,
) -> ExamTemplateRead:
    return await ExamService(session).update_template(actor, template_id, data)


@templates.put(
    "/{template_id}/stage-targets",
    summary="단계별 목표 시각 설정 (3단계 전체 교체)",
    responses=WRITE_ERRORS,
)
async def set_stage_targets(
    academy_id: uuid.UUID,
    template_id: uuid.UUID,
    data: StageTargetsUpdate,
    actor: AcademyStaff,
    session: DbSession,
) -> ExamTemplateRead:
    return await ExamService(session).update_template(
        actor, template_id, ExamTemplateUpdate(stage_targets=data.stage_targets)
    )


@templates.delete(
    "/{template_id}",
    summary="시험 템플릿 보관 (새 시험에 사용 불가)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def archive_template(
    academy_id: uuid.UUID, template_id: uuid.UUID, actor: AcademyStaff, session: DbSession
) -> None:
    await ExamService(session).archive_template(actor, template_id)


# ----------------------------------------------------------------------------- sessions


@sessions.post(
    "",
    summary="반 시험 세션 생성 (담당 강사 / OWNER·MANAGER)",
    description="템플릿 설정을 복사해 SCHEDULED로 만든다. `start_now: true`면 바로 시작.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_session(
    academy_id: uuid.UUID, data: ExamSessionCreate, actor: AcademyStaff, session: DbSession
) -> ExamSessionDetail:
    return await ExamService(session).create_session(actor, data)


@sessions.get(
    "",
    summary="시험 세션 목록 (담당 반, 최신순)",
    responses=READ_ERRORS,
)
async def list_sessions(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    pagination: PaginationQuery,
    class_id: uuid.UUID | None = None,
    session_status: Annotated[ExamSessionStatus | None, Query(alias="status")] = None,
) -> Page[ExamSessionSummary]:
    items, total = await ExamService(session).list_sessions(
        actor, pagination, class_id=class_id, status=session_status
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


# 주의: "/me"는 "/{session_id}"보다 먼저 선언해야 한다.
@sessions.get(
    "/me",
    summary="내가 참가한 시험 (학생)",
    description="`active=true`(기본): 진행 중인 시험만. false면 지난 시험 포함 (최신순).",
    responses=READ_ERRORS,
)
async def my_exams(
    academy_id: uuid.UUID,
    student: AcademyStudent,
    session: DbSession,
    pagination: PaginationQuery,
    active: bool = True,
) -> Page[MyExam]:
    items, total = await ExamService(session).my_exams(student, pagination, active_only=active)
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@sessions.get(
    "/{session_id}",
    summary="반 시험 현황 (담당 강사 / OWNER·MANAGER)",
    description="타이머 + 학생별 현재 단계, 단계별 인원, 목표보다 늦은 학생 수.",
    responses=READ_ERRORS,
)
async def session_detail(
    academy_id: uuid.UUID, session_id: uuid.UUID, actor: AcademyStaff, session: DbSession
) -> ExamSessionDetail:
    return await ExamService(session).detail(actor, session_id)


@sessions.post("/{session_id}/start", summary="시험 시작", responses=WRITE_ERRORS)
async def start_session(
    academy_id: uuid.UUID, session_id: uuid.UUID, actor: AcademyStaff, session: DbSession
) -> ExamSessionDetail:
    return await ExamService(session).start(actor, session_id)


@sessions.post(
    "/{session_id}/end",
    summary="시험 종료",
    description="이미 끝난 시험이면 현재 상태를 돌려준다.",
    responses=WRITE_ERRORS,
)
async def end_session(
    academy_id: uuid.UUID, session_id: uuid.UUID, actor: AcademyStaff, session: DbSession
) -> ExamSessionDetail:
    return await ExamService(session).end(actor, session_id)


@sessions.delete(
    "/{session_id}",
    summary="시작 전 시험 취소",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def cancel_session(
    academy_id: uuid.UUID, session_id: uuid.UUID, actor: AcademyStaff, session: DbSession
) -> None:
    await ExamService(session).cancel(actor, session_id)


@sessions.get(
    "/{session_id}/me",
    summary="내 시험 타이머 (학생)",
    description=(
        "남은 시간·현재 목표 단계·다음 단계까지 남은 시간·종료 여부. 새로고침 시 이 API로 복원."
    ),
    responses=READ_ERRORS,
)
async def my_exam(
    academy_id: uuid.UUID, session_id: uuid.UUID, student: AcademyStudent, session: DbSession
) -> MyExam:
    return await ExamService(session).my_exam(student, session_id)


@sessions.put(
    "/{session_id}/me/stage",
    summary="내 작업 단계 변경 (학생)",
    description="진행 중인 시험에서만. 종료·시간 만료 후에는 409 EXAM_NOT_RUNNING.",
    responses=WRITE_ERRORS,
)
async def change_my_stage(
    academy_id: uuid.UUID,
    session_id: uuid.UUID,
    data: StageChange,
    student: AcademyStudent,
    session: DbSession,
) -> MyExam:
    return await ExamService(session).change_stage(student, session_id, data.stage)
