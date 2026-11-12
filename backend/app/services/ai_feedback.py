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
- v0.9 텍스트 첨삭: 출처가 SELF_NOTE·PEER면 학원 작품이어도 학생 본인이 확정한다 (강사 화면·검토
  대기열에 나오지 않음). 강사 첨삭(INSTRUCTOR)을 학원 작품에 적었으면 기존처럼 담당 강사가 확정.
- v0.9 STT 결과 수정: 학생이 전사 문장을 고치면 새 전사 행을 만든다 (원본 보존, 구간·시각 유지).

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
    RateLimitedError,
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
    FeedbackNote,
    FeedbackReviewHistory,
    FeedbackSummary,
    FeedbackTranscript,
)
from app.models.artwork import Artwork
from app.models.enums import (
    ACTIVE_JOB_STATUSES,
    CURRENT_FEEDBACK_STATUSES,
    AiConsentPurpose,
    AiJobStatus,
    AiJobType,
    ConsentGrantor,
    ConsentType,
    FeedbackItemKind,
    FeedbackItemOrigin,
    FeedbackSource,
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
    BrowserTranscriptCreate,
    BrowserTranscriptResult,
    Evidence,
    FeedbackDecision,
    FeedbackItemRead,
    FeedbackRead,
    FeedbackReject,
    FeedbackUpdate,
    GuardianConsentConfirm,
    GuardianConsentView,
    JobRead,
    ReviewerFeedbackRead,
    ReviewHistoryRead,
    ReviewQueueItem,
    Segment,
    SummaryStatusRead,
    TranscriptEdit,
    TranscriptionStatusRead,
    TranscriptMeta,
    TranscriptRead,
)
from app.schemas.common import PaginationParams
from app.schemas.students import student_ref
from app.services import ai_consent_policy as consent_policy
from app.services.access import managed_student_ids
from app.services.ai_cleanup import (
    PURPOSE_JOB_TYPES,
    cancel_jobs_for_owner,
    skip_pending_narratives,
)
from app.services.ai_limits import check_summary_quota, log_stt_disabled, log_summary_disabled
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


BROWSER_ENGINE_PREFIX = "browser-"
# 기기 시계·디코딩 차이로 녹음 길이보다 조금 긴 타임스탬프 허용
BROWSER_DURATION_SLACK_MS = 5_000


def transcript_origin(t: FeedbackTranscript) -> str:
    if t.edited_from_id is not None:
        return "EDITED"
    return "BROWSER" if t.engine.startswith(BROWSER_ENGINE_PREFIX) else "SERVER"


def transcript_meta(t: FeedbackTranscript) -> dict[str, Any]:
    return {
        "id": t.id,
        "language": t.language,
        "duration_ms": t.duration_ms,
        "segment_count": t.segment_count,
        "engine": t.engine,
        "model_name": t.model_name,
        "origin": transcript_origin(t),
        "created_at": t.created_at,
    }


