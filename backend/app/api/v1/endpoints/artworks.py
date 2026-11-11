"""작품·단계별 사진 API (F-06).

- `/artworks`: 학생 본인 작품 (학원 소속 여부와 무관). 생성·수정·삭제·업로드는 본인만.
- `/academies/{academy_id}/artworks`: 강사 이상이 담당 학생의 '학원 연결 작품'을 조회 (읽기 전용).

사진 업로드는 2단계: `POST .../photos`(업로드 URL 발급) → Storage에 직접 PUT → `POST .../complete`.

v0.5.1: 실기 유형(practical_type)·작업 목적(work_category) 분류와 필터, 작품 완료
(`POST /artworks/{id}/complete`, `POST /artworks/{id}/reopen`), 목록의 recording_count.
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
    SharedStorage,
    require_user_types,
)
from app.api.responses import AUTH_ERRORS, error_responses
from app.core.security import CurrentUser
from app.models.enums import ArtworkWorkCategory, ArtworkWorkStatus, PracticalType, UserType
from app.models.profile import Profile
from app.schemas.artworks import (
    ArtworkCreate,
    ArtworkDetail,
    ArtworkExamNext,
    ArtworkExamPlan,
    ArtworkExamRead,
    ArtworkProgressRead,
    ArtworkRead,
    ArtworkUpdate,
    PhotoRead,
    PhotoUpdate,
    SignedUrl,
    StaffArtworkDetail,
    StaffArtworkRead,
    TimerEventCreate,
    TimerRead,
    UploadRequest,
    UploadTicket,
)
from app.schemas.common import Page, PaginationQuery
from app.schemas.students import student_ref
from app.services.artwork_timer import ArtworkTimerService
from app.services.artworks import ArtworkFilters, ArtworkService
from app.services.exam_stages import ExamStageService
from app.services.recordings import RecordingService
from app.services.sharing import SharingService

router = APIRouter(prefix="/artworks", tags=["artworks"])
staff_router = APIRouter(prefix="/academies/{academy_id}/artworks", tags=["artworks"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
READ_ERRORS = AUTH_ERRORS | error_responses(404)
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422)
IncludeUrls = Annotated[
    bool, Query(description="true면 사진마다 짧은 만료의 Signed URL 포함 (Storage 호출)")
]
PracticalTypeFilter = Annotated[
    list[PracticalType] | None,
    Query(
        description="실기 유형 필터. 여러 번 주면 OR "
        "(`?practical_type=BASIC_DESIGN&practical_type=DRAWING`)"
    ),
]
WorkCategoryFilter = Annotated[
    list[ArtworkWorkCategory] | None,
    Query(description="작업 목적 필터. 여러 번 주면 OR. practical_type과 함께 주면 AND"),
]
WorkStatusFilter = Annotated[
    ArtworkWorkStatus | None, Query(description="IN_PROGRESS 또는 COMPLETED")
]


def _service(session, settings, storage) -> ArtworkService:  # type: ignore[no-untyped-def]
    return ArtworkService(session, settings, storage)


# ----------------------------------------------------------------------------- owner


@router.post(
    "",
    summary="작품 생성 (학생)",
    description="학원 미소속 학생도 개인 작품을 만들 수 있다. 학원·반·과제 연결은 선택. "
    "v0.9: 실기 주제·작업 방식·실제 소요 시간·제한 시간(분), recommendation_id(개인 과제 수행 "
    "작품으로 연결, 채택된 본인 과제만).",
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


@router.get(
    "",
    summary="내 작품 목록 (작업 날짜 최신순)",
    description=(
        "필터는 모두 선택이며 서로 AND로 결합된다. 아카이브 필터 예: "
        "'기초디자인' → `practical_type=BASIC_DESIGN`, '모의시험' → `work_category=MOCK_EXAM`, "
        "'개인 연습' → `work_category=PERSONAL_PRACTICE`. "
        "각 항목에 `recording_count`(ACTIVE 피드백 녹음 수)가 포함된다."
    ),
    responses=READ_ERRORS | error_responses(422),
)
async def list_artworks(
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    pagination: PaginationQuery,
    academy_id: uuid.UUID | None = None,
    work_date_from: dt.date | None = None,
    work_date_to: dt.date | None = None,
    practical_type: PracticalTypeFilter = None,
    work_category: WorkCategoryFilter = None,
    work_status: WorkStatusFilter = None,
) -> Page[ArtworkRead]:
    filters = ArtworkFilters(
        academy_id=academy_id,
        work_date_from=work_date_from,
        work_date_to=work_date_to,
        practical_types=practical_type or (),
        work_categories=work_category or (),
        work_status=work_status,
    )
    items, total = await _service(session, settings, storage).list_mine(owner, pagination, filters)
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
    shared_storage: SharedStorage,
) -> None:
    await _service(session, settings, storage).delete(owner, artwork_id, user.access_token)
    # 작품에 연결된 녹음 파일 정리 (실패하면 다음 요청에서 재시도)
    await RecordingService(session, settings, audio_storage).cleanup_storage(
        owner, user.access_token
    )
    # v0.8: 공유용 파생 이미지 정리
    await SharingService(session, settings, shared_storage=shared_storage).cleanup_storage(
        owner, user.access_token
    )


@router.post(
    "/{artwork_id}/complete",
    summary="작품 완료하기 (학생)",
    description=(
        "작업 상태를 COMPLETED로 바꾸고 completed_at을 기록한다. ACTIVE FINAL 사진이 없으면 409 "
        "`FINAL_PHOTO_REQUIRED`. 이미 완료된 작품이면 변경 없이 200 (멱등, 완료 시각 유지). "
        "완료 후에는 사진 업로드·교체·삭제·대표 변경이 409 `ARTWORK_COMPLETED`로 막히고, "
        "제목·설명·분류 수정과 피드백 녹음은 가능하다. 진행 중이던 사진 업로드는 취소된다."
    ),
    responses=WRITE_ERRORS,
)
async def complete_artwork(
    artwork_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> ArtworkDetail:
    return await _service(session, settings, storage).complete(owner, artwork_id, user.access_token)


@router.post(
    "/{artwork_id}/reopen",
    summary="작업 재개 (완료 취소, 학생)",
    description="작업 상태를 IN_PROGRESS로 되돌리고 completed_at을 지운다. "
    "이미 작업 중이면 200 (멱등).",
    responses=WRITE_ERRORS,
)
async def reopen_artwork(
    artwork_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
) -> ArtworkDetail:
    return await _service(session, settings, storage).reopen(owner, artwork_id, user.access_token)


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


# ============================================================================ v0.9 타이머 (F-2)


@router.get(
    "/{artwork_id}/timer",
    summary="작품 타이머 상태 (새로고침·앱 재시작 후 복원)",
    description="저장된 이벤트로 계산한 현재 상태·누적 시간·남은 제한 시간. "
    "서버는 타이머를 돌리지 않으므로 RUNNING이면 running_since부터 클라이언트가 이어서 센다.",
    responses=READ_ERRORS,
)
async def get_timer(
    artwork_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> TimerRead:
    return await ArtworkTimerService(session, settings).get(owner, artwork_id)


@router.post(
    "/{artwork_id}/timer/events",
    summary="타이머 시작·일시정지·재개·종료·초기화",
    description="STOP하면 누적 시간(올림, 분)이 작품의 actual_minutes(time_source=TIMER)로 "
    "저장된다. 잘못된 전이 409 `TIMER_INVALID_TRANSITION`, 시각 오류 422 `TIMER_INVALID_TIME`, "
    "24시간 초과 422 `TIMER_TOO_LONG`.",
    responses=WRITE_ERRORS,
)
async def record_timer_event(
    artwork_id: uuid.UUID,
    data: TimerEventCreate,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> TimerRead:
    return await ArtworkTimerService(session, settings).record(owner, artwork_id, data)


# ============================================================================ VER.2 실기시험 단계


@router.get(
    "/{artwork_id}/exam",
    summary="실기시험 단계 진행 상태 (다른 기기에서도 같은 값)",
    description="단계별 목표·작업 시간(일시정지 제외)·현재 단계와 작품 타이머 상태.",
    responses=READ_ERRORS,
)
async def get_exam(
    artwork_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> ArtworkExamRead:
    return await ExamStageService(session, settings).get(owner, artwork_id)


@router.put(
    "/{artwork_id}/exam/plan",
    summary="실기시험 단계 계획 저장 (순서·목표 시간)",
    description="목표 합계가 작품의 제한 시간(time_limit_minutes)이 된다. 시작 후에는 단계 구성은 "
    "바꿀 수 없고 목표 시간만 바꿀 수 있다 (409 EXAM_ALREADY_STARTED).",
    responses=WRITE_ERRORS,
)
async def save_exam_plan(
    artwork_id: uuid.UUID,
    data: ArtworkExamPlan,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ArtworkExamRead:
    return await ExamStageService(session, settings).save_plan(owner, artwork_id, data)


@router.post(
    "/{artwork_id}/exam/next",
    summary="다음 단계로 (현재 단계 종료 + 다음 단계 시작)",
    description="타이머가 RUNNING·PAUSED일 때만 (409 EXAM_NOT_RUNNING). current_stage가 서버의 "
    "현재 단계와 다르면 409 EXAM_STAGE_CONFLICT (중복 전환 방지), 마지막 단계면 409 "
    "EXAM_LAST_STAGE (타이머 STOP으로 끝냄). 시작은 타이머 START, 종료는 STOP.",
    responses=WRITE_ERRORS,
)
async def next_exam_stage(
    artwork_id: uuid.UUID,
    data: ArtworkExamNext,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ArtworkExamRead:
    return await ExamStageService(session, settings).next_stage(owner, artwork_id, data)


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
    practical_type: PracticalTypeFilter = None,
    work_category: WorkCategoryFilter = None,
    work_status: WorkStatusFilter = None,
) -> Page[StaffArtworkRead]:
    filters = ArtworkFilters(
        practical_types=practical_type or (),
        work_categories=work_category or (),
        work_status=work_status,
    )
    rows, total = await _service(session, settings, storage).list_for_staff(
        actor, pagination, filters, student_membership_id=student_membership_id
    )
    items = [StaffArtworkRead(**data, student=student_ref(m, p)) for data, m, p in rows]
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
