"""AI 시각적 첨삭: AI 수정본 요청·조회·저장·삭제 (v1.3).

흐름
1. 단계별 피드백 화면이 `candidates`로 지금 사진의 개선사항(기존 AI 첨삭 정리 항목)을 받는다.
2. 학생이 고른 key로 `create` → 서버가 후보를 다시 계산해 대조, 동의·한도 확인, 같은 요청이면
재사용,
   아니면 수정본 행(QUEUED) + IMAGE_REVISE 작업을 만든다 (원본 Signed URL은 학생 토큰으로 발급).
3. Worker가 이미지 수정 API를 호출해 결과를 `result_staging`에 두고 STORING으로 바꾼다.
4. 학생이 다음에 조회할 때(`get`·`stage_revisions`·`summary`) 서버가 학생 토큰으로 Storage에 올리고
   (행 잠금 SKIP LOCKED → 동시 조회에도 1번), 성공하면 임시 이미지를 지우고 SUCCEEDED.
   업로드가 실패하면 임시 이미지를 그대로 두고 다음 조회에서 저장만 다시 한다 (생성 API 재호출
   없음).

비용·중복
- 학생이 버튼을 눌렀을 때만 생성. 조회·비교·저장 재시도는 생성 API를 부르지 않는다.
- request_hash 부분 유니크 + 사용자별 advisory lock → 동시 요청도 1건, 같은 요청은 기존 결과 반환.
- 사용자별 일·월 한도, 서비스 전체 일 한도·월 예상 비용 한도를 서버에서 확인한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import (
    AiRevisionDisabledError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    RateLimitedError,
    StorageNotConfiguredError,
    StorageUnavailableError,
    UnprocessableError,
)
from app.integrations.ai.openai_image import PROVIDER
from app.integrations.supabase.storage import StorageClient, StorageError, StorageObjectExists
from app.models.ai_feedback import AiProcessingConsent, AiProcessingJob
from app.models.ai_revision import ArtworkAiRevision
from app.models.artwork import Artwork, ArtworkPhoto, ArtworkReferencePhoto, ArtworkStageDef
from app.models.enums import (
    REUSABLE_REVISION_STATUSES,
    AiConsentPurpose,
    AiJobStatus,
    AiJobType,
    AiRevisionStatus,
    PhotoStatus,
)
from app.models.profile import Profile
from app.schemas.ai_revisions import (
    AiRevisionRead,
    ArtworkRevisionSummary,
    Improvement,
    ReplacedPhoto,
    RevisionCandidates,
    RevisionQuota,
    RevisionTimings,
    RevisionUsage,
    SourcePhotoRef,
    StageRevisionCount,
    StageRevisions,
)
from app.services import ai_consent_policy as consent_policy
from app.services import ai_revision_candidates as candidates_mod
from app.services.ai_revision_cleanup import release_replaced_originals, soft_delete_revisions
from app.services.ai_revision_images import EXTENSIONS
from app.services.ai_revision_prompt import PROMPT_VERSION
from app.services.artworks import ArtworkService

logger = logging.getLogger("app.ai_revisions")

ACTIVE_REVISION_STATUSES = frozenset({AiRevisionStatus.QUEUED, AiRevisionStatus.RUNNING})
IMAGE_STATUSES = frozenset({AiRevisionStatus.STORING, AiRevisionStatus.SUCCEEDED})
# 한 번의 조회에서 Storage로 옮길 임시 결과 수 (응답 지연 제한)
FINALIZE_BATCH = 3
CLEANUP_BATCH = 50
# 서비스 전체 생성 요청 직렬화 (한도 확인과 생성 사이 경쟁 방지). 생성은 드문 동작이라 충분하다
_CREATE_LOCK = "artmate:ai-revision:create"


def _ms(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def request_hash(
    source_sha256: str, improvements: list[dict[str, Any]], settings_snapshot: dict[str, Any]
) -> str:
    payload = {
        "source": source_sha256,
        "improvements": sorted(
            (i["category"], i["kind"], candidates_mod.normalize(i["text"])) for i in improvements
        ),
        "settings": settings_snapshot,
        "prompt": PROMPT_VERSION,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def estimate_cost(
    settings: Settings, *, text_tokens: int, image_tokens: int, output_tokens: int
) -> Decimal:
    usd = (
        text_tokens * settings.image_edit_price_text_input
        + image_tokens * settings.image_edit_price_image_input
        + output_tokens * settings.image_edit_price_image_output
    ) / 1_000_000
    return Decimal(str(round(usd, 5)))


def _month_start(today: date) -> datetime:
    start, _ = clock.local_day_bounds(today.replace(day=1))
    return start


def _charged():  # type: ignore[no-untyped-def]
    """한도에 세는 요청: 진행 중·결과 있음, 또는 실제로 API를 호출함 (호출 없는 실패 제외)."""
    return or_(
        ArtworkAiRevision.status.in_(REUSABLE_REVISION_STATUSES),
        ArtworkAiRevision.api_call_count > 0,
    )


class AiRevisionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        storage: StorageClient | None,
        revision_storage: StorageClient | None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage  # 작품 사진 버킷 (원본 Signed URL)
        self.revision_storage = revision_storage  # AI 수정본 버킷
        self.artworks = ArtworkService(session, settings, storage)

    # ================================================================ 공통

    def feature_status(self) -> str:
        if self.settings.image_edit_active:
            return "ENABLED"
        return "UNCONFIRMED" if self.settings.image_edit_enabled else "DISABLED"

    def _require_active(self) -> None:
        if not self.settings.image_edit_active:
            raise AiRevisionDisabledError()

    def _require_revision_storage(self) -> StorageClient:
        if self.revision_storage is None:
            raise StorageNotConfiguredError()
        return self.revision_storage

    async def _consent(self, user_id: uuid.UUID) -> consent_policy.ConsentState:
        purpose = AiConsentPurpose.VISUAL_CRITIQUE
        consent = (
            await self.session.execute(
                select(AiProcessingConsent).where(
                    AiProcessingConsent.user_id == user_id,
                    AiProcessingConsent.provider
                    == consent_policy.provider_for(self.settings, purpose),
                    AiProcessingConsent.purpose == purpose,
                    AiProcessingConsent.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        return consent_policy.evaluate(consent, self.settings, purpose)

    async def _photo_and_stage(
        self, artwork: Artwork, photo_id: uuid.UUID, *, for_update: bool = False
    ) -> tuple[ArtworkPhoto, ArtworkStageDef]:
        stmt = select(ArtworkPhoto).where(
            ArtworkPhoto.artwork_id == artwork.id,
            ArtworkPhoto.id == photo_id,
            ArtworkPhoto.status == PhotoStatus.ACTIVE,
        )
        if for_update:
            stmt = stmt.with_for_update()
        photo = (await self.session.execute(stmt)).scalar_one_or_none()
        if photo is None:
            raise NotFoundError("Photo not found")
        stage = await self.session.get(ArtworkStageDef, photo.stage_id)
        assert stage is not None
        return photo, stage

    async def _owned_revision(
        self, owner: Profile, revision_id: uuid.UUID, *, for_update: bool = False
    ) -> ArtworkAiRevision:
        stmt = (
            select(ArtworkAiRevision)
            .join(Artwork, Artwork.id == ArtworkAiRevision.artwork_id)
            .where(
                ArtworkAiRevision.id == revision_id,
                ArtworkAiRevision.owner_id == owner.id,
                ArtworkAiRevision.deleted_at.is_(None),
                Artwork.deleted_at.is_(None),
            )
        )
        if for_update:
            stmt = stmt.with_for_update(of=ArtworkAiRevision)
        revision = (await self.session.execute(stmt)).scalar_one_or_none()
        if revision is None:
            raise NotFoundError("AI revision not found")
        return revision

    # ================================================================ 한도

    async def _count(self, *conditions: Any) -> int:
        return int(
            (
                await self.session.execute(
                    select(func.count()).select_from(ArtworkAiRevision).where(*conditions)
                )
            ).scalar_one()
        )

    async def quota(self, owner_id: uuid.UUID) -> RevisionQuota:
        settings = self.settings
        today = clock.local_today()
        day_start, _ = clock.local_day_bounds(today)
        month_start = _month_start(today)
        daily = await self._count(
            ArtworkAiRevision.owner_id == owner_id,
            ArtworkAiRevision.created_at >= day_start,
            _charged(),
        )
        monthly = await self._count(
            ArtworkAiRevision.owner_id == owner_id,
            ArtworkAiRevision.created_at >= month_start,
            _charged(),
        )
        blocked: str | None = None
        if settings.image_edit_daily_limit and daily >= settings.image_edit_daily_limit:
            blocked = "DAILY"
        elif settings.image_edit_monthly_limit and monthly >= settings.image_edit_monthly_limit:
            blocked = "MONTHLY"
        elif await self._service_blocked(day_start, month_start):
            blocked = "SERVICE"
        return RevisionQuota(
            daily_used=daily,
            daily_limit=settings.image_edit_daily_limit,
            monthly_used=monthly,
            monthly_limit=settings.image_edit_monthly_limit,
            can_create=blocked is None,
            blocked_scope=blocked,  # type: ignore[arg-type]
        )

    async def _service_blocked(self, day_start: datetime, month_start: datetime) -> bool:
        settings = self.settings
        if settings.image_edit_service_daily_limit:
            used = await self._count(ArtworkAiRevision.created_at >= day_start, _charged())
            if used >= settings.image_edit_service_daily_limit:
                return True
        if settings.image_edit_service_monthly_budget_usd:
            spent, in_flight = (
                await self.session.execute(
                    select(
                        func.coalesce(func.sum(ArtworkAiRevision.estimated_cost_usd), 0),
                        func.count().filter(ArtworkAiRevision.status.in_(ACTIVE_REVISION_STATUSES)),
                    ).where(ArtworkAiRevision.created_at >= month_start)
                )
            ).one()
            projected = float(spent) + (int(in_flight) + 1) * settings.image_edit_estimated_cost_usd
            if projected > settings.image_edit_service_monthly_budget_usd:
                return True
        return False

    def _limit_error(self, quota: RevisionQuota) -> RateLimitedError:
        now = clock.utc_now()
        today = clock.local_today()
        if quota.blocked_scope == "DAILY":
            reset = clock.local_day_bounds(today)[1]
        else:
            nxt = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
            reset = clock.local_day_bounds(nxt)[0]
        retry = max(1, int((reset - now).total_seconds()) + 1)
        return RateLimitedError(
            "AI revision limit reached",
            code=ErrorCode.AI_REVISION_LIMIT_REACHED,
            details={
                "scope": quota.blocked_scope,
                "daily_limit": quota.daily_limit,
                "monthly_limit": quota.monthly_limit,
            },
            headers={"Retry-After": str(retry)},
        )

    # ================================================================ 읽기 변환

    async def _replacement_info(
        self, photo_ids: list[uuid.UUID]
    ) -> tuple[dict[uuid.UUID, ArtworkPhoto], dict[uuid.UUID, uuid.UUID]]:
        """원본 사진 행들과, 교체된 사진 → 지금 그 자리의 ACTIVE 사진."""
        if not photo_ids:
            return {}, {}
        photos = {
            p.id: p
            for p in (
                await self.session.execute(
                    select(ArtworkPhoto).where(ArtworkPhoto.id.in_(photo_ids))
                )
            ).scalars()
        }
        deleted = [pid for pid, p in photos.items() if p.status == PhotoStatus.DELETED]
        current: dict[uuid.UUID, uuid.UUID] = {}
        frontier = {pid: pid for pid in deleted}
        for _ in range(10):  # 여러 번 교체돼도 따라감
            if not frontier:
                break
            rows = (
                await self.session.execute(
                    select(
                        ArtworkPhoto.id, ArtworkPhoto.replaces_photo_id, ArtworkPhoto.status
                    ).where(
                        ArtworkPhoto.replaces_photo_id.in_(list(frontier)),
                        ArtworkPhoto.uploaded_at.isnot(None),
                    )
                )
            ).all()
            nxt: dict[uuid.UUID, uuid.UUID] = {}
            for new_id, old_id, status in rows:
                origin = frontier[old_id]
                if status == PhotoStatus.ACTIVE:
                    current[origin] = new_id
                else:
                    nxt[new_id] = origin
            frontier = nxt
        return photos, current

    async def _reads(
        self, revisions: list[ArtworkAiRevision], token: str | None
    ) -> list[AiRevisionRead]:
        photos, current = await self._replacement_info(list({r.photo_id for r in revisions}))
        urls: dict[str, str] = {}
        paths = [
            r.storage_path
            for r in revisions
            if r.status == AiRevisionStatus.SUCCEEDED and r.storage_path
        ]
        if paths and token is not None and self.revision_storage is not None:
            try:
                urls = await self.revision_storage.create_signed_urls(
                    paths, access_token=token, expires_in=self.settings.storage_signed_url_seconds
                )
            except StorageError:
                logger.warning("ai revision sign failed", extra={"count": len(paths)})
        now = clock.utc_now()
        expires = now + timedelta(seconds=self.settings.storage_signed_url_seconds)
        result = []
        for r in revisions:
            photo = photos.get(r.photo_id)
            url = urls.get(r.storage_path) if r.storage_path else None
            result.append(
                AiRevisionRead(
                    id=r.id,
                    artwork_id=r.artwork_id,
                    stage_id=r.stage_id,
                    photo_id=r.photo_id,
                    version=r.version,
                    status=r.status,
                    improvements=[Improvement.model_validate(i) for i in r.improvements],
                    candidate_count=len(r.selection.get("candidate_keys", [])),
                    provider=r.provider,
                    model_name=r.model_name,
                    quality=r.settings.get("quality"),
                    url=url,
                    url_expires_at=expires if url else None,
                    width=r.width,
                    height=r.height,
                    source_photo=SourcePhotoRef(
                        photo_id=r.photo_id,
                        photo_status=photo.status.value if photo else "DELETED",
                        replaced=r.photo_id in current,
                        current_photo_id=current.get(r.photo_id),
                    ),
                    error_code=r.error_code,
                    retryable=r.status in (AiRevisionStatus.FAILED, AiRevisionStatus.CANCELLED)
                    and photo is not None
                    and photo.status == PhotoStatus.ACTIVE,
                    timings=RevisionTimings(
                        queue_wait_ms=_ms(r.created_at, r.started_at),
                        generation_ms=_ms(r.api_started_at, r.api_finished_at),
                        storage_ms=r.storage_ms,
                        # 처음 내려주는 응답이면 지금이 '화면에 표시된' 시각
                        total_ms=_ms(r.created_at, r.delivered_at or (now if url else None)),
                    ),
                    created_at=r.created_at,
                    finished_at=r.finished_at,
                    stored_at=r.stored_at,
                )
            )
        return result

    async def _mark_delivered(self, revisions: list[AiRevisionRead]) -> None:
        """완성 이미지 URL을 처음 내려주는 시각 (전체 소요 시간 측정)."""
        ids = [r.id for r in revisions if r.url is not None]
        if not ids:
            return
        await self.session.execute(
            update(ArtworkAiRevision)
            .where(ArtworkAiRevision.id.in_(ids), ArtworkAiRevision.delivered_at.is_(None))
            .values(delivered_at=func.now())
        )
        await self.session.commit()

    # ================================================================ 저장 (STORING → SUCCEEDED)

    async def finalize(self, revision_id: uuid.UUID, token: str) -> None:
        """Worker 결과를 학생 토큰으로 Storage에 저장. 다른 요청이 처리 중이면 건너뛴다."""
        storage = self.revision_storage
        if storage is None:
            return
        revision = (
            await self.session.execute(
                select(ArtworkAiRevision)
                .options(undefer(ArtworkAiRevision.result_staging))
                .where(
                    ArtworkAiRevision.id == revision_id,
                    ArtworkAiRevision.status == AiRevisionStatus.STORING,
                    ArtworkAiRevision.deleted_at.is_(None),
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if revision is None or revision.result_staging is None or revision.storage_path is None:
            await self.session.rollback()
            return
        started = time.monotonic()
        try:
            await storage.upload(
                revision.storage_path,
                revision.result_staging,
                content_type=revision.content_type or "image/jpeg",
                access_token=token,
            )
        except StorageObjectExists:
            pass  # 이전 시도에서 이미 올라감 (같은 경로·같은 임시 결과)
        except StorageError:
            revision.storage_attempts += 1
            revision.storage_error_code = "STORAGE_UPLOAD_FAILED"
            await self.session.commit()
            logger.warning(
                "ai revision store deferred",
                extra={"revision_id": str(revision_id), "attempts": revision.storage_attempts},
            )
            return
        now = clock.utc_now()
        revision.storage_attempts += 1
        revision.storage_ms = int((time.monotonic() - started) * 1000)
        revision.stored_at = now
        revision.finished_at = revision.finished_at or now
        revision.status = AiRevisionStatus.SUCCEEDED
        revision.storage_error_code = None
        revision.result_staging = None  # 저장 확인 후에만 임시 이미지 삭제
        await self.session.commit()
        logger.info(
            "ai revision stored",
            extra={"revision_id": str(revision_id), "storage_ms": revision.storage_ms},
        )

    async def finalize_pending(
        self, owner: Profile, token: str, *, artwork_id: uuid.UUID | None = None
    ) -> None:
        stmt = select(ArtworkAiRevision.id).where(
            ArtworkAiRevision.owner_id == owner.id,
            ArtworkAiRevision.status == AiRevisionStatus.STORING,
            ArtworkAiRevision.deleted_at.is_(None),
        )
        if artwork_id is not None:
            stmt = stmt.where(ArtworkAiRevision.artwork_id == artwork_id)
        ids = list(
            (
                await self.session.execute(
                    stmt.order_by(ArtworkAiRevision.staged_at).limit(FINALIZE_BATCH)
                )
            ).scalars()
        )
        for revision_id in ids:
            await self.finalize(revision_id, token)

    # ================================================================ 조회

    async def candidates(
        self, owner: Profile, artwork_id: uuid.UUID, photo_id: uuid.UUID, token: str
    ) -> RevisionCandidates:
        artwork = await self.artworks.owned(owner, artwork_id)
        photo, stage = await self._photo_and_stage(artwork, photo_id)
        found = await candidates_mod.collect(self.session, stage.id, photo.id)
        consent = await self._consent(owner.id)
        quota = await self.quota(owner.id)
        await self.finalize_pending(owner, token, artwork_id=artwork.id)
        revisions = list(
            (
                await self.session.execute(
                    select(ArtworkAiRevision)
                    .where(
                        ArtworkAiRevision.photo_id == photo.id,
                        ArtworkAiRevision.deleted_at.is_(None),
                    )
                    .order_by(ArtworkAiRevision.created_at.desc(), ArtworkAiRevision.id)
                )
            ).scalars()
        )
        latest = (await self._reads(revisions[:1], token)) if revisions else []
        await self._mark_delivered(latest)
        return RevisionCandidates(
            photo_id=photo.id,
            stage_id=stage.id,
            feature_status=self.feature_status(),  # type: ignore[arg-type]
            consent_valid=consent.is_valid,
            consent_reason=consent.reason,
            consent_required_version=self.settings.ai_visual_consent_version,
            feedback_count=found.feedback_count,
            unsummarized_count=found.unsummarized_count,
            candidates=[Improvement.model_validate(c.snapshot()) for c in found.candidates],
            quota=quota,
            revision_count=len(revisions),
            latest=latest[0] if latest else None,
        )

    async def get(self, owner: Profile, revision_id: uuid.UUID, token: str) -> AiRevisionRead:
        revision = await self._owned_revision(owner, revision_id)
        if revision.status == AiRevisionStatus.STORING:
            await self.finalize(revision.id, token)
            revision = await self._owned_revision(owner, revision_id)
            await self.session.refresh(revision)
        reads = await self._reads([revision], token)
        await self._mark_delivered(reads)
        return reads[0]

    async def stage_revisions(
        self, owner: Profile, artwork_id: uuid.UUID, stage_id: uuid.UUID, token: str
    ) -> StageRevisions:
        artwork = await self.artworks.owned(owner, artwork_id)
        stage = await self.session.get(ArtworkStageDef, stage_id)
        if stage is None or stage.artwork_id != artwork.id:
            raise NotFoundError("Stage not found")
        await self.finalize_pending(owner, token, artwork_id=artwork.id)
        revisions = list(
            (
                await self.session.execute(
                    select(ArtworkAiRevision)
                    .where(
                        ArtworkAiRevision.artwork_id == artwork.id,
                        ArtworkAiRevision.stage_id == stage.id,
                        ArtworkAiRevision.deleted_at.is_(None),
                    )
                    .order_by(ArtworkAiRevision.created_at.desc(), ArtworkAiRevision.id)
                )
            ).scalars()
        )
        reads = await self._reads(revisions, token)
        await self._mark_delivered(reads)
        replaced: dict[uuid.UUID, ReplacedPhoto] = {}
        photos, _ = await self._replacement_info([r.photo_id for r in revisions])
        for read in reads:
            src = read.source_photo
            if src.replaced and src.current_photo_id is not None and src.photo_id not in replaced:
                photo = photos.get(src.photo_id)
                replaced[src.photo_id] = ReplacedPhoto(
                    photo_id=src.photo_id,
                    current_photo_id=src.current_photo_id,
                    uploaded_at=photo.uploaded_at if photo else None,
                )
        return StageRevisions(
            artwork_id=artwork.id,
            stage_id=stage.id,
            revisions=reads,
            replaced_photos=list(replaced.values()),
        )

    async def summary(
        self, owner: Profile, artwork_id: uuid.UUID, token: str
    ) -> ArtworkRevisionSummary:
        artwork = await self.artworks.owned(owner, artwork_id)
        await self.finalize_pending(owner, token, artwork_id=artwork.id)
        rows = (
            await self.session.execute(
                select(
                    ArtworkAiRevision.stage_id,
                    func.count().filter(ArtworkAiRevision.status.in_(IMAGE_STATUSES)),
                    func.count().filter(ArtworkAiRevision.status.in_(ACTIVE_REVISION_STATUSES)),
                )
                .where(
                    ArtworkAiRevision.artwork_id == artwork.id,
                    ArtworkAiRevision.deleted_at.is_(None),
                )
                .group_by(ArtworkAiRevision.stage_id)
            )
        ).all()
        return ArtworkRevisionSummary(
            artwork_id=artwork.id,
            stages=[
                StageRevisionCount(stage_id=sid, count=int(done), in_progress=int(running))
                for sid, done, running in rows
            ],
        )

    # ================================================================ 생성

    async def create(
        self,
        owner: Profile,
        artwork_id: uuid.UUID,
        photo_id: uuid.UUID,
        selected_keys: list[str],
        token: str,
    ) -> tuple[AiRevisionRead, bool]:
        self._require_active()
        artwork = await self.artworks.owned(owner, artwork_id)
        photo, stage = await self._photo_and_stage(artwork, photo_id)
        consent = await self._consent(owner.id)
        if not consent.is_valid:
            raise ConflictError(
                "Consent to send artwork images to external AI is required",
                code=ErrorCode.AI_CONSENT_REQUIRED,
                details={
                    "purpose": AiConsentPurpose.VISUAL_CRITIQUE.value,
                    "required_version": self.settings.ai_visual_consent_version,
                    "reason": consent.reason,
                },
            )
        found = await candidates_mod.collect(self.session, stage.id, photo.id)
        by_key = found.by_key()
        wanted = list(dict.fromkeys(selected_keys))
        if not found.candidates:
            raise UnprocessableError(
                "There are no improvements from the AI feedback summary for this photo",
                code=ErrorCode.AI_REVISION_NO_IMPROVEMENTS,
                details={"unsummarized_count": found.unsummarized_count},
            )
        unknown = [k for k in wanted if k not in by_key]
        if unknown:
            raise ConflictError(
                "The feedback changed; reload the improvements",
                code=ErrorCode.AI_REVISION_CANDIDATES_CHANGED,
            )
        chosen = set(wanted)
        improvements = [c.snapshot() for c in found.candidates if c.key in chosen]
        if not improvements:
            raise UnprocessableError(
                "Select at least one improvement", code=ErrorCode.AI_REVISION_NO_IMPROVEMENTS
            )
        assert photo.sha256 is not None
        reference = (
            await self.session.execute(
                select(ArtworkReferencePhoto)
                .where(
                    ArtworkReferencePhoto.artwork_id == artwork.id,
                    ArtworkReferencePhoto.status == PhotoStatus.ACTIVE,
                )
                .order_by(ArtworkReferencePhoto.position, ArtworkReferencePhoto.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()
        settings_snapshot = {
            "model": self.settings.image_edit_model,
            "quality": self.settings.image_edit_quality,
            "size": self.settings.image_edit_size,
            "output_format": self.settings.image_edit_output_format,
            "max_input_px": self.settings.image_edit_max_input_px,
            "reference_sha256": reference.sha256 if reference else None,
        }
        digest = request_hash(photo.sha256, improvements, settings_snapshot)

        # 서비스 전체 직렬화 (한도 확인 ~ 생성), 트랜잭션 끝에 자동 해제
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": _CREATE_LOCK}
        )
        existing = await self._reusable(owner.id, digest)
        if existing is not None:
            await self.session.commit()
            reads = await self._reads([existing], token)
            return reads[0], False
        quota = await self.quota(owner.id)
        if not quota.can_create:
            raise self._limit_error(quota)

        # 원본·제시물 사진 Signed URL (학생 토큰, Worker가 내려받음)
        paths = [photo.storage_path] + ([reference.storage_path] if reference else [])
        if self.storage is None:
            raise StorageNotConfiguredError()
        try:
            urls = await self.storage.create_signed_urls(
                paths, access_token=token, expires_in=self.settings.image_edit_source_url_seconds
            )
        except StorageError:
            raise StorageUnavailableError() from None
        if photo.storage_path not in urls:
            raise StorageUnavailableError()

        version = (
            int(
                (
                    await self.session.execute(
                        select(func.coalesce(func.max(ArtworkAiRevision.version), 0)).where(
                            ArtworkAiRevision.photo_id == photo.id
                        )
                    )
                ).scalar_one()
            )
            + 1
        )
        now = clock.utc_now()
        revision_id = uuid.uuid4()
        ext = EXTENSIONS.get(f"image/{self.settings.image_edit_output_format}", "jpg")
        revision = ArtworkAiRevision(
            id=revision_id,
            artwork_id=artwork.id,
            owner_id=owner.id,
            stage_id=stage.id,
            photo_id=photo.id,
            source_sha256=photo.sha256,
            version=version,
            status=AiRevisionStatus.QUEUED,
            source_feedback=found.source_feedback,
            improvements=improvements,
            selection={
                "candidate_keys": [c.key for c in found.candidates],
                "selected_keys": [i["key"] for i in improvements],
            },
            provider=PROVIDER,
            model_name=self.settings.image_edit_model,
            prompt_version=PROMPT_VERSION,
            settings={
                **settings_snapshot,
                "reference_photo_id": str(reference.id) if reference else None,
            },
            request_hash=digest,
            # 경로는 서버가 정한다 (Worker 결과를 학생 토큰으로 올릴 위치)
            storage_path=f"{owner.id}/{artwork.id}/{revision_id}.{ext}",
        )
        job = AiProcessingJob(
            id=uuid.uuid4(),
            job_type=AiJobType.IMAGE_REVISE,
            status=AiJobStatus.QUEUED,
            artwork_id=artwork.id,
            revision_id=revision_id,
            owner_id=owner.id,
            requested_by=owner.id,
            attempts=0,
            max_attempts=self.settings.image_edit_max_attempts,
            run_after=now,
            source_url=urls[photo.storage_path],
            source_url_expires_at=now
            + timedelta(seconds=self.settings.image_edit_source_url_seconds),
            params={
                "reference_url": urls.get(reference.storage_path) if reference else None,
            },
        )
        self.session.add(revision)
        await self.session.flush()
        revision.job_id = job.id
        self.session.add(job)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self._reusable(owner.id, digest)
            if existing is None:
                raise
            reads = await self._reads([existing], token)
            return reads[0], False
        await self.session.refresh(revision)
        logger.info(
            "ai revision requested",
            extra={"revision_id": str(revision_id), "improvements": len(improvements)},
        )
        reads = await self._reads([revision], token)
        return reads[0], True

    async def _reusable(self, owner_id: uuid.UUID, digest: str) -> ArtworkAiRevision | None:
        return (
            await self.session.execute(
                select(ArtworkAiRevision).where(
                    ArtworkAiRevision.owner_id == owner_id,
                    ArtworkAiRevision.request_hash == digest,
                    ArtworkAiRevision.status.in_(REUSABLE_REVISION_STATUSES),
                    ArtworkAiRevision.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    async def retry(
        self, owner: Profile, revision_id: uuid.UUID, token: str
    ) -> tuple[AiRevisionRead, bool]:
        """실패·취소된 수정본을 같은 개선사항으로 다시 요청 (새 버전, 한도 차감)."""
        self._require_active()
        revision = await self._owned_revision(owner, revision_id)
        if revision.status not in (AiRevisionStatus.FAILED, AiRevisionStatus.CANCELLED):
            raise ConflictError(
                "Only failed revisions can be retried", code=ErrorCode.JOB_NOT_RETRYABLE
            )
        artwork_id, photo_id = revision.artwork_id, revision.photo_id
        selected = list(revision.selection.get("selected_keys", []))
        try:
            read, created = await self.create(owner, artwork_id, photo_id, selected, token)
        except NotFoundError:
            raise ConflictError(
                "The original photo was replaced or deleted", code=ErrorCode.JOB_NOT_RETRYABLE
            ) from None
        if created:
            await self.session.execute(
                update(ArtworkAiRevision)
                .where(ArtworkAiRevision.id == read.id)
                .values(retry_of_id=revision_id)
            )
            await self.session.commit()
        return read, created

    # ================================================================ 삭제·정리

    async def delete(self, owner: Profile, revision_id: uuid.UUID, token: str) -> None:
        """수정본만 지운다 (학생 원본 사진에는 영향 없음). 진행 중이면 작업을 취소한다."""
        revision = await self._owned_revision(owner, revision_id, for_update=True)
        await soft_delete_revisions(self.session, [revision.id], code="AI_REVISION_DELETED")
        await self.session.commit()
        await release_replaced_originals(self.session, [revision.photo_id])
        await self.session.commit()
        await self.cleanup_storage(owner, token)
        await self.artworks.cleanup_storage(owner, token)

    async def cleanup_storage(self, owner: Profile, token: str) -> None:
        storage = self.revision_storage
        if storage is None:
            return
        rows = (
            await self.session.execute(
                select(ArtworkAiRevision.id, ArtworkAiRevision.storage_path)
                .where(
                    ArtworkAiRevision.owner_id == owner.id,
                    ArtworkAiRevision.storage_cleanup_pending,
                )
                .limit(CLEANUP_BATCH)
            )
        ).all()
        if not rows:
            return
        paths = [path for _, path in rows if path]
        try:
            if paths:
                await storage.delete(paths, access_token=token)
        except StorageError:
            logger.warning("ai revision cleanup deferred", extra={"count": len(rows)})
            return
        await self.session.execute(
            update(ArtworkAiRevision)
            .where(ArtworkAiRevision.id.in_([rid for rid, _ in rows]))
            .values(storage_cleanup_pending=False, updated_at=func.now())
        )
        await self.session.commit()

    # ================================================================ 운영

    async def usage(self, days: int) -> RevisionUsage:
        start = clock.utc_now() - timedelta(days=days)
        r = ArtworkAiRevision
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count().filter(r.status == AiRevisionStatus.SUCCEEDED),
                    func.count().filter(r.status == AiRevisionStatus.FAILED),
                    func.count().filter(
                        r.status.in_(
                            [
                                AiRevisionStatus.QUEUED,
                                AiRevisionStatus.RUNNING,
                                AiRevisionStatus.STORING,
                            ]
                        )
                    ),
                    func.coalesce(func.sum(r.api_call_count), 0),
                    func.coalesce(func.sum(r.input_tokens), 0),
                    func.coalesce(func.sum(r.input_image_tokens), 0),
                    func.coalesce(func.sum(r.output_tokens), 0),
                    func.coalesce(func.sum(r.estimated_cost_usd), 0),
                    func.count(func.distinct(r.owner_id)),
                    func.avg(func.extract("epoch", r.api_finished_at - r.api_started_at) * 1000),
                    func.avg(func.extract("epoch", r.started_at - r.created_at) * 1000),
                ).where(r.created_at >= start)
            )
        ).one()
        staged = (
            await self.session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(func.length(r.result_staging)), 0),
                ).where(r.result_staging.isnot(None))
            )
        ).one()
        return RevisionUsage(
            period_start=start,
            requests=row[0],
            succeeded=row[1],
            failed=row[2],
            in_progress=row[3],
            api_calls=int(row[4]),
            input_tokens=int(row[5]),
            input_image_tokens=int(row[6]),
            output_tokens=int(row[7]),
            estimated_cost_usd=Decimal(row[8]),
            users=row[9],
            staged_results=staged[0],
            staged_bytes=int(staged[1]),
            avg_generation_ms=int(row[10]) if row[10] is not None else None,
            avg_queue_wait_ms=int(row[11]) if row[11] is not None else None,
        )
