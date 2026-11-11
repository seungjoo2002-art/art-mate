"""작품 공유·F-15 참고작 추천·커뮤니티 (v0.8).

공유와 동의
- 작품은 기본 비공개. 공유는 목적별 동의(`artwork_sharing_consents`: COMMUNITY / REFERENCE)로만
  열리며, 목적마다 공개 범위(ACADEMY/PLATFORM)와 작성자 표시(NAME/ANONYMOUS)를 따로 정한다.
  철회·변경 이력을 보존한다.
- 원본 사진(artworks 버킷)은 공유하지 않는다. 공유 시 서버가 FINAL 대표 사진에서 파생 이미지
  (긴 변 축소, EXIF·메타데이터 제거, 재인코딩)를 만들어 별도 비공개 버킷(shared-artworks)에
  저장하고(`shared_artwork_images`), 보는 사람의 토큰으로 짧은 Signed URL을 그때그때 발급한다.
- 모든 공개 조회는 현재 유효한 동의를 조인해서 판단한다.
  철회하면 즉시 피드·추천·저장 목록에서 빠진다.

참고작 (F-15)
- 우수성 근거 = 강사가 특정 약점 카테고리의 우수 사례로 확인한 기록(`reference_artwork_reviews`).
  카테고리가 같다는 사실만으로 추천하지 않는다. AI가 우수성을 판단하지 않는다.
- 학생별 추천 결과는 `reference_recommendations`에 근거와 함께 스냅샷으로 저장하고,
  조회 시 원작자 동의·이미지·검토 상태를 다시 확인한다.

커뮤니티: 게시물·댓글·좋아요·저장·신고·관리 이력. 모든 테이블 RLS 활성화 (정책 없음).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import (
    ArtworkWorkCategory,
    AuthorDisplay,
    CommentStatus,
    CommentType,
    CommunityReportStatus,
    ConsentGrantor,
    ModerationAction,
    PostCategory,
    PostStatus,
    PracticalType,
    ReferenceReviewStatus,
    ReferenceSetStatus,
    ReportReason,
    ReportTarget,
    SharedImageKind,
    SharedImageStatus,
    SharingPurpose,
    SharingScope,
    WeaknessCategory,
)


class ArtworkSharingConsent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """작품 1개 · 목적 1개의 공유 동의. 변경은 철회 + 새 행 (이력 보존)."""

    __tablename__ = "artwork_sharing_consents"
    __table_args__ = (
        Index(
            "uq_artwork_sharing_consents_active",
            "artwork_id",
            "purpose",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_artwork_sharing_consents_owner", "owner_id", "granted_at"),
        Index(
            "ix_artwork_sharing_consents_visible",
            "purpose",
            "scope",
            "academy_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        CheckConstraint("(scope = 'ACADEMY') = (academy_id IS NOT NULL)", name="scope_academy"),
    )

    artwork_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artworks.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    purpose: Mapped[SharingPurpose] = mapped_column(enum_column(SharingPurpose, "purpose"))
    scope: Mapped[SharingScope] = mapped_column(enum_column(SharingScope, "scope"))
    academy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academies.id", ondelete="CASCADE")
    )
    author_display: Mapped[AuthorDisplay] = mapped_column(
        enum_column(AuthorDisplay, "author_display")
    )
    policy_version: Mapped[str] = mapped_column(String(20))
    granted_by: Mapped[ConsentGrantor] = mapped_column(enum_column(ConsentGrantor, "granted_by"))
    granted_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    # OWNER_REVOKED / CHANGED / ARTWORK_DELETED / ACCOUNT_DELETED 등
    revoked_reason: Mapped[str | None] = mapped_column(String(50))


class SharedArtworkImage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """공유용 파생 이미지 (원본과 다른 비공개 버킷).

    PRIMARY(작품 대표 FINAL 사진, 작품당 살아 있는 것 1개)와
    POST(게시물에 고른 사진, 원본 사진당 1개).
    """

    __tablename__ = "shared_artwork_images"
    __table_args__ = (
        Index(
            "uq_shared_artwork_images_live",
            "artwork_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'ACTIVE') AND kind = 'PRIMARY'"),
        ),
        Index(
            "uq_shared_artwork_images_live_post",
            "artwork_id",
            "source_photo_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'ACTIVE') AND kind = 'POST'"),
        ),
        Index(
            "ix_shared_artwork_images_owner_cleanup",
            "owner_id",
            postgresql_where=text("storage_cleanup_pending"),
        ),
        CheckConstraint(
            "status <> 'ACTIVE' OR (width IS NOT NULL AND height IS NOT NULL"
            " AND size_bytes IS NOT NULL)",
            name="active_has_metadata",
        ),
    )

    artwork_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artworks.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    source_photo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artwork_photos.id", ondelete="SET NULL")
    )
    status: Mapped[SharedImageStatus] = mapped_column(
        enum_column(SharedImageStatus, "status"), default=SharedImageStatus.PENDING
    )
    kind: Mapped[SharedImageKind] = mapped_column(
        enum_column(SharedImageKind, "kind"),
        server_default=SharedImageKind.PRIMARY.value,
        default=SharedImageKind.PRIMARY,
    )
    # "{random}/{image_id}.jpg" (서버 생성, 사용자·작품 ID 미포함 → URL로 작성자 식별 불가)
    storage_path: Mapped[str] = mapped_column(String(512), unique=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None]
    storage_cleanup_pending: Mapped[bool] = mapped_column(
        Boolean, server_default=false(), default=False
    )


class ReferenceArtworkReview(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """강사가 '이 작품은 ○○ 약점의 우수 사례'라고 확인한 기록 (F-15 우수성 근거)."""

    __tablename__ = "reference_artwork_reviews"
    __table_args__ = (
        Index(
            "uq_reference_artwork_reviews_active",
            "artwork_id",
            "category",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_reference_artwork_reviews_category", "category", "status"),
        Index("ix_reference_artwork_reviews_academy", "academy_id", "status", "created_at"),
    )

    artwork_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artworks.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    academy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("academies.id", ondelete="CASCADE"))
    category: Mapped[WeaknessCategory] = mapped_column(enum_column(WeaknessCategory, "category"))
    # 무엇을 참고하면 좋은지 (학생에게 보이는 강사 메모)
    note: Mapped[str] = mapped_column(String(500))
    status: Mapped[ReferenceReviewStatus] = mapped_column(
        enum_column(ReferenceReviewStatus, "status"), default=ReferenceReviewStatus.ACTIVE
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    reviewer_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )


class ReferenceRecommendation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """학생 1명에게 추천한 참고작 1개 (새로고침 단위 set_id로 묶음)."""

    __tablename__ = "reference_recommendations"
    __table_args__ = (
        UniqueConstraint("owner_id", "set_id", "reference_artwork_id"),
        Index("ix_reference_recommendations_owner_set", "owner_id", "status", "rank"),
        Index(
            "ix_reference_recommendations_saved",
            "owner_id",
            "saved_at",
            postgresql_where=text("saved_at IS NOT NULL"),
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    set_id: Mapped[uuid.UUID]
    status: Mapped[ReferenceSetStatus] = mapped_column(
        enum_column(ReferenceSetStatus, "status"), default=ReferenceSetStatus.ACTIVE
    )
    weakness_category: Mapped[WeaknessCategory] = mapped_column(
        enum_column(WeaknessCategory, "weakness_category")
    )
    weakness_rank: Mapped[int] = mapped_column(Integer)
    reference_artwork_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artworks.id", ondelete="CASCADE")
    )
    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reference_artwork_reviews.id", ondelete="CASCADE")
    )
    rank: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    # [{code, message}] 추천 근거 + 사용한 입력 (엔진 이름·버전, 학생 실기 유형 등)
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    data_fingerprint: Mapped[str] = mapped_column(String(64))
    saved_at: Mapped[datetime | None]


class CommunityPost(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_posts"
    __table_args__ = (
        Index(
            "uq_community_posts_live_artwork",
            "artwork_id",
            unique=True,
            postgresql_where=text("status <> 'DELETED'"),
        ),
        Index("ix_community_posts_feed", "status", "created_at"),
        Index("ix_community_posts_author", "author_id", "created_at"),
        # VER.2: 카테고리 필터
        Index("ix_community_posts_category_feed", "category", "status", "created_at"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("like_count >= 0 AND comment_count >= 0", name="counts_nonnegative"),
        # VER.2: 작품 공유 게시물은 작품 필수, 사진 없는 글은 본문 필수
        CheckConstraint(
            "category <> 'ARTWORK_SHARE' OR artwork_id IS NOT NULL", name="share_has_artwork"
        ),
        CheckConstraint(
            "artwork_id IS NOT NULL OR (body IS NOT NULL AND length(btrim(body)) > 0)",
            name="text_post_has_body",
        ),
        CheckConstraint("photo_id IS NULL OR artwork_id IS NOT NULL", name="photo_needs_artwork"),
    )

    # VER.2: NULL = 사진 없는 글 (작품·공유 동의 없이 작성)
    artwork_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artworks.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    image_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shared_artwork_images.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str | None] = mapped_column(String(2000))
    practical_type: Mapped[PracticalType | None] = mapped_column(
        enum_column(PracticalType, "practical_type")
    )
    work_category: Mapped[ArtworkWorkCategory | None] = mapped_column(
        enum_column(ArtworkWorkCategory, "work_category")
    )
    status: Mapped[PostStatus] = mapped_column(
        enum_column(PostStatus, "status"), default=PostStatus.ACTIVE
    )
    like_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    comment_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    hidden_at: Mapped[datetime | None]
    hidden_reason: Mapped[str | None] = mapped_column(String(300))
    deleted_at: Mapped[datetime | None]
    # v0.9 F-6: 작품에 대해 묻고 싶은 질문 (선택)
    question: Mapped[str | None] = mapped_column(String(1000))
    # VER.2 게시판 분류 (기존 게시물: question 있으면 FEEDBACK_REQUEST, 없으면 ARTWORK_SHARE)
    category: Mapped[PostCategory] = mapped_column(
        enum_column(PostCategory, "category"),
        server_default=PostCategory.ARTWORK_SHARE.value,
        default=PostCategory.ARTWORK_SHARE,
    )
    # VER.2 작품에서 고른 사진 (NULL = 기본 대표 사진). 사진이 지워지면 NULL
    photo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artwork_photos.id", ondelete="SET NULL")
    )
    # VER.2 사진 없는 글의 작성자 표시 (작품 게시물은 공유 동의의 표시 방식을 따른다)
    author_display: Mapped[AuthorDisplay | None] = mapped_column(
        enum_column(AuthorDisplay, "author_display")
    )


class CommunityComment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_comments"
    __table_args__ = (
        Index("ix_community_comments_post", "post_id", "status", "created_at"),
        Index("ix_community_comments_author", "author_id", "created_at"),
        CheckConstraint("length(btrim(body)) > 0", name="body_not_blank"),
        # v0.9: 항목 지정은 작품 피드백 댓글만
        CheckConstraint(
            "comment_type = 'FEEDBACK' OR cardinality(categories) = 0",
            name="categories_only_feedback",
        ),
        CheckConstraint(
            "categories <@ ARRAY["
            + ", ".join(f"'{c.value}'" for c in WeaknessCategory)
            + "]::varchar[]",
            name="categories_known",
        ),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(String(1000))
    status: Mapped[CommentStatus] = mapped_column(
        enum_column(CommentStatus, "status"), default=CommentStatus.ACTIVE
    )
    hidden_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    # v0.9 F-6: 일반 의견 / 작품 피드백(+ 선택 항목: 약점 카테고리 코드)
    comment_type: Mapped[CommentType] = mapped_column(
        enum_column(CommentType, "comment_type"),
        server_default=CommentType.GENERAL.value,
        default=CommentType.GENERAL,
    )
    categories: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), server_default=text("'{}'::varchar[]"), default=list
    )
    # VER.2 익명 댓글: 다른 사람에게는 '익명 학생'으로 보이고 DB에는 작성자 ID를 그대로 둔다
    # (본인 수정·삭제, 관리자 신고 처리용)
    is_anonymous: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)


class CommunityLike(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_likes"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id"),
        Index("ix_community_likes_user", "user_id", "created_at"),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))


class CommunityBookmark(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_bookmarks"
    __table_args__ = (
        UniqueConstraint("post_id", "user_id"),
        Index("ix_community_bookmarks_user", "user_id", "created_at"),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))


class CommunityReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "community_reports"
    __table_args__ = (
        CheckConstraint(
            "(target_type = 'COMMENT') = (comment_id IS NOT NULL)", name="target_matches"
        ),
        # 같은 사람이 같은 대상을 중복 신고하지 못한다
        Index(
            "uq_community_reports_post",
            "reporter_id",
            "post_id",
            unique=True,
            postgresql_where=text("target_type = 'POST'"),
        ),
        Index(
            "uq_community_reports_comment",
            "reporter_id",
            "comment_id",
            unique=True,
            postgresql_where=text("target_type = 'COMMENT'"),
        ),
        Index("ix_community_reports_status", "status", "created_at"),
    )

    target_type: Mapped[ReportTarget] = mapped_column(enum_column(ReportTarget, "target_type"))
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("community_posts.id", ondelete="CASCADE"))
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_comments.id", ondelete="CASCADE")
    )
    reporter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    reason: Mapped[ReportReason] = mapped_column(enum_column(ReportReason, "reason"))
    detail: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[CommunityReportStatus] = mapped_column(
        enum_column(CommunityReportStatus, "status"), default=CommunityReportStatus.OPEN
    )
    handled_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    handled_at: Mapped[datetime | None]
    resolution_note: Mapped[str | None] = mapped_column(String(500))


class CommunityModerationLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """관리 처리 이력 (append-only). actor_id NULL = 시스템(신고 누적 자동 숨김)."""

    __tablename__ = "community_moderation_logs"
    __table_args__ = (Index("ix_community_moderation_logs_created", "created_at"),)

    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    action: Mapped[ModerationAction] = mapped_column(enum_column(ModerationAction, "action"))
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_posts.id", ondelete="SET NULL")
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_comments.id", ondelete="SET NULL")
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("community_reports.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
