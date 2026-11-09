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
    FeedbackReviewHistory,
    FeedbackSummary,
    FeedbackTranscript,
)
from app.models.artwork import Artwork
from app.models.enums import (
    ACTIVE_JOB_STATUSES,
    AiJobStatus,
    AiJobType,
    AiProvider,
    ConsentType,
    FeedbackItemKind,
    FeedbackItemOrigin,
    FeedbackStatus,
    RecordingStatus,
    ReviewAction,
    ReviewMode,
    TranscriptionStatus,
)
from app.models.recording import FeedbackRecording, RecordingConsent
from app.services.ai_summary import (
    KIND_FIELDS,
    PROMPT_VERSION,
    RESPONSE_SCHEMA,
    SYSTEM_INSTRUCTION,
    InvalidAiOutput,
    build_prompt,
    parse_output,
)

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
    ) -> None:
        self.database = database
        self.settings = settings
        self.stt = stt
        self.llm = llm
        self.fetcher = fetcher
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:12]}"

    def _session(self) -> AsyncSession:
        return self.database.session_factory()

    # ------------------------------------------------------------------ queue

    async def claim(self) -> uuid.UUID | None:
        """실행할 작업 1건을 잡는다. 대기 중(QUEUED) 또는 lease가 만료된 RUNNING(죽은 Worker)."""
        lease = timedelta(seconds=self.settings.job_lease_seconds)
        async with self._session() as session:
            while True:
                row = (
                    await session.execute(
                        text(
                            "SELECT id FROM ai_processing_jobs"
                            " WHERE (status = 'QUEUED' AND run_after <= now())"
                            "    OR (status = 'RUNNING' AND lease_expires_at < now())"
                            " ORDER BY run_after, created_at"
                            " LIMIT 1 FOR UPDATE SKIP LOCKED"
                        )
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

    async def run_forever(self, stop: asyncio.Event) -> None:
        logger.info("worker started", extra={"worker_id": self.worker_id})
        while not stop.is_set():
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
            await session.commit()
        logger.info("job cancelled", extra={"job_id": str(job_id), "code": code})

    async def _process(self, job_id: uuid.UUID) -> None:
        async with self._session() as session:
            job = await session.get(AiProcessingJob, job_id)
            assert job is not None
            job_type = job.job_type
        handler: Callable[[uuid.UUID], Awaitable[None]] = (
            self._transcribe if job_type == AiJobType.TRANSCRIBE else self._summarize
        )
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

    async def _check_ai_consent(self, session: AsyncSession, owner_id: uuid.UUID) -> None:
        version = (
            await session.execute(
                select(AiProcessingConsent.policy_version).where(
                    AiProcessingConsent.user_id == owner_id,
                    AiProcessingConsent.provider == AiProvider.GOOGLE_GEMINI,
                    AiProcessingConsent.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if version != self.settings.ai_consent_version:
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
            output, dropped = parse_output(response.text, segment_count)
        except InvalidAiOutput:
            raise JobFailure(
                "LLM_INVALID_OUTPUT", "AI response did not match the schema", retryable=True
            ) from None

        async with self._session() as session:
            job = await self._locked_own_job(session, job_id)
            _, artwork = await self._load_recording(session, job)
            # 호출 중 동의를 철회했으면 결과를 저장하지 않는다
            await self._check_ai_consent(session, job.owner_id)
            mode = ReviewMode.SELF if artwork.academy_id is None else ReviewMode.INSTRUCTOR
            previous = list(
                (
                    await session.execute(
                        select(FeedbackSummary)
                        .where(
                            FeedbackSummary.recording_id == job.recording_id,
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
                recording_id=job.recording_id,
                artwork_id=job.artwork_id,
                owner_id=job.owner_id,
                transcript_id=transcript_pk,
                job_id=job.id,
                status=FeedbackStatus.DRAFT,
                review_mode=mode,
                version=1,
                summary=output.summary,
                ai_output=output.model_dump(mode="json"),
                model_name=response.model_name,
                prompt_version=PROMPT_VERSION,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                dropped_item_count=dropped,
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
                    note=f"{response.model_name} / {PROMPT_VERSION}",
                )
            )
            self._finish(job, AiJobStatus.SUCCEEDED, clock.utc_now())
            job.last_error_code = None
            job.last_error_message = None
            await session.commit()
