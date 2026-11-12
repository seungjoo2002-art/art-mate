"""AI 기능 설정 안내(운영자 로그)와 사용자별 요약 요청 한도.

사용자 화면에는 설정 이름·키·내부 오류를 보여 주지 않고, 무엇을 켜야 하는지는 서버 로그에만 남긴다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import RateLimitedError
from app.models.ai_feedback import AiProcessingJob
from app.models.enums import AiJobType

logger = logging.getLogger("app.ai.setup")

STT_SETUP = (
    "server transcription requested but STT_ENABLED is not true on the API service (Render). "
    "Set STT_ENABLED=true on Render; transcription runs in the GitHub Actions stt-worker "
    "(needs secret WORKER_DATABASE_URL). Browser transcription still works."
)
SUMMARY_SETUP = (
    "AI summary requested but it is not active on the API service (Render). "
    "Set AI_SUMMARY_ENABLED=true and, after confirming a paid Gemini tier and the provider terms "
    "(age clause, guardian consent), AI_PROVIDER_TERMS_CONFIRMED=true on Render; in GitHub Actions "
    "set variables AI_SUMMARY_ENABLED=true, AI_PROVIDER_TERMS_CONFIRMED=true and secret "
    "GEMINI_API_KEY (summaries are processed by stt-worker)."
)


def log_stt_disabled(where: str) -> None:
    logger.warning(STT_SETUP, extra={"where": where, "setting": "STT_ENABLED"})


def log_summary_disabled(where: str) -> None:
    logger.warning(SUMMARY_SETUP, extra={"where": where, "setting": "AI_SUMMARY_ENABLED"})


async def check_summary_quota(
    session: AsyncSession, settings: Settings, owner_id: uuid.UUID
) -> None:
    """오늘(Asia/Seoul) 이 학생이 만든 요약 작업 수가 한도 이상이면 429."""
    limit = settings.ai_summary_daily_limit
    if limit <= 0:
        return
    start, _ = clock.local_day_bounds(clock.local_today())
    used = (
        await session.execute(
            select(func.count())
            .select_from(AiProcessingJob)
            .where(
                AiProcessingJob.owner_id == owner_id,
                AiProcessingJob.job_type == AiJobType.SUMMARIZE,
                AiProcessingJob.created_at >= start,
            )
        )
    ).scalar_one()
    if used >= limit:
        retry = int((start + timedelta(days=1) - clock.utc_now()).total_seconds()) + 1
        raise RateLimitedError(
            "Daily AI summary limit reached; try again tomorrow",
            details={"limit": limit},
            headers={"Retry-After": str(max(retry, 1))},
        )
