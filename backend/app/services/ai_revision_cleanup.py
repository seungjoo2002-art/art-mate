"""AI 수정본 정리 (v1.3). 모델만 import → 작품·사진 서비스에서 순환 없이 호출한다.

- 수정본 삭제 표시(soft delete)·진행 중 작업 취소·올린 파일 정리 대기
- 교체 전 원본 파일 보존 해제
- Worker 정기 작업: 보관 기간이 지난 임시 결과(DB) 정리
호출자가 commit 한다.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.models.ai_feedback import AiProcessingJob
from app.models.ai_revision import ArtworkAiRevision
from app.models.artwork import ArtworkPhoto
from app.models.enums import ACTIVE_JOB_STATUSES, AiJobStatus, AiRevisionStatus, PhotoStatus
from app.services.feedback_image_refs import is_feedback_reference

# 호출)


def _cancel_job_values(code: str) -> dict[str, Any]:
    return {
        "status": AiJobStatus.CANCELLED,
        "last_error_code": code,
        "last_error_message": None,
        "source_url": None,
        "source_url_expires_at": None,
        "params": {},
        "locked_by": None,
        "lease_expires_at": None,
        "finished_at": func.now(),
        "updated_at": func.now(),
    }


async def soft_delete_revisions(
    session: AsyncSession, revision_ids: list[uuid.UUID], *, code: str
) -> None:
    """수정본 삭제: 임시 이미지 삭제, 올린 파일 정리 대기, 진행 중 작업 취소 (호출자 commit)."""
    if not revision_ids:
        return
    await session.execute(
        update(AiProcessingJob)
        .where(
            AiProcessingJob.revision_id.in_(revision_ids),
            AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .values(**_cancel_job_values(code))
    )
    await session.execute(
        update(ArtworkAiRevision)
        .where(ArtworkAiRevision.id.in_(revision_ids), ArtworkAiRevision.deleted_at.is_(None))
        .values(
            deleted_at=func.now(),
            result_staging=None,
            status=case(
                (
                    ArtworkAiRevision.status.in_(
                        [
                            AiRevisionStatus.QUEUED,
                            AiRevisionStatus.RUNNING,
                            AiRevisionStatus.STORING,
                        ]
                    ),
                    AiRevisionStatus.CANCELLED.value,
                ),
                else_=ArtworkAiRevision.status,
            ),
            error_code=case(
                (
                    ArtworkAiRevision.status.in_(
                        [
                            AiRevisionStatus.QUEUED,
                            AiRevisionStatus.RUNNING,
                            AiRevisionStatus.STORING,
                        ]
                    ),
                    code,
                ),
                else_=ArtworkAiRevision.error_code,
            ),
            # Storage에 올라갔을 수 있는 경로는 정리 (STORING의 이전 시도 포함)
            storage_cleanup_pending=ArtworkAiRevision.storage_path.isnot(None),
            updated_at=func.now(),
        )
    )


async def revisions_for_photos(
    session: AsyncSession, photo_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    if not photo_ids:
        return []
    return list(
        (
            await session.execute(
                select(ArtworkAiRevision.id).where(
                    ArtworkAiRevision.photo_id.in_(photo_ids),
                    ArtworkAiRevision.deleted_at.is_(None),
                )
            )
        ).scalars()
    )


async def has_live_revisions(session: AsyncSession, photo_id: uuid.UUID) -> bool:
    found = await session.execute(
        select(ArtworkAiRevision.id)
        .where(ArtworkAiRevision.photo_id == photo_id, ArtworkAiRevision.deleted_at.is_(None))
        .limit(1)
    )
    return found.first() is not None


async def release_replaced_originals(session: AsyncSession, photo_ids: list[uuid.UUID]) -> None:
    """수정본 때문에 남겨 둔 교체 전 원본 파일이 더는 참조되지 않으면 정리 대기 (호출자 commit)."""
    for photo_id in set(photo_ids):
        photo = await session.get(ArtworkPhoto, photo_id)
        if (
            photo is None
            or photo.status != PhotoStatus.DELETED
            or photo.storage_cleanup_pending
            or await has_live_revisions(session, photo_id)
            or await is_feedback_reference(session, photo_id)
        ):
            continue
        photo.storage_cleanup_pending = True


async def expire_staged_results(session: AsyncSession, settings: Settings) -> int:
    """Worker 정기 작업: 보관 기간 안에 학생이 열지 않아 Storage에 옮기지 못한 임시 결과 정리.

    임시 이미지를 지우고 FAILED(RESULT_EXPIRED)로 표시한다 (생성 API를 다시 부르지 않음).
    학생은 다시 만들 수 있다 (한도 차감). 호출자가 commit.
    """
    cutoff = clock.utc_now() - timedelta(days=settings.image_edit_staging_retention_days)
    result = await session.execute(
        update(ArtworkAiRevision)
        .where(
            ArtworkAiRevision.status == AiRevisionStatus.STORING,
            ArtworkAiRevision.staged_at < cutoff,
        )
        .values(
            status=AiRevisionStatus.FAILED,
            result_staging=None,
            error_code="RESULT_EXPIRED",
            error_message="The result was not opened in time and was discarded",
            # 이전 저장 시도에서 일부 올라갔을 수 있는 파일은 다음 접속 때 정리
            storage_cleanup_pending=True,
            updated_at=func.now(),
        )
        .returning(ArtworkAiRevision.id)
    )
    return len(result.scalars().all())
