"""피드백 기준 이미지 (v0.9.8).

피드백(녹음·글 첨삭)이 실제로 어떤 작품 사진을 보고 작성됐는지를 고정 저장한다.

- 만들 때 사진을 고르면(reference_photo_ids) 그대로 연결. reference_confirmed=true면 CONFIRMED.
- 고르지 않으면 그 시점의 최신 사진(같은 단계, 단계 미지정이면 작품 전체)을
  **제안(SUGGESTED)** 으로 연결.
  제안은 사용자가 확인하기 전까지 학습 데이터로 쓰지 않는다.
- 연결은 행으로 저장되므로 이후 사진이 추가돼도 바뀌지 않는다.
  바꾸려면 명시적으로 다시 저장(replace)한다.
- STT 전사·AI 요약은 원본 녹음·글 첨삭에 매달려 있으므로 같은 연결을 그대로 보여 준다.
- 참조한 사진이 나중에 삭제돼도 연결 행은 남고(photo_status=DELETED), 학습 데이터에서는 빠진다.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.exceptions import UnprocessableError
from app.models.ai_feedback import FeedbackNote
from app.models.ai_revision import ArtworkAiRevision
from app.models.artwork import Artwork, ArtworkPhoto
from app.models.dataset import MAX_IMAGE_REFS, FeedbackImageRef
from app.models.enums import ImageRefStatus, PhotoStatus
from app.models.profile import Profile
from app.models.recording import FeedbackRecording
from app.schemas.image_refs import FeedbackImageRefRead, ImageRefsRead

Feedback = FeedbackRecording | FeedbackNote


async def latest_photo(
    session: AsyncSession, artwork_id: uuid.UUID, stage_id: uuid.UUID | None
) -> uuid.UUID | None:
    """제안용: 지금 시점의 최신 ACTIVE 사진 (같은 단계, 단계 미지정이면 작품 전체)."""
    stmt = select(ArtworkPhoto.id).where(
        ArtworkPhoto.artwork_id == artwork_id, ArtworkPhoto.status == PhotoStatus.ACTIVE
    )
    if stage_id is not None:
        stmt = stmt.where(ArtworkPhoto.stage_id == stage_id)
    stmt = stmt.order_by(ArtworkPhoto.uploaded_at.desc().nulls_last(), ArtworkPhoto.id.desc())
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


async def is_feedback_reference(session: AsyncSession, photo_id: uuid.UUID) -> bool:
    """이 사진을 기준 사진으로 삼은 피드백이 있는지 (사진 교체 때 파일을 남길지 정함)."""
    found = await session.execute(
        select(FeedbackImageRef.id).where(FeedbackImageRef.photo_id == photo_id).limit(1)
    )
    return found.first() is not None


async def is_kept_reference(session: AsyncSession, photo_id: uuid.UUID) -> bool:
    """교체 때 파일을 남겨야 하는 사진: 피드백 기준 사진이거나 (v1.3) AI 수정본의 원본."""
    if await is_feedback_reference(session, photo_id):
        return True
    found = await session.execute(
        select(ArtworkAiRevision.id)
        .where(ArtworkAiRevision.photo_id == photo_id, ArtworkAiRevision.deleted_at.is_(None))
        .limit(1)
    )
    return found.first() is not None


MAX_REPLACE_HOPS = 10


async def _successors(
    session: AsyncSession, photo_ids: Sequence[uuid.UUID]
) -> tuple[dict[uuid.UUID, uuid.UUID], set[uuid.UUID]]:
    """교체된 사진 id → 지금 그 자리에 있는 ACTIVE 사진 id (여러 번 교체돼도 따라감),
    그리고 교체된(삭제가 아닌) 사진 id 모음."""
    current: dict[uuid.UUID, uuid.UUID] = {}
    replaced: set[uuid.UUID] = set()
    frontier = {pid: pid for pid in photo_ids}  # 따라가는 중인 id → 처음 id
    for _ in range(MAX_REPLACE_HOPS):
        if not frontier:
            break
        rows = (
            await session.execute(
                select(ArtworkPhoto.id, ArtworkPhoto.replaces_photo_id, ArtworkPhoto.status).where(
                    ArtworkPhoto.replaces_photo_id.in_(list(frontier)),
                    # 업로드를 끝낸 교체만 (실패·만료된 교체 요청은 uploaded_at이 없음)
                    ArtworkPhoto.uploaded_at.isnot(None),
                )
            )
        ).all()
        nxt: dict[uuid.UUID, uuid.UUID] = {}
        for new_id, old_id, status in rows:
            origin = frontier[old_id]
            if old_id == origin:
                replaced.add(origin)
            if status == PhotoStatus.ACTIVE:
                current[origin] = new_id
            else:
                nxt[new_id] = origin
        frontier = nxt
    return current, replaced


async def _check_photos(
    session: AsyncSession, artwork_id: uuid.UUID, photo_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    ids = list(dict.fromkeys(photo_ids))  # 순서 유지, 중복 제거
    if len(ids) > MAX_IMAGE_REFS:
        raise UnprocessableError(
            f"Up to {MAX_IMAGE_REFS} reference photos per feedback",
            details={"max_photos": MAX_IMAGE_REFS},
        )
    if not ids:
        return ids
    found = set(
        (
            await session.execute(
                select(ArtworkPhoto.id).where(
                    ArtworkPhoto.id.in_(ids),
                    ArtworkPhoto.artwork_id == artwork_id,
                    ArtworkPhoto.status == PhotoStatus.ACTIVE,
                )
            )
        ).scalars()
    )
    missing = [i for i in ids if i not in found]
    if missing:
        raise UnprocessableError(
            "Reference photos must be uploaded photos of this artwork",
            details={"photo_id": str(missing[0])},
        )
    return ids


def _ref_filter(feedback: Feedback):  # type: ignore[no-untyped-def]
    if isinstance(feedback, FeedbackRecording):
        return FeedbackImageRef.feedback_recording_id == feedback.id
    return FeedbackImageRef.feedback_note_id == feedback.id


async def replace_refs(
    session: AsyncSession,
    artwork: Artwork,
    feedback: Feedback,
    photo_ids: Sequence[uuid.UUID],
    *,
    confirmed: bool,
    actor: Profile | None,
) -> None:
    """기준 사진을 통째로 바꾼다 (명시적 저장). 호출 쪽에서 커밋한다."""
    ids = await _check_photos(session, artwork.id, photo_ids)
    await session.execute(delete(FeedbackImageRef).where(_ref_filter(feedback)))
    is_recording = isinstance(feedback, FeedbackRecording)
    session.add_all(
        FeedbackImageRef(
            id=uuid.uuid4(),
            artwork_id=artwork.id,
            owner_id=artwork.owner_id,
            feedback_recording_id=feedback.id if is_recording else None,
            feedback_note_id=None if is_recording else feedback.id,
            photo_id=photo_id,
            position=i,
        )
        for i, photo_id in enumerate(ids)
    )
    if confirmed:
        # 사진 없이 받은 피드백이라고 확인한 경우도 확인으로 기록 (상태는 NONE)
        feedback.image_ref_status = ImageRefStatus.CONFIRMED if ids else ImageRefStatus.NONE
        feedback.image_ref_confirmed_at = clock.utc_now()
        feedback.image_ref_confirmed_by = actor.id if actor else None
    else:
        feedback.image_ref_status = ImageRefStatus.SUGGESTED if ids else ImageRefStatus.NONE
        feedback.image_ref_confirmed_at = None
        feedback.image_ref_confirmed_by = None


async def initial_refs(
    session: AsyncSession,
    artwork: Artwork,
    feedback: Feedback,
    photo_ids: Sequence[uuid.UUID] | None,
    *,
    confirmed: bool,
    actor: Profile,
) -> None:
    """피드백을 만들 때. 사진을 고르지 않았으면 최신 사진을 제안으로 (확인 아님)."""
    if photo_ids is None:
        suggested = await latest_photo(session, artwork.id, feedback.stage_id)
        await replace_refs(
            session,
            artwork,
            feedback,
            [suggested] if suggested else [],
            confirmed=False,
            actor=None,
        )
        return
    await replace_refs(session, artwork, feedback, photo_ids, confirmed=confirmed, actor=actor)


async def refs_by_feedback(
    session: AsyncSession,
    *,
    recording_ids: Sequence[uuid.UUID] = (),
    note_ids: Sequence[uuid.UUID] = (),
) -> dict[uuid.UUID, list[FeedbackImageRefRead]]:
    """피드백 id(녹음 또는 글 첨삭) → 기준 사진 목록 (순서대로)."""
    out: dict[uuid.UUID, list[FeedbackImageRefRead]] = defaultdict(list)
    conditions = []
    if recording_ids:
        conditions.append(FeedbackImageRef.feedback_recording_id.in_(list(recording_ids)))
    if note_ids:
        conditions.append(FeedbackImageRef.feedback_note_id.in_(list(note_ids)))
    found: list[tuple[FeedbackImageRef, ArtworkPhoto]] = []
    for condition in conditions:
        rows = await session.execute(
            select(FeedbackImageRef, ArtworkPhoto)
            .join(ArtworkPhoto, ArtworkPhoto.id == FeedbackImageRef.photo_id)
            .where(condition)
            .order_by(FeedbackImageRef.position)
        )
        found.extend((ref, photo) for ref, photo in rows)
    # 교체된 기준 사진: 연결은 교체 전 사진 그대로 두고, 지금 그 자리의 사진을 함께 알려 줌
    successors, replaced = await _successors(
        session, [photo.id for _, photo in found if photo.status == PhotoStatus.DELETED]
    )
    for ref, photo in found:
        key = ref.feedback_recording_id or ref.feedback_note_id
        current = photo.id if photo.status == PhotoStatus.ACTIVE else successors.get(photo.id)
        out[key].append(  # type: ignore[index]
            FeedbackImageRefRead(
                photo_id=photo.id,
                stage_id=photo.stage_id,
                position=ref.position,
                photo_status=photo.status,
                uploaded_at=photo.uploaded_at,
                replaced=photo.id in replaced,
                current_photo_id=current,
            )
        )
    return out


def refs_read(feedback: Feedback, photos: list[FeedbackImageRefRead]) -> ImageRefsRead:
    return ImageRefsRead(
        status=feedback.image_ref_status,
        confirmed_at=feedback.image_ref_confirmed_at,
        photos=photos,
    )


async def refs_for(session: AsyncSession, feedback: Feedback) -> ImageRefsRead:
    key = "recording_ids" if isinstance(feedback, FeedbackRecording) else "note_ids"
    found = await refs_by_feedback(session, **{key: [feedback.id]})
    return refs_read(feedback, found.get(feedback.id, []))
