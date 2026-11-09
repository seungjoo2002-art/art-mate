"""AI 첨삭 기록 API 요청·응답 (v0.6)."""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.models.enums import (
    AiConsentPurpose,
    AiJobStatus,
    AiJobType,
    AiProvider,
    ConsentGrantor,
    FeedbackItemKind,
    FeedbackItemOrigin,
    FeedbackStatus,
    ReviewAction,
    ReviewMode,
    TranscriptionStatus,
    WeaknessCategory,
)
from app.schemas.fields import InputModel
from app.schemas.students import StudentRef

# ----------------------------------------------------------------------------- consent


class AiConsentCreate(InputModel):
    purpose: AiConsentPurpose = Field(
        default=AiConsentPurpose.FEEDBACK_SUMMARY,
        description="FEEDBACK_SUMMARY(첨삭 요약, v0.6) / "
        "GROWTH_COACHING(성장 분석·맞춤 과제, v0.7)",
    )
    policy_version: str = Field(
        min_length=1,
        max_length=20,
        description="GET /ai-processing-consents/me 의 required_version",
    )
    agreed: Literal[True] = Field(
        description="전사문의 외부 AI(Gemini) 전송에 동의함 (true만 허용)"
    )
    granted_by: ConsentGrantor = Field(
        default=ConsentGrantor.SELF, description="만 14세 미만은 GUARDIAN (법정대리인 동의)"
    )


class AiConsentRead(BaseModel):
    id: uuid.UUID
    provider: AiProvider
    purpose: AiConsentPurpose
    policy_version: str
    granted_by: ConsentGrantor
    granted_at: dt.datetime
    revoked_at: dt.datetime | None


class AiConsentStatus(BaseModel):
    provider: AiProvider
    purpose: AiConsentPurpose
    required_version: str
    is_valid: bool = Field(description="현재 버전에 유효한 동의가 있음 → AI 요약 요청 가능")
    consent: AiConsentRead | None


# ----------------------------------------------------------------------------- jobs


class TranscriptionRequest(InputModel):
    auto_summarize: bool = Field(
        default=False,
        description="전사가 끝나면 AI 요약을 자동으로 요청 "
        "(그 시점에 학생의 AI 전송 동의가 있어야 함)",
    )


class JobRead(BaseModel):
    """처리 작업 상태. 내부 Signed URL·오류 상세는 내보내지 않는다."""

    id: uuid.UUID
    job_type: AiJobType
    status: AiJobStatus
    attempts: int
    max_attempts: int
    next_attempt_at: dt.datetime | None = Field(description="QUEUED일 때 다음 실행 예정 시각")
    error_code: str | None = Field(description="마지막 실패 코드 (재시도 중이어도 남아 있음)")
    retryable: bool = Field(description="FAILED/CANCELLED → 재시도 API 사용 가능")
    created_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None


class TranscriptMeta(BaseModel):
    id: uuid.UUID
    language: str
    duration_ms: int | None
    segment_count: int
    engine: str
    model_name: str
    created_at: dt.datetime


class TranscriptionStatusRead(BaseModel):
    recording_id: uuid.UUID
    transcription_status: TranscriptionStatus
    job: JobRead | None = Field(description="가장 최근 전사 작업")
    transcript: TranscriptMeta | None = Field(description="완료된 최신 전사 (원문은 /transcript)")


class Segment(BaseModel):
    index: int
    start_ms: int
    end_ms: int
    text: str


class TranscriptRead(TranscriptMeta):
    recording_id: uuid.UUID
    text: str
    segments: list[Segment]


class SummaryStatusRead(BaseModel):
    recording_id: uuid.UUID
    job: JobRead | None = Field(description="가장 최근 요약 작업")
    feedback_id: uuid.UUID | None = Field(description="현재 첨삭 (DRAFT/IN_REVIEW/APPROVED)")
    feedback_status: FeedbackStatus | None
    review_mode: ReviewMode | None = Field(
        description="INSTRUCTOR: 담당 강사가 확정, SELF: 학생 본인이 확정 (학원 미연결 작품)"
    )


