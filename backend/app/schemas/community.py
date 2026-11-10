"""작품 공유·참고작·커뮤니티 API 요청·응답 (v0.8)."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.models.enums import (
    ArtworkWorkCategory,
    AuthorDisplay,
    CommentStatus,
    CommentType,
    CommunityReportStatus,
    ConsentGrantor,
    ModerationAction,
    PostStatus,
    PracticalType,
    ReferenceReason,
    ReferenceResultStatus,
    ReferenceReviewStatus,
    ReportReason,
    ReportTarget,
    SharingPurpose,
    SharingScope,
    WeaknessCategory,
)
from app.schemas.fields import InputModel
from app.schemas.students import StudentRef

Text100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Text500 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Text1000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
Text2000 = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]

# ============================================================================ 공유 동의


class ImageRead(BaseModel):
    """공유용 파생 이미지 (원본 아님). URL은 보는 사람 권한으로 발급한 짧은 Signed URL."""

    image_id: uuid.UUID
    url: str | None = Field(description="만료되면 목록·상세를 다시 조회")
    url_expires_at: dt.datetime | None
    width: int
    height: int


class SharingGrant(InputModel):
    scope: SharingScope = Field(
        description="ACADEMY: 작품이 연결된 학원 멤버만 / PLATFORM: ART MATE 로그인 사용자 전체"
    )
    author_display: AuthorDisplay = Field(
        default=AuthorDisplay.ANONYMOUS, description="NAME: 표시 이름 공개 / ANONYMOUS: '익명 학생'"
    )
    policy_version: str = Field(min_length=1, max_length=20)
    agreed: Literal[True]
    granted_by: ConsentGrantor = Field(
        default=ConsentGrantor.SELF, description="만 14세 미만은 GUARDIAN (법정대리인 동의)"
    )


class SharingConsentRead(BaseModel):
    id: uuid.UUID
    purpose: SharingPurpose
    scope: SharingScope
    academy_id: uuid.UUID | None
    author_display: AuthorDisplay
    policy_version: str
    granted_by: ConsentGrantor
    granted_at: dt.datetime
    revoked_at: dt.datetime | None
    revoked_reason: str | None


class SharingStatus(BaseModel):
    artwork_id: uuid.UUID
    required_version: str
    community: SharingConsentRead | None = Field(description="커뮤니티 게시 동의 (없으면 null)")
    reference: SharingConsentRead | None = Field(description="참고작 활용 동의 (없으면 null)")
    image: ImageRead | None = Field(description="공유용 이미지 (동의가 하나라도 있으면)")
    post_id: uuid.UUID | None = Field(description="이 작품의 커뮤니티 게시물")


# ============================================================================ 참고작


class AuthorRead(BaseModel):
    display_name: str = Field(description="작성자 표시 설정에 따라 이름 또는 '익명 학생'")
    is_anonymous: bool
    is_me: bool


class ReasonRead(BaseModel):
    code: ReferenceReason
    message: str


class ReferenceItem(BaseModel):
    id: uuid.UUID
    weakness_category: WeaknessCategory
    weakness_label: str
    weakness_rank: int = Field(description="학생의 반복 약점 순위 (1 = 가장 많이 지적)")
    rank: int = Field(description="이 학생에게 보여 줄 순서")
    reasons: list[ReasonRead] = Field(description="추천 근거 (검증된 사실만)")
    reference_point: str = Field(description="강사가 남긴 참고 포인트")
    reviewed_at: dt.datetime
    practical_type: PracticalType | None
    work_category: ArtworkWorkCategory | None
    author: AuthorRead
    image: ImageRead | None
    community_post_id: uuid.UUID | None = Field(description="볼 수 있는 커뮤니티 게시물이 있으면")
    saved: bool
    created_at: dt.datetime


class ReferenceResult(BaseModel):
    status: ReferenceResultStatus
    message: str | None
    weaknesses: list[WeaknessCategory] = Field(
        description="추천 기준으로 쓴 반복 약점 (v0.7 TOP 3)"
    )
    practical_type: PracticalType | None = Field(description="학생의 주 실기 유형")
    generated_at: dt.datetime | None
    items: list[ReferenceItem]
    removed_count: int = Field(description="원작자 철회 등으로 빠진 항목 수")


class RefreshResult(ReferenceResult):
    refreshed: bool = Field(description="false: 입력이 같아 기존 추천을 그대로 반환")


class ReviewCreate(InputModel):
    artwork_id: uuid.UUID
    category: WeaknessCategory
    note: Text500 = Field(description="학생이 무엇을 참고하면 좋은지 (학생에게 보임)")


class ReviewRead(BaseModel):
    id: uuid.UUID
    artwork_id: uuid.UUID
    artwork_title: str
    category: WeaknessCategory
    note: str
    status: ReferenceReviewStatus
    reviewer_name: str | None
    student: StudentRef
    reference_consent: SharingConsentRead | None = Field(
        description="학생의 참고작 활용 동의 (없으면 추천에 쓰이지 않음)"
    )
    created_at: dt.datetime
    revoked_at: dt.datetime | None


class CandidateRead(BaseModel):
    """강사용 우수 사례 후보 (자동 추천 아님).

    승인된 첨삭에서 이 카테고리가 '잘한 점'으로 언급된 담당 학생 작품.
    """

    artwork_id: uuid.UUID
    artwork_title: str
    work_date: dt.date
    practical_type: PracticalType | None
    student: StudentRef
    strength_texts: list[str]
    already_reviewed: bool
    has_reference_consent: bool


# ============================================================================ 커뮤니티


class PostCreate(InputModel):
    artwork_id: uuid.UUID
    title: Text100
    body: Text2000 | None = None
    question: Text1000 | None = Field(
        default=None, description="작품에 대해 묻고 싶은 질문 (v0.9, 선택)"
    )
    practical_type: PracticalType | None = Field(default=None, description="생략하면 작품 값")
    work_category: ArtworkWorkCategory | None = Field(default=None, description="생략하면 작품 값")


class PostUpdate(InputModel):
    title: Text100 | None = None
    body: Text2000 | None = None
    question: Text1000 | None = None
    practical_type: PracticalType | None = None
    work_category: ArtworkWorkCategory | None = None


class VisibilityRead(BaseModel):
    scope: SharingScope
    academy_id: uuid.UUID | None


class PostRead(BaseModel):
    id: uuid.UUID
    artwork_id: uuid.UUID | None = Field(description="본인 게시물일 때만")
    title: str
    body: str | None
    question: str | None = Field(default=None, description="작성자의 질문 (v0.9)")
    practical_type: PracticalType | None
    work_category: ArtworkWorkCategory | None
    author: AuthorRead
    image: ImageRead | None
    visibility: VisibilityRead
    like_count: int
    comment_count: int
    liked: bool
    bookmarked: bool
    status: PostStatus
    hidden_reason: str | None = Field(description="숨김 사유 (본인에게만)")
    created_at: dt.datetime
    updated_at: dt.datetime


class LikeState(BaseModel):
    post_id: uuid.UUID
    liked: bool
    like_count: int


class BookmarkState(BaseModel):
    post_id: uuid.UUID
    bookmarked: bool


class CommentCreate(InputModel):
    body: Text1000
    comment_type: CommentType = Field(
        default=CommentType.GENERAL,
        description="v0.9: GENERAL(일반 의견) / FEEDBACK(작품 피드백, 작성자가 채택 가능)",
    )
    categories: list[WeaknessCategory] = Field(
        default_factory=list,
        max_length=5,
        description="작품 피드백 항목 (구도·비례·명암·채색 등, FEEDBACK일 때만)",
    )

    @model_validator(mode="after")
    def _categories_only_feedback(self) -> "CommentCreate":
        if self.categories and self.comment_type != CommentType.FEEDBACK:
            raise ValueError("categories are only for FEEDBACK comments")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("duplicate category")
        return self


class CommentUpdate(InputModel):
    """댓글 수정. 보내지 않은 필드는 그대로 (기존처럼 body만 보내도 된다)."""

    body: Text1000
    comment_type: CommentType | None = None
    categories: list[WeaknessCategory] | None = Field(default=None, max_length=5)


class CommentAdopt(InputModel):
    request_summary: bool = Field(
        default=False, description="채택 후 AI 요약·분류 요청 (AI 전송 동의 필요, 없으면 저장만)"
    )


class CommentRead(BaseModel):
    id: uuid.UUID
    post_id: uuid.UUID
    body: str
    author: AuthorRead = Field(description="댓글은 항상 표시 이름 (익명 아님)")
    comment_type: CommentType = CommentType.GENERAL
    categories: list[WeaknessCategory] = Field(default_factory=list)
    adopted: bool | None = Field(
        default=None,
        description="게시물 작성자가 내 첨삭 기록으로 채택함 (게시물 작성자·댓글 작성자에게만)",
    )
    status: CommentStatus
    created_at: dt.datetime
    updated_at: dt.datetime


class ReportCreate(InputModel):
    reason: ReportReason
    detail: Text500 | None = None


class ReportAck(BaseModel):
    id: uuid.UUID
    target_type: ReportTarget
    status: CommunityReportStatus
    created_at: dt.datetime


# ============================================================================ 관리


class AdminReportRead(BaseModel):
    id: uuid.UUID
    target_type: ReportTarget
    post_id: uuid.UUID
    comment_id: uuid.UUID | None
    reason: ReportReason
    detail: str | None
    status: CommunityReportStatus
    reporter_id: uuid.UUID
    target_status: str
    target_preview: str = Field(description="게시물 제목 또는 댓글 앞부분")
    open_report_count: int = Field(description="같은 대상의 미처리 신고 수")
    created_at: dt.datetime
    handled_at: dt.datetime | None
    resolution_note: str | None


class ReportResolve(InputModel):
    action: Literal["HIDE", "NONE"] = Field(
        description="HIDE: 대상 숨김 / NONE: 조치 없이 처리 완료"
    )
    note: Text500 | None = None


class ReportDismiss(InputModel):
    note: Text500 | None = None
    restore: bool = Field(
        default=True, description="자동 숨김된 대상을 다시 보이게 함 (다른 미처리 신고가 없을 때)"
    )


class ModerationRequest(InputModel):
    reason: Text500 | None = None


class ModerationLogRead(BaseModel):
    id: uuid.UUID
    actor_name: str | None = Field(description="NULL = 시스템 (신고 누적 자동 숨김)")
    action: ModerationAction
    post_id: uuid.UUID | None
    comment_id: uuid.UUID | None
    report_id: uuid.UUID | None
    note: str | None
    created_at: dt.datetime
