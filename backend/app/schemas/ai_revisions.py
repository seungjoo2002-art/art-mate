"""AI 시각적 첨삭 (v1.3) 요청·응답 스키마."""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import AiRevisionStatus, FeedbackItemKind, WeaknessCategory


class ImprovementSource(BaseModel):
    feedback_type: Literal["RECORDING", "NOTE"]
    feedback_id: uuid.UUID
    item_id: uuid.UUID


class Improvement(BaseModel):
    key: str = Field(description="개선사항 식별 키 (생성 요청의 selected_keys에 사용)")
    category: WeaknessCategory
    category_label: str
    kind: FeedbackItemKind = Field(description="WEAKNESS(부족한 점) 또는 FIX(수정 방법)")
    kind_label: str
    text: str = Field(description="기존 AI 첨삭 정리 항목 문장 (중복은 하나로 합침)")
    sources: list[ImprovementSource] = Field(description="이 개선사항이 나온 피드백·항목")


class RevisionQuota(BaseModel):
    daily_used: int
    daily_limit: int = Field(description="0 = 제한 없음")
    monthly_used: int
    monthly_limit: int = Field(description="0 = 제한 없음")
    can_create: bool = Field(description="개인·서비스 한도 기준으로 지금 새로 만들 수 있음")
    blocked_scope: Literal["DAILY", "MONTHLY", "SERVICE"] | None = None


class RevisionTimings(BaseModel):
    queue_wait_ms: int | None = Field(description="요청 → Worker 시작")
    generation_ms: int | None = Field(description="이미지 수정 API 호출 시간")
    storage_ms: int | None = Field(description="Storage 업로드 자체 소요")
    total_ms: int | None = Field(description="요청 → 완성 이미지를 처음 화면에 보냄")


class SourcePhotoRef(BaseModel):
    photo_id: uuid.UUID
    photo_status: str = Field(description="원본 사진 행 상태 (ACTIVE / DELETED)")
    replaced: bool = Field(description="이 원본 사진이 교체됨 (교체 전 사진의 수정본)")
    current_photo_id: uuid.UUID | None = Field(description="교체됐다면 지금 그 자리의 사진")


class AiRevisionRead(BaseModel):
    id: uuid.UUID
    artwork_id: uuid.UUID
    stage_id: uuid.UUID
    photo_id: uuid.UUID
    version: int
    status: AiRevisionStatus
    is_ai_generated: Literal[True] = Field(
        default=True, description="항상 true: 학생이 그린 작품이 아닌 AI 학습용 참고 이미지"
    )
    improvements: list[Improvement] = Field(description="생성 당시 보낸 개선사항 스냅샷")
    candidate_count: int = Field(description="생성 당시 후보 개선사항 수")
    provider: str
    model_name: str
    quality: str | None
    url: str | None = Field(description="완성 이미지 Signed URL (완성 전·실패면 null)")
    url_expires_at: dt.datetime | None
    width: int | None
    height: int | None
    source_photo: SourcePhotoRef
    error_code: str | None
    retryable: bool = Field(description="실패해 다시 시도할 수 있음 (새 버전, 한도 차감)")
    timings: RevisionTimings
    created_at: dt.datetime
    finished_at: dt.datetime | None
    stored_at: dt.datetime | None


class RevisionCandidates(BaseModel):
    """단계별 피드백 화면: 지금 사진의 개선사항과 생성 가능 여부."""

    photo_id: uuid.UUID
    stage_id: uuid.UUID
    feature_status: Literal["ENABLED", "DISABLED", "UNCONFIRMED"] = Field(
        description="ENABLED 사용 가능 / DISABLED 꺼짐 / UNCONFIRMED 운영자 확인 전"
    )
    consent_valid: bool
    consent_reason: str | None
    consent_required_version: str
    feedback_count: int = Field(description="이 사진에 연결된 피드백 수")
    unsummarized_count: int = Field(description="그중 AI 첨삭 정리가 없는 피드백 수")
    candidates: list[Improvement]
    quota: RevisionQuota
    revision_count: int = Field(description="이 사진의 수정본 수 (삭제 제외, 진행 중 포함)")
    latest: AiRevisionRead | None = Field(description="이 사진의 가장 최근 수정본 (진행 중 포함)")


class AiRevisionCreate(BaseModel):
    selected_keys: list[str] = Field(
        min_length=1, max_length=20, description="반영할 개선사항 key (candidates[].key)"
    )


class StageRevisionCount(BaseModel):
    stage_id: uuid.UUID
    count: int = Field(description="완성된 수정본 수 (저장 대기 포함, 삭제·실패 제외)")
    in_progress: int = Field(description="생성 대기·중인 수정본 수")


class ArtworkRevisionSummary(BaseModel):
    artwork_id: uuid.UUID
    stages: list[StageRevisionCount]


class ReplacedPhoto(BaseModel):
    photo_id: uuid.UUID = Field(description="교체 전 원본 사진 행")
    current_photo_id: uuid.UUID = Field(description="지금 그 자리의 사진")
    uploaded_at: dt.datetime | None


class StageRevisions(BaseModel):
    """AI 수정본 화면: 단계의 수정본 전부 (최신 먼저). 사진별 묶음은 photo_id로."""

    artwork_id: uuid.UUID
    stage_id: uuid.UUID
    revisions: list[AiRevisionRead]
    replaced_photos: list[ReplacedPhoto] = Field(
        description="수정본이 있는 교체 전 원본 사진 (지금 사진의 과거 수정 이력으로 표시)"
    )


class RevisionUsage(BaseModel):
    """운영 확인용 사용량 (관리자)."""

    period_start: dt.datetime
    requests: int
    succeeded: int
    failed: int
    in_progress: int
    reused_requests_note: str = "재사용 요청은 행을 만들지 않으므로 여기 포함되지 않는다"
    api_calls: int
    input_tokens: int
    input_image_tokens: int
    output_tokens: int
    estimated_cost_usd: Decimal
    users: int
    staged_results: int = Field(description="Storage 저장 대기 중인 결과 수 (DB 임시 보관)")
    staged_bytes: int
    avg_generation_ms: int | None
    avg_queue_wait_ms: int | None
