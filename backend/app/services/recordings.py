"""피드백 음성 녹음 저장 (F-11)과 녹음 동의.

업로드 흐름은 작품 사진(app/services/artworks.py)과 같다.
1. 업로드 요청: 유효한 녹음 동의 + 강사 고지 확인 + 형식·확장자·크기·길이 1차 검증
   → 녹음 행(PENDING) → 사용자 토큰으로 Signed upload URL (비공개 오디오 버킷)
2. 브라우저가 Storage에 직접 업로드
3. 완료 처리: 파일을 받아 실제 오디오 형식(시그니처) 검증, 내용 해시 중복 확인 → ACTIVE

DB·Storage 일관성, 정리 재시도, 만료 처리 원칙도 사진과 같다.
STT(transcription_status)는 v0.6에서 사용한다. v0.5는 NOT_REQUESTED로만 저장하고
작업을 실행하지 않는다.

권한: 생성·삭제는 작품 소유 학생 본인. 조회·재생은 소유자, 또는 학원 연결 작품의 담당 강사·
학원 관리자. 학생 개인 작품의 녹음은 강사에게 보이지 않는다.
"""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
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
from app.integrations.supabase.storage import (
    StorageClient,
    StorageError,
    StorageObjectNotFound,
    StorageObjectTooLarge,
)
from app.models.enums import ConsentGrantor, ConsentType, RecordingStatus
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.models.recording import FeedbackRecording, RecordingConsent
from app.schemas.artworks import UploadTarget
from app.schemas.recordings import (
    ConsentStatus,
    RecordingConsentCreate,
    RecordingConsentRead,
    RecordingRead,
    RecordingUploadRequest,
    RecordingUploadTicket,
    RecordingUrl,
)
from app.services.artworks import ArtworkService
from app.services.audio import (
    check_declared_audio,
    inspect_audio,
    normalize_content_type,
    storage_extension,
)

logger = logging.getLogger(__name__)

CLEANUP_BATCH = 50
_LIVE = (RecordingStatus.PENDING, RecordingStatus.ACTIVE)


def consent_read(consent: RecordingConsent) -> RecordingConsentRead:
    return RecordingConsentRead(
        id=consent.id,
        consent_type=consent.consent_type,
        policy_version=consent.policy_version,
        granted_by=consent.granted_by,
        granted_at=consent.granted_at,
        revoked_at=consent.revoked_at,
    )


def recording_read(
    recording: FeedbackRecording, url: str | None = None, expires: datetime | None = None
) -> RecordingRead:
    return RecordingRead(
        id=recording.id,
        artwork_id=recording.artwork_id,
        title=recording.title,
        status=recording.status,
        content_type=recording.content_type,
        size_bytes=recording.size_bytes,
        duration_ms=recording.duration_ms,
        recorded_at=recording.recorded_at,
        uploaded_at=recording.uploaded_at,
        created_at=recording.created_at,
        consent_id=recording.consent_id,
        speaker_notice_confirmed=recording.speaker_notice_confirmed,
        transcription_status=recording.transcription_status,
        url=url,
        url_expires_at=expires if url else None,
    )


