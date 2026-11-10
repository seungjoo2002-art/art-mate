"""성장 코치 (v0.7).

성장 데이터 통합 조회, 반복 약점 분석, 성장 리포트, 맞춤 연습 과제 추천·검토·배포.

권한 (기존 작품·첨삭 정책을 그대로 따른다)
- 학생: 본인 데이터만. 범위 ALL(모든 작품)·PERSONAL(학원 미연결)·ACADEMY(특정 학원 연결 작품).
- 강사: 학원 경로(/academies/{id})에서 담당 학생(managed_student_ids)의
  그 학원 연결 작품만 (ACADEMY). 학생의 개인 작품·다른 학원 작품은 통계·근거·리포트
  어디에도 포함되지 않는다. 비담당 403, 다른 학원 404.
- 데이터: 승인(APPROVED)된 첨삭만, 삭제된 작품·녹음은 제외 (삭제 시 첨삭도 삭제됨).

추천 과제
- 학원 범위(ACADEMY): 담당 강사가 검토·수정·승인 → 기존 v0.3 과제(tasks/task_assignments)로 배포.
  학생은 배포된 것만 보고, 완료는 기존 과제 완료 API
  (PUT /academies/{id}/tasks/{task_id}/completion).
- 개인 범위(PERSONAL): 강사에게 보이지 않고 학생 본인이 수정·채택·완료 기록.
- 규칙 기반(템플릿 + 실제 첨삭 근거)은 즉시,
  AI(Gemini)는 GROWTH_COACHING 동의 후 Worker가 비동기 생성.

접근 기록: 리포트·학생 성장 데이터 조회는 viewer·대상 ID만 구조화 로그로 남긴다 (내용 미기록).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    UnprocessableError,
)
from app.models.academy_class import AcademyClass, ClassMembership
from app.models.ai_feedback import (
    AiProcessingJob,
    FeedbackCategory,
    FeedbackItem,
    FeedbackNote,
    FeedbackSummary,
    FeedbackTranscript,
)
from app.models.artwork import Artwork, ArtworkPhoto
from app.models.enums import (
    ACTIVE_JOB_STATUSES,
    WEAKNESS_CATEGORY_LABELS,
    AiConsentPurpose,
    AiJobStatus,
    AiJobType,
    ArtworkWorkCategory,
    ClassMemberRole,
    ClassMemberStatus,
    ClassStatus,
    FeedbackItemKind,
    FeedbackSource,
    FeedbackStatus,
    GrowthScope,
    MembershipRole,
    NarrativeStatus,
    PhotoStatus,
    PracticalType,
    RecommendationAction,
    RecommendationSource,
    RecommendationStatus,
    ReportPeriod,
    ReportStatus,
    ReviewMode,
    TaskTargetType,
    WeaknessCategory,
)
from app.models.growth import (
    GrowthReport,
    PracticeRecommendation,
    PracticeRecommendationArtwork,
    PracticeRecommendationHistory,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.models.task import Task, TaskAssignment
from app.repositories.pagination import fetch_page
from app.schemas.ai_feedback import JobRead
from app.schemas.common import PaginationParams
from app.schemas.growth import (
    ArtworkComparison,
    ComparisonPhoto,
    ComparisonSide,
    Evidence,
    FollowUp,
    GenerationResult,
    GrowthSummary,
    LinkedArtwork,
    NarrativeRead,
    RecentFeedback,
    RecommendationCompletion,
    RecommendationDecision,
    RecommendationDistribute,
    RecommendationGenerate,
    RecommendationHistoryRead,
    RecommendationRead,
    RecommendationRef,
    RecommendationReject,
    RecommendationStart,
    RecommendationUpdate,
    ReportCreate,
    ReportListItem,
    ReportMeta,
    ReportRead,
    ReviewerRecommendationRead,
    ScopeRead,
    StageCount,
    StudentGrowthRow,
    TaskLink,
    TimelineArtwork,
    TimelineFeedback,
    TimelineTask,
    WeaknessAnalysis,
    WeaknessHistoryItem,
)
from app.schemas.students import StudentRef, student_ref
from app.schemas.tasks import TaskCreate
from app.services.access import AccessService, is_admin, managed_student_ids, taught_class_ids
from app.services.ai_cleanup import consent_version
from app.services.ai_feedback import AiFeedbackService, job_read
from app.services.artworks import summarize
from app.services.growth_ai import RULE_TEMPLATE_VERSION, pick_template
from app.services.growth_analytics import (
    ANALYSIS_VERSION,
    ArtworkFact,
    Bucket,
    Dataset,
    FeedbackFact,
    ItemFact,
    analyze,
    fingerprint,
)
from app.services.notifications import NotificationService
from app.services.practice_links import link_artwork, personal_recommendation, unlink_artwork
from app.services.tasks import TaskService

logger = logging.getLogger(__name__)

EDITABLE = (RecommendationStatus.DRAFT, RecommendationStatus.IN_REVIEW)


@dataclass(frozen=True)
class Scope:
    owner_id: uuid.UUID
    scope: GrowthScope
    academy_id: uuid.UUID | None = None
    student_membership_id: uuid.UUID | None = None
    staff: AcademyMembership | None = None  # 강사 화면이면 조회자 소속

    @property
    def key(self) -> str:
        return str(self.academy_id) if self.scope == GrowthScope.ACADEMY else self.scope.value

    def read(self) -> ScopeRead:
        return ScopeRead(
            scope=self.scope,
            academy_id=self.academy_id,
            student_membership_id=self.student_membership_id,
        )


def _sha(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def period_range(
    period: ReportPeriod, date_from: date | None, date_to: date | None
) -> tuple[date | None, date]:
    today = clock.local_today()
    if period == ReportPeriod.WEEK:
        return today - timedelta(days=6), today
    if period == ReportPeriod.MONTH:
        return today - timedelta(days=29), today
    if period == ReportPeriod.CUSTOM:
        assert date_from is not None and date_to is not None
        return date_from, date_to
    return None, today


class GrowthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.access = AccessService(session)

    # ================================================================ 범위·권한

    async def student_scope(
        self, owner: Profile, scope: GrowthScope, academy_id: uuid.UUID | None
    ) -> Scope:
        if scope != GrowthScope.ACADEMY:
            return Scope(owner.id, scope)
        if academy_id is None:
            raise UnprocessableError("academy_id is required for scope=ACADEMY")
        membership = (
            await self.session.execute(
                select(AcademyMembership)
                .where(
                    AcademyMembership.academy_id == academy_id,
                    AcademyMembership.user_id == owner.id,
                    AcademyMembership.role == MembershipRole.STUDENT,
                )
                .order_by(AcademyMembership.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if membership is None:
            raise NotFoundError("Academy not found")
        return Scope(owner.id, GrowthScope.ACADEMY, academy_id, membership.id)

    async def staff_scope(
        self, actor: AcademyMembership, student_membership_id: uuid.UUID
    ) -> Scope:
        student = await self.access.require_managed_student(actor, student_membership_id)
        return Scope(
            student.user_id, GrowthScope.ACADEMY, actor.academy_id, student.id, staff=actor
        )

    def _log_access(self, scope: Scope, what: str, target: uuid.UUID | None = None) -> None:
        logger.info(
            "growth data accessed",
            extra={
                "what": what,
                "owner_id": str(scope.owner_id),
                "viewer": f"staff:{scope.staff.id}" if scope.staff else "owner",
                "target_id": str(target) if target else None,
            },
        )

    @staticmethod
    def _feedback_visibility(scope: Scope) -> list[Any]:
        """강사 화면에는 강사 첨삭만 (자기 메모·다른 학생 의견은 학생 개인 기록)."""
        if scope.staff is not None:
            return [FeedbackSummary.source == FeedbackSource.INSTRUCTOR]
        return []

    def _artwork_filter(self, scope: Scope) -> list[Any]:
        conditions: list[Any] = [Artwork.owner_id == scope.owner_id, Artwork.deleted_at.is_(None)]
        if scope.scope == GrowthScope.PERSONAL:
            conditions.append(Artwork.academy_id.is_(None))
        elif scope.scope == GrowthScope.ACADEMY:
            conditions.append(Artwork.academy_id == scope.academy_id)
        return conditions

    # ================================================================ 데이터 적재

    async def load(
        self,
        scope: Scope,
        start: date | None = None,
        end: date | None = None,
        *,
        practical_types: Sequence[PracticalType] = (),
        work_categories: Sequence[ArtworkWorkCategory] = (),
    ) -> Dataset:
        stmt = select(Artwork).where(*self._artwork_filter(scope))
        if start is not None:
            stmt = stmt.where(Artwork.work_date >= start)
        if end is not None:
            stmt = stmt.where(Artwork.work_date <= end)
        if practical_types:
            stmt = stmt.where(Artwork.practical_type.in_(practical_types))
        if work_categories:
            stmt = stmt.where(Artwork.work_category.in_(work_categories))
        artworks = list((await self.session.execute(stmt)).scalars())
        facts = [
            ArtworkFact(
                id=a.id,
                title=a.title,
                work_date=a.work_date,
                created_at=a.created_at,
                updated_at=a.updated_at,
                work_status=a.work_status,
                completed_at=a.completed_at,
                practical_type=a.practical_type,
                work_category=a.work_category,
                actual_minutes=a.actual_minutes,
                time_limit_minutes=a.time_limit_minutes,
            )
            for a in artworks
        ]
        work_dates = {a.id: a.work_date for a in artworks}
        if not artworks:
            return Dataset(facts, [], {}, [])
        feedback_rows = (
            await self.session.execute(
                select(
                    FeedbackSummary.id,
                    FeedbackSummary.artwork_id,
                    FeedbackSummary.approved_at,
                    FeedbackSummary.version,
                    FeedbackSummary.source,
                ).where(
                    FeedbackSummary.artwork_id.in_(work_dates),
                    FeedbackSummary.status == FeedbackStatus.APPROVED,
                    *self._feedback_visibility(scope),
                )
            )
        ).all()
        feedbacks = [
            FeedbackFact(id=r[0], artwork_id=r[1], approved_at=r[2], version=r[3], source=r[4])
            for r in feedback_rows
        ]
        approved_at = {f.id: (f.artwork_id, f.approved_at) for f in feedbacks}
        categories: dict[uuid.UUID, set[WeaknessCategory]] = defaultdict(set)
        items: list[ItemFact] = []
        if feedbacks:
            for summary_id, category in (
                await self.session.execute(
                    select(FeedbackCategory.summary_id, FeedbackCategory.category).where(
                        FeedbackCategory.summary_id.in_(approved_at)
                    )
                )
            ).all():
                categories[summary_id].add(category)
            for item_id, summary_id, kind, category in (
                await self.session.execute(
                    select(
                        FeedbackItem.id,
                        FeedbackItem.summary_id,
                        FeedbackItem.kind,
                        FeedbackItem.category,
                    ).where(FeedbackItem.summary_id.in_(approved_at))
                )
            ).all():
                artwork_id, approved = approved_at[summary_id]
                items.append(
                    ItemFact(
                        id=item_id,
                        feedback_id=summary_id,
                        artwork_id=artwork_id,
                        kind=kind,
                        category=category,
                        work_date=work_dates[artwork_id],
                        approved_at=approved,
                    )
                )
        return Dataset(facts, feedbacks, dict(categories), items)

    # ================================================================ 근거 해석

    async def resolve_evidence(self, scope: Scope, item_ids: Sequence[str]) -> dict[str, Evidence]:
        """근거 항목 ID → 현재 승인된 첨삭 문장. 범위 밖·삭제·승인 취소된 항목은 빠진다."""
        ids = {uuid.UUID(i) for i in item_ids if i}
        if not ids:
            return {}
        rows = (
            await self.session.execute(
                self._evidence_query().where(
                    FeedbackItem.id.in_(ids),
                    FeedbackSummary.status == FeedbackStatus.APPROVED,
                    *self._artwork_filter(scope),
                    *self._feedback_visibility(scope),
                )
            )
        ).all()
        return {str(row[0].id): self._evidence(*row) for row in rows}

    @staticmethod
    def _evidence_query() -> Any:
        """근거 항목 + 원문 (녹음 전사 또는 텍스트 첨삭 문장)."""
        return (
            select(
                FeedbackItem,
                FeedbackSummary,
                Artwork,
                FeedbackTranscript.segments,
                FeedbackNote.segments,
            )
            .join(FeedbackSummary, FeedbackSummary.id == FeedbackItem.summary_id)
            .join(Artwork, Artwork.id == FeedbackSummary.artwork_id)
            .outerjoin(FeedbackTranscript, FeedbackTranscript.id == FeedbackSummary.transcript_id)
            .outerjoin(FeedbackNote, FeedbackNote.id == FeedbackSummary.note_id)
        )

    @staticmethod
    def _evidence(
        item: FeedbackItem,
        summary: FeedbackSummary,
        artwork: Artwork,
        transcript_segments: list[dict[str, Any]] | None,
        note_segments: list[dict[str, Any]] | None,
    ) -> Evidence:
        by_index = {s["index"]: s for s in (transcript_segments or note_segments or [])}
        first = item.evidence_segment_ids[0] if item.evidence_segment_ids else None
        return Evidence(
            item_id=item.id,
            feedback_id=summary.id,
            recording_id=summary.recording_id,
            note_id=summary.note_id,
            source=summary.source,
            artwork_id=artwork.id,
            artwork_title=artwork.title,
            work_date=artwork.work_date,
            kind=item.kind,
            category=item.category,
            content=item.content,
            start_ms=by_index.get(first, {}).get("start_ms") if first is not None else None,
            source_text=[by_index[i]["text"] for i in item.evidence_segment_ids if i in by_index],
        )

    async def _analysis_read(
        self, scope: Scope, metrics: dict[str, Any], start: date | None, end: date | None
    ) -> WeaknessAnalysis:
        ids: list[str] = []
        for w in metrics["weaknesses"]:
            ids += [e["item_id"] for e in w["evidence"]]
        for s in metrics["strengths"]:
            ids += [e["item_id"] for e in s["evidence"]]
        ids += [g["based_on_item_id"] for g in metrics["next_goals"] if g["based_on_item_id"]]
        evidence = await self.resolve_evidence(scope, ids)

        def resolve(entries: list[dict[str, Any]]) -> list[Evidence]:
            return [evidence[e["item_id"]] for e in entries if e["item_id"] in evidence]

        return WeaknessAnalysis(
            scope=scope.read(),
            period_start=start,
            period_end=end,
            status=metrics["status"],
            message=metrics["message"],
            required_artwork_count=metrics["required_artwork_count"],
            confidence=metrics["confidence"],
            recent_window=metrics["recent_window"],
            totals=metrics["totals"],
            practical_type_distribution=metrics["practical_type_distribution"],
            work_category_distribution=metrics["work_category_distribution"],
            top_weaknesses=metrics["top_weaknesses"],
            weaknesses=[w | {"evidence": resolve(w["evidence"])} for w in metrics["weaknesses"]],
            strengths=[s | {"evidence": resolve(s["evidence"])} for s in metrics["strengths"]],
            timeline_bucket=metrics["timeline_bucket"],
            timeline=metrics["timeline"],
            next_goals=[
                {
                    "category": g["category"],
                    "goal": g["goal"],
                    "based_on": evidence.get(g["based_on_item_id"] or ""),
                }
                for g in metrics["next_goals"]
            ],
            # v0.9 (이전 버전 리포트 지표에는 없을 수 있음)
            **{
                key: metrics[key]
                for key in (
                    "time_stats",
                    "activity",
                    "source_breakdown",
                    "unverified_mentions",
                    "guidance",
                )
                if key in metrics
            },
            notes=metrics["notes"],
        )

    def _analyze(
        self, dataset: Dataset, *, recent_window: int | None = None, bucket: Bucket = "month"
    ) -> dict[str, Any]:
        return analyze(
            dataset,
            min_artworks=self.settings.growth_min_artworks,
            recent_window=recent_window or self.settings.growth_recent_window,
            bucket=bucket,
        )

    # ================================================================ 약점 분석·요약·타임라인

    async def weaknesses(
        self,
        scope: Scope,
        *,
        start: date | None,
        end: date | None,
        practical_types: Sequence[PracticalType] = (),
        work_categories: Sequence[ArtworkWorkCategory] = (),
        recent_window: int | None = None,
        bucket: Bucket = "month",
    ) -> WeaknessAnalysis:
        dataset = await self.load(
            scope, start, end, practical_types=practical_types, work_categories=work_categories
        )
        metrics = self._analyze(dataset, recent_window=recent_window, bucket=bucket)
        self._log_access(scope, "weaknesses")
        return await self._analysis_read(scope, metrics, start, end)

    async def summary(self, scope: Scope, student: StudentRef | None = None) -> GrowthSummary:
        analysis = await self.weaknesses(scope, start=None, end=None)
        top = [w for w in analysis.weaknesses if w.category in analysis.top_weaknesses]
        recent_rows = (
            await self.session.execute(
                select(FeedbackSummary, Artwork)
                .join(Artwork, Artwork.id == FeedbackSummary.artwork_id)
                .where(
                    FeedbackSummary.status == FeedbackStatus.APPROVED,
                    *self._artwork_filter(scope),
                    *self._feedback_visibility(scope),
                )
                .order_by(FeedbackSummary.approved_at.desc())
                .limit(5)
            )
        ).all()
        categories = await self._categories([s.id for s, _ in recent_rows])
        report = (
            await self.session.execute(
                self._report_query(scope).order_by(GrowthReport.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        open_statuses = (
            list(EDITABLE)
            if scope.staff is not None
            else [RecommendationStatus.DISTRIBUTED, RecommendationStatus.ADOPTED, *EDITABLE]
        )
        rec_stmt = (
            select(func.count())
            .select_from(PracticeRecommendation)
            .where(
                *self._recommendation_filter(scope),
                PracticeRecommendation.status.in_(open_statuses),
            )
        )
        if scope.staff is None:
            # 학생: 학원 추천 초안은 보이지 않으므로 세지 않는다
            rec_stmt = rec_stmt.where(
                (PracticeRecommendation.scope == GrowthScope.PERSONAL)
                | (PracticeRecommendation.status == RecommendationStatus.DISTRIBUTED)
            )
        open_count = (await self.session.execute(rec_stmt)).scalar_one()
        return GrowthSummary(
            scope=scope.read(),
            student=student,
            totals=analysis.totals,
            confidence=analysis.confidence,
            status=analysis.status,
            message=analysis.message,
            top_weaknesses=top,
            recent_feedbacks=[
                RecentFeedback(
                    id=s.id,
                    source=s.source,
                    artwork_id=a.id,
                    artwork_title=a.title,
                    summary=s.summary,
                    categories=categories.get(s.id, []),
                    approved_at=s.approved_at,  # type: ignore[arg-type]
                )
                for s, a in recent_rows
            ],
            latest_report=ReportMeta(
                id=report.id,
                period_type=report.period_type,
                period_start=report.period_start,
                period_end=report.period_end,
                status=report.status,
                narrative_status=report.narrative_status,
                created_at=report.created_at,
            )
            if report
            else None,
            open_recommendation_count=open_count,
            notes=analysis.notes,
        )

    async def _categories(
        self, summary_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[WeaknessCategory]]:
        result: dict[uuid.UUID, list[WeaknessCategory]] = defaultdict(list)
        if summary_ids:
            for sid, category in (
                await self.session.execute(
                    select(FeedbackCategory.summary_id, FeedbackCategory.category).where(
                        FeedbackCategory.summary_id.in_(summary_ids)
                    )
                )
            ).all():
                result[sid].append(category)
        for sid in result:
            result[sid].sort(key=list(WeaknessCategory).index)
        return result

    async def timeline(
        self,
        scope: Scope,
        params: PaginationParams,
        *,
        start: date | None,
        end: date | None,
        practical_types: Sequence[PracticalType] = (),
        work_categories: Sequence[ArtworkWorkCategory] = (),
    ) -> tuple[list[TimelineArtwork], int]:
        stmt = select(Artwork).where(*self._artwork_filter(scope))
        if start is not None:
            stmt = stmt.where(Artwork.work_date >= start)
        if end is not None:
            stmt = stmt.where(Artwork.work_date <= end)
        if practical_types:
            stmt = stmt.where(Artwork.practical_type.in_(practical_types))
        if work_categories:
            stmt = stmt.where(Artwork.work_category.in_(work_categories))
        stmt = stmt.order_by(Artwork.work_date.desc(), Artwork.created_at.desc(), Artwork.id)
        rows, total = await fetch_page(self.session, stmt, params)
        artworks = [r[0] for r in rows]
        ids = [a.id for a in artworks]
        photos: dict[uuid.UUID, list[ArtworkPhoto]] = defaultdict(list)
        feedbacks: dict[uuid.UUID, list[FeedbackSummary]] = defaultdict(list)
        items: dict[uuid.UUID, list[FeedbackItem]] = defaultdict(list)
        tasks: dict[uuid.UUID, tuple[Task, TaskAssignment | None]] = {}
        if ids:
            for photo in (
                await self.session.execute(
                    select(ArtworkPhoto).where(
                        ArtworkPhoto.artwork_id.in_(ids), ArtworkPhoto.status == PhotoStatus.ACTIVE
                    )
                )
            ).scalars():
                photos[photo.artwork_id].append(photo)
            summaries = list(
                (
                    await self.session.execute(
                        select(FeedbackSummary)
                        .where(
                            FeedbackSummary.artwork_id.in_(ids),
                            FeedbackSummary.status == FeedbackStatus.APPROVED,
                            *self._feedback_visibility(scope),
                        )
                        .order_by(FeedbackSummary.approved_at)
                    )
                ).scalars()
            )
            for s in summaries:
                feedbacks[s.artwork_id].append(s)
            if summaries:
                for item in (
                    await self.session.execute(
                        select(FeedbackItem)
                        .where(FeedbackItem.summary_id.in_([s.id for s in summaries]))
                        .order_by(FeedbackItem.position)
                    )
                ).scalars():
                    items[item.summary_id].append(item)
            task_ids = {a.task_id for a in artworks if a.task_id}
            if task_ids:
                for task, assignment in (
                    await self.session.execute(
                        select(Task, TaskAssignment)
                        .outerjoin(
                            TaskAssignment,
                            (TaskAssignment.task_id == Task.id)
                            & (
                                TaskAssignment.student_membership_id.in_(
                                    select(AcademyMembership.id).where(
                                        AcademyMembership.user_id == scope.owner_id
                                    )
                                )
                            ),
                        )
                        .where(Task.id.in_(task_ids))
                    )
                ).all():
                    tasks[task.id] = (task, assignment)
        rec_refs: dict[uuid.UUID, list[RecommendationRef]] = defaultdict(list)
        if ids and scope.staff is None:
            for link_artwork_id, rec in (
                await self.session.execute(
                    select(PracticeRecommendationArtwork.artwork_id, PracticeRecommendation)
                    .join(
                        PracticeRecommendation,
                        PracticeRecommendation.id
                        == PracticeRecommendationArtwork.recommendation_id,
                    )
                    .where(PracticeRecommendationArtwork.artwork_id.in_(ids))
                    .order_by(PracticeRecommendationArtwork.created_at)
                )
            ).all():
                rec_refs[link_artwork_id].append(
                    RecommendationRef(
                        id=rec.id,
                        title=rec.title,
                        weakness_category=rec.weakness_category,
                        status=rec.status,
                    )
                )
        categories = await self._categories([s.id for v in feedbacks.values() for s in v])

        def texts(summary_id: uuid.UUID, kind: FeedbackItemKind) -> list[str]:
            return [i.content for i in items[summary_id] if i.kind == kind]

        result = []
        for a in artworks:
            progress = summarize(a, photos[a.id])
            cover = next(
                (
                    s.representative_photo_id
                    for s in reversed(progress.stages)
                    if s.representative_photo_id
                ),
                None,
            )
            task_pair = tasks.get(a.task_id) if a.task_id else None
            result.append(
                TimelineArtwork(
                    artwork_id=a.id,
                    title=a.title,
                    work_date=a.work_date,
                    created_at=a.created_at,
                    academy_id=a.academy_id,
                    practical_type=a.practical_type,
                    work_category=a.work_category,
                    work_status=a.work_status,
                    completed_at=a.completed_at,
                    progress=progress.progress,
                    cover_photo_id=cover,
                    stages=[
                        StageCount(
                            stage=s.stage.value,
                            photo_count=s.photo_count,
                            representative_photo_id=s.representative_photo_id,
                        )
                        for s in progress.stages
                    ],
                    feedbacks=[
                        TimelineFeedback(
                            id=s.id,
                            recording_id=s.recording_id,
                            note_id=s.note_id,
                            source=s.source,
                            summary=s.summary,
                            categories=categories.get(s.id, []),
                            strengths=texts(s.id, FeedbackItemKind.STRENGTH),
                            weaknesses=texts(s.id, FeedbackItemKind.WEAKNESS),
                            fixes=texts(s.id, FeedbackItemKind.FIX),
                            approved_at=s.approved_at,  # type: ignore[arg-type]
                        )
                        for s in feedbacks[a.id]
                    ],
                    task=TimelineTask(
                        task_id=task_pair[0].id,
                        title=task_pair[0].title,
                        completed=(task_pair[1].completed_at is not None) if task_pair[1] else None,
                    )
                    if task_pair
                    else None,
                    topic=a.topic,
                    work_method=a.work_method,
                    actual_minutes=a.actual_minutes,
                    time_limit_minutes=a.time_limit_minutes,
                    recommendations=rec_refs.get(a.id, []),
                )
            )
        self._log_access(scope, "timeline")
        return result, total

    async def staff_students(
        self, actor: AcademyMembership, params: PaginationParams
    ) -> tuple[list[StudentGrowthRow], int]:
        """담당 학생 성장 현황 (학원 연결 작품 기준)."""
        stmt = (
            select(AcademyMembership, Profile)
            .join(Profile, Profile.id == AcademyMembership.user_id)
            .where(AcademyMembership.id.in_(managed_student_ids(actor)))
            .order_by(Profile.display_name, AcademyMembership.id)
        )
        rows, total = await fetch_page(self.session, stmt, params)
        result = []
        for membership, profile in rows:
            scope = Scope(
                profile.id, GrowthScope.ACADEMY, actor.academy_id, membership.id, staff=actor
            )
            metrics = self._analyze(await self.load(scope))
            last = (
                await self.session.execute(
                    select(func.max(FeedbackSummary.approved_at))
                    .join(Artwork, Artwork.id == FeedbackSummary.artwork_id)
                    .where(
                        FeedbackSummary.status == FeedbackStatus.APPROVED,
                        *self._artwork_filter(scope),
                        *self._feedback_visibility(scope),
                    )
                )
            ).scalar_one()
            pending = (
                await self.session.execute(
                    select(func.count())
                    .select_from(PracticeRecommendation)
                    .where(
                        *self._recommendation_filter(scope),
                        PracticeRecommendation.status.in_(EDITABLE),
                    )
                )
            ).scalar_one()
            result.append(
                StudentGrowthRow(
                    student=student_ref(membership, profile),
                    analyzed_artwork_count=metrics["totals"]["analyzed_artwork_count"],
                    top_weaknesses=metrics["top_weaknesses"],
                    last_feedback_at=last,
                    pending_recommendation_count=pending,
                )
            )
        return result, total

    async def student_ref_for(self, scope: Scope) -> StudentRef | None:
        if scope.student_membership_id is None or scope.staff is None:
            return None
        m, p = (
            await self.session.execute(
                select(AcademyMembership, Profile)
                .join(Profile, Profile.id == AcademyMembership.user_id)
                .where(AcademyMembership.id == scope.student_membership_id)
            )
        ).one()
        return student_ref(m, p)

    # ================================================================ 성장 리포트

    def _report_query(self, scope: Scope):  # type: ignore[no-untyped-def]
        stmt = select(GrowthReport).where(GrowthReport.owner_id == scope.owner_id)
        if scope.staff is not None:
            stmt = stmt.where(
                GrowthReport.scope == GrowthScope.ACADEMY,
                GrowthReport.academy_id == scope.academy_id,
            )
        return stmt

    async def create_report(
        self, scope: Scope, data: ReportCreate, requester: Profile, *, regenerate: bool = False
    ) -> tuple[ReportRead, bool]:
        start, end = period_range(data.period, data.date_from, data.date_to)
        dataset = await self.load(scope, start, end)
        metrics = self._analyze(dataset)
        fp = fingerprint(dataset)
        dedupe = _sha(scope.key, data.period.value, start, end, fp, ANALYSIS_VERSION)
        existing = (
            await self.session.execute(
                select(GrowthReport)
                .where(GrowthReport.owner_id == scope.owner_id, GrowthReport.dedupe_key == dedupe)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if existing is not None:
            # 같은 데이터 → 같은 리포트. 설명문만 다시 요청할 수 있다 (실패·건너뜀·무효화된 경우)
            if (data.include_ai_narrative or regenerate) and existing.narrative_status in (
                NarrativeStatus.NOT_REQUESTED,
                NarrativeStatus.FAILED,
                NarrativeStatus.SKIPPED,
                NarrativeStatus.INVALIDATED,
            ):
                await self._request_narrative(existing, requester)
            await self.session.commit()
            return await self.report_read(scope, existing), False

        report = GrowthReport(
            id=uuid.uuid4(),
            owner_id=scope.owner_id,
            scope=scope.scope,
            academy_id=scope.academy_id,
            period_type=data.period,
            period_start=start,
            period_end=end,
            status=ReportStatus(metrics["status"]),
            metrics=metrics,
            source_feedback_ids=[str(f.id) for f in dataset.feedbacks],
            data_fingerprint=fp,
            dedupe_key=dedupe,
            analysis_version=ANALYSIS_VERSION,
            narrative_status=NarrativeStatus.NOT_REQUESTED,
            generated_by=requester.id,
        )
        self.session.add(report)
        await self.session.flush()
        if data.include_ai_narrative:
            await self._request_narrative(report, requester)
        # v0.9 F-9: 학생에게 새 리포트 알림 (강사가 만들어도 학생에게)
        await NotificationService(self.session).report_ready(scope.owner_id, report.id)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = (
                await self.session.execute(
                    select(GrowthReport).where(
                        GrowthReport.owner_id == scope.owner_id, GrowthReport.dedupe_key == dedupe
                    )
                )
            ).scalar_one()
            return await self.report_read(scope, existing), False
        await self.session.refresh(report)
        return await self.report_read(scope, report), True

    async def _request_narrative(self, report: GrowthReport, requester: Profile) -> None:
        """AI 설명문 작업 등록.

        조건이 안 맞으면 SKIPPED + 사유 코드 (요청 자체는 실패시키지 않음).
        """
        if report.status == ReportStatus.INSUFFICIENT_DATA:
            code = "INSUFFICIENT_DATA"
        elif not self.settings.growth_ai_enabled:
            code = "GROWTH_AI_NOT_CONFIGURED"
        elif not await AiFeedbackService(self.session, self.settings).has_valid_ai_consent(
            report.owner_id, AiConsentPurpose.GROWTH_COACHING
        ):
            code = "AI_CONSENT_REQUIRED"
        else:
            code = None
        if code is not None:
            report.narrative_status = NarrativeStatus.SKIPPED
            report.narrative_error_code = code
            return
        report.narrative_status = NarrativeStatus.PENDING
        report.narrative_error_code = None
        report.narrative = None
        active = (
            await self.session.execute(
                select(AiProcessingJob.id).where(
                    AiProcessingJob.report_id == report.id,
                    AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                )
            )
        ).first()
        if active is None:
            self.session.add(
                AiProcessingJob(
                    id=uuid.uuid4(),
                    job_type=AiJobType.GROWTH_REPORT,
                    status=AiJobStatus.QUEUED,
                    owner_id=report.owner_id,
                    report_id=report.id,
                    dedupe_key=f"report:{report.id}",
                    requested_by=requester.id,
                    attempts=0,
                    max_attempts=self.settings.job_max_attempts,
                    run_after=clock.utc_now(),
                    params={},
                )
            )

    async def report_read(self, scope: Scope, report: GrowthReport) -> ReportRead:
        report_scope = Scope(
            report.owner_id,
            report.scope,
            report.academy_id,
            scope.student_membership_id,
            staff=scope.staff,
        )
        statistics = await self._analysis_read(
            report_scope, report.metrics, report.period_start, report.period_end
        )
        current = await self.load(report_scope, report.period_start, report.period_end)
        narrative = None
        if report.narrative_status == NarrativeStatus.READY and report.narrative:
            evidence = await self.resolve_evidence(
                report_scope,
                [
                    i
                    for g in report.narrative.get("next_goals", [])
                    for i in g.get("evidence_item_ids", [])
                ],
            )
            narrative = {
                "overview": report.narrative["overview"],
                "strengths_comment": report.narrative["strengths_comment"],
                "improvement_comment": report.narrative["improvement_comment"],
                "next_goals": [
                    {
                        "goal": g["goal"],
                        "evidence": [
                            evidence[i].model_dump(mode="json")
                            for i in g.get("evidence_item_ids", [])
                            if i in evidence
                        ],
                    }
                    for g in report.narrative.get("next_goals", [])
                ],
            }
        generated_by = (
            (
                await self.session.execute(
                    select(Profile.display_name).where(Profile.id == report.generated_by)
                )
            ).scalar_one_or_none()
            if report.generated_by
            else None
        )
        self._log_access(scope, "report", report.id)
        return ReportRead(
            id=report.id,
            scope=report_scope.read(),
            period_type=report.period_type,
            period_start=report.period_start,
            period_end=report.period_end,
            status=report.status,
            message=report.metrics.get("message"),
            statistics=statistics,
            ai_narrative=NarrativeRead(
                status=report.narrative_status,
                content=narrative,  # type: ignore[arg-type]
                error_code=report.narrative_error_code,
                model_name=report.model_name,
                prompt_version=report.prompt_version,
            ),
            is_stale=fingerprint(current) != report.data_fingerprint,
            analysis_version=report.analysis_version,
            source_feedback_count=len(report.source_feedback_ids),
            generated_by_name=generated_by,
            created_at=report.created_at,
        )

    async def list_reports(
        self, scope: Scope, params: PaginationParams, scope_filter: GrowthScope | None = None
    ) -> tuple[list[ReportListItem], int]:
        stmt = self._report_query(scope)
        if scope_filter is not None:
            stmt = stmt.where(GrowthReport.scope == scope_filter)
        rows, total = await fetch_page(
            self.session, stmt.order_by(GrowthReport.created_at.desc(), GrowthReport.id), params
        )
        return [
            ReportListItem(
                id=r.id,
                period_type=r.period_type,
                period_start=r.period_start,
                period_end=r.period_end,
                status=r.status,
                narrative_status=r.narrative_status,
                created_at=r.created_at,
                scope=ScopeRead(scope=r.scope, academy_id=r.academy_id, student_membership_id=None),
            )
            for (r,) in rows
        ], total

    async def get_report(self, scope: Scope, report_id: uuid.UUID) -> GrowthReport:
        report = (
            await self.session.execute(
                self._report_query(scope).where(GrowthReport.id == report_id)
            )
        ).scalar_one_or_none()
        if report is None:
            raise NotFoundError("Report not found")
        return report

    async def staff_report_scope(
        self, actor: AcademyMembership, report_id: uuid.UUID
    ) -> tuple[Scope, GrowthReport]:
        """강사: 자기 학원 범위 리포트만, 담당 학생 것만 (아니면 404/403)."""
        report = (
            await self.session.execute(
                select(GrowthReport).where(
                    GrowthReport.id == report_id,
                    GrowthReport.scope == GrowthScope.ACADEMY,
                    GrowthReport.academy_id == actor.academy_id,
                )
            )
        ).scalar_one_or_none()
        membership_id = (
            (
                await self.session.execute(
                    select(AcademyMembership.id)
                    .where(
                        AcademyMembership.academy_id == actor.academy_id,
                        AcademyMembership.user_id == report.owner_id,
                        AcademyMembership.role == MembershipRole.STUDENT,
                    )
                    .order_by(AcademyMembership.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if report
            else None
        )
        if report is None or membership_id is None:
            raise NotFoundError("Report not found")
        if not await self.access.is_managed_student(actor, membership_id):
            raise ForbiddenError("This student is not in your classes")
        return (
            Scope(report.owner_id, GrowthScope.ACADEMY, actor.academy_id, membership_id, actor),
            report,
        )

    async def regenerate_report(
        self, scope: Scope, report_id: uuid.UUID, requester: Profile, include_ai: bool
    ) -> tuple[ReportRead, bool]:
        report = await self.get_report(scope, report_id)
        target = scope
        if report.scope != scope.scope or report.academy_id != scope.academy_id:
            target = Scope(
                scope.owner_id,
                report.scope,
                report.academy_id,
                scope.student_membership_id,
                scope.staff,
            )
        data = ReportCreate.model_validate(
            {
                "period": report.period_type,
                "from": report.period_start if report.period_type == ReportPeriod.CUSTOM else None,
                "to": report.period_end if report.period_type == ReportPeriod.CUSTOM else None,
                "scope": report.scope,
                "academy_id": report.academy_id,
                "include_ai_narrative": include_ai,
            }
        )
        return await self.create_report(target, data, requester, regenerate=True)

    # ================================================================ 추천 과제: 생성

    def _recommendation_filter(self, scope: Scope) -> list[Any]:
        conditions: list[Any] = [PracticeRecommendation.owner_id == scope.owner_id]
        if scope.scope == GrowthScope.ACADEMY:
            conditions.append(PracticeRecommendation.academy_id == scope.academy_id)
        elif scope.scope == GrowthScope.PERSONAL:
            conditions.append(PracticeRecommendation.scope == GrowthScope.PERSONAL)
        return conditions

    async def recommendation_basis(self, scope: Scope) -> tuple[Dataset, dict[str, Any], str]:
        """추천에 쓰는 데이터: 범위 안의 전체 기간 승인 첨삭 (최근 구간 비교 포함)."""
        dataset = await self.load(scope)
        metrics = self._analyze(dataset)
        return dataset, metrics, fingerprint(dataset)

    def _check_recommendable(self, metrics: dict[str, Any]) -> list[str]:
        if metrics["status"] == ReportStatus.INSUFFICIENT_DATA.value:
            raise ConflictError(
                "Not enough approved feedback to recommend practice",
                code=ErrorCode.INSUFFICIENT_DATA,
                details={
                    "reason": "NOT_ENOUGH_ARTWORKS",
                    "analyzed_artwork_count": metrics["totals"]["analyzed_artwork_count"],
                    "required_artwork_count": metrics["required_artwork_count"],
                },
            )
        categories = metrics["top_weaknesses"][: self.settings.growth_max_recommendations]
        if not categories:
            raise ConflictError(
                "No repeated weakness was found in approved feedback",
                code=ErrorCode.INSUFFICIENT_DATA,
                details={"reason": "NO_REPEATED_WEAKNESS"},
            )
        return categories

    async def generate_recommendations(
        self, scope: Scope, data: RecommendationGenerate, requester: Profile
    ) -> GenerationResult:
        _, metrics, fp = await self.recommendation_basis(scope)
        categories = self._check_recommendable(metrics)
        source = RecommendationSource.AI if data.use_ai else RecommendationSource.RULE
        batch_key = _sha(scope.key, source.value, fp, ANALYSIS_VERSION)
        existing = await self._batch(scope, batch_key)
        if existing:
            return GenerationResult(
                status="EXISTING",
                recommendations=[await self.reviewer_read(scope, r) for r in existing],
                job=None,
            )
        if data.use_ai:
            return await self._queue_ai(scope, requester, batch_key)
        try:
            recs = await self.create_rule_recommendations(
                scope, metrics, categories, batch_key, requester.id
            )
            if scope.scope == GrowthScope.PERSONAL:
                # 학원 추천은 강사 검토 후 배포될 때 알린다
                await NotificationService(self.session).tasks_recommended(
                    scope.owner_id, recs, f"recs:{batch_key}"
                )
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            recs = await self._batch(scope, batch_key)
            return GenerationResult(
                status="EXISTING",
                recommendations=[await self.reviewer_read(scope, r) for r in recs],
                job=None,
            )
        return GenerationResult(
            status="CREATED",
            recommendations=[await self.reviewer_read(scope, r) for r in recs],
            job=None,
        )

    async def _batch(self, scope: Scope, batch_key: str) -> list[PracticeRecommendation]:
        return list(
            (
                await self.session.execute(
                    select(PracticeRecommendation)
                    .where(
                        PracticeRecommendation.owner_id == scope.owner_id,
                        PracticeRecommendation.batch_key == batch_key,
                        PracticeRecommendation.status.notin_(
                            [RecommendationStatus.REJECTED, RecommendationStatus.SUPERSEDED]
                        ),
                    )
                    .order_by(PracticeRecommendation.created_at, PracticeRecommendation.id)
                )
            ).scalars()
        )

    async def _queue_ai(self, scope: Scope, requester: Profile, batch_key: str) -> GenerationResult:
        if not self.settings.growth_ai_enabled:
            raise ServiceUnavailableError(
                "AI growth coaching is not enabled", code=ErrorCode.GROWTH_AI_NOT_CONFIGURED
            )
        if not await AiFeedbackService(self.session, self.settings).has_valid_ai_consent(
            scope.owner_id, AiConsentPurpose.GROWTH_COACHING
        ):
            raise ConflictError(
                "The student's consent to AI growth coaching is required",
                code=ErrorCode.AI_CONSENT_REQUIRED,
                details={
                    "purpose": AiConsentPurpose.GROWTH_COACHING.value,
                    "required_version": consent_version(
                        self.settings, AiConsentPurpose.GROWTH_COACHING
                    ),
                },
            )
        dedupe = f"rec:{scope.owner_id}:{batch_key}"[:100]
        job = (
            await self.session.execute(
                select(AiProcessingJob).where(
                    AiProcessingJob.job_type == AiJobType.PRACTICE_RECOMMEND,
                    AiProcessingJob.dedupe_key == dedupe,
                    AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                )
            )
        ).scalar_one_or_none()
        if job is None:
            job = AiProcessingJob(
                id=uuid.uuid4(),
                job_type=AiJobType.PRACTICE_RECOMMEND,
                status=AiJobStatus.QUEUED,
                owner_id=scope.owner_id,
                dedupe_key=dedupe,
                requested_by=requester.id,
                attempts=0,
                max_attempts=self.settings.job_max_attempts,
                run_after=clock.utc_now(),
                params={
                    "scope": scope.scope.value,
                    "academy_id": str(scope.academy_id) if scope.academy_id else None,
                    "student_membership_id": str(scope.student_membership_id)
                    if scope.student_membership_id
                    else None,
                    "batch_key": batch_key,
                },
            )
            self.session.add(job)
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                job = (
                    await self.session.execute(
                        select(AiProcessingJob).where(
                            AiProcessingJob.dedupe_key == dedupe,
                            AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                        )
                    )
                ).scalar_one()
            await self.session.refresh(job)
        return GenerationResult(status="QUEUED", recommendations=[], job=job_read(job))

    async def supersede_open(
        self, scope: Scope, keep_batch: str, actor_id: uuid.UUID | None
    ) -> None:
        """새 추천을 만들면 같은 범위의 검토 전 추천(DRAFT/IN_REVIEW)은 대체 처리."""
        old = list(
            (
                await self.session.execute(
                    select(PracticeRecommendation)
                    .where(
                        *self._recommendation_filter(scope),
                        PracticeRecommendation.scope == scope.scope,
                        PracticeRecommendation.status.in_(EDITABLE),
                        PracticeRecommendation.batch_key != keep_batch,
                    )
                    .with_for_update()
                )
            ).scalars()
        )
        for rec in old:
            from_status = rec.status
            rec.status = RecommendationStatus.SUPERSEDED
            rec.version += 1
            self._history(rec, actor_id, None, RecommendationAction.SUPERSEDED, from_status)

    async def create_rule_recommendations(
        self,
        scope: Scope,
        metrics: dict[str, Any],
        categories: list[str],
        batch_key: str,
        actor_id: uuid.UUID | None,
    ) -> list[PracticeRecommendation]:
        await self.supersede_open(scope, batch_key, actor_id)
        practical = self._main_practical_type(metrics)
        by_category = {w["category"]: w for w in metrics["weaknesses"]}
        recs = []
        for code in categories:
            category = WeaknessCategory(code)
            stat = by_category[code]
            template = pick_template(category, practical)
            evidence = stat["evidence"]
            reason = (
                f"승인된 첨삭이 있는 작품 {metrics['totals']['analyzed_artwork_count']}개 중 "
                f"{stat['artwork_count']}개에서 '{WEAKNESS_CATEGORY_LABELS[category]}'이(가) "
                "지적되었습니다."
            )
            origin = {
                "source": RecommendationSource.RULE.value,
                "template_version": RULE_TEMPLATE_VERSION,
                "title": template.title,
                "description": template.description,
                "steps": list(template.steps),
                "estimated_minutes": template.minutes,
                "difficulty": template.difficulty.value,
                "reason": reason,
            }
            recs.append(
                self._new_recommendation(
                    scope,
                    RecommendationSource.RULE,
                    batch_key,
                    category,
                    practical,
                    title=template.title,
                    description=template.description,
                    steps=list(template.steps),
                    minutes=template.minutes,
                    difficulty=template.difficulty,
                    reason=reason,
                    origin=origin,
                    evidence=evidence,
                    metrics=metrics,
                    stat=stat,
                    actor_id=actor_id,
                    model_name=None,
                    prompt_version=RULE_TEMPLATE_VERSION,
                )
            )
        await self.session.flush()
        return recs

    @staticmethod
    def _main_practical_type(metrics: dict[str, Any]) -> PracticalType | None:
        for entry in metrics["practical_type_distribution"]:
            if entry["practical_type"]:
                return PracticalType(entry["practical_type"])
        return None

    def _new_recommendation(
        self,
        scope: Scope,
        source: RecommendationSource,
        batch_key: str,
        category: WeaknessCategory,
        practical: PracticalType | None,
        *,
        title: str,
        description: str,
        steps: list[str],
        minutes: int,
        difficulty: Any,
        reason: str,
        origin: dict[str, Any],
        evidence: list[dict[str, Any]],
        metrics: dict[str, Any],
        stat: dict[str, Any],
        actor_id: uuid.UUID | None,
        model_name: str | None,
        prompt_version: str | None,
    ) -> PracticeRecommendation:
        rec = PracticeRecommendation(
            id=uuid.uuid4(),
            owner_id=scope.owner_id,
            scope=scope.scope,
            academy_id=scope.academy_id,
            student_membership_id=scope.student_membership_id,
            review_mode=ReviewMode.INSTRUCTOR
            if scope.scope == GrowthScope.ACADEMY
            else ReviewMode.SELF,
            source=source,
            status=RecommendationStatus.DRAFT,
            version=1,
            batch_key=batch_key,
            weakness_category=category,
            practical_type=practical,
            title=title,
            description=description,
            method_steps=steps,
            estimated_minutes=minutes,
            difficulty=difficulty,
            reason=reason,
            origin_output=origin,
            evidence_item_ids=[e["item_id"] for e in evidence],
            evidence_feedback_ids=sorted({e["feedback_id"] for e in evidence}),
            evidence_artwork_ids=sorted({e["artwork_id"] for e in evidence}),
            analysis_snapshot={
                "analysis_version": ANALYSIS_VERSION,
                "period": "ALL",
                "analyzed_artwork_count": metrics["totals"]["analyzed_artwork_count"],
                "artwork_count": stat["artwork_count"],
                "recent": stat["recent"],
                "trend": stat["trend"],
                "practical_types": [
                    d["practical_type"] for d in metrics["practical_type_distribution"]
                ],
                "work_categories": [
                    d["work_category"] for d in metrics["work_category_distribution"]
                ],
                "recent_artwork_ids": metrics["analyzed_artwork_ids"][-metrics["recent_window"] :],
            },
            model_name=model_name,
            prompt_version=prompt_version,
            created_by=actor_id,
            learning_goal=(
                f"다음 작품에서 '{WEAKNESS_CATEGORY_LABELS[category]}'을(를) 의식적으로 점검하며 "
                "지적이 반복되는지 확인하기"
            ),
        )
        self.session.add(rec)
        self._history(rec, actor_id, None, RecommendationAction.CREATED, None, note=source.value)
        return rec

    # ================================================================ 추천 과제: 조회

    def _history(
        self,
        rec: PracticeRecommendation,
        actor_id: uuid.UUID | None,
        mode: ReviewMode | None,
        action: RecommendationAction,
        from_status: RecommendationStatus | None,
        *,
        changes: dict[str, Any] | None = None,
        note: str | None = None,
    ) -> None:
        self.session.add(
            PracticeRecommendationHistory(
                id=uuid.uuid4(),
                recommendation_id=rec.id,
                actor_id=actor_id,
                actor_mode=mode,
                action=action,
                from_status=from_status,
                to_status=rec.status,
                version=rec.version,
                changes=changes,
                note=note,
            )
        )

    async def _read_dict(self, scope: Scope, rec: PracticeRecommendation) -> dict[str, Any]:
        rec_scope = Scope(
            rec.owner_id, rec.scope, rec.academy_id, rec.student_membership_id, scope.staff
        )
        evidence = await self.resolve_evidence(rec_scope, rec.evidence_item_ids)
        task = None
        if rec.task_id is not None:
            row = (
                await self.session.execute(
                    select(Task, TaskAssignment)
                    .outerjoin(
                        TaskAssignment,
                        (TaskAssignment.task_id == Task.id)
                        & (TaskAssignment.student_membership_id == rec.student_membership_id),
                    )
                    .where(Task.id == rec.task_id)
                )
            ).one_or_none()
            if row is not None:
                t, a = row
                task = TaskLink(
                    task_id=t.id,
                    title=t.title,
                    due_at=t.due_at,
                    completed=(a.completed_at is not None) if a else None,
                    completed_at=a.completed_at if a else None,
                )
        approver = (
            (
                await self.session.execute(
                    select(Profile.display_name).where(Profile.id == rec.approved_by)
                )
            ).scalar_one_or_none()
            if rec.approved_by
            else None
        )
        return {
            "id": rec.id,
            "scope": rec_scope.read(),
            "review_mode": rec.review_mode,
            "source": rec.source,
            "status": rec.status,
            "version": rec.version,
            "weakness_category": rec.weakness_category,
            "practical_type": rec.practical_type,
            "title": rec.title,
            "description": rec.description,
            "method_steps": rec.method_steps,
            "estimated_minutes": rec.estimated_minutes,
            "difficulty": rec.difficulty,
            "reason": rec.reason,
            "evidence": [evidence[i] for i in rec.evidence_item_ids if i in evidence],
            "analysis": rec.analysis_snapshot,
            "task": task,
            "learning_goal": rec.learning_goal,
            "started_at": rec.started_at,
            "linked_artwork_ids": list(
                (
                    await self.session.execute(
                        select(PracticeRecommendationArtwork.artwork_id)
                        .join(Artwork, Artwork.id == PracticeRecommendationArtwork.artwork_id)
                        .where(
                            PracticeRecommendationArtwork.recommendation_id == rec.id,
                            Artwork.deleted_at.is_(None),
                        )
                        .order_by(PracticeRecommendationArtwork.created_at)
                    )
                ).scalars()
            )
            if rec.scope == GrowthScope.PERSONAL
            else [],
            "completed_at": rec.completed_at,
            "approved_at": rec.approved_at,
            "approved_by_name": approver,
            "rejected_reason": rec.rejected_reason,
            "created_at": rec.created_at,
            "updated_at": rec.updated_at,
        }

    async def reviewer_read(
        self, scope: Scope, rec: PracticeRecommendation
    ) -> ReviewerRecommendationRead:
        student = None
        if scope.staff is not None and rec.student_membership_id is not None:
            student = await self.student_ref_for(
                Scope(
                    rec.owner_id, rec.scope, rec.academy_id, rec.student_membership_id, scope.staff
                )
            )
        return ReviewerRecommendationRead(
            **await self._read_dict(scope, rec),
            origin=rec.origin_output,
            model_name=rec.model_name,
            prompt_version=rec.prompt_version,
            student=student,
        )

    def _student_visible(self) -> Any:
        """학생에게 보이는 추천: 개인 추천 전부(대체 제외), 학원 추천은 배포된 것만."""
        return (
            (PracticeRecommendation.scope == GrowthScope.PERSONAL)
            & (PracticeRecommendation.status != RecommendationStatus.SUPERSEDED)
        ) | (PracticeRecommendation.status == RecommendationStatus.DISTRIBUTED)

    async def list_recommendations(
        self,
        scope: Scope,
        params: PaginationParams,
        statuses: Sequence[RecommendationStatus],
        student_membership_id: uuid.UUID | None = None,
    ) -> tuple[list[ReviewerRecommendationRead | RecommendationRead], int]:
        if scope.staff is not None:
            actor = scope.staff
            stmt = select(PracticeRecommendation).where(
                PracticeRecommendation.academy_id == actor.academy_id,
                PracticeRecommendation.student_membership_id.in_(managed_student_ids(actor)),
            )
            if student_membership_id is not None:
                await self.access.require_managed_student(actor, student_membership_id)
                stmt = stmt.where(
                    PracticeRecommendation.student_membership_id == student_membership_id
                )
        else:
            stmt = select(PracticeRecommendation).where(
                *self._recommendation_filter(scope), self._student_visible()
            )
        if statuses:
            stmt = stmt.where(PracticeRecommendation.status.in_(statuses))
        stmt = stmt.order_by(PracticeRecommendation.created_at.desc(), PracticeRecommendation.id)
        rows, total = await fetch_page(self.session, stmt, params)
        items: list[ReviewerRecommendationRead | RecommendationRead] = []
        for (rec,) in rows:
            if scope.staff is not None or rec.review_mode == ReviewMode.SELF:
                items.append(await self.reviewer_read(scope, rec))
            else:
                items.append(RecommendationRead(**await self._read_dict(scope, rec)))
        return items, total

    async def _owned_rec(
        self, owner: Profile, rec_id: uuid.UUID, *, for_update: bool = False
    ) -> PracticeRecommendation:
        stmt = select(PracticeRecommendation).where(
            PracticeRecommendation.id == rec_id,
            PracticeRecommendation.owner_id == owner.id,
            self._student_visible(),
        )
        if for_update:
            stmt = stmt.with_for_update()
        rec = (await self.session.execute(stmt)).scalar_one_or_none()
        if rec is None:
            raise NotFoundError("Recommendation not found")
        return rec

    async def _staff_rec(
        self, actor: AcademyMembership, rec_id: uuid.UUID, *, for_update: bool = False
    ) -> PracticeRecommendation:
        stmt = select(PracticeRecommendation).where(
            PracticeRecommendation.id == rec_id,
            PracticeRecommendation.academy_id == actor.academy_id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        rec = (await self.session.execute(stmt)).scalar_one_or_none()
        if rec is None or rec.student_membership_id is None:
            raise NotFoundError("Recommendation not found")
        if not await self.access.is_managed_student(actor, rec.student_membership_id):
            raise ForbiddenError("This student is not in your classes")
        return rec

    async def owner_view(self, owner: Profile, rec_id: uuid.UUID) -> RecommendationRead:
        rec = await self._owned_rec(owner, rec_id)
        scope = Scope(owner.id, rec.scope, rec.academy_id, rec.student_membership_id)
        if rec.review_mode == ReviewMode.SELF:
            return await self.reviewer_read(scope, rec)
        return RecommendationRead(**await self._read_dict(scope, rec))

    async def staff_view(
        self, actor: AcademyMembership, rec_id: uuid.UUID
    ) -> ReviewerRecommendationRead:
        rec = await self._staff_rec(actor, rec_id)
        scope = Scope(
            rec.owner_id, rec.scope, rec.academy_id, rec.student_membership_id, staff=actor
        )
        return await self.reviewer_read(scope, rec)

    async def history(self, rec: PracticeRecommendation) -> list[RecommendationHistoryRead]:
        rows = (
            await self.session.execute(
                select(PracticeRecommendationHistory, Profile.display_name)
                .outerjoin(Profile, Profile.id == PracticeRecommendationHistory.actor_id)
                .where(PracticeRecommendationHistory.recommendation_id == rec.id)
                .order_by(
                    PracticeRecommendationHistory.created_at, PracticeRecommendationHistory.id
                )
            )
        ).all()
        return [
            RecommendationHistoryRead(
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
        self, owner: Profile, rec_id: uuid.UUID
    ) -> list[RecommendationHistoryRead]:
        rec = await self._owned_rec(owner, rec_id)
        if rec.review_mode != ReviewMode.SELF:
            raise ForbiddenError("Your instructor reviews academy recommendations")
        return await self.history(rec)

    async def staff_history(
        self, actor: AcademyMembership, rec_id: uuid.UUID
    ) -> list[RecommendationHistoryRead]:
        return await self.history(await self._staff_rec(actor, rec_id))

    # ================================================================ 추천 과제: 검토 동작

    @staticmethod
    def _check(
        rec: PracticeRecommendation, version: int, allowed: Sequence[RecommendationStatus]
    ) -> None:
        if rec.status not in allowed:
            raise ConflictError(
                f"Not allowed while the recommendation is {rec.status.value}",
                code=ErrorCode.RECOMMENDATION_INVALID_STATE,
                details={"status": rec.status.value},
            )
        if rec.version != version:
            raise ConflictError(
                "The recommendation was changed by someone else; reload it",
                code=ErrorCode.RECOMMENDATION_VERSION_CONFLICT,
                details={"current_version": rec.version},
            )

    async def _locked(
        self,
        profile: Profile,
        rec_id: uuid.UUID,
        actor: AcademyMembership | None,
        *,
        self_only: bool,
    ) -> tuple[PracticeRecommendation, ReviewMode]:
        if actor is not None:
            return await self._staff_rec(actor, rec_id, for_update=True), ReviewMode.INSTRUCTOR
        rec = await self._owned_rec(profile, rec_id, for_update=True)
        if self_only and rec.review_mode != ReviewMode.SELF:
            raise ForbiddenError("Your instructor reviews academy recommendations")
        return rec, ReviewMode.SELF

    async def _reload(
        self, rec: PracticeRecommendation, actor: AcademyMembership | None
    ) -> ReviewerRecommendationRead | RecommendationRead:
        await self.session.commit()
        await self.session.refresh(rec)
        scope = Scope(rec.owner_id, rec.scope, rec.academy_id, rec.student_membership_id, actor)
        if actor is None and rec.review_mode == ReviewMode.INSTRUCTOR:
            return RecommendationRead(**await self._read_dict(scope, rec))
        return await self.reviewer_read(scope, rec)

    @staticmethod
    def _snapshot(rec: PracticeRecommendation) -> dict[str, Any]:
        return {
            "title": rec.title,
            "description": rec.description,
            "method_steps": list(rec.method_steps),
            "estimated_minutes": rec.estimated_minutes,
            "difficulty": rec.difficulty.value,
            "practical_type": rec.practical_type.value if rec.practical_type else None,
        }

    async def update(
        self,
        profile: Profile,
        rec_id: uuid.UUID,
        data: RecommendationUpdate,
        actor: AcademyMembership | None = None,
    ) -> ReviewerRecommendationRead | RecommendationRead:
        rec, mode = await self._locked(profile, rec_id, actor, self_only=True)
        self._check(rec, data.version, EDITABLE)
        changes = data.model_dump(exclude_unset=True, exclude={"version", "note"})
        if not changes:
            raise UnprocessableError("Nothing to update")
        if "practical_type" not in changes:
            changes.pop("practical_type", None)
        before = self._snapshot(rec)
        for field, value in changes.items():
            if value is None and field != "practical_type":
                raise UnprocessableError(f"'{field}' cannot be null")
            setattr(rec, field, value)
        from_status = rec.status
        rec.status = RecommendationStatus.IN_REVIEW
        rec.version += 1
        self._history(
            rec,
            profile.id,
            mode,
            RecommendationAction.EDITED,
            from_status,
            changes={"before": before, "after": self._snapshot(rec)},
            note=data.note,
        )
        return await self._reload(rec, actor)

    async def approve(
        self,
        profile: Profile,
        rec_id: uuid.UUID,
        data: RecommendationDecision,
        actor: AcademyMembership,
    ) -> ReviewerRecommendationRead | RecommendationRead:
        rec, mode = await self._locked(profile, rec_id, actor, self_only=False)
        self._check(rec, data.version, EDITABLE)
        from_status = rec.status
        rec.status = RecommendationStatus.APPROVED
        rec.approved_by = profile.id
        rec.approved_at = clock.utc_now()
        rec.version += 1
        self._history(
            rec,
            profile.id,
            mode,
            RecommendationAction.APPROVED,
            from_status,
            changes={"approved": self._snapshot(rec)},
            note=data.note,
        )
        return await self._reload(rec, actor)

    async def reject(
        self,
        profile: Profile,
        rec_id: uuid.UUID,
        data: RecommendationReject,
        actor: AcademyMembership | None = None,
    ) -> ReviewerRecommendationRead | RecommendationRead:
        rec, mode = await self._locked(profile, rec_id, actor, self_only=True)
        allowed = (*EDITABLE, RecommendationStatus.APPROVED) if actor else EDITABLE
        self._check(rec, data.version, allowed)
        from_status = rec.status
        rec.status = RecommendationStatus.REJECTED
        rec.rejected_reason = data.reason
        rec.version += 1
        self._history(
            rec, profile.id, mode, RecommendationAction.REJECTED, from_status, note=data.reason
        )
        return await self._reload(rec, actor)

    async def adopt(
        self, owner: Profile, rec_id: uuid.UUID, data: RecommendationDecision
    ) -> ReviewerRecommendationRead | RecommendationRead:
        rec, mode = await self._locked(owner, rec_id, None, self_only=True)
        self._check(rec, data.version, EDITABLE)
        from_status = rec.status
        rec.status = RecommendationStatus.ADOPTED
        rec.approved_by = owner.id
        rec.approved_at = clock.utc_now()
        rec.version += 1
        self._history(
            rec,
            owner.id,
            mode,
            RecommendationAction.ADOPTED,
            from_status,
            changes={"adopted": self._snapshot(rec)},
            note=data.note,
        )
        return await self._reload(rec, None)

    async def set_completion(
        self, owner: Profile, rec_id: uuid.UUID, data: RecommendationCompletion
    ) -> ReviewerRecommendationRead | RecommendationRead:
        """개인 추천 완료 기록. 학원 과제(배포됨)는 기존 과제 완료 API를 쓴다."""
        rec, mode = await self._locked(owner, rec_id, None, self_only=True)
        if data.artwork_id is not None:
            if not data.completed:
                raise UnprocessableError("artwork_id can be sent only when completing")
            artwork = await self._own_artwork(owner, data.artwork_id)
        if data.completed:
            self._check(rec, data.version, (RecommendationStatus.ADOPTED,))
            if rec.started_at is None:
                rec.started_at = clock.utc_now()
            rec.status = RecommendationStatus.COMPLETED
            rec.completed_at = clock.utc_now()
            from_status = RecommendationStatus.ADOPTED
        else:
            self._check(rec, data.version, (RecommendationStatus.COMPLETED,))
            rec.status = RecommendationStatus.ADOPTED
            rec.completed_at = None
            from_status = RecommendationStatus.COMPLETED
        rec.version += 1
        self._history(
            rec,
            owner.id,
            mode,
            RecommendationAction.COMPLETED,
            from_status,
            note=None if data.completed else "uncompleted",
        )
        if data.artwork_id is not None:
            await self.session.flush()
            await link_artwork(self.session, owner, rec.id, artwork)
        return await self._reload(rec, None)

    async def _distribution_class(
        self, actor: AcademyMembership, student_membership_id: uuid.UUID, class_id: uuid.UUID | None
    ) -> uuid.UUID:
        """학생이 배정된 ACTIVE 반 중 actor가 관리하는 반."""
        stmt = (
            select(ClassMembership.class_id)
            .join(AcademyClass, AcademyClass.id == ClassMembership.class_id)
            .where(
                ClassMembership.membership_id == student_membership_id,
                ClassMembership.role == ClassMemberRole.STUDENT,
                ClassMembership.status == ClassMemberStatus.ACTIVE,
                AcademyClass.status == ClassStatus.ACTIVE,
                AcademyClass.academy_id == actor.academy_id,
            )
        )
        if not is_admin(actor):
            stmt = stmt.where(ClassMembership.class_id.in_(taught_class_ids(actor)))
        candidates = sorted(set((await self.session.execute(stmt)).scalars()), key=str)
        if class_id is not None:
            if class_id not in candidates:
                raise UnprocessableError(
                    "The student is not in this class or you do not manage it",
                    code=ErrorCode.CLASS_REQUIRED,
                    details={"class_ids": [str(c) for c in candidates]},
                )
            return class_id
        if len(candidates) != 1:
            raise UnprocessableError(
                "Choose the class to distribute to",
                code=ErrorCode.CLASS_REQUIRED,
                details={"class_ids": [str(c) for c in candidates]},
            )
        return candidates[0]

    async def distribute(
        self,
        profile: Profile,
        rec_id: uuid.UUID,
        data: RecommendationDistribute,
        actor: AcademyMembership,
    ) -> ReviewerRecommendationRead | RecommendationRead:
        """승인된 추천을 기존 v0.3 과제로 배포 (반 학생 1명 대상).

        추천 상태 변경과 과제 생성은 한 트랜잭션으로 저장한다.
        """
        rec, mode = await self._locked(profile, rec_id, actor, self_only=False)
        self._check(rec, data.version, (RecommendationStatus.APPROVED,))
        assert rec.student_membership_id is not None
        class_id = await self._distribution_class(actor, rec.student_membership_id, data.class_id)
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(rec.method_steps, start=1))
        description = (
            f"{rec.description}\n\n연습 방법:\n{steps}\n\n"
            f"예상 시간: {rec.estimated_minutes}분 · 난이도: {rec.difficulty.value}\n"
            f"(맞춤 연습 과제 · 약점: {WEAKNESS_CATEGORY_LABELS[rec.weakness_category]})"
        )[:2000]

        async def link(task: Task) -> None:
            from_status = rec.status
            rec.task_id = task.id
            rec.status = RecommendationStatus.DISTRIBUTED
            rec.version += 1
            self._history(
                rec,
                profile.id,
                mode,
                RecommendationAction.DISTRIBUTED,
                from_status,
                changes={"task_id": str(task.id), "class_id": str(class_id)},
            )
            await NotificationService(self.session).task_distributed(rec)

        await TaskService(self.session).create(
            actor,
            TaskCreate(
                class_id=class_id,
                title=rec.title,
                description=description,
                due_at=data.due_at,
                target_type=TaskTargetType.STUDENTS,
                student_membership_ids=[rec.student_membership_id],
            ),
            before_commit=link,
        )
        await self.session.refresh(rec)
        scope = Scope(rec.owner_id, rec.scope, rec.academy_id, rec.student_membership_id, actor)
        return await self.reviewer_read(scope, rec)

    # ================================================================ 작업 조회

    async def job_for_owner(self, owner: Profile, job_id: uuid.UUID) -> JobRead:
        job = (
            await self.session.execute(
                select(AiProcessingJob).where(
                    AiProcessingJob.id == job_id,
                    AiProcessingJob.owner_id == owner.id,
                    AiProcessingJob.job_type.in_(
                        [AiJobType.GROWTH_REPORT, AiJobType.PRACTICE_RECOMMEND]
                    ),
                )
            )
        ).scalar_one_or_none()
        if job is None:
            raise NotFoundError("Job not found")
        return job_read(job)

    async def job_for_staff(self, actor: AcademyMembership, job_id: uuid.UUID) -> JobRead:
        job = (
            await self.session.execute(
                select(AiProcessingJob).where(
                    AiProcessingJob.id == job_id,
                    AiProcessingJob.job_type.in_(
                        [AiJobType.GROWTH_REPORT, AiJobType.PRACTICE_RECOMMEND]
                    ),
                )
            )
        ).scalar_one_or_none()
        params = job.params if job else {}
        if job is not None and job.report_id is not None:
            report = await self.session.get(GrowthReport, job.report_id)
            params = {
                "academy_id": str(report.academy_id) if report and report.academy_id else None
            }
        if job is None or params.get("academy_id") != str(actor.academy_id):
            raise NotFoundError("Job not found")
        membership_id = params.get("student_membership_id")
        if membership_id and not await self.access.is_managed_student(
            actor, uuid.UUID(membership_id)
        ):
            raise ForbiddenError("This student is not in your classes")
        return job_read(job)

    # ================================================================ v0.9 F-8 과제 수행

    async def _own_artwork(self, owner: Profile, artwork_id: uuid.UUID) -> Artwork:
        artwork = (
            await self.session.execute(
                select(Artwork).where(
                    Artwork.id == artwork_id,
                    Artwork.owner_id == owner.id,
                    Artwork.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if artwork is None:
            # 다른 사람 작품도 존재를 드러내지 않는다
            raise NotFoundError("Artwork not found")
        return artwork

    async def start(
        self, owner: Profile, rec_id: uuid.UUID, data: RecommendationStart
    ) -> ReviewerRecommendationRead | RecommendationRead:
        """개인 과제 시작 기록 (채택 후). 이미 시작했으면 그대로 (멱등)."""
        rec, mode = await self._locked(owner, rec_id, None, self_only=True)
        self._check(rec, data.version, (RecommendationStatus.ADOPTED,))
        if rec.started_at is None:
            rec.started_at = clock.utc_now()
            rec.version += 1
            self._history(rec, owner.id, mode, RecommendationAction.STARTED, rec.status)
        return await self._reload(rec, None)

    async def link_artwork(
        self, owner: Profile, rec_id: uuid.UUID, artwork_id: uuid.UUID
    ) -> list[LinkedArtwork]:
        artwork = await self._own_artwork(owner, artwork_id)
        await link_artwork(self.session, owner, rec_id, artwork)
        await self.session.commit()
        return await self.linked_artworks(owner, rec_id)

    async def unlink_artwork(
        self, owner: Profile, rec_id: uuid.UUID, artwork_id: uuid.UUID
    ) -> None:
        await unlink_artwork(self.session, owner, rec_id, artwork_id)
        await self.session.commit()

    async def _linked(
        self, rec: PracticeRecommendation
    ) -> tuple[list[tuple[Artwork, Any]], dict[uuid.UUID, list[uuid.UUID]], set[uuid.UUID]]:
        """연결 작품, 작품별 승인된 강사 첨삭 id, 과제 약점이 지적된 첨삭 id."""
        rows = list(
            (
                await self.session.execute(
                    select(Artwork, PracticeRecommendationArtwork.created_at)
                    .join(
                        PracticeRecommendationArtwork,
                        PracticeRecommendationArtwork.artwork_id == Artwork.id,
                    )
                    .where(
                        PracticeRecommendationArtwork.recommendation_id == rec.id,
                        Artwork.deleted_at.is_(None),
                    )
                    .order_by(Artwork.work_date, PracticeRecommendationArtwork.created_at)
                )
            ).all()
        )
        ids = [a.id for a, _ in rows]
        feedbacks: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        flagged: set[uuid.UUID] = set()
        if ids:
            summaries = (
                await self.session.execute(
                    select(FeedbackSummary.id, FeedbackSummary.artwork_id).where(
                        FeedbackSummary.artwork_id.in_(ids),
                        FeedbackSummary.status == FeedbackStatus.APPROVED,
                        FeedbackSummary.source == FeedbackSource.INSTRUCTOR,
                    )
                )
            ).all()
            for sid, aid in summaries:
                feedbacks[aid].append(sid)
            if summaries:
                flagged = set(
                    (
                        await self.session.execute(
                            select(FeedbackCategory.summary_id).where(
                                FeedbackCategory.summary_id.in_([s for s, _ in summaries]),
                                FeedbackCategory.category == rec.weakness_category,
                            )
                        )
                    ).scalars()
                )
        return [(a, at) for a, at in rows], feedbacks, flagged

    async def linked_artworks(self, owner: Profile, rec_id: uuid.UUID) -> list[LinkedArtwork]:
        rec = await personal_recommendation(self.session, owner, rec_id)
        rows, feedbacks, flagged = await self._linked(rec)
        return [
            LinkedArtwork(
                artwork_id=a.id,
                title=a.title,
                work_date=a.work_date,
                linked_at=at,
                feedback_count=len(feedbacks[a.id]),
                weakness_mentioned=any(s in flagged for s in feedbacks[a.id])
                if feedbacks[a.id]
                else None,
            )
            for a, at in rows
        ]

    async def follow_up(self, owner: Profile, rec_id: uuid.UUID) -> FollowUp:
        """과제 수행 작품의 후속 강사 첨삭에서 같은 약점이 다시 지적됐는지 (향상 판정 아님)."""
        rec = await personal_recommendation(self.session, owner, rec_id)
        linked = await self.linked_artworks(owner, rec_id)
        analyzed = [la for la in linked if la.weakness_mentioned is not None]
        reappeared = [la for la in analyzed if la.weakness_mentioned]
        if not linked:
            status = "NO_LINKED_ARTWORK"
        elif not analyzed:
            status = "NO_FOLLOW_UP_FEEDBACK"
        elif reappeared:
            status = "REAPPEARED"
        else:
            status = "NOT_MENTIONED"
        scope = Scope(owner.id, GrowthScope.ALL)
        evidence: list[Evidence] = []
        if reappeared:
            rows = (
                await self.session.execute(
                    self._evidence_query()
                    .where(
                        FeedbackSummary.artwork_id.in_([la.artwork_id for la in reappeared]),
                        FeedbackSummary.status == FeedbackStatus.APPROVED,
                        FeedbackSummary.source == FeedbackSource.INSTRUCTOR,
                        FeedbackItem.category == rec.weakness_category,
                        *self._artwork_filter(scope),
                    )
                    .order_by(Artwork.work_date.desc(), FeedbackItem.position)
                    .limit(10)
                )
            ).all()
            evidence = [self._evidence(*row) for row in rows]
        label = WEAKNESS_CATEGORY_LABELS[rec.weakness_category]
        return FollowUp(
            recommendation_id=rec.id,
            weakness_category=rec.weakness_category,
            completed=rec.status == RecommendationStatus.COMPLETED,
            status=status,  # type: ignore[arg-type]
            linked_artworks=linked,
            reappeared_count=len(reappeared),
            analyzed_count=len(analyzed),
            evidence=evidence,
            notes=[
                "과제를 완료했다는 것과 실력이 향상되었다는 것은 같은 뜻이 아닙니다.",
                f"후속 첨삭에서 '{label}'이(가) 언급되지 않았다고 해서 개선되었다고 단정할 수 "
                "없습니다 (첨삭에서 다루지 않았을 수 있음).",
                "강사 첨삭만 확인합니다 (자기 메모·다른 학생 의견 제외).",
            ],
        )

    # ================================================================ v0.9 F-5 아카이브

    async def weakness_history(
        self,
        scope: Scope,
        category: WeaknessCategory,
        params: PaginationParams,
        *,
        include_unverified: bool = False,
    ) -> tuple[list[WeaknessHistoryItem], int]:
        """특정 약점이 지적된 과거 첨삭 항목 (최근순). 기본은 강사 첨삭만."""
        stmt = self._evidence_query().where(
            FeedbackItem.category == category,
            FeedbackItem.kind != FeedbackItemKind.STRENGTH,
            FeedbackSummary.status == FeedbackStatus.APPROVED,
            *self._artwork_filter(scope),
            *self._feedback_visibility(scope),
        )
        if not include_unverified or scope.staff is not None:
            stmt = stmt.where(FeedbackSummary.source == FeedbackSource.INSTRUCTOR)
        stmt = stmt.order_by(
            Artwork.work_date.desc(), FeedbackSummary.approved_at.desc(), FeedbackItem.id
        )
        rows, total = await fetch_page(self.session, stmt, params)
        self._log_access(scope, "weakness_history")
        return [
            WeaknessHistoryItem(
                evidence=self._evidence(*row),
                feedback_summary=row[1].summary,
                approved_at=row[1].approved_at,
            )
            for row in rows
        ], total

    async def _comparison_side(
        self, scope: Scope, artwork: Artwork, photo_urls: dict[uuid.UUID, tuple[str, Any]]
    ) -> ComparisonSide:
        photos = (await self._photo_map([artwork.id]))[artwork.id]
        summaries = list(
            (
                await self.session.execute(
                    select(FeedbackSummary).where(
                        FeedbackSummary.artwork_id == artwork.id,
                        FeedbackSummary.status == FeedbackStatus.APPROVED,
                        FeedbackSummary.source == FeedbackSource.INSTRUCTOR,
                    )
                )
            ).scalars()
        )
        categories = await self._categories([s.id for s in summaries])
        items = (
            list(
                (
                    await self.session.execute(
                        select(FeedbackItem)
                        .where(FeedbackItem.summary_id.in_([s.id for s in summaries]))
                        .order_by(FeedbackItem.position)
                    )
                ).scalars()
            )
            if summaries
            else []
        )
        merged = sorted(
            {c for s in summaries for c in categories.get(s.id, [])},
            key=list(WeaknessCategory).index,
        )
        return ComparisonSide(
            artwork_id=artwork.id,
            title=artwork.title,
            work_date=artwork.work_date,
            practical_type=artwork.practical_type,
            work_category=artwork.work_category,
            topic=artwork.topic,
            actual_minutes=artwork.actual_minutes,
            time_limit_minutes=artwork.time_limit_minutes,
            photos=[
                ComparisonPhoto(
                    stage=p.stage.value,
                    photo_id=p.id,
                    url=photo_urls.get(p.id, (None, None))[0],
                    url_expires_at=photo_urls.get(p.id, (None, None))[1],
                )
                for p in photos
                if p.is_representative
            ],
            feedback_count=len(summaries),
            categories=merged,
            strengths=[i.content for i in items if i.kind == FeedbackItemKind.STRENGTH],
            weaknesses=[i.content for i in items if i.kind == FeedbackItemKind.WEAKNESS],
        )

    async def _photo_map(self, artwork_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ArtworkPhoto]]:
        result: dict[uuid.UUID, list[ArtworkPhoto]] = defaultdict(list)
        for photo in (
            await self.session.execute(
                select(ArtworkPhoto)
                .where(
                    ArtworkPhoto.artwork_id.in_(artwork_ids),
                    ArtworkPhoto.status == PhotoStatus.ACTIVE,
                )
                .order_by(ArtworkPhoto.stage, ArtworkPhoto.uploaded_at)
            )
        ).scalars():
            result[photo.artwork_id].append(photo)
        return result

    async def compare(
        self,
        scope: Scope,
        current_id: uuid.UUID,
        previous_id: uuid.UUID | None,
        *,
        storage: Any,
        token: str | None,
    ) -> ArtworkComparison:
        """이전 작품과 현재 작품 비교. previous를 생략하면 같은 실기 유형의 직전 작품."""
        current = (
            await self.session.execute(
                select(Artwork).where(Artwork.id == current_id, *self._artwork_filter(scope))
            )
        ).scalar_one_or_none()
        if current is None:
            raise NotFoundError("Artwork not found")
        if previous_id is not None:
            previous = (
                await self.session.execute(
                    select(Artwork).where(Artwork.id == previous_id, *self._artwork_filter(scope))
                )
            ).scalar_one_or_none()
            if previous is None:
                raise NotFoundError("Artwork not found")
        else:
            stmt = select(Artwork).where(
                *self._artwork_filter(scope),
                Artwork.id != current.id,
                (Artwork.work_date < current.work_date)
                | (
                    (Artwork.work_date == current.work_date)
                    & (Artwork.created_at < current.created_at)
                ),
            )
            if current.practical_type is not None:
                stmt = stmt.where(Artwork.practical_type == current.practical_type)
            previous = (
                await self.session.execute(
                    stmt.order_by(Artwork.work_date.desc(), Artwork.created_at.desc()).limit(1)
                )
            ).scalar_one_or_none()
            if previous is None:
                raise ConflictError(
                    "There is no earlier artwork to compare with",
                    code=ErrorCode.ARTWORK_NOT_COMPARABLE,
                )
        if previous.id == current.id:
            raise UnprocessableError("Choose two different artworks")
        photo_urls: dict[uuid.UUID, tuple[str, Any]] = {}
        photos = await self._photo_map([previous.id, current.id])
        reps = [p for ps in photos.values() for p in ps if p.is_representative]
        if storage is not None and token and reps:
            expires = clock.utc_now() + timedelta(seconds=self.settings.storage_signed_url_seconds)
            try:
                urls = await storage.create_signed_urls(
                    [p.storage_path for p in reps],
                    access_token=token,
                    expires_in=self.settings.storage_signed_url_seconds,
                )
            except Exception:  # Storage 장애여도 메타데이터 비교는 제공 (URL만 null)
                logger.warning("comparison photo urls unavailable")
                urls = {}
            photo_urls = {
                p.id: (urls[p.storage_path], expires) for p in reps if p.storage_path in urls
            }
        prev_side = await self._comparison_side(scope, previous, photo_urls)
        cur_side = await self._comparison_side(scope, current, photo_urls)
        before, after = set(prev_side.categories), set(cur_side.categories)
        order = list(WeaknessCategory).index
        self._log_access(scope, "compare", current.id)
        return ArtworkComparison(
            previous=prev_side,
            current=cur_side,
            still_mentioned=sorted(before & after, key=order),
            not_mentioned_now=sorted(before - after, key=order),
            newly_mentioned=sorted(after - before, key=order),
            notes=[
                "강사 첨삭에서 지적된 항목만 비교합니다 (AI가 사진을 평가하지 않습니다).",
                "이번 작품에서 언급되지 않은 항목이 개선되었다는 뜻은 아닙니다.",
            ],
        )
