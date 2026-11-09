"""작품과 단계별 사진 (F-06).

업로드 흐름 (2단계, 파일은 백엔드를 거치지 않는다)
1. `request_upload`: 형식·크기 1차 검증 → 사진 행(PENDING) 생성
   → 사용자 토큰으로 Signed upload URL 발급
2. 클라이언트가 Storage에 직접 업로드
3. `complete_upload`: Storage에서 파일을 받아 실제 형식·크기·픽셀 검증, 내용 해시로 중복 확인
   → ACTIVE + 메타데이터 저장 (대표 사진 지정, 교체 처리)

DB·Storage 일관성
- 파일이 없는 ACTIVE 행이 생기지 않도록, ACTIVE 전환은 Storage에서 파일을 확인한 뒤에만 한다.
- 삭제·교체·검증 실패는 먼저 DB를 DELETED + storage_cleanup_pending=true로 커밋하고, 그 다음 Storage
  삭제를 시도한다. 실패해도 플래그가 남아 같은 사용자의 다음 요청에서 다시 정리한다
  (고아 파일 방지).
- 완료 처리 중 Storage 장애는 503, 사진은 PENDING으로 남아 재시도할 수 있다.
- 만료된 PENDING 업로드는 다음 업로드 요청 때 정리한다.

권한
- 작품 생성·수정·삭제·업로드: 소유 학생 본인 (`/artworks`)
- 조회: 소유자 본인, 또는 학원에 연결된 작품의 담당 강사·학원 관리자 (`/academies/{id}/artworks`)
- 다른 사람의 작품 ID → 404 (존재 여부 비노출)

분류·완료 (v0.5.1)
- practical_type(실기 유형)과 work_category(작업 목적)는 독립 필터
  (같이 주면 AND, 각각 여러 값은 OR)
- work_status: 학생이 `POST /complete`로 완료, `POST /reopen`으로 작업 재개. 완료하려면 ACTIVE
  FINAL 사진이 필요하다. 완료된 작품은 사진 업로드·교체·삭제·대표 변경이 막힌다(409
  ARTWORK_COMPLETED). 제목·설명·분류·연결 수정과 피드백 녹음은 계속 가능하다.
- recording_count: 작품별 ACTIVE 녹음 수를 목록 1페이지당 쿼리 1번(GROUP BY)으로 집계한다.
"""

