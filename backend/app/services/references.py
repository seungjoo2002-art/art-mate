"""F-15 참고작: 강사 우수 사례 확인, 학생별 추천 생성·조회·저장 (v0.8).

- 우수성 근거는 강사가 남긴 `reference_artwork_reviews`(카테고리별)뿐이다. 강사는 담당 학생의 학원
  연결 작품만 확인할 수 있다. 확인 자체는 공개가 아니며, 원작자가 REFERENCE 동의를 해야 추천에
  쓰인다.
- 학생 추천: v0.7 반복 약점 TOP 3(승인 첨삭, 전체 범위) + 주 실기 유형으로 엔진을 돌려 스냅샷 저장.
  같은 입력이면 다시 만들지 않는다. 검증된 사례가 없으면 NO_VERIFIED_REFERENCES (억지로 채우지
  않음).
- 조회 시 원작자 동의·공개 범위·이미지·검토 상태·작품 삭제를 다시 확인 → 철회되면 저장한 항목도
  빠진다.
- 원작자 정보: 작성자 표시 설정(NAME/ANONYMOUS)에 따라 이름 또는 '익명 학생'. 학원명·연락처는
  미노출.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
)
from app.integrations.supabase.storage import StorageClient
from app.models.ai_feedback import FeedbackItem, FeedbackSummary
from app.models.artwork import Artwork, ArtworkPhoto
from app.models.community import (
    ArtworkSharingConsent,
    CommunityPost,
    ReferenceArtworkReview,
    ReferenceRecommendation,
    SharedArtworkImage,
)
from app.models.enums import (
    WEAKNESS_CATEGORY_LABELS,
    ArtworkStage,
    ArtworkWorkCategory,
    FeedbackItemKind,
    FeedbackStatus,
    GrowthScope,
    PhotoStatus,
    PostStatus,
    PracticalType,
    ReferenceResultStatus,
    ReferenceReviewStatus,
    ReferenceSetStatus,
    SharedImageStatus,
    SharingPurpose,
    WeaknessCategory,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.repositories.pagination import fetch_page
from app.schemas.community import (
    AuthorRead,
    CandidateRead,
    ReasonRead,
    ReferenceItem,
    ReferenceResult,
    RefreshResult,
    ReviewCreate,
    ReviewRead,
)
from app.schemas.students import student_ref
from app.services.access import AccessService, managed_student_ids
from app.services.growth import GrowthService, Scope
from app.services.reference_engine import (
    ENGINE_VERSION,
    StudentContext,
    VerifiedExemplarSource,
    rank_candidates,
)
from app.services.sharing import (
    ANONYMOUS_NAME,
    author_name,
    consent_read,
    sign_images,
    visible_consent,
)

MESSAGES = {
    ReferenceResultStatus.NO_REPEATED_WEAKNESS: (
        "추천 기준이 될 반복 약점이 아직 없습니다. 승인된 첨삭이 더 쌓이면 추천해 드릴게요."
    ),
    ReferenceResultStatus.NO_VERIFIED_REFERENCES: (
        "지금 약점에 맞는, 강사가 확인한 참고작이 아직 없습니다."
    ),
    ReferenceResultStatus.NOT_GENERATED: "아직 참고작 추천을 받지 않았습니다.",
}


class ReferenceService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        shared_storage: StorageClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.shared_storage = shared_storage
        self.access = AccessService(session)
        self.source = VerifiedExemplarSource()

    # ================================================================ 강사: 우수 사례 확인

    async def _managed_artwork(self, actor: AcademyMembership, artwork_id: uuid.UUID) -> Artwork:
        artwork = (
            await self.session.execute(
                select(Artwork).where(
                    Artwork.id == artwork_id,
                    Artwork.academy_id == actor.academy_id,
                    Artwork.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if artwork is None or artwork.student_membership_id is None:
            raise NotFoundError("Artwork not found")
        if not await self.access.is_managed_student(actor, artwork.student_membership_id):
            raise ForbiddenError("This student is not in your classes")
        return artwork

    async def create_review(
        self, actor: AcademyMembership, reviewer: Profile, data: ReviewCreate
    ) -> ReviewRead:
        artwork = await self._managed_artwork(actor, data.artwork_id)
        final = (
            await self.session.execute(
                select(ArtworkPhoto.id).where(
                    ArtworkPhoto.artwork_id == artwork.id,
                    ArtworkPhoto.stage == ArtworkStage.FINAL,
                    ArtworkPhoto.status == PhotoStatus.ACTIVE,
                )
            )
        ).first()
        if final is None:
            raise ConflictError(
                "A FINAL stage photo is required for a reference",
                code=ErrorCode.FINAL_PHOTO_REQUIRED,
            )
        review = ReferenceArtworkReview(
            id=uuid.uuid4(),
            artwork_id=artwork.id,
            owner_id=artwork.owner_id,
            academy_id=actor.academy_id,
            category=data.category,
            note=data.note,
            status=ReferenceReviewStatus.ACTIVE,
            reviewer_id=reviewer.id,
            reviewer_membership_id=actor.id,
        )
        self.session.add(review)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise ConflictError(
                "This artwork is already a reference for this category",
                code=ErrorCode.REFERENCE_REVIEW_EXISTS,
            ) from None
        return (await self._review_reads([review]))[0]

    async def revoke_review(
        self, actor: AcademyMembership, reviewer: Profile, review_id: uuid.UUID
    ) -> ReviewRead:
        review = (
            await self.session.execute(
                select(ReferenceArtworkReview)
                .where(
                    ReferenceArtworkReview.id == review_id,
                    ReferenceArtworkReview.academy_id == actor.academy_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if review is None:
            raise NotFoundError("Reference review not found")
        await self._managed_artwork(actor, review.artwork_id)
        if review.status == ReferenceReviewStatus.ACTIVE:
            review.status = ReferenceReviewStatus.REVOKED
            review.revoked_at = clock.utc_now()
            review.revoked_by = reviewer.id
            # 이 확인을 근거로 한 학생별 추천은 더 이상 근거가 없으므로 삭제
            await self.session.execute(
                ReferenceRecommendation.__table__.delete().where(
                    ReferenceRecommendation.review_id == review.id
                )
            )
            await self.session.commit()
        return (await self._review_reads([review]))[0]

    async def list_reviews(
        self,
        actor: AcademyMembership,
        params: Any,
        *,
        category: WeaknessCategory | None,
        student_membership_id: uuid.UUID | None,
        status: ReferenceReviewStatus | None,
    ) -> tuple[list[ReviewRead], int]:
        stmt = (
            select(ReferenceArtworkReview)
            .join(Artwork, Artwork.id == ReferenceArtworkReview.artwork_id)
            .where(
                ReferenceArtworkReview.academy_id == actor.academy_id,
                Artwork.student_membership_id.in_(managed_student_ids(actor)),
            )
        )
        if category is not None:
            stmt = stmt.where(ReferenceArtworkReview.category == category)
        if student_membership_id is not None:
            await self.access.require_managed_student(actor, student_membership_id)
            stmt = stmt.where(Artwork.student_membership_id == student_membership_id)
        if status is not None:
            stmt = stmt.where(ReferenceArtworkReview.status == status)
        stmt = stmt.order_by(ReferenceArtworkReview.created_at.desc(), ReferenceArtworkReview.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return await self._review_reads([r[0] for r in rows]), total

    async def _review_reads(self, reviews: list[ReferenceArtworkReview]) -> list[ReviewRead]:
        if not reviews:
            return []
        artwork_ids = {r.artwork_id for r in reviews}
        artworks = {
            a.id: a
            for a in (
                await self.session.execute(select(Artwork).where(Artwork.id.in_(artwork_ids)))
            ).scalars()
        }
        people = {
            m.id: (m, p)
            for m, p in (
                await self.session.execute(
                    select(AcademyMembership, Profile)
                    .join(Profile, Profile.id == AcademyMembership.user_id)
                    .where(
                        AcademyMembership.id.in_(
                            {a.student_membership_id for a in artworks.values()}
                        )
                    )
                )
            ).all()
        }
        consents = {
            c.artwork_id: c
            for c in (
                await self.session.execute(
                    select(ArtworkSharingConsent).where(
                        ArtworkSharingConsent.artwork_id.in_(artwork_ids),
                        ArtworkSharingConsent.purpose == SharingPurpose.REFERENCE,
                        ArtworkSharingConsent.revoked_at.is_(None),
                    )
                )
            ).scalars()
        }
        reviewers = dict(
            (
                await self.session.execute(
                    select(Profile.id, Profile.display_name).where(
                        Profile.id.in_({r.reviewer_id for r in reviews if r.reviewer_id})
                    )
                )
            ).all()
        )
        result = []
        for r in reviews:
            artwork = artworks[r.artwork_id]
            membership, profile = people[artwork.student_membership_id]  # type: ignore[index]
            consent = consents.get(r.artwork_id)
            result.append(
                ReviewRead(
                    id=r.id,
                    artwork_id=r.artwork_id,
                    artwork_title=artwork.title,
                    category=r.category,
                    note=r.note,
                    status=r.status,
                    reviewer_name=reviewers.get(r.reviewer_id) if r.reviewer_id else None,
                    student=student_ref(membership, profile),
                    reference_consent=consent_read(consent) if consent else None,
                    created_at=r.created_at,
                    revoked_at=r.revoked_at,
                )
            )
        return result

    async def candidates(
        self, actor: AcademyMembership, category: WeaknessCategory, limit: int
    ) -> list[CandidateRead]:
        """승인된 첨삭에서 이 카테고리가 '잘한 점'으로 언급된 담당 학생 작품 (강사 확인용 후보)."""
        rows = (
            await self.session.execute(
                select(Artwork, FeedbackItem.content)
                .join(FeedbackSummary, FeedbackSummary.artwork_id == Artwork.id)
                .join(FeedbackItem, FeedbackItem.summary_id == FeedbackSummary.id)
                .where(
                    Artwork.academy_id == actor.academy_id,
                    Artwork.deleted_at.is_(None),
                    Artwork.student_membership_id.in_(managed_student_ids(actor)),
                    FeedbackSummary.status == FeedbackStatus.APPROVED,
                    FeedbackItem.kind == FeedbackItemKind.STRENGTH,
                    FeedbackItem.category == category,
                )
                .order_by(Artwork.work_date.desc(), Artwork.id)
            )
        ).all()
        grouped: dict[uuid.UUID, tuple[Artwork, list[str]]] = {}
        for artwork, content in rows:
            grouped.setdefault(artwork.id, (artwork, []))[1].append(content)
        selected = list(grouped.values())[:limit]
        if not selected:
            return []
        ids = [a.id for a, _ in selected]
        reviewed = set(
            (
                await self.session.execute(
                    select(ReferenceArtworkReview.artwork_id).where(
                        ReferenceArtworkReview.artwork_id.in_(ids),
                        ReferenceArtworkReview.category == category,
                        ReferenceArtworkReview.status == ReferenceReviewStatus.ACTIVE,
                    )
                )
            ).scalars()
        )
        consented = set(
            (
                await self.session.execute(
                    select(ArtworkSharingConsent.artwork_id).where(
                        ArtworkSharingConsent.artwork_id.in_(ids),
                        ArtworkSharingConsent.purpose == SharingPurpose.REFERENCE,
                        ArtworkSharingConsent.revoked_at.is_(None),
                    )
                )
            ).scalars()
        )
        people = {
            m.id: (m, p)
            for m, p in (
                await self.session.execute(
                    select(AcademyMembership, Profile)
                    .join(Profile, Profile.id == AcademyMembership.user_id)
                    .where(AcademyMembership.id.in_({a.student_membership_id for a, _ in selected}))
                )
            ).all()
        }
        return [
            CandidateRead(
                artwork_id=a.id,
                artwork_title=a.title,
                work_date=a.work_date,
                practical_type=a.practical_type,
                student=student_ref(*people[a.student_membership_id]),  # type: ignore[index]
                strength_texts=texts[:3],
                already_reviewed=a.id in reviewed,
                has_reference_consent=a.id in consented,
            )
            for a, texts in selected
        ]

    # ================================================================ 학생: 추천

    async def _context(self, student: Profile) -> StudentContext:
        growth = GrowthService(self.session, self.settings)
        _, metrics, _ = await growth.recommendation_basis(Scope(student.id, GrowthScope.ALL))
        weaknesses = (
            [WeaknessCategory(c) for c in metrics["top_weaknesses"]]
            if metrics["status"] == "READY"
            else []
        )
        practical = student.practical_type or growth._main_practical_type(metrics)
        categories = frozenset(
            ArtworkWorkCategory(d["work_category"])
            for d in metrics["work_category_distribution"]
            if d["work_category"]
        )
        return StudentContext(student.id, weaknesses, practical, categories)

    @staticmethod
    def _fingerprint(context: StudentContext, candidates: list[Any]) -> str:
        parts = [
            ENGINE_VERSION,
            ",".join(c.value for c in context.weaknesses),
            context.practical_type.value if context.practical_type else "-",
            ",".join(sorted(c.value for c in context.work_categories)),
            *sorted(f"{c.review_id}:{c.consent_id}:{c.image_id}" for c in candidates),
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()

    async def refresh(self, student: Profile, token: str) -> RefreshResult:
        # 학생 단위 직렬화 (동시 새로고침으로 ACTIVE 묶음이 둘 생기지 않도록)
        await self.session.execute(
            select(Profile.id).where(Profile.id == student.id).with_for_update()
        )
        context = await self._context(student)
        active = list(
            (
                await self.session.execute(
                    select(ReferenceRecommendation).where(
                        ReferenceRecommendation.owner_id == student.id,
                        ReferenceRecommendation.status == ReferenceSetStatus.ACTIVE,
                    )
                )
            ).scalars()
        )
        candidates = await self.source.candidates(self.session, context)
        fingerprint = self._fingerprint(context, candidates)
        if active and active[0].data_fingerprint == fingerprint:
            await self.session.commit()
            result = await self.current(student, token, context=context)
            return RefreshResult(**result.model_dump(), refreshed=False)

        saved = {r.reference_artwork_id: r.saved_at for r in active if r.saved_at}
        saved.update(
            dict(
                (
                    await self.session.execute(
                        select(
                            ReferenceRecommendation.reference_artwork_id,
                            func.max(ReferenceRecommendation.saved_at),
                        )
                        .where(
                            ReferenceRecommendation.owner_id == student.id,
                            ReferenceRecommendation.saved_at.is_not(None),
                        )
                        .group_by(ReferenceRecommendation.reference_artwork_id)
                    )
                ).all()
            )
        )
        await self.session.execute(
            update(ReferenceRecommendation)
            .where(
                ReferenceRecommendation.owner_id == student.id,
                ReferenceRecommendation.status == ReferenceSetStatus.ACTIVE,
            )
            .values(status=ReferenceSetStatus.SUPERSEDED, updated_at=func.now())
        )
        scored = rank_candidates(
            context,
            candidates,
            per_weakness=self.settings.reference_per_weakness,
            max_results=self.settings.reference_max_results,
        )
        set_id = uuid.uuid4()
        inputs = {
            "engine": ENGINE_VERSION,
            "source": self.source.name,
            "weaknesses": [c.value for c in context.weaknesses],
            "practical_type": context.practical_type.value if context.practical_type else None,
            "work_categories": sorted(c.value for c in context.work_categories),
            "candidate_count": len(candidates),
        }
        for position, item in enumerate(scored, start=1):
            self.session.add(
                ReferenceRecommendation(
                    id=uuid.uuid4(),
                    owner_id=student.id,
                    set_id=set_id,
                    status=ReferenceSetStatus.ACTIVE,
                    weakness_category=item.candidate.category,
                    weakness_rank=item.weakness_rank,
                    reference_artwork_id=item.candidate.artwork_id,
                    review_id=item.candidate.review_id,
                    rank=position,
                    score=round(item.score, 4),
                    reasons=item.reasons,
                    inputs=inputs,
                    data_fingerprint=fingerprint,
                    saved_at=saved.get(item.candidate.artwork_id),
                )
            )
        await self.session.commit()
        result = await self.current(student, token, context=context)
        return RefreshResult(**result.model_dump(), refreshed=True)

    def _live_query(self, student: Profile) -> Any:
        """추천 행 + 지금도 볼 수 있는지 판단에 필요한 조인 (동의·이미지·검토·작품)."""
        return (
            select(
                ReferenceRecommendation,
                ReferenceArtworkReview,
                Artwork,
                ArtworkSharingConsent,
                SharedArtworkImage,
                Profile,
            )
            .join(
                ReferenceArtworkReview,
                ReferenceArtworkReview.id == ReferenceRecommendation.review_id,
            )
            .join(Artwork, Artwork.id == ReferenceRecommendation.reference_artwork_id)
            .join(Profile, Profile.id == Artwork.owner_id)
            .join(
                ArtworkSharingConsent,
                ArtworkSharingConsent.artwork_id == ReferenceRecommendation.reference_artwork_id,
            )
            .join(
                SharedArtworkImage,
                (SharedArtworkImage.artwork_id == ReferenceRecommendation.reference_artwork_id)
                & (SharedArtworkImage.status == SharedImageStatus.ACTIVE),
            )
            .where(
                ReferenceRecommendation.owner_id == student.id,
                ReferenceArtworkReview.status == ReferenceReviewStatus.ACTIVE,
                Artwork.deleted_at.is_(None),
                visible_consent(student.id, SharingPurpose.REFERENCE, include_own=False),
            )
        )

    async def _items(self, student: Profile, rows: list[Any], token: str) -> list[ReferenceItem]:
        images = await sign_images(
            self.shared_storage, self.settings, [row[4] for row in rows], token
        )
        artwork_ids = [row[2].id for row in rows]
        posts: dict[uuid.UUID, uuid.UUID] = {}
        if artwork_ids:
            posts = dict(
                (
                    await self.session.execute(
                        select(CommunityPost.artwork_id, CommunityPost.id)
                        .join(
                            ArtworkSharingConsent,
                            ArtworkSharingConsent.artwork_id == CommunityPost.artwork_id,
                        )
                        .where(
                            CommunityPost.artwork_id.in_(artwork_ids),
                            CommunityPost.status == PostStatus.ACTIVE,
                            visible_consent(student.id, SharingPurpose.COMMUNITY),
                        )
                    )
                ).all()
            )
        items = []
        for rec, review, artwork, consent, image, owner in rows:
            name = author_name(owner, consent.author_display, student.id)
            items.append(
                ReferenceItem(
                    id=rec.id,
                    weakness_category=rec.weakness_category,
                    weakness_label=WEAKNESS_CATEGORY_LABELS[rec.weakness_category],
                    weakness_rank=rec.weakness_rank,
                    rank=rec.rank,
                    reasons=[ReasonRead(**r) for r in rec.reasons],
                    reference_point=review.note,
                    reviewed_at=review.created_at,
                    practical_type=artwork.practical_type,
                    work_category=artwork.work_category,
                    author=AuthorRead(
                        display_name=name, is_anonymous=name == ANONYMOUS_NAME, is_me=False
                    ),
                    image=images.get(image.id),
                    community_post_id=posts.get(artwork.id),
                    saved=rec.saved_at is not None,
                    created_at=rec.created_at,
                )
            )
        return items

    async def current(
        self,
        student: Profile,
        token: str,
        *,
        category: WeaknessCategory | None = None,
        context: StudentContext | None = None,
    ) -> ReferenceResult:
        all_rows = list(
            (
                await self.session.execute(
                    select(ReferenceRecommendation).where(
                        ReferenceRecommendation.owner_id == student.id,
                        ReferenceRecommendation.status == ReferenceSetStatus.ACTIVE,
                    )
                )
            ).scalars()
        )
        stmt = self._live_query(student).where(
            ReferenceRecommendation.status == ReferenceSetStatus.ACTIVE
        )
        if category is not None:
            stmt = stmt.where(ReferenceRecommendation.weakness_category == category)
            all_rows = [r for r in all_rows if r.weakness_category == category]
        rows = list((await self.session.execute(stmt.order_by(ReferenceRecommendation.rank))).all())
        items = await self._items(student, rows, token)
        if all_rows:
            weaknesses = [WeaknessCategory(c) for c in all_rows[0].inputs.get("weaknesses", [])]
            practical = all_rows[0].inputs.get("practical_type")
            generated = all_rows[0].created_at
        elif context is not None:
            weaknesses, practical, generated = (
                context.weaknesses,
                context.practical_type.value if context.practical_type else None,
                clock.utc_now(),
            )
        else:
            weaknesses, practical, generated = [], None, None
        if items:
            status = ReferenceResultStatus.READY
        elif context is not None and not context.weaknesses:
            status = ReferenceResultStatus.NO_REPEATED_WEAKNESS
        elif context is not None or all_rows:
            status = ReferenceResultStatus.NO_VERIFIED_REFERENCES
        else:
            status = ReferenceResultStatus.NOT_GENERATED
        return ReferenceResult(
            status=status,
            message=MESSAGES.get(status),
            weaknesses=weaknesses,
            practical_type=PracticalType(practical) if practical else None,
            generated_at=generated,
            items=items,
            removed_count=len(all_rows) - len(items),
        )

    async def detail(self, student: Profile, rec_id: uuid.UUID, token: str) -> ReferenceItem:
        row = (
            await self.session.execute(
                self._live_query(student).where(ReferenceRecommendation.id == rec_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("Reference not found or no longer shared")
        return (await self._items(student, [row], token))[0]

    async def set_saved(
        self, student: Profile, rec_id: uuid.UUID, saved: bool, token: str
    ) -> ReferenceItem:
        row = (
            await self.session.execute(
                self._live_query(student).where(ReferenceRecommendation.id == rec_id)
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("Reference not found or no longer shared")
        rec = row[0]
        await self.session.execute(
            update(ReferenceRecommendation)
            .where(
                ReferenceRecommendation.owner_id == student.id,
                ReferenceRecommendation.reference_artwork_id == rec.reference_artwork_id,
            )
            .values(saved_at=clock.utc_now() if saved else None, updated_at=func.now())
        )
        await self.session.commit()
        return await self.detail(student, rec_id, token)

    async def saved(self, student: Profile, token: str) -> list[ReferenceItem]:
        """저장한 참고작 (원작자 철회·검토 해제·삭제된 것은 빠짐). 작품당 최근 행 1개."""
        rows = list(
            (
                await self.session.execute(
                    self._live_query(student)
                    .where(ReferenceRecommendation.saved_at.is_not(None))
                    .order_by(
                        ReferenceRecommendation.saved_at.desc(),
                        ReferenceRecommendation.created_at.desc(),
                    )
                )
            ).all()
        )
        seen: set[uuid.UUID] = set()
        unique = []
        for row in rows:
            if row[2].id not in seen:
                seen.add(row[2].id)
                unique.append(row)
        return await self._items(student, unique, token)
