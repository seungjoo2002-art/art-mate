"""음성 원본 보관 기간 (v0.9 F-3 개인정보).

- 업로드 후 `recording_audio_retention_days`(기본 180일)가 지난 음성 파일만 삭제한다.
  전사·첨삭(학습 기록)은 학생이 지우기 전까지 남는다. 0이면 기한 없음.
- 진행 중인 전사 작업이 있는 녹음은 건너뛴다 (다음 정리 때 처리).
- 서버는 service_role 키를 쓰지 않으므로 여기서는 DB에 표시(audio_deleted_at,
  storage_cleanup_pending)만 하고, 실제 파일 삭제는 학생 토큰으로 하는 기존 정리 경로
  (RecordingService.cleanup_storage)가 다음 요청 때 수행한다.
- 녹음·전사문은 AI 모델 학습 데이터로 수집하지 않는다 (학습용 수집 기능 없음).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import and_, exists, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.models.ai_feedback import AiProcessingJob
from app.models.enums import ACTIVE_JOB_STATUSES, AiJobType, RecordingStatus
from app.models.recording import FeedbackRecording


async def expire_recording_audio(
    session: AsyncSession, settings: Settings, *, owner_id: uuid.UUID | None = None
) -> int:
    """보관 기간이 지난 음성을 삭제 대상으로 표시하고 개수를 돌려준다 (commit은 호출자)."""
    days = settings.recording_audio_retention_days
    if days <= 0:
        return 0
    cutoff = clock.utc_now() - timedelta(days=days)
    running = exists().where(
        and_(
            AiProcessingJob.recording_id == FeedbackRecording.id,
            AiProcessingJob.job_type == AiJobType.TRANSCRIBE,
            AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    stmt = (
        update(FeedbackRecording)
        .where(
            FeedbackRecording.status == RecordingStatus.ACTIVE,
            FeedbackRecording.audio_deleted_at.is_(None),
            func.coalesce(FeedbackRecording.uploaded_at, FeedbackRecording.created_at) < cutoff,
            ~running,
        )
        .values(audio_deleted_at=func.now(), storage_cleanup_pending=True, updated_at=func.now())
        .returning(FeedbackRecording.id)
    )
    if owner_id is not None:
        stmt = stmt.where(FeedbackRecording.owner_id == owner_id)
    return len((await session.execute(stmt)).all())
