"""AI 첨삭 기록 (v0.6): 외부 AI 전송 동의, 전사·요약 요청, 첨삭 검토·승인, 학생 아카이브.

실제 처리(STT, Gemini)는 이 모듈이 하지 않는다. API는 작업을 큐(ai_processing_jobs)에 넣기만 하고
Worker(app/worker)가 처리한다 → API 요청이 오래 걸리지 않고, 서버가 재시작돼도 작업이 남는다.

권한 (기존 작품·녹음 정책을 그대로 따른다)
- 작품 소유 학생: 자기 녹음의 전사·요약 요청, 전사 원문 조회.
  - 학원 미연결 개인 작품: 학생이 직접 검토·수정·확정한다 (review_mode=SELF).
    강사에게 보이지 않는다.
  - 학원 연결 작품: 승인(APPROVED)된 첨삭만 볼 수 있다. 초안 내용은 강사만 본다.
- 담당 강사·학원 관리자(학원 연결 작품, 담당 학생): 전사·요약 요청, 전사 원문, 초안 검토·수정·승인.
  비담당 403, 다른 학원·개인 작품 404.
- 첨삭의 검토 주체는 저장값이 아니라 매 요청마다 작품의 현재 학원 연결로 판단한다.

동의
- 전사(STT, 서버 내부): 녹음 소유 학생의 녹음 동의가 철회되지 않았어야 한다.
- 요약(Gemini, 외부 전송): 학생의 **별도** AI 전송 동의(현재 버전)가 있어야 한다. 녹음 동의로
  대체하지 않는다. 강사가 요청해도 학생의 동의가 기준이다.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import (
    AiNotConfiguredError,
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    StorageNotConfiguredError,
    StorageUnavailableError,
    SttNotConfiguredError,
    UnprocessableError,
)
from app.integrations.supabase.storage import StorageClient, StorageError
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
    CURRENT_FEEDBACK_STATUSES,
    AiJobStatus,
    AiJobType,
    AiProvider,
    ConsentGrantor,
    ConsentType,
    FeedbackItemKind,
    FeedbackItemOrigin,
    FeedbackStatus,
    RecordingStatus,
    ReviewAction,
    ReviewMode,
    TranscriptionStatus,
    WeaknessCategory,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.models.recording import FeedbackRecording, RecordingConsent
from app.repositories.pagination import fetch_page
from app.schemas.ai_feedback import (
    AiConsentCreate,
    AiConsentRead,
    AiConsentStatus,
    Evidence,
    FeedbackDecision,
    FeedbackItemRead,
    FeedbackRead,
    FeedbackReject,
    FeedbackUpdate,
    JobRead,
    ReviewerFeedbackRead,
    ReviewHistoryRead,
    ReviewQueueItem,
    Segment,
    SummaryStatusRead,
    TranscriptionStatusRead,
    TranscriptMeta,
    TranscriptRead,
)
from app.schemas.common import PaginationParams
from app.schemas.students import student_ref
from app.services.access import managed_student_ids
from app.services.ai_cleanup import cancel_jobs_for_owner
from app.services.artworks import ArtworkService

KIND_ORDER = (
    FeedbackItemKind.STRENGTH,
    FeedbackItemKind.WEAKNESS,
    FeedbackItemKind.FIX,
    FeedbackItemKind.NEXT_TIP,
)
KIND_FIELD = {
    FeedbackItemKind.STRENGTH: "strengths",
    FeedbackItemKind.WEAKNESS: "weaknesses",
    FeedbackItemKind.FIX: "fixes",
    FeedbackItemKind.NEXT_TIP: "next_tips",
}
EDITABLE = (FeedbackStatus.DRAFT, FeedbackStatus.IN_REVIEW)


def job_read(job: AiProcessingJob) -> JobRead:
    return JobRead(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        next_attempt_at=job.run_after if job.status == AiJobStatus.QUEUED else None,
        error_code=job.last_error_code,
        retryable=job.status in (AiJobStatus.FAILED, AiJobStatus.CANCELLED),
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def transcript_meta(t: FeedbackTranscript) -> dict[str, Any]:
    return {
        "id": t.id,
        "language": t.language,
        "duration_ms": t.duration_ms,
        "segment_count": t.segment_count,
        "engine": t.engine,
        "model_name": t.model_name,
        "created_at": t.created_at,
    }


def review_mode_for(artwork: Artwork) -> ReviewMode:
    return ReviewMode.SELF if artwork.academy_id is None else ReviewMode.INSTRUCTOR


@dataclass(frozen=True)
class Reviewer:
    """검토 행위자. membership이 있으면 강사(학원), 없으면 개인 작품의 학생 본인."""

    profile: Profile
    membership: AcademyMembership | None

    @property
    def mode(self) -> ReviewMode:
        return ReviewMode.SELF if self.membership is None else ReviewMode.INSTRUCTOR


class AiFeedbackService:
    def __init__(
        self, session: AsyncSession, settings: Settings, audio_storage: StorageClient | None = None
    ) -> None:
        self.session = session
        self.settings = settings
        self.audio_storage = audio_storage
        self.artworks = ArtworkService(session, settings)

    # ================================================================ AI 전송 동의

    async def _active_ai_consent(self, user_id: uuid.UUID) -> AiProcessingConsent | None:
        stmt = select(AiProcessingConsent).where(
            AiProcessingConsent.user_id == user_id,
            AiProcessingConsent.provider == AiProvider.GOOGLE_GEMINI,
            AiProcessingConsent.revoked_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def has_valid_ai_consent(self, user_id: uuid.UUID) -> bool:
        consent = await self._active_ai_consent(user_id)
        return consent is not None and consent.policy_version == self.settings.ai_consent_version

    async def ai_consent_status(self, user: Profile) -> AiConsentStatus:
        consent = await self._active_ai_consent(user.id)
        required = self.settings.ai_consent_version
        return AiConsentStatus(
            provider=AiProvider.GOOGLE_GEMINI,
            required_version=required,
            is_valid=consent is not None and consent.policy_version == required,
            consent=(
                AiConsentRead(
                    id=consent.id,
                    provider=consent.provider,
                    policy_version=consent.policy_version,
                    granted_by=consent.granted_by,
                    granted_at=consent.granted_at,
                    revoked_at=consent.revoked_at,
                )
                if consent
                else None
            ),
        )

    async def grant_ai_consent(self, user: Profile, data: AiConsentCreate) -> AiConsentStatus:
        if data.policy_version != self.settings.ai_consent_version:
            raise UnprocessableError(
                "Please agree to the current AI processing consent version",
                details={"required_version": self.settings.ai_consent_version},
            )
        current = await self._active_ai_consent(user.id)
        if (
            current is not None
            and current.policy_version == data.policy_version
            and current.granted_by == data.granted_by
        ):
            return await self.ai_consent_status(user)
        now = clock.utc_now()
        if current is not None:
            current.revoked_at = now  # 이전 버전 동의는 철회 처리 (이력 보존)
            await self.session.flush()
        self.session.add(
            AiProcessingConsent(
                id=uuid.uuid4(),
                user_id=user.id,
                provider=AiProvider.GOOGLE_GEMINI,
                policy_version=data.policy_version,
                granted_by=ConsentGrantor(data.granted_by),
                granted_at=now,
            )
        )
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()  # 동시 동의: 먼저 저장된 동의 사용
        return await self.ai_consent_status(user)

    async def revoke_ai_consent(self, user: Profile) -> None:
        """철회: 새 요약 요청이 막히고, 대기·실행 중 요약 작업은 취소된다."""
        consent = await self._active_ai_consent(user.id)
        if consent is None:
            raise NotFoundError("No active AI processing consent")
        consent.revoked_at = clock.utc_now()
        await cancel_jobs_for_owner(
            self.session, user.id, AiJobType.SUMMARIZE, "AI_CONSENT_REVOKED"
        )
        await self.session.commit()

    # ================================================================ 대상 조회·권한

    async def _recording(self, artwork: Artwork, recording_id: uuid.UUID) -> FeedbackRecording:
        recording = (
            await self.session.execute(
                select(FeedbackRecording).where(
                    FeedbackRecording.artwork_id == artwork.id,
                    FeedbackRecording.id == recording_id,
                    FeedbackRecording.status == RecordingStatus.ACTIVE,
                )
            )
        ).scalar_one_or_none()
        if recording is None:
            raise NotFoundError("Recording not found")
        return recording

    async def owner_target(
        self, owner: Profile, artwork_id: uuid.UUID, recording_id: uuid.UUID
    ) -> tuple[Artwork, FeedbackRecording]:
        artwork = await self.artworks.owned(owner, artwork_id)
        return artwork, await self._recording(artwork, recording_id)

    async def staff_target(
        self, actor: AcademyMembership, artwork_id: uuid.UUID, recording_id: uuid.UUID
    ) -> tuple[Artwork, FeedbackRecording]:
        artwork = await self.artworks.staff_artwork(actor, artwork_id)
        return artwork, await self._recording(artwork, recording_id)

    # ================================================================ 작업 조회

    async def _latest_job(
        self, recording_id: uuid.UUID, job_type: AiJobType
    ) -> AiProcessingJob | None:
        stmt = (
            select(AiProcessingJob)
            .where(
                AiProcessingJob.recording_id == recording_id,
                AiProcessingJob.job_type == job_type,
            )
            .order_by(AiProcessingJob.created_at.desc(), AiProcessingJob.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def latest_transcript(self, recording_id: uuid.UUID) -> FeedbackTranscript | None:
        stmt = (
            select(FeedbackTranscript)
            .where(FeedbackTranscript.recording_id == recording_id)
            .order_by(FeedbackTranscript.created_at.desc(), FeedbackTranscript.id.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def current_feedback(self, recording_id: uuid.UUID) -> FeedbackSummary | None:
        stmt = select(FeedbackSummary).where(
            FeedbackSummary.recording_id == recording_id,
            FeedbackSummary.status.in_(CURRENT_FEEDBACK_STATUSES),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _active_job(
        self, recording_id: uuid.UUID, job_type: AiJobType
    ) -> AiProcessingJob | None:
        stmt = select(AiProcessingJob).where(
            AiProcessingJob.recording_id == recording_id,
            AiProcessingJob.job_type == job_type,
            AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ================================================================ 전사 (STT)

    async def _owner_has_recording_consent(self, owner_id: uuid.UUID) -> bool:
        stmt = select(RecordingConsent.id).where(
            RecordingConsent.user_id == owner_id,
            RecordingConsent.consent_type == ConsentType.VOICE_RECORDING,
            RecordingConsent.revoked_at.is_(None),
        )
        return (await self.session.execute(stmt)).first() is not None

    async def request_transcription(
        self,
        recording: FeedbackRecording,
        requester: Profile,
        token: str,
        *,
        auto_summarize: bool,
        retry: bool = False,
    ) -> tuple[JobRead, bool]:
        """(작업, 새로 만들었는지). 진행 중 작업이 있으면 그것을 돌려준다 (중복 방지·멱등)."""
        if not self.settings.stt_enabled:
            raise SttNotConfiguredError()
        if self.audio_storage is None:
            raise StorageNotConfiguredError()
        active = await self._active_job(recording.id, AiJobType.TRANSCRIBE)
        if active is not None:
            return job_read(active), False
        latest = await self._latest_job(recording.id, AiJobType.TRANSCRIBE)
        if retry and (
            latest is None or latest.status not in (AiJobStatus.FAILED, AiJobStatus.CANCELLED)
        ):
            raise ConflictError(
                "Only a failed or cancelled transcription can be retried",
                code=ErrorCode.JOB_NOT_RETRYABLE,
            )
        if await self.latest_transcript(recording.id) is not None:
            raise ConflictError(
                "This recording is already transcribed", code=ErrorCode.TRANSCRIPTION_ALREADY_DONE
            )
        if not await self._owner_has_recording_consent(recording.owner_id):
            raise ConflictError(
                "The student's recording consent is required for transcription",
                code=ErrorCode.RECORDING_CONSENT_REQUIRED,
            )
        if recording.duration_ms > self.settings.stt_max_audio_seconds * 1000:
            raise UnprocessableError(
                "The recording is too long for transcription",
                code=ErrorCode.RECORDING_TOO_LONG,
                details={"max_seconds": self.settings.stt_max_audio_seconds},
            )
        # Worker가 내려받을 Signed URL: 요청한 사용자 토큰으로 발급 → Storage RLS가 권한을 다시 검사
        ttl = self.settings.stt_source_url_seconds
        try:
            urls = await self.audio_storage.create_signed_urls(
                [recording.storage_path], access_token=token, expires_in=ttl
            )
        except StorageError:
            raise StorageUnavailableError() from None
        if recording.storage_path not in urls:
            raise StorageUnavailableError()
        now = clock.utc_now()
        job = AiProcessingJob(
            id=uuid.uuid4(),
            job_type=AiJobType.TRANSCRIBE,
            status=AiJobStatus.QUEUED,
            recording_id=recording.id,
            artwork_id=recording.artwork_id,
            owner_id=recording.owner_id,
            requested_by=requester.id,
            attempts=0,
            max_attempts=self.settings.job_max_attempts,
            run_after=now,
            source_url=urls[recording.storage_path],
            source_url_expires_at=now + timedelta(seconds=ttl),
            params={"chain_summary": auto_summarize},
        )
        self.session.add(job)
        recording.transcription_status = TranscriptionStatus.PENDING
        recording.transcription_updated_at = now
        try:
            await self.session.commit()
        except IntegrityError:
            # 동시 요청: 부분 유니크(uq_ai_processing_jobs_active) → 먼저 만든 작업 반환
            await self.session.rollback()
            existing = await self._active_job(recording.id, AiJobType.TRANSCRIBE)
            if existing is None:
                raise
            return job_read(existing), False
        await self.session.refresh(job)
        return job_read(job), True

    async def transcription_status(self, recording: FeedbackRecording) -> TranscriptionStatusRead:
        job = await self._latest_job(recording.id, AiJobType.TRANSCRIBE)
        transcript = await self.latest_transcript(recording.id)
        return TranscriptionStatusRead(
            recording_id=recording.id,
            transcription_status=recording.transcription_status,
            job=job_read(job) if job else None,
            transcript=TranscriptMeta(**transcript_meta(transcript)) if transcript else None,
        )

    async def transcript(self, recording: FeedbackRecording) -> TranscriptRead:
        transcript = await self.latest_transcript(recording.id)
        if transcript is None:
            raise ConflictError(
                "The transcript is not ready yet", code=ErrorCode.TRANSCRIPT_NOT_READY
            )
        return TranscriptRead(
            **transcript_meta(transcript),
            recording_id=recording.id,
            text=transcript.text,
            segments=[Segment(**s) for s in transcript.segments],
        )

    # ================================================================ 요약 (Gemini)

    async def request_summary(
        self, recording: FeedbackRecording, requester: Profile, *, regenerate: bool
    ) -> tuple[JobRead, bool]:
        if not self.settings.ai_summary_enabled:
            raise AiNotConfiguredError()
        active = await self._active_job(recording.id, AiJobType.SUMMARIZE)
        if active is not None:
            return job_read(active), False
        if not await self.has_valid_ai_consent(recording.owner_id):
            raise ConflictError(
                "The student's consent to external AI processing is required",
                code=ErrorCode.AI_CONSENT_REQUIRED,
                details={"required_version": self.settings.ai_consent_version},
            )
        transcript = await self.latest_transcript(recording.id)
        if transcript is None:
            raise ConflictError(
                "Transcribe the recording first", code=ErrorCode.TRANSCRIPT_NOT_READY
            )
        current = await self.current_feedback(recording.id)
        if current is not None and current.status == FeedbackStatus.APPROVED:
            raise ConflictError(
                "The feedback is already approved; reopen it before regenerating",
                code=ErrorCode.FEEDBACK_ALREADY_APPROVED,
            )
        if current is not None and not regenerate:
            raise ConflictError(
                "A feedback draft already exists; use regenerate",
                code=ErrorCode.FEEDBACK_INVALID_STATE,
                details={"feedback_id": str(current.id)},
            )
        job = AiProcessingJob(
            id=uuid.uuid4(),
            job_type=AiJobType.SUMMARIZE,
            status=AiJobStatus.QUEUED,
            recording_id=recording.id,
            artwork_id=recording.artwork_id,
            owner_id=recording.owner_id,
            requested_by=requester.id,
            attempts=0,
            max_attempts=self.settings.job_max_attempts,
            run_after=clock.utc_now(),
            params={"transcript_id": str(transcript.id)},
        )
        self.session.add(job)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self._active_job(recording.id, AiJobType.SUMMARIZE)
            if existing is None:
                raise
            return job_read(existing), False
        await self.session.refresh(job)
        return job_read(job), True

    async def summary_status(
        self, artwork: Artwork, recording: FeedbackRecording
    ) -> SummaryStatusRead:
        job = await self._latest_job(recording.id, AiJobType.SUMMARIZE)
        current = await self.current_feedback(recording.id)
        return SummaryStatusRead(
            recording_id=recording.id,
            job=job_read(job) if job else None,
            feedback_id=current.id if current else None,
            feedback_status=current.status if current else None,
            review_mode=review_mode_for(artwork) if current else None,
        )

    # ================================================================ 첨삭 조회

    async def _parts(
        self, summaries: list[FeedbackSummary]
    ) -> tuple[
        dict[uuid.UUID, list[FeedbackItem]],
        dict[uuid.UUID, list[WeaknessCategory]],
        dict[uuid.UUID, dict[int, Evidence]],
        dict[uuid.UUID, str],
    ]:
        ids = [s.id for s in summaries]
        items: dict[uuid.UUID, list[FeedbackItem]] = defaultdict(list)
        categories: dict[uuid.UUID, list[WeaknessCategory]] = defaultdict(list)
        segments: dict[uuid.UUID, dict[int, Evidence]] = {}
        names: dict[uuid.UUID, str] = {}
        if not ids:
            return items, categories, segments, names
        for item in (
            await self.session.execute(
                select(FeedbackItem)
                .where(FeedbackItem.summary_id.in_(ids))
                .order_by(FeedbackItem.position, FeedbackItem.id)
            )
        ).scalars():
            items[item.summary_id].append(item)
        for summary_id, category in (
            await self.session.execute(
                select(FeedbackCategory.summary_id, FeedbackCategory.category).where(
                    FeedbackCategory.summary_id.in_(ids)
                )
            )
        ).all():
            categories[summary_id].append(category)
        for summary_id in categories:
            categories[summary_id].sort(key=list(WeaknessCategory).index)
        transcripts = (
            await self.session.execute(
                select(FeedbackTranscript.id, FeedbackTranscript.segments).where(
                    FeedbackTranscript.id.in_({s.transcript_id for s in summaries})
                )
            )
        ).all()
        for transcript_id, segs in transcripts:
            segments[transcript_id] = {
                s["index"]: Evidence(index=s["index"], start_ms=s["start_ms"], end_ms=s["end_ms"])
                for s in segs
            }
        approvers = {s.approved_by for s in summaries if s.approved_by}
        if approvers:
            names = dict(
                (
                    await self.session.execute(
                        select(Profile.id, Profile.display_name).where(Profile.id.in_(approvers))
                    )
                ).all()
            )
        return items, categories, segments, names

    def _read_dict(
        self,
        summary: FeedbackSummary,
        artwork: Artwork,
        items: list[FeedbackItem],
        categories: list[WeaknessCategory],
        segments: dict[int, Evidence],
        names: dict[uuid.UUID, str],
    ) -> dict[str, Any]:
        grouped: dict[str, list[FeedbackItemRead]] = {f: [] for f in KIND_FIELD.values()}
        for item in items:
            grouped[KIND_FIELD[item.kind]].append(
                FeedbackItemRead(
                    id=item.id,
                    kind=item.kind,
                    position=item.position,
                    content=item.content,
                    category=item.category,
                    evidence=[segments[i] for i in item.evidence_segment_ids if i in segments],
                    origin=item.origin,
                )
            )
        return {
            "id": summary.id,
            "recording_id": summary.recording_id,
            "artwork_id": summary.artwork_id,
            "status": summary.status,
            "review_mode": review_mode_for(artwork),
            "version": summary.version,
            "summary": summary.summary,
            **grouped,
            "categories": categories,
            "approved_at": summary.approved_at,
            "approved_by_name": names.get(summary.approved_by) if summary.approved_by else None,
            "created_at": summary.created_at,
            "updated_at": summary.updated_at,
        }

    async def _read(self, summary: FeedbackSummary, artwork: Artwork) -> dict[str, Any]:
        items, categories, segments, names = await self._parts([summary])
        return self._read_dict(
            summary,
            artwork,
            items[summary.id],
            categories[summary.id],
            segments.get(summary.transcript_id, {}),
            names,
        )

    async def _reviewer_read(
        self, summary: FeedbackSummary, artwork: Artwork, membership: AcademyMembership | None
    ) -> ReviewerFeedbackRead:
        student = None
        if membership is not None and artwork.student_membership_id is not None:
            m, p = (
                await self.session.execute(
                    select(AcademyMembership, Profile)
                    .join(Profile, Profile.id == AcademyMembership.user_id)
                    .where(AcademyMembership.id == artwork.student_membership_id)
                )
            ).one()
            student = student_ref(m, p)
        return ReviewerFeedbackRead(
            **await self._read(summary, artwork),
            ai_draft=summary.ai_output,
            model_name=summary.model_name,
            prompt_version=summary.prompt_version,
            dropped_item_count=summary.dropped_item_count,
            rejected_reason=summary.rejected_reason,
            artwork_title=artwork.title,
            student=student,
        )

    async def _summary_with_artwork(
        self, stmt: Select[tuple[FeedbackSummary, Artwork]], *, for_update: bool = False
    ) -> tuple[FeedbackSummary, Artwork]:
        if for_update:
            stmt = stmt.with_for_update(of=FeedbackSummary)
        row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            raise NotFoundError("Feedback not found")
        return row[0], row[1]

    def _base(self, feedback_id: uuid.UUID) -> Select[tuple[FeedbackSummary, Artwork]]:
        return (
            select(FeedbackSummary, Artwork)
            .join(Artwork, Artwork.id == FeedbackSummary.artwork_id)
            .where(
                FeedbackSummary.id == feedback_id,
                Artwork.deleted_at.is_(None),
                FeedbackSummary.status != FeedbackStatus.SUPERSEDED,
            )
        )

    async def owner_feedback(
        self, owner: Profile, feedback_id: uuid.UUID, *, for_update: bool = False
    ) -> tuple[FeedbackSummary, Artwork]:
        return await self._summary_with_artwork(
            self._base(feedback_id).where(FeedbackSummary.owner_id == owner.id),
            for_update=for_update,
        )

    async def staff_feedback(
        self, actor: AcademyMembership, feedback_id: uuid.UUID, *, for_update: bool = False
    ) -> tuple[FeedbackSummary, Artwork]:
        summary, artwork = await self._summary_with_artwork(
            self._base(feedback_id).where(
                Artwork.academy_id == actor.academy_id,
                Artwork.student_membership_id.is_not(None),
            ),
            for_update=for_update,
        )
        if not await self.artworks.access.is_managed_student(
            actor,
            artwork.student_membership_id,  # type: ignore[arg-type]
        ):
            raise ForbiddenError("This student is not in your classes")
        return summary, artwork

    async def owner_view(self, owner: Profile, feedback_id: uuid.UUID) -> FeedbackRead:
        """학생: 개인 작품이면 검토자 화면, 학원 연결 작품이면 승인된 첨삭만."""
        summary, artwork = await self.owner_feedback(owner, feedback_id)
        if artwork.academy_id is None:
            return await self._reviewer_read(summary, artwork, None)
        if summary.status != FeedbackStatus.APPROVED:
            raise ForbiddenError(
                "The feedback is waiting for instructor approval",
                code=ErrorCode.FEEDBACK_NOT_APPROVED,
            )
        return FeedbackRead(**await self._read(summary, artwork))

    async def staff_view(
        self, actor: AcademyMembership, feedback_id: uuid.UUID
    ) -> ReviewerFeedbackRead:
        summary, artwork = await self.staff_feedback(actor, feedback_id)
        return await self._reviewer_read(summary, artwork, actor)

    async def archive(self, owner: Profile, artwork_id: uuid.UUID) -> list[FeedbackRead]:
        """작품별 확정 첨삭 (최근 승인순)."""
        artwork = await self.artworks.owned(owner, artwork_id)
        summaries = list(
            (
                await self.session.execute(
                    select(FeedbackSummary)
                    .where(
                        FeedbackSummary.artwork_id == artwork.id,
                        FeedbackSummary.status == FeedbackStatus.APPROVED,
                    )
                    .order_by(FeedbackSummary.approved_at.desc(), FeedbackSummary.id)
                )
            ).scalars()
        )
        items, categories, segments, names = await self._parts(summaries)
        return [
            FeedbackRead(
                **self._read_dict(
                    s,
                    artwork,
                    items[s.id],
                    categories[s.id],
                    segments.get(s.transcript_id, {}),
                    names,
                )
            )
            for s in summaries
        ]

    async def review_queue(
        self,
        actor: AcademyMembership,
        params: PaginationParams,
        *,
        statuses: list[FeedbackStatus],
        student_membership_id: uuid.UUID | None,
    ) -> tuple[list[ReviewQueueItem], int]:
        if student_membership_id is not None:
            await self.artworks.access.require_managed_student(actor, student_membership_id)
        stmt = (
            select(FeedbackSummary, Artwork, AcademyMembership, Profile, FeedbackRecording.title)
            .join(Artwork, Artwork.id == FeedbackSummary.artwork_id)
            .join(AcademyMembership, AcademyMembership.id == Artwork.student_membership_id)
            .join(Profile, Profile.id == AcademyMembership.user_id)
            .join(FeedbackRecording, FeedbackRecording.id == FeedbackSummary.recording_id)
            .where(
                Artwork.academy_id == actor.academy_id,
                Artwork.deleted_at.is_(None),
                Artwork.student_membership_id.in_(managed_student_ids(actor)),
                FeedbackSummary.status.in_(statuses),
            )
            .order_by(FeedbackSummary.created_at, FeedbackSummary.id)
        )
        if student_membership_id is not None:
            stmt = stmt.where(Artwork.student_membership_id == student_membership_id)
        rows, total = await fetch_page(self.session, stmt, params)
        _, categories, _, _ = await self._parts([r[0] for r in rows]) if rows else ({}, {}, {}, {})
        return [
            ReviewQueueItem(
                id=s.id,
                recording_id=s.recording_id,
                artwork_id=a.id,
                artwork_title=a.title,
                recording_title=title,
                status=s.status,
                version=s.version,
                summary=s.summary,
                categories=categories.get(s.id, []),
                student=student_ref(m, p),
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s, a, m, p, title in rows
        ], total

    # ================================================================ 검토·수정·승인

    async def _snapshot(self, summary: FeedbackSummary) -> dict[str, Any]:
        items = (
            await self.session.execute(
                select(FeedbackItem)
                .where(FeedbackItem.summary_id == summary.id)
                .order_by(FeedbackItem.kind, FeedbackItem.position)
            )
        ).scalars()
        categories = (
            await self.session.execute(
                select(FeedbackCategory.category).where(FeedbackCategory.summary_id == summary.id)
            )
        ).scalars()
        return {
            "summary": summary.summary,
            "items": [
                {
                    "kind": i.kind.value,
                    "content": i.content,
                    "category": i.category.value if i.category else None,
                    "evidence": list(i.evidence_segment_ids),
                }
                for i in items
            ],
            "categories": sorted(c.value for c in categories),
        }

    def _history(
        self,
        summary: FeedbackSummary,
        reviewer: Reviewer,
        action: ReviewAction,
        from_status: FeedbackStatus | None,
        *,
        changes: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> None:
        self.session.add(
            FeedbackReviewHistory(
                id=uuid.uuid4(),
                summary_id=summary.id,
                actor_id=reviewer.profile.id,
                actor_mode=reviewer.mode,
                action=action,
                from_status=from_status,
                to_status=summary.status,
                version=summary.version,
                changes=changes,
                note=note,
            )
        )

    @staticmethod
    def _check(summary: FeedbackSummary, version: int, allowed: tuple[FeedbackStatus, ...]) -> None:
        if summary.status not in allowed:
            if summary.status == FeedbackStatus.APPROVED:
                raise ConflictError(
                    "The feedback is already approved", code=ErrorCode.FEEDBACK_ALREADY_APPROVED
                )
            raise ConflictError(
                f"Not allowed while the feedback is {summary.status.value}",
                code=ErrorCode.FEEDBACK_INVALID_STATE,
            )
        if summary.version != version:
            raise ConflictError(
                "The feedback was changed by someone else; reload it",
                code=ErrorCode.FEEDBACK_VERSION_CONFLICT,
                details={"current_version": summary.version},
            )

    def _reviewer_for_owner(self, owner: Profile, artwork: Artwork) -> Reviewer:
        if artwork.academy_id is not None:
            raise ForbiddenError("Your instructor reviews feedback for academy artworks")
        return Reviewer(owner, None)

    async def _locked(
        self, reviewer_profile: Profile, feedback_id: uuid.UUID, actor: AcademyMembership | None
    ) -> tuple[FeedbackSummary, Artwork, Reviewer]:
        if actor is None:
            summary, artwork = await self.owner_feedback(
                reviewer_profile, feedback_id, for_update=True
            )
            return summary, artwork, self._reviewer_for_owner(reviewer_profile, artwork)
        summary, artwork = await self.staff_feedback(actor, feedback_id, for_update=True)
        return summary, artwork, Reviewer(reviewer_profile, actor)

    async def update(
        self,
        reviewer_profile: Profile,
        feedback_id: uuid.UUID,
        data: FeedbackUpdate,
        actor: AcademyMembership | None = None,
    ) -> ReviewerFeedbackRead:
        summary, artwork, reviewer = await self._locked(reviewer_profile, feedback_id, actor)
        self._check(summary, data.version, EDITABLE)
        segment_count = (
            await self.session.execute(
                select(FeedbackTranscript.segment_count).where(
                    FeedbackTranscript.id == summary.transcript_id
                )
            )
        ).scalar_one()
        for item in data.items:
            if item.evidence_segment_ids and any(
                not 0 <= i < segment_count for i in item.evidence_segment_ids
            ):
                raise UnprocessableError(
                    "evidence_segment_ids must refer to transcript segments",
                    details={"segment_count": segment_count},
                )
        existing = {
            i.id: i
            for i in (
                await self.session.execute(
                    select(FeedbackItem).where(FeedbackItem.summary_id == summary.id)
                )
            ).scalars()
        }
        unknown = [str(i.id) for i in data.items if i.id is not None and i.id not in existing]
        if unknown:
            raise UnprocessableError("Unknown feedback item id", details={"item_ids": unknown})
        before = await self._snapshot(summary)

        positions: dict[FeedbackItemKind, int] = defaultdict(int)
        kept: set[uuid.UUID] = set()
        for entry in data.items:
            position = positions[entry.kind]
            positions[entry.kind] += 1
            if entry.id is not None:
                item = existing[entry.id]
                kept.add(item.id)
                evidence = (
                    sorted(set(entry.evidence_segment_ids))
                    if entry.evidence_segment_ids is not None
                    else list(item.evidence_segment_ids)
                )
                changed = (
                    item.content != entry.content
                    or item.category != entry.category
                    or item.kind != entry.kind
                    or list(item.evidence_segment_ids) != evidence
                )
                if changed and item.origin == FeedbackItemOrigin.AI:
                    item.origin = FeedbackItemOrigin.EDITED
                item.kind = entry.kind
                item.content = entry.content
                item.category = entry.category
                item.evidence_segment_ids = evidence
                item.position = position
            else:
                self.session.add(
                    FeedbackItem(
                        id=uuid.uuid4(),
                        summary_id=summary.id,
                        kind=entry.kind,
                        position=position,
                        content=entry.content,
                        category=entry.category,
                        evidence_segment_ids=sorted(set(entry.evidence_segment_ids or [])),
                        origin=FeedbackItemOrigin.ADDED,
                    )
                )
        for item_id, item in existing.items():
            if item_id not in kept:
                await self.session.delete(item)

        current_categories = {
            c.category: c
            for c in (
                await self.session.execute(
                    select(FeedbackCategory).where(FeedbackCategory.summary_id == summary.id)
                )
            ).scalars()
        }
        wanted = set(data.categories)
        for category, row in current_categories.items():
            if category not in wanted:
                await self.session.delete(row)
        for category in wanted - current_categories.keys():
            self.session.add(
                FeedbackCategory(
                    id=uuid.uuid4(),
                    summary_id=summary.id,
                    category=category,
                    origin=FeedbackItemOrigin.ADDED,
                )
            )
        await self.session.flush()

        from_status = summary.status
        summary.summary = data.summary
        summary.status = FeedbackStatus.IN_REVIEW
        summary.review_mode = reviewer.mode
        summary.version += 1
        after = await self._snapshot(summary)
        self._history(
            summary,
            reviewer,
            ReviewAction.EDITED,
            from_status,
            changes={"before": before, "after": after},
            note=data.note,
        )
        await self.session.commit()
        await self.session.refresh(summary)
        return await self._reviewer_read(summary, artwork, actor)

    async def approve(
        self,
        reviewer_profile: Profile,
        feedback_id: uuid.UUID,
        data: FeedbackDecision,
        actor: AcademyMembership | None = None,
    ) -> ReviewerFeedbackRead:
        summary, artwork, reviewer = await self._locked(reviewer_profile, feedback_id, actor)
        self._check(summary, data.version, EDITABLE)
        from_status = summary.status
        summary.status = FeedbackStatus.APPROVED
        summary.approved_at = clock.utc_now()
        summary.approved_by = reviewer.profile.id
        summary.approver_membership_id = actor.id if actor else None
        summary.review_mode = reviewer.mode
        summary.rejected_reason = None
        summary.version += 1
        self._history(
            summary,
            reviewer,
            ReviewAction.APPROVED,
            from_status,
            changes={"approved": await self._snapshot(summary)},
            note=data.note,
        )
        await self.session.commit()
        await self.session.refresh(summary)
        return await self._reviewer_read(summary, artwork, actor)

    async def reject(
        self,
        reviewer_profile: Profile,
        feedback_id: uuid.UUID,
        data: FeedbackReject,
        actor: AcademyMembership | None = None,
    ) -> ReviewerFeedbackRead:
        """초안을 쓰지 않음 (예: 첨삭이 아닌 녹음, AI 결과 부정확). 이후 재생성 가능."""
        summary, artwork, reviewer = await self._locked(reviewer_profile, feedback_id, actor)
        self._check(summary, data.version, EDITABLE)
        from_status = summary.status
        summary.status = FeedbackStatus.REJECTED
        summary.rejected_reason = data.reason
        summary.version += 1
        self._history(summary, reviewer, ReviewAction.REJECTED, from_status, note=data.reason)
        await self.session.commit()
        await self.session.refresh(summary)
        return await self._reviewer_read(summary, artwork, actor)

    async def reopen(
        self,
        reviewer_profile: Profile,
        feedback_id: uuid.UUID,
        data: FeedbackDecision,
        actor: AcademyMembership | None = None,
    ) -> ReviewerFeedbackRead:
        """승인 취소 → 다시 검토 중. 학생 아카이브에서 빠진다."""
        summary, artwork, reviewer = await self._locked(reviewer_profile, feedback_id, actor)
        self._check(summary, data.version, (FeedbackStatus.APPROVED,))
        summary.status = FeedbackStatus.IN_REVIEW
        summary.approved_at = None
        summary.approved_by = None
        summary.approver_membership_id = None
        summary.version += 1
        self._history(
            summary, reviewer, ReviewAction.REOPENED, FeedbackStatus.APPROVED, note=data.note
        )
        await self.session.commit()
        await self.session.refresh(summary)
        return await self._reviewer_read(summary, artwork, actor)

    async def history(self, summary: FeedbackSummary) -> list[ReviewHistoryRead]:
        rows = (
            await self.session.execute(
                select(FeedbackReviewHistory, Profile.display_name)
                .outerjoin(Profile, Profile.id == FeedbackReviewHistory.actor_id)
                .where(FeedbackReviewHistory.summary_id == summary.id)
                .order_by(FeedbackReviewHistory.created_at, FeedbackReviewHistory.id)
            )
        ).all()
        return [
            ReviewHistoryRead(
                id=h.id,
                action=h.action,
                from_status=h.from_status,
                to_status=h.to_status,
                version=h.version,
                actor_name=name,
                actor_mode=h.actor_mode,
                changes=h.changes,
                note=h.note,
                created_at=h.created_at,
            )
            for h, name in rows
        ]

    async def owner_history(
        self, owner: Profile, feedback_id: uuid.UUID
    ) -> list[ReviewHistoryRead]:
        summary, artwork = await self.owner_feedback(owner, feedback_id)
        self._reviewer_for_owner(owner, artwork)  # 학원 연결 작품의 이력은 강사만
        return await self.history(summary)

    async def staff_history(
        self, actor: AcademyMembership, feedback_id: uuid.UUID
    ) -> list[ReviewHistoryRead]:
        summary, _ = await self.staff_feedback(actor, feedback_id)
        return await self.history(summary)
