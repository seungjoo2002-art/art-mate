"""v1.2 아카이브 분석 리포트·홈 오늘의 브리핑 응답 스키마.

- 단순 기록 수(`counts`)와 첨삭 근거 분석(반복 실수·강점·개선 추세)을 분리해 내려 보낸다.
- 분석 항목마다 근거 첨삭(`Evidence`: 항목 문장 + 원문 문장 + 작품·날짜)을 함께 준다.
- AI 설명문(`ai_narrative`)은 저장된 성장 리포트에서 읽기만 한다 (조회 때 LLM을 부르지 않음).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import FeedbackSource, FeedbackTag
from app.schemas.growth import Evidence

TagProgress = Literal["IMPROVING", "NEEDS_WORK", "CONSISTENT_STRENGTH", "INSUFFICIENT"]


class ArtworkRef(BaseModel):
    id: uuid.UUID
    title: str
    work_date: dt.date


class ThemeRead(BaseModel):
    code: str = Field(description="세부 주제 코드 (예: ELLIPSE)")
    label: str = Field(description="예: 타원·원통형 형태")
    artwork_count: int = Field(description="이 주제가 지적된 작품 수")
    evidence: list[Evidence]


class TagEvent(BaseModel):
    artwork_id: uuid.UUID
    work_date: dt.date
    polarity: Literal["NEG", "POS", "MIXED"] = Field(
        description="그 작품 첨삭에서 이 영역이 지적(NEG)·칭찬(POS)·둘 다(MIXED)"
    )


class TagInsight(BaseModel):
    tag: FeedbackTag
    label: str
    progress: TagProgress = Field(
        description="IMPROVING(지적 뒤 최근 긍정) / NEEDS_WORK(최근 지적) / "
        "CONSISTENT_STRENGTH(지적 없이 긍정 2작품+) / INSUFFICIENT(판단 보류)"
    )
    issue_artwork_count: int
    positive_artwork_count: int
    first_issue_date: dt.date | None
    last_issue_date: dt.date | None
    last_positive_date: dt.date | None
    positive_since_last_issue: int = Field(description="마지막 지적 뒤 긍정 첨삭 작품 수")
    improvement_confirmed: bool = Field(
        description="IMPROVING이고 지적 뒤 긍정이 2개 작품 이상 (1개면 초기 신호)"
    )
    themes: list[ThemeRead] = Field(description="반복된 세부 주제 (2개 작품 이상)")
    issue_evidence: list[Evidence] = Field(description="최근 지적 근거 (작품당 1개, 최대 3)")
    positive_evidence: list[Evidence] = Field(description="최근 긍정 근거 (작품당 1개, 최대 3)")
    practice_evidence: list[Evidence] = Field(description="수정 방법·연습 과제 근거")
    related_artworks: list[ArtworkRef] = Field(description="이 영역이 언급된 작품 (최신순)")
    events: list[TagEvent] = Field(description="작업일 순 사건 (추세 근거)")


class RecordCounts(BaseModel):
    """단순 기록 수 (AI 분석 아님)."""

    artwork_count: int
    completed_artwork_count: int
    mock_exam_count: int = Field(description="실기시험 모드(MOCK_EXAM) 작품 수")
    practice_artwork_count: int = Field(description="그 밖의 작품 수 (자유 연습·수업)")
    confirmed_feedback_count: int = Field(description="확정된 첨삭 (모든 출처)")
    instructor_feedback_count: int = Field(description="확정된 강사 첨삭 (분석 대상)")
    analyzed_artwork_count: int = Field(description="확정 강사 첨삭이 있는 작품 수")
    pending_review_count: int = Field(description="AI 정리가 끝나 확정을 기다리는 첨삭")
    processing_count: int = Field(description="음성 변환·AI 정리 진행 중인 작업")
    last_feedback_date: dt.date | None = Field(description="가장 최근 확정 첨삭 작품의 작업일")


class RecentFeedbackRead(BaseModel):
    feedback_id: uuid.UUID
    artwork_id: uuid.UUID
    artwork_title: str
    work_date: dt.date
    approved_at: dt.datetime
    source: FeedbackSource
    summary: str
    tags: list[FeedbackTag]


class AiNarrativeRead(BaseModel):
    """저장된 성장 리포트의 AI 설명문 (조회 때 새로 만들지 않음)."""

    status: Literal["READY", "STALE", "PENDING", "FAILED", "NOT_AVAILABLE", "NONE"] = Field(
        description="READY(현재 데이터 기준) / STALE(이전 데이터 기준, 갱신 전) / "
        "PENDING(갱신 중) / FAILED(갱신 실패) / NOT_AVAILABLE(AI 꺼짐·동의 없음·데이터 부족) / "
        "NONE(아직 없음)"
    )
    report_id: uuid.UUID | None = None
    overview: str | None = None
    strengths_comment: str | None = None
    improvement_comment: str | None = None
    based_on_current_data: bool = Field(
        default=False, description="false면 최신 첨삭이 반영되지 않은 이전 설명문"
    )
    generated_at: dt.datetime | None = None
    reason: str | None = Field(default=None, description="NOT_AVAILABLE·FAILED 사유 코드")


class AnalysisCriteria(BaseModel):
    required_artwork_count: int
    repeated_min_artworks: int
    strength_min_artworks: int
    theme_min_artworks: int
    improvement_rule: str


class AnalysisReport(BaseModel):
    status: Literal["NO_FEEDBACK", "NEEDS_CONFIRMATION", "INSUFFICIENT_DATA", "READY"]
    message: str | None
    generated_at: dt.datetime
    data_fingerprint: str = Field(description="분석에 쓴 데이터 지문 (같으면 결과도 같음)")
    insights_version: str
    counts: RecordCounts
    recent_feedbacks: list[RecentFeedbackRead] = Field(description="최근 확정 첨삭 요약 (5개)")
    repeated_mistakes: list[TagInsight]
    strengths: list[TagInsight]
    improving: list[TagInsight]
    needs_work: list[TagInsight]
    next_practice: list[Evidence] = Field(description="최근 첨삭의 다음 연습 과제·수정 방법")
    tags: list[TagInsight] = Field(description="언급된 모든 영역 (차트용)")
    ai_narrative: AiNarrativeRead
    criteria: AnalysisCriteria
    notes: list[str]


class BriefingFocus(BaseModel):
    tag: FeedbackTag
    label: str
    theme_label: str | None = Field(description="세부 주제가 있으면 (예: 타원·원통형 형태)")
    reason: Literal["REPEATED", "RECENT"]
    artwork_count: int


class BriefingHighlight(BaseModel):
    tag: FeedbackTag
    label: str
    kind: Literal["IMPROVING", "STRENGTH", "RECENT_POSITIVE"]
    artwork_count: int


class Briefing(BaseModel):
    status: Literal[
        "NO_RECORDS",
        "NO_FEEDBACK",
        "PROCESSING",
        "NEEDS_CONFIRMATION",
        "INSUFFICIENT_DATA",
        "READY",
    ]
    headline: str = Field(description="홈 카드 제목 문장")
    lines: list[str] = Field(description="headline 다음에 보여 줄 문장 (0~3개)")
    focus: BriefingFocus | None
    highlight: BriefingHighlight | None
    practice: Evidence | None = Field(
        description="오늘 연습할 실제 첨삭 문장 (수정 방법·연습 과제)"
    )
    evidence: list[Evidence] = Field(description="브리핑 문장의 근거 첨삭")
    counts: RecordCounts
    ai_comment: AiNarrativeRead
    data_fingerprint: str
    generated_at: dt.datetime
