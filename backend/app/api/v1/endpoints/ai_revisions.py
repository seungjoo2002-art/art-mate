"""AI 시각적 첨삭: AI 수정본 API (v1.3). 학생 본인만 (다른 사람 작품·수정본 → 404).

- 개선사항 후보 조회·수정본 조회·비교는 이미지 수정 API를 부르지 않는다.
- 생성 요청(`POST .../ai-revisions`)만 작업을 만든다 (같은 요청이면 기존 결과를 200으로 반환).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status

from app.api.deps import (
    AppSettings,
    DbSession,
    OptionalStorage,
    RevisionStorage,
    require_user_types,
)
from app.api.responses import AUTH_ERRORS, error_responses
from app.core.security import CurrentUser
from app.models.enums import UserType
from app.models.profile import Profile
from app.schemas.ai_revisions import (
    AiRevisionCreate,
    AiRevisionRead,
    ArtworkRevisionSummary,
    RevisionCandidates,
    RevisionUsage,
    StageRevisions,
)
from app.services.ai_revisions import AiRevisionService
from app.services.worker_dispatch import sweep_with_new_session

router = APIRouter(tags=["ai-revisions"])
admin = APIRouter(prefix="/admin", tags=["admin"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
SystemAdmin = Annotated[Profile, Depends(require_user_types(UserType.ADMIN))]
READ_ERRORS = AUTH_ERRORS | error_responses(404, 503)
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422, 429, 503)


def _svc(session, settings, storage, revision_storage) -> AiRevisionService:  # type: ignore[no-untyped-def]
    return AiRevisionService(session, settings, storage, revision_storage)


def _kick(request: Request, background: BackgroundTasks) -> None:
    """작업을 넣은 뒤 GitHub Actions Worker 실행 요청 (토큰이 없으면 아무것도 안 함)."""
    state = request.app.state
    dispatcher = getattr(state, "worker_dispatcher", None)
    if dispatcher is not None:
        background.add_task(dispatcher.notify, state.settings, "ai-revision")


def _sweep(request: Request, background: BackgroundTasks) -> None:
    """상태 확인 뒤: 오래 대기한 작업이 있으면 Worker 재요청 (프로세스당 일정 간격에 한 번)."""
    if getattr(request.app.state, "worker_dispatcher", None) is not None:
        background.add_task(sweep_with_new_session, request.app.state)


@router.get(
    "/artworks/{artwork_id}/ai-revisions/summary",
    summary="단계별 AI 수정본 수 (아카이브 상세 'AI 수정본 보기 (N개)')",
    responses=READ_ERRORS,
)
async def revision_summary(
    artwork_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    revision_storage: RevisionStorage,
) -> ArtworkRevisionSummary:
    return await _svc(session, settings, storage, revision_storage).summary(
        owner, artwork_id, user.access_token
    )


@router.get(
    "/artworks/{artwork_id}/stages/{stage_id}/ai-revisions",
    summary="단계의 AI 수정본 (최신 먼저, 교체 전 원본의 수정본 포함)",
    responses=READ_ERRORS,
)
async def stage_revisions(
    artwork_id: uuid.UUID,
    stage_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    revision_storage: RevisionStorage,
    request: Request,
    background: BackgroundTasks,
) -> StageRevisions:
    result = await _svc(session, settings, storage, revision_storage).stage_revisions(
        owner, artwork_id, stage_id, user.access_token
    )
    if any(r.status in ("QUEUED", "RUNNING") for r in result.revisions):
        _sweep(request, background)
    return result


@router.get(
    "/artworks/{artwork_id}/photos/{photo_id}/ai-revision-candidates",
    summary="이 사진의 AI 수정 개선사항 후보 (기존 AI 첨삭 정리의 부족한 점·수정 방법)",
    description="이 사진을 기준으로 한 같은 단계 피드백만. 교체 전 사진·단계 공통·작품 전체 "
    "피드백은 포함하지 않는다. 한도·동의·최근 수정본도 함께 돌려준다.",
    responses=READ_ERRORS,
)
async def revision_candidates(
    artwork_id: uuid.UUID,
    photo_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    revision_storage: RevisionStorage,
) -> RevisionCandidates:
    return await _svc(session, settings, storage, revision_storage).candidates(
        owner, artwork_id, photo_id, user.access_token
    )


@router.post(
    "/artworks/{artwork_id}/photos/{photo_id}/ai-revisions",
    summary="피드백 반영 AI 수정본 만들기",
    description="202: 새로 요청함 / 200: 같은 원본·개선사항·설정의 기존 수정본(진행 중 포함)을 "
    "그대로 돌려줌 (이미지 수정 API를 다시 부르지 않음, 한도 차감 없음). "
    "409 AI_CONSENT_REQUIRED(작품 이미지 외부 전송 동의 필요) · AI_REVISION_CANDIDATES_CHANGED, "
    "422 AI_REVISION_NO_IMPROVEMENTS, 429 AI_REVISION_LIMIT_REACHED(details.scope), "
    "503 AI_REVISION_DISABLED.",
    status_code=status.HTTP_202_ACCEPTED,
    responses=WRITE_ERRORS,
)
async def create_revision(
    artwork_id: uuid.UUID,
    photo_id: uuid.UUID,
    data: AiRevisionCreate,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    revision_storage: RevisionStorage,
    request: Request,
    response: Response,
    background: BackgroundTasks,
) -> AiRevisionRead:
    read, created = await _svc(session, settings, storage, revision_storage).create(
        owner, artwork_id, photo_id, data.selected_keys, user.access_token
    )
    if created:
        _kick(request, background)
    else:
        response.status_code = status.HTTP_200_OK
    return read


@router.get(
    "/ai-revisions/{revision_id}",
    summary="AI 수정본 상태·결과 (저장 대기 결과는 이때 Storage로 옮긴다)",
    responses=READ_ERRORS,
)
async def get_revision(
    revision_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    revision_storage: RevisionStorage,
    request: Request,
    background: BackgroundTasks,
) -> AiRevisionRead:
    read = await _svc(session, settings, storage, revision_storage).get(
        owner, revision_id, user.access_token
    )
    if read.status in ("QUEUED", "RUNNING"):
        _sweep(request, background)
    return read


@router.post(
    "/ai-revisions/{revision_id}/retry",
    summary="실패한 AI 수정본 다시 만들기 (새 버전, 한도 차감)",
    status_code=status.HTTP_202_ACCEPTED,
    responses=WRITE_ERRORS,
)
async def retry_revision(
    revision_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    revision_storage: RevisionStorage,
    request: Request,
    response: Response,
    background: BackgroundTasks,
) -> AiRevisionRead:
    read, created = await _svc(session, settings, storage, revision_storage).retry(
        owner, revision_id, user.access_token
    )
    if created:
        _kick(request, background)
    else:
        response.status_code = status.HTTP_200_OK
    return read


@router.delete(
    "/ai-revisions/{revision_id}",
    summary="AI 수정본 삭제 (학생 원본 사진은 그대로)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=AUTH_ERRORS | error_responses(404),
)
async def delete_revision(
    revision_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    revision_storage: RevisionStorage,
) -> None:
    await _svc(session, settings, storage, revision_storage).delete(
        owner, revision_id, user.access_token
    )


@admin.get(
    "/ai-revisions/usage",
    summary="AI 수정본 사용량·예상 비용 (ADMIN)",
    responses=AUTH_ERRORS,
)
async def revision_usage(
    _: SystemAdmin,
    session: DbSession,
    settings: AppSettings,
    days: Annotated[int, Query(ge=1, le=366)] = 30,
) -> RevisionUsage:
    return await AiRevisionService(session, settings, None, None).usage(days)
