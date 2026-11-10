"""AI 첨삭 기록 (v0.6): 외부 AI 전송 동의, 처리 작업 큐, 전사, 첨삭(요약·항목·카테고리), 검토 이력.

데이터 흐름
    feedback_recordings ─(TRANSCRIBE 작업, 서버 내부 faster-whisper)→ feedback_transcripts
    feedback_transcripts ─(SUMMARIZE 작업, Gemini 외부 전송 · 별도 동의 필요)→ feedback_summaries
    feedback_summaries ─ feedback_items(잘한 점·부족한 점·수정 방법·다음 주의점, 근거 구간)
                       ─ feedback_categories(약점 카테고리, 정규화)
                       ─ feedback_review_history(생성·수정·승인 이력, append-only)

원칙
- AI 원본과 사람이 확정한 결과를 분리한다: `feedback_summaries.ai_output`(불변 JSON)은 AI 응답 원본,
  `summary`·items·categories는 검토자가 수정하는 현재 값,
  승인 시점 스냅샷은 review_history에 남는다.
- 전사·첨삭 결과는 작업 성공 시에만 생성되고 이후 바뀌지 않는다(전사) / 검토로만 바뀐다(첨삭).
  처리 상태·재시도·오류는 `ai_processing_jobs`에 둔다.
- 녹음·작품·사용자 FK는 ON DELETE CASCADE. 녹음은 소프트 삭제되므로 서비스가 파생 데이터를 직접
  삭제한다 (app/services/ai_feedback.py `purge_for_recordings`).
- 모든 테이블 RLS 활성화(정책 없음): PostgREST 직접 접근 차단, 백엔드만 접근.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
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
    WeaknessCategory,
)


class AiProcessingConsent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """외부 AI 서비스로 전사문을 보내는 것에 대한 동의 (녹음 동의와 별개, 버전별·철회 가능)."""

    __tablename__ = "ai_processing_consents"
    __table_args__ = (
        # v0.7: 목적별 유효 동의 1개 (0007에서 purpose 추가)
        Index(
            "uq_ai_processing_consents_active",
            "user_id",
            "provider",
            "purpose",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_ai_processing_consents_user_granted", "user_id", "granted_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    provider: Mapped[AiProvider] = mapped_column(enum_column(AiProvider, "provider"))
    purpose: Mapped[AiConsentPurpose] = mapped_column(
        enum_column(AiConsentPurpose, "purpose"),
        server_default=AiConsentPurpose.FEEDBACK_SUMMARY.value,
        default=AiConsentPurpose.FEEDBACK_SUMMARY,
    )
    policy_version: Mapped[str] = mapped_column(String(20))
    granted_by: Mapped[ConsentGrantor] = mapped_column(enum_column(ConsentGrantor, "granted_by"))
    granted_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class AiProcessingJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """DB 기반 작업 큐 1건. Worker가 `FOR UPDATE SKIP LOCKED`로 가져가 lease를 잡고 처리한다."""

    __tablename__ = "ai_processing_jobs"
    __table_args__ = (
        # 같은 녹음·같은 종류의 진행 중 작업은 1개 (중복 요청 방지)
        Index(
            "uq_ai_processing_jobs_active",
            "recording_id",
            "job_type",
            unique=True,
            postgresql_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
        Index(
            "ix_ai_processing_jobs_queue",
            "run_after",
            postgresql_where=text("status = 'QUEUED'"),
        ),
        Index(
            "ix_ai_processing_jobs_lease",
            "lease_expires_at",
            postgresql_where=text("status = 'RUNNING'"),
        ),
        Index("ix_ai_processing_jobs_recording", "recording_id", "job_type", "created_at"),
        # v0.7: 녹음이 없는 작업(성장 리포트·추천)의 중복 방지
        Index(
            "uq_ai_processing_jobs_active_dedupe",
            "job_type",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('QUEUED', 'RUNNING') AND dedupe_key IS NOT NULL"),
        ),
        CheckConstraint(
            "job_type NOT IN ('TRANSCRIBE', 'SUMMARIZE')"
            " OR (recording_id IS NOT NULL AND artwork_id IS NOT NULL)",
            name="recording_job_has_recording",
        ),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts", name="attempts_range"),
        CheckConstraint(
            "status <> 'RUNNING' OR (lease_expires_at IS NOT NULL AND locked_by IS NOT NULL)",
            name="running_has_lease",
        ),
    )

    job_type: Mapped[AiJobType] = mapped_column(enum_column(AiJobType, "job_type"))
    status: Mapped[AiJobStatus] = mapped_column(
        enum_column(AiJobStatus, "status"), default=AiJobStatus.QUEUED
    )
    # TRANSCRIBE/SUMMARIZE는 필수, v0.7 성장 작업은 NULL
    recording_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feedback_recordings.id", ondelete="CASCADE")
    )
    artwork_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artworks.id", ondelete="CASCADE")
    )
    # v0.7 GROWTH_REPORT 작업의 대상 리포트
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("growth_reports.id", ondelete="CASCADE")
    )
    # v0.7 중복 방지 키 (녹음이 없는 작업)
    dedupe_key: Mapped[str | None] = mapped_column(String(100))
    # 녹음·분석 대상 학생 (동의 확인 대상)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    run_after: Mapped[datetime]
    locked_by: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    # 오류 코드와 안전한 메시지만 저장 (전사문·음성·키·URL을 넣지 않는다)
    last_error_code: Mapped[str | None] = mapped_column(String(50))
    last_error_message: Mapped[str | None] = mapped_column(String(500))
    # TRANSCRIBE 전용: 요청한 사용자 토큰으로 발급한 음성 Signed URL. API 응답·로그에 내보내지 않고
    # 작업이 끝나면 지운다. 만료되면 사용자가 재시도를 요청해 새로 발급한다 (service_role 미사용)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_url_expires_at: Mapped[datetime | None]
    # 작업 입력값: {"transcript_id": ..., "chain_summary": bool}
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    # 비용 추적: 외부 API 호출 수와 토큰 (모든 시도 누적)
    api_call_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)


class FeedbackTranscript(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """STT 결과 (불변). 재전사하면 새 행이 생기고, 최신 행이 현재 전사다."""

    __tablename__ = "feedback_transcripts"
    __table_args__ = (Index("ix_feedback_transcripts_recording", "recording_id", "created_at"),)

    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback_recordings.id", ondelete="CASCADE")
    )
    artwork_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artworks.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_processing_jobs.id", ondelete="SET NULL")
    )
    language: Mapped[str] = mapped_column(String(10))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # [{"index": 0, "start_ms": 0, "end_ms": 4200, "text": "..."}] — index가 근거 연결 키
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    segment_count: Mapped[int] = mapped_column(Integer)
    engine: Mapped[str] = mapped_column(String(30))
    model_name: Mapped[str] = mapped_column(String(200))
    processing_ms: Mapped[int | None] = mapped_column(Integer)


class FeedbackSummary(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """첨삭 1건 (녹음 1개 기준). AI 초안으로 생성되고 검토자가 수정·승인한다."""

    __tablename__ = "feedback_summaries"
    __table_args__ = (
        # 녹음당 '현재' 첨삭(초안·검토 중·승인)은 1개
        Index(
            "uq_feedback_summaries_current",
            "recording_id",
            unique=True,
            postgresql_where=text("status IN ('DRAFT', 'IN_REVIEW', 'APPROVED')"),
        ),
        Index("ix_feedback_summaries_artwork_status", "artwork_id", "status"),
        Index("ix_feedback_summaries_owner_approved", "owner_id", "status", "approved_at"),
        CheckConstraint(
            "(status = 'APPROVED') = (approved_at IS NOT NULL)", name="approved_has_time"
        ),
        CheckConstraint("version >= 1", name="version_positive"),
    )

    recording_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback_recordings.id", ondelete="CASCADE")
    )
    artwork_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artworks.id", ondelete="CASCADE"))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback_transcripts.id", ondelete="CASCADE")
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_processing_jobs.id", ondelete="SET NULL")
    )
    status: Mapped[FeedbackStatus] = mapped_column(
        enum_column(FeedbackStatus, "status"), default=FeedbackStatus.DRAFT
    )
    # 생성 시점 기준. 실제 권한은 매 요청마다 작품의 현재 학원 연결로 다시 판단한다
    review_mode: Mapped[ReviewMode] = mapped_column(enum_column(ReviewMode, "review_mode"))
    # 낙관적 잠금: 수정할 때마다 +1, 클라이언트가 보낸 version과 다르면 409
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    # 현재(검토자가 수정한) 전체 요약
    summary: Mapped[str] = mapped_column(Text)
    # AI 응답 원본 (검증 통과한 JSON, 이후 변경하지 않음)
    ai_output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    # 근거 구간이 없어 버린 AI 항목 수 (환각 방지 지표)
    dropped_item_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None]
    # 강사 승인일 때 승인자의 학원 소속 (학원 단위 감사용)
    approver_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )
    rejected_reason: Mapped[str | None] = mapped_column(String(500))


class FeedbackItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """첨삭 항목 1개 (잘한 점·부족한 점·수정 방법·다음 주의점). 근거 전사 구간을 가리킨다."""

    __tablename__ = "feedback_items"
    __table_args__ = (
        Index("ix_feedback_items_summary", "summary_id", "kind", "position"),
        # v0.7 반복 약점 분석: 카테고리별 항목 집계
        Index(
            "ix_feedback_items_category",
            "category",
            postgresql_where=text("category IS NOT NULL"),
        ),
        CheckConstraint("length(btrim(content)) > 0", name="content_not_blank"),
    )

    summary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback_summaries.id", ondelete="CASCADE")
    )
    kind: Mapped[FeedbackItemKind] = mapped_column(enum_column(FeedbackItemKind, "kind"))
    position: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(String(1000))
    category: Mapped[WeaknessCategory | None] = mapped_column(
        enum_column(WeaknessCategory, "category")
    )
    # feedback_transcripts.segments[].index (근거 구간). 사람이 추가한 항목은 빈 배열일 수 있다
    evidence_segment_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'::integer[]"), default=list
    )
    origin: Mapped[FeedbackItemOrigin] = mapped_column(enum_column(FeedbackItemOrigin, "origin"))


class FeedbackCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """첨삭 1건의 약점 카테고리 (여러 개). v0.7 성장 분석의 정규화된 집계 단위."""

    __tablename__ = "feedback_categories"
    __table_args__ = (
        UniqueConstraint("summary_id", "category"),
        Index("ix_feedback_categories_category", "category"),
    )

    summary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback_summaries.id", ondelete="CASCADE")
    )
    category: Mapped[WeaknessCategory] = mapped_column(enum_column(WeaknessCategory, "category"))
    origin: Mapped[FeedbackItemOrigin] = mapped_column(enum_column(FeedbackItemOrigin, "origin"))


class FeedbackReviewHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """첨삭 생성·수정·승인·반려 이력 (append-only). changes에 변경 전후 스냅샷."""

    __tablename__ = "feedback_review_history"
    __table_args__ = (Index("ix_feedback_review_history_summary", "summary_id", "created_at"),)

    summary_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feedback_summaries.id", ondelete="CASCADE")
    )
    # NULL = 시스템(Worker) 또는 탈퇴한 사용자
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    actor_mode: Mapped[ReviewMode | None] = mapped_column(enum_column(ReviewMode, "actor_mode"))
    action: Mapped[ReviewAction] = mapped_column(enum_column(ReviewAction, "action"))
    from_status: Mapped[FeedbackStatus | None] = mapped_column(
        enum_column(FeedbackStatus, "from_status")
    )
    to_status: Mapped[FeedbackStatus] = mapped_column(enum_column(FeedbackStatus, "to_status"))
    version: Mapped[int] = mapped_column(Integer)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(String(500))
