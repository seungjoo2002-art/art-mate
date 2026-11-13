"""작품 공유 동의와 공유용 파생 이미지 (v0.8).

- 목적별 동의: COMMUNITY(커뮤니티 게시) / REFERENCE(F-15 참고작 활용). 서로 독립적으로 동의·철회.
- 공개 범위: ACADEMY(작품이 연결된 학원의 ACTIVE 멤버) / PLATFORM(로그인 사용자 전체). 작성자 표시:
  NAME / ANONYMOUS. 범위·표시를 바꾸면 기존 동의를 철회(CHANGED)하고 새 동의를 남긴다 (이력 보존).
- 원본 보호: 원본 사진(artworks 버킷)의 URL은 공유 화면에 절대 내보내지 않는다. 동의할 때 서버가
  FINAL
  대표 사진을 내려받아 파생 이미지(긴 변 축소, EXIF 제거, JPEG 재인코딩)를 만들고 shared-artworks
  비공개 버킷에 올린다. 보는 사람에게는 그 사람의 토큰으로 발급한 짧은 Signed URL만 준다
  (Storage RLS `can_access_shared_image`가 동의 범위를 다시 확인).
- 철회 정리:
  - COMMUNITY 철회 → 그 작품의 게시물 DELETED (좋아요·저장·댓글은 게시물과 함께 보이지 않음)
  - REFERENCE 철회 → 그 작품을 가리키는 학생별 참고작 추천(저장 포함) 행 삭제
  - 남은 유효 동의가 없으면 파생 이미지 DELETED + Storage 파일 삭제 (실패하면 다음 요청에 재시도)
  - 작품 삭제 시 모든 동의를 ARTWORK_DELETED로 철회하고 같은 정리를 한다.
- 조회 쪽은 항상 '현재 유효한 동의'를 조인한다 → 정리 전이라도 철회 즉시 보이지 않는다.
"""

from __future__ import annotations

import io
import logging
import uuid
from datetime import timedelta
from typing import Any

