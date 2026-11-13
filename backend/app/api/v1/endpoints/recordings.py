"""피드백 음성 녹음 API (F-11)와 녹음 동의.

- `/recording-consents`: 학생 본인의 녹음 동의 (현재 버전에 동의해야 업로드 가능)
- `/artworks/{artwork_id}/recordings`: 학생 본인 작품의 녹음 업로드·조회·재생·삭제
- `/academies/{academy_id}/artworks/{artwork_id}/recordings`: 담당 학생의 학원 연결 작품 녹음
  조회·재생

녹음 업로드는 사진과 같은 2단계다: 업로드 요청 → Storage에 직접 PUT → 완료 처리.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AcademyStaff, AppSettings, AudioStorage, DbSession, require_user_types
from app.api.responses import AUTH_ERRORS, error_responses
from app.core.security import CurrentUser
from app.models.enums import UserType
from app.models.profile import Profile
from app.schemas.recordings import (
    ConsentStatus,
    RecordingConsentCreate,
    RecordingRead,
    RecordingStageUpdate,
    RecordingUploadRequest,
    RecordingUploadTicket,
    RecordingUrl,
)
from app.services.recordings import RecordingService

consents = APIRouter(prefix="/recording-consents", tags=["recordings"])
router = APIRouter(prefix="/artworks/{artwork_id}/recordings", tags=["recordings"])
staff_router = APIRouter(
    prefix="/academies/{academy_id}/artworks/{artwork_id}/recordings", tags=["recordings"]
)

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
READ_ERRORS = AUTH_ERRORS | error_responses(404)
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422)
IncludeUrls = Annotated[bool, Query(description="true면 녹음마다 재생용 Signed URL 포함")]


def _service(session, settings, storage) -> RecordingService:  # type: ignore[no-untyped-def]
    return RecordingService(session, settings, storage)


# ----------------------------------------------------------------------------- consent


@consents.get("/me", summary="내 녹음 동의 상태 (학생)", responses=READ_ERRORS)
async def my_consent(
    owner: Student, session: DbSession, settings: AppSettings, storage: AudioStorage
) -> ConsentStatus:
    return await _service(session, settings, storage).consent_status(owner)


@consents.post(
    "",
    summary="녹음 동의 (학생)",
    description="`policy_version`은 GET /recording-consents/me 의 `required_version`. 만 14세 "
    "미만은 법정대리인 동의 후 `granted_by: GUARDIAN`. 동의 이력은 삭제되지 않는다.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def grant_consent(
    data: RecordingConsentCreate,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
) -> ConsentStatus:
    return await _service(session, settings, storage).grant_consent(owner, data)


@consents.delete(
    "/me",
    summary="녹음 동의 철회 (학생)",
    description=(
        "이후 새 녹음 업로드가 막힌다. 저장된 녹음은 그대로이며 학생이 직접 삭제할 수 있다."
    ),
    status_code=status.HTTP_204_NO_CONTENT,
    responses=READ_ERRORS,
)
async def revoke_consent(
    owner: Student, session: DbSession, settings: AppSettings, storage: AudioStorage
) -> None:
    await _service(session, settings, storage).revoke_consent(owner)


# ----------------------------------------------------------------------------- owner


@router.post(
    "",
    summary="녹음 업로드 요청 (Signed upload URL 발급)",
    description="현재 버전의 녹음 동의가 없으면 409 RECORDING_CONSENT_REQUIRED. "
    "`content_type`은 MediaRecorder의 mimeType 그대로 보내도 된다 (예: audio/webm;codecs=opus).",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS | error_responses(503),
)
async def request_recording_upload(
    artwork_id: uuid.UUID,
    data: RecordingUploadRequest,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
) -> RecordingUploadTicket:
    return await _service(session, settings, storage).request_upload(
        owner, artwork_id, data, user.access_token
    )


@router.post(
    "/{recording_id}/complete",
    summary="녹음 업로드 완료 처리",
    description="파일 시그니처로 실제 오디오 형식을 검증하고 중복 파일을 막는다. 재호출해도 안전.",
    responses=WRITE_ERRORS | error_responses(503),
)
async def complete_recording_upload(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
) -> RecordingRead:
    return await _service(session, settings, storage).complete_upload(
        owner, artwork_id, recording_id, user.access_token
    )


@router.get("", summary="작품 녹음 목록 (최신순)", responses=READ_ERRORS | error_responses(503))
async def list_recordings(
    artwork_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
    include_urls: IncludeUrls = False,
) -> list[RecordingRead]:
    return await _service(session, settings, storage).list_mine(
        owner, artwork_id, user.access_token, include_urls
    )


@router.get("/{recording_id}", summary="녹음 상세", responses=READ_ERRORS)
async def get_recording(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
) -> RecordingRead:
    return await _service(session, settings, storage).get_mine(owner, artwork_id, recording_id)


@router.patch(
    "/{recording_id}",
    summary="녹음의 단계 연결 변경",
    description="stage_id: 작품 단계 id, null이면 작품 전체 피드백 (v0.9.7)",
    responses=WRITE_ERRORS,
)
async def update_recording_stage(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    data: RecordingStageUpdate,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
) -> RecordingRead:
    return await _service(session, settings, storage).set_stage(
        owner, artwork_id, recording_id, data
    )


@router.get(
    "/{recording_id}/url",
    summary="녹음 재생 Signed URL",
    responses=READ_ERRORS | error_responses(409, 503),
)
async def recording_url(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
) -> RecordingUrl:
    return await _service(session, settings, storage).owner_url(
        owner, artwork_id, recording_id, user.access_token
    )


@router.delete(
    "/{recording_id}",
    summary="녹음 삭제",
    description="DB에서 먼저 삭제 처리하고 Storage 파일을 지운다 (실패하면 다음 요청에서 재시도).",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def delete_recording(
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
) -> None:
    await _service(session, settings, storage).delete(
        owner, artwork_id, recording_id, user.access_token
    )


# ----------------------------------------------------------------------------- staff


@staff_router.get(
    "",
    summary="담당 학생 작품의 녹음 목록 (강사 이상)",
    description="학원 연결 작품 + 담당 학생만. 학생 개인 작품의 녹음은 404.",
    responses=READ_ERRORS | error_responses(503),
)
async def staff_list_recordings(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    actor: AcademyStaff,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
    include_urls: IncludeUrls = False,
) -> list[RecordingRead]:
    return await _service(session, settings, storage).staff_list(
        actor, artwork_id, user.access_token, include_urls
    )


@staff_router.get("/{recording_id}", summary="녹음 메타데이터 (강사 이상)", responses=READ_ERRORS)
async def staff_get_recording(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
) -> RecordingRead:
    return await _service(session, settings, storage).staff_get(actor, artwork_id, recording_id)


@staff_router.get(
    "/{recording_id}/url",
    summary="녹음 재생 Signed URL (강사 이상)",
    responses=READ_ERRORS | error_responses(409, 503),
)
async def staff_recording_url(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    recording_id: uuid.UUID,
    actor: AcademyStaff,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: AudioStorage,
) -> RecordingUrl:
    return await _service(session, settings, storage).staff_url(
        actor, artwork_id, recording_id, user.access_token
    )
