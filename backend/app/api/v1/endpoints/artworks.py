"""작품·단계별 사진 API (F-06).

- `/artworks`: 학생 본인 작품 (학원 소속 여부와 무관). 생성·수정·삭제·업로드는 본인만.
- `/academies/{academy_id}/artworks`: 강사 이상이 담당 학생의 '학원 연결 작품'을 조회 (읽기 전용).

사진 업로드는 2단계: `POST .../photos`(업로드 URL 발급) → Storage에 직접 PUT → `POST .../complete`.
"""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    AcademyStaff,
    AppSettings,
    AudioStorage,
    DbSession,
    OptionalStorage,
    require_user_types,
)
from app.api.responses import AUTH_ERRORS, error_responses
from app.core.security import CurrentUser
from app.models.enums import UserType
from app.models.profile import Profile
from app.schemas.artworks import (
    ArtworkCreate,
    ArtworkDetail,
    ArtworkProgressRead,
    ArtworkRead,
    ArtworkUpdate,
    PhotoRead,
    PhotoUpdate,
    SignedUrl,
    StaffArtworkDetail,
    StaffArtworkRead,
    UploadRequest,
    UploadTicket,
)
from app.schemas.common import Page, PaginationQuery
from app.services.artworks import ArtworkService, artwork_read
from app.services.exams import student_ref
from app.services.recordings import RecordingService

