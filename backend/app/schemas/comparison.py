"""v1.1 → v1.2 원본 제시물 ↔ 학생 작품 AI 비교 첨삭 데이터 구조.

- `ComparisonInput`: v1.1에서 실제로 만든다 (저장된 작품 데이터만, AI 호출 없음).
- `ComparisonResult*`: v1.2에서 AI(Claude Vision) 출력 검증에 쓸 **설계 스키마**.
  v1.1은 결과를 만들지 않는다 (가짜 결과·점수 생성 금지).
  설계 설명: docs/ai-comparison-v1.2-design.md
"""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    ExpressionMethod,
    PracticalType,
)

COMPARISON_INPUT_VERSION = "comparison-input-v1"

# 학생이 의도를 쓰지 않았을 때 v1.2 AI에 함께 보내는 규칙 (의도를 추정·확정하지 않는다)
INTENT_NOT_PROVIDED_RULE = (
    "학생이 표현 의도를 입력하지 않았다. 원본과 다른 점을 의도된 변형으로 단정하거나 형태 오류로 "
    "단정하지 말고, 판단이 갈리면 '추가 확인이 필요한 사항'으로 남긴다."
)
INTENT_PROVIDED_RULE = (
    "학생이 밝힌 표현 방식·의도와 일치하는 변형은 형태 오류로 판단하지 않는다. 의도가 화면에서 "
    "충분히 전달되는지는 평가할 수 있다."
)


class ComparisonImageRef(BaseModel):
    """이미지 참조 (경로·URL 대신 id. v1.2 Worker가 소유자 권한으로 내려받는다)."""

    photo_id: uuid.UUID
    role: Literal["REFERENCE", "ARTWORK"]
    width: int | None
    height: int | None
    uploaded_at: dt.datetime | None
    is_representative: bool = Field(default=False, description="ARTWORK: 단계 대표 사진")


class ComparisonStage(BaseModel):
    stage_id: uuid.UUID
    name: str
    position: int
    photos: list[ComparisonImageRef] = Field(description="이 단계의 학생 작품 사진 (올린 순서)")


class ComparisonExam(BaseModel):
    topic: str | None = Field(description="실기 주제")
    practical_type: PracticalType | None
    work_category: ArtworkWorkCategory | None
    exam_materials: str | None = Field(description="제시물 설명")
    time_limit_minutes: int | None = Field(description="시험 시간 (분)")
    paper_size: str | None = Field(description="화지 규격")
    exam_conditions: str | None = Field(description="추가 시험 조건")
    memo: str | None = Field(description="자유 메모 (작품 설명)")


class ComparisonIntent(BaseModel):
    status: Literal["PROVIDED", "NOT_PROVIDED"] = Field(
        description=(
            "학생이 표현 방식·의도 중 하나라도 입력했는지. NOT_PROVIDED면 의도를 추정하지 않는다"
        )
    )
    methods: list[ExpressionMethod]
    method_labels: list[str]
    text: str | None
    rule: str = Field(description="v1.2 AI에 함께 보내는 해석 규칙")


class ComparisonReadiness(BaseModel):
    ready: bool = Field(description="원본 사진 1장 이상 + 학생 작품 사진 1장 이상")
    missing: list[Literal["REFERENCE_PHOTO", "ARTWORK_PHOTO"]]


class ComparisonInput(BaseModel):
    """v1.2 AI 비교 첨삭 입력 (v1.1에서 저장된 데이터로만 구성, 강사 첨삭 없이도 만들어진다)."""

    schema_version: Literal["comparison-input-v1"] = COMPARISON_INPUT_VERSION
    artwork_id: uuid.UUID
    title: str
    work_date: dt.date
    work_status: ArtworkWorkStatus
    exam: ComparisonExam
    intent: ComparisonIntent
    references: list[ComparisonImageRef] = Field(description="원본 제시물 사진 (모든 단계 공통)")
    stages: list[ComparisonStage] = Field(description="작품 단계 순서대로")
    readiness: ComparisonReadiness


# ============================================================================ v1.2 출력 설계
# (v1.1에서는 응답·저장하지 않는다. v1.2 Structured Outputs 스키마의 기준)

ComparisonAspect = Literal[
    "COMPOSITION", "FORM", "PROPORTION", "VALUE", "COLOR", "TEXTURE", "PERSPECTIVE", "FINISH"
]


class ComparisonEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_id: uuid.UUID = Field(description="입력에 있던 이미지 id만")
    role: Literal["REFERENCE", "ARTWORK"]
    region: str | None = Field(description="이미지 안의 위치 설명 (예: 왼쪽 아래 사과)")


class ComparisonFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    aspect: ComparisonAspect
    observation: str = Field(description="관찰된 특징 (원본과 작품의 차이·공통점)")
    kind: Literal["STRENGTH", "IMPROVEMENT_CANDIDATE", "NEUTRAL"] = Field(
        description="잘한 점 / 개선 후보 / 판단 보류"
    )
    rationale: str = Field(description="판단 근거")
    suggestion: str | None = Field(description="구체적인 수정 방법 (개선 후보일 때)")
    related_intent: bool = Field(description="학생이 밝힌 표현 의도와 관련된 변형인지")
    uncertainty: Literal["LOW", "MEDIUM", "HIGH"] = Field(description="판단 불확실성")
    evidence: list[ComparisonEvidence] = Field(min_length=1)


class ComparisonResultDraft(BaseModel):
    """v1.2 AI 출력 설계 (항목 8개 기준). 점수·등급 필드는 두지 않는다."""

    model_config = ConfigDict(extra="forbid")

    input_version: Literal["comparison-input-v1"]
    stage_id: uuid.UUID | None = Field(description="분석한 단계 (null = 작품 전체)")
    findings: list[ComparisonFinding]
    needs_confirmation: list[str] = Field(description="추가 확인이 필요한 사항 (학생에게 묻기)")
    image_quality_notes: list[str] = Field(description="촬영 상태 때문에 판단이 어려운 점")
