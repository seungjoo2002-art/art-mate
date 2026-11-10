"""성장 코치 API 요청·응답 (v0.7)."""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.enums import (
    ArtworkProgress,
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    Confidence,
    Difficulty,
    FeedbackItemKind,
    GrowthScope,
    NarrativeStatus,
    PracticalType,
    RecommendationAction,
    RecommendationSource,
    RecommendationStatus,
    ReportPeriod,
    ReportStatus,
    ReviewMode,
    TrendDirection,
    WeaknessCategory,
)
from app.schemas.ai_feedback import JobRead
from app.schemas.fields import InputModel
from app.schemas.students import StudentRef

# ============================================================================ 공통


class ScopeRead(BaseModel):
    scope: GrowthScope
    academy_id: uuid.UUID | None
    student_membership_id: uuid.UUID | None


class Evidence(BaseModel):
    """근거 첨삭 항목 (조회 시점의 승인된 첨삭에서 읽음, 삭제되면 빠진다)."""

    item_id: uuid.UUID
    feedback_id: uuid.UUID
    recording_id: uuid.UUID
    artwork_id: uuid.UUID
    artwork_title: str
    work_date: dt.date
    kind: FeedbackItemKind
    category: WeaknessCategory | None
    content: str
    start_ms: int | None = Field(description="녹음에서 근거 구간 시작 (재생 위치)")


class WindowStat(BaseModel):
    analyzed_artwork_count: int
    artwork_count: int
    ratio: float | None = Field(description="artwork_count / analyzed_artwork_count (0~1)")


class WeaknessStat(BaseModel):
    category: WeaknessCategory
    label: str
    mention_count: int = Field(description="이 카테고리가 붙은 승인 첨삭 수")
    artwork_count: int = Field(description="이 카테고리가 지적된 작품 수 (작품당 1번)")
    artwork_ratio: float | None = Field(description="분석 대상 작품 중 비율")
    recent: WindowStat = Field(description="최근 N개 분석 작품")
    previous: WindowStat | None = Field(description="그 이전 N개 (둘 다 N개일 때만)")
    trend: TrendDirection = Field(
        description="최근 구간의 작품 단위 지적 비율 비교. LESS_FREQUENT는 '개선'을 뜻하지 않는다"
    )
    repeated: bool = Field(description="2개 이상 작품에서 지적됨")
    last_seen_work_date: dt.date
    evidence: list[Evidence]


class StrengthStat(BaseModel):
    category: WeaknessCategory | None
    label: str
    artwork_count: int
    evidence: list[Evidence]


class TimelineBucket(BaseModel):
    bucket_start: dt.date
    analyzed_artwork_count: int
    categories: dict[str, int] = Field(description="카테고리 → 지적된 작품 수")


class Distribution(BaseModel):
    practical_type: PracticalType | None = None
    work_category: ArtworkWorkCategory | None = None
    artwork_count: int


class Totals(BaseModel):
    artwork_count: int
    completed_artwork_count: int
    approved_feedback_count: int
    analyzed_artwork_count: int = Field(description="승인된 첨삭이 있는 작품 수 (분석 대상)")


class NextGoal(BaseModel):
    category: WeaknessCategory
    goal: str
    based_on: Evidence | None


class WeaknessAnalysis(BaseModel):
    """규칙 기반 통계 (AI 생성 아님)."""

    scope: ScopeRead
    period_start: dt.date | None
    period_end: dt.date | None
    status: ReportStatus
    message: str | None = Field(description="데이터 부족 시 안내 문구")
    required_artwork_count: int
    confidence: Confidence = Field(description="분석 대상 작품 수 기준 신뢰도")
    recent_window: int
    totals: Totals
    practical_type_distribution: list[Distribution]
    work_category_distribution: list[Distribution]
    top_weaknesses: list[WeaknessCategory] = Field(description="반복 약점 TOP 3")
    weaknesses: list[WeaknessStat]
    strengths: list[StrengthStat] = Field(description="강사가 잘한 점으로 언급한 부분")
    timeline_bucket: Literal["week", "month"]
    timeline: list[TimelineBucket]
    next_goals: list[NextGoal] = Field(description="규칙 기반 다음 학습 목표")
    notes: list[str] = Field(description="해석 시 주의 문구 (화면에 함께 표시)")


# ============================================================================ 타임라인


class StageCount(BaseModel):
    stage: str
    photo_count: int
    representative_photo_id: uuid.UUID | None


class TimelineFeedback(BaseModel):
    id: uuid.UUID
    recording_id: uuid.UUID
    summary: str
    categories: list[WeaknessCategory]
    strengths: list[str]
    weaknesses: list[str]
    fixes: list[str]
    approved_at: dt.datetime


