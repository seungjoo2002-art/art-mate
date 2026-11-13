"""단계별 피드백 이력 (v0.9.7).

작품의 단계마다 [단계 사진 → 그 단계의 피드백(녹음·글 첨삭) → 피드백을 반영한 수정 사진]을 묶고,
단계를 정하지 않은 피드백은 '작품 전체 피드백'으로 따로 모은다.

- 수정 사진이 피드백을 잘 반영했는지는 판단하지 않는다 (연결 관계와 개수만 보여 준다).
- 숨긴 단계(archived)도 데이터 보존을 위해 이력에는 나온다 (활성 단계 뒤).
- 학생 본인만 조회한다 (ArtworkService.owned).
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feedback import FeedbackNote, FeedbackSummary
from app.models.artwork import ArtworkPhoto
from app.models.enums import CURRENT_FEEDBACK_STATUSES, PhotoKind, PhotoStatus, RecordingStatus
from app.models.profile import Profile
from app.models.recording import FeedbackRecording
from app.schemas.artworks import (
    ArtworkStageHistory,
    PhotoRead,
    StageFeedbackEntry,
    StageHistoryEntry,
)
from app.services.artwork_stages import all_stages, ensure_stages
from app.services.artworks import ArtworkService, stage_read

_NOTE_TITLE = 40


def _note_title(body: str) -> str:
    first = body.strip().splitlines()[0] if body.strip() else ""
    return first if len(first) <= _NOTE_TITLE else first[: _NOTE_TITLE - 1] + "…"


class StageHistoryService:
    def __init__(self, session: AsyncSession, artworks: ArtworkService) -> None:
        self.session = session
        self.artworks = artworks

    async def history(
        self, owner: Profile, artwork_id: uuid.UUID, token: str, include_urls: bool = False
    ) -> ArtworkStageHistory:
        artwork = await self.artworks.owned(owner, artwork_id)
        await ensure_stages(self.session, artwork)
        await self.session.commit()
        stages = await all_stages(self.session, artwork.id)

        photos = list(
            (
                await self.session.execute(
                    select(ArtworkPhoto)
                    .where(
                        ArtworkPhoto.artwork_id == artwork.id,
                        ArtworkPhoto.status == PhotoStatus.ACTIVE,
                    )
                    .order_by(ArtworkPhoto.uploaded_at, ArtworkPhoto.id)
                )
            ).scalars()
        )
        reads = await self.artworks._photo_reads(photos, token, include_urls)
        read_of: dict[uuid.UUID, PhotoRead] = {r.id: r for r in reads}

        recordings = list(
            (
                await self.session.execute(
                    select(FeedbackRecording)
                    .where(
                        FeedbackRecording.artwork_id == artwork.id,
                        FeedbackRecording.status == RecordingStatus.ACTIVE,
                    )
                    .order_by(FeedbackRecording.uploaded_at, FeedbackRecording.id)
                )
            ).scalars()
        )
        notes = list(
            (
                await self.session.execute(
                    select(FeedbackNote)
                    .where(FeedbackNote.artwork_id == artwork.id)
                    .order_by(FeedbackNote.feedback_date, FeedbackNote.created_at)
                )
            ).scalars()
        )
        summaries = (
            await self.session.execute(
                select(FeedbackSummary).where(
                    FeedbackSummary.artwork_id == artwork.id,
                    FeedbackSummary.status.in_(CURRENT_FEEDBACK_STATUSES),
                )
            )
        ).scalars()
        current: dict[uuid.UUID, FeedbackSummary] = {}
        for s in summaries:
            key = s.recording_id or s.note_id
            if key is not None:
                current[key] = s

        # 수정 사진: 피드백별 / 피드백이 지워진 것은 단계별
        revisions: dict[uuid.UUID, list[PhotoRead]] = defaultdict(list)
        unlinked: dict[uuid.UUID, list[PhotoRead]] = defaultdict(list)
        stage_photos: dict[uuid.UUID, list[PhotoRead]] = defaultdict(list)
        revision_count: dict[uuid.UUID, int] = defaultdict(int)
        for p in photos:
            read = read_of[p.id]
            if p.kind == PhotoKind.STAGE:
                stage_photos[p.stage_id].append(read)
                continue
            revision_count[p.stage_id] += 1
            ref = p.feedback_recording_id or p.feedback_note_id
            if ref is None:
                unlinked[p.stage_id].append(read)
            else:
                revisions[ref].append(read)
        for group in stage_photos.values():
            group.sort(key=lambda r: (not r.is_representative, r.uploaded_at or r.created_at))

        def entry_of_recording(r: FeedbackRecording) -> StageFeedbackEntry:
            summary = current.get(r.id)
            return StageFeedbackEntry(
                type="RECORDING",
                id=r.id,
                title=r.title,
                source=None,
                feedback_at=r.recorded_at or r.uploaded_at or r.created_at,
                transcription_status=r.transcription_status,
                ai_feedback_id=summary.id if summary else None,
                ai_feedback_status=summary.status if summary else None,
                revisions=revisions.get(r.id, []),
                revision_count=len(revisions.get(r.id, [])),
            )

        def entry_of_note(n: FeedbackNote) -> StageFeedbackEntry:
            summary = current.get(n.id)
            return StageFeedbackEntry(
                type="NOTE",
                id=n.id,
                title=_note_title(n.body),
                source=n.source,
                feedback_at=n.feedback_date,
                transcription_status=None,
                ai_feedback_id=summary.id if summary else None,
                ai_feedback_status=summary.status if summary else None,
                revisions=revisions.get(n.id, []),
                revision_count=len(revisions.get(n.id, [])),
            )

        by_stage: dict[uuid.UUID | None, list[StageFeedbackEntry]] = defaultdict(list)
        for r in recordings:
            by_stage[r.stage_id].append(entry_of_recording(r))
        for n in notes:
            by_stage[n.stage_id].append(entry_of_note(n))

        def _when(e: StageFeedbackEntry) -> str:
            return e.feedback_at.isoformat()

        return ArtworkStageHistory(
            artwork_id=artwork.id,
            stages=[
                StageHistoryEntry(
                    stage=stage_read(stage),
                    photos=stage_photos.get(stage.id, []),
                    feedback=sorted(by_stage.get(stage.id, []), key=_when),
                    unlinked_revisions=unlinked.get(stage.id, []),
                    revision_count=revision_count.get(stage.id, 0),
                )
                for stage in stages
            ],
            overall_feedback=sorted(by_stage.get(None, []), key=_when),
        )
