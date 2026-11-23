"""v1.2 아카이브 분석 리포트·홈 오늘의 브리핑.

비용·일관성 원칙
- 조회 때 LLM을 부르지 않는다. 브리핑 문장은 규칙으로 만들고, 문장에 넣는 첨삭 내용은 학생이 확정한
  실제 첨삭 항목 문장을 그대로 인용한다 (AI가 새 평가를 만들 수 없음).
- 분석은 매 조회마다 DB의 현재 확정 첨삭으로 다시 계산한다 → 첨삭 수정·삭제·확정 취소, 작품 삭제,
  단계 변경이 즉시 반영되고 오래된 분석이 남지 않는다. 데이터 지문(`data_fingerprint`)으로 같은
  데이터인지 확인할 수 있다.
- AI 설명문은 기존 성장 리포트(growth_reports.narrative)에 저장된 것만 읽는다. 데이터 지문이 같아야
  READY, 다르면 STALE. 데이터가 바뀌었으면 브리핑 조회 때 리포트 설명문을 한 번 다시 요청할 수 있다
  (`growth_briefing_auto_refresh`, 성장 AI 켜짐 + 동의 + 최소 간격, 같은 데이터는 dedupe로 1번).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.core import timezone as clock
from app.core.config import Settings
from app.models.ai_feedback import AiProcessingJob, FeedbackSummary
from app.models.artwork import Artwork
from app.models.enums import (
    ACTIVE_JOB_STATUSES,
    CATEGORY_TAG,
    AiConsentPurpose,
    AiJobType,
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    FeedbackItemKind,
    FeedbackSource,
    FeedbackStatus,
    GrowthScope,
    NarrativeStatus,
    ReportPeriod,
    ReportStatus,
)
from app.models.growth import GrowthReport
from app.models.profile import Profile
from app.schemas.growth import Evidence, ReportCreate
from app.schemas.insights import (
    AiNarrativeRead,
    AnalysisCriteria,
    AnalysisReport,
    ArtworkRef,
    Briefing,
    RecentFeedbackRead,
    RecordCounts,
    TagEvent,
    TagInsight,
    ThemeRead,
)
from app.services.ai_feedback import AiFeedbackService
from app.services.growth import GrowthService, Scope, period_range
from app.services.growth_analytics import Dataset, fingerprint
from app.services.growth_insights import (
    MIN_REPEAT_ARTWORKS,
    MIN_STRENGTH_ARTWORKS,
    MIN_THEME_ARTWORKS,
    build_insights,
    tag_entry,
)

logger = logging.getLogger(__name__)

MAX_QUOTE = 80
MAX_RECENT_FEEDBACKS = 5
MAX_NEXT_PRACTICE = 5

MSG_NO_RECORDS = "아직 첨삭 기록이 없어요. 첫 작품을 등록하고 선생님의 피드백을 기록해 보세요!"
MSG_NO_FEEDBACK = "아직 첨삭 기록이 없어요. 작품에 선생님의 피드백을 기록해 보세요!"
MSG_SELF_ONLY = (
    "자기 메모는 참고로만 보관돼요. 선생님 첨삭을 기록하면 반복되는 강점과 개선점을 알려 드릴게요."
)
MSG_PROCESSING = "첨삭을 정리하고 있어요. 잠시 후 다시 확인해 주세요."
MSG_CONFIRM = "내용을 확인하고 확정하면 오늘의 브리핑과 아카이브 분석에 반영돼요."
MSG_INSUFFICIENT = (
    "아직 성장 추세를 분석할 만큼 첨삭 기록이 충분하지 않아요. 작품과 첨삭이 더 쌓이면 "
    "반복되는 강점과 개선점을 확인할 수 있어요."
)
NOTES = [
    "분석은 학생이 확정한 강사 첨삭만 근거로 하며, AI가 그림을 보고 평가한 결과가 아닙니다.",
    "첨삭에서 언급되지 않은 영역이 좋아졌다는 뜻은 아닙니다. 개선 추세는 실제 긍정 첨삭이 있을 때만 "
    "보여 줍니다.",
    "점수·성장률은 만들지 않습니다. 숫자는 실제 작품 수와 날짜입니다.",
]
IMPROVEMENT_RULE = (
    "같은 영역에서 지적이 먼저 있고, 그 뒤 작품들의 첨삭이 모두 긍정일 때 개선 추세로 봅니다 "
    "(긍정 2개 작품 이상이면 확인됨)."
)


def _quote(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= MAX_QUOTE else text[: MAX_QUOTE - 1] + "…"


def compose_briefing(
    *,
    counts: dict[str, Any],
    insights: dict[str, Any],
    contents: dict[str, str],
    has_self_notes: bool,
) -> dict[str, Any]:
    """브리핑 문장 (순수 함수). 근거 항목 ID를 함께 돌려준다.

    contents: 항목 ID → 확정된 첨삭 항목 문장 (인용용).
    """
    pending = counts["pending_review_count"]
    result: dict[str, Any] = {
        "lines": [],
        "focus": None,
        "highlight": None,
        "practice_item_id": None,
        "evidence_item_ids": [],
    }
    if counts["instructor_feedback_count"] == 0:
        if pending:
            result["status"] = "NEEDS_CONFIRMATION"
            result["headline"] = f"AI가 정리한 첨삭 {pending}건이 확인을 기다리고 있어요."
            result["lines"] = [MSG_CONFIRM]
        elif counts["processing_count"]:
            result["status"] = "PROCESSING"
            result["headline"] = MSG_PROCESSING
        elif counts["artwork_count"] == 0:
            result["status"] = "NO_RECORDS"
            result["headline"] = MSG_NO_RECORDS
        else:
            result["status"] = "NO_FEEDBACK"
            result["headline"] = MSG_NO_FEEDBACK
            if has_self_notes:
                result["lines"] = [MSG_SELF_ONLY]
        return result

    tags = insights["tags"]
    sufficient = insights["sufficient"]
    focus_tag: dict[str, Any] | None = None
    reason = "RECENT"
    if sufficient and insights["needs_work"]:
        focus_tag = tag_entry(insights, insights["needs_work"][0])
        if focus_tag["issue_artwork_count"] >= MIN_REPEAT_ARTWORKS:
            reason = "REPEATED"
    elif not sufficient:
        # 데이터 부족: 가장 최근 지적 1개만 (반복·추세 판단 없이)
        issued = [t for t in tags if t["last_issue_date"] and t["progress"] != "IMPROVING"]
        if issued:
            focus_tag = max(issued, key=lambda t: t["last_issue_date"])

    highlight_tag: dict[str, Any] | None = None
    highlight_kind = "RECENT_POSITIVE"
    if sufficient:
        for code in insights["improving"]:
            highlight_tag, highlight_kind = tag_entry(insights, code), "IMPROVING"
            break
        if highlight_tag is None:
            for code in insights["strengths"]:
                if focus_tag is None or code != focus_tag["tag"]:
                    highlight_tag, highlight_kind = tag_entry(insights, code), "STRENGTH"
                    break
    else:
        positives = [t for t in tags if t["last_positive_date"]]
        if positives:
            highlight_tag = max(positives, key=lambda t: t["last_positive_date"])

    lines: list[str] = []
    evidence: list[str] = []
    if focus_tag is not None:
        theme = focus_tag["themes"][0]["label"] if focus_tag["themes"] else None
        subject = theme or focus_tag["label"]
        result["focus"] = {
            "tag": focus_tag["tag"],
            "label": focus_tag["label"],
            "theme_label": theme,
            "reason": reason,
            "artwork_count": focus_tag["issue_artwork_count"],
        }
        if reason == "REPEATED":
            headline = (
                f"최근 {subject}에 대한 첨삭이 {focus_tag['issue_artwork_count']}개 작품에서 "
                "반복되고 있어요."
            )
            evidence += (
                focus_tag["themes"][0]["item_ids"][:2] if theme else focus_tag["issue_item_ids"][:2]
            )
        else:
            headline = f"최근 첨삭에서 {subject}에 대한 지적이 있었어요."
            evidence += focus_tag["issue_item_ids"][:1]
        practice = next((i for i in focus_tag["practice_item_ids"] if i in contents), None)
        if practice:
            result["practice_item_id"] = practice
            evidence.append(practice)
            practice_line = (
                f"오늘은 이 첨삭을 떠올리며 연습해 보세요: “{_quote(contents[practice])}”"
            )
        else:
            practice_line = f"오늘은 {subject} 부분을 집중해서 연습해 보세요."
    elif highlight_tag is None:
        headline = "최근 첨삭이 기록됐어요."
        practice_line = None
    else:
        headline = "최근 첨삭에서 반복되는 지적은 없어요." if sufficient else ""
        practice_line = None

    if highlight_tag is not None:
        label = highlight_tag["label"]
        count = highlight_tag["positive_artwork_count"]
        result["highlight"] = {
            "tag": highlight_tag["tag"],
            "label": label,
            "kind": highlight_kind,
            "artwork_count": count,
        }
        if highlight_kind == "IMPROVING":
            tail = (
                "첨삭이 이어지고 있어요."
                if highlight_tag["improvement_confirmed"]
                else "첨삭이 있었어요."
            )
            line = f"{label} 부분은 이전 지적 이후 좋아졌다는 {tail}"
        elif highlight_kind == "STRENGTH":
            line = f"{label} 부분은 {count}개 작품에서 좋다는 첨삭을 받았어요. 이 강점은 유지해 보세요."
        else:
            line = f"최근 첨삭에서 {label} 부분이 좋다는 평가가 있었어요."
        evidence += highlight_tag["positive_item_ids"][:1]
        if headline:
            lines.append(line)
        else:
            headline = line

    if practice_line:
        lines.append(practice_line)
    if not sufficient:
        lines.append(MSG_INSUFFICIENT)
    if pending:
        lines.append(f"확정을 기다리는 첨삭이 {pending}건 있어요. 확정하면 분석에 반영돼요.")
    result["status"] = "READY" if sufficient else "INSUFFICIENT_DATA"
    result["headline"] = headline
    result["lines"] = lines
    result["evidence_item_ids"] = list(dict.fromkeys(evidence))
    return result


class GrowthInsightService:
    """학생 본인의 전체 작품(scope ALL) 기준 아카이브 분석·브리핑."""

    def __init__(self, growth: GrowthService) -> None:
        self.growth = growth
        self.session = growth.session
        self.settings: Settings = growth.settings

    # ------------------------------------------------------------------ 공통 데이터

    async def _basis(self, owner: Profile) -> tuple[Scope, Dataset, dict[str, Any], str]:
        scope = Scope(owner.id, GrowthScope.ALL)
        start, end = period_range(ReportPeriod.ALL, None, None)
        dataset = await self.growth.load(scope, start, end)
        insights = build_insights(dataset, min_artworks=self.settings.growth_min_artworks)
        return scope, dataset, insights, fingerprint(dataset)

    async def _counts(self, owner: Profile, dataset: Dataset) -> dict[str, Any]:
        pending = (
            await self.session.execute(
                select(func.count())
                .select_from(FeedbackSummary)
                .join(Artwork, Artwork.id == FeedbackSummary.artwork_id)
                .where(
                    FeedbackSummary.owner_id == owner.id,
                    Artwork.deleted_at.is_(None),
                    FeedbackSummary.status.in_([FeedbackStatus.DRAFT, FeedbackStatus.IN_REVIEW]),
                )
            )
        ).scalar_one()
        processing = (
            await self.session.execute(
                select(func.count())
                .select_from(AiProcessingJob)
                .where(
                    AiProcessingJob.owner_id == owner.id,
                    AiProcessingJob.job_type.in_([AiJobType.TRANSCRIBE, AiJobType.SUMMARIZE]),
                    AiProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
                )
            )
        ).scalar_one()
        artworks = {a.id: a for a in dataset.artworks}
        instructor = [f for f in dataset.feedbacks if f.source == FeedbackSource.INSTRUCTOR]
        mock = sum(1 for a in artworks.values() if a.work_category == ArtworkWorkCategory.MOCK_EXAM)
        dates = [artworks[f.artwork_id].work_date for f in dataset.feedbacks]
        return {
            "artwork_count": len(artworks),
            "completed_artwork_count": sum(
                1 for a in artworks.values() if a.work_status == ArtworkWorkStatus.COMPLETED
            ),
            "mock_exam_count": mock,
            "practice_artwork_count": len(artworks) - mock,
            "confirmed_feedback_count": len(dataset.feedbacks),
            "instructor_feedback_count": len(instructor),
            "analyzed_artwork_count": len({f.artwork_id for f in instructor}),
            "pending_review_count": pending,
            "processing_count": processing,
            "last_feedback_date": max(dates) if dates else None,
        }

    async def _narrative(
        self, owner: Profile, fp: str, *, sufficient: bool, may_refresh: bool
    ) -> AiNarrativeRead:
        reports = list(
            (
                await self.session.execute(
                    select(GrowthReport)
                    .where(
                        GrowthReport.owner_id == owner.id,
                        GrowthReport.scope == GrowthScope.ALL,
                        GrowthReport.period_type == ReportPeriod.ALL,
                    )
                    .order_by(GrowthReport.created_at.desc())
                    .limit(20)
                )
            ).scalars()
        )
        current = [r for r in reports if r.data_fingerprint == fp]
        fresh = next((r for r in current if r.narrative_status == NarrativeStatus.READY), None)
        if fresh is not None:
            return _narrative_read(fresh, "READY", current=True)
        previous = next(
            (
                r
                for r in reports
                if r.narrative_status == NarrativeStatus.READY and r.narrative is not None
            ),
            None,
        )
        if not self.settings.growth_ai_active:
            return AiNarrativeRead(status="NOT_AVAILABLE", reason="GROWTH_AI_NOT_CONFIGURED")
        if not sufficient:
            return AiNarrativeRead(status="NOT_AVAILABLE", reason="INSUFFICIENT_DATA")
        pending = next((r for r in current if r.narrative_status == NarrativeStatus.PENDING), None)
        if pending is None and may_refresh and await self._refresh(owner, reports):
            return await self._narrative(owner, fp, sufficient=sufficient, may_refresh=False)
        if pending is not None:
            status = "PENDING"
        elif any(r.narrative_status == NarrativeStatus.FAILED for r in current):
            status = "FAILED"
        else:
            status = "STALE" if previous else "NONE"
        reason = next(
            (r.narrative_error_code for r in current if r.narrative_error_code),
            None,
        )
        if previous is not None:
            return _narrative_read(previous, status, current=False, reason=reason)
        return AiNarrativeRead(status=status, reason=reason)

    async def _refresh(self, owner: Profile, reports: list[GrowthReport]) -> bool:
        """데이터가 바뀌었으면 AI 설명문을 한 번 다시 요청 (최소 간격·동의 확인). 요청했으면 True."""
        if not self.settings.growth_briefing_auto_refresh:
            return False
        last = max((r.updated_at for r in reports), default=None)
        cooldown = timedelta(minutes=self.settings.growth_briefing_refresh_minutes)
        if last is not None and clock.utc_now() - last < cooldown:
            return False
        if not await AiFeedbackService(self.session, self.settings).has_valid_ai_consent(
            owner.id, AiConsentPurpose.GROWTH_COACHING
        ):
            return False
        scope = Scope(owner.id, GrowthScope.ALL)
        report, _ = await self.growth.create_report(
            scope,
            ReportCreate(period=ReportPeriod.ALL, include_ai_narrative=True),
            owner,
            notify=False,
        )
        logger.info(
            "briefing narrative refresh requested",
            extra={"report_id": str(report.id), "status": report.status.value},
        )
        return report.status == ReportStatus.READY

    async def _evidence(self, scope: Scope, ids: list[str]) -> dict[str, Evidence]:
        return await self.growth.resolve_evidence(scope, ids)

    def _tag_read(
        self,
        tag: dict[str, Any],
        evidence: dict[str, Evidence],
        artworks: dict[str, ArtworkRef],
    ) -> TagInsight:
        def pick(ids: list[str]) -> list[Evidence]:
            return [evidence[i] for i in ids if i in evidence]

        related = list(dict.fromkeys(tag["issue_artwork_ids"] + tag["positive_artwork_ids"]))
        return TagInsight(
            tag=tag["tag"],
            label=tag["label"],
            progress=tag["progress"],
            issue_artwork_count=tag["issue_artwork_count"],
            positive_artwork_count=tag["positive_artwork_count"],
            first_issue_date=tag["first_issue_date"],
            last_issue_date=tag["last_issue_date"],
            last_positive_date=tag["last_positive_date"],
            positive_since_last_issue=tag["positive_since_last_issue"],
            improvement_confirmed=tag["improvement_confirmed"],
            themes=[
                ThemeRead(
                    code=t["code"],
                    label=t["label"],
                    artwork_count=t["artwork_count"],
                    evidence=pick(t["item_ids"]),
                )
                for t in tag["themes"]
            ],
            issue_evidence=pick(tag["issue_item_ids"]),
            positive_evidence=pick(tag["positive_item_ids"]),
            practice_evidence=pick(tag["practice_item_ids"]),
            related_artworks=sorted(
                (artworks[a] for a in related if a in artworks),
                key=lambda a: a.work_date,
                reverse=True,
            ),
            events=[TagEvent(**e) for e in tag["events"]],
        )

    @staticmethod
    def _all_item_ids(insights: dict[str, Any]) -> list[str]:
        ids: list[str] = []
        for t in insights["tags"]:
            ids += t["issue_item_ids"] + t["positive_item_ids"] + t["practice_item_ids"]
            for theme in t["themes"]:
                ids += theme["item_ids"]
        return ids

    # ------------------------------------------------------------------ 아카이브 분석 리포트

    async def analysis_report(self, owner: Profile) -> AnalysisReport:
        scope, dataset, insights, fp = await self._basis(owner)
        counts = await self._counts(owner, dataset)
        instructor = {f.id for f in dataset.feedbacks if f.source == FeedbackSource.INSTRUCTOR}
        next_tips = sorted(
            (
                i
                for i in dataset.items
                if i.kind == FeedbackItemKind.NEXT_TIP and i.feedback_id in instructor
            ),
            key=lambda i: (i.work_date, i.approved_at),
            reverse=True,
        )[:MAX_NEXT_PRACTICE]
        evidence = await self._evidence(
            scope, self._all_item_ids(insights) + [str(i.id) for i in next_tips]
        )
        artworks = {
            str(a.id): ArtworkRef(id=a.id, title=a.title, work_date=a.work_date)
            for a in dataset.artworks
        }
        by_tag = {t["tag"]: self._tag_read(t, evidence, artworks) for t in insights["tags"]}
        if counts["instructor_feedback_count"] == 0:
            status = "NEEDS_CONFIRMATION" if counts["pending_review_count"] else "NO_FEEDBACK"
            message = MSG_CONFIRM if status == "NEEDS_CONFIRMATION" else MSG_NO_FEEDBACK
        elif not insights["sufficient"]:
            status, message = "INSUFFICIENT_DATA", MSG_INSUFFICIENT
        else:
            status, message = "READY", None
        self.growth._log_access(scope, "analysis_report")
        return AnalysisReport(
            status=status,  # type: ignore[arg-type]
            message=message,
            generated_at=clock.utc_now(),
            data_fingerprint=fp,
            insights_version=insights["insights_version"],
            counts=RecordCounts(**counts),
            recent_feedbacks=await self._recent_feedbacks(scope),
            repeated_mistakes=[by_tag[t] for t in insights["repeated_mistakes"]],
            strengths=[by_tag[t] for t in insights["strengths"]],
            improving=[by_tag[t] for t in insights["improving"]],
            needs_work=[by_tag[t] for t in insights["needs_work"]],
            next_practice=[evidence[str(i.id)] for i in next_tips if str(i.id) in evidence],
            tags=list(by_tag.values()),
            ai_narrative=await self._narrative(
                owner, fp, sufficient=insights["sufficient"], may_refresh=False
            ),
            criteria=AnalysisCriteria(
                required_artwork_count=insights["required_artwork_count"],
                repeated_min_artworks=MIN_REPEAT_ARTWORKS,
                strength_min_artworks=MIN_STRENGTH_ARTWORKS,
                theme_min_artworks=MIN_THEME_ARTWORKS,
                improvement_rule=IMPROVEMENT_RULE,
            ),
            notes=NOTES,
        )

    async def _recent_feedbacks(self, scope: Scope) -> list[RecentFeedbackRead]:
        rows = (
            await self.session.execute(
                select(FeedbackSummary, Artwork)
                .join(Artwork, Artwork.id == FeedbackSummary.artwork_id)
                .where(
                    FeedbackSummary.status == FeedbackStatus.APPROVED,
                    *self.growth._artwork_filter(scope),
                )
                .order_by(FeedbackSummary.approved_at.desc())
                .limit(MAX_RECENT_FEEDBACKS)
            )
        ).all()
        categories = await self.growth._categories([s.id for s, _ in rows])
        return [
            RecentFeedbackRead(
                feedback_id=s.id,
                artwork_id=a.id,
                artwork_title=a.title,
                work_date=a.work_date,
                approved_at=s.approved_at,  # type: ignore[arg-type]
                source=s.source,
                summary=s.summary,
                tags=list(dict.fromkeys(CATEGORY_TAG[c] for c in categories.get(s.id, []))),
            )
            for s, a in rows
        ]

    # ------------------------------------------------------------------ 홈 브리핑

    async def briefing(self, owner: Profile) -> Briefing:
        scope, dataset, insights, fp = await self._basis(owner)
        counts = await self._counts(owner, dataset)
        contents = {str(i.id): i.content for i in dataset.items if i.content}
        composed = compose_briefing(
            counts=counts,
            insights=insights,
            contents=contents,
            has_self_notes=any(f.source != FeedbackSource.INSTRUCTOR for f in dataset.feedbacks),
        )
        evidence = await self._evidence(scope, composed["evidence_item_ids"])
        ai_comment = await self._narrative(
            owner,
            fp,
            sufficient=insights["sufficient"],
            may_refresh=composed["status"] == "READY",
        )
        self.growth._log_access(scope, "briefing")
        practice = composed["practice_item_id"]
        return Briefing(
            status=composed["status"],
            headline=composed["headline"],
            lines=composed["lines"],
            focus=composed["focus"],
            highlight=composed["highlight"],
            practice=evidence.get(practice) if practice else None,
            evidence=[evidence[i] for i in composed["evidence_item_ids"] if i in evidence],
            counts=RecordCounts(**counts),
            ai_comment=ai_comment,
            data_fingerprint=fp,
            generated_at=clock.utc_now(),
        )


def _narrative_read(
    report: GrowthReport, status: str, *, current: bool, reason: str | None = None
) -> AiNarrativeRead:
    narrative = report.narrative or {}
    return AiNarrativeRead(
        status=status,  # type: ignore[arg-type]
        report_id=report.id,
        overview=narrative.get("overview"),
        strengths_comment=narrative.get("strengths_comment"),
        improvement_comment=narrative.get("improvement_comment"),
        based_on_current_data=current,
        generated_at=report.updated_at,
        reason=reason,
    )
