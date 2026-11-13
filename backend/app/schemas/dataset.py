"""AI 첨삭 학습 데이터셋 (v0.9.8) 스키마."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import (
    AiAgeBand,
    ArtworkStage,
    ArtworkWorkCategory,
    FeedbackSource,
    FeedbackStatus,
    LabelOrigin,
    LabelVerification,
    PracticalType,
    WeaknessCategory,
)
from app.schemas.fields import InputModel


class DatasetConsentCreate(InputModel):
    policy_version: str = Field(min_length=1, max_length=20)
    agreed: Literal[True]
    birth_year_month: str = Field(
        pattern=r"^\d{4}-\d{2}$", description="YYYY-MM (연령 구간 계산에만 쓰고 저장하지 않음)"
    )


class DatasetConsentStatus(BaseModel):
    is_valid: bool
    required_version: str
    policy_version: str | None = None
    age_band: AiAgeBand | None = None
    granted_at: dt.datetime | None = None


# ------------------------------------------------------------------ 관리자: 통계·샘플


class DatasetStats(BaseModel):
    """학습 데이터 후보(피드백) 수와 제외 사유별 수. 한 피드백이 여러 사유에 해당할 수 있다."""

    candidates: int
    eligible: int
    excluded: dict[str, int]


class SampleImage(BaseModel):
    photo_id: uuid.UUID
    stage_id: uuid.UUID | None
    stage_name: str | None
    legacy_stage: ArtworkStage
    position: int
    uploaded_at: dt.datetime | None


class SampleTarget(BaseModel):
    priority: int
    university_name: str
    department: str | None


class SampleLabel(BaseModel):
    """구조화 레이블. origin·verification으로 AI 추정 / 전문가 확인을 구분 (원문과 분리)."""

    origin: LabelOrigin
    verification: LabelVerification
    problem_type: WeaknessCategory | None
    kind: str | None = Field(
        description="AI 요약 항목 종류 (STRENGTH/WEAKNESS/FIX/TIP), 전문가 레이블은 null"
    )
    target_object: str | None = None
    photo_id: uuid.UUID | None = None
    region: dict | None = None  # type: ignore[type-arg]
    description: str
    recommendation: str | None = None
    severity: int | None = None
    evidence_segment_ids: list[int]


class TrainingSample(BaseModel):
    """학습 샘플 1개 = 강사 피드백 1개 + 그 기준 이미지 (가명 처리)."""

    sample_id: uuid.UUID = Field(description="피드백(녹음·글 첨삭) id")
    feedback_type: Literal["RECORDING", "NOTE"]
    learner: str = Field(description="학생 가명 (HMAC)")
    artwork_id: uuid.UUID
    images: list[SampleImage] = Field(description="피드백 기준 이미지 (확인됨)")
    feedback_stage: str | None = Field(description="피드백 단계 이름 (null = 작품 전체)")
    practical_type: PracticalType | None
    work_category: ArtworkWorkCategory | None
    topic: str | None
    exam_materials: str | None
    target_universities: list[SampleTarget]
    source: FeedbackSource
    raw_text: str | None = Field(description="글 첨삭 원문")
    transcript: str | None = Field(description="STT 전사 원문 (사용자가 고친 최신본)")
    transcript_edited: bool | None
    ai_summary: str | None
    ai_summary_status: FeedbackStatus | None
    expert_verified: bool = Field(description="강사가 AI 요약을 확정함 (학원 작품의 강사 검토)")
    labels: list[SampleLabel]
    feedback_created_at: dt.datetime
    consent_version: str
    consent_age_band: AiAgeBand