class TimelineTask(BaseModel):
    task_id: uuid.UUID
    title: str
    completed: bool | None = Field(description="이 학생의 완료 여부 (배정이 없으면 null)")


class TimelineArtwork(BaseModel):
    artwork_id: uuid.UUID
    title: str
    work_date: dt.date
    created_at: dt.datetime
    academy_id: uuid.UUID | None
    practical_type: PracticalType | None
    work_category: ArtworkWorkCategory | None
    work_status: ArtworkWorkStatus
    completed_at: dt.datetime | None
    progress: ArtworkProgress
    cover_photo_id: uuid.UUID | None
    stages: list[StageCount]
    feedbacks: list[TimelineFeedback] = Field(description="승인된 첨삭만")
    task: TimelineTask | None = Field(description="작품에 연결된 v0.3 과제")


# ============================================================================ 요약 (대시보드)


class RecentFeedback(BaseModel):
    id: uuid.UUID
    artwork_id: uuid.UUID
    artwork_title: str
    summary: str
    categories: list[WeaknessCategory]
    approved_at: dt.datetime


class ReportMeta(BaseModel):
    id: uuid.UUID
    period_type: ReportPeriod
    period_start: dt.date | None
    period_end: dt.date
    status: ReportStatus
    narrative_status: NarrativeStatus
    created_at: dt.datetime


class GrowthSummary(BaseModel):
    scope: ScopeRead
    student: StudentRef | None = Field(description="강사 화면일 때")
    totals: Totals
    confidence: Confidence
    status: ReportStatus = Field(description="전체 기간 기준 분석 가능 여부")
    message: str | None
    top_weaknesses: list[WeaknessStat] = Field(description="반복 약점 TOP 3 (최근 경향 포함)")
    recent_feedbacks: list[RecentFeedback]
    latest_report: ReportMeta | None
    open_recommendation_count: int = Field(
        description="학생: 진행 중 과제 수 / 강사: 검토 대기 추천 수"
    )
    notes: list[str]


class StudentGrowthRow(BaseModel):
    student: StudentRef
    analyzed_artwork_count: int
    top_weaknesses: list[WeaknessCategory]
    last_feedback_at: dt.datetime | None
    pending_recommendation_count: int


# ============================================================================ 리포트


