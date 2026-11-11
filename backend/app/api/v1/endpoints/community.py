"""작품 공유·F-15 참고작·커뮤니티 API (v0.8).

- /artworks/{artwork_id}/sharing            작품 공유 동의 (목적별: COMMUNITY / REFERENCE)
- /references/me                            학생 참고작 추천·저장
- /academies/{academy_id}/references        강사 우수 사례 확인·해제·후보
- /community                                게시물·좋아요·저장·댓글·신고
- /admin/community                          시스템 ADMIN 신고 처리·숨김·이력
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    AcademyStaff,
    ActiveProfile,
    AppSettings,
    DbSession,
    OptionalStorage,
    SharedStorage,
    require_user_types,
)
from app.api.responses import AUTH_ERRORS, error_responses
from app.core.security import CurrentUser
from app.models.enums import (
    ArtworkWorkCategory,
    CommunityReportStatus,
    ModerationAction,
    PostCategory,
    PracticalType,
    ReferenceReviewStatus,
    ReportTarget,
    SharingPurpose,
    UserType,
    WeaknessCategory,
)
from app.models.profile import Profile
from app.schemas.ai_feedback import FeedbackNoteRead
from app.schemas.common import Page, PaginationQuery
from app.schemas.community import (
    AdminReportRead,
    BookmarkState,
    CandidateRead,
    CommentAdopt,
    CommentCreate,
    CommentRead,
    CommentUpdate,
    LikeState,
    ModerationLogRead,
    ModerationRequest,
    PostCreate,
    PostRead,
    PostUpdate,
    ReferenceItem,
    ReferenceResult,
    RefreshResult,
    ReportAck,
    ReportCreate,
    ReportDismiss,
    ReportResolve,
    ReviewCreate,
    ReviewRead,
    SharingConsentRead,
    SharingGrant,
    SharingStatus,
)
from app.services.community import CommunityService
from app.services.references import ReferenceService
from app.services.sharing import SharingService

sharing = APIRouter(prefix="/artworks/{artwork_id}/sharing", tags=["sharing"])
references_me = APIRouter(prefix="/references/me", tags=["references"])
references_staff = APIRouter(prefix="/academies/{academy_id}/references", tags=["references"])
community = APIRouter(prefix="/community", tags=["community"])
admin = APIRouter(prefix="/admin/community", tags=["community-admin"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
Admin = Annotated[Profile, Depends(require_user_types(UserType.ADMIN))]
READ = AUTH_ERRORS | error_responses(404)
WRITE = AUTH_ERRORS | error_responses(404, 409, 422)
LIMITED = WRITE | error_responses(429)


def _community(session, settings, shared, photos=None) -> CommunityService:  # type: ignore[no-untyped-def]
    return CommunityService(session, settings, shared, photos)


# ============================================================================ 공유 동의


@sharing.get("", summary="작품 공유 상태 (학생 본인)", responses=READ)
async def sharing_status(
    artwork_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
) -> SharingStatus:
    svc = SharingService(session, settings, shared_storage=shared)
    return await svc.status(owner, artwork_id, user.access_token)


@sharing.get("/history", summary="공유 동의 이력", responses=READ)
async def sharing_history(
    artwork_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> list[SharingConsentRead]:
    return await SharingService(session, settings).history(owner, artwork_id)


@sharing.put(
    "/{purpose}",
    summary="공유 동의·범위 변경 (학생 본인)",
    description=(
        "COMMUNITY(커뮤니티 게시) / REFERENCE(참고작 활용)를 따로 동의한다. FINAL 대표 사진이 "
        "있어야 하며(409 FINAL_PHOTO_REQUIRED), "
        "처음 동의할 때 공유용 파생 이미지(축소·EXIF 제거)를 "
        "만든다. 범위·작성자 표시를 바꾸면 이전 동의는 CHANGED로 철회되고 새 동의가 남는다. "
        "ACADEMY 범위는 학원에 연결된 작품만 (422 SHARING_SCOPE_INVALID)."
    ),
    responses=WRITE | error_responses(503),
)
async def grant_sharing(
    artwork_id: uuid.UUID,
    purpose: SharingPurpose,
    data: SharingGrant,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    photos: OptionalStorage,
    shared: SharedStorage,
) -> SharingStatus:
    svc = SharingService(session, settings, photo_storage=photos, shared_storage=shared)
    return await svc.grant(owner, artwork_id, purpose, data, user.access_token)


@sharing.delete(
    "/{purpose}",
    summary="공유 철회 (학생 본인)",
    description=(
        "COMMUNITY 철회: 게시물 삭제. REFERENCE 철회: 이 작품을 가리키는 참고작 추천·저장 삭제. "
        "남은 동의가 없으면 공유용 이미지도 삭제한다. 철회 즉시 다른 사람에게 보이지 않는다."
    ),
    responses=WRITE,
)
async def revoke_sharing(
    artwork_id: uuid.UUID,
    purpose: SharingPurpose,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
) -> SharingStatus:
    svc = SharingService(session, settings, shared_storage=shared)
    return await svc.revoke(owner, artwork_id, purpose, user.access_token)


# ============================================================================ 참고작 (학생)


@references_me.get(
    "",
    summary="내 참고작 추천 (반복 약점별)",
    description="마지막 새로고침 결과. 원작자가 철회했거나 강사 확인이 해제된 항목은 빠진다 "
    "(removed_count). 아직 없으면 status=NOT_GENERATED → POST /refresh.",
    responses=READ,
)
async def my_references(
    student: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
    category: WeaknessCategory | None = None,
) -> ReferenceResult:
    svc = ReferenceService(session, settings, shared)
    return await svc.current(student, user.access_token, category=category)


@references_me.post(
    "/refresh",
    summary="참고작 추천 새로고침",
    description="v0.7 반복 약점 TOP 3 기준으로 다시 계산. 입력이 같으면 refreshed=false로 기존 "
    "결과를 돌려준다. 검증된 우수 사례가 없으면 NO_VERIFIED_REFERENCES.",
    responses=READ,
)
async def refresh_references(
    student: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
) -> RefreshResult:
    return await ReferenceService(session, settings, shared).refresh(student, user.access_token)


@references_me.get("/saved", summary="저장한 참고작", responses=READ)
async def saved_references(
    student: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
) -> list[ReferenceItem]:
    return await ReferenceService(session, settings, shared).saved(student, user.access_token)


@references_me.get("/{reference_id}", summary="참고작 상세·추천 근거", responses=READ)
async def reference_detail(
    reference_id: uuid.UUID,
    student: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
) -> ReferenceItem:
    svc = ReferenceService(session, settings, shared)
    return await svc.detail(student, reference_id, user.access_token)


@references_me.put("/{reference_id}/save", summary="참고작 저장", responses=READ)
async def save_reference(
    reference_id: uuid.UUID,
    student: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
) -> ReferenceItem:
    svc = ReferenceService(session, settings, shared)
    return await svc.set_saved(student, reference_id, True, user.access_token)


@references_me.delete("/{reference_id}/save", summary="참고작 저장 해제", responses=READ)
async def unsave_reference(
    reference_id: uuid.UUID,
    student: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
) -> ReferenceItem:
    svc = ReferenceService(session, settings, shared)
    return await svc.set_saved(student, reference_id, False, user.access_token)


# ============================================================================ 참고작 (강사)


@references_staff.post(
    "/reviews",
    summary="우수 사례 확인 (강사)",
    description="담당 학생의 학원 연결 작품을 특정 약점 카테고리의 참고 사례로 확인한다. 학생이 "
    "REFERENCE 공유에 동의해야 추천에 쓰인다. 같은 작품·카테고리 중복 409.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE,
)
async def create_review(
    academy_id: uuid.UUID,
    data: ReviewCreate,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReviewRead:
    return await ReferenceService(session, settings).create_review(actor, profile, data)


@references_staff.get("/reviews", summary="우수 사례 목록 (강사)", responses=READ)
async def list_reviews(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
    category: WeaknessCategory | None = None,
    student_membership_id: uuid.UUID | None = None,
    review_status: Annotated[ReferenceReviewStatus | None, Query(alias="status")] = (
        ReferenceReviewStatus.ACTIVE
    ),
) -> Page[ReviewRead]:
    items, total = await ReferenceService(session, settings).list_reviews(
        actor,
        pagination,
        category=category,
        student_membership_id=student_membership_id,
        status=review_status,
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@references_staff.delete(
    "/reviews/{review_id}",
    summary="우수 사례 확인 해제 (강사)",
    description="이 확인을 근거로 한 학생별 추천도 함께 사라진다.",
    responses=WRITE,
)
async def revoke_review(
    academy_id: uuid.UUID,
    review_id: uuid.UUID,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReviewRead:
    return await ReferenceService(session, settings).revoke_review(actor, profile, review_id)


@references_staff.get(
    "/candidates",
    summary="우수 사례 후보 (강사 확인용, 자동 추천 아님)",
    description="승인된 첨삭에서 이 카테고리가 '잘한 점'으로 언급된 담당 학생 작품.",
    responses=READ,
)
async def review_candidates(
    academy_id: uuid.UUID,
    category: WeaknessCategory,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[CandidateRead]:
    return await ReferenceService(session, settings).candidates(actor, category, limit)


# ============================================================================ 커뮤니티

PracticalQ = Annotated[list[PracticalType] | None, Query()]
CategoryQ = Annotated[list[ArtworkWorkCategory] | None, Query()]
PostCategoryQ = Annotated[
    list[PostCategory] | None,
    Query(
        description="VER.2 게시판 분류 (여러 개 OR): PRACTICE_QUESTION / FEEDBACK_REQUEST / "
        "ARTWORK_SHARE / FREE"
    ),
]


@community.get(
    "/posts",
    summary="커뮤니티 피드 (최신순)",
    description="볼 수 있는 게시물만: PLATFORM 공개 + 내가 ACTIVE 멤버인 학원의 ACADEMY 공개.",
    responses=READ,
)
async def feed(
    viewer: ActiveProfile,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
    pagination: PaginationQuery,
    practical_type: PracticalQ = None,
    work_category: CategoryQ = None,
    academy_id: uuid.UUID | None = None,
    category: PostCategoryQ = None,
) -> Page[PostRead]:
    items, total = await _community(session, settings, shared).feed(
        viewer,
        pagination,
        user.access_token,
        practical_types=practical_type or [],
        work_categories=work_category or [],
        academy_id=academy_id,
        categories=category or [],
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@community.post(
    "/posts",
    summary="게시물 작성 (학생)",
    description="작품 게시물: 작품의 COMMUNITY 공유 동의 필요 (409 SHARING_CONSENT_REQUIRED), "
    "작품당 1개 (409 POST_ALREADY_EXISTS), photo_id로 공유할 사진 선택 "
    "(생략 시 완성 대표 사진, 없으면 409 PHOTO_SELECTION_REQUIRED). "
    "VER.2 사진 없는 글: artwork_id 생략, 본문 필수, ARTWORK_SHARE 불가. "
    "하루 작성 수 제한 (429).",
    status_code=status.HTTP_201_CREATED,
    responses=LIMITED,
)
async def create_post(
    data: PostCreate,
    author: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
    photos: OptionalStorage,
) -> PostRead:
    return await _community(session, settings, shared, photos).create_post(
        author, data, user.access_token
    )


@community.get("/posts/me", summary="내 게시물 (숨김 포함)", responses=READ)
async def my_posts(
    author: ActiveProfile,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
    pagination: PaginationQuery,
) -> Page[PostRead]:
    items, total = await _community(session, settings, shared).my_posts(
        author, pagination, user.access_token
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@community.get("/bookmarks", summary="저장한 게시물 (지금 볼 수 있는 것만)", responses=READ)
async def my_bookmarks(
    viewer: ActiveProfile,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
    pagination: PaginationQuery,
) -> Page[PostRead]:
    items, total = await _community(session, settings, shared).bookmarks(
        viewer, pagination, user.access_token
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@community.get("/posts/{post_id}", summary="게시물 상세", responses=READ)
async def get_post(
    post_id: uuid.UUID,
    viewer: ActiveProfile,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
) -> PostRead:
    return await _community(session, settings, shared).get_post(viewer, post_id, user.access_token)


@community.patch("/posts/{post_id}", summary="게시물 수정 (작성자)", responses=WRITE)
async def update_post(
    post_id: uuid.UUID,
    data: PostUpdate,
    author: ActiveProfile,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
    photos: OptionalStorage,
) -> PostRead:
    svc = _community(session, settings, shared, photos)
    return await svc.update_post(author, post_id, data, user.access_token)


@community.delete(
    "/posts/{post_id}",
    summary="게시물 삭제 (작성자)",
    description="게시물만 삭제한다. "
    "작품 공유 동의는 그대로이며 /artworks/{id}/sharing에서 철회한다. "
    "VER.2: 게시물용으로 고른 사진의 공유 이미지는 함께 삭제된다.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
)
async def delete_post(
    post_id: uuid.UUID,
    author: ActiveProfile,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    shared: SharedStorage,
) -> None:
    await _community(session, settings, shared).delete_post(author, post_id, user.access_token)


@community.put("/posts/{post_id}/like", summary="좋아요", responses=READ)
async def like(
    post_id: uuid.UUID, viewer: ActiveProfile, session: DbSession, settings: AppSettings
) -> LikeState:
    return await _community(session, settings, None).set_like(viewer, post_id, True)


@community.delete("/posts/{post_id}/like", summary="좋아요 취소", responses=READ)
async def unlike(
    post_id: uuid.UUID, viewer: ActiveProfile, session: DbSession, settings: AppSettings
) -> LikeState:
    return await _community(session, settings, None).set_like(viewer, post_id, False)


@community.put("/posts/{post_id}/bookmark", summary="게시물 저장", responses=READ)
async def bookmark(
    post_id: uuid.UUID, viewer: ActiveProfile, session: DbSession, settings: AppSettings
) -> BookmarkState:
    return await _community(session, settings, None).set_bookmark(viewer, post_id, True)


@community.delete("/posts/{post_id}/bookmark", summary="게시물 저장 취소", responses=READ)
async def unbookmark(
    post_id: uuid.UUID, viewer: ActiveProfile, session: DbSession, settings: AppSettings
) -> BookmarkState:
    return await _community(session, settings, None).set_bookmark(viewer, post_id, False)


@community.get("/posts/{post_id}/comments", summary="댓글 목록 (오래된 순)", responses=READ)
async def list_comments(
    post_id: uuid.UUID,
    viewer: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
) -> Page[CommentRead]:
    items, total = await _community(session, settings, None).comments(viewer, post_id, pagination)
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@community.post(
    "/posts/{post_id}/comments",
    summary="댓글 작성",
    description="10분당 작성 수 제한 (429 RATE_LIMITED). "
    "v0.9: comment_type=FEEDBACK(작품 피드백)이면 "
    "categories(구도·비례·명암·채색 등)를 선택해 붙일 수 있다.",
    status_code=status.HTTP_201_CREATED,
    responses=LIMITED,
)
async def add_comment(
    post_id: uuid.UUID,
    data: CommentCreate,
    viewer: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> CommentRead:
    return await _community(session, settings, None).add_comment(viewer, post_id, data)


@community.patch("/comments/{comment_id}", summary="댓글 수정 (작성자)", responses=WRITE)
async def update_comment(
    comment_id: uuid.UUID,
    data: CommentUpdate,
    viewer: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> CommentRead:
    return await _community(session, settings, None).update_comment(viewer, comment_id, data)


@community.post(
    "/comments/{comment_id}/adopt",
    summary="작품 피드백 댓글 채택 → 내 첨삭 기록 (게시물 작성자, v0.9)",
    description="FEEDBACK 댓글을 출처 PEER(다른 학생 의견) 텍스트 첨삭으로 내 작품에 저장한다. "
    "채택 전에는 성장 분석에 반영되지 않고, 채택해도 강사 첨삭과 구분되어 반복 약점 통계에는 "
    "들어가지 않는다. 게시물 작성자만 (아니면 403), 일반 댓글 409 `COMMENT_NOT_FEEDBACK`, "
    "이미 채택 409 `COMMENT_ALREADY_ADOPTED`.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE,
)
async def adopt_comment(
    comment_id: uuid.UUID,
    viewer: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
    data: CommentAdopt | None = None,
) -> FeedbackNoteRead:
    return await _community(session, settings, None).adopt_comment(
        viewer, comment_id, data or CommentAdopt()
    )


@community.delete(
    "/comments/{comment_id}",
    summary="댓글 삭제 (작성자)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
)
async def delete_comment(
    comment_id: uuid.UUID, viewer: ActiveProfile, session: DbSession, settings: AppSettings
) -> None:
    await _community(session, settings, None).delete_comment(viewer, comment_id)


@community.post(
    "/posts/{post_id}/reports",
    summary="게시물 신고",
    description="본인 게시물 신고 불가(422), 중복 신고 409, 하루 신고 수 제한 429. "
    "서로 다른 사용자의 미처리 신고가 누적되면 자동 숨김(관리자 검토 대기).",
    status_code=status.HTTP_201_CREATED,
    responses=LIMITED,
)
async def report_post(
    post_id: uuid.UUID,
    data: ReportCreate,
    viewer: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReportAck:
    return await _community(session, settings, None).report(viewer, data, post_id=post_id)


@community.post(
    "/comments/{comment_id}/reports",
    summary="댓글 신고",
    status_code=status.HTTP_201_CREATED,
    responses=LIMITED,
)
async def report_comment(
    comment_id: uuid.UUID,
    data: ReportCreate,
    viewer: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReportAck:
    return await _community(session, settings, None).report(viewer, data, comment_id=comment_id)


# ============================================================================ 관리 (ADMIN)


@admin.get("/reports", summary="신고 목록 (ADMIN)", responses=READ)
async def admin_reports(
    _: Admin,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
    report_status: Annotated[CommunityReportStatus | None, Query(alias="status")] = (
        CommunityReportStatus.OPEN
    ),
    target_type: ReportTarget | None = None,
) -> Page[AdminReportRead]:
    items, total = await _community(session, settings, None).admin_reports(
        pagination, report_status, target_type
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@admin.post(
    "/reports/{report_id}/resolve",
    summary="신고 처리 (ADMIN)",
    description="HIDE: 대상 숨김 / NONE: 조치 없이 완료. 같은 대상의 다른 미처리 신고도 함께 처리.",
    responses=WRITE,
)
async def resolve_report(
    report_id: uuid.UUID,
    data: ReportResolve,
    admin_user: Admin,
    session: DbSession,
    settings: AppSettings,
) -> AdminReportRead:
    return await _community(session, settings, None).resolve_report(admin_user, report_id, data)


@admin.post(
    "/reports/{report_id}/dismiss",
    summary="신고 기각 (ADMIN)",
    description="restore=true면 신고 누적으로 자동 숨김된 대상을 다시 보이게 한다.",
    responses=WRITE,
)
async def dismiss_report(
    report_id: uuid.UUID,
    data: ReportDismiss,
    admin_user: Admin,
    session: DbSession,
    settings: AppSettings,
) -> AdminReportRead:
    return await _community(session, settings, None).dismiss_report(admin_user, report_id, data)


async def _moderate(  # type: ignore[no-untyped-def]
    session, settings, admin_user: Profile, action: ModerationAction, target: uuid.UUID, data
) -> None:
    await _community(session, settings, None).moderate(
        admin_user, action, target, data.reason if data else None
    )


@admin.post(
    "/posts/{post_id}/hide",
    summary="게시물 숨김 (ADMIN)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
)
async def hide_post(
    post_id: uuid.UUID,
    admin_user: Admin,
    session: DbSession,
    settings: AppSettings,
    data: ModerationRequest | None = None,
) -> None:
    await _moderate(session, settings, admin_user, ModerationAction.HIDE_POST, post_id, data)


@admin.post(
    "/posts/{post_id}/unhide",
    summary="게시물 숨김 해제 (ADMIN)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
)
async def unhide_post(
    post_id: uuid.UUID,
    admin_user: Admin,
    session: DbSession,
    settings: AppSettings,
    data: ModerationRequest | None = None,
) -> None:
    await _moderate(session, settings, admin_user, ModerationAction.UNHIDE_POST, post_id, data)


@admin.post(
    "/comments/{comment_id}/hide",
    summary="댓글 숨김 (ADMIN)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
)
async def hide_comment(
    comment_id: uuid.UUID,
    admin_user: Admin,
    session: DbSession,
    settings: AppSettings,
    data: ModerationRequest | None = None,
) -> None:
    await _moderate(session, settings, admin_user, ModerationAction.HIDE_COMMENT, comment_id, data)


@admin.post(
    "/comments/{comment_id}/unhide",
    summary="댓글 숨김 해제 (ADMIN)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE,
)
async def unhide_comment(
    comment_id: uuid.UUID,
    admin_user: Admin,
    session: DbSession,
    settings: AppSettings,
    data: ModerationRequest | None = None,
) -> None:
    await _moderate(
        session, settings, admin_user, ModerationAction.UNHIDE_COMMENT, comment_id, data
    )


@admin.get("/moderation-logs", summary="관리 처리 이력 (ADMIN)", responses=READ)
async def moderation_logs(
    _: Admin, session: DbSession, settings: AppSettings, pagination: PaginationQuery
) -> Page[ModerationLogRead]:
    items, total = await _community(session, settings, None).moderation_logs(pagination)
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)
