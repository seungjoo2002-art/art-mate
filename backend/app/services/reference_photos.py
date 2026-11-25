"""v1.1 원본 제시물 사진: 업로드 요청 → 브라우저가 Storage에 직접 업로드 → 완료(실제 이미지 검증).

작품 사진(ArtworkService)과 같은 안전 규칙을 따른다.
- 경로는 서버가 만든다: `{owner}/{artwork}/ref-{id}.{ext}`
  (같은 비공개 버킷, 기존 사진 경로 변경 없음)
- 완료 시 Storage에서 받아 형식·크기·픽셀 수를 검증하고, 같은 작품의 같은 파일은 막는다
- 삭제·교체·만료는 DB를 먼저 DELETED로 커밋하고 Storage 파일은 나중에 정리한다(실패하면 다음 기회)
- 학생 본인 작품만 (다른 학생은 404).
  완료한 작품에도 추가·삭제할 수 있다 (작업 기록이 아닌 참고 자료)
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
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
from app.integrations.supabase.storage import (
    StorageClient,
    StorageError,
    StorageObjectNotFound,
    StorageObjectTooLarge,
)
from app.models.artwork import Artwork, ArtworkReferencePhoto
from app.models.enums import PhotoStatus
from app.models.profile import Profile
from app.schemas.artworks import UploadTarget
from app.schemas.reference_photos import (
    ReferencePhotoList,
    ReferencePhotoRead,
    ReferenceUploadRequest,
    ReferenceUploadTicket,
)
from app.services.artworks import ArtworkService
from app.services.images import (
    check_declared_file,
    inspect_image,
    normalize_content_type,
    storage_extension,
)

_LIVE = (PhotoStatus.PENDING, PhotoStatus.ACTIVE)


def reference_read(
    photo: ArtworkReferencePhoto, url: str | None = None, expires: object = None
) -> ReferencePhotoRead:
    return ReferencePhotoRead(
        id=photo.id,
        artwork_id=photo.artwork_id,
        position=photo.position,
        status=photo.status,
        content_type=photo.content_type,
        size_bytes=photo.size_bytes,
        width=photo.width,
        height=photo.height,
        uploaded_at=photo.uploaded_at,
        created_at=photo.created_at,
        url=url,
        url_expires_at=expires,  # type: ignore[arg-type]
    )


class ReferencePhotoService:
    def __init__(
        self, session: AsyncSession, settings: Settings, storage: StorageClient | None = None
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.artworks = ArtworkService(session, settings, storage)

    def _require_storage(self) -> StorageClient:
        if self.storage is None:
            raise StorageNotConfiguredError()
        return self.storage

    async def _photo(
        self, artwork_id: uuid.UUID, photo_id: uuid.UUID, *, for_update: bool = False
    ) -> ArtworkReferencePhoto:
        stmt = select(ArtworkReferencePhoto).where(
            ArtworkReferencePhoto.id == photo_id,
            ArtworkReferencePhoto.artwork_id == artwork_id,
            ArtworkReferencePhoto.status != PhotoStatus.DELETED,
        )
        if for_update:
            stmt = stmt.with_for_update()
        photo = (await self.session.execute(stmt)).scalar_one_or_none()
        if photo is None:
            raise NotFoundError("Reference photo not found")
        return photo

    async def active(self, artwork_id: uuid.UUID) -> list[ArtworkReferencePhoto]:
        return list(
            (
                await self.session.execute(
                    select(ArtworkReferencePhoto)
                    .where(
                        ArtworkReferencePhoto.artwork_id == artwork_id,
                        ArtworkReferencePhoto.status == PhotoStatus.ACTIVE,
                    )
                    .order_by(ArtworkReferencePhoto.position, ArtworkReferencePhoto.uploaded_at)
                )
            ).scalars()
        )

    async def _expire_pending(self, artwork_id: uuid.UUID) -> None:
        now = clock.utc_now()
        await self.session.execute(
            update(ArtworkReferencePhoto)
            .where(
                ArtworkReferencePhoto.artwork_id == artwork_id,
                ArtworkReferencePhoto.status == PhotoStatus.PENDING,
                ArtworkReferencePhoto.upload_expires_at <= now,
            )
            .values(
                status=PhotoStatus.DELETED,
                deleted_at=now,
                storage_cleanup_pending=True,
                updated_at=func.now(),
            )
        )

    async def _discard(self, owner: Profile, photo: ArtworkReferencePhoto, token: str) -> None:
        photo.status = PhotoStatus.DELETED
        photo.deleted_at = clock.utc_now()
        photo.storage_cleanup_pending = True
        await self.session.commit()
        await self.artworks.cleanup_storage(owner, token)

    # ------------------------------------------------------------------ 조회

    async def list(
        self, owner: Profile, artwork_id: uuid.UUID, token: str, *, include_urls: bool
    ) -> ReferencePhotoList:
        artwork = await self.artworks.owned(owner, artwork_id)
        photos = await self.active(artwork.id)
        urls: dict[str, str] = {}
        expires = None
        if include_urls and photos:
            urls = await self.artworks._sign([p.storage_path for p in photos], token)
            expires = clock.utc_now() + timedelta(seconds=self.settings.storage_signed_url_seconds)
        return ReferencePhotoList(
            items=[reference_read(p, urls.get(p.storage_path), expires) for p in photos],
            max_count=self.settings.artwork_max_reference_photos,
        )

    # ------------------------------------------------------------------ 업로드

    async def request_upload(
        self, owner: Profile, artwork_id: uuid.UUID, data: ReferenceUploadRequest, token: str
    ) -> ReferenceUploadTicket:
        storage = self._require_storage()
        settings = self.settings
        content_type = normalize_content_type(data.content_type)
        check_declared_file(
            content_type,
            data.file_name,
            data.file_size,
            allowed=settings.artwork_allowed_content_types,
            max_bytes=settings.artwork_max_upload_bytes,
        )
        # 작품 행 잠금: 장수 제한·순서 계산을 직렬화
        artwork: Artwork = await self.artworks.owned(owner, artwork_id, for_update=True)
        await self._expire_pending(artwork.id)

        position: int | None = None
        if data.replaces_photo_id is not None:
            target = await self._photo(artwork.id, data.replaces_photo_id)
            if target.status != PhotoStatus.ACTIVE:
                raise ConflictError(
                    "Only uploaded photos can be replaced", code=ErrorCode.PHOTO_NOT_ACTIVE
                )
            position = target.position  # 교체는 같은 자리

        live = (
            await self.session.execute(
                select(func.count()).where(
                    ArtworkReferencePhoto.artwork_id == artwork.id,
                    ArtworkReferencePhoto.status.in_(_LIVE),
                )
            )
        ).scalar_one()
        limit = settings.artwork_max_reference_photos + (1 if data.replaces_photo_id else 0)
        if live >= limit:
            raise ConflictError(
                f"Up to {settings.artwork_max_reference_photos} reference photos per artwork",
                code=ErrorCode.PHOTO_LIMIT_REACHED,
                details={"kind": "REFERENCE", "max": settings.artwork_max_reference_photos},
            )
        if position is None:
            last = (
                await self.session.execute(
                    select(func.max(ArtworkReferencePhoto.position)).where(
                        ArtworkReferencePhoto.artwork_id == artwork.id,
                        ArtworkReferencePhoto.status.in_(_LIVE),
                    )
                )
            ).scalar_one()
            position = 0 if last is None else last + 1

        now = clock.utc_now()
        photo_id = uuid.uuid4()
        # 경로는 서버가 만든다 (사용자 파일명 미사용). 첫 폴더 = 본인 ID → Storage 정책 조건
        path = f"{owner.id}/{artwork.id}/ref-{photo_id}.{storage_extension(content_type)}"
        photo = ArtworkReferencePhoto(
            id=photo_id,
            artwork_id=artwork.id,
            owner_id=owner.id,
            position=position,
            status=PhotoStatus.PENDING,
            storage_path=path,
            content_type=content_type,
            upload_expires_at=now + timedelta(seconds=settings.artwork_upload_ttl_seconds),
            replaces_photo_id=data.replaces_photo_id,
        )
        self.session.add(photo)
        # Storage 정책 함수가 이 행을 확인하므로 URL 발급 전에 커밋한다
        await self.session.commit()
        try:
            signed = await storage.create_upload_url(path, access_token=token)
        except StorageError:
            await self.session.delete(photo)
            await self.session.commit()
            raise StorageUnavailableError() from None
        await self.session.refresh(photo)
        await self.artworks.cleanup_storage(owner, token)
        return ReferenceUploadTicket(
            photo=reference_read(photo),
            upload=UploadTarget(
                bucket=storage.bucket,
                path=path,
                url=signed.url,
                token=signed.token,
                expires_at=photo.upload_expires_at,
            ),
        )

    async def complete_upload(
        self, owner: Profile, artwork_id: uuid.UUID, photo_id: uuid.UUID, token: str
    ) -> ReferencePhotoRead:
        storage = self._require_storage()
        settings = self.settings
        artwork = await self.artworks.owned(owner, artwork_id, for_update=True)
        photo = await self._photo(artwork.id, photo_id, for_update=True)
        if photo.status == PhotoStatus.ACTIVE:
            return reference_read(photo)  # 재시도·중복 호출: 같은 결과 (멱등)

        if photo.upload_expires_at <= clock.utc_now():
            await self._discard(owner, photo, token)
            raise ConflictError(
                "The upload has expired; request a new one", code=ErrorCode.UPLOAD_EXPIRED
            )
        try:
            data = await storage.download(
                photo.storage_path, access_token=token, max_bytes=settings.artwork_max_upload_bytes
            )
        except StorageObjectNotFound:
            await self.session.rollback()
            raise ConflictError(
                "The file has not been uploaded yet", code=ErrorCode.UPLOAD_NOT_FOUND
            ) from None
        except StorageObjectTooLarge:
            await self._discard(owner, photo, token)
            raise UnprocessableError(
                "The uploaded file is too large", code=ErrorCode.FILE_TOO_LARGE
            ) from None
        except StorageError:
            await self.session.rollback()
            raise StorageUnavailableError() from None

        try:
            info = inspect_image(
                data,
                declared_type=photo.content_type,
                allowed=settings.artwork_allowed_content_types,
                max_bytes=settings.artwork_max_upload_bytes,
                max_pixels=settings.artwork_max_image_pixels,
            )
        except UnprocessableError:
            await self._discard(owner, photo, token)
            raise

        duplicate = (
            await self.session.execute(
                select(ArtworkReferencePhoto.id).where(
                    ArtworkReferencePhoto.artwork_id == artwork.id,
                    ArtworkReferencePhoto.status == PhotoStatus.ACTIVE,
                    ArtworkReferencePhoto.sha256 == info.sha256,
                    ArtworkReferencePhoto.id != photo.replaces_photo_id,
                )
            )
        ).first()
        if duplicate is not None:
            await self._discard(owner, photo, token)
            raise ConflictError(
                "The same image is already a reference photo of this artwork",
                code=ErrorCode.DUPLICATE_PHOTO,
                details={"photo_id": str(duplicate[0])},
            )

        now = clock.utc_now()
        replaced = False
        if photo.replaces_photo_id is not None:
            old = (
                await self.session.execute(
                    select(ArtworkReferencePhoto)
                    .where(ArtworkReferencePhoto.id == photo.replaces_photo_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if old is not None and old.status == PhotoStatus.ACTIVE:
                old.status = PhotoStatus.DELETED
                old.deleted_at = now
                old.storage_cleanup_pending = True
                replaced = True
                await self.session.flush()
        photo.status = PhotoStatus.ACTIVE
        photo.uploaded_at = now
        photo.size_bytes = info.size_bytes
        photo.width = info.width
        photo.height = info.height
        photo.sha256 = info.sha256
        await self.session.commit()
        await self.session.refresh(photo)
        if replaced:
            await self.artworks.cleanup_storage(owner, token)
        return reference_read(photo)

    # ------------------------------------------------------------------ 삭제

    async def delete(
        self, owner: Profile, artwork_id: uuid.UUID, photo_id: uuid.UUID, token: str
    ) -> None:
        artwork = await self.artworks.owned(owner, artwork_id, for_update=True)
        photo = await self._photo(artwork.id, photo_id, for_update=True)
        await self._discard(owner, photo, token)