class ReportCreate(InputModel):
    period: ReportPeriod = ReportPeriod.MONTH
    date_from: dt.date | None = Field(default=None, alias="from", description="CUSTOM일 때 필수")
    date_to: dt.date | None = Field(default=None, alias="to", description="CUSTOM일 때 필수")
    scope: GrowthScope = Field(
        default=GrowthScope.ALL, description="학생: ALL/PERSONAL/ACADEMY. 강사 API는 항상 ACADEMY"
    )
    academy_id: uuid.UUID | None = Field(default=None, description="scope=ACADEMY일 때 (학생)")
    include_ai_narrative: bool = Field(
        default=False,
        description="AI 설명문 생성 요청 (학생의 GROWTH_COACHING 동의 필요, 없으면 SKIPPED)",
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def _check(self) -> "ReportCreate":
        if self.period == ReportPeriod.CUSTOM:
            if self.date_from is None or self.date_to is None:
                raise ValueError("from and to are required for CUSTOM period")
            if self.date_from > self.date_to:
                raise ValueError("from must be on or before to")
            if (self.date_to - self.date_from).days > 731:
                raise ValueError("CUSTOM period can be at most 2 years")
        elif self.date_from is not None or self.date_to is not None:
            raise ValueError("from/to are only for CUSTOM period")
        if (self.scope == GrowthScope.ACADEMY) != (self.academy_id is not None):
            raise ValueError("academy_id is required only for scope=ACADEMY")
        return self


class ReportRegenerate(InputModel):
    include_ai_narrative: bool = Field(
        default=False, description="AI 설명문도 다시 요청 (동의 필요, 실패·건너뜀이었을 때)"
    )


class Narrative(BaseModel):
    overview: str
    strengths_comment: str
    improvement_comment: str
    next_goals: list[dict[str, Any]] = Field(description="[{goal, evidence: [Evidence]}]")


class NarrativeRead(BaseModel):
    """AI 생성 설명문 (통계와 분리 표시). 숫자·예측을 만들지 않도록 검증됨."""

    status: NarrativeStatus
    generated_by: Literal["AI"] = "AI"
    content: Narrative | None
    error_code: str | None
    model_name: str | None
    prompt_version: str | None


class ReportRead(BaseModel):
    id: uuid.UUID
    scope: ScopeRead
    period_type: ReportPeriod
    period_start: dt.date | None
    period_end: dt.date
    status: ReportStatus
    message: str | None
    statistics: WeaknessAnalysis = Field(description="데이터 기반 통계 (규칙 계산)")
    ai_narrative: NarrativeRead = Field(description="AI 설명 (선택)")
    is_stale: bool = Field(description="생성 후 첨삭·작품 데이터가 바뀜 → 재생성 권장")
    analysis_version: str
    source_feedback_count: int
    generated_by_name: str | None
    created_at: dt.datetime


class ReportListItem(ReportMeta):
    scope: ScopeRead
    is_stale: bool | None = Field(default=None, description="목록에서는 계산하지 않음")


# ============================================================================ 추천 과제


class RecommendationGenerate(InputModel):
    scope: GrowthScope = Field(
        default=GrowthScope.PERSONAL,
        description="학생: PERSONAL(본인 채택) 또는 ACADEMY(강사 승인). 강사 API는 ACADEMY",
    )
    academy_id: uuid.UUID | None = None
    use_ai: bool = Field(
        default=False,
        description="true: Gemini 생성 (GROWTH_COACHING 동의 필요, 비동기 202). "
        "false: 규칙 기반 즉시",
    )

    @model_validator(mode="after")
    def _check(self) -> "RecommendationGenerate":
        if self.scope == GrowthScope.ALL:
            raise ValueError("scope must be PERSONAL or ACADEMY")
        if (self.scope == GrowthScope.ACADEMY) != (self.academy_id is not None):
            raise ValueError("academy_id is required only for scope=ACADEMY")
        return self


class TaskLink(BaseModel):
    task_id: uuid.UUID
    title: str
    due_at: dt.datetime | None
    completed: bool | None
    completed_at: dt.datetime | None


class RecommendationRead(BaseModel):
    id: uuid.UUID
    scope: ScopeRead
    review_mode: ReviewMode
    source: RecommendationSource
    status: RecommendationStatus
    version: int
    weakness_category: WeaknessCategory
    practical_type: PracticalType | None
    title: str
    description: str
    method_steps: list[str]
    estimated_minutes: int
    difficulty: Difficulty
    reason: str
    evidence: list[Evidence] = Field(description="근거 첨삭 (삭제된 것은 빠짐)")
    analysis: dict[str, Any] = Field(description="생성 시 약점 통계 (기간·작품 수·최근 비율)")
    task: TaskLink | None = Field(description="학원: 배포된 v0.3 과제와 이 학생의 완료 여부")
    completed_at: dt.datetime | None = Field(description="개인: 본인 완료 시각")
    approved_at: dt.datetime | None
    approved_by_name: str | None
    rejected_reason: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ReviewerRecommendationRead(RecommendationRead):
    origin: dict[str, Any] = Field(description="생성 원본 (규칙 템플릿 또는 AI 응답, 변경 안 됨)")
    model_name: str | None
    prompt_version: str | None
    student: StudentRef | None


class GenerationResult(BaseModel):
    status: Literal["CREATED", "EXISTING", "QUEUED"]
    recommendations: list[ReviewerRecommendationRead]
    job: JobRead | None = Field(description="use_ai=true일 때 생성 작업 (폴링)")


Title200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text2000 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
Step = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class RecommendationUpdate(InputModel):
    version: int = Field(ge=1)
    title: Title200 | None = None
    description: Text2000 | None = None
    method_steps: list[Step] | None = Field(default=None, min_length=1, max_length=10)
    estimated_minutes: int | None = Field(default=None, ge=5, le=480)
    difficulty: Difficulty | None = None
    practical_type: PracticalType | None = None
    note: Reason | None = None


class RecommendationDecision(InputModel):
    version: int = Field(ge=1)
    note: Reason | None = None


class RecommendationReject(InputModel):
    version: int = Field(ge=1)
    reason: Reason


class RecommendationDistribute(InputModel):
    version: int = Field(ge=1)
    class_id: uuid.UUID | None = Field(
        default=None, description="배포할 반. 학생이 담당 반 1개에만 있으면 생략 가능"
    )
    due_at: AwareDatetime | None = None


class RecommendationCompletion(InputModel):
    version: int = Field(ge=1)
    completed: bool


class RecommendationHistoryRead(BaseModel):
    id: uuid.UUID
    action: RecommendationAction
    from_status: RecommendationStatus | None
    to_status: RecommendationStatus
    version: int
    actor_name: str | None
    actor_mode: ReviewMode | None
    changes: dict[str, Any] | None
    note: str | None
    created_at: dt.datetime
