"""텍스트 첨삭 기록 (v0.9 F-3): 녹음 없이 첨삭을 직접 입력한다.

흐름 (녹음 첨삭과 같은 파이프라인)
    feedback_notes(원문, 문장 단위 segments) ─(SUMMARIZE 작업, Gemini · AI 전송 동의 필요)→
    feedback_summaries(note_id, source) ─ 학생 본인 검토·수정·확정(SELF) 또는 담당 강사 확정
    → 승인(APPROVED)된 강사 첨삭(INSTRUCTOR)만 반복 약점 통계에 집계 (자기 메모·다른 학생 의견은
      '참고' 통계로 분리)

권한: 작품 소유 학생 본인만 만들고·보고·고치고·지운다 (학원 연결과 무관). 강사는 학원 작품의
강사 첨삭(INSTRUCTOR) 요약만 기존 검토 화면에서 본다 (원문 문장은 근거로 함께 보임).

원문 수정 규칙
- 확정(APPROVED)된 요약이 있으면 원문·출처를 바꿀 수 없다 (409 FEEDBACK_NOTE_LOCKED)
  → 먼저 다시 연다.
- 초안·검토 중 요약은 대체(SUPERSEDED)되고 진행 중 요약 작업은 취소된다 → 새로 요약을 요청한다.
- 삭제하면 요약·항목·이력이 함께 지워져 성장 분석에서 즉시 빠진다.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import (
    AiNotConfiguredError,
    ConflictError,
    ErrorCode,
    NotFoundError,
)
from app.models.ai_feedback import AiProcessingJob, FeedbackNote, FeedbackSummary
from app.models.artwork import Artwork
from app.models.enums import (
    ACTIVE_JOB_STATUSES,
    CURRENT_FEEDBACK_STATUSES,
    AiJobStatus,
    AiJobType,
    FeedbackStatus,
)
from app.models.profile import Profile
from app.schemas.ai_feedback import (
    FeedbackNoteCreate,
    FeedbackNoteRead,
    FeedbackNoteUpdate,
    JobRead,
    NoteSegment,
)
from app.services.ai_feedback import AiFeedbackService, job_read, review_mode_for
from app.services.ai_limits import check_summary_quota, log_summary_disabled
from app.services.ai_summary import split_segments

MAX_NOTES_PER_ARTWORK = 50


class FeedbackNoteService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.feedback = AiFeedbackService(session, settings)

    # ------------------------------------------------------------------ 조회

    async def _note(
        self, owner: Profile, note_id: uuid.UUID, *, for_update: bool = False
    ) -> tuple[FeedbackNote, Artwork]:
        stmt = (
            select(FeedbackNote, Artwork)
            .join(Artwork, Artwork.id == FeedbackNote.artwork_id)
            .where(
                FeedbackNote.id == note_id,
                FeedbackNote.owner_id == owner.id,
                Artwork.deleted_at.is_(None),
            )
        )
        if for_update:
            stmt = stmt.with_for_update(of=FeedbackNote)
        row = (await self.session.execute(stmt)).one_or_none()
        if row is None:
            raise NotFoundError("Feedback note not found")
        return row[0], row[1]

    async def _current(self, note_id: uuid.UUID) -> FeedbackSummary | None:
        return (
            await self.session.execute(
                select(FeedbackSummary).where(
                    FeedbackSummary.note_id == note_id,
                    FeedbackSummary.status.in_(CURRENT_FEEDBACK_STATUSES),
                )
            )
        ).scalar_one_or_none()

    async def _latest_job(self, note_id: uuid.UUID) -> AiProcessingJob | None:
        return (
            await self.session.execute(
                select(AiProcessingJob)
                .where(AiProcessingJob.note_id == note_id)
                .order_by(AiProcessingJob.created_at.desc(), AiProcessingJob.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _active_job(self, note_id: uuid.UUID) -> AiProcessingJob | None:
        return (
            await self.session.execute(
                select(AiProcessingJob).where(
                    AiProcessingJob.note_id == note_id,
                    AiProcessingJob.job_type == AiJobType.SUMMARIZE,
                    AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                )
            )
        ).scalar_one_or_none()

    async def _read(self, note: FeedbackNote, artwork: Artwork) -> FeedbackNoteRead:
        current = await self._current(note.id)
        job = await self._latest_job(note.id)
        return FeedbackNoteRead(
            id=note.id,
            artwork_id=note.artwork_id,
            source=note.source,
            body=note.body,
            segments=[NoteSegment(**s) for s in note.segments],
            feedback_date=note.feedback_date,
            version=note.version,
            community_comment_id=note.community_comment_id,
            feedback_id=current.id if current else None,
            feedback_status=current.status if current else None,
            review_mode=review_mode_for(artwork, note.source),
            summary_job=job_read(job) if job else None,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )

    async def list_for_artwork(
        self, owner: Profile, artwork_id: uuid.UUID
    ) -> list[FeedbackNoteRead]:
        artwork = await self.feedback.artworks.owned(owner, artwork_id)
        notes = (
            await self.session.execute(
                select(FeedbackNote)
                .where(FeedbackNote.artwork_id == artwork.id)
                .order_by(FeedbackNote.feedback_date.desc(), FeedbackNote.created_at.desc())
            )
        ).scalars()
        return [await self._read(n, artwork) for n in notes]

    async def get(self, owner: Profile, note_id: uuid.UUID) -> FeedbackNoteRead:
        note, artwork = await self._note(owner, note_id)
        return await self._read(note, artwork)

    # ------------------------------------------------------------------ 생성·수정·삭제

    async def create(
        self,
        owner: Profile,
        artwork_id: uuid.UUID,
        data: FeedbackNoteCreate,
        *,
        community_comment_id: uuid.UUID | None = None,
    ) -> FeedbackNoteRead:
        artwork = await self.feedback.artworks.owned(owner, artwork_id, for_update=True)
        count = (
            await self.session.execute(
                select(func.count())
                .select_from(FeedbackNote)
                .where(FeedbackNote.artwork_id == artwork.id)
            )
        ).scalar_one()
        if count >= MAX_NOTES_PER_ARTWORK:
            raise ConflictError(
                f"Up to {MAX_NOTES_PER_ARTWORK} text feedback notes per artwork",
                code=ErrorCode.FEEDBACK_NOTE_LIMIT,
            )
        segments = split_segments(data.body)
        note = FeedbackNote(
            id=uuid.uuid4(),
            artwork_id=artwork.id,
            owner_id=owner.id,
            source=data.source,
            body=data.body,
            segments=segments,
            segment_count=len(segments),
            feedback_date=data.feedback_date or clock.local_today(),
            version=1,
            community_comment_id=community_comment_id,
            created_by=owner.id,
        )
        self.session.add(note)
        await self.session.commit()
        if data.request_summary and await self._can_summarize(owner.id):
            await self._queue(note.id, note.artwork_id, owner, note.version)
        note, artwork = await self._note(owner, note.id)
        return await self._read(note, artwork)

    async def update(
        self, owner: Profile, note_id: uuid.UUID, data: FeedbackNoteUpdate
    ) -> FeedbackNoteRead:
        note, artwork = await self._note(owner, note_id, for_update=True)
        if note.version != data.version:
            raise ConflictError(
                "The note was changed; reload it",
                code=ErrorCode.FEEDBACK_VERSION_CONFLICT,
                details={"current_version": note.version},
            )
        content_changed = ("body" in data.model_fields_set and data.body != note.body) or (
            "source" in data.model_fields_set and data.source != note.source
        )
        current = await self._current(note.id)
        if content_changed and current is not None:
            if current.status == FeedbackStatus.APPROVED:
                raise ConflictError(
                    "The AI summary of this note is approved; reopen it before editing",
                    code=ErrorCode.FEEDBACK_NOTE_LOCKED,
                    details={"feedback_id": str(current.id)},
                )
            await self.feedback._supersede(current, owner, note="note edited")
        if content_changed:
            await self.feedback._cancel_active(AiProcessingJob.note_id == note.id, "NOTE_EDITED")
        if "body" in data.model_fields_set and data.body is not None:
            note.body = data.body
            note.segments = split_segments(data.body)
            note.segment_count = len(note.segments)
        if "source" in data.model_fields_set and data.source is not None:
            note.source = data.source
        if "feedback_date" in data.model_fields_set and data.feedback_date is not None:
            note.feedback_date = data.feedback_date
        note.version += 1
        await self.session.commit()
        note, artwork = await self._note(owner, note_id)
        return await self._read(note, artwork)

    async def delete(self, owner: Profile, note_id: uuid.UUID) -> None:
        """원문과 그 요약·항목·이력을 삭제 (작업은 FK CASCADE). 성장 분석에서 즉시 빠진다."""
        note, _ = await self._note(owner, note_id, for_update=True)
        await self.session.delete(note)
        await self.session.commit()

    # ------------------------------------------------------------------ AI 요약

    async def _can_summarize(self, owner_id: uuid.UUID) -> bool:
        return self.settings.ai_summary_active and await self.feedback.has_valid_ai_consent(
            owner_id
        )

    async def _queue(
        self, note_id: uuid.UUID, artwork_id: uuid.UUID, requester: Profile, version: int
    ) -> tuple[JobRead, bool]:
        job = AiProcessingJob(
            id=uuid.uuid4(),
            job_type=AiJobType.SUMMARIZE,
            status=AiJobStatus.QUEUED,
            note_id=note_id,
            artwork_id=artwork_id,
            owner_id=requester.id,
            requested_by=requester.id,
            attempts=0,
            max_attempts=self.settings.job_max_attempts,
            run_after=clock.utc_now(),
            params={"note_version": version},
        )
        self.session.add(job)
        try:
            await self.session.commit()
        except IntegrityError:
            # 동시 요청: 부분 유니크(uq_ai_processing_jobs_active_note) → 먼저 만든 작업
            await self.session.rollback()
            existing = await self._active_job(note_id)
            if existing is None:
                raise
            return job_read(existing), False
        await self.session.refresh(job)
        return job_read(job), True

    async def request_summary(
        self, owner: Profile, note_id: uuid.UUID, *, regenerate: bool
    ) -> tuple[JobRead, bool]:
        if not self.settings.ai_summary_active:
            log_summary_disabled("note_summary")
            raise AiNotConfiguredError()
        note, _ = await self._note(owner, note_id)
        ids: dict[str, Any] = {"note": note.id, "artwork": note.artwork_id, "version": note.version}
        active = await self._active_job(note.id)
        if active is not None:
            return job_read(active), False
        if not await self.feedback.has_valid_ai_consent(owner.id):
            raise ConflictError(
                "Your consent to external AI processing is required",
                code=ErrorCode.AI_CONSENT_REQUIRED,
                details={"required_version": self.settings.ai_consent_version},
            )
        current = await self._current(note.id)
        if current is not None and current.status == FeedbackStatus.APPROVED:
            raise ConflictError(
                "The summary is already approved; reopen it before regenerating",
                code=ErrorCode.FEEDBACK_ALREADY_APPROVED,
            )
        if current is not None and not regenerate:
            raise ConflictError(
                "A summary draft already exists; use regenerate",
                code=ErrorCode.FEEDBACK_INVALID_STATE,
                details={"feedback_id": str(current.id)},
            )
        await check_summary_quota(self.session, self.settings, owner.id)
        return await self._queue(ids["note"], ids["artwork"], owner, ids["version"])
