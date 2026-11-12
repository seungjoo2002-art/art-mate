"""AI 처리 데이터 정리 (녹음 삭제·동의 철회 시). 모델만 import → 다른 서비스에서 순환 없이 호출.

- 녹음·작품 삭제: 진행 중 작업 취소 + 전사·첨삭(항목·카테고리·이력 CASCADE) 삭제.
  학생이 녹음을 지우면 그 녹음에서 나온 텍스트도 남기지 않는다 (승인된 첨삭 포함).
- 동의 철회: 대기·실행 중 작업을 CANCELLED로 바꾼다. 실행 중인 Worker는 결과를 저장하기 직전에
  작업 상태를 다시 확인하므로 결과가 저장되지 않는다. 이미 저장된 전사·첨삭은 유지한다
  (학생이 녹음을 삭제하면 함께 삭제).
- 호출자가 commit 한다.
"""

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.ai_feedback import AiProcessingJob, FeedbackSummary, FeedbackTranscript
from app.models.enums import (
    ACTIVE_JOB_STATUSES,
    AiConsentPurpose,
    AiJobStatus,
    AiJobType,
    NarrativeStatus,
    TranscriptionStatus,
)
from app.models.growth import GrowthReport
from app.models.recording import FeedbackRecording

# 동의 목적별로 취소할 작업 종류
PURPOSE_JOB_TYPES: dict[AiConsentPurpose, tuple[AiJobType, ...]] = {
    AiConsentPurpose.FEEDBACK_SUMMARY: (AiJobType.SUMMARIZE,),
    AiConsentPurpose.GROWTH_COACHING: (AiJobType.GROWTH_REPORT, AiJobType.PRACTICE_RECOMMEND),
}


def consent_version(settings: Settings, purpose: AiConsentPurpose) -> str:
    """현재 동의서 버전 (판정 규칙 전체는 ai_consent_policy.evaluate)."""
    if purpose == AiConsentPurpose.GROWTH_COACHING:
        return settings.ai_growth_consent_version
    return settings.ai_consent_version


async def skip_pending_narratives(session: AsyncSession, owner_id: uuid.UUID) -> None:
    """성장 분석 동의 철회: 생성 대기 중인 리포트 설명문을 건너뜀 처리."""
    await session.execute(
        update(GrowthReport)
        .where(
            GrowthReport.owner_id == owner_id,
            GrowthReport.narrative_status == NarrativeStatus.PENDING,
        )
        .values(
            narrative_status=NarrativeStatus.SKIPPED,
            narrative_error_code="AI_CONSENT_REVOKED",
            updated_at=func.now(),
        )
    )


def _cancel_values(code: str) -> dict:  # type: ignore[type-arg]
    return {
        "status": AiJobStatus.CANCELLED,
        "last_error_code": code,
        "last_error_message": None,
        "source_url": None,
        "source_url_expires_at": None,
        "locked_by": None,
        "lease_expires_at": None,
        "finished_at": func.now(),
        "updated_at": func.now(),
    }


async def purge_for_recordings(session: AsyncSession, recording_ids: list[uuid.UUID]) -> None:
    if not recording_ids:
        return
    await session.execute(
        update(AiProcessingJob)
        .where(
            AiProcessingJob.recording_id.in_(recording_ids),
            AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        .values(**_cancel_values("RECORDING_DELETED"))
    )
    # v0.7: 이 녹음의 첨삭을 근거로 쓴 성장 리포트의 AI 설명문을 지운다 (통계 숫자는 유지).
    # 근거 문장은 ID로만 저장하므로 첨삭이 삭제되면 조회 시 자동으로 빠진다.
    summary_ids = [
        str(i)
        for i in (
            await session.execute(
                select(FeedbackSummary.id).where(FeedbackSummary.recording_id.in_(recording_ids))
            )
        ).scalars()
    ]
    if summary_ids:
        await session.execute(
            update(GrowthReport)
            .where(GrowthReport.source_feedback_ids.overlap(summary_ids))
            .values(
                narrative=None,
                narrative_status=NarrativeStatus.INVALIDATED,
                narrative_error_code="SOURCE_FEEDBACK_DELETED",
                updated_at=func.now(),
            )
        )
    await session.execute(
        delete(FeedbackSummary).where(FeedbackSummary.recording_id.in_(recording_ids))
    )
    await session.execute(
        delete(FeedbackTranscript).where(FeedbackTranscript.recording_id.in_(recording_ids))
    )


async def cancel_jobs_for_owner(
    session: AsyncSession, owner_id: uuid.UUID, job_type: AiJobType, code: str
) -> list[uuid.UUID]:
    """소유자의 진행 중 작업 취소. 전사 작업이면 녹음의 전사 상태도 FAILED로 바꾼다."""
    cancelled = (
        (
            await session.execute(
                update(AiProcessingJob)
                .where(
                    AiProcessingJob.owner_id == owner_id,
                    AiProcessingJob.job_type == job_type,
                    AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                )
                .values(**_cancel_values(code))
                .returning(AiProcessingJob.recording_id)
            )
        )
        .scalars()
        .all()
    )
    if cancelled and job_type == AiJobType.TRANSCRIBE:
        await session.execute(
            update(FeedbackRecording)
            .where(FeedbackRecording.id.in_(cancelled))
            .values(
                transcription_status=TranscriptionStatus.FAILED,
                transcription_updated_at=func.now(),
                updated_at=func.now(),
            )
        )
    return list(cancelled)
