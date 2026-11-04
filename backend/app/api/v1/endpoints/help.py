"""질문 콜·대기열 API (F-07). v0.5는 REST 폴링 (권장 주기: 강사 5초, 학생 10초).

- 학생: 질문 요청·취소, 내 상태(순번·예상 대기시간·호출 여부)
- 강사(그 반 담당 강사 / OWNER·MANAGER): 반 대기열, 다음 학생 호출, 처리 시작·완료, 건너뛰기,
  호출 취소(대기열 복귀), 요청 취소
"""

import uuid
from typing import Literal

from fastapi import APIRouter, status

from app.api.deps import (
    AcademyMember,
    AcademyStaff,
    AcademyStudent,
    AppSettings,
    DbSession,
    HelpPublisher,
)
from app.api.responses import AUTH_ERRORS, error_responses
from app.schemas.common import Page, PaginationQuery
from app.schemas.help import (
    ClassEstimate,
    HelpQueue,
    HelpRequestCreate,
    MyHelpRequest,
    StaffHelpRequest,
)
from app.services.help_queue import HelpQueueService

requests = APIRouter(prefix="/academies/{academy_id}/help-requests", tags=["help-queue"])
queues = APIRouter(
    prefix="/academies/{academy_id}/classes/{class_id}/help-queue", tags=["help-queue"]
)

READ_ERRORS = AUTH_ERRORS | error_responses(404)
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422)
StaffAction = Literal["call", "start", "complete", "skip", "requeue", "cancel"]


def _service(session, settings, publisher) -> HelpQueueService:  # type: ignore[no-untyped-def]
    return HelpQueueService(session, settings, publisher)


# ----------------------------------------------------------------------------- student


@requests.post(
    "",
    summary="질문 요청 (학생)",
    description="배정된 반의 담당 강사를 호출한다. 같은 반에 진행 중인 요청이 있으면 409 "
    "HELP_REQUEST_ALREADY_ACTIVE (`details.help_request_id`).",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_help_request(
    academy_id: uuid.UUID,
    data: HelpRequestCreate,
    student: AcademyStudent,
    session: DbSession,
    settings: AppSettings,
    publisher: HelpPublisher,
) -> MyHelpRequest:
    return await _service(session, settings, publisher).create(student, data)


# 주의: "/me..." 경로는 "/{help_request_id}/{action}"보다 먼저 선언해야 한다.
@requests.get(
    "/me",
    summary="내 질문 요청 목록 (학생)",
    description="`active=true`(기본): WAITING·CALLED·IN_PROGRESS만. 순번·예상 대기시간 포함.",
    responses=READ_ERRORS,
)
async def my_help_requests(
    academy_id: uuid.UUID,
    student: AcademyStudent,
    session: DbSession,
    settings: AppSettings,
    publisher: HelpPublisher,
    pagination: PaginationQuery,
    active: bool = True,
) -> Page[MyHelpRequest]:
    items, total = await _service(session, settings, publisher).my_requests(
        student, pagination, active_only=active
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@requests.get(
    "/me/{help_request_id}",
    summary="내 질문 상태 (학생, 폴링용)",
    description="status, 대기 순번(position), 예상 대기시간(estimate), 호출한 강사, 완료 여부.",
    responses=READ_ERRORS,
)
async def my_help_request(
    academy_id: uuid.UUID,
    help_request_id: uuid.UUID,
    student: AcademyStudent,
    session: DbSession,
    settings: AppSettings,
    publisher: HelpPublisher,
) -> MyHelpRequest:
    return await _service(session, settings, publisher).my_request(student, help_request_id)


@requests.post(
    "/me/{help_request_id}/cancel",
    summary="질문 요청 취소 (학생)",
    description="WAITING·CALLED일 때만. 처리 중(IN_PROGRESS)·종료된 요청은 409.",
    responses=WRITE_ERRORS,
)
async def cancel_my_help_request(
    academy_id: uuid.UUID,
    help_request_id: uuid.UUID,
    student: AcademyStudent,
    session: DbSession,
    settings: AppSettings,
    publisher: HelpPublisher,
) -> MyHelpRequest:
    return await _service(session, settings, publisher).cancel_mine(student, help_request_id)


# ----------------------------------------------------------------------------- staff


@requests.post(
    "/{help_request_id}/{action}",
    summary="질문 처리 (강사)",
    description=(
        "- `call`: WAITING → CALLED (특정 학생 호출)\n"
        "- `start`: WAITING·CALLED → IN_PROGRESS (질문 처리 시작)\n"
        "- `complete`: CALLED·IN_PROGRESS → COMPLETED\n"
        "- `skip`: WAITING·CALLED → SKIPPED (자리에 없음 등)\n"
        "- `requeue`: CALLED → WAITING (호출 취소, 원래 순번으로 복귀)\n"
        "- `cancel`: 진행 중 요청 → CANCELLED\n\n"
        "허용되지 않는 상태(다른 강사가 먼저 처리함 등) → 409 HELP_REQUEST_INVALID_STATE."
    ),
    responses=WRITE_ERRORS,
)
async def act_on_help_request(
    academy_id: uuid.UUID,
    help_request_id: uuid.UUID,
    action: StaffAction,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    publisher: HelpPublisher,
) -> StaffHelpRequest:
    return await _service(session, settings, publisher).transition(actor, help_request_id, action)


@queues.get(
    "",
    summary="반 질문 대기열 (담당 강사 / OWNER·MANAGER, 폴링용)",
    description="처리 중(active)과 대기(waiting, 순번 순), 대기 인원, 신규 요청 예상 대기시간, "
    "`last_changed_at`(변경 감지용). 권장 폴링 5초.",
    responses=READ_ERRORS,
)
async def help_queue(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    publisher: HelpPublisher,
) -> HelpQueue:
    return await _service(session, settings, publisher).queue(actor, class_id)


@queues.post(
    "/call-next",
    summary="다음 학생 호출 (강사)",
    description="가장 먼저 요청한 대기 학생을 CALLED로 바꾼다. 여러 강사가 동시에 눌러도 서로 "
    "다른 학생이 호출된다. 대기자가 없으면 409 HELP_QUEUE_EMPTY.",
    responses=WRITE_ERRORS,
)
async def call_next(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    publisher: HelpPublisher,
) -> StaffHelpRequest:
    return await _service(session, settings, publisher).call_next(actor, class_id)


@queues.get(
    "/estimate",
    summary="예상 대기시간 (반 학생·강사)",
    description="지금 질문을 요청하면 기다릴 예상 시간. 최근 완료 질문 평균 처리시간 기준이며, "
    "기록이 부족하면 기본값(`is_default=true`)을 쓴다.",
    responses=READ_ERRORS,
)
async def help_estimate(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    actor: AcademyMember,
    session: DbSession,
    settings: AppSettings,
    publisher: HelpPublisher,
) -> ClassEstimate:
    return await _service(session, settings, publisher).class_estimate(actor, class_id)
