"""F-15 참고작 추천 엔진 (규칙 기반 1차, `reference-rule-v1`).

구조 (교체·확장 가능)
- CandidateSource: 추천 후보를 가져오는 곳. 1차 구현은 `VerifiedExemplarSource` 하나 —
  강사가 '이 약점의 우수 사례'로 확인한 작품만 후보가 된다. 향후 이미지 임베딩 유사도·AI 시각 분석은
  새 Source(또는 점수 보정 단계)로 추가하되, **우수성 근거는 사람이 확인한 기록**이라는 원칙을
  유지한다.
- rank_candidates: 학생 맥락(반복 약점 순위, 주 실기 유형, 작업 목적)으로 점수를 매기고 근거 문장을
  만든다.

후보 조건 (모두 SQL에서 강제)
- 강사 우수 사례 확인(ACTIVE) + 그 카테고리가 학생의 반복 약점
- 원작자의 REFERENCE 동의가 유효하고 그 범위가 이 학생에게 열려 있음 (PLATFORM, 또는 같은 학원 멤버)
- 공유용 이미지 ACTIVE, 작품 삭제 안 됨, 학생 본인 작품 제외

점수 (높을수록 먼저)
- 약점 순위: (약점 수 - 순위 + 1) × 10   ← 1순위 약점이 가장 큼
- 같은 실기 유형 +5, 학생이 해 온 작업 목적과 같음 +2
- 같은 작품이 여러 약점에 해당하면 한 번만 (가장 높은 점수), 약점당·전체 개수 제한
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artwork import Artwork
from app.models.community import ArtworkSharingConsent, ReferenceArtworkReview, SharedArtworkImage
from app.models.enums import (
    PRACTICAL_TYPE_LABELS,
    WEAKNESS_CATEGORY_LABELS,
    WORK_CATEGORY_LABELS,
    ArtworkWorkCategory,
    AuthorDisplay,
    PracticalType,
    ReferenceReason,
    ReferenceReviewStatus,
    SharedImageKind,
    SharedImageStatus,
    SharingPurpose,
    WeaknessCategory,
)
from app.services.sharing import visible_consent

ENGINE_VERSION = "reference-rule-v1"


@dataclass(frozen=True)
class Candidate:
    review_id: uuid.UUID
    artwork_id: uuid.UUID
    owner_id: uuid.UUID
    category: WeaknessCategory
    note: str
    reviewed_at: datetime
    practical_type: PracticalType | None
    work_category: ArtworkWorkCategory | None
    consent_id: uuid.UUID
    author_display: AuthorDisplay
    image_id: uuid.UUID


@dataclass(frozen=True)
class StudentContext:
    viewer_id: uuid.UUID
    weaknesses: list[WeaknessCategory]  # 순위순 (v0.7 TOP 3)
    practical_type: PracticalType | None
    work_categories: frozenset[ArtworkWorkCategory] = frozenset()


@dataclass
class Scored:
    candidate: Candidate
    weakness_rank: int
    score: float
    reasons: list[dict[str, str]] = field(default_factory=list)


class CandidateSource(Protocol):
    name: str

    async def candidates(
        self, session: AsyncSession, context: StudentContext
    ) -> list[Candidate]: ...


class VerifiedExemplarSource:
    """강사가 확인한 우수 사례 + 원작자 참고작 활용 동의 + 공개 범위 + 공유 이미지."""

    name = "verified-exemplar"

    async def candidates(self, session: AsyncSession, context: StudentContext) -> list[Candidate]:
        if not context.weaknesses:
            return []
        rows = (
            await session.execute(
                select(
                    ReferenceArtworkReview, Artwork, ArtworkSharingConsent, SharedArtworkImage.id
                )
                .join(Artwork, Artwork.id == ReferenceArtworkReview.artwork_id)
                .join(
                    ArtworkSharingConsent,
                    ArtworkSharingConsent.artwork_id == ReferenceArtworkReview.artwork_id,
                )
                .join(
                    SharedArtworkImage,
                    (SharedArtworkImage.artwork_id == ReferenceArtworkReview.artwork_id)
                    & (SharedArtworkImage.status == SharedImageStatus.ACTIVE)
                    & (SharedArtworkImage.kind == SharedImageKind.PRIMARY),
                )
                .where(
                    ReferenceArtworkReview.status == ReferenceReviewStatus.ACTIVE,
                    ReferenceArtworkReview.category.in_(context.weaknesses),
                    Artwork.deleted_at.is_(None),
                    Artwork.owner_id != context.viewer_id,
                    visible_consent(context.viewer_id, SharingPurpose.REFERENCE, include_own=False),
                )
            )
        ).all()
        return [
            Candidate(
                review_id=review.id,
                artwork_id=artwork.id,
                owner_id=artwork.owner_id,
                category=review.category,
                note=review.note,
                reviewed_at=review.created_at,
                practical_type=artwork.practical_type,
                work_category=artwork.work_category,
                consent_id=consent.id,
                author_display=consent.author_display,
                image_id=image_id,
            )
            for review, artwork, consent, image_id in rows
        ]


def rank_candidates(
    context: StudentContext,
    candidates: list[Candidate],
    *,
    per_weakness: int,
    max_results: int,
) -> list[Scored]:
    count = len(context.weaknesses)
    best: dict[uuid.UUID, Scored] = {}
    for c in candidates:
        rank = context.weaknesses.index(c.category) + 1
        label = WEAKNESS_CATEGORY_LABELS[c.category]
        score = float((count - rank + 1) * 10)
        reasons = [
            {
                "code": ReferenceReason.VERIFIED_EXEMPLAR.value,
                "message": f"'{label}' 표현의 참고 사례로 강사가 확인한 작품입니다.",
            },
            {
                "code": ReferenceReason.MATCHES_WEAKNESS.value,
                "message": f"최근 첨삭에서 반복된 '{label}' 약점과 관련된 사례입니다.",
            },
        ]
        if context.practical_type is not None and c.practical_type == context.practical_type:
            score += 5
            reasons.append(
                {
                    "code": ReferenceReason.SAME_PRACTICAL_TYPE.value,
                    "message": f"현재 연습 중인 '{PRACTICAL_TYPE_LABELS[c.practical_type]}' "
                    "유형과 일치합니다.",
                }
            )
        if c.work_category is not None and c.work_category in context.work_categories:
            score += 2
            reasons.append(
                {
                    "code": ReferenceReason.SAME_WORK_CATEGORY.value,
                    "message": f"자주 하는 '{WORK_CATEGORY_LABELS[c.work_category]}' 작업과 같은 "
                    "분류의 작품입니다.",
                }
            )
        # 같은 점수면 최근에 확인된 우수 사례 먼저 (아주 작은 가중치)
        score += c.reviewed_at.timestamp() / 1e12
        scored = Scored(c, rank, score, reasons)
        previous = best.get(c.artwork_id)
        if previous is None or scored.score > previous.score:
            best[c.artwork_id] = scored

    result: list[Scored] = []
    per: dict[WeaknessCategory, int] = {}
    for item in sorted(best.values(), key=lambda s: (-s.score, str(s.candidate.artwork_id))):
        category = item.candidate.category
        if per.get(category, 0) >= per_weakness:
            continue
        per[category] = per.get(category, 0) + 1
        result.append(item)
        if len(result) >= max_results:
            break
    return result