from PIL import Image, ImageOps
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    StorageNotConfiguredError,
    StorageUnavailableError,
    UnprocessableError,
)
from app.integrations.supabase.storage import StorageClient, StorageError
from app.models.artwork import Artwork, ArtworkPhoto
from app.models.community import (
    ArtworkSharingConsent,
    CommunityPost,
    ReferenceRecommendation,
    SharedArtworkImage,
)
from app.models.enums import (
    ArtworkStage,
    AuthorDisplay,
    ConsentGrantor,
    MembershipRole,
    MembershipStatus,
    PhotoStatus,
    PostStatus,
    SharedImageKind,
    SharedImageStatus,
    SharingPurpose,
    SharingScope,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.schemas.community import (
    ImageRead,
    SharingConsentRead,
    SharingGrant,
    SharingStatus,
)
from app.services.artwork_stages import visible_stage_photo

logger = logging.getLogger(__name__)

ANONYMOUS_NAME = "익명 학생"
CLEANUP_BATCH = 50


def derive_shared_image(data: bytes, *, max_px: int, quality: int) -> tuple[bytes, int, int]:
    """원본에서 공유용 이미지를 만든다.

    회전 보정 → RGB → 긴 변 max_px → JPEG (EXIF·메타데이터 없음).
    """
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    image.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(
        out, format="JPEG", quality=quality, optimize=True
    )  # exif 인자 없음 → 메타데이터 제거
    return out.getvalue(), image.width, image.height


def member_academies(user_id: uuid.UUID) -> Any:
    return select(AcademyMembership.academy_id).where(
        AcademyMembership.user_id == user_id,
        AcademyMembership.status == MembershipStatus.ACTIVE,
    )


def visible_consent(
    viewer_id: uuid.UUID, purpose: SharingPurpose, *, include_own: bool = True
) -> Any:
    """viewer가 볼 수 있는 유효 동의 조건 (ArtworkSharingConsent에 적용)."""
    c = ArtworkSharingConsent
    reach = [
        c.scope == SharingScope.PLATFORM,
        and_(c.scope == SharingScope.ACADEMY, c.academy_id.in_(member_academies(viewer_id))),
    ]
    if include_own:
        reach.append(c.owner_id == viewer_id)
    return and_(c.revoked_at.is_(None), c.purpose == purpose, or_(*reach))


def author_name(profile: Profile, display: AuthorDisplay, viewer_id: uuid.UUID) -> str:
    if display == AuthorDisplay.NAME or profile.id == viewer_id:
        return profile.display_name
    return ANONYMOUS_NAME


async def sign_images(
    storage: StorageClient | None,
    settings: Settings,
    images: list[SharedArtworkImage],
    token: str,
) -> dict[uuid.UUID, ImageRead]:
    """보는 사람 토큰으로 파생 이미지 Signed URL (짧은 만료). 실패해도 목록은 이미지 없이 반환."""
    live = [i for i in images if i.status == SharedImageStatus.ACTIVE]
    if not live:
        return {}
    urls: dict[str, str] = {}
    if storage is not None:
        try:
            urls = await storage.create_signed_urls(
                [i.storage_path for i in live],
                access_token=token,
                expires_in=settings.storage_signed_url_seconds,
            )
        except StorageError:
            logger.warning("shared image signing failed", extra={"count": len(live)})
    expires = clock.utc_now() + timedelta(seconds=settings.storage_signed_url_seconds)
    return {
        i.id: ImageRead(
            image_id=i.id,
            url=urls.get(i.storage_path),
            url_expires_at=expires if i.storage_path in urls else None,
            width=i.width or 0,
            height=i.height or 0,
        )
        for i in live
    }


def consent_read(c: ArtworkSharingConsent) -> SharingConsentRead:
    return SharingConsentRead(
        id=c.id,
        purpose=c.purpose,
        scope=c.scope,
        academy_id=c.academy_id,
        author_display=c.author_display,
        policy_version=c.policy_version,
        granted_by=c.granted_by,
        granted_at=c.granted_at,
        revoked_at=c.revoked_at,
        revoked_reason=c.revoked_reason,
    )


async def withdraw_artwork_sharing(
    session: AsyncSession,
    artwork_id: uuid.UUID,
    purposes: list[SharingPurpose],
    reason: str,
) -> None:
    """동의 철회와 공개 데이터 정리 (호출자가 commit, Storage 정리는 cleanup_storage)."""
    now = clock.utc_now()
    await session.execute(
        update(ArtworkSharingConsent)
        .where(
            ArtworkSharingConsent.artwork_id == artwork_id,
            ArtworkSharingConsent.purpose.in_(purposes),
            ArtworkSharingConsent.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoked_reason=reason, updated_at=func.now())
    )
    if SharingPurpose.COMMUNITY in purposes:
        await session.execute(
            update(CommunityPost)
            .where(
                CommunityPost.artwork_id == artwork_id, CommunityPost.status != PostStatus.DELETED
            )
            .values(status=PostStatus.DELETED, deleted_at=now, updated_at=func.now())
        )
        # VER.2: 게시물용으로 고른 사진의 공유 이미지는 커뮤니티 철회와 함께 삭제
        await retire_post_images(session, SharedArtworkImage.artwork_id == artwork_id)
    if SharingPurpose.REFERENCE in purposes:
        await session.execute(
            delete(ReferenceRecommendation).where(
                ReferenceRecommendation.reference_artwork_id == artwork_id
            )
        )
    remaining = (
        await session.execute(
            select(func.count()).where(
                ArtworkSharingConsent.artwork_id == artwork_id,
                ArtworkSharingConsent.revoked_at.is_(None),
            )
        )
    ).scalar_one()
    if remaining == 0:
        await session.execute(
            update(SharedArtworkImage)
            .where(
                SharedArtworkImage.artwork_id == artwork_id,
                SharedArtworkImage.status != SharedImageStatus.DELETED,
            )
            .values(
                status=SharedImageStatus.DELETED,
                deleted_at=now,
                storage_cleanup_pending=True,
                updated_at=func.now(),
            )
        )


async def retire_post_images(session: AsyncSession, condition: Any) -> int:
    """게시물용(POST) 공유 이미지 삭제 처리 (파일은 cleanup_storage가 정리). 호출자가 commit.

    원본 사진이 지워지거나 교체됐을 때, 게시물을 지웠을 때, 커뮤니티 공유를 철회했을 때 쓴다.
    그 이미지를 쓰던 게시물은 남고 이미지만 사라진다 (작성자가 다른 사진을 다시 고를 수 있음).
    """
    retired = list(
        (
            await session.execute(
                update(SharedArtworkImage)
                .where(
                    condition,
                    SharedArtworkImage.kind == SharedImageKind.POST,
                    SharedArtworkImage.status != SharedImageStatus.DELETED,
                )
                .values(
                    status=SharedImageStatus.DELETED,
                    deleted_at=clock.utc_now(),
                    storage_cleanup_pending=True,
                    updated_at=func.now(),
                )
                .returning(SharedArtworkImage.id)
            )
        ).scalars()
    )
    if retired:
        await session.execute(
            update(CommunityPost)
            .where(CommunityPost.image_id.in_(retired))
            .values(image_id=None, photo_id=None, updated_at=func.now())
        )
    return len(retired)


class SharingService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        photo_storage: StorageClient | None = None,
        shared_storage: StorageClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.photo_storage = photo_storage
        self.shared_storage = shared_storage

    async def _artwork(
        self, owner: Profile, artwork_id: uuid.UUID, *, lock: bool = False
    ) -> Artwork:
        stmt = select(Artwork).where(
            Artwork.id == artwork_id, Artwork.owner_id == owner.id, Artwork.deleted_at.is_(None)
        )
        if lock:
            stmt = stmt.with_for_update()
        artwork = (await self.session.execute(stmt)).scalar_one_or_none()
        if artwork is None:
            raise NotFoundError("Artwork not found")
        return artwork

    async def _consents(self, artwork_id: uuid.UUID) -> dict[SharingPurpose, ArtworkSharingConsent]:
        rows = (
            await self.session.execute(
                select(ArtworkSharingConsent).where(
                    ArtworkSharingConsent.artwork_id == artwork_id,
                    ArtworkSharingConsent.revoked_at.is_(None),
                )
            )
        ).scalars()
        return {c.purpose: c for c in rows}

    async def live_image(self, artwork_id: uuid.UUID) -> SharedArtworkImage | None:
        """작품 대표(PRIMARY) 공유 이미지."""
        return (
            await self.session.execute(
                select(SharedArtworkImage).where(
                    SharedArtworkImage.artwork_id == artwork_id,
                    SharedArtworkImage.kind == SharedImageKind.PRIMARY,
                    SharedArtworkImage.status == SharedImageStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()

    async def status(self, owner: Profile, artwork_id: uuid.UUID, token: str) -> SharingStatus:
        artwork = await self._artwork(owner, artwork_id)
        consents = await self._consents(artwork.id)
        image = await self.live_image(artwork.id)
        images = await sign_images(
            self.shared_storage, self.settings, [image] if image else [], token
        )
        post_id = (
            await self.session.execute(
                select(CommunityPost.id).where(
                    CommunityPost.artwork_id == artwork.id,
                    CommunityPost.status != PostStatus.DELETED,
                )
            )
        ).scalar_one_or_none()
        return SharingStatus(
            artwork_id=artwork.id,
            required_version=self.settings.sharing_consent_version,
            community=consent_read(consents[SharingPurpose.COMMUNITY])
            if SharingPurpose.COMMUNITY in consents
            else None,
            reference=consent_read(consents[SharingPurpose.REFERENCE])
            if SharingPurpose.REFERENCE in consents
            else None,
            image=images.get(image.id) if image else None,
            post_id=post_id,
        )

    async def history(self, owner: Profile, artwork_id: uuid.UUID) -> list[SharingConsentRead]:
        artwork = await self._artwork(owner, artwork_id)
        rows = (
            await self.session.execute(
                select(ArtworkSharingConsent)
                .where(ArtworkSharingConsent.artwork_id == artwork.id)
                .order_by(ArtworkSharingConsent.granted_at, ArtworkSharingConsent.id)
            )
        ).scalars()
        return [consent_read(c) for c in rows]

    async def _source_photo(self, artwork: Artwork) -> ArtworkPhoto:
        photo = await self._final_photo(artwork)
        if photo is None:
            raise ConflictError(
                "Upload a FINAL stage photo before sharing", code=ErrorCode.FINAL_PHOTO_REQUIRED
            )
        return photo

    async def _final_photo(self, artwork: Artwork) -> ArtworkPhoto | None:
        return (
            await self.session.execute(
                select(ArtworkPhoto).where(
                    ArtworkPhoto.artwork_id == artwork.id,
                    ArtworkPhoto.stage == ArtworkStage.FINAL,
                    ArtworkPhoto.status == PhotoStatus.ACTIVE,
                    ArtworkPhoto.is_representative,
                    visible_stage_photo(),
                )
            )
        ).scalar_one_or_none()

    async def _live_post_image(
        self, artwork_id: uuid.UUID, photo_id: uuid.UUID
    ) -> SharedArtworkImage | None:
        return (
            await self.session.execute(
                select(SharedArtworkImage).where(
                    SharedArtworkImage.artwork_id == artwork_id,
                    SharedArtworkImage.source_photo_id == photo_id,
                    SharedArtworkImage.kind == SharedImageKind.POST,
                    SharedArtworkImage.status == SharedImageStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()

    async def ensure_post_image(
        self, owner: Profile, artwork: Artwork, photo_id: uuid.UUID, token: str
    ) -> SharedArtworkImage:
        """게시물에 고른 사진(스케치·중간·완성)의 공유 이미지 (VER.2).

        사진은 이 작품의 ACTIVE 사진이어야 한다.
        대표 이미지의 원본과 같으면 대표 이미지를 그대로 쓴다.
        """
        photo = (
            await self.session.execute(
                select(ArtworkPhoto).where(
                    ArtworkPhoto.id == photo_id,
                    ArtworkPhoto.artwork_id == artwork.id,
                    ArtworkPhoto.owner_id == owner.id,
                    ArtworkPhoto.status == PhotoStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if photo is None:
            raise NotFoundError("Photo not found in this artwork")
        primary = await self.live_image(artwork.id)
        if primary is not None and primary.source_photo_id == photo.id:
            return primary
        existing = await self._live_post_image(artwork.id, photo.id)
        if existing is not None:
            return existing
        return await self._create_image(owner, artwork, photo, SharedImageKind.POST, token)

    async def _ensure_image(
        self, owner: Profile, artwork: Artwork, token: str
    ) -> SharedArtworkImage:
        existing = await self.live_image(artwork.id)
        if existing is not None:
            return existing
        photo = await self._source_photo(artwork)
        return await self._create_image(owner, artwork, photo, SharedImageKind.PRIMARY, token)

    async def _create_image(
        self,
        owner: Profile,
        artwork: Artwork,
        photo: ArtworkPhoto,
        kind: SharedImageKind,
        token: str,
    ) -> SharedArtworkImage:
        """원본 사진 → 파생 이미지 (축소·메타데이터 제거) → 공유 버킷. 커밋한다."""
        if self.photo_storage is None or self.shared_storage is None:
            raise StorageNotConfiguredError()
        image_id = uuid.uuid4()
        image = SharedArtworkImage(
            id=image_id,
            artwork_id=artwork.id,
            owner_id=owner.id,
            source_photo_id=photo.id,
            kind=kind,
            status=SharedImageStatus.PENDING,
            # 경로에 사용자·작품 ID를 넣지 않는다 (익명 공개 시 URL로 작성자를 알 수 없도록)
            storage_path=f"{uuid.uuid4().hex}/{image_id.hex}.jpg",
        )
        self.session.add(image)
        try:
            await self.session.commit()  # Storage 정책이 이미지 행을 확인하므로 업로드 전에 커밋
        except IntegrityError:
            await self.session.rollback()  # 동시 공유: 다른 요청이 만드는 중
            raise ConflictError("The shared image is being prepared; try again") from None
        try:
            original = await self.photo_storage.download(
                photo.storage_path,
                access_token=token,
                max_bytes=self.settings.artwork_max_upload_bytes,
            )
            data, width, height = derive_shared_image(
                original,
                max_px=self.settings.shared_image_max_px,
                quality=self.settings.shared_image_quality,
            )
            del original
            await self.shared_storage.upload(
                image.storage_path, data, content_type="image/jpeg", access_token=token
            )
        except (StorageError, OSError) as exc:
            image.status = SharedImageStatus.DELETED
            image.deleted_at = clock.utc_now()
            image.storage_cleanup_pending = True
            await self.session.commit()
            logger.warning("shared image creation failed", extra={"error_type": type(exc).__name__})
            raise StorageUnavailableError() from None
        image.status = SharedImageStatus.ACTIVE
        image.width, image.height, image.size_bytes = width, height, len(data)
        await self.session.flush()
        return image

    async def grant(
        self,
        owner: Profile,
        artwork_id: uuid.UUID,
        purpose: SharingPurpose,
        data: SharingGrant,
        token: str,
    ) -> SharingStatus:
        required = self.settings.sharing_consent_version
        if data.policy_version != required:
            raise UnprocessableError(
                "Please agree to the current sharing consent version",
                details={"required_version": required},
            )
        artwork = await self._artwork(owner, artwork_id)
        academy_id = None
        if data.scope == SharingScope.ACADEMY:
            if artwork.academy_id is None:
                raise UnprocessableError(
                    "Academy sharing needs an artwork linked to an academy",
                    code=ErrorCode.SHARING_SCOPE_INVALID,
                )
            member = (
                await self.session.execute(
                    select(AcademyMembership.id).where(
                        AcademyMembership.academy_id == artwork.academy_id,
                        AcademyMembership.user_id == owner.id,
                        AcademyMembership.role == MembershipRole.STUDENT,
                        AcademyMembership.status == MembershipStatus.ACTIVE,
                    )
                )
            ).first()
            if member is None:
                raise UnprocessableError(
                    "You are no longer a member of this academy",
                    code=ErrorCode.SHARING_SCOPE_INVALID,
                )
            academy_id = artwork.academy_id
        # 공유 가능 조건을 이미지 작업 전에 확인. 참고작은 완성(FINAL) 대표 사진 필수.
        # 커뮤니티는 VER.2부터 사진 아무거나 1장 이상이면 동의 가능 (게시물에서 사진을 고름)
        final = await self._final_photo(artwork)
        if purpose == SharingPurpose.REFERENCE or final is not None:
            await self._source_photo(artwork)
            await self._ensure_image(owner, artwork, token)
        else:
            any_photo = (
                await self.session.execute(
                    select(ArtworkPhoto.id).where(
                        ArtworkPhoto.artwork_id == artwork.id,
                        ArtworkPhoto.status == PhotoStatus.ACTIVE,
                    )
                )
            ).first()
            if any_photo is None:
                raise ConflictError(
                    "Upload a photo before sharing", code=ErrorCode.FINAL_PHOTO_REQUIRED
                )

        artwork = await self._artwork(owner, artwork_id, lock=True)  # 동의 변경 직렬화
        current = (await self._consents(artwork.id)).get(purpose)
        same = current is not None and (
            current.scope,
            current.academy_id,
            current.author_display,
            current.policy_version,
            current.granted_by,
        ) == (data.scope, academy_id, data.author_display, data.policy_version, data.granted_by)
        if not same:
            now = clock.utc_now()
            if current is not None:
                current.revoked_at = now
                current.revoked_reason = "CHANGED"
                await self.session.flush()
            self.session.add(
                ArtworkSharingConsent(
                    id=uuid.uuid4(),
                    artwork_id=artwork.id,
                    owner_id=owner.id,
                    purpose=purpose,
                    scope=data.scope,
                    academy_id=academy_id,
                    author_display=data.author_display,
                    policy_version=data.policy_version,
                    granted_by=ConsentGrantor(data.granted_by),
                    granted_at=now,
                )
            )
        await self.session.commit()
        return await self.status(owner, artwork.id, token)

    async def revoke(
        self, owner: Profile, artwork_id: uuid.UUID, purpose: SharingPurpose, token: str
    ) -> SharingStatus:
        artwork = await self._artwork(owner, artwork_id, lock=True)
        if purpose not in await self._consents(artwork.id):
            raise NotFoundError("No active sharing consent for this purpose")
        await withdraw_artwork_sharing(self.session, artwork.id, [purpose], "OWNER_REVOKED")
        await self.session.commit()
        await self.cleanup_storage(owner, token)
        return await self.status(owner, artwork.id, token)

    async def cleanup_storage(self, owner: Profile, token: str) -> None:
        """철회된 파생 이미지 파일 삭제 (실패하면 다음 요청에서 재시도)."""
        if self.shared_storage is None:
            return
        rows = (
            await self.session.execute(
                select(SharedArtworkImage.id, SharedArtworkImage.storage_path)
                .where(
                    SharedArtworkImage.owner_id == owner.id,
                    SharedArtworkImage.storage_cleanup_pending,
                )
                .limit(CLEANUP_BATCH)
            )
        ).all()
        if not rows:
            return
        try:
            await self.shared_storage.delete([p for _, p in rows], access_token=token)
        except StorageError:
            logger.warning("shared image cleanup deferred", extra={"count": len(rows)})
            return
        await self.session.execute(
            update(SharedArtworkImage)
            .where(SharedArtworkImage.id.in_([i for i, _ in rows]))
            .values(storage_cleanup_pending=False, updated_at=func.now())
        )
        await self.session.commit()
