"""v1.1 원본 제시물 사진 + AI 비교 첨삭 입력 (학생 본인 작품만).

업로드 흐름은 작품 사진과 같다: 요청(Signed upload URL) → 브라우저가 Storage에 직접 업로드 → 완료.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AppSettings, DbSession, OptionalStorage, require_user_types
from app.api.responses import AUTH_ERRORS, error_responses
from app.core.security import CurrentUser
from app.models.enums import UserType
from app.models.profile import Profile
from app.schemas.comparison import ComparisonInput
from app.schemas.reference_photos import (
    ReferencePhotoList,
    ReferencePhotoRead,
    ReferenceUploadRequest,
    ReferenceUploadTicket,
)
from app.services.artwork_stages import active_stages
from app.services.comparison_input import build_comparison_input
from app.services.reference_photos import ReferencePhotoService

router = APIRouter(prefix="/artworks", tags=["reference-photos"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
READ_ERRORS = AUTH_ERRORS | error_responses(404)
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422)
IncludeUrls = Annotated[
    bool, Query(description="true면 사진마다 짧은 만료의 Signed URL 포함 (Storage 호출)")
]


def _svc(session, settings, storage) -> ReferencePhotoService:  # type: ignore[no-untyped-def]
    return ReferencePhotoService(session, settings, storage)


@router.get(
    "/{artwork_id}/reference-photos",
    summary="원본 제시물 사진 목록 (v1.1)",
    description="업로드 완료된 사진만, 순서대로. 최대 장수(max_count)도 함께.",
    responses=READ_ERRORS | error_responses(503),
)
async def list_reference_photos(
    artwork_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    include_urls: IncludeUrls = False,
) -> ReferencePhotoList:
    return await _svc(session, settings, storage).list(
        owner, artwork_id, user.access_token, include_urls=include_urls
    )


@router.post(
    "/{artwork_id}/reference-photos",
    status_code=status.HTTP_201_CREATED,
    summary="원본 제시물 사진 업로드 요청 (v1.1)",
    description=(
        "JPG·PNG·WebP, 작품 사진과 같은 크기 제한. "
        "작품당 최대 ARTWORK_MAX_REFERENCE_PHOTOS장(기본 5). replaces_photo_id를 주면 완료 시 "
        "그 사진을 같은 자리에서 교체한다. 완료한 작품에도 추가할 수 있다."
    ),
    responses=WRITE_ERRORS | error_responses(503),
)
async def request_reference_upload(
    artwork_id: uuid.UUID,
    data: ReferenceUploadRequest,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> ReferenceUploadTicket:
    return await _svc(session, settings, storage).request_upload(
        owner, artwork_id, data, user.access_token
    )


@router.post(
    "/{artwork_id}/reference-photos/{photo_id}/complete",
    summary="원본 제시물 사진 업로드 완료 (v1.1)",
    description="실제 이미지 형식·크기·픽셀 수를 검증하고 같은 작품의 중복을 막는다. 재시도 안전.",
    responses=WRITE_ERRORS | error_responses(503),
)
async def complete_reference_upload(
    artwork_id: uuid.UUID,
    photo_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> ReferencePhotoRead:
    return await _svc(session, settings, storage).complete_upload(
        owner, artwork_id, photo_id, user.access_token
    )


@router.delete(
    "/{artwork_id}/reference-photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="원본 제시물 사진 삭제 (v1.1)",
    description=(
        "DB에서 먼저 삭제 처리하고 Storage 파일은 정리 작업이 지운다 (실패하면 다음에 재시도)."
    ),
    responses=WRITE_ERRORS,
)
async def delete_reference_photo(
    artwork_id: uuid.UUID,
    photo_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> None:
    await _svc(session, settings, storage).delete(owner, artwork_id, photo_id, user.access_token)


@router.get(
    "/{artwork_id}/comparison-input",
    summary="AI 비교 첨삭 입력 미리보기 (v1.1, AI 호출 없음)",
    description=(
        "v1.2에서 원본 제시물과 학생 작품을 비교할 때 AI에 보낼 입력 구조. "
        "저장된 작품 정보·원본 사진·단계 사진·표현 의도만으로 만들며 분석 결과는 포함하지 않는다. "
        "이미지는 id로만 참조한다."
    ),
    responses=READ_ERRORS,
)
async def comparison_input(
    artwork_id: uuid.UUID,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> ComparisonInput:
    svc = _svc(session, settings, storage)
    artwork = await svc.artworks.owned(owner, artwork_id)
    photos = (await svc.artworks._photos([artwork.id])).get(artwork.id, [])
    stages = await active_stages(session, artwork.id)
    return build_comparison_input(artwork, await svc.active(artwork.id), stages, photos)