router = APIRouter(prefix="/artworks", tags=["artworks"])
staff_router = APIRouter(prefix="/academies/{academy_id}/artworks", tags=["artworks"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
READ_ERRORS = AUTH_ERRORS | error_responses(404)
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422)
IncludeUrls = Annotated[
    bool, Query(description="true면 사진마다 짧은 만료의 Signed URL 포함 (Storage 호출)")
]


def _service(session, settings, storage) -> ArtworkService:  # type: ignore[no-untyped-def]
    return ArtworkService(session, settings, storage)


# ----------------------------------------------------------------------------- owner


@router.post(
    "",
    summary="작품 생성 (학생)",
    description="학원 미소속 학생도 개인 작품을 만들 수 있다. 학원·반·과제 연결은 선택.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_artwork(
    data: ArtworkCreate,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> ArtworkDetail:
    return await _service(session, settings, storage).create(owner, data)


@router.get("", summary="내 작품 목록 (작업 날짜 최신순)", responses=READ_ERRORS)
async def list_artworks(
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    pagination: PaginationQuery,
    academy_id: uuid.UUID | None = None,
    work_date_from: dt.date | None = None,
    work_date_to: dt.date | None = None,
) -> Page[ArtworkRead]:
    items, total = await _service(session, settings, storage).list_mine(
        owner,
        pagination,
        academy_id=academy_id,
        work_date_from=work_date_from,
        work_date_to=work_date_to,
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.get(
    "/{artwork_id}", summary="작품 상세 (사진 포함)", responses=READ_ERRORS | error_responses(503)
)
async def get_artwork(
    artwork_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    include_urls: IncludeUrls = False,
) -> ArtworkDetail:
    return await _service(session, settings, storage).get_mine(
        owner, artwork_id, user.access_token, include_urls
    )


@router.patch("/{artwork_id}", summary="작품 수정", responses=WRITE_ERRORS)
async def update_artwork(
    artwork_id: uuid.UUID,
    data: ArtworkUpdate,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> ArtworkDetail:
    return await _service(session, settings, storage).update(
        owner, artwork_id, data, user.access_token
    )


@router.delete(
    "/{artwork_id}",
    summary="작품 삭제 (사진 포함)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def delete_artwork(
    artwork_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    audio_storage: AudioStorage,
) -> None:
    await _service(session, settings, storage).delete(owner, artwork_id, user.access_token)
    # 작품에 연결된 녹음 파일 정리 (실패하면 다음 요청에서 재시도)
    await RecordingService(session, settings, audio_storage).cleanup_storage(
        owner, user.access_token
    )


@router.get("/{artwork_id}/progress", summary="작품 진행 상태", responses=READ_ERRORS)
async def artwork_progress(
    artwork_id: uuid.UUID,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> ArtworkProgressRead:
    return await _service(session, settings, storage).progress(owner, artwork_id)


@router.get(
    "/{artwork_id}/photos",
    summary="작품 사진 목록 (단계 순, 대표 사진 먼저)",
    responses=READ_ERRORS | error_responses(503),
)
async def list_photos(
    artwork_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    include_urls: IncludeUrls = False,
) -> list[PhotoRead]:
    return await _service(session, settings, storage).list_photos(
        owner, artwork_id, user.access_token, include_urls
    )


@router.post(
    "/{artwork_id}/photos",
    summary="사진 업로드 요청 (Signed upload URL 발급)",
    description=(
        "형식·크기를 먼저 검증하고 PENDING 사진과 업로드 URL을 만든다. 파일을 Storage에 올린 뒤 "
        "`POST /artworks/{id}/photos/{photo_id}/complete`를 호출해야 작품에 연결된다. "
        "`replaces_photo_id`를 주면 완료 시 기존 사진을 교체한다."
    ),
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS | error_responses(503),
)
async def request_upload(
    artwork_id: uuid.UUID,
    data: UploadRequest,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> UploadTicket:
    return await _service(session, settings, storage).request_upload(
        owner, artwork_id, data, user.access_token
    )


@router.post(
    "/{artwork_id}/photos/{photo_id}/complete",
    summary="사진 업로드 완료 처리",
    description=(
        "Storage의 파일을 받아 실제 이미지 형식·크기·픽셀 수를 검증하고, 같은 작품의 중복 사진인지 "
        "확인한 뒤 ACTIVE로 전환한다. 이미 완료된 사진이면 같은 결과를 돌려준다(재시도 안전)."
    ),
    responses=WRITE_ERRORS | error_responses(503),
)
async def complete_upload(
    artwork_id: uuid.UUID,
    photo_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> PhotoRead:
    return await _service(session, settings, storage).complete_upload(
        owner, artwork_id, photo_id, user.access_token
    )


@router.patch(
    "/{artwork_id}/photos/{photo_id}",
    summary="대표 사진 지정",
    description="같은 단계의 기존 대표 사진은 자동 해제된다.",
    responses=WRITE_ERRORS,
)
async def update_photo(
    artwork_id: uuid.UUID,
    photo_id: uuid.UUID,
    data: PhotoUpdate,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> PhotoRead:
    return await _service(session, settings, storage).set_representative(
        owner, artwork_id, photo_id, data.is_representative
    )


@router.delete(
    "/{artwork_id}/photos/{photo_id}",
    summary="사진 삭제",
    description="대표 사진을 지우면 같은 단계의 가장 먼저 올린 사진이 대표가 된다.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def delete_photo(
    artwork_id: uuid.UUID,
    photo_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> None:
    await _service(session, settings, storage).delete_photo(
        owner, artwork_id, photo_id, user.access_token
    )


@router.get(
    "/{artwork_id}/photos/{photo_id}/url",
    summary="사진 조회용 Signed URL",
    responses=READ_ERRORS | error_responses(409, 503),
)
async def photo_url(
    artwork_id: uuid.UUID,
    photo_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> SignedUrl:
    return await _service(session, settings, storage).owner_photo_url(
        owner, artwork_id, photo_id, user.access_token
    )


# ----------------------------------------------------------------------------- staff


@staff_router.get(
    "",
    summary="담당 학생 작품 목록 (강사 이상)",
    description="학원에 연결된 작품 중 담당 학생 것만 (OWNER/MANAGER는 학원 전체 학생). "
    "학생의 개인 작품(학원 미연결)은 보이지 않는다.",
    responses=READ_ERRORS,
)
async def list_student_artworks(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    pagination: PaginationQuery,
    student_membership_id: uuid.UUID | None = None,
) -> Page[StaffArtworkRead]:
    rows, total = await _service(session, settings, storage).list_for_staff(
        actor, pagination, student_membership_id=student_membership_id
    )
    items = [
        StaffArtworkRead(**artwork_read(artwork, photos), student=student_ref(m, p))
        for artwork, m, p, photos in rows
    ]
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@staff_router.get(
    "/{artwork_id}",
    summary="담당 학생 작품 상세 (강사 이상)",
    responses=READ_ERRORS | error_responses(503),
)
async def get_student_artwork(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    actor: AcademyStaff,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    include_urls: IncludeUrls = False,
) -> StaffArtworkDetail:
    data, membership, profile = await _service(session, settings, storage).staff_detail(
        actor, artwork_id, user.access_token, include_urls
    )
    return StaffArtworkDetail(**data, student=student_ref(membership, profile))


@staff_router.get(
    "/{artwork_id}/photos/{photo_id}/url",
    summary="담당 학생 작품 사진 Signed URL (강사 이상)",
    responses=READ_ERRORS | error_responses(409, 503),
)
async def student_photo_url(
    academy_id: uuid.UUID,
    artwork_id: uuid.UUID,
    photo_id: uuid.UUID,
    actor: AcademyStaff,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> SignedUrl:
    service = _service(session, settings, storage)
    artwork = await service.staff_artwork(actor, artwork_id)
    return await service.photo_url(artwork.id, photo_id, user.access_token)
