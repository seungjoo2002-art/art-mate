"""커뮤니티 (v0.8): 게시물·좋아요·저장·댓글·신고·관리.

공개 규칙
- 게시물은 본인 작품에만, 그 작품의 COMMUNITY 공유 동의가 유효할 때만 쓸 수 있다. 공개 범위·작성자
  표시는
  동의를 따른다 (ACADEMY: 그 학원 ACTIVE 멤버, PLATFORM: 로그인 사용자). 이미지는 공유용 파생
  이미지.
- 피드·상세·좋아요·댓글 등 모든 조회는 '현재 유효한 동의 + 범위 + 게시물 ACTIVE'를 조인해서
  판단한다.
  보이지 않는 게시물은 존재 여부를 숨긴다(404). 숨김(HIDDEN)·삭제 게시물은 작성자 본인만 상태를
  본다.
- 저장(북마크)한 게시물도 원작자가 공유를 철회하면 목록에서 빠진다.

남용 방지
- 사용자별 요청 제한(DB 기준): 게시물 하루 N개, 댓글 10분 N개, 신고 하루 N개 → 429 RATE_LIMITED.
- 좋아요·저장·신고는 유니크 제약으로 중복을 막는다 (동시 요청에도 1번만 반영).
- 서로 다른 사용자의 미처리 신고가 기준 수에 도달하면 자동 숨김(관리자 검토 대기, 이력 기록).
- 관리: 시스템 ADMIN이 신고 처리·숨김·복구. 모든 처리는 community_moderation_logs에 남긴다.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnprocessableError,
)
from app.integrations.supabase.storage import StorageClient
from app.models.ai_feedback import FeedbackNote
from app.models.artwork import Artwork
from app.models.community import (
    ArtworkSharingConsent,
    CommunityBookmark,
    CommunityComment,
    CommunityLike,
    CommunityModerationLog,
    CommunityPost,
    CommunityReport,
    SharedArtworkImage,
)
from app.models.enums import (
    AuthorDisplay,
    CommentStatus,
    CommentType,
    CommunityReportStatus,
    FeedbackSource,
    ModerationAction,
    PostCategory,
    PostStatus,
    PracticalType,
    ReportTarget,
    SharedImageStatus,
    SharingPurpose,
    SharingScope,
)
from app.models.profile import Profile
from app.repositories.pagination import fetch_page
from app.schemas.ai_feedback import FeedbackNoteCreate, FeedbackNoteRead
from app.schemas.common import PaginationParams
from app.schemas.community import (
    AdminReportRead,
    AuthorRead,
    BookmarkState,
    CommentAdopt,
    CommentCreate,
    CommentRead,
    CommentUpdate,
    LikeState,
    ModerationLogRead,
    PostCreate,
    PostRead,
    PostUpdate,
    ReportAck,
    ReportCreate,
    ReportDismiss,
    ReportResolve,
    VisibilityRead,
)
from app.services.feedback_notes import FeedbackNoteService
from app.services.sharing import (
    ANONYMOUS_NAME,
    SharingService,
    author_name,
    retire_post_images,
    sign_images,
    visible_consent,
)


class CommunityService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        shared_storage: StorageClient | None = None,
        photo_storage: StorageClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.shared_storage = shared_storage
        self.photo_storage = photo_storage

    def _sharing(self) -> SharingService:
        return SharingService(
            self.session,
            self.settings,
            photo_storage=self.photo_storage,
            shared_storage=self.shared_storage,
        )

    # ================================================================ 공통

    async def _rate_limit(
        self, model: Any, column: Any, user_id: uuid.UUID, limit: int, window: timedelta
    ) -> None:
        since = clock.utc_now() - window
        count = (
            await self.session.execute(
                select(func.count())
                .select_from(model)
                .where(column == user_id, model.created_at >= since)
            )
        ).scalar_one()
        if count >= limit:
            raise RateLimitedError(
                details={
                    "limit": limit,
                    "window_seconds": int(window.total_seconds()),
                    "retry_after_seconds": int(window.total_seconds()),
                },
                headers={"Retry-After": str(int(window.total_seconds()))},
            )

    def _visible_posts(self, viewer: Profile) -> Any:
        """보이는 게시물 + 그 동의 (게시물 ACTIVE).

        작품 게시물: 유효 COMMUNITY 동의 범위 안 + 작품 삭제 안 됨.
        사진 없는 글(VER.2): 로그인한 사용자 모두 (동의 행 없음 → consent는 None).
        """
        return (
            select(CommunityPost, ArtworkSharingConsent)
            .outerjoin(
                ArtworkSharingConsent,
                and_(
                    ArtworkSharingConsent.artwork_id == CommunityPost.artwork_id,
                    visible_consent(viewer.id, SharingPurpose.COMMUNITY),
                ),
            )
            .outerjoin(Artwork, Artwork.id == CommunityPost.artwork_id)
            .where(
                CommunityPost.status == PostStatus.ACTIVE,
                or_(
                    CommunityPost.artwork_id.is_(None),
                    and_(ArtworkSharingConsent.id.is_not(None), Artwork.deleted_at.is_(None)),
                ),
            )
        )

    async def _post_reads(
        self,
        viewer: Profile,
        rows: list[tuple[CommunityPost, ArtworkSharingConsent | None]],
        token: str,
    ) -> list[PostRead]:
        if not rows:
            return []
        posts = [p for p, _ in rows]
        ids = [p.id for p in posts]
        authors = {
            p.id: p
            for p in (
                await self.session.execute(
                    select(Profile).where(Profile.id.in_({p.author_id for p in posts}))
                )
            ).scalars()
        }
        image_rows = list(
            (
                await self.session.execute(
                    select(SharedArtworkImage).where(
                        SharedArtworkImage.id.in_({p.image_id for p in posts if p.image_id}),
                        SharedArtworkImage.status == SharedImageStatus.ACTIVE,
                    )
                )
            ).scalars()
        )
        images = await sign_images(self.shared_storage, self.settings, image_rows, token)
        liked = set(
            (
                await self.session.execute(
                    select(CommunityLike.post_id).where(
                        CommunityLike.post_id.in_(ids), CommunityLike.user_id == viewer.id
                    )
                )
            ).scalars()
        )
        bookmarked = set(
            (
                await self.session.execute(
                    select(CommunityBookmark.post_id).where(
                        CommunityBookmark.post_id.in_(ids), CommunityBookmark.user_id == viewer.id
                    )
                )
            ).scalars()
        )
        result = []
        for post, consent in rows:
            author = authors[post.author_id]
            mine = post.author_id == viewer.id
            display = (
                consent.author_display if consent else post.author_display or AuthorDisplay.NAME
            )
            name = author_name(author, display, viewer.id)
            result.append(
                PostRead(
                    id=post.id,
                    artwork_id=post.artwork_id if mine else None,
                    title=post.title,
                    body=post.body,
                    question=post.question,
                    category=post.category,
                    has_artwork=post.artwork_id is not None,
                    photo_id=post.photo_id if mine else None,
                    practical_type=post.practical_type,
                    work_category=post.work_category,
                    author=AuthorRead(
                        display_name=name, is_anonymous=name == ANONYMOUS_NAME, is_me=mine
                    ),
                    image=images.get(post.image_id) if post.image_id else None,
                    visibility=VisibilityRead(
                        scope=consent.scope if consent else SharingScope.PLATFORM,
                        academy_id=consent.academy_id if consent else None,
                    ),
                    like_count=post.like_count,
                    comment_count=post.comment_count,
                    liked=post.id in liked,
                    bookmarked=post.id in bookmarked,
                    status=post.status,
                    hidden_reason=post.hidden_reason if mine else None,
                    created_at=post.created_at,
                    updated_at=post.updated_at,
                )
            )
        return result

    async def _visible_post(
        self, viewer: Profile, post_id: uuid.UUID, *, lock: bool = False
    ) -> CommunityPost:
        stmt = self._visible_posts(viewer).where(CommunityPost.id == post_id)
        if lock:
            stmt = stmt.with_for_update(of=CommunityPost)
        row = (await self.session.execute(stmt)).first()
        if row is None:
            raise NotFoundError("Post not found")
        return row[0]

    # ================================================================ 게시물

    async def _create_text_post(self, author: Profile, data: PostCreate, token: str) -> PostRead:
        """사진 없는 글 (VER.2): 작품·공유 동의 없이 작성."""
        await self._rate_limit(
            CommunityPost,
            CommunityPost.author_id,
            author.id,
            self.settings.community_posts_per_day,
            timedelta(days=1),
        )
        post = CommunityPost(
            id=uuid.uuid4(),
            artwork_id=None,
            author_id=author.id,
            image_id=None,
            title=data.title,
            body=data.body,
            question=data.question or None,
            category=data.category or PostCategory.FREE,
            author_display=data.author_display or AuthorDisplay.NAME,
            practical_type=data.practical_type,
            work_category=data.work_category,
            status=PostStatus.ACTIVE,
        )
        self.session.add(post)
        await self.session.commit()
        return await self.get_post(author, post.id, token)

    async def create_post(self, author: Profile, data: PostCreate, token: str) -> PostRead:
        if data.artwork_id is None:
            return await self._create_text_post(author, data, token)
        artwork = (
            await self.session.execute(
                select(Artwork)
                .where(
                    Artwork.id == data.artwork_id,
                    Artwork.owner_id == author.id,
                    Artwork.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if artwork is None:
            raise NotFoundError("Artwork not found")
        consent = (
            await self.session.execute(
                select(ArtworkSharingConsent).where(
                    ArtworkSharingConsent.artwork_id == artwork.id,
                    ArtworkSharingConsent.purpose == SharingPurpose.COMMUNITY,
                    ArtworkSharingConsent.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if consent is None:
            raise ConflictError(
                "Agree to community sharing for this artwork first",
                code=ErrorCode.SHARING_CONSENT_REQUIRED,
                details={"purpose": SharingPurpose.COMMUNITY.value},
            )
        existing = (
            await self.session.execute(
                select(CommunityPost.id).where(
                    CommunityPost.artwork_id == artwork.id,
                    CommunityPost.status != PostStatus.DELETED,
                )
            )
        ).first()
        if existing is not None:
            raise ConflictError(
                "This artwork is already posted", code=ErrorCode.POST_ALREADY_EXISTS
            )
        image = await self._post_image(author, artwork, data.photo_id, token)
        # 이미지 만들기에서 커밋했을 수 있으므로 작품 행을 다시 잠근다
        artwork = (
            await self.session.execute(
                select(Artwork)
                .where(Artwork.id == artwork.id, Artwork.deleted_at.is_(None))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if artwork is None:
            raise NotFoundError("Artwork not found")
        await self._rate_limit(
            CommunityPost,
            CommunityPost.author_id,
            author.id,
            self.settings.community_posts_per_day,
            timedelta(days=1),
        )
        post = CommunityPost(
            id=uuid.uuid4(),
            artwork_id=artwork.id,
            author_id=author.id,
            image_id=image.id,
            photo_id=data.photo_id,
            title=data.title,
            body=data.body or None,
            question=data.question or None,
            category=data.category
            or (PostCategory.FEEDBACK_REQUEST if data.question else PostCategory.ARTWORK_SHARE),
            practical_type=data.practical_type or artwork.practical_type,
            work_category=data.work_category or artwork.work_category,
            status=PostStatus.ACTIVE,
        )
        self.session.add(post)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(
                "This artwork is already posted", code=ErrorCode.POST_ALREADY_EXISTS
            ) from None
        return await self.get_post(author, post.id, token)

    async def feed(
        self,
        viewer: Profile,
        params: PaginationParams,
        token: str,
        *,
        practical_types: list[PracticalType],
        work_categories: list[Any],
        academy_id: uuid.UUID | None,
        categories: list[PostCategory] | None = None,
    ) -> tuple[list[PostRead], int]:
        stmt = self._visible_posts(viewer)
        if categories:
            stmt = stmt.where(CommunityPost.category.in_(categories))
        if practical_types:
            stmt = stmt.where(CommunityPost.practical_type.in_(practical_types))
        if work_categories:
            stmt = stmt.where(CommunityPost.work_category.in_(work_categories))
        if academy_id is not None:
            stmt = stmt.where(
                ArtworkSharingConsent.scope == SharingScope.ACADEMY,
                ArtworkSharingConsent.academy_id == academy_id,
            )
        stmt = stmt.order_by(CommunityPost.created_at.desc(), CommunityPost.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return await self._post_reads(viewer, [(r[0], r[1]) for r in rows], token), total

    async def my_posts(
        self, author: Profile, params: PaginationParams, token: str
    ) -> tuple[list[PostRead], int]:
        stmt = (
            select(CommunityPost, ArtworkSharingConsent)
            .outerjoin(
                ArtworkSharingConsent,
                and_(
                    ArtworkSharingConsent.artwork_id == CommunityPost.artwork_id,
                    ArtworkSharingConsent.purpose == SharingPurpose.COMMUNITY,
                    ArtworkSharingConsent.revoked_at.is_(None),
                ),
            )
            .where(CommunityPost.author_id == author.id, CommunityPost.status != PostStatus.DELETED)
            .order_by(CommunityPost.created_at.desc(), CommunityPost.id)
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return await self._post_reads(author, [(r[0], r[1]) for r in rows], token), total

    async def get_post(self, viewer: Profile, post_id: uuid.UUID, token: str) -> PostRead:
        row = (
            await self.session.execute(
                self._visible_posts(viewer).where(CommunityPost.id == post_id)
            )
        ).first()
        if row is None:
            # 작성자 본인은 숨김 상태여도 볼 수 있다 (사유 확인용)
            own = (
                await self.session.execute(
                    select(CommunityPost).where(
                        CommunityPost.id == post_id,
                        CommunityPost.author_id == viewer.id,
                        CommunityPost.status == PostStatus.HIDDEN,
                    )
                )
            ).scalar_one_or_none()
            if own is None:
                raise NotFoundError("Post not found")
            consent = (
                await self.session.execute(
                    select(ArtworkSharingConsent).where(
                        ArtworkSharingConsent.artwork_id == own.artwork_id,
                        ArtworkSharingConsent.purpose == SharingPurpose.COMMUNITY,
                        ArtworkSharingConsent.revoked_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            return (await self._post_reads(viewer, [(own, consent)], token))[0]
        return (await self._post_reads(viewer, [(row[0], row[1])], token))[0]

    async def _own_post(self, author: Profile, post_id: uuid.UUID) -> CommunityPost:
        post = (
            await self.session.execute(
                select(CommunityPost)
                .where(CommunityPost.id == post_id, CommunityPost.status != PostStatus.DELETED)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if post is None:
            raise NotFoundError("Post not found")
        if post.author_id != author.id:
            raise ForbiddenError("Only the author can change this post")
        return post

    async def _post_image(
        self, author: Profile, artwork: Artwork, photo_id: uuid.UUID | None, token: str
    ) -> SharedArtworkImage:
        """게시물 이미지: 고른 사진이 있으면 그 사진의 POST 이미지, 없으면 대표(PRIMARY) 이미지."""
        sharing = self._sharing()
        if photo_id is not None:
            return await sharing.ensure_post_image(author, artwork, photo_id, token)
        image = await sharing.live_image(artwork.id)
        if image is None:
            raise ConflictError(
                "This artwork has no FINAL photo; choose a photo to share (photo_id)",
                code=ErrorCode.PHOTO_SELECTION_REQUIRED,
            )
        return image

    async def update_post(
        self, author: Profile, post_id: uuid.UUID, data: PostUpdate, token: str
    ) -> PostRead:
        post = await self._own_post(author, post_id)
        changes = data.model_dump(exclude_unset=True)
        if not changes:
            raise UnprocessableError("Nothing to update")
        for field in ("title", "category"):
            if field in changes and changes[field] is None:
                raise UnprocessableError(f"'{field}' cannot be null")
        if post.artwork_id is None:
            if "photo_id" in changes:
                raise UnprocessableError("Posts without an artwork have no photo")
            if changes.get("category") == PostCategory.ARTWORK_SHARE:
                raise UnprocessableError("ARTWORK_SHARE posts need an artwork")
            if "body" in changes and not changes["body"]:
                raise UnprocessableError("body is required for posts without an artwork")
        elif "author_display" in changes:
            raise UnprocessableError("Change the author display in the sharing consent")
        if "photo_id" in changes:
            post_id_value = post.id
            artwork = (
                await self.session.execute(
                    select(Artwork).where(
                        Artwork.id == post.artwork_id, Artwork.deleted_at.is_(None)
                    )
                )
            ).scalar_one()
            old_image_id = post.image_id
            image = await self._post_image(author, artwork, changes.pop("photo_id"), token)
            post = await self._own_post(author, post_id_value)  # 커밋 후 다시 잠금
            post.image_id = image.id
            post.photo_id = image.source_photo_id if image.kind.value == "POST" else None
            if old_image_id and old_image_id != image.id:
                await retire_post_images(self.session, SharedArtworkImage.id == old_image_id)
                post.image_id = image.id  # retire가 같은 게시물을 비웠을 수 있음
        for field, value in changes.items():
            setattr(post, field, value or None if field in ("body", "question") else value)
        await self.session.commit()
        await self._sharing().cleanup_storage(author, token)
        return await self.get_post(author, post.id, token)

    async def delete_post(
        self, author: Profile, post_id: uuid.UUID, token: str | None = None
    ) -> None:
        post = await self._own_post(author, post_id)
        post.status = PostStatus.DELETED
        post.deleted_at = clock.utc_now()
        if post.image_id is not None:
            # 게시물용으로 고른 사진의 공유 이미지는 함께 삭제 (대표 이미지는 동의가 관리)
            await retire_post_images(self.session, SharedArtworkImage.id == post.image_id)
        await self.session.commit()
        if token:
            await self._sharing().cleanup_storage(author, token)

    # ================================================================ 좋아요·저장

    async def set_like(self, viewer: Profile, post_id: uuid.UUID, liked: bool) -> LikeState:
        post = await self._visible_post(viewer, post_id)
        if liked:
            inserted = (
                await self.session.execute(
                    insert(CommunityLike)
                    .values(id=uuid.uuid4(), post_id=post.id, user_id=viewer.id)
                    .on_conflict_do_nothing(index_elements=["post_id", "user_id"])
                    .returning(CommunityLike.id)
                )
            ).first()
            delta = 1 if inserted else 0
        else:
            removed = (
                await self.session.execute(
                    CommunityLike.__table__.delete()
                    .where(CommunityLike.post_id == post.id, CommunityLike.user_id == viewer.id)
                    .returning(CommunityLike.id)
                )
            ).first()
            delta = -1 if removed else 0
        count = (
            await self.session.execute(
                update(CommunityPost)
                .where(CommunityPost.id == post.id)
                .values(like_count=CommunityPost.like_count + delta)
                .returning(CommunityPost.like_count)
            )
        ).scalar_one()
        await self.session.commit()
        return LikeState(post_id=post.id, liked=liked, like_count=count)

    async def set_bookmark(
        self, viewer: Profile, post_id: uuid.UUID, bookmarked: bool
    ) -> BookmarkState:
        post = await self._visible_post(viewer, post_id)
        if bookmarked:
            await self.session.execute(
                insert(CommunityBookmark)
                .values(id=uuid.uuid4(), post_id=post.id, user_id=viewer.id)
                .on_conflict_do_nothing(index_elements=["post_id", "user_id"])
            )
        else:
            await self.session.execute(
                CommunityBookmark.__table__.delete().where(
                    CommunityBookmark.post_id == post.id, CommunityBookmark.user_id == viewer.id
                )
            )
        await self.session.commit()
        return BookmarkState(post_id=post.id, bookmarked=bookmarked)

    async def bookmarks(
        self, viewer: Profile, params: PaginationParams, token: str
    ) -> tuple[list[PostRead], int]:
        """저장한 게시물 중 지금도 볼 수 있는 것 (공유 철회·숨김·삭제된 게시물은 빠짐)."""
        stmt = (
            self._visible_posts(viewer)
            .join(CommunityBookmark, CommunityBookmark.post_id == CommunityPost.id)
            .where(CommunityBookmark.user_id == viewer.id)
            .order_by(CommunityBookmark.created_at.desc(), CommunityPost.id)
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return await self._post_reads(viewer, [(r[0], r[1]) for r in rows], token), total

    # ================================================================ 댓글

    def _comment_read(
        self,
        comment: CommunityComment,
        author: Profile,
        viewer: Profile,
        *,
        adopted: bool | None = None,
    ) -> CommentRead:
        return CommentRead(
            id=comment.id,
            post_id=comment.post_id,
            body=comment.body,
            author=AuthorRead(
                display_name=author.display_name, is_anonymous=False, is_me=author.id == viewer.id
            ),
            comment_type=comment.comment_type,
            categories=list(comment.categories),
            adopted=adopted,
            status=comment.status,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
        )

    async def comments(
        self, viewer: Profile, post_id: uuid.UUID, params: PaginationParams
    ) -> tuple[list[CommentRead], int]:
        post = await self._visible_post(viewer, post_id)
        stmt = (
            select(CommunityComment, Profile)
            .join(Profile, Profile.id == CommunityComment.author_id)
            .where(
                CommunityComment.post_id == post.id,
                (CommunityComment.status == CommentStatus.ACTIVE)
                | (
                    (CommunityComment.status == CommentStatus.HIDDEN)
                    & (CommunityComment.author_id == viewer.id)
                ),
            )
            .order_by(CommunityComment.created_at, CommunityComment.id)
        )
        rows, total = await fetch_page(self.session, stmt, params)
        adopted = await self._adopted({c.id for c, _ in rows})
        return [
            self._comment_read(
                c,
                p,
                viewer,
                # 채택 여부는 게시물 작성자와 댓글 작성자에게만
                adopted=(c.id in adopted)
                if viewer.id in (post.author_id, c.author_id)
                and c.comment_type == CommentType.FEEDBACK
                else None,
            )
            for c, p in rows
        ], total

    async def _adopted(self, comment_ids: set[uuid.UUID]) -> set[uuid.UUID]:
        if not comment_ids:
            return set()
        return set(
            (
                await self.session.execute(
                    select(FeedbackNote.community_comment_id).where(
                        FeedbackNote.community_comment_id.in_(comment_ids)
                    )
                )
            ).scalars()
        )

    async def add_comment(
        self, viewer: Profile, post_id: uuid.UUID, data: CommentCreate
    ) -> CommentRead:
        post = await self._visible_post(viewer, post_id, lock=True)
        await self._rate_limit(
            CommunityComment,
            CommunityComment.author_id,
            viewer.id,
            self.settings.community_comments_per_10min,
            timedelta(minutes=10),
        )
        comment = CommunityComment(
            id=uuid.uuid4(),
            post_id=post.id,
            author_id=viewer.id,
            body=data.body,
            comment_type=data.comment_type,
            categories=[c.value for c in data.categories],
            status=CommentStatus.ACTIVE,
        )
        self.session.add(comment)
        post.comment_count += 1
        await self.session.commit()
        await self.session.refresh(comment)
        return self._comment_read(comment, viewer, viewer)

    async def _own_comment(self, viewer: Profile, comment_id: uuid.UUID) -> CommunityComment:
        row = (
            await self.session.execute(
                select(CommunityComment, CommunityPost)
                .join(CommunityPost, CommunityPost.id == CommunityComment.post_id)
                .where(
                    CommunityComment.id == comment_id,
                    CommunityComment.status != CommentStatus.DELETED,
                )
                .with_for_update(of=CommunityComment)
            )
        ).first()
        if row is None:
            raise NotFoundError("Comment not found")
        comment = row[0]
        if comment.author_id != viewer.id:
            # 다른 사람 댓글: 볼 수 있는 게시물이면 403, 아니면 존재를 숨김
            await self._visible_post(viewer, comment.post_id)
            raise ForbiddenError("Only the author can change this comment")
        return comment

    async def update_comment(
        self, viewer: Profile, comment_id: uuid.UUID, data: CommentUpdate
    ) -> CommentRead:
        comment = await self._own_comment(viewer, comment_id)
        comment.body = data.body
        if data.comment_type is not None:
            comment.comment_type = data.comment_type
        if data.categories is not None:
            comment.categories = sorted({c.value for c in data.categories})
        if comment.comment_type != CommentType.FEEDBACK and comment.categories:
            raise UnprocessableError("categories are only for FEEDBACK comments")
        await self.session.commit()
        await self.session.refresh(comment)
        return self._comment_read(comment, viewer, viewer)

    async def delete_comment(self, viewer: Profile, comment_id: uuid.UUID) -> None:
        comment = await self._own_comment(viewer, comment_id)
        await self._remove_comment(comment, CommentStatus.DELETED)
        await self.session.commit()

    async def _remove_comment(self, comment: CommunityComment, status: CommentStatus) -> None:
        was_active = comment.status == CommentStatus.ACTIVE
        comment.status = status
        if status == CommentStatus.DELETED:
            comment.deleted_at = clock.utc_now()
        else:
            comment.hidden_at = clock.utc_now()
        if was_active:
            await self.session.execute(
                update(CommunityPost)
                .where(CommunityPost.id == comment.post_id)
                .values(comment_count=func.greatest(CommunityPost.comment_count - 1, 0))
            )

    # ================================================================ v0.9 피드백 채택

    async def adopt_comment(
        self, viewer: Profile, comment_id: uuid.UUID, data: CommentAdopt
    ) -> FeedbackNoteRead:
        """게시물 작성자가 작품 피드백 댓글을 자기 첨삭 기록(출처 PEER)으로 채택한다.

        채택하기 전에는 성장 분석에 쓰지 않는다. 채택해도 출처가 PEER라 강사 첨삭과 구분되고,
        반복 약점 통계에는 들어가지 않는다 (참고 통계만). 원문 사본을 저장하므로 댓글이 나중에
        지워져도 학생의 기록은 남는다.
        """
        row = (
            await self.session.execute(
                select(CommunityComment, CommunityPost)
                .join(CommunityPost, CommunityPost.id == CommunityComment.post_id)
                .where(
                    CommunityComment.id == comment_id,
                    CommunityComment.status == CommentStatus.ACTIVE,
                    CommunityPost.status != PostStatus.DELETED,
                )
            )
        ).first()
        if row is None:
            raise NotFoundError("Comment not found")
        comment, post = row
        if post.author_id != viewer.id:
            await self._visible_post(viewer, post.id)
            raise ForbiddenError("Only the post author can adopt feedback")
        if comment.author_id == viewer.id:
            raise UnprocessableError("You cannot adopt your own comment")
        if comment.comment_type != CommentType.FEEDBACK:
            raise ConflictError(
                "Only FEEDBACK comments can be adopted", code=ErrorCode.COMMENT_NOT_FEEDBACK
            )
        if await self._adopted({comment.id}):
            raise ConflictError(
                "This comment is already adopted", code=ErrorCode.COMMENT_ALREADY_ADOPTED
            )
        notes = FeedbackNoteService(self.session, self.settings)
        try:
            return await notes.create(
                viewer,
                post.artwork_id,
                FeedbackNoteCreate(
                    source=FeedbackSource.PEER,
                    body=comment.body,
                    request_summary=data.request_summary,
                ),
                community_comment_id=comment.id,
            )
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(
                "This comment is already adopted", code=ErrorCode.COMMENT_ALREADY_ADOPTED
            ) from None

    # ================================================================ 신고

    async def report(
        self,
        viewer: Profile,
        data: ReportCreate,
        *,
        post_id: uuid.UUID | None = None,
        comment_id: uuid.UUID | None = None,
    ) -> ReportAck:
        if comment_id is not None:
            comment = (
                await self.session.execute(
                    select(CommunityComment).where(
                        CommunityComment.id == comment_id,
                        CommunityComment.status == CommentStatus.ACTIVE,
                    )
                )
            ).scalar_one_or_none()
            if comment is None:
                raise NotFoundError("Comment not found")
            post = await self._visible_post(viewer, comment.post_id)
            owner_id, target = comment.author_id, ReportTarget.COMMENT
        else:
            assert post_id is not None
            post = await self._visible_post(viewer, post_id)
            owner_id, target = post.author_id, ReportTarget.POST
        if owner_id == viewer.id:
            raise UnprocessableError(
                "You cannot report your own content", code=ErrorCode.CANNOT_REPORT_OWN_CONTENT
            )
        await self._rate_limit(
            CommunityReport,
            CommunityReport.reporter_id,
            viewer.id,
            self.settings.community_reports_per_day,
            timedelta(days=1),
        )
        report = CommunityReport(
            id=uuid.uuid4(),
            target_type=target,
            post_id=post.id,
            comment_id=comment_id,
            reporter_id=viewer.id,
            reason=data.reason,
            detail=data.detail,
            status=CommunityReportStatus.OPEN,
        )
        self.session.add(report)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(
                "You already reported this", code=ErrorCode.ALREADY_REPORTED
            ) from None
        await self._auto_hide(target, post.id, comment_id)
        await self.session.commit()
        return ReportAck(
            id=report.id, target_type=target, status=report.status, created_at=report.created_at
        )

    async def _open_reports(
        self, target: ReportTarget, post_id: uuid.UUID, comment_id: uuid.UUID | None
    ) -> int:
        stmt = select(func.count(func.distinct(CommunityReport.reporter_id))).where(
            CommunityReport.status == CommunityReportStatus.OPEN,
            CommunityReport.target_type == target,
        )
        stmt = stmt.where(
            CommunityReport.comment_id == comment_id
            if target == ReportTarget.COMMENT
            else CommunityReport.post_id == post_id
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def _auto_hide(
        self, target: ReportTarget, post_id: uuid.UUID, comment_id: uuid.UUID | None
    ) -> None:
        if (
            await self._open_reports(target, post_id, comment_id)
            < self.settings.community_auto_hide_reports
        ):
            return
        note = (
            f"신고 {self.settings.community_auto_hide_reports}건 누적 자동 숨김 (관리자 검토 대기)"
        )
        if target == ReportTarget.COMMENT:
            comment = await self.session.get(CommunityComment, comment_id, with_for_update=True)
            if comment is not None and comment.status == CommentStatus.ACTIVE:
                await self._remove_comment(comment, CommentStatus.HIDDEN)
                self._log(None, ModerationAction.AUTO_HIDE_COMMENT, post_id, comment_id, None, note)
        else:
            post = await self.session.get(CommunityPost, post_id, with_for_update=True)
            if post is not None and post.status == PostStatus.ACTIVE:
                post.status = PostStatus.HIDDEN
                post.hidden_at = clock.utc_now()
                post.hidden_reason = note
                self._log(None, ModerationAction.AUTO_HIDE_POST, post_id, None, None, note)

    # ================================================================ 관리 (시스템 ADMIN)

    def _log(
        self,
        actor: Profile | None,
        action: ModerationAction,
        post_id: uuid.UUID | None,
        comment_id: uuid.UUID | None,
        report_id: uuid.UUID | None,
        note: str | None,
    ) -> None:
        self.session.add(
            CommunityModerationLog(
                id=uuid.uuid4(),
                actor_id=actor.id if actor else None,
                action=action,
                post_id=post_id,
                comment_id=comment_id,
                report_id=report_id,
                note=note,
            )
        )

    async def admin_reports(
        self,
        params: PaginationParams,
        status: CommunityReportStatus | None,
        target: ReportTarget | None,
    ) -> tuple[list[AdminReportRead], int]:
        stmt = select(CommunityReport)
        if status is not None:
            stmt = stmt.where(CommunityReport.status == status)
        if target is not None:
            stmt = stmt.where(CommunityReport.target_type == target)
        stmt = stmt.order_by(CommunityReport.created_at, CommunityReport.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return [await self._admin_report_read(r[0]) for r in rows], total

    async def _admin_report_read(self, report: CommunityReport) -> AdminReportRead:
        if report.target_type == ReportTarget.COMMENT:
            comment = await self.session.get(CommunityComment, report.comment_id)
            preview, target_status = (
                (comment.body[:80], comment.status.value) if comment else ("", "DELETED")
            )
        else:
            post = await self.session.get(CommunityPost, report.post_id)
            preview, target_status = (post.title, post.status.value) if post else ("", "DELETED")
        return AdminReportRead(
            id=report.id,
            target_type=report.target_type,
            post_id=report.post_id,
            comment_id=report.comment_id,
            reason=report.reason,
            detail=report.detail,
            status=report.status,
            reporter_id=report.reporter_id,
            target_status=target_status,
            target_preview=preview,
            open_report_count=await self._open_reports(
                report.target_type, report.post_id, report.comment_id
            ),
            created_at=report.created_at,
            handled_at=report.handled_at,
            resolution_note=report.resolution_note,
        )

    async def _open_report(self, report_id: uuid.UUID) -> CommunityReport:
        report = (
            await self.session.execute(
                select(CommunityReport).where(CommunityReport.id == report_id).with_for_update()
            )
        ).scalar_one_or_none()
        if report is None:
            raise NotFoundError("Report not found")
        if report.status != CommunityReportStatus.OPEN:
            raise ConflictError(
                "The report is already handled", code=ErrorCode.REPORT_ALREADY_HANDLED
            )
        return report

    async def _close_same_target(
        self,
        report: CommunityReport,
        status: CommunityReportStatus,
        admin: Profile,
        note: str | None,
    ) -> None:
        """같은 대상의 다른 미처리 신고도 함께 처리."""
        target_filter = (
            CommunityReport.comment_id == report.comment_id
            if report.target_type == ReportTarget.COMMENT
            else (CommunityReport.post_id == report.post_id)
            & (CommunityReport.target_type == ReportTarget.POST)
        )
        await self.session.execute(
            update(CommunityReport)
            .where(target_filter, CommunityReport.status == CommunityReportStatus.OPEN)
            .values(
                status=status,
                handled_by=admin.id,
                handled_at=clock.utc_now(),
                resolution_note=note,
                updated_at=func.now(),
            )
        )

    async def resolve_report(
        self, admin: Profile, report_id: uuid.UUID, data: ReportResolve
    ) -> AdminReportRead:
        report = await self._open_report(report_id)
        if data.action == "HIDE":
            if report.target_type == ReportTarget.COMMENT:
                await self._hide_comment(admin, report.comment_id, data.note, report.id)  # type: ignore[arg-type]
            else:
                await self._hide_post(admin, report.post_id, data.note, report.id)
        await self._close_same_target(report, CommunityReportStatus.RESOLVED, admin, data.note)
        self._log(
            admin,
            ModerationAction.RESOLVE_REPORT,
            report.post_id,
            report.comment_id,
            report.id,
            data.note,
        )
        await self.session.commit()
        await self.session.refresh(report)
        return await self._admin_report_read(report)

    async def dismiss_report(
        self, admin: Profile, report_id: uuid.UUID, data: ReportDismiss
    ) -> AdminReportRead:
        report = await self._open_report(report_id)
        await self._close_same_target(report, CommunityReportStatus.DISMISSED, admin, data.note)
        if data.restore:
            # 신고 누적으로 자동 숨김된 대상이면 복구 (관리자가 직접 숨긴 경우는 제외)
            if report.target_type == ReportTarget.COMMENT:
                comment = await self.session.get(
                    CommunityComment, report.comment_id, with_for_update=True
                )
                if (
                    comment is not None
                    and comment.status == CommentStatus.HIDDEN
                    and await self._was_auto_hidden(None, comment.id)
                ):
                    await self._unhide_comment(admin, comment.id, "신고 기각으로 복구", report.id)
            else:
                post = await self.session.get(CommunityPost, report.post_id, with_for_update=True)
                if (
                    post is not None
                    and post.status == PostStatus.HIDDEN
                    and await self._was_auto_hidden(post.id, None)
                ):
                    await self._unhide_post(admin, post.id, "신고 기각으로 복구", report.id)
        self._log(
            admin,
            ModerationAction.DISMISS_REPORT,
            report.post_id,
            report.comment_id,
            report.id,
            data.note,
        )
        await self.session.commit()
        await self.session.refresh(report)
        return await self._admin_report_read(report)

    async def _was_auto_hidden(
        self, post_id: uuid.UUID | None, comment_id: uuid.UUID | None
    ) -> bool:
        stmt = (
            select(CommunityModerationLog.action)
            .order_by(CommunityModerationLog.created_at.desc())
            .limit(1)
        )
        if comment_id is not None:
            stmt = stmt.where(
                CommunityModerationLog.comment_id == comment_id,
                CommunityModerationLog.action.in_(
                    [ModerationAction.AUTO_HIDE_COMMENT, ModerationAction.HIDE_COMMENT]
                ),
            )
            return (
                await self.session.execute(stmt)
            ).scalar_one_or_none() == ModerationAction.AUTO_HIDE_COMMENT
        stmt = stmt.where(
            CommunityModerationLog.post_id == post_id,
            CommunityModerationLog.comment_id.is_(None),
            CommunityModerationLog.action.in_(
                [ModerationAction.AUTO_HIDE_POST, ModerationAction.HIDE_POST]
            ),
        )
        return (
            await self.session.execute(stmt)
        ).scalar_one_or_none() == ModerationAction.AUTO_HIDE_POST

    async def _hide_post(
        self,
        admin: Profile,
        post_id: uuid.UUID,
        reason: str | None,
        report_id: uuid.UUID | None = None,
    ) -> None:
        post = await self.session.get(CommunityPost, post_id, with_for_update=True)
        if post is None or post.status == PostStatus.DELETED:
            raise NotFoundError("Post not found")
        post.status = PostStatus.HIDDEN
        post.hidden_at = clock.utc_now()
        post.hidden_reason = reason or "관리자 숨김"
        self._log(admin, ModerationAction.HIDE_POST, post.id, None, report_id, reason)

    async def _unhide_post(
        self,
        admin: Profile,
        post_id: uuid.UUID,
        reason: str | None,
        report_id: uuid.UUID | None = None,
    ) -> None:
        post = await self.session.get(CommunityPost, post_id, with_for_update=True)
        if post is None or post.status != PostStatus.HIDDEN:
            raise ConflictError("The post is not hidden")
        post.status = PostStatus.ACTIVE
        post.hidden_at = None
        post.hidden_reason = None
        self._log(admin, ModerationAction.UNHIDE_POST, post.id, None, report_id, reason)

    async def _hide_comment(
        self,
        admin: Profile,
        comment_id: uuid.UUID,
        reason: str | None,
        report_id: uuid.UUID | None = None,
    ) -> None:
        comment = await self.session.get(CommunityComment, comment_id, with_for_update=True)
        if comment is None or comment.status == CommentStatus.DELETED:
            raise NotFoundError("Comment not found")
        if comment.status == CommentStatus.ACTIVE:
            await self._remove_comment(comment, CommentStatus.HIDDEN)
        self._log(
            admin, ModerationAction.HIDE_COMMENT, comment.post_id, comment.id, report_id, reason
        )

    async def _unhide_comment(
        self,
        admin: Profile,
        comment_id: uuid.UUID,
        reason: str | None,
        report_id: uuid.UUID | None = None,
    ) -> None:
        comment = await self.session.get(CommunityComment, comment_id, with_for_update=True)
        if comment is None or comment.status != CommentStatus.HIDDEN:
            raise ConflictError("The comment is not hidden")
        comment.status = CommentStatus.ACTIVE
        comment.hidden_at = None
        await self.session.execute(
            update(CommunityPost)
            .where(CommunityPost.id == comment.post_id)
            .values(comment_count=CommunityPost.comment_count + 1)
        )
        self._log(
            admin, ModerationAction.UNHIDE_COMMENT, comment.post_id, comment.id, report_id, reason
        )

    async def moderate(
        self, admin: Profile, action: ModerationAction, target_id: uuid.UUID, reason: str | None
    ) -> None:
        handler = {
            ModerationAction.HIDE_POST: self._hide_post,
            ModerationAction.UNHIDE_POST: self._unhide_post,
            ModerationAction.HIDE_COMMENT: self._hide_comment,
            ModerationAction.UNHIDE_COMMENT: self._unhide_comment,
        }[action]
        await handler(admin, target_id, reason)
        await self.session.commit()

    async def moderation_logs(
        self, params: PaginationParams
    ) -> tuple[list[ModerationLogRead], int]:
        stmt = (
            select(CommunityModerationLog, Profile.display_name)
            .outerjoin(Profile, Profile.id == CommunityModerationLog.actor_id)
            .order_by(CommunityModerationLog.created_at.desc(), CommunityModerationLog.id)
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [
            ModerationLogRead(
                id=log.id,
                actor_name=name,
                action=log.action,
                post_id=log.post_id,
                comment_id=log.comment_id,
                report_id=log.report_id,
                note=log.note,
                created_at=log.created_at,
            )
            for log, name in rows
        ], total