# ----------------------------------------------------------------------------- feedback


class Evidence(BaseModel):
    index: int
    start_ms: int
    end_ms: int


class FeedbackItemRead(BaseModel):
    id: uuid.UUID
    kind: FeedbackItemKind
    position: int
    content: str
    category: WeaknessCategory | None
    evidence: list[Evidence] = Field(description="근거 전사 구간 (재생 위치 이동용)")
    origin: FeedbackItemOrigin


class FeedbackRead(BaseModel):
    id: uuid.UUID
    recording_id: uuid.UUID
    artwork_id: uuid.UUID
    status: FeedbackStatus
    review_mode: ReviewMode
    version: int = Field(description="수정·승인 요청에 그대로 보낸다 (동시 수정 감지)")
    summary: str
    strengths: list[FeedbackItemRead]
    weaknesses: list[FeedbackItemRead]
    fixes: list[FeedbackItemRead]
    next_tips: list[FeedbackItemRead]
    categories: list[WeaknessCategory] = Field(description="약점 카테고리")
    approved_at: dt.datetime | None
    approved_by_name: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ReviewerFeedbackRead(FeedbackRead):
    """검토자(담당 강사, 개인 작품의 학생 본인)용: AI 원본과 처리 정보 포함."""

    ai_draft: dict[str, Any] = Field(description="AI 응답 원본 (검증 통과본, 변경되지 않음)")
    model_name: str
    prompt_version: str
    dropped_item_count: int = Field(description="근거가 없어 저장하지 않은 AI 항목 수")
    rejected_reason: str | None
    artwork_title: str
    student: StudentRef | None = Field(description="강사 화면일 때 학생 정보")


class ReviewQueueItem(BaseModel):
    id: uuid.UUID
    recording_id: uuid.UUID
    artwork_id: uuid.UUID
    artwork_title: str
    recording_title: str | None
    status: FeedbackStatus
    version: int
    summary: str
    categories: list[WeaknessCategory]
    student: StudentRef
    created_at: dt.datetime
    updated_at: dt.datetime


ContentText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]
SummaryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
ReasonText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class FeedbackItemInput(InputModel):
    id: uuid.UUID | None = Field(
        default=None, description="기존 항목 수정이면 id, 새 항목이면 생략"
    )
    kind: FeedbackItemKind
    content: ContentText
    category: WeaknessCategory | None = None
    evidence_segment_ids: list[int] | None = Field(
        default=None,
        max_length=20,
        description="근거 구간 번호. 생략하면 기존 항목의 근거 유지(새 항목은 빈 배열)",
    )


class FeedbackUpdate(InputModel):
    """첨삭 전체 교체 (보낸 목록이 최종 상태). 빠진 기존 항목은 삭제된다."""

    version: int = Field(ge=1, description="조회한 version (다르면 409 FEEDBACK_VERSION_CONFLICT)")
    summary: SummaryText
    items: list[FeedbackItemInput] = Field(max_length=60)
    categories: list[WeaknessCategory] = Field(max_length=10)
    note: ReasonText | None = Field(default=None, description="수정 메모 (이력에 기록)")

    @model_validator(mode="after")
    def _unique(self) -> "FeedbackUpdate":
        ids = [i.id for i in self.items if i.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate item id")
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("duplicate category")
        return self


class FeedbackDecision(InputModel):
    version: int = Field(ge=1)
    note: ReasonText | None = None


class FeedbackReject(InputModel):
    version: int = Field(ge=1)
    reason: ReasonText


class ReviewHistoryRead(BaseModel):
    id: uuid.UUID
    action: ReviewAction
    from_status: FeedbackStatus | None
    to_status: FeedbackStatus
    version: int
    actor_name: str | None = Field(description="NULL = 시스템(AI 처리) 또는 탈퇴한 사용자")
    actor_mode: ReviewMode | None
    changes: dict[str, Any] | None = Field(description="변경 전후 (before/after)")
    note: str | None
    created_at: dt.datetime