import logging
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    ForbiddenError,
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
from app.models.academy_class import AcademyClass
from app.models.artwork import Artwork, ArtworkPhoto
from app.models.enums import (
    ARTWORK_STAGE_ORDER,
    ArtworkProgress,
    ArtworkStage,
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    ClassMemberRole,
    MembershipRole,
    MembershipStatus,
    PhotoStatus,
    PracticalType,
    RecordingStatus,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.models.recording import FeedbackRecording
from app.models.task import Task, TaskAssignment
from app.repositories.pagination import fetch_page
from app.schemas.artworks import (
    ArtworkCreate,
    ArtworkDetail,
    ArtworkProgressRead,
    ArtworkRead,
    ArtworkUpdate,
    PhotoRead,
    SignedUrl,
    StageSummary,
    UploadRequest,
    UploadTarget,
    UploadTicket,
)
from app.schemas.common import PaginationParams
from app.services.access import AccessService, managed_student_ids
from app.services.ai_cleanup import purge_for_recordings
from app.services.images import check_declared_file, inspect_image, storage_extension

logger = logging.getLogger(__name__)

CLEANUP_BATCH = 50
_LIVE = (PhotoStatus.PENDING, PhotoStatus.ACTIVE)


@dataclass(frozen=True)
class ArtworkFilters:
    """작품 목록 필터. 빈 값은 조건 없음. 시퀀스는 OR, 서로 다른 필드는 AND."""

    academy_id: uuid.UUID | None = None
    work_date_from: date | None = None
    work_date_to: date | None = None
    practical_types: Sequence[PracticalType] = ()
    work_categories: Sequence[ArtworkWorkCategory] = ()
    work_status: ArtworkWorkStatus | None = None

    def apply(self, stmt: Select[tuple[Artwork]]) -> Select[tuple[Artwork]]:
        if self.academy_id is not None:
            stmt = stmt.where(Artwork.academy_id == self.academy_id)
        if self.work_date_from is not None:
            stmt = stmt.where(Artwork.work_date >= self.work_date_from)
        if self.work_date_to is not None:
            stmt = stmt.where(Artwork.work_date <= self.work_date_to)
        if self.practical_types:
            stmt = stmt.where(Artwork.practical_type.in_(self.practical_types))
        if self.work_categories:
            stmt = stmt.where(Artwork.work_category.in_(self.work_categories))
        if self.work_status is not None:
            stmt = stmt.where(Artwork.work_status == self.work_status)
        return stmt


def _stage_rank(stage: ArtworkStage) -> int:
    return ARTWORK_STAGE_ORDER.index(stage)


def summarize(artwork: Artwork, photos: list[ArtworkPhoto]) -> ArtworkProgressRead:
    active = [p for p in photos if p.status == PhotoStatus.ACTIVE]
    stages = []
    for stage in ARTWORK_STAGE_ORDER:
        items = sorted((p for p in active if p.stage == stage), key=lambda p: (p.uploaded_at, p.id))
        representative = next((p.id for p in items if p.is_representative), None)
        stages.append(
            StageSummary(
                stage=stage,
                photo_count=len(items),
                representative_photo_id=representative,
                first_uploaded_at=items[0].uploaded_at if items else None,
                last_uploaded_at=items[-1].uploaded_at if items else None,
            )
        )
    reached = [s for s in stages if s.photo_count]
    progress = ArtworkProgress(reached[-1].stage) if reached else ArtworkProgress.NOT_STARTED
    has_final = progress == ArtworkProgress.FINAL
    return ArtworkProgressRead(
        artwork_id=artwork.id,
        progress=progress,
        completed=has_final,
        has_final_photo=has_final,
        work_status=artwork.work_status,
        stages=stages,
    )


def photo_read(photo: ArtworkPhoto, url: str | None = None, expires: datetime | None = None):  # type: ignore[no-untyped-def]
    return PhotoRead(
        id=photo.id,
        artwork_id=photo.artwork_id,
        stage=photo.stage,
        status=photo.status,
        content_type=photo.content_type,
        size_bytes=photo.size_bytes,
        width=photo.width,
        height=photo.height,
        is_representative=photo.is_representative,
        uploaded_at=photo.uploaded_at,
        created_at=photo.created_at,
        url=url,
        url_expires_at=expires if url else None,
    )


def artwork_read(  # type: ignore[type-arg]
    artwork: Artwork, photos: list[ArtworkPhoto], recording_count: int = 0
) -> dict:
    summary = summarize(artwork, photos)
    cover = next(
        (s.representative_photo_id for s in reversed(summary.stages) if s.representative_photo_id),
        None,
    )
    return {
        "id": artwork.id,
        "title": artwork.title,
        "description": artwork.description,
        "work_date": artwork.work_date,
        "academy_id": artwork.academy_id,
        "student_membership_id": artwork.student_membership_id,
        "class_id": artwork.class_id,
        "task_id": artwork.task_id,
        "practical_type": artwork.practical_type,
        "work_category": artwork.work_category,
        "work_status": artwork.work_status,
        "completed_at": artwork.completed_at,
        "progress": summary.progress,
        "photo_count": sum(s.photo_count for s in summary.stages),
        "recording_count": recording_count,
        "cover_photo_id": cover,
        "created_at": artwork.created_at,
        "updated_at": artwork.updated_at,
        "stages": summary.stages,
    }


class ArtworkService:
    def __init__(
        self, session: AsyncSession, settings: Settings, storage: StorageClient | None = None
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.access = AccessService(session)

    # ------------------------------------------------------------------ queries

    async def _photos(self, artwork_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ArtworkPhoto]]:
        result: dict[uuid.UUID, list[ArtworkPhoto]] = defaultdict(list)
        if not artwork_ids:
            return result
        stmt = select(ArtworkPhoto).where(
            ArtworkPhoto.artwork_id.in_(artwork_ids), ArtworkPhoto.status == PhotoStatus.ACTIVE
        )
        for photo in (await self.session.execute(stmt)).scalars():
            result[photo.artwork_id].append(photo)
        return result

    async def recording_counts(self, artwork_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """작품별 ACTIVE 녹음 수 (삭제·업로드 미완료 제외). 작품 수와 무관하게 쿼리 1번.

        호출자가 이미 작품 접근 권한을 확인한 작품 ID만 넘긴다. 소유자와 담당 강사 모두 그 작품의
        ACTIVE 녹음 전체를 볼 수 있으므로(RecordingService) 집계 범위도 같다.
        """
        if not artwork_ids:
            return {}
        stmt = (
            select(FeedbackRecording.artwork_id, func.count())
            .where(
                FeedbackRecording.artwork_id.in_(artwork_ids),
                FeedbackRecording.status == RecordingStatus.ACTIVE,
            )
            .group_by(FeedbackRecording.artwork_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {artwork_id: count for artwork_id, count in rows}

    async def _reads(self, artworks: list[Artwork]) -> list[dict]:  # type: ignore[type-arg]
        ids = [a.id for a in artworks]
        photos = await self._photos(ids)
        counts = await self.recording_counts(ids)
        return [artwork_read(a, photos[a.id], counts.get(a.id, 0)) for a in artworks]

    async def owned(
        self, owner: Profile, artwork_id: uuid.UUID, *, for_update: bool = False
    ) -> Artwork:
        stmt = select(Artwork).where(
            Artwork.id == artwork_id, Artwork.owner_id == owner.id, Artwork.deleted_at.is_(None)
        )
        if for_update:
            stmt = stmt.with_for_update()
        artwork = (await self.session.execute(stmt)).scalar_one_or_none()
        if artwork is None:
            raise NotFoundError("Artwork not found")
        return artwork

    async def _photo(
        self, artwork_id: uuid.UUID, photo_id: uuid.UUID, *, for_update: bool = False
    ) -> ArtworkPhoto:
        stmt = select(ArtworkPhoto).where(
            ArtworkPhoto.artwork_id == artwork_id, ArtworkPhoto.id == photo_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        photo = (await self.session.execute(stmt)).scalar_one_or_none()
        if photo is None or photo.status == PhotoStatus.DELETED:
            raise NotFoundError("Photo not found")
        return photo

    async def _page(
        self, stmt: Select[tuple[Artwork]], params: PaginationParams
    ) -> tuple[list[Artwork], int]:
        stmt = stmt.where(Artwork.deleted_at.is_(None)).order_by(
            Artwork.work_date.desc(), Artwork.created_at.desc(), Artwork.id
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [row[0] for row in rows], total

    async def _detail_dict(self, artwork: Artwork, viewer_token: str, include_urls: bool) -> dict:  # type: ignore[type-arg]
        photos = (await self._photos([artwork.id]))[artwork.id]
        counts = await self.recording_counts([artwork.id])
        data = artwork_read(artwork, photos, counts.get(artwork.id, 0))
        data["photos"] = await self._photo_reads(photos, viewer_token, include_urls)
        return data

    async def _photo_reads(
        self, photos: list[ArtworkPhoto], token: str, include_urls: bool
    ) -> list[PhotoRead]:
        ordered = sorted(
            photos, key=lambda p: (_stage_rank(p.stage), not p.is_representative, p.uploaded_at)
        )
        urls: dict[str, str] = {}
        expires = clock.utc_now() + timedelta(seconds=self.settings.storage_signed_url_seconds)
        if include_urls and ordered:
            urls = await self._sign([p.storage_path for p in ordered], token)
        return [photo_read(p, urls.get(p.storage_path), expires) for p in ordered]

    async def _sign(self, paths: list[str], token: str) -> dict[str, str]:
        storage = self._require_storage()
        try:
            return await storage.create_signed_urls(
                paths, access_token=token, expires_in=self.settings.storage_signed_url_seconds
            )
        except StorageError:
            raise StorageUnavailableError() from None

    def _require_storage(self) -> StorageClient:
        if self.storage is None:
            raise StorageNotConfiguredError()
        return self.storage

    @staticmethod
    def _ensure_photos_editable(artwork: Artwork) -> None:
        """완료된 작품의 사진은 바꿀 수 없다 (작업 재개 후 가능)."""
        if artwork.work_status == ArtworkWorkStatus.COMPLETED:
            raise ConflictError(
                "The artwork is completed; reopen it to change photos",
                code=ErrorCode.ARTWORK_COMPLETED,
            )

    # ------------------------------------------------------------------ links

    async def _resolve_links(
        self,
        owner: Profile,
        academy_id: uuid.UUID | None,
        class_id: uuid.UUID | None,
        task_id: uuid.UUID | None,
    ) -> dict[str, uuid.UUID | None]:
        """학원·반·과제 연결 검증. 학원은 본인이 학생으로 ACTIVE 소속된 곳만."""
        if academy_id is None:
            if class_id or task_id:
                raise UnprocessableError(
                    "academy_id is required to link a class or task",
                    code=ErrorCode.INVALID_ARTWORK_LINK,
                )
            return {
                "academy_id": None,
                "student_membership_id": None,
                "class_id": None,
                "task_id": None,
            }
        membership = (
            await self.session.execute(
                select(AcademyMembership).where(
                    AcademyMembership.academy_id == academy_id,
                    AcademyMembership.user_id == owner.id,
                    AcademyMembership.role == MembershipRole.STUDENT,
                    AcademyMembership.status == MembershipStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if membership is None:
            raise UnprocessableError(
                "You are not a student of this academy", code=ErrorCode.INVALID_ARTWORK_LINK
            )
        if task_id is not None:
            task = (
                await self.session.execute(
                    select(Task)
                    .join(TaskAssignment, TaskAssignment.task_id == Task.id)
                    .where(
                        Task.academy_id == academy_id,
                        Task.id == task_id,
                        TaskAssignment.student_membership_id == membership.id,
                    )
                )
            ).scalar_one_or_none()
            if task is None or (class_id is not None and task.class_id != class_id):
                raise UnprocessableError(
                    "The task is not assigned to you in this class",
                    code=ErrorCode.INVALID_ARTWORK_LINK,
                )
            class_id = task.class_id
        if class_id is not None:
            in_class = await self.access.class_role(class_id, membership.id)
            exists = await self.session.get(AcademyClass, class_id)
            if (
                in_class != ClassMemberRole.STUDENT
                or exists is None
                or exists.academy_id != academy_id
            ):
                raise UnprocessableError(
                    "You are not assigned to this class", code=ErrorCode.INVALID_ARTWORK_LINK
                )
        return {
            "academy_id": academy_id,
            "student_membership_id": membership.id,
            "class_id": class_id,
            "task_id": task_id,
        }

    # ------------------------------------------------------------------ owner: artworks

    async def create(self, owner: Profile, data: ArtworkCreate) -> ArtworkDetail:
        links = await self._resolve_links(owner, data.academy_id, data.class_id, data.task_id)
        artwork = Artwork(
            id=uuid.uuid4(),
            owner_id=owner.id,
            title=data.title,
            description=data.description,
            work_date=data.work_date or clock.local_today(),
            practical_type=data.practical_type,
            work_category=data.work_category,
            work_status=ArtworkWorkStatus.IN_PROGRESS,
            **links,
        )
        self.session.add(artwork)
        await self.session.commit()
        await self.session.refresh(artwork)
        return ArtworkDetail(**artwork_read(artwork, []), photos=[])

    async def list_mine(
        self, owner: Profile, params: PaginationParams, filters: ArtworkFilters
    ) -> tuple[list[ArtworkRead], int]:
        stmt = filters.apply(select(Artwork).where(Artwork.owner_id == owner.id))
        artworks, total = await self._page(stmt, params)
        return [ArtworkRead(**data) for data in await self._reads(artworks)], total

    async def get_mine(
        self, owner: Profile, artwork_id: uuid.UUID, token: str, include_urls: bool
    ) -> ArtworkDetail:
        artwork = await self.owned(owner, artwork_id)
        return ArtworkDetail(**await self._detail_dict(artwork, token, include_urls))

    async def progress(self, owner: Profile, artwork_id: uuid.UUID) -> ArtworkProgressRead:
        artwork = await self.owned(owner, artwork_id)
        return summarize(artwork, (await self._photos([artwork.id]))[artwork.id])

    async def update(
        self, owner: Profile, artwork_id: uuid.UUID, data: ArtworkUpdate, token: str
    ) -> ArtworkDetail:
        artwork = await self.owned(owner, artwork_id, for_update=True)
        changes = data.changes()
        link_fields = {"academy_id", "class_id", "task_id"}
        if link_fields & changes.keys():
            academy_id = changes.get("academy_id", artwork.academy_id)
            # 학원을 바꾸거나 해제하면 기존 반·과제 연결은 함께 초기화
            same_academy = academy_id == artwork.academy_id
            class_id = changes.get("class_id", artwork.class_id if same_academy else None)
            task_id = changes.get("task_id", artwork.task_id if same_academy else None)
            for field, value in (
                await self._resolve_links(owner, academy_id, class_id, task_id)
            ).items():
                setattr(artwork, field, value)
        for field in ("title", "description", "work_date", "practical_type", "work_category"):
            if field in changes:
                setattr(artwork, field, changes[field])
        await self.session.commit()
        await self.session.refresh(artwork)
        return ArtworkDetail(**await self._detail_dict(artwork, token, include_urls=False))

    async def complete(self, owner: Profile, artwork_id: uuid.UUID, token: str) -> ArtworkDetail:
        """작품 완료. ACTIVE FINAL 사진이 있어야 한다. 이미 완료면 그대로 반환 (멱등, 시각 유지).

        완료 시점에 업로드 중(PENDING)인 사진은 취소한다 (완료 후 사진이 추가되지 않도록).
        """
        artwork = await self.owned(owner, artwork_id, for_update=True)
        if artwork.work_status != ArtworkWorkStatus.COMPLETED:
            has_final = (
                await self.session.execute(
                    select(ArtworkPhoto.id)
                    .where(
                        ArtworkPhoto.artwork_id == artwork.id,
                        ArtworkPhoto.stage == ArtworkStage.FINAL,
                        ArtworkPhoto.status == PhotoStatus.ACTIVE,
                    )
                    .limit(1)
                )
            ).first() is not None
            if not has_final:
                raise ConflictError(
                    "Upload a FINAL stage photo before completing the artwork",
                    code=ErrorCode.FINAL_PHOTO_REQUIRED,
                )
            now = clock.utc_now()
            artwork.work_status = ArtworkWorkStatus.COMPLETED
            artwork.completed_at = now
            await self.session.execute(
                update(ArtworkPhoto)
                .where(
                    ArtworkPhoto.artwork_id == artwork.id,
                    ArtworkPhoto.status == PhotoStatus.PENDING,
                )
                .values(
                    status=PhotoStatus.DELETED,
                    deleted_at=now,
                    storage_cleanup_pending=True,
                    updated_at=func.now(),
                )
            )
            await self.session.commit()
            await self.session.refresh(artwork)
            await self.cleanup_storage(owner, token)
        return ArtworkDetail(**await self._detail_dict(artwork, token, include_urls=False))

    async def reopen(self, owner: Profile, artwork_id: uuid.UUID, token: str) -> ArtworkDetail:
        """작업 재개 (완료 취소). 이미 작업 중이면 그대로 반환 (멱등)."""
        artwork = await self.owned(owner, artwork_id, for_update=True)
        if artwork.work_status != ArtworkWorkStatus.IN_PROGRESS:
            artwork.work_status = ArtworkWorkStatus.IN_PROGRESS
            artwork.completed_at = None
            await self.session.commit()
            await self.session.refresh(artwork)
        return ArtworkDetail(**await self._detail_dict(artwork, token, include_urls=False))

    async def delete(self, owner: Profile, artwork_id: uuid.UUID, token: str) -> None:
        artwork = await self.owned(owner, artwork_id, for_update=True)
        now = clock.utc_now()
        artwork.deleted_at = now
        await self.session.execute(
            update(ArtworkPhoto)
            .where(ArtworkPhoto.artwork_id == artwork.id, ArtworkPhoto.status.in_(_LIVE))
            .values(
                status=PhotoStatus.DELETED,
                deleted_at=now,
                is_representative=False,
                storage_cleanup_pending=True,
                updated_at=func.now(),
            )
        )
        # v0.6: 작품 녹음의 전사·첨삭 삭제, 진행 중 AI 작업 취소
        recording_ids = list(
            (
                await self.session.execute(
                    select(FeedbackRecording.id).where(FeedbackRecording.artwork_id == artwork.id)
                )
            ).scalars()
        )
        await purge_for_recordings(self.session, recording_ids)
        # v0.5: 작품의 피드백 녹음도 같은 트랜잭션에서 삭제 처리 (파일 정리는 RecordingService)
        await self.session.execute(
            update(FeedbackRecording)
            .where(
                FeedbackRecording.artwork_id == artwork.id,
                FeedbackRecording.status.in_([RecordingStatus.PENDING, RecordingStatus.ACTIVE]),
            )
            .values(
                status=RecordingStatus.DELETED,
                deleted_at=now,
                storage_cleanup_pending=True,
                updated_at=func.now(),
            )
        )
        await self.session.commit()
        await self.cleanup_storage(owner, token)

    # ------------------------------------------------------------------ owner: photos

    async def list_photos(
        self, owner: Profile, artwork_id: uuid.UUID, token: str, include_urls: bool
    ) -> list[PhotoRead]:
        artwork = await self.owned(owner, artwork_id)
        photos = (await self._photos([artwork.id]))[artwork.id]
        return await self._photo_reads(photos, token, include_urls)

    async def request_upload(
        self, owner: Profile, artwork_id: uuid.UUID, data: UploadRequest, token: str
    ) -> UploadTicket:
        storage = self._require_storage()
        settings = self.settings
        check_declared_file(
            data.content_type.lower(),
            data.file_name,
            data.file_size,
            allowed=settings.artwork_allowed_content_types,
            max_bytes=settings.artwork_max_upload_bytes,
        )
        content_type = data.content_type.lower()
        # 작품 행 잠금: 단계별 장수 제한·대표 사진 지정·완료 처리를 직렬화
        artwork = await self.owned(owner, artwork_id, for_update=True)
        self._ensure_photos_editable(artwork)
        now = clock.utc_now()
        await self._expire_pending(artwork.id, now)

        stage = data.stage
        if data.replaces_photo_id is not None:
            target = await self._photo(artwork.id, data.replaces_photo_id)
            if target.status != PhotoStatus.ACTIVE:
                raise ConflictError(
                    "Only uploaded photos can be replaced", code=ErrorCode.PHOTO_NOT_ACTIVE
                )
            if stage is not None and stage != target.stage:
                raise UnprocessableError("A replacement must keep the same stage")
            stage = target.stage
        if stage is None:
            raise UnprocessableError("stage is required")

        live = (
            await self.session.execute(
                select(func.count()).where(
                    ArtworkPhoto.artwork_id == artwork.id,
                    ArtworkPhoto.stage == stage,
                    ArtworkPhoto.status.in_(_LIVE),
                )
            )
        ).scalar_one()
        limit = settings.artwork_max_photos_per_stage + (1 if data.replaces_photo_id else 0)
        if live >= limit:
            raise ConflictError(
                f"Up to {settings.artwork_max_photos_per_stage} photos per stage",
                code=ErrorCode.PHOTO_LIMIT_REACHED,
            )

        photo_id = uuid.uuid4()
        # 경로는 서버가 만든다 (사용자 파일명 미사용 → 경로 조작·충돌 방지)
        path = f"{owner.id}/{artwork.id}/{photo_id}.{storage_extension(content_type)}"
        photo = ArtworkPhoto(
            id=photo_id,
            artwork_id=artwork.id,
            owner_id=owner.id,
            stage=stage,
            status=PhotoStatus.PENDING,
            storage_path=path,
            content_type=content_type,
            upload_expires_at=now + timedelta(seconds=settings.artwork_upload_ttl_seconds),
            replaces_photo_id=data.replaces_photo_id,
        )
        self.session.add(photo)
        # Storage 정책이 사진 행을 확인하므로 URL 발급 전에 커밋한다
        await self.session.commit()
        try:
            signed = await storage.create_upload_url(path, access_token=token)
        except StorageError:
            # 발급 실패: 아직 파일이 없으므로 행만 지운다 (DB·Storage 불일치 없음)
            await self.session.delete(photo)
            await self.session.commit()
            raise StorageUnavailableError() from None
        await self.session.refresh(photo)
        await self.cleanup_storage(owner, token)  # 만료 처리된 이전 업로드 정리 (best effort)
        return UploadTicket(
            photo=photo_read(photo),
            upload=UploadTarget(
                bucket=storage.bucket,
                path=path,
                url=signed.url,
                token=signed.token,
                expires_at=photo.upload_expires_at,
            ),
        )

    async def _expire_pending(self, artwork_id: uuid.UUID, now: datetime) -> None:
        await self.session.execute(
            update(ArtworkPhoto)
            .where(
                ArtworkPhoto.artwork_id == artwork_id,
                ArtworkPhoto.status == PhotoStatus.PENDING,
                ArtworkPhoto.upload_expires_at <= now,
            )
            .values(
                status=PhotoStatus.DELETED,
                deleted_at=now,
                storage_cleanup_pending=True,
                updated_at=func.now(),
            )
        )

    async def _discard(self, owner: Profile, photo: ArtworkPhoto, token: str) -> None:
        """검증 실패·만료: DB를 먼저 DELETED로 커밋한 뒤 Storage 파일을 정리한다.

        오류는 호출자가 던진다.
        """
        photo.status = PhotoStatus.DELETED
        photo.deleted_at = clock.utc_now()
        photo.storage_cleanup_pending = True
        await self.session.commit()
        await self.cleanup_storage(owner, token)

    async def complete_upload(
        self, owner: Profile, artwork_id: uuid.UUID, photo_id: uuid.UUID, token: str
    ) -> PhotoRead:
        storage = self._require_storage()
        settings = self.settings
        artwork = await self.owned(owner, artwork_id, for_update=True)
        photo = await self._photo(artwork.id, photo_id, for_update=True)
        if photo.status == PhotoStatus.ACTIVE:
            return photo_read(photo)  # 재시도·중복 호출: 같은 결과 (멱등)
        self._ensure_photos_editable(artwork)

        now = clock.utc_now()
        if photo.upload_expires_at <= now:
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
                select(ArtworkPhoto.id).where(
                    ArtworkPhoto.artwork_id == artwork.id,
                    ArtworkPhoto.status == PhotoStatus.ACTIVE,
                    ArtworkPhoto.sha256 == info.sha256,
                    ArtworkPhoto.id != photo.replaces_photo_id,
                )
            )
        ).first()
        if duplicate is not None:
            await self._discard(owner, photo, token)
            raise ConflictError(
                "The same image is already uploaded to this artwork",
                code=ErrorCode.DUPLICATE_PHOTO,
                details={"photo_id": str(duplicate[0])},
            )

        replaced: ArtworkPhoto | None = None
        if photo.replaces_photo_id is not None:
            replaced = (
                await self.session.execute(
                    select(ArtworkPhoto)
                    .where(ArtworkPhoto.id == photo.replaces_photo_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if replaced is not None and replaced.status != PhotoStatus.ACTIVE:
                replaced = None
        inherit = replaced.is_representative if replaced else False
        if replaced is not None:
            replaced.status = PhotoStatus.DELETED
            replaced.deleted_at = now
            replaced.is_representative = False
            replaced.storage_cleanup_pending = True
            await self.session.flush()

        has_representative = (
            await self.session.execute(
                select(ArtworkPhoto.id).where(
                    ArtworkPhoto.artwork_id == artwork.id,
                    ArtworkPhoto.stage == photo.stage,
                    ArtworkPhoto.is_representative,
                )
            )
        ).first() is not None
        photo.status = PhotoStatus.ACTIVE
        photo.uploaded_at = now
        photo.size_bytes = info.size_bytes
        photo.width = info.width
        photo.height = info.height
        photo.sha256 = info.sha256
        photo.is_representative = inherit or not has_representative
        await self.session.commit()
        await self.session.refresh(photo)
        if replaced is not None:
            await self.cleanup_storage(owner, token)
        return photo_read(photo)

    async def set_representative(
        self, owner: Profile, artwork_id: uuid.UUID, photo_id: uuid.UUID, value: bool
    ) -> PhotoRead:
        artwork = await self.owned(owner, artwork_id, for_update=True)
        self._ensure_photos_editable(artwork)
        photo = await self._photo(artwork.id, photo_id, for_update=True)
        if photo.status != PhotoStatus.ACTIVE:
            raise ConflictError("The photo is not uploaded yet", code=ErrorCode.PHOTO_NOT_ACTIVE)
        if not value:
            raise UnprocessableError(
                "Choose another photo as representative instead of unsetting it"
            )
        if not photo.is_representative:
            await self.session.execute(
                update(ArtworkPhoto)
                .where(
                    ArtworkPhoto.artwork_id == artwork.id,
                    ArtworkPhoto.stage == photo.stage,
                    ArtworkPhoto.is_representative,
                )
                .values(is_representative=False, updated_at=func.now())
            )
            photo.is_representative = True
            await self.session.commit()
            await self.session.refresh(photo)
        return photo_read(photo)

    async def delete_photo(
        self, owner: Profile, artwork_id: uuid.UUID, photo_id: uuid.UUID, token: str
    ) -> None:
        artwork = await self.owned(owner, artwork_id, for_update=True)
        self._ensure_photos_editable(artwork)
        photo = await self._photo(artwork.id, photo_id, for_update=True)
        was_representative = photo.is_representative
        photo.status = PhotoStatus.DELETED
        photo.deleted_at = clock.utc_now()
        photo.is_representative = False
        photo.storage_cleanup_pending = True
        await self.session.flush()
        if was_representative:
            # 같은 단계의 가장 먼저 올린 사진이 대표를 이어받는다
            successor = (
                await self.session.execute(
                    select(ArtworkPhoto)
                    .where(
                        ArtworkPhoto.artwork_id == artwork.id,
                        ArtworkPhoto.stage == photo.stage,
                        ArtworkPhoto.status == PhotoStatus.ACTIVE,
                    )
                    .order_by(ArtworkPhoto.uploaded_at, ArtworkPhoto.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if successor is not None:
                successor.is_representative = True
        await self.session.commit()
        await self.cleanup_storage(owner, token)

    async def photo_url(self, artwork_id: uuid.UUID, photo_id: uuid.UUID, token: str) -> SignedUrl:
        photo = await self._photo(artwork_id, photo_id)
        if photo.status != PhotoStatus.ACTIVE:
            raise ConflictError("The photo is not uploaded yet", code=ErrorCode.PHOTO_NOT_ACTIVE)
        urls = await self._sign([photo.storage_path], token)
        if photo.storage_path not in urls:
            raise StorageUnavailableError()
        return SignedUrl(
            photo_id=photo.id,
            url=urls[photo.storage_path],
            expires_at=clock.utc_now()
            + timedelta(seconds=self.settings.storage_signed_url_seconds),
        )

    async def owner_photo_url(
        self, owner: Profile, artwork_id: uuid.UUID, photo_id: uuid.UUID, token: str
    ) -> SignedUrl:
        await self.owned(owner, artwork_id)
        return await self.photo_url(artwork_id, photo_id, token)

    async def cleanup_storage(self, owner: Profile, token: str) -> None:
        """DELETED인데 Storage 정리가 안 된 파일을 지운다 (실패하면 다음 기회에 재시도)."""
        if self.storage is None:
            return
        rows = (
            await self.session.execute(
                select(ArtworkPhoto.id, ArtworkPhoto.storage_path)
                .where(ArtworkPhoto.owner_id == owner.id, ArtworkPhoto.storage_cleanup_pending)
                .limit(CLEANUP_BATCH)
            )
        ).all()
        if not rows:
            return
        try:
            await self.storage.delete([path for _, path in rows], access_token=token)
        except StorageError:
            logger.warning("storage cleanup deferred", extra={"count": len(rows)})
            return
        await self.session.execute(
            update(ArtworkPhoto)
            .where(ArtworkPhoto.id.in_([photo_id for photo_id, _ in rows]))
            .values(storage_cleanup_pending=False, updated_at=func.now())
        )
        await self.session.commit()

    # ------------------------------------------------------------------ staff (read only)

    async def list_for_staff(
        self,
        actor: AcademyMembership,
        params: PaginationParams,
        filters: ArtworkFilters,
        *,
        student_membership_id: uuid.UUID | None,
    ) -> tuple[list[tuple[dict, AcademyMembership, Profile]], int]:  # type: ignore[type-arg]
        if student_membership_id is not None:
            await self.access.require_managed_student(actor, student_membership_id)
        stmt = select(Artwork).where(
            Artwork.academy_id == actor.academy_id,
            Artwork.student_membership_id.in_(managed_student_ids(actor)),
        )
        if student_membership_id is not None:
            stmt = stmt.where(Artwork.student_membership_id == student_membership_id)
        artworks, total = await self._page(filters.apply(stmt), params)
        reads = await self._reads(artworks)
        people = await self._students({a.student_membership_id for a in artworks})
        return [
            (data, *people[a.student_membership_id])  # type: ignore[index]
            for a, data in zip(artworks, reads, strict=True)
        ], total

    async def _students(
        self, membership_ids: set[uuid.UUID | None]
    ) -> dict[uuid.UUID, tuple[AcademyMembership, Profile]]:
        ids = [m for m in membership_ids if m is not None]
        if not ids:
            return {}
        stmt = (
            select(AcademyMembership, Profile)
            .join(Profile, Profile.id == AcademyMembership.user_id)
            .where(AcademyMembership.id.in_(ids))
        )
        return {m.id: (m, p) for m, p in (await self.session.execute(stmt)).all()}

    async def staff_artwork(self, actor: AcademyMembership, artwork_id: uuid.UUID) -> Artwork:
        """학원 연결 작품만, 담당 학생 작품만 (다른 학원·개인 작품은 404, 비담당 403)."""
        artwork = (
            await self.session.execute(
                select(Artwork).where(
                    Artwork.id == artwork_id,
                    Artwork.academy_id == actor.academy_id,
                    Artwork.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if artwork is None or artwork.student_membership_id is None:
            raise NotFoundError("Artwork not found")
        if not await self.access.is_managed_student(actor, artwork.student_membership_id):
            raise ForbiddenError("This student is not in your classes")
        return artwork

    async def staff_detail(
        self, actor: AcademyMembership, artwork_id: uuid.UUID, token: str, include_urls: bool
    ) -> tuple[dict, AcademyMembership, Profile]:  # type: ignore[type-arg]
        artwork = await self.staff_artwork(actor, artwork_id)
        membership, profile = (await self._students({artwork.student_membership_id}))[
            artwork.student_membership_id  # type: ignore[index]
        ]
        return await self._detail_dict(artwork, token, include_urls), membership, profile