class RecordingService:
    def __init__(
        self, session: AsyncSession, settings: Settings, storage: StorageClient | None
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.artworks = ArtworkService(session, settings)

    def _require_storage(self) -> StorageClient:
        if self.storage is None:
            raise StorageNotConfiguredError()
        return self.storage

    # ------------------------------------------------------------------ consent

    async def _active_consent(self, user: Profile) -> RecordingConsent | None:
        stmt = select(RecordingConsent).where(
            RecordingConsent.user_id == user.id,
            RecordingConsent.consent_type == ConsentType.VOICE_RECORDING,
            RecordingConsent.revoked_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def consent_status(self, user: Profile) -> ConsentStatus:
        consent = await self._active_consent(user)
        required = self.settings.recording_consent_version
        return ConsentStatus(
            required_version=required,
            is_valid=consent is not None and consent.policy_version == required,
            consent=consent_read(consent) if consent else None,
        )

    async def grant_consent(self, user: Profile, data: RecordingConsentCreate) -> ConsentStatus:
        """현재 버전 동의를 기록한다. 이전 버전 동의는 철회 처리하고 새 행을 남긴다 (이력 보존)."""
        if data.policy_version != self.settings.recording_consent_version:
            raise UnprocessableError(
                "Please agree to the current consent version",
                details={"required_version": self.settings.recording_consent_version},
            )
        current = await self._active_consent(user)
        if (
            current is not None
            and current.policy_version == data.policy_version
            and current.granted_by == data.granted_by
        ):
            return await self.consent_status(user)  # 같은 동의 재요청: 그대로 (멱등)
        now = clock.utc_now()
        if current is not None:
            current.revoked_at = now
            await self.session.flush()
        self.session.add(
            RecordingConsent(
                id=uuid.uuid4(),
                user_id=user.id,
                consent_type=ConsentType.VOICE_RECORDING,
                policy_version=data.policy_version,
                granted_by=ConsentGrantor(data.granted_by),
                granted_at=now,
            )
        )
        try:
            await self.session.commit()
        except IntegrityError:
            # 동시에 동의 요청: 부분 유니크(uq_recording_consents_active) → 먼저 저장된 동의 사용
            await self.session.rollback()
        return await self.consent_status(user)

    async def revoke_consent(self, user: Profile) -> None:
        """동의 철회: 새 녹음 업로드가 막힌다. 이미 저장된 녹음은 학생이 직접 삭제할 수 있다."""
        consent = await self._active_consent(user)
        if consent is None:
            raise NotFoundError("No active recording consent")
        consent.revoked_at = clock.utc_now()
        await self.session.commit()

    # ------------------------------------------------------------------ owner

    async def _recording(
        self, artwork_id: uuid.UUID, recording_id: uuid.UUID, *, for_update: bool = False
    ) -> FeedbackRecording:
        stmt = select(FeedbackRecording).where(
            FeedbackRecording.artwork_id == artwork_id, FeedbackRecording.id == recording_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        recording = (await self.session.execute(stmt)).scalar_one_or_none()
        if recording is None or recording.status == RecordingStatus.DELETED:
            raise NotFoundError("Recording not found")
        return recording

    async def _active(self, artwork_id: uuid.UUID) -> list[FeedbackRecording]:
        stmt = (
            select(FeedbackRecording)
            .where(
                FeedbackRecording.artwork_id == artwork_id,
                FeedbackRecording.status == RecordingStatus.ACTIVE,
            )
            .order_by(FeedbackRecording.uploaded_at.desc(), FeedbackRecording.id)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def _reads(
        self, recordings: list[FeedbackRecording], token: str, include_urls: bool
    ) -> list[RecordingRead]:
        urls: dict[str, str] = {}
        expires = clock.utc_now() + timedelta(seconds=self.settings.storage_signed_url_seconds)
        if include_urls and recordings:
            urls = await self._sign([r.storage_path for r in recordings], token)
        return [recording_read(r, urls.get(r.storage_path), expires) for r in recordings]

    async def _sign(self, paths: list[str], token: str) -> dict[str, str]:
        try:
            return await self._require_storage().create_signed_urls(
                paths, access_token=token, expires_in=self.settings.storage_signed_url_seconds
            )
        except StorageError:
            raise StorageUnavailableError() from None

    async def request_upload(
        self, owner: Profile, artwork_id: uuid.UUID, data: RecordingUploadRequest, token: str
    ) -> RecordingUploadTicket:
        storage = self._require_storage()
        settings = self.settings
        consent = await self._active_consent(owner)
        if consent is None or consent.policy_version != settings.recording_consent_version:
            raise ConflictError(
                "Recording consent is required",
                code=ErrorCode.RECORDING_CONSENT_REQUIRED,
                details={"required_version": settings.recording_consent_version},
            )
        content_type = normalize_content_type(data.content_type)
        check_declared_audio(
            content_type,
            data.file_name,
            data.file_size,
            data.duration_ms,
            allowed=settings.recording_allowed_content_types,
            max_bytes=settings.recording_max_upload_bytes,
            max_duration_seconds=settings.recording_max_duration_seconds,
        )
        # 작품 행 잠금: 녹음 개수 제한을 직렬화
        artwork = await self.artworks.owned(owner, artwork_id, for_update=True)
        now = clock.utc_now()
        await self._expire_pending(artwork.id, now)
        live = (
            await self.session.execute(
                select(func.count()).where(
                    FeedbackRecording.artwork_id == artwork.id,
                    FeedbackRecording.status.in_(_LIVE),
                )
            )
        ).scalar_one()
        if live >= settings.recording_max_per_artwork:
            raise ConflictError(
                f"Up to {settings.recording_max_per_artwork} recordings per artwork",
                code=ErrorCode.RECORDING_LIMIT_REACHED,
            )

        recording_id = uuid.uuid4()
        path = f"{owner.id}/{artwork.id}/{recording_id}.{storage_extension(content_type)}"
        recording = FeedbackRecording(
            id=recording_id,
            artwork_id=artwork.id,
            owner_id=owner.id,
            consent_id=consent.id,
            speaker_notice_confirmed=True,
            title=data.title,
            status=RecordingStatus.PENDING,
            storage_path=path,
            content_type=content_type,
            duration_ms=data.duration_ms,
            recorded_at=data.recorded_at,
            upload_expires_at=now + timedelta(seconds=settings.recording_upload_ttl_seconds),
        )
        self.session.add(recording)
        await self.session.commit()  # Storage 정책이 녹음 행을 확인하므로 URL 발급 전에 커밋
        try:
            signed = await storage.create_upload_url(path, access_token=token)
        except StorageError:
            await self.session.delete(recording)
            await self.session.commit()
            raise StorageUnavailableError() from None
        await self.session.refresh(recording)
        await self.cleanup_storage(owner, token)
        return RecordingUploadTicket(
            recording=recording_read(recording),
            upload=UploadTarget(
                bucket=storage.bucket,
                path=path,
                url=signed.url,
                token=signed.token,
                expires_at=recording.upload_expires_at,
            ),
        )

    async def _expire_pending(self, artwork_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(FeedbackRecording)
            .where(
                FeedbackRecording.artwork_id == artwork_id,
                FeedbackRecording.status == RecordingStatus.PENDING,
                FeedbackRecording.upload_expires_at <= now,
            )
            .values(
                status=RecordingStatus.DELETED,
                deleted_at=now,
                storage_cleanup_pending=True,
                updated_at=func.now(),
            )
        )

    async def _discard(self, owner: Profile, recording: FeedbackRecording, token: str) -> None:
        recording.status = RecordingStatus.DELETED
        recording.deleted_at = clock.utc_now()
        recording.storage_cleanup_pending = True
        await self.session.commit()
        await self.cleanup_storage(owner, token)

    async def complete_upload(
        self, owner: Profile, artwork_id: uuid.UUID, recording_id: uuid.UUID, token: str
    ) -> RecordingRead:
        storage = self._require_storage()
        settings = self.settings
        artwork = await self.artworks.owned(owner, artwork_id, for_update=True)
        recording = await self._recording(artwork.id, recording_id, for_update=True)
        if recording.status == RecordingStatus.ACTIVE:
            return recording_read(recording)  # 재시도·중복 호출 (멱등)
        if recording.upload_expires_at <= clock.utc_now():
            await self._discard(owner, recording, token)
            raise ConflictError(
                "The upload has expired; request a new one", code=ErrorCode.UPLOAD_EXPIRED
            )
        try:
            data = await storage.download(
                recording.storage_path,
                access_token=token,
                max_bytes=settings.recording_max_upload_bytes,
            )
        except StorageObjectNotFound:
            await self.session.rollback()
            raise ConflictError(
                "The file has not been uploaded yet", code=ErrorCode.UPLOAD_NOT_FOUND
            ) from None
        except StorageObjectTooLarge:
            await self._discard(owner, recording, token)
            raise UnprocessableError(
                "The uploaded file is too large", code=ErrorCode.FILE_TOO_LARGE
            ) from None
        except StorageError:
            await self.session.rollback()
            raise StorageUnavailableError() from None

        try:
            info = inspect_audio(
                data,
                declared_type=recording.content_type,
                allowed=settings.recording_allowed_content_types,
                max_bytes=settings.recording_max_upload_bytes,
                max_duration_seconds=settings.recording_max_duration_seconds,
            )
        except UnprocessableError:
            await self._discard(owner, recording, token)
            raise

        duplicate = (
            await self.session.execute(
                select(FeedbackRecording.id).where(
                    FeedbackRecording.artwork_id == artwork.id,
                    FeedbackRecording.status == RecordingStatus.ACTIVE,
                    FeedbackRecording.sha256 == info.sha256,
                )
            )
        ).first()
        if duplicate is not None:
            await self._discard(owner, recording, token)
            raise ConflictError(
                "The same recording is already uploaded to this artwork",
                code=ErrorCode.DUPLICATE_RECORDING,
                details={"recording_id": str(duplicate[0])},
            )

        recording.status = RecordingStatus.ACTIVE
        recording.uploaded_at = clock.utc_now()
        recording.size_bytes = info.size_bytes
        recording.sha256 = info.sha256
        if info.duration_ms is not None:
            recording.duration_ms = info.duration_ms  # WAV: 서버 계산값으로 보정
        await self.session.commit()
        await self.session.refresh(recording)
        return recording_read(recording)

    async def list_mine(
        self, owner: Profile, artwork_id: uuid.UUID, token: str, include_urls: bool
    ) -> list[RecordingRead]:
        artwork = await self.artworks.owned(owner, artwork_id)
        return await self._reads(await self._active(artwork.id), token, include_urls)

    async def get_mine(
        self, owner: Profile, artwork_id: uuid.UUID, recording_id: uuid.UUID
    ) -> RecordingRead:
        artwork = await self.artworks.owned(owner, artwork_id)
        return recording_read(await self._recording(artwork.id, recording_id))

    async def url(self, artwork_id: uuid.UUID, recording_id: uuid.UUID, token: str) -> RecordingUrl:
        recording = await self._recording(artwork_id, recording_id)
        if recording.status != RecordingStatus.ACTIVE:
            raise ConflictError(
                "The recording is not uploaded yet", code=ErrorCode.RECORDING_NOT_ACTIVE
            )
        urls = await self._sign([recording.storage_path], token)
        if recording.storage_path not in urls:
            raise StorageUnavailableError()
        return RecordingUrl(
            recording_id=recording.id,
            url=urls[recording.storage_path],
            expires_at=clock.utc_now()
            + timedelta(seconds=self.settings.storage_signed_url_seconds),
        )

    async def owner_url(
        self, owner: Profile, artwork_id: uuid.UUID, recording_id: uuid.UUID, token: str
    ) -> RecordingUrl:
        await self.artworks.owned(owner, artwork_id)
        return await self.url(artwork_id, recording_id, token)

    async def delete(
        self, owner: Profile, artwork_id: uuid.UUID, recording_id: uuid.UUID, token: str
    ) -> None:
        artwork = await self.artworks.owned(owner, artwork_id, for_update=True)
        recording = await self._recording(artwork.id, recording_id, for_update=True)
        await self._discard(owner, recording, token)

    async def cleanup_storage(self, owner: Profile, token: str) -> None:
        if self.storage is None:
            return
        rows = (
            await self.session.execute(
                select(FeedbackRecording.id, FeedbackRecording.storage_path)
                .where(
                    FeedbackRecording.owner_id == owner.id,
                    FeedbackRecording.storage_cleanup_pending,
                )
                .limit(CLEANUP_BATCH)
            )
        ).all()
        if not rows:
            return
        try:
            await self.storage.delete([path for _, path in rows], access_token=token)
        except StorageError:
            logger.warning("recording cleanup deferred", extra={"count": len(rows)})
            return
        await self.session.execute(
            update(FeedbackRecording)
            .where(FeedbackRecording.id.in_([rid for rid, _ in rows]))
            .values(storage_cleanup_pending=False, updated_at=func.now())
        )
        await self.session.commit()

    # ------------------------------------------------------------------ staff (read only)

    async def staff_list(
        self, actor: AcademyMembership, artwork_id: uuid.UUID, token: str, include_urls: bool
    ) -> list[RecordingRead]:
        artwork = await self.artworks.staff_artwork(actor, artwork_id)
        return await self._reads(await self._active(artwork.id), token, include_urls)

    async def staff_get(
        self, actor: AcademyMembership, artwork_id: uuid.UUID, recording_id: uuid.UUID
    ) -> RecordingRead:
        artwork = await self.artworks.staff_artwork(actor, artwork_id)
        recording = await self._recording(artwork.id, recording_id)
        if recording.status != RecordingStatus.ACTIVE:
            raise NotFoundError("Recording not found")
        return recording_read(recording)

    async def staff_url(
        self, actor: AcademyMembership, artwork_id: uuid.UUID, recording_id: uuid.UUID, token: str
    ) -> RecordingUrl:
        artwork = await self.artworks.staff_artwork(actor, artwork_id)
        return await self.url(artwork.id, recording_id, token)