def review_mode_for(
    artwork: Artwork, source: FeedbackSource = FeedbackSource.INSTRUCTOR
) -> ReviewMode:
    """개인 작품, 또는 강사 첨삭이 아닌 기록(자기 메모·다른 학생 의견)은 학생 본인이 확정한다."""
    if artwork.academy_id is None or source != FeedbackSource.INSTRUCTOR:
        return ReviewMode.SELF
    return ReviewMode.INSTRUCTOR


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

    def required_version(self, purpose: AiConsentPurpose) -> str:
        return consent_policy.required_version(self.settings, purpose)

    async def _active_ai_consent(
        self, user_id: uuid.UUID, purpose: AiConsentPurpose = AiConsentPurpose.FEEDBACK_SUMMARY
    ) -> AiProcessingConsent | None:
        """지금 제공자(AI_PROVIDER)에 대한 철회되지 않은 동의 (보호자 확인 대기 포함)."""
        stmt = select(AiProcessingConsent).where(
            AiProcessingConsent.user_id == user_id,
            AiProcessingConsent.provider == consent_policy.provider_for(self.settings),
            AiProcessingConsent.purpose == purpose,
            AiProcessingConsent.revoked_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def has_valid_ai_consent(
        self, user_id: uuid.UUID, purpose: AiConsentPurpose = AiConsentPurpose.FEEDBACK_SUMMARY
    ) -> bool:
        consent = await self._active_ai_consent(user_id, purpose)
        return consent_policy.evaluate(consent, self.settings, purpose).is_valid

    async def ai_consent_status(
        self,
        user: Profile,
        purpose: AiConsentPurpose = AiConsentPurpose.FEEDBACK_SUMMARY,
        *,
        guardian_token: str | None = None,
    ) -> AiConsentStatus:
        consent = await self._active_ai_consent(user.id, purpose)
        state = consent_policy.evaluate(consent, self.settings, purpose)
        return AiConsentStatus(
            provider=consent_policy.provider_for(self.settings),
            purpose=purpose,
            required_version=self.required_version(purpose),
            is_valid=state.is_valid,
            reason=state.reason,  # type: ignore[arg-type]
            consent=(
                AiConsentRead(
                    id=consent.id,
                    provider=consent.provider,
                    purpose=consent.purpose,
                    policy_version=consent.policy_version,
                    granted_by=consent.granted_by,
                    granted_at=consent.granted_at,
                    revoked_at=consent.revoked_at,
                    age_band=consent.age_band,
                    guardian_relationship=consent.guardian_relationship,
                    guardian_confirmed_at=consent.guardian_confirmed_at,
                )
                if consent
                else None
            ),
            guardian_token=guardian_token,
            guardian_token_expires_at=(
                consent.guardian_token_expires_at if consent and guardian_token else None
            ),
        )

    async def grant_ai_consent(self, user: Profile, data: AiConsentCreate) -> AiConsentStatus:
        """동의 (v0.9.6). 생년월로 연령 구간을 정하고(저장 안 함), 미성년자는 보호자 확인 링크 발급.

        같은 버전·제공자·연령 구간의 동의가 이미 유효(또는 차단 사유가 보호자 대기가 아님)하면
        그대로 돌려준다 (멱등). 보호자 대기 중 다시 동의하면 새 링크를 발급한다.
        """
        purpose = data.purpose
        required = self.required_version(purpose)
        if data.policy_version != required:
            raise UnprocessableError(
                "Please agree to the current AI processing consent version",
                details={"required_version": required, "purpose": purpose.value},
            )
        if data.birth_year_month is None:
            raise UnprocessableError(
                "Birth year and month are required to check the age for AI processing",
                code=ErrorCode.AI_AGE_REQUIRED,
            )
        try:
            band = consent_policy.age_band(data.birth_year_month, clock.local_today())
        except ValueError:
            raise UnprocessableError(
                "Invalid birth year and month", code=ErrorCode.AI_AGE_REQUIRED
            ) from None
        current = await self._active_ai_consent(user.id, purpose)
        if (
            current is not None
            and current.policy_version == required
            and current.age_band == band
            and consent_policy.evaluate(current, self.settings, purpose).reason
            != consent_policy.GUARDIAN_PENDING
        ):
            return await self.ai_consent_status(user, purpose)
        now = clock.utc_now()
        if current is not None:
            current.revoked_at = now  # 이전 동의(버전·보호자 대기)는 철회 처리 (이력 보존)
            await self.session.flush()
        guardian = consent_policy.needs_guardian(band, self.settings)
        consent = AiProcessingConsent(
            id=uuid.uuid4(),
            user_id=user.id,
            provider=consent_policy.provider_for(self.settings),
            purpose=purpose,
            policy_version=data.policy_version,
            granted_by=ConsentGrantor.GUARDIAN if guardian else ConsentGrantor.SELF,
            granted_at=now,
            revoked_at=None,
            age_band=band,
            guardian_confirmed_at=None,
        )
        # 보호자 링크는 보호자 확인만 남은 경우에만 (연령대가 닫혀 있으면 발급 안 함)
        token: str | None = None
        if (
            consent_policy.evaluate(consent, self.settings, purpose).reason
            == consent_policy.GUARDIAN_PENDING
        ):
            token, consent.guardian_token_hash, consent.guardian_token_expires_at = (
                consent_policy.new_guardian_token(now)
            )
        self.session.add(consent)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()  # 동시 동의: 먼저 저장된 동의 사용
            await self.session.refresh(user)  # 만료된 ORM 객체 재조회 (MissingGreenlet 방지)
            return await self.ai_consent_status(user, purpose)
        return await self.ai_consent_status(user, purpose, guardian_token=token)

    async def new_guardian_link(
        self, user: Profile, purpose: AiConsentPurpose = AiConsentPurpose.FEEDBACK_SUMMARY
    ) -> AiConsentStatus:
        """보호자 확인 대기 중인 동의의 링크 재발급 (이전 링크는 무효)."""
        consent = await self._active_ai_consent(user.id, purpose)
        state = consent_policy.evaluate(consent, self.settings, purpose)
        if consent is None or state.reason != consent_policy.GUARDIAN_PENDING:
            raise ConflictError(
                "There is no consent waiting for a guardian",
                code=ErrorCode.FEEDBACK_INVALID_STATE,
            )
        token, token_hash, expires_at = consent_policy.new_guardian_token(clock.utc_now())
        consent.guardian_token_hash = token_hash
        consent.guardian_token_expires_at = expires_at
        await self.session.commit()
        return await self.ai_consent_status(user, purpose, guardian_token=token)

    async def _consent_by_guardian_token(
        self, token: str, *, for_update: bool = False
    ) -> AiProcessingConsent:
        stmt = select(AiProcessingConsent).where(
            AiProcessingConsent.guardian_token_hash == consent_policy.hash_token(token),
            AiProcessingConsent.revoked_at.is_(None),
        )
        if for_update:
            stmt = stmt.with_for_update()
        consent = (await self.session.execute(stmt)).scalar_one_or_none()
        if (
            consent is None
            or consent.guardian_token_expires_at is None
            or consent.guardian_token_expires_at <= clock.utc_now()
            or consent.age_band is None
        ):
            raise NotFoundError(
                "The guardian link is invalid or expired", code=ErrorCode.GUARDIAN_LINK_INVALID
            )
        return consent

    @staticmethod
    def _guardian_view(consent: AiProcessingConsent) -> GuardianConsentView:
        assert consent.age_band is not None
        return GuardianConsentView(
            provider=consent.provider,
            purpose=consent.purpose,
            policy_version=consent.policy_version,
            age_band=consent.age_band,
            status="CONFIRMED" if consent.guardian_confirmed_at else "PENDING",
            expires_at=consent.guardian_token_expires_at,
        )

    async def guardian_consent_view(self, token: str) -> GuardianConsentView:
        return self._guardian_view(await self._consent_by_guardian_token(token))

    async def guardian_confirm(
        self, token: str, data: GuardianConsentConfirm
    ) -> GuardianConsentView:
        """보호자 확인 (로그인 불필요, 링크 토큰). 확인하면 링크는 더 쓸 수 없다."""
        consent = await self._consent_by_guardian_token(token, for_update=True)
        consent.guardian_name = data.guardian_name
        consent.guardian_relationship = data.relationship
        consent.guardian_confirmed_at = clock.utc_now()
        consent.guardian_token_hash = None  # 한 번 쓰면 끝 (다시 열면 404)
        consent.guardian_token_expires_at = None
        view = self._guardian_view(consent)
        await self.session.commit()
        return view

    async def revoke_ai_consent(
        self, user: Profile, purpose: AiConsentPurpose = AiConsentPurpose.FEEDBACK_SUMMARY
    ) -> None:
        """철회: 그 목적의 새 AI 요청이 막히고, 대기·실행 중 작업은 취소된다."""
        consent = await self._active_ai_consent(user.id, purpose)
        if consent is None:
            raise NotFoundError("No active AI processing consent")
        consent.revoked_at = clock.utc_now()
        for job_type in PURPOSE_JOB_TYPES[purpose]:
            await cancel_jobs_for_owner(self.session, user.id, job_type, "AI_CONSENT_REVOKED")
        if purpose == AiConsentPurpose.GROWTH_COACHING:
            await skip_pending_narratives(self.session, user.id)
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
        defer_seconds: int = 0,
    ) -> tuple[JobRead, bool]:
        """(작업, 새로 만들었는지). 진행 중 작업이 있으면 그것을 돌려준다 (중복 방지·멱등).

        defer_seconds > 0: 기기 전사 중 백업 작업 (run_after를 미룸).
        defer_seconds == 0인데 미뤄 둔 대기 작업이 있으면 지금 처리하도록 앞당긴다.
        """
        recording_id = recording.id
        if not self.settings.stt_enabled:
            log_stt_disabled("request_transcription")
            raise SttNotConfiguredError()
        if self.audio_storage is None:
            raise StorageNotConfiguredError()
        defer_seconds = min(defer_seconds, self.settings.stt_max_defer_seconds)
        active = await self._active_job(recording.id, AiJobType.TRANSCRIBE)
        if active is not None:
            now = clock.utc_now()
            if (
                defer_seconds == 0
                and active.status == AiJobStatus.QUEUED
                and active.run_after > now
            ):
                active.run_after = now
                if auto_summarize and not active.params.get("chain_summary"):
                    active.params = {**active.params, "chain_summary": True}
                await self.session.commit()
                await self.session.refresh(active)
            return job_read(active), False
        if recording.audio_deleted_at is not None:
            raise ConflictError(
                "The audio was deleted after the retention period",
                code=ErrorCode.RECORDING_AUDIO_EXPIRED,
            )
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
            run_after=now + timedelta(seconds=defer_seconds),
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
            # rollback으로 ORM 객체가 만료되므로 미리 꺼낸 ID를 쓴다 (지연 로드 금지)
            existing = await self._active_job(recording_id, AiJobType.TRANSCRIBE)
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
            edited=transcript.edited_from_id is not None,
            edited_from_id=transcript.edited_from_id,
        )

    async def save_browser_transcript(
        self, owner: Profile, recording: FeedbackRecording, data: BrowserTranscriptCreate
    ) -> BrowserTranscriptResult:
        """학생 기기에서 만든 전사 저장 (v0.9.2). 서버 전사와 같은 테이블·같은 이후 흐름.

        중복 방지: 녹음 행 → 진행 중 전사 작업 순서로 잠근 뒤 전사가 없을 때만 저장하고,
        대기·진행 중인 서버(GitHub Actions) 전사 작업은 취소한다. Worker는 결과 저장 직전에
        작업 행을 다시 잠그고 RUNNING인지 확인하므로 취소된 작업의 결과는 버려진다.
        Worker가 먼저 저장했으면 409.
        """
        recording_id = recording.id
        await self.session.execute(
            select(FeedbackRecording.id)
            .where(FeedbackRecording.id == recording_id)
            .with_for_update()
        )
        if not await self._owner_has_recording_consent(recording.owner_id):
            raise ConflictError(
                "The student's recording consent is required for transcription",
                code=ErrorCode.RECORDING_CONSENT_REQUIRED,
            )
        last_end = max(s.end_ms for s in data.segments)
        if last_end > recording.duration_ms + BROWSER_DURATION_SLACK_MS:
            raise UnprocessableError(
                "Segment timestamps exceed the recording length",
                details={"duration_ms": recording.duration_ms},
            )
        text = " ".join(s.text for s in data.segments)
        if len(text) > self.settings.ai_max_transcript_chars:
            raise UnprocessableError(
                "The transcript is too long",
                details={"max_chars": self.settings.ai_max_transcript_chars},
            )
        active = list(
            (
                await self.session.execute(
                    select(AiProcessingJob)
                    .where(
                        AiProcessingJob.recording_id == recording_id,
                        AiProcessingJob.job_type == AiJobType.TRANSCRIBE,
                        AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        if await self.latest_transcript(recording_id) is not None:
            raise ConflictError(
                "This recording is already transcribed", code=ErrorCode.TRANSCRIPTION_ALREADY_DONE
            )
        now = clock.utc_now()
        for job in active:
            job.status = AiJobStatus.CANCELLED
            job.finished_at = now
            job.locked_by = None
            job.lease_expires_at = None
            job.source_url = None
            job.source_url_expires_at = None
            job.last_error_code = "BROWSER_TRANSCRIBED"
        self.session.add(
            FeedbackTranscript(
                id=uuid.uuid4(),
                recording_id=recording_id,
                artwork_id=recording.artwork_id,
                owner_id=recording.owner_id,
                job_id=None,
                language=data.language,
                duration_ms=recording.duration_ms,
                text=text,
                segments=[
                    {"index": i, "start_ms": s.start_ms, "end_ms": s.end_ms, "text": s.text}
                    for i, s in enumerate(data.segments)
                ],
                segment_count=len(data.segments),
                engine=f"{BROWSER_ENGINE_PREFIX}{data.device}",
                model_name=data.model_name,
                processing_ms=data.processing_ms,
            )
        )
        recording.transcription_status = TranscriptionStatus.COMPLETED
        recording.transcription_updated_at = now
        await self.session.commit()
        summary_job = None
        summary_status = "NOT_REQUESTED"
        if data.auto_summarize:
            if not self.settings.ai_summary_active:
                log_summary_disabled("save_browser_transcript")
                summary_status = "AI_DISABLED"
            elif not await self.has_valid_ai_consent(recording.owner_id):
                summary_status = "CONSENT_REQUIRED"
            else:
                try:
                    summary_job, _ = await self.request_summary(recording, owner, regenerate=False)
                    summary_status = "QUEUED"
                except RateLimitedError:
                    summary_status = "LIMIT_REACHED"
        recording = await self._recording_by_id(recording_id)
        return BrowserTranscriptResult(
            transcript=await self.transcript(recording),
            summary_job=summary_job,
            summary_status=summary_status,  # type: ignore[arg-type]
        )

    async def _recording_by_id(self, recording_id: uuid.UUID) -> FeedbackRecording:
        recording = await self.session.get(FeedbackRecording, recording_id)
        assert recording is not None
        return recording

    async def edit_transcript(
        self, editor: Profile, recording: FeedbackRecording, data: TranscriptEdit
    ) -> TranscriptRead:
        """STT 결과 수정: 새 전사 행 (원본 보존). 확정된 첨삭이 있으면 먼저 다시 열어야 한다."""
        await self.session.execute(
            select(FeedbackRecording.id)
            .where(FeedbackRecording.id == recording.id)
            .with_for_update()
        )
        base = await self.latest_transcript(recording.id)
        if base is None:
            raise ConflictError(
                "The transcript is not ready yet", code=ErrorCode.TRANSCRIPT_NOT_READY
            )
        if base.id != data.base_transcript_id:
            raise ConflictError(
                "The transcript was changed; reload it",
                code=ErrorCode.FEEDBACK_VERSION_CONFLICT,
                details={"current_transcript_id": str(base.id)},
            )
        current = await self.current_feedback(recording.id)
        if current is not None and current.status == FeedbackStatus.APPROVED:
            raise ConflictError(
                "The feedback from this transcript is approved; reopen it first",
                code=ErrorCode.TRANSCRIPT_LOCKED,
            )
        segments = [dict(s) for s in base.segments]
        by_index = {s["index"]: s for s in segments}
        unknown = [e.index for e in data.segments if e.index not in by_index]
        if unknown:
            raise UnprocessableError(
                "Unknown segment index", details={"indexes": unknown, "count": len(segments)}
            )
        for edit in data.segments:
            by_index[edit.index]["text"] = edit.text
        if current is not None:
            await self._supersede(current, editor, note="transcript edited")
        await self._cancel_active(AiProcessingJob.recording_id == recording.id, "TRANSCRIPT_EDITED")
        edited = FeedbackTranscript(
            id=uuid.uuid4(),
            recording_id=recording.id,
            artwork_id=recording.artwork_id,
            owner_id=recording.owner_id,
            job_id=None,
            language=base.language,
            duration_ms=base.duration_ms,
            text=" ".join(s["text"] for s in segments),
            segments=segments,
            segment_count=len(segments),
            engine="manual-edit",
            model_name=base.model_name,
            processing_ms=None,
            edited_from_id=base.id,
            edited_by=editor.id,
        )
        self.session.add(edited)
        await self.session.commit()
        return await self.transcript(recording)

    async def _supersede(self, summary: FeedbackSummary, actor: Profile, *, note: str) -> None:
        """현재 첨삭(초안·검토 중)을 대체 처리 (원문이 바뀜). 이력에 남긴다."""
        from_status = summary.status
        summary.status = FeedbackStatus.SUPERSEDED
        summary.version += 1
        self.session.add(
            FeedbackReviewHistory(
                id=uuid.uuid4(),
                summary_id=summary.id,
                actor_id=actor.id,
                actor_mode=None,
                action=ReviewAction.SUPERSEDED,
                from_status=from_status,
                to_status=FeedbackStatus.SUPERSEDED,
                version=summary.version,
                note=note,
            )
        )
        await self.session.flush()

    async def _cancel_active(self, condition: Any, code: str) -> None:
        """원문이 바뀐 요약 작업 취소 (RUNNING이면 Worker가 저장 직전에 확인하고 버린다)."""
        now = clock.utc_now()
        for job in (
            await self.session.execute(
                select(AiProcessingJob)
                .where(
                    condition,
                    AiProcessingJob.job_type == AiJobType.SUMMARIZE,
                    AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                )
                .with_for_update()
            )
        ).scalars():
            job.status = AiJobStatus.CANCELLED
            job.finished_at = now
            job.locked_by = None
            job.lease_expires_at = None
            job.last_error_code = code

    # ================================================================ 요약 (Gemini)

    async def request_summary(
        self, recording: FeedbackRecording, requester: Profile, *, regenerate: bool
    ) -> tuple[JobRead, bool]:
        if not self.settings.ai_summary_active:
            log_summary_disabled("request_summary")
            raise AiNotConfiguredError()
        recording_id = recording.id
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
        await check_summary_quota(self.session, self.settings, recording.owner_id)
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
            # rollback으로 ORM 객체가 만료되므로 미리 꺼낸 ID를 쓴다 (지연 로드 금지)
            existing = await self._active_job(recording_id, AiJobType.SUMMARIZE)
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
        """항목·카테고리·근거 구간(첨삭 id → 구간 번호 → 근거)·승인자 이름."""
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
        by_source: dict[uuid.UUID, dict[int, Evidence]] = {}
        transcript_ids = {s.transcript_id for s in summaries if s.transcript_id}
        if transcript_ids:
            for transcript_id, segs in (
                await self.session.execute(
                    select(FeedbackTranscript.id, FeedbackTranscript.segments).where(
                        FeedbackTranscript.id.in_(transcript_ids)
                    )
                )
            ).all():
                by_source[transcript_id] = {
                    s["index"]: Evidence(
                        index=s["index"], start_ms=s["start_ms"], end_ms=s["end_ms"], text=s["text"]
                    )
                    for s in segs
                }
        note_ids = {s.note_id for s in summaries if s.note_id}
        if note_ids:
            for note_id, segs in (
                await self.session.execute(
                    select(FeedbackNote.id, FeedbackNote.segments).where(
                        FeedbackNote.id.in_(note_ids)
                    )
                )
            ).all():
                by_source[note_id] = {
                    s["index"]: Evidence(index=s["index"], text=s["text"]) for s in segs
                }
        for s in summaries:
            segments[s.id] = by_source.get(s.transcript_id or s.note_id, {})  # type: ignore[arg-type]
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
            "note_id": summary.note_id,
            "source": summary.source,
            "artwork_id": summary.artwork_id,
            "status": summary.status,
            "review_mode": review_mode_for(artwork, summary.source),
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
            segments.get(summary.id, {}),
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
                # 자기 메모·다른 학생 의견은 학생 개인 기록 (강사에게 보이지 않음)
                FeedbackSummary.source == FeedbackSource.INSTRUCTOR,
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
        if review_mode_for(artwork, summary.source) == ReviewMode.SELF:
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
                    segments.get(s.id, {}),
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
            .outerjoin(FeedbackRecording, FeedbackRecording.id == FeedbackSummary.recording_id)
            .where(
                FeedbackSummary.source == FeedbackSource.INSTRUCTOR,
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
                note_id=s.note_id,
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

    def _reviewer_for_owner(
        self, owner: Profile, artwork: Artwork, summary: FeedbackSummary
    ) -> Reviewer:
        if review_mode_for(artwork, summary.source) != ReviewMode.SELF:
            raise ForbiddenError("Your instructor reviews feedback for academy artworks")
        return Reviewer(owner, None)

    async def _locked(
        self, reviewer_profile: Profile, feedback_id: uuid.UUID, actor: AcademyMembership | None
    ) -> tuple[FeedbackSummary, Artwork, Reviewer]:
        if actor is None:
            summary, artwork = await self.owner_feedback(
                reviewer_profile, feedback_id, for_update=True
            )
            return summary, artwork, self._reviewer_for_owner(reviewer_profile, artwork, summary)
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
                if summary.transcript_id
                else select(FeedbackNote.segment_count).where(FeedbackNote.id == summary.note_id)
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
        self._reviewer_for_owner(owner, artwork, summary)  # 학원 작품의 강사 첨삭 이력은 강사만
        return await self.history(summary)

    async def staff_history(
        self, actor: AcademyMembership, feedback_id: uuid.UUID
    ) -> list[ReviewHistoryRead]:
        summary, _ = await self.staff_feedback(actor, feedback_id)
        return await self.history(summary)
