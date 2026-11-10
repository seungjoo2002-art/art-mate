"""AI 처리 Worker: DB 작업 큐(ai_processing_jobs)에서 작업을 가져와 STT·요약을 실행한다.

큐 동작
- 가져가기: `FOR UPDATE SKIP LOCKED`로 1건을 잠그고 RUNNING + lease(만료 시각) 설정 → 여러 Worker가
  같은 작업을 동시에 잡지 않는다.
- 처리 중에는 lease를 주기적으로 연장한다(heartbeat). Worker가 죽으면 lease가 만료되고, 다른
  Worker(또는 재시작한 Worker)가 그 작업을 다시 가져간다 → 서버 재시작 복구. 시도 횟수를 다 쓴
  작업은 WORKER_LOST로 FAILED.
- 실패: 재시도 가능한 오류면 지수 백오프로 QUEUED, 아니면 FAILED.
  사용자는 재시도 API로 새 작업을 만든다.
- 결과 저장 직전에 작업 행을 다시 잠그고 "아직 내가 잡고 있는 RUNNING"인지 확인한다. 그 사이 동의
  철회·녹음 삭제로 취소됐으면 결과를 버린다.

개인정보: 로그에는 작업 ID·종류·오류 코드·소요 시간만 남긴다 (음성·전사·요약 내용·URL 금지).

실행 방식 (v0.9.1)
- 상시 실행: `run_forever` (기존, 서버에 Worker를 띄울 때).
- 일괄 실행: `run_batch` — GitHub Actions처럼 주기적으로 잠깐 켜지는 환경용. 처리할 작업 수·시간을
  제한하고 큐가 비면 바로 끝난다. `job_types`로 이 Worker가 처리할 수 있는 종류만 가져간다
  (예: Gemini 키가 없으면 요약 작업은 큐에 그대로 두어 실패로 만들지 않는다).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import ConflictError
from app.db.session import Database
from app.integrations.ai.gemini import LlmError, SummaryLlm
from app.integrations.ai.stt import SpeechToText, SttError
from app.integrations.supabase.storage import (
    AudioFetcher,
    StorageError,
    StorageObjectNotFound,
    StorageObjectTooLarge,
)
from app.models.ai_feedback import (
    AiProcessingConsent,
    AiProcessingJob,
    FeedbackCategory,
    FeedbackItem,
    FeedbackNote,
    FeedbackReviewHistory,
    FeedbackSummary,
    FeedbackTranscript,
)
from app.models.artwork import Artwork
from app.models.enums import (
    ACTIVE_JOB_STATUSES,
    AiConsentPurpose,
    AiJobStatus,
    AiJobType,
    AiProvider,
    ConsentType,
    FeedbackItemKind,
    FeedbackItemOrigin,
    FeedbackSource,
    FeedbackStatus,
    GrowthScope,
    NarrativeStatus,
    RecommendationSource,
    RecordingStatus,
    ReviewAction,
    ReviewMode,
    TranscriptionStatus,
)
from app.models.growth import GrowthReport
from app.models.recording import FeedbackRecording, RecordingConsent
from app.schemas.growth import Evidence
from app.services.ai_cleanup import consent_version
from app.services.ai_feedback import review_mode_for
from app.services.ai_summary import (
    KIND_FIELDS,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    SYSTEM_INSTRUCTION,
    TEXT_PROMPT_VERSION,
    TEXT_SYSTEM_INSTRUCTION,
    InvalidAiOutput,
    build_prompt,
    build_text_prompt,
    parse_output,
)
from app.services.growth import GrowthService, Scope
from app.services.growth_ai import (
    NARRATIVE_PROMPT_VERSION,
    NARRATIVE_SCHEMA,
    NARRATIVE_SYSTEM,
    RECOMMEND_PROMPT_VERSION,
    RECOMMEND_SCHEMA,
    RECOMMEND_SYSTEM,
    InvalidGrowthOutput,
    build_narrative_prompt,
    build_recommend_prompt,
    parse_narrative,
    parse_recommendations,
)
from app.services.notifications import NotificationService
from app.services.retention import expire_recording_audio

logger = logging.getLogger("app.worker")


class JobFailure(Exception):
    """작업 실패. message는 사용자에게 보여도 되는 짧은 문장 (내용·URL 미포함)."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class JobCancelled(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class _Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class JobRunner:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        *,
        stt: SpeechToText | None,
        llm: SummaryLlm | None,
        fetcher: AudioFetcher,
        worker_id: str | None = None,
        job_types: frozenset[AiJobType] | None = None,
    ) -> None:
        self.database = database
        self.settings = settings
        self.stt = stt
        self.llm = llm
        self.fetcher = fetcher
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        # None = 모든 종류 (기존 동작). 지정하면 그 종류만 가져간다
        self.job_types = job_types

    def _session(self) -> AsyncSession:
        return self.database.session_factory()

    # ------------------------------------------------------------------ queue

    async def claim(self) -> uuid.UUID | None:
        """실행할 작업 1건을 잡는다. 대기 중(QUEUED) 또는 lease가 만료된 RUNNING(죽은 Worker)."""
        lease = timedelta(seconds=self.settings.job_lease_seconds)
        type_filter = " AND job_type = ANY(:types)" if self.job_types is not None else ""
        params = {"types": sorted(t.value for t in self.job_types)} if self.job_types else {}
        if self.job_types is not None and not self.job_types:
            return None
        async with self._session() as session:
            while True:
                row = (
                    await session.execute(
                        text(
                            "SELECT id FROM ai_processing_jobs"
                            " WHERE ((status = 'QUEUED' AND run_after <= now())"
                            "    OR (status = 'RUNNING' AND lease_expires_at < now()))"
                            f"{type_filter}"
                            " ORDER BY run_after, created_at"
                            " LIMIT 1 FOR UPDATE SKIP LOCKED"
                        ),
                        params,
                    )
                ).first()
                if row is None:
                    await session.rollback()
                    return None
                job = await session.get(AiProcessingJob, row[0])
                assert job is not None
                now = clock.utc_now()
                if job.attempts >= job.max_attempts:
                    # 마지막 시도 중 Worker가 죽음 → 더 시도하지 않는다
                    self._finish(job, AiJobStatus.FAILED, now, "WORKER_LOST", "Worker stopped")
                    await self._set_recording_status(session, job, failed=True)
                    await self._on_terminal(session, job, cancelled=False)
                    await session.commit()
                    logger.warning("job abandoned", extra={"job_id": str(job.id)})
                    continue
                recovered = job.status == AiJobStatus.RUNNING
                job.status = AiJobStatus.RUNNING
                job.attempts += 1
                job.locked_by = self.worker_id
                job.lease_expires_at = now + lease
                job.started_at = job.started_at or now
                await session.commit()
                if recovered:
                    logger.info("job recovered", extra={"job_id": str(job.id)})
                return job.id

    async def _heartbeat(self, job_id: uuid.UUID) -> None:
        interval = max(1.0, self.settings.job_lease_seconds / 3)
        lease = timedelta(seconds=self.settings.job_lease_seconds)
        while True:
            await asyncio.sleep(interval)
            async with self._session() as session:
                await session.execute(
                    update(AiProcessingJob)
                    .where(
                        AiProcessingJob.id == job_id,
                        AiProcessingJob.status == AiJobStatus.RUNNING,
                        AiProcessingJob.locked_by == self.worker_id,
                    )
                    .values(lease_expires_at=clock.utc_now() + lease)
                )
                await session.commit()

    async def run_once(self) -> bool:
        """작업 1건 처리. 처리할 작업이 없으면 False."""
        job_id = await self.claim()
        if job_id is None:
            return False
        heartbeat = asyncio.create_task(self._heartbeat(job_id))
        started = time.monotonic()
        try:
            await self._process(job_id)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            logger.info(
                "job processed",
                extra={
                    "job_id": str(job_id),
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                },
            )
        return True

    async def run_batch(
        self, *, max_jobs: int, max_seconds: float, maintenance: bool = True
    ) -> dict[str, int]:
        """일괄 실행: 큐가 비거나 max_jobs·max_seconds에 닿으면 끝난다 (새 작업을 더 잡지 않음).

        진행 중인 작업은 끝까지 처리한다. 실행 환경이 강제로 끝나도 lease가 만료되면 다음 실행이
        이어받는다 (시도 횟수 1 소모).
        """
        started = time.monotonic()
        stats = {"processed": 0, "expired_audio": 0, "notifications": 0}
        if maintenance:
            try:
                stats.update(await self.maintenance())
            except Exception:  # 정기 작업 실패가 큐 처리를 막지 않게
                logger.exception("maintenance error")
        while stats["processed"] < max_jobs and time.monotonic() - started < max_seconds:
            if not await self.run_once():
                break
            stats["processed"] += 1
        logger.info(
            "batch done",
            extra={**stats, "elapsed_ms": int((time.monotonic() - started) * 1000)},
        )
        return stats

    async def pending_counts(self) -> dict[str, int]:
        """지금 가져갈 수 있는 작업 수 (종류별). 내용은 보지 않는다."""
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT job_type, count(*) FROM ai_processing_jobs"
                        " WHERE (status = 'QUEUED' AND run_after <= now())"
                        "    OR (status = 'RUNNING' AND lease_expires_at < now())"
                        " GROUP BY job_type"
                    )
                )
            ).all()
        return {job_type: count for job_type, count in rows}

    async def maintenance(self) -> dict[str, int]:
        """정기 작업 (v0.9): 음성 보관 기간 표시, 미완료 과제·학습 목표 알림. DB만 사용."""
        async with self._session() as session:
            expired = await expire_recording_audio(session, self.settings)
            await session.commit()
        async with self._session() as session:
            notified = await NotificationService(session).sweep_all()
        logger.info("maintenance done", extra={"expired_audio": expired, "notifications": notified})
        return {"expired_audio": expired, "notifications": notified}

    async def run_forever(self, stop: asyncio.Event) -> None:
        logger.info("worker started", extra={"worker_id": self.worker_id})
        next_maintenance = time.monotonic()
        while not stop.is_set():
            if time.monotonic() >= next_maintenance:
                next_maintenance = time.monotonic() + self.settings.worker_maintenance_seconds
                try:
                    await self.maintenance()
                except Exception:  # 정기 작업 실패가 큐 처리를 막지 않게
                    logger.exception("maintenance error")
            try:
                processed = await self.run_once()
            except Exception:  # DB 일시 장애 등: 잠시 쉬고 계속 (작업은 lease 만료로 복구)
                logger.exception("worker loop error")
                processed = False
            if not processed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self.settings.worker_poll_seconds)
        logger.info("worker stopped", extra={"worker_id": self.worker_id})

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _finish(
        job: AiProcessingJob,
        status: AiJobStatus,
        now: Any,
        code: str | None = None,
        message: str | None = None,
    ) -> None:
        job.status = status
        job.finished_at = now
        job.locked_by = None
        job.lease_expires_at = None
        if status != AiJobStatus.SUCCEEDED or code:
            job.last_error_code = code
            job.last_error_message = message
        if status in (AiJobStatus.SUCCEEDED, AiJobStatus.FAILED, AiJobStatus.CANCELLED):
            job.source_url = None
            job.source_url_expires_at = None

    async def _on_terminal(
        self, session: AsyncSession, job: AiProcessingJob, *, cancelled: bool
    ) -> None:
        """작업이 실패·취소로 끝났을 때 연결된 성장 리포트의 설명문 상태를 맞춘다."""
        if job.job_type != AiJobType.GROWTH_REPORT or job.report_id is None:
            return
        await session.execute(
            update(GrowthReport)
            .where(
                GrowthReport.id == job.report_id,
                GrowthReport.narrative_status == NarrativeStatus.PENDING,
            )
            .values(
                narrative_status=NarrativeStatus.SKIPPED if cancelled else NarrativeStatus.FAILED,
                narrative_error_code=job.last_error_code,
                updated_at=func.now(),
            )
        )

    async def _set_recording_status(
        self,
        session: AsyncSession,
        job: AiProcessingJob,
        *,
        failed: bool = False,
        status: TranscriptionStatus | None = None,
    ) -> None:
        if job.job_type != AiJobType.TRANSCRIBE:
            return
        await session.execute(
            update(FeedbackRecording)
            .where(FeedbackRecording.id == job.recording_id)
            .values(
                transcription_status=status
                or (TranscriptionStatus.FAILED if failed else TranscriptionStatus.PENDING),
                transcription_updated_at=func.now(),
                updated_at=func.now(),
            )
        )

    async def _locked_own_job(self, session: AsyncSession, job_id: uuid.UUID) -> AiProcessingJob:
        """결과 저장 직전: 아직 내가 잡은 RUNNING 작업인지 확인 (취소·회수됐으면 JobCancelled)."""
        job = (
            await session.execute(
                select(AiProcessingJob).where(AiProcessingJob.id == job_id).with_for_update()
            )
        ).scalar_one_or_none()
        if job is None or job.status != AiJobStatus.RUNNING or job.locked_by != self.worker_id:
            raise JobCancelled(
                job.last_error_code if job and job.last_error_code else "JOB_CANCELLED"
            )
        return job

    async def _record_usage(self, job_id: uuid.UUID, usage: _Usage) -> None:
        if not usage.calls:
            return
        async with self._session() as session:
            await session.execute(
                update(AiProcessingJob)
                .where(AiProcessingJob.id == job_id)
                .values(
                    api_call_count=AiProcessingJob.api_call_count + usage.calls,
                    input_tokens=AiProcessingJob.input_tokens + usage.input_tokens,
                    output_tokens=AiProcessingJob.output_tokens + usage.output_tokens,
                )
            )
            await session.commit()

    async def _fail(self, job_id: uuid.UUID, failure: JobFailure) -> None:
        async with self._session() as session:
            job = await session.get(AiProcessingJob, job_id, with_for_update=True)
            if job is None or job.status != AiJobStatus.RUNNING or job.locked_by != self.worker_id:
                await session.rollback()
                return
            now = clock.utc_now()
            if failure.retryable and job.attempts < job.max_attempts:
                delay = self.settings.job_retry_base_seconds * (2 ** (job.attempts - 1))
                job.status = AiJobStatus.QUEUED
                job.run_after = now + timedelta(seconds=delay)
                job.locked_by = None
                job.lease_expires_at = None
                job.last_error_code = failure.code
                job.last_error_message = str(failure)
                await self._set_recording_status(session, job)
            else:
                self._finish(job, AiJobStatus.FAILED, now, failure.code, str(failure))
                await self._set_recording_status(session, job, failed=True)
                await self._on_terminal(session, job, cancelled=False)
            await session.commit()
        logger.warning(
            "job failed",
            extra={"job_id": str(job_id), "code": failure.code, "retryable": failure.retryable},
        )

    async def _cancel(self, job_id: uuid.UUID, code: str) -> None:
        async with self._session() as session:
            job = await session.get(AiProcessingJob, job_id, with_for_update=True)
            if (
                job is not None
                and job.status == AiJobStatus.RUNNING
                and job.locked_by == self.worker_id
            ):
                self._finish(job, AiJobStatus.CANCELLED, clock.utc_now(), code, None)
                await self._set_recording_status(session, job, failed=True)
                await self._on_terminal(session, job, cancelled=True)
            await session.commit()
        logger.info("job cancelled", extra={"job_id": str(job_id), "code": code})

    async def _process(self, job_id: uuid.UUID) -> None:
        async with self._session() as session:
            job = await session.get(AiProcessingJob, job_id)
            assert job is not None
            job_type = job.job_type
        handlers: dict[AiJobType, Callable[[uuid.UUID], Awaitable[None]]] = {
            AiJobType.TRANSCRIBE: self._transcribe,
            AiJobType.SUMMARIZE: self._summarize,
            AiJobType.GROWTH_REPORT: self._growth_report,
            AiJobType.PRACTICE_RECOMMEND: self._practice_recommend,
        }
        handler = handlers[job_type]
        try:
            await handler(job_id)
        except JobCancelled as cancelled:
            await self._cancel(job_id, cancelled.code)
        except JobFailure as failure:
            await self._fail(job_id, failure)
        except Exception as exc:  # 예상 못한 오류: 재시도 (내용은 로그에 남기지 않음)
            logger.exception("job crashed", extra={"job_id": str(job_id)})
            await self._fail(
                job_id, JobFailure("INTERNAL_ERROR", type(exc).__name__, retryable=True)
            )

    # ------------------------------------------------------------------ checks

    async def _load_recording(
        self, session: AsyncSession, job: AiProcessingJob
    ) -> tuple[FeedbackRecording, Artwork]:
        row = (
            await session.execute(
                select(FeedbackRecording, Artwork)
                .join(Artwork, Artwork.id == FeedbackRecording.artwork_id)
                .where(FeedbackRecording.id == job.recording_id)
            )
        ).one_or_none()
        if row is None or row[0].status != RecordingStatus.ACTIVE or row[1].deleted_at is not None:
            raise JobCancelled("RECORDING_DELETED")
        return row[0], row[1]

    async def _check_recording_consent(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        found = (
            await session.execute(
                select(RecordingConsent.id).where(
                    RecordingConsent.user_id == owner_id,
                    RecordingConsent.consent_type == ConsentType.VOICE_RECORDING,
                    RecordingConsent.revoked_at.is_(None),
                )
            )
        ).first()
        if found is None:
            raise JobCancelled("RECORDING_CONSENT_REVOKED")

    async def _check_ai_consent(
        self,
        session: AsyncSession,
        owner_id: uuid.UUID,
        purpose: AiConsentPurpose = AiConsentPurpose.FEEDBACK_SUMMARY,
    ) -> None:
        version = (
            await session.execute(
                select(AiProcessingConsent.policy_version).where(
                    AiProcessingConsent.user_id == owner_id,
                    AiProcessingConsent.provider == AiProvider.GOOGLE_GEMINI,
                    AiProcessingConsent.purpose == purpose,
                    AiProcessingConsent.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if version != consent_version(self.settings, purpose):
            raise JobCancelled("AI_CONSENT_REVOKED")

    # ------------------------------------------------------------------ TRANSCRIBE

    async def _transcribe(self, job_id: uuid.UUID) -> None:
        settings = self.settings
        async with self._session() as session:
            job = await session.get(AiProcessingJob, job_id)
            assert job is not None
            await self._load_recording(session, job)
            await self._check_recording_consent(session, job.owner_id)
            if self.stt is None:
                raise JobFailure(
                    "STT_NOT_CONFIGURED", "STT is not enabled on the worker", retryable=False
                )
            if not job.source_url or (
                job.source_url_expires_at is not None
                and job.source_url_expires_at <= clock.utc_now()
            ):
                raise JobFailure(
                    "SOURCE_URL_EXPIRED", "Request the transcription again", retryable=False
                )
            source_url = job.source_url
            await self._set_recording_status(session, job, status=TranscriptionStatus.PROCESSING)
            await session.commit()

        try:
            audio = await self.fetcher.fetch(
                source_url, max_bytes=settings.recording_max_upload_bytes
            )
        except StorageObjectNotFound:
            raise JobFailure(
                "AUDIO_NOT_FOUND", "The audio file is missing", retryable=False
            ) from None
        except StorageObjectTooLarge:
            raise JobFailure(
                "AUDIO_TOO_LARGE", "The audio file is too large", retryable=False
            ) from None
        except StorageError:
            raise JobFailure(
                "STORAGE_UNAVAILABLE", "Storage is unavailable", retryable=True
            ) from None

        stt = self.stt
        started = time.monotonic()
        deadline = started + settings.stt_timeout_seconds
        try:
            result = await asyncio.to_thread(
                stt.transcribe,
                audio,
                language=settings.stt_language,
                deadline=deadline,
                max_audio_seconds=settings.stt_max_audio_seconds,
            )
        except SttError as exc:
            raise JobFailure(exc.code, str(exc), retryable=exc.retryable) from None
        finally:
            del audio
        processing_ms = int((time.monotonic() - started) * 1000)

        async with self._session() as session:
            job = await self._locked_own_job(session, job_id)
            await self._load_recording(session, job)
            await self._check_recording_consent(session, job.owner_id)
            transcript = FeedbackTranscript(
                id=uuid.uuid4(),
                recording_id=job.recording_id,
                artwork_id=job.artwork_id,
                owner_id=job.owner_id,
                job_id=job.id,
                language=result.language,
                duration_ms=result.duration_ms,
                text=result.text,
                segments=[
                    {"index": s.index, "start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text}
                    for s in result.segments
                ],
                segment_count=len(result.segments),
                engine=result.engine,
                model_name=result.model_name,
                processing_ms=processing_ms,
            )
            session.add(transcript)
            self._finish(job, AiJobStatus.SUCCEEDED, clock.utc_now())
            job.last_error_code = None
            job.last_error_message = None
            await self._set_recording_status(session, job, status=TranscriptionStatus.COMPLETED)
            await session.flush()
            if job.params.get("chain_summary"):
                await self._chain_summary(session, job, transcript)
            await session.commit()

    async def _chain_summary(
        self, session: AsyncSession, job: AiProcessingJob, transcript: FeedbackTranscript
    ) -> None:
        """전사 후 자동 요약: 설정이 켜져 있고 그 시점에 학생의 AI 전송 동의가 있을 때만."""
        if not self.settings.ai_summary_enabled:
            return
        try:
            await self._check_ai_consent(session, job.owner_id)
        except JobCancelled:
            return
        exists = (
            await session.execute(
                select(AiProcessingJob.id).where(
                    AiProcessingJob.recording_id == job.recording_id,
                    AiProcessingJob.job_type == AiJobType.SUMMARIZE,
                    AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                )
            )
        ).first()
        current = (
            await session.execute(
                select(FeedbackSummary.id).where(
                    FeedbackSummary.recording_id == job.recording_id,
                    FeedbackSummary.status.in_(
                        [FeedbackStatus.DRAFT, FeedbackStatus.IN_REVIEW, FeedbackStatus.APPROVED]
                    ),
                )
            )
        ).first()
        if exists or current:
            return
        session.add(
            AiProcessingJob(
                id=uuid.uuid4(),
                job_type=AiJobType.SUMMARIZE,
                status=AiJobStatus.QUEUED,
                recording_id=job.recording_id,
                artwork_id=job.artwork_id,
                owner_id=job.owner_id,
                requested_by=job.requested_by,
                attempts=0,
                max_attempts=self.settings.job_max_attempts,
                run_after=clock.utc_now(),
                params={"transcript_id": str(transcript.id)},
            )
        )

    # ------------------------------------------------------------------ SUMMARIZE

    async def _summarize(self, job_id: uuid.UUID) -> None:
        settings = self.settings
        async with self._session() as session:
            job = await session.get(AiProcessingJob, job_id)
            assert job is not None
            is_note = job.note_id is not None
        if is_note:
            await self._summarize_note(job_id)
            return
        async with self._session() as session:
            job = await session.get(AiProcessingJob, job_id)
            assert job is not None
            await self._load_recording(session, job)
            await self._check_ai_consent(session, job.owner_id)
            transcript = None
            transcript_id = job.params.get("transcript_id")
            if transcript_id:
                transcript = await session.get(FeedbackTranscript, uuid.UUID(transcript_id))
            if transcript is None:
                raise JobFailure("TRANSCRIPT_NOT_FOUND", "Transcript is missing", retryable=False)
            approved = (
                await session.execute(
                    select(FeedbackSummary.id).where(
                        FeedbackSummary.recording_id == job.recording_id,
                        FeedbackSummary.status == FeedbackStatus.APPROVED,
                    )
                )
            ).first()
            if approved is not None:
                raise JobCancelled("FEEDBACK_ALREADY_APPROVED")
            if len(transcript.text) > settings.ai_max_transcript_chars:
                raise JobFailure(
                    "TRANSCRIPT_TOO_LONG", "Transcript is too long to summarize", retryable=False
                )
            if self.llm is None:
                raise JobFailure("AI_NOT_CONFIGURED", "AI summary is not enabled", retryable=False)
            segments = list(transcript.segments)
            segment_count = transcript.segment_count
            transcript_pk = transcript.id

        # 외부 전송: 구간 번호·시각·문장만 (이름·학원·작품 정보·ID 미포함)
        usage = _Usage()
        try:
            response = await self.llm.generate(
                system=SYSTEM_INSTRUCTION, prompt=build_prompt(segments), schema=RESPONSE_SCHEMA
            )
            usage.calls += 1
            usage.input_tokens += response.input_tokens
            usage.output_tokens += response.output_tokens
        except LlmError as exc:
            if exc.called:
                usage.calls += 1
                usage.input_tokens += exc.input_tokens
                usage.output_tokens += exc.output_tokens
            await self._record_usage(job_id, usage)
            raise JobFailure(exc.code, str(exc), retryable=exc.retryable) from None
        await self._record_usage(job_id, usage)

        try:
            output, dropped = parse_output(
                response.text, segment_count, [s["text"] for s in segments]
            )
        except InvalidAiOutput:
            raise JobFailure(
                "LLM_INVALID_OUTPUT", "AI response did not match the schema", retryable=True
            ) from None

        async with self._session() as session:
            job = await self._locked_own_job(session, job_id)
            _, artwork = await self._load_recording(session, job)
            # 호출 중 동의를 철회했으면 결과를 저장하지 않는다
            await self._check_ai_consent(session, job.owner_id)
            await self._store_summary(
                session,
                job,
                FeedbackSummary.recording_id == job.recording_id,
                mode=review_mode_for(artwork),
                source=FeedbackSource.INSTRUCTOR,
                refs={"recording_id": job.recording_id, "transcript_id": transcript_pk},
                output=output,
                response=response,
                dropped=dropped,
                prompt_version=PROMPT_VERSION,
            )
            await session.commit()

    async def _store_summary(
        self,
        session: AsyncSession,
        job: AiProcessingJob,
        same_source: Any,
        *,
        mode: ReviewMode,
        source: FeedbackSource,
        refs: dict[str, Any],
        output: Any,
        response: Any,
        dropped: int,
        prompt_version: str,
    ) -> None:
        """AI 초안 저장 (녹음·텍스트 공통): 이전 초안 대체 → 첨삭·항목·카테고리·이력."""
        previous = list(
            (
                await session.execute(
                    select(FeedbackSummary)
                    .where(
                        same_source,
                        FeedbackSummary.status.in_(
                            [
                                FeedbackStatus.DRAFT,
                                FeedbackStatus.IN_REVIEW,
                                FeedbackStatus.APPROVED,
                            ]
                        ),
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        if any(p.status == FeedbackStatus.APPROVED for p in previous):
            raise JobCancelled("FEEDBACK_ALREADY_APPROVED")
        for old in previous:
            from_status = old.status
            old.status = FeedbackStatus.SUPERSEDED
            old.version += 1
            session.add(
                FeedbackReviewHistory(
                    id=uuid.uuid4(),
                    summary_id=old.id,
                    actor_id=None,
                    actor_mode=None,
                    action=ReviewAction.SUPERSEDED,
                    from_status=from_status,
                    to_status=FeedbackStatus.SUPERSEDED,
                    version=old.version,
                )
            )
        await session.flush()

        summary = FeedbackSummary(
            id=uuid.uuid4(),
            artwork_id=job.artwork_id,
            owner_id=job.owner_id,
            job_id=job.id,
            status=FeedbackStatus.DRAFT,
            review_mode=mode,
            source=source,
            version=1,
            summary=output.summary,
            ai_output=output.model_dump(mode="json"),
            model_name=response.model_name,
            prompt_version=prompt_version,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            dropped_item_count=dropped,
            **refs,
        )
        session.add(summary)
        await session.flush()
        for kind, field in KIND_FIELDS.items():
            for position, item in enumerate(getattr(output, field)):
                session.add(
                    FeedbackItem(
                        id=uuid.uuid4(),
                        summary_id=summary.id,
                        kind=FeedbackItemKind(kind),
                        position=position,
                        content=item.text,
                        category=item.category,
                        evidence_segment_ids=item.evidence,
                        origin=FeedbackItemOrigin.AI,
                    )
                )
        for category in output.weakness_categories:
            session.add(
                FeedbackCategory(
                    id=uuid.uuid4(),
                    summary_id=summary.id,
                    category=category,
                    origin=FeedbackItemOrigin.AI,
                )
            )
        session.add(
            FeedbackReviewHistory(
                id=uuid.uuid4(),
                summary_id=summary.id,
                actor_id=None,
                actor_mode=None,
                action=ReviewAction.CREATED,
                from_status=None,
                to_status=FeedbackStatus.DRAFT,
                version=1,
                note=f"{response.model_name} / {prompt_version}",
            )
        )
        self._finish(job, AiJobStatus.SUCCEEDED, clock.utc_now())
        job.last_error_code = None
        job.last_error_message = None

    # ------------------------------------------------------------------ SUMMARIZE (텍스트, v0.9)

    async def _load_note(
        self, session: AsyncSession, job: AiProcessingJob
    ) -> tuple[FeedbackNote, Artwork]:
        row = (
            await session.execute(
                select(FeedbackNote, Artwork)
                .join(Artwork, Artwork.id == FeedbackNote.artwork_id)
                .where(FeedbackNote.id == job.note_id)
            )
        ).one_or_none()
        if row is None or row[1].deleted_at is not None:
            raise JobCancelled("NOTE_DELETED")
        expected = job.params.get("note_version")
        if expected is not None and expected != row[0].version:
            raise JobCancelled("NOTE_CHANGED")
        return row[0], row[1]

    async def _summarize_note(self, job_id: uuid.UUID) -> None:
        async with self._session() as session:
            job = await session.get(AiProcessingJob, job_id)
            assert job is not None
            note, _ = await self._load_note(session, job)
            await self._check_ai_consent(session, job.owner_id)
            approved = (
                await session.execute(
                    select(FeedbackSummary.id).where(
                        FeedbackSummary.note_id == job.note_id,
                        FeedbackSummary.status == FeedbackStatus.APPROVED,
                    )
                )
            ).first()
            if approved is not None:
                raise JobCancelled("FEEDBACK_ALREADY_APPROVED")
            if self.llm is None:
                raise JobFailure("AI_NOT_CONFIGURED", "AI summary is not enabled", retryable=False)
            segments = list(note.segments)
            segment_count = note.segment_count

        # 외부 전송: 문장 번호와 문장만 (출처·이름·학원·작품 정보·ID 미포함)
        response = await self._call_llm(
            job_id, TEXT_SYSTEM_INSTRUCTION, build_text_prompt(segments), RESPONSE_SCHEMA
        )
        try:
            output, dropped = parse_output(
                response.text, segment_count, [s["text"] for s in segments]
            )
        except InvalidAiOutput:
            raise JobFailure(
                "LLM_INVALID_OUTPUT", "AI response did not match the schema", retryable=True
            ) from None

        async with self._session() as session:
            job = await self._locked_own_job(session, job_id)
            note, artwork = await self._load_note(session, job)
            await self._check_ai_consent(session, job.owner_id)
            await self._store_summary(
                session,
                job,
                FeedbackSummary.note_id == note.id,
                mode=review_mode_for(artwork, note.source),
                source=note.source,
                refs={"note_id": note.id},
                output=output,
                response=response,
                dropped=dropped,
                prompt_version=TEXT_PROMPT_VERSION,
            )
            await session.commit()

    # ------------------------------------------------------------------ v0.7 성장 코치

    async def _call_llm(
        self, job_id: uuid.UUID, system: str, prompt: str, schema: dict[str, Any]
    ) -> Any:
        assert self.llm is not None
        usage = _Usage()
        try:
            response = await self.llm.generate(system=system, prompt=prompt, schema=schema)
            usage.calls += 1
            usage.input_tokens += response.input_tokens
            usage.output_tokens += response.output_tokens
        except LlmError as exc:
            if exc.called:
                usage.calls += 1
                usage.input_tokens += exc.input_tokens
                usage.output_tokens += exc.output_tokens
            await self._record_usage(job_id, usage)
            raise JobFailure(exc.code, str(exc), retryable=exc.retryable) from None
        await self._record_usage(job_id, usage)
        return response

    @staticmethod
    def _evidence_entries(evidence: list[Evidence]) -> list[dict[str, Any]]:
        """프롬프트에 넣는 근거: 카테고리·종류·문장만 (작품 제목·이름·ID 미포함)."""
        return [
            {
                "item_id": str(e.item_id),
                "feedback_id": str(e.feedback_id),
                "artwork_id": str(e.artwork_id),
                "category": e.category.value if e.category else None,
                "kind": e.kind.value,
                "content": e.content,
            }
            for e in evidence
        ]

    async def _growth_report(self, job_id: uuid.UUID) -> None:
        async with self._session() as session:
            job = await session.get(AiProcessingJob, job_id)
            assert job is not None
            report = await session.get(GrowthReport, job.report_id) if job.report_id else None
            if report is None:
                raise JobCancelled("REPORT_DELETED")
            await self._check_ai_consent(session, job.owner_id, AiConsentPurpose.GROWTH_COACHING)
            if self.llm is None:
                raise JobFailure("AI_NOT_CONFIGURED", "AI is not enabled", retryable=False)
            scope = Scope(report.owner_id, report.scope, report.academy_id)
            metrics = report.metrics
            ids: list[str] = []
            for w in metrics["weaknesses"][:5]:
                ids += [e["item_id"] for e in w["evidence"]]
            for st in metrics["strengths"][:3]:
                ids += [e["item_id"] for e in st["evidence"]]
            resolved = await GrowthService(session, self.settings).resolve_evidence(scope, ids)
            ordered = list(dict.fromkeys(i for i in ids if i in resolved))[:15]
            evidence = self._evidence_entries([resolved[i] for i in ordered])

        response = await self._call_llm(
            job_id, NARRATIVE_SYSTEM, build_narrative_prompt(metrics, evidence), NARRATIVE_SCHEMA
        )
        try:
            output = parse_narrative(response.text, len(evidence))
        except InvalidGrowthOutput:
            raise JobFailure(
                "LLM_INVALID_OUTPUT", "AI response did not pass validation", retryable=True
            ) from None

        async with self._session() as session:
            job = await self._locked_own_job(session, job_id)
            await self._check_ai_consent(session, job.owner_id, AiConsentPurpose.GROWTH_COACHING)
            report = await session.get(GrowthReport, job.report_id, with_for_update=True)
            if report is None:
                raise JobCancelled("REPORT_DELETED")
            report.narrative = {
                "overview": output.overview,
                "strengths_comment": output.strengths_comment,
                "improvement_comment": output.improvement_comment,
                "next_goals": [
                    {
                        "goal": g.goal,
                        "evidence_item_ids": [evidence[i - 1]["item_id"] for i in g.evidence],
                    }
                    for g in output.next_goals
                ],
            }
            report.narrative_status = NarrativeStatus.READY
            report.narrative_error_code = None
            report.model_name = response.model_name
            report.prompt_version = NARRATIVE_PROMPT_VERSION
            report.input_tokens = response.input_tokens
            report.output_tokens = response.output_tokens
            self._finish(job, AiJobStatus.SUCCEEDED, clock.utc_now())
            job.last_error_code = None
            job.last_error_message = None
            await session.commit()

    async def _practice_recommend(self, job_id: uuid.UUID) -> None:
        async with self._session() as session:
            job = await session.get(AiProcessingJob, job_id)
            assert job is not None
            await self._check_ai_consent(session, job.owner_id, AiConsentPurpose.GROWTH_COACHING)
            if self.llm is None:
                raise JobFailure("AI_NOT_CONFIGURED", "AI is not enabled", retryable=False)
            params = job.params
            scope = Scope(
                job.owner_id,
                GrowthScope(params["scope"]),
                uuid.UUID(params["academy_id"]) if params.get("academy_id") else None,
                uuid.UUID(params["student_membership_id"])
                if params.get("student_membership_id")
                else None,
            )
            service = GrowthService(session, self.settings)
            _, metrics, _ = await service.recommendation_basis(scope)
            try:
                categories = service._check_recommendable(metrics)
            except ConflictError:
                raise JobFailure(
                    "INSUFFICIENT_DATA", "Not enough approved feedback", retryable=False
                ) from None
            by_category = {w["category"]: w for w in metrics["weaknesses"]}
            ids = [e["item_id"] for c in categories for e in by_category[c]["evidence"]]
            resolved = await service.resolve_evidence(scope, ids)
            evidence = self._evidence_entries([resolved[i] for i in ids if i in resolved])
            practical = service._main_practical_type(metrics)

        response = await self._call_llm(
            job_id,
            RECOMMEND_SYSTEM,
            build_recommend_prompt(metrics, evidence, categories, practical),
            RECOMMEND_SCHEMA,
        )
        try:
            recommendations, dropped = parse_recommendations(response.text, evidence, categories)
        except InvalidGrowthOutput:
            raise JobFailure(
                "LLM_INVALID_OUTPUT", "AI response did not pass validation", retryable=True
            ) from None

        async with self._session() as session:
            job = await self._locked_own_job(session, job_id)
            await self._check_ai_consent(session, job.owner_id, AiConsentPurpose.GROWTH_COACHING)
            service = GrowthService(session, self.settings)
            batch_key = params["batch_key"]
            if not await service._batch(scope, batch_key):
                await service.supersede_open(scope, batch_key, job.requested_by)
                for rec in recommendations:
                    stat = by_category[rec.category.value]
                    refs = [evidence[i - 1] for i in rec.evidence]
                    service._new_recommendation(
                        scope,
                        RecommendationSource.AI,
                        batch_key,
                        rec.category,
                        practical,
                        title=rec.title,
                        description=rec.description,
                        steps=list(rec.steps),
                        minutes=rec.estimated_minutes,
                        difficulty=rec.difficulty,
                        reason=rec.reason,
                        origin={
                            **rec.model_dump(mode="json"),
                            "evidence_item_ids": [r["item_id"] for r in refs],
                            "dropped_recommendation_count": dropped,
                        },
                        evidence=refs,
                        metrics=metrics,
                        stat=stat,
                        actor_id=job.requested_by,
                        model_name=response.model_name,
                        prompt_version=RECOMMEND_PROMPT_VERSION,
                    )
                if scope.scope == GrowthScope.PERSONAL:
                    await session.flush()
                    await NotificationService(session).tasks_recommended(
                        scope.owner_id, await service._batch(scope, batch_key), f"recs:{batch_key}"
                    )
            self._finish(job, AiJobStatus.SUCCEEDED, clock.utc_now())
            job.last_error_code = None
            job.last_error_message = None
            await session.commit()
