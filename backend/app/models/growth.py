"""성장 코치 (v0.7): 성장 리포트, 맞춤 연습 과제 추천과 그 검토 이력.

원칙
- 약점 분석은 규칙 기반 통계로 매번 계산한다 (승인된 첨삭의 feedback_categories).
  별도 스냅샷 테이블을 두지 않고, 리포트를 만들 때
  그 시점의 통계를 `growth_reports.metrics`에 저장한다.
- 리포트 = 통계(`metrics`, 데이터로 계산) + AI 설명문(`narrative`, 선택). 둘은 분리 저장·표시한다.
- 근거는 ID로만 저장하고(`source_feedback_ids`, 추천의 `evidence_item_ids`) 문장은 조회할 때 현재
  테이블에서 다시 읽는다 → 녹음·첨삭이 삭제되면 근거 문장도 보이지 않는다.
- 추천 과제: AI(또는 규칙) 원본 `origin_output`과 검토자가 수정한 현재 값을 분리한다. 학원 작품
  추천은 강사가 승인한 뒤 기존 v0.3 과제(tasks/task_assignments)로 배포한다 (과제 시스템 재사용).
  학원 미연결 개인 작품 추천은 학생 본인이 채택·완료 기록한다.
- 모든 테이블 RLS 활성화 (정책 없음, 백엔드만 접근).
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
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
    Difficulty,
    GrowthScope,
    NarrativeStatus,
    PracticalType,
    RecommendationAction,
    RecommendationSource,
    RecommendationStatus,
    ReportPeriod,
    ReportStatus,
    ReviewMode,
    WeaknessCategory,
)

_SCOPE_CHECK = "(scope = 'ACADEMY') = (academy_id IS NOT NULL)"


class GrowthReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """학생 1명 · 범위 · 기간의 성장 리포트 (생성 시점 통계 스냅샷 + 선택적 AI 설명문)."""

    __tablename__ = "growth_reports"
    __table_args__ = (
        CheckConstraint(_SCOPE_CHECK, name="scope_academy"),
        CheckConstraint("period_start IS NULL OR period_start <= period_end", name="period_order"),
        # 같은 범위·기간·같은 데이터로 만든 리포트는 1개 (중복 생성 방지)
        Index("uq_growth_reports_dedupe", "owner_id", "dedupe_key", unique=True),
        Index("ix_growth_reports_owner_created", "owner_id", "created_at"),
        Index("ix_growth_reports_academy_created", "academy_id", "created_at"),
        # 근거 첨삭이 삭제될 때 관련 리포트를 찾기 위한 GIN
        Index(
            "ix_growth_reports_source_feedback",
            "source_feedback_ids",
            postgresql_using="gin",
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    scope: Mapped[GrowthScope] = mapped_column(enum_column(GrowthScope, "scope"))
    academy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academies.id", ondelete="CASCADE")
    )
    period_type: Mapped[ReportPeriod] = mapped_column(enum_column(ReportPeriod, "period_type"))
    # NULL = 처음부터 (ALL)
    period_start: Mapped[date | None]
    period_end: Mapped[date]
    status: Mapped[ReportStatus] = mapped_column(enum_column(ReportStatus, "status"))
    # 규칙 기반 통계 (app/services/growth_analytics.py). 근거는 ID만
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # 사용한 승인 첨삭 ID와 데이터 지문 (변경 감지·삭제 시 무효화)
    source_feedback_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(36)), server_default=text("'{}'::varchar[]"), default=list
    )
    data_fingerprint: Mapped[str] = mapped_column(String(64))
    dedupe_key: Mapped[str] = mapped_column(String(64))
    analysis_version: Mapped[str] = mapped_column(String(30))
    # AI 설명문 (통계와 별개, 선택)
    narrative_status: Mapped[NarrativeStatus] = mapped_column(
        enum_column(NarrativeStatus, "narrative_status")
    )
    narrative: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    narrative_error_code: Mapped[str | None] = mapped_column(String(50))
    model_name: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )


class PracticeRecommendation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """맞춤 연습 과제 추천 1건 (약점 카테고리 1개 기준)."""

    __tablename__ = "practice_recommendations"
    __table_args__ = (
        CheckConstraint(_SCOPE_CHECK, name="scope_academy"),
        CheckConstraint("scope <> 'ALL'", name="scope_not_all"),
        CheckConstraint(
            "(scope = 'ACADEMY') = (student_membership_id IS NOT NULL)",
            name="academy_has_student",
        ),
        CheckConstraint("estimated_minutes BETWEEN 5 AND 480", name="minutes_range"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("status <> 'DISTRIBUTED' OR task_id IS NOT NULL", name="distributed_task"),
        CheckConstraint("status <> 'COMPLETED' OR completed_at IS NOT NULL", name="completed_time"),
        ForeignKeyConstraint(
            ["academy_id", "task_id"], ["tasks.academy_id", "tasks.id"], ondelete="SET NULL"
        ),
        ForeignKeyConstraint(
            ["academy_id", "student_membership_id"],
            ["academy_memberships.academy_id", "academy_memberships.id"],
            ondelete="CASCADE",
        ),
        # 같은 데이터·같은 약점으로 살아 있는 추천은 1개 (중복 생성 방지)
        Index(
            "uq_practice_recommendations_live",
            "owner_id",
            "batch_key",
            "weakness_category",
            unique=True,
            postgresql_where=text("status NOT IN ('REJECTED', 'SUPERSEDED')"),
        ),
        Index("ix_practice_recommendations_owner_status", "owner_id", "status", "created_at"),
        # v0.9: 시작은 채택(ADOPTED) 이후에만
        CheckConstraint(
            "started_at IS NULL OR status IN ('ADOPTED', 'COMPLETED', 'SUPERSEDED', 'REJECTED')",
            name="started_after_adopt",
        ),
        Index("ix_practice_recommendations_academy_status", "academy_id", "status", "created_at"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    scope: Mapped[GrowthScope] = mapped_column(enum_column(GrowthScope, "scope"))
    academy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academies.id", ondelete="CASCADE")
    )
    student_membership_id: Mapped[uuid.UUID | None]
    review_mode: Mapped[ReviewMode] = mapped_column(enum_column(ReviewMode, "review_mode"))
    source: Mapped[RecommendationSource] = mapped_column(
        enum_column(RecommendationSource, "source")
    )
    status: Mapped[RecommendationStatus] = mapped_column(
        enum_column(RecommendationStatus, "status"), default=RecommendationStatus.DRAFT
    )
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)
    # 생성에 쓴 데이터 지문 + 범위 (같은 키 = 같은 데이터로 만든 추천 묶음)
    batch_key: Mapped[str] = mapped_column(String(64))
    weakness_category: Mapped[WeaknessCategory] = mapped_column(
        enum_column(WeaknessCategory, "weakness_category")
    )
    practical_type: Mapped[PracticalType | None] = mapped_column(
        enum_column(PracticalType, "practical_type")
    )
    # 현재 값 (검토자가 수정)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(2000))
    method_steps: Mapped[list[str]] = mapped_column(JSONB)
    estimated_minutes: Mapped[int] = mapped_column(Integer)
    difficulty: Mapped[Difficulty] = mapped_column(enum_column(Difficulty, "difficulty"))
    reason: Mapped[str] = mapped_column(String(1000))
    # 생성 원본 (규칙 템플릿 또는 AI 응답, 변경하지 않음)
    origin_output: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # 근거: 승인된 첨삭 항목·첨삭·작품 ID (문장은 조회 시 현재 테이블에서 읽는다)
    evidence_item_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(36)), server_default=text("'{}'::varchar[]"), default=list
    )
    evidence_feedback_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(36)), server_default=text("'{}'::varchar[]"), default=list
    )
    evidence_artwork_ids: Mapped[list[str]] = mapped_column(
        ARRAY(String(36)), server_default=text("'{}'::varchar[]"), default=list
    )
    # 생성 시 약점 통계 (F-15 연계용: 분석 기간·최근 비율·작품 수)
    analysis_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("growth_reports.id", ondelete="SET NULL")
    )
    model_name: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None]
    rejected_reason: Mapped[str | None] = mapped_column(String(500))
    # 학원: 배포된 v0.3 과제 (완료 기록은 task_assignments.completed_at)
    task_id: Mapped[uuid.UUID | None]
    # 개인: 학생 본인 완료 기록
    completed_at: Mapped[datetime | None]
    # v0.9 F-8: 과제 시작 시각 (개인), 학습 목표 문장
    started_at: Mapped[datetime | None]
    learning_goal: Mapped[str | None] = mapped_column(String(300))


class PracticeRecommendationArtwork(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """과제 수행 작품 연결 (v0.9 F-8). 개인 과제에 학생 본인의 작품만 연결한다.

    완료(과제 상태)와 실력 향상(연결 작품의 후속 첨삭에서 약점이 다시 나왔는지)은 별개로 다룬다.
    작품이 삭제되면 연결도 사라진다 (CASCADE). owner_id 복합 FK로 다른 사람 작품 연결을 막는다.
    """

    __tablename__ = "practice_recommendation_artworks"
    __table_args__ = (
        UniqueConstraint("recommendation_id", "artwork_id"),
        ForeignKeyConstraint(
            ["artwork_id", "owner_id"], ["artworks.id", "artworks.owner_id"], ondelete="CASCADE"
        ),
        Index("ix_practice_recommendation_artworks_artwork", "artwork_id"),
    )

    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_recommendations.id", ondelete="CASCADE")
    )
    artwork_id: Mapped[uuid.UUID]
    owner_id: Mapped[uuid.UUID]


class PracticeRecommendationHistory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """추천 과제 생성·수정·승인·반려·배포·채택·완료 이력 (append-only)."""

    __tablename__ = "practice_recommendation_history"
    __table_args__ = (
        Index("ix_practice_recommendation_history_rec", "recommendation_id", "created_at"),
    )

    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_recommendations.id", ondelete="CASCADE")
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    actor_mode: Mapped[ReviewMode | None] = mapped_column(enum_column(ReviewMode, "actor_mode"))
    action: Mapped[RecommendationAction] = mapped_column(
        enum_column(RecommendationAction, "action")
    )
    from_status: Mapped[RecommendationStatus | None] = mapped_column(
        enum_column(RecommendationStatus, "from_status")
    )
    to_status: Mapped[RecommendationStatus] = mapped_column(
        enum_column(RecommendationStatus, "to_status")
    )
    version: Mapped[int] = mapped_column(Integer)
    changes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    note: Mapped[str | None] = mapped_column(Text)
