"""AI 첨삭 기록 API (v0.6).

전사(STT)·AI 요약 요청, 강사/본인 검토·승인, 학생 아카이브, AI 전송 동의.

처리는 비동기다. 요청 API는 작업을 큐에 넣고 202(새 작업) 또는 200(이미 진행 중인 작업)을 돌려주며,
프론트는 상태 API를 폴링한다. 실제 처리는 Worker 프로세스(`python -m app.worker`)가 한다.

경로
- 학생 본인:  /artworks/{artwork_id}/recordings/{recording_id}/(transcription|transcript|summary)
- 담당 강사:  /academies/{academy_id}/artworks/{artwork_id}/recordings/{recording_id}/(같음)
- 첨삭 검토:  /academies/{academy_id}/feedbacks[...] (강사), /feedbacks/{feedback_id}[...] (학생)
- 아카이브:   /artworks/{artwork_id}/feedbacks (학생, 승인된 첨삭)
- 동의:       /ai-processing-consents
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Path, Query, Request, Response, status

from app.api.deps import (
    AcademyStaff,
    ActiveProfile,
    AppSettings,
    AudioStorage,
    DbSession,
    require_user_types,
)
from app.api.responses import AUTH_ERRORS, error_responses
from app.core import timezone as clock
from app.core.security import CurrentUser
from app.models.enums import AiConsentPurpose, AiJobStatus, FeedbackStatus, UserType
from app.models.profile import Profile
from app.schemas.ai_feedback import (
    AiConsentCreate,
    AiConsentStatus,
    BrowserTranscriptCreate,
    BrowserTranscriptResult,
    FeedbackDecision,
    FeedbackNoteCreate,
    FeedbackNoteRead,
    FeedbackNoteUpdate,
    FeedbackRead,
    FeedbackReject,
    FeedbackUpdate,
    GuardianConsentConfirm,
    GuardianConsentView,
    JobRead,
    NoteSummaryRequest,
    ReviewerFeedbackRead,
    ReviewHistoryRead,
    ReviewQueueItem,
    SummaryStatusRead,
    TranscriptEdit,
    TranscriptionRequest,
    TranscriptionStatusRead,
    TranscriptRead,
)
from app.schemas.common import Page, PaginationQuery
from app.services.ai_feedback import AiFeedbackService
from app.services.feedback_notes import FeedbackNoteService

consents = APIRouter(prefix="/ai-processing-consents", tags=["ai-feedback"])
# v0.9.6 보호자 확인 (로그인 없이 링크 토큰으로)
guardian_consents = APIRouter(prefix="/guardian-consents", tags=["ai-feedback"])
owner_processing = APIRouter(
    prefix="/artworks/{artwork_id}/recordings/{recording_id}", tags=["ai-feedback"]
)
staff_processing = APIRouter(
    prefix="/academies/{academy_id}/artworks/{artwork_id}/recordings/{recording_id}",
    tags=["ai-feedback"],
)
owner_feedback = APIRouter(prefix="/feedbacks", tags=["ai-feedback"])
archive = APIRouter(prefix="/artworks/{artwork_id}/feedbacks", tags=["ai-feedback"])
staff_feedback = APIRouter(prefix="/academies/{academy_id}/feedbacks", tags=["ai-feedback"])
# v0.9 텍스트 첨삭
artwork_notes = APIRouter(prefix="/artworks/{artwork_id}/feedback-notes", tags=["ai-feedback"])
notes = APIRouter(prefix="/feedback-notes", tags=["ai-feedback"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
READ = AUTH_ERRORS | error_responses(404, 409)
WRITE = AUTH_ERRORS | error_responses(404, 409, 422)
QUEUE = (
    AUTH_ERRORS
    | error_responses(404, 409, 422, 503)
    | {200: {"model": JobRead, "description": "이미 진행 중인 작업 (새로 만들지 않음)"}}
)


def _svc(session, settings, storage=None) -> AiFeedbackService:  # type: ignore[no-untyped-def]
    return AiFeedbackService(session, settings, storage)


class WorkerKick:
    """작업을 큐에 넣은 뒤(응답 후) GitHub Actions Worker 실행을 요청한다 (v0.9.3).

    토큰이 없으면 아무것도 하지 않는다. 미뤄 둔 백업 작업(next_attempt_at이 미래)은 요청하지 않는다.
    """

    def __init__(self, request: Request, background: BackgroundTasks) -> None:
        self._request = request
        self._background = background

    def __call__(self, job: JobRead | None, reason: str) -> None:
        if job is None or job.status != AiJobStatus.QUEUED:
            return
        if job.next_attempt_at is not None and job.next_attempt_at > clock.utc_now():
            return
        state = self._request.app.state
        dispatcher = getattr(state, "worker_dispatcher", None)
        if dispatcher is not None:
            self._background.add_task(dispatcher.notify, state.settings, reason)


Kick = Annotated[WorkerKick, Depends(WorkerKick)]


def _queued(
    job_and_created: tuple[JobRead, bool],
    response: Response,
    kick: WorkerKick | None = None,
    reason: str = "job",
) -> JobRead:
    job, created = job_and_created
    response.status_code = status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK
    if kick is not None:
        kick(job, reason)
    return job


# ============================================================================ consent


Purpose = Annotated[
    AiConsentPurpose,
    Query(description="FEEDBACK_SUMMARY(기본, 첨삭 요약) / GROWTH_COACHING(성장 분석·맞춤 과제)"),
]


@consents.get("/me", summary="내 AI 전송 동의 상태 (학생, 목적별)", responses=AUTH_ERRORS)
async def my_ai_consent(
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    purpose: Purpose = AiConsentPurpose.FEEDBACK_SUMMARY,
) -> AiConsentStatus:
    return await _svc(session, settings).ai_consent_status(owner, purpose)


@consents.post(
    "",
    summary="AI 전송 동의 (학생)",
    description=(
        "첨삭 전사문을 외부 AI(AI_PROVIDER, 기본 OpenAI)로 보내 요약하는 것에 대한 동의. "
        "녹음 동의와 별개다. `policy_version`은 GET /me 의 `required_version`. "
        "(v0.9.6) `birth_year_month`(YYYY-MM) 필수 — 연령 구간만 저장한다. 만 18세 미만이면 "
        "응답의 `guardian_token`으로 보호자 확인 링크를 만들어 보호자에게 보낸다. "
        "보호자가 확인해야 "
        "`is_valid`가 true가 된다 (`reason: GUARDIAN_PENDING`). 만 13세 미만은 운영자의 데이터 "
        "무보관 승인 전까지 `UNDER_13_BLOCKED`."
    ),
    status_code=status.HTTP_201_CREATED,
    responses=WRITE,
)
async def grant_ai_consent(
    data: AiConsentCreate, owner: Student, session: DbSession, settings: AppSettings
) -> AiConsentStatus:
    return await _svc(session, settings).grant_ai_consent(owner, data)


@consents.post(
    "/me/guardian-link",
    summary="보호자 확인 링크 재발급 (학생, v0.9.6)",
    description="보호자 확인 대기 중인 동의만. 이전 링크는 무효가 된다 (없으면 409).",
    responses=WRITE,
)
async def renew_guardian_link(
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    purpose: Purpose = AiConsentPurpose.FEEDBACK_SUMMARY,
) -> AiConsentStatus:
    return await _svc(session, settings).new_guardian_link(owner, purpose)


@guardian_consents.get(
    "/{token}",
    summary="보호자 확인 화면 정보 (로그인 불필요, v0.9.6)",
    description="링크 토큰으로 동의 내용(제공자·목적·버전·연령 구간)만 보여 준다. 학생 이름·작품·"
    "전사 내용은 포함하지 않는다. 없거나 만료·사용된 링크는 404 `GUARDIAN_LINK_INVALID`.",
    responses=error_responses(404),
)
async def guardian_consent_view(
    token: Annotated[str, Path(min_length=20, max_length=100)],
    session: DbSession,
    settings: AppSettings,
) -> GuardianConsentView:
    return await _svc(session, settings).guardian_consent_view(token)


@guardian_consents.post(
    "/{token}",
    summary="보호자 동의 확인 (로그인 불필요, v0.9.6)",
    description="보호자 성명·관계를 받고 동의를 유효하게 한다. 링크는 한 번만 쓸 수 있다.",
    responses=error_responses(404, 422),
)
async def guardian_confirm(
    token: Annotated[str, Path(min_length=20, max_length=100)],
    data: GuardianConsentConfirm,
    session: DbSession,
    settings: AppSettings,
) -> GuardianConsentView:
    return await _svc(session, settings).guardian_confirm(token, data)


@consents.delete(
    "/me",
    summary="AI 전송 동의 철회 (학생)",
    description="새 요약 요청이 막히고 대기·처리 중인 요약 작업은 취소된다. "
    "이미 만든 첨삭은 남는다.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=READ,
)
async def revoke_ai_consent(
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    purpose: Purpose = AiConsentPurpose.FEEDBACK_SUMMARY,
) -> None:
    await _svc(session, settings).revoke_ai_consent(owner, purpose)


# ============================================================================ owner processing


@owner_processing.post(
    "/transcription",
    summary="전사(STT) 요청 (학생)",
    description=(
        "녹음을 한국어 텍스트로 변환하는 작업을 큐에 넣는다 (서버 내부 처리, 외부 전송 없음). "
        "새 작업 202, 이미 진행 중이면 200으로 그 작업. 학생의 녹음 동의가 철회됐으면 409 "
        "`RECORDING_CONSENT_REQUIRED`, 이미 전사됐으면 409 `TRANSCRIPTION_ALREADY_DONE`."
    ),
    status_code=status.HTTP_202_ACCEPTED,
    responses=QUEUE,
)
async def owner_request_transcription(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    response: Response,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
    kick: Kick,
    data: TranscriptionRequest | None = None,
) -> JobRead:
    svc = _svc(session, settings, storage)
    _, recording = await svc.owner_target(owner, artwork_id, recording_id)
    data = data or TranscriptionRequest()
    return _queued(
        await svc.request_transcription(
            recording,
            owner,
            user.access_token,
            auto_summarize=data.auto_summarize,
            defer_seconds=data.defer_seconds,
        ),
        response,
        kick,
        "transcription",
    )


@owner_processing.post(
    "/transcription/retry",
    summary="전사 재시도 (학생)",
    description="마지막 전사 작업이 FAILED/CANCELLED일 때만 (아니면 409 `JOB_NOT_RETRYABLE`).",
    status_code=status.HTTP_202_ACCEPTED,
    responses=QUEUE,
)
async def owner_retry_transcription(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    response: Response,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
    kick: Kick,
    data: TranscriptionRequest | None = None,
) -> JobRead:
    svc = _svc(session, settings, storage)
    _, recording = await svc.owner_target(owner, artwork_id, recording_id)
    data = data or TranscriptionRequest()
    return _queued(
        await svc.request_transcription(
            recording, owner, user.access_token, auto_summarize=data.auto_summarize, retry=True
        ),
        response,
        kick,
        "transcription_retry",
    )


@owner_processing.get("/transcription", summary="전사 상태 (학생)", responses=READ)
async def owner_transcription_status(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> TranscriptionStatusRead:
    svc = _svc(session, settings)
    _, recording = await svc.owner_target(owner, artwork_id, recording_id)
    return await svc.transcription_status(recording)


@owner_processing.get(
    "/transcript",
    summary="전사 원문 (학생 본인)",
    description="구간별 타임스탬프 포함. 아직 없으면 409 `TRANSCRIPT_NOT_READY`.",
    responses=READ,
)
async def owner_transcript(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> TranscriptRead:
    svc = _svc(session, settings)
    _, recording = await svc.owner_target(owner, artwork_id, recording_id)
    return await svc.transcript(recording)


@owner_processing.post(
    "/transcript/browser",
    summary="브라우저 전사 결과 저장 (학생 본인, v0.9.2)",
    description=(
        "학생 기기에서 Whisper(Transformers.js)로 만든 전사를 저장한다. 음성은 기기 밖으로 "
        "보내지 않는다. 대기·진행 중인 서버(GitHub Actions) 전사 작업은 취소되고, 이미 전사가 "
        "있으면 409 `TRANSCRIPTION_ALREADY_DONE`. 녹음 동의가 없으면 409 "
        "`RECORDING_CONSENT_REQUIRED`, 타임스탬프가 녹음 길이를 넘으면 422. "
        "auto_summarize=true면 AI 요약 작업도 만든다 (AI 전송 동의가 있을 때만). "
        "브라우저 전사가 실패하면 기존 POST /transcription (서버 처리)으로 대신한다."
    ),
    status_code=status.HTTP_201_CREATED,
    responses=WRITE,
)
async def owner_save_browser_transcript(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    data: BrowserTranscriptCreate,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    kick: Kick,
) -> BrowserTranscriptResult:
    svc = _svc(session, settings)
    _, recording = await svc.owner_target(owner, artwork_id, recording_id)
    result = await svc.save_browser_transcript(owner, recording, data)
    kick(result.summary_job, "summary")
    return result


@owner_processing.put(
    "/transcript",
    summary="전사(STT) 결과 수정 (학생 본인, v0.9)",
    description=(
        "잘못 인식된 문장을 고친다. 구간 번호·시각은 그대로 두고 바꾼 구간의 문장만 보낸다. "
        "원본 전사는 보존되고 새 버전이 현재 전사가 된다. 초안·검토 중 요약은 대체되므로 "
        "요약을 다시 요청한다. 확정된 첨삭이 있으면 409 `TRANSCRIPT_LOCKED`, base_transcript_id가 "
        "최신이 아니면 409 `FEEDBACK_VERSION_CONFLICT`."
    ),
    responses=WRITE,
)
async def owner_edit_transcript(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    data: TranscriptEdit,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> TranscriptRead:
    svc = _svc(session, settings)
    _, recording = await svc.owner_target(owner, artwork_id, recording_id)
    return await svc.edit_transcript(owner, recording, data)


@owner_processing.post(
    "/summary",
    summary="AI 첨삭 요약 요청 (학생)",
    description=(
        "전사문을 Gemini로 요약·분류하는 작업. 학생의 AI 전송 동의(현재 버전)가 없으면 409 "
        "`AI_CONSENT_REQUIRED`, 전사가 없으면 409 `TRANSCRIPT_NOT_READY`, 이미 초안이 있으면 409 "
        "`FEEDBACK_INVALID_STATE`(재생성 API 사용), 승인됐으면 409 `FEEDBACK_ALREADY_APPROVED`."
    ),
    status_code=status.HTTP_202_ACCEPTED,
    responses=QUEUE,
)
async def owner_request_summary(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    response: Response,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    kick: Kick,
) -> JobRead:
    svc = _svc(session, settings)
    _, recording = await svc.owner_target(owner, artwork_id, recording_id)
    return _queued(
        await svc.request_summary(recording, owner, regenerate=False), response, kick, "summary"
    )


@owner_processing.post(
    "/summary/regenerate",
    summary="AI 첨삭 재생성 (학생)",
    description="승인 전 초안(DRAFT/IN_REVIEW/REJECTED)을 새 AI 초안으로 대체한다 "
    "(기존은 SUPERSEDED).",
    status_code=status.HTTP_202_ACCEPTED,
    responses=QUEUE,
)
async def owner_regenerate_summary(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    response: Response,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    kick: Kick,
) -> JobRead:
    svc = _svc(session, settings)
    _, recording = await svc.owner_target(owner, artwork_id, recording_id)
    return _queued(
        await svc.request_summary(recording, owner, regenerate=True), response, kick, "summary"
    )


@owner_processing.get("/summary", summary="AI 요약 상태 (학생)", responses=READ)
async def owner_summary_status(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> SummaryStatusRead:
    svc = _svc(session, settings)
    artwork, recording = await svc.owner_target(owner, artwork_id, recording_id)
    return await svc.summary_status(artwork, recording)


# ============================================================================ staff processing


@staff_processing.post(
    "/transcription",
    summary="전사(STT) 요청 (담당 강사)",
    status_code=status.HTTP_202_ACCEPTED,
    responses=QUEUE,
)
async def staff_request_transcription(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    response: Response,
    actor: AcademyStaff,
    profile: ActiveProfile,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
    data: TranscriptionRequest | None = None,
) -> JobRead:
    svc = _svc(session, settings, storage)
    _, recording = await svc.staff_target(actor, artwork_id, recording_id)
    data = data or TranscriptionRequest()
    return _queued(
        await svc.request_transcription(
            recording, profile, user.access_token, auto_summarize=data.auto_summarize
        ),
        response,
    )


@staff_processing.post(
    "/transcription/retry",
    summary="전사 재시도 (담당 강사)",
    status_code=status.HTTP_202_ACCEPTED,
    responses=QUEUE,
)
async def staff_retry_transcription(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    response: Response,
    actor: AcademyStaff,
    profile: ActiveProfile,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
    data: TranscriptionRequest | None = None,
) -> JobRead:
    svc = _svc(session, settings, storage)
    _, recording = await svc.staff_target(actor, artwork_id, recording_id)
    data = data or TranscriptionRequest()
    return _queued(
        await svc.request_transcription(
            recording,
            profile,
            user.access_token,
            auto_summarize=data.auto_summarize,
            retry=True,
        ),
        response,
    )


@staff_processing.get("/transcription", summary="전사 상태 (담당 강사)", responses=READ)
async def staff_transcription_status(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
) -> TranscriptionStatusRead:
    svc = _svc(session, settings)
    _, recording = await svc.staff_target(actor, artwork_id, recording_id)
    return await svc.transcription_status(recording)


@staff_processing.get("/transcript", summary="전사 원문 (담당 강사)", responses=READ)
async def staff_transcript(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
) -> TranscriptRead:
    svc = _svc(session, settings)
    _, recording = await svc.staff_target(actor, artwork_id, recording_id)
    return await svc.transcript(recording)


@staff_processing.post(
    "/summary",
    summary="AI 첨삭 요약 요청 (담당 강사)",
    description="학생의 AI 전송 동의가 기준이다 (강사가 대신 동의할 수 없음).",
    status_code=status.HTTP_202_ACCEPTED,
    responses=QUEUE,
)
async def staff_request_summary(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    response: Response,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> JobRead:
    svc = _svc(session, settings)
    _, recording = await svc.staff_target(actor, artwork_id, recording_id)
    return _queued(await svc.request_summary(recording, profile, regenerate=False), response)


@staff_processing.post(
    "/summary/regenerate",
    summary="AI 첨삭 재생성 (담당 강사)",
    status_code=status.HTTP_202_ACCEPTED,
    responses=QUEUE,
)
async def staff_regenerate_summary(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    response: Response,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> JobRead:
    svc = _svc(session, settings)
    _, recording = await svc.staff_target(actor, artwork_id, recording_id)
    return _queued(await svc.request_summary(recording, profile, regenerate=True), response)


@staff_processing.get("/summary", summary="AI 요약 상태 (담당 강사)", responses=READ)
async def staff_summary_status(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
) -> SummaryStatusRead:
    svc = _svc(session, settings)
    artwork, recording = await svc.staff_target(actor, artwork_id, recording_id)
    return await svc.summary_status(artwork, recording)


# ============================================================================ staff review

StatusFilter = Annotated[
    list[FeedbackStatus] | None,
    Query(description="기본 DRAFT, IN_REVIEW (검토 대기). 여러 번 지정 가능"),
]


@staff_feedback.get(
    "",
    summary="검토 대기 첨삭 목록 (담당 강사)",
    description="담당 학생의 학원 연결 작품 첨삭. 오래된 순. `status=APPROVED`로 확정 목록도 조회.",
    responses=AUTH_ERRORS | error_responses(404, 422),
)
async def review_queue(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
    status_filter: Annotated[StatusFilter, Query(alias="status")] = None,
    student_membership_id: uuid.UUID | None = None,
) -> Page[ReviewQueueItem]:
    statuses = status_filter or [FeedbackStatus.DRAFT, FeedbackStatus.IN_REVIEW]
    items, total = await _svc(session, settings).review_queue(
        actor, pagination, statuses=statuses, student_membership_id=student_membership_id
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@staff_feedback.get(
    "/{feedback_id}",
    summary="첨삭 상세 (담당 강사, AI 원본 포함)",
    responses=READ,
)
async def staff_feedback_detail(
    academy_id: uuid.UUID,
    feedback_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerFeedbackRead:
    return await _svc(session, settings).staff_view(actor, feedback_id)


@staff_feedback.patch(
    "/{feedback_id}",
    summary="첨삭 수정 (담당 강사)",
    description="요약·항목·카테고리 전체 교체. DRAFT → IN_REVIEW. `version` 불일치 409.",
    responses=WRITE,
)
async def staff_update_feedback(
    academy_id: uuid.UUID,
    feedback_id: uuid.UUID,
    data: FeedbackUpdate,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerFeedbackRead:
    return await _svc(session, settings).update(profile, feedback_id, data, actor)


@staff_feedback.post(
    "/{feedback_id}/approve",
    summary="첨삭 승인 (담당 강사)",
    description="DRAFT/IN_REVIEW → APPROVED. 승인자·시각 저장, 학생 아카이브에 표시.",
    responses=WRITE,
)
async def staff_approve_feedback(
    academy_id: uuid.UUID,
    feedback_id: uuid.UUID,
    data: FeedbackDecision,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerFeedbackRead:
    return await _svc(session, settings).approve(profile, feedback_id, data, actor)


@staff_feedback.post(
    "/{feedback_id}/reject",
    summary="AI 초안 반려 (담당 강사)",
    responses=WRITE,
)
async def staff_reject_feedback(
    academy_id: uuid.UUID,
    feedback_id: uuid.UUID,
    data: FeedbackReject,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerFeedbackRead:
    return await _svc(session, settings).reject(profile, feedback_id, data, actor)


@staff_feedback.post(
    "/{feedback_id}/reopen",
    summary="승인 취소·다시 검토 (담당 강사)",
    responses=WRITE,
)
async def staff_reopen_feedback(
    academy_id: uuid.UUID,
    feedback_id: uuid.UUID,
    data: FeedbackDecision,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerFeedbackRead:
    return await _svc(session, settings).reopen(profile, feedback_id, data, actor)


@staff_feedback.get("/{feedback_id}/history", summary="수정·승인 이력 (담당 강사)", responses=READ)
async def staff_feedback_history(
    academy_id: uuid.UUID,
    feedback_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
) -> list[ReviewHistoryRead]:
    return await _svc(session, settings).staff_history(actor, feedback_id)


# ============================================================================ student feedback


@archive.get(
    "",
    summary="작품별 확정 첨삭 목록 (학생 아카이브)",
    description="APPROVED 첨삭만 (강사 승인 또는 개인 작품의 본인 확정). 최근 승인순.",
    responses=READ,
)
async def artwork_feedbacks(
    artwork_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> list[FeedbackRead]:
    return await _svc(session, settings).archive(owner, artwork_id)


@owner_feedback.get(
    "/{feedback_id}",
    summary="첨삭 상세 (학생)",
    description=(
        "개인 작품(학원 미연결): 본인이 검토자이므로 초안 포함 전체(ReviewerFeedbackRead). "
        "학원 연결 작품: APPROVED만, 승인 전이면 403 `FEEDBACK_NOT_APPROVED`."
    ),
    response_model=ReviewerFeedbackRead | FeedbackRead,
    responses=AUTH_ERRORS | error_responses(404),
)
async def owner_feedback_detail(
    feedback_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> ReviewerFeedbackRead | FeedbackRead:
    return await _svc(session, settings).owner_view(owner, feedback_id)


@owner_feedback.patch(
    "/{feedback_id}",
    summary="첨삭 수정 (개인 작품, 학생 본인)",
    description="학원 연결 작품은 담당 강사가 검토하므로 403.",
    responses=WRITE,
)
async def owner_update_feedback(
    feedback_id: uuid.UUID,
    data: FeedbackUpdate,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerFeedbackRead:
    return await _svc(session, settings).update(owner, feedback_id, data)


@owner_feedback.post(
    "/{feedback_id}/approve", summary="첨삭 확정 (개인 작품, 학생 본인)", responses=WRITE
)
async def owner_approve_feedback(
    feedback_id: uuid.UUID,
    data: FeedbackDecision,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerFeedbackRead:
    return await _svc(session, settings).approve(owner, feedback_id, data)


@owner_feedback.post(
    "/{feedback_id}/reject", summary="AI 초안 반려 (개인 작품, 학생 본인)", responses=WRITE
)
async def owner_reject_feedback(
    feedback_id: uuid.UUID,
    data: FeedbackReject,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerFeedbackRead:
    return await _svc(session, settings).reject(owner, feedback_id, data)


@owner_feedback.post(
    "/{feedback_id}/reopen", summary="확정 취소 (개인 작품, 학생 본인)", responses=WRITE
)
async def owner_reopen_feedback(
    feedback_id: uuid.UUID,
    data: FeedbackDecision,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerFeedbackRead:
    return await _svc(session, settings).reopen(owner, feedback_id, data)


@owner_feedback.get(
    "/{feedback_id}/history", summary="수정·확정 이력 (개인 작품, 학생 본인)", responses=READ
)
async def owner_feedback_history(
    feedback_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> list[ReviewHistoryRead]:
    return await _svc(session, settings).owner_history(owner, feedback_id)


# ======================================================================= v0.9 텍스트 첨삭 (F-3)


def _notes(session, settings) -> FeedbackNoteService:  # type: ignore[no-untyped-def]
    return FeedbackNoteService(session, settings)


@artwork_notes.post(
    "",
    summary="텍스트 첨삭 입력 (학생, 녹음 없이)",
    description=(
        "출처: INSTRUCTOR(강사 첨삭을 받아 적음) / SELF_NOTE(자기 메모) / PEER(다른 학생 의견). "
        "작품 하나에 여러 개 (최대 50). 원문은 문장 단위로 나눠 저장한다. "
        "request_summary=true면 AI 요약을 바로 요청한다 (동의·설정이 없으면 저장만). "
        "학원 가입과 무관하게 쓸 수 있다."
    ),
    status_code=status.HTTP_201_CREATED,
    responses=WRITE,
)
async def create_note(
    artwork_id: uuid.UUID,
    data: FeedbackNoteCreate,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> FeedbackNoteRead:
    return await _notes(session, settings).create(owner, artwork_id, data)


@artwork_notes.get("", summary="작품의 텍스트 첨삭 목록 (학생 본인)", responses=READ)
async def list_notes(
    artwork_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> list[FeedbackNoteRead]:
    return await _notes(session, settings).list_for_artwork(owner, artwork_id)


@notes.get("/{note_id}", summary="텍스트 첨삭 원문·요약 상태", responses=READ)
async def get_note(
    note_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> FeedbackNoteRead:
    return await _notes(session, settings).get(owner, note_id)


@notes.patch(
    "/{note_id}",
    summary="텍스트 첨삭 수정",
    description=(
        "version 필수 (다르면 409 `FEEDBACK_VERSION_CONFLICT`). 원문·출처를 바꾸면 초안·검토 중 "
        "요약은 대체되고 진행 중 요약 작업은 취소된다. 확정된 요약이 있으면 409 "
        "`FEEDBACK_NOTE_LOCKED` (먼저 POST /feedbacks/{id}/reopen)."
    ),
    responses=WRITE,
)
async def update_note(
    note_id: uuid.UUID,
    data: FeedbackNoteUpdate,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> FeedbackNoteRead:
    return await _notes(session, settings).update(owner, note_id, data)


@notes.delete(
    "/{note_id}",
    summary="텍스트 첨삭 삭제 (요약·이력 함께 삭제, 성장 분석에서 제외)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=READ,
)
async def delete_note(
    note_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> None:
    await _notes(session, settings).delete(owner, note_id)


@notes.post(
    "/{note_id}/summary",
    summary="텍스트 첨삭 AI 요약·분류 요청",
    description=(
        "녹음 첨삭과 같은 요약 작업(SUMMARIZE)을 큐에 넣는다. 새 작업 202, 진행 중이면 200. "
        "AI 전송 동의가 없으면 409 `AI_CONSENT_REQUIRED`, 초안이 있으면 regenerate=true. "
        "결과 확인: GET /feedback-notes/{id} 의 feedback_id → GET /feedbacks/{feedback_id}."
    ),
    status_code=status.HTTP_202_ACCEPTED,
    responses=QUEUE,
)
async def request_note_summary(
    note_id: uuid.UUID,
    response: Response,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    kick: Kick,
    data: NoteSummaryRequest | None = None,
) -> JobRead:
    data = data or NoteSummaryRequest()
    return _queued(
        await _notes(session, settings).request_summary(owner, note_id, regenerate=data.regenerate),
        response,
        kick,
        "note_summary",
    )
