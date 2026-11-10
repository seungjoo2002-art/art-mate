"""개인 맞춤 과제 ↔ 수행 작품 연결 (v0.9 F-8). 작품·성장 서비스가 함께 쓴다 (모델만 의존).

- 학생 본인의 개인(PERSONAL) 과제 중 채택(ADOPTED)·완료(COMPLETED)된 것에만 연결한다.
- 작품도 본인 소유·삭제 안 됨이어야 한다 (복합 FK가 DB에서도 소유자 일치를 강제).
- 이미 연결돼 있으면 그대로 둔다 (멱등). 연결·해제는 과제 이력에 남긴다.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ErrorCode, NotFoundError
from app.models.artwork import Artwork
from app.models.enums import (
    GrowthScope,
    RecommendationAction,
    RecommendationStatus,
    ReviewMode,
)
from app.models.growth import (
    PracticeRecommendation,
    PracticeRecommendationArtwork,
    PracticeRecommendationHistory,
)
from app.models.profile import Profile

LINKABLE = (RecommendationStatus.ADOPTED, RecommendationStatus.COMPLETED)
MAX_LINKED_ARTWORKS = 20


async def personal_recommendation(
    session: AsyncSession, owner: Profile, rec_id: uuid.UUID, *, for_update: bool = False
) -> PracticeRecommendation:
    stmt = select(PracticeRecommendation).where(
        PracticeRecommendation.id == rec_id,
        PracticeRecommendation.owner_id == owner.id,
        PracticeRecommendation.scope == GrowthScope.PERSONAL,
        PracticeRecommendation.status != RecommendationStatus.SUPERSEDED,
    )
    if for_update:
        stmt = stmt.with_for_update()
    rec = (await session.execute(stmt)).scalar_one_or_none()
    if rec is None:
        raise NotFoundError("Recommendation not found")
    return rec


def _history(
    session: AsyncSession,
    rec: PracticeRecommendation,
    owner: Profile,
    action: RecommendationAction,
    artwork_id: uuid.UUID,
) -> None:
    session.add(
        PracticeRecommendationHistory(
            id=uuid.uuid4(),
            recommendation_id=rec.id,
            actor_id=owner.id,
            actor_mode=ReviewMode.SELF,
            action=action,
            from_status=rec.status,
            to_status=rec.status,
            version=rec.version,
            changes={"artwork_id": str(artwork_id)},
        )
    )


async def link_artwork(
    session: AsyncSession, owner: Profile, rec_id: uuid.UUID, artwork: Artwork
) -> bool:
    """연결했으면 True, 이미 연결돼 있으면 False. 호출자가 commit 한다."""
    rec = await personal_recommendation(session, owner, rec_id, for_update=True)
    if rec.status not in LINKABLE:
        raise ConflictError(
            "Adopt the recommendation before linking artworks",
            code=ErrorCode.RECOMMENDATION_INVALID_STATE,
            details={"status": rec.status.value},
        )
    if artwork.owner_id != owner.id or artwork.deleted_at is not None:
        raise NotFoundError("Artwork not found")
    count = len(
        (
            await session.execute(
                select(PracticeRecommendationArtwork.id).where(
                    PracticeRecommendationArtwork.recommendation_id == rec.id
                )
            )
        ).all()
    )
    if count >= MAX_LINKED_ARTWORKS:
        raise ConflictError(
            "Too many artworks linked to this recommendation",
            code=ErrorCode.RECOMMENDATION_ARTWORK_INVALID,
            details={"max": MAX_LINKED_ARTWORKS},
        )
    inserted = (
        await session.execute(
            insert(PracticeRecommendationArtwork)
            .values(
                id=uuid.uuid4(), recommendation_id=rec.id, artwork_id=artwork.id, owner_id=owner.id
            )
            .on_conflict_do_nothing(index_elements=["recommendation_id", "artwork_id"])
            .returning(PracticeRecommendationArtwork.id)
        )
    ).first()
    if inserted is not None:
        _history(session, rec, owner, RecommendationAction.ARTWORK_LINKED, artwork.id)
    return inserted is not None


async def unlink_artwork(
    session: AsyncSession, owner: Profile, rec_id: uuid.UUID, artwork_id: uuid.UUID
) -> None:
    rec = await personal_recommendation(session, owner, rec_id, for_update=True)
    link = (
        await session.execute(
            select(PracticeRecommendationArtwork).where(
                PracticeRecommendationArtwork.recommendation_id == rec.id,
                PracticeRecommendationArtwork.artwork_id == artwork_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise NotFoundError("Linked artwork not found")
    await session.delete(link)
    _history(session, rec, owner, RecommendationAction.ARTWORK_UNLINKED, artwork_id)
