"""시험 타이머 (v0.4, F-10).

[v0.5.1 서비스 제외] 기획 변경으로 API·서비스는 제거했다. 테이블은 데이터 보존과 Alembic 모델 일치
(`alembic check`)를 위해 남겨 두며, 물리 삭제는 별도 승인 후 새 리비전으로 진행한다
(docs/v0.5.1-planning-changes.md).

- exam_templates / exam_stage_targets: 학원의 재사용 가능한 시험 설정 (총시간, 단계별 목표 시각)
- exam_sessions / exam_session_stages: 반 단위 실제 시험. 시작할 때 템플릿 설정을 복사(스냅샷)하고
  시작 시각·종료 예정 시각·단계별 목표 시각을 저장한다 → 템플릿을 바꿔도 진행 중 시험은 영향 없음
- exam_participants: 시작 시점 반 학생 목록과 학생별 현재 작업 단계

남은 시간은 저장하지 않는다. 서버 시각과 저장된 시각으로 매 응답에서 계산한다.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import ArtworkStage, ExamEndReason, ExamSessionStatus, ExamWorkStage

_MEMBERSHIP_REF = ["academy_memberships.academy_id", "academy_memberships.id"]


class ExamTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exam_templates"
    __table_args__ = (
        UniqueConstraint("academy_id", "id"),
        CheckConstraint("total_minutes BETWEEN 1 AND 720", name="total_minutes_range"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        Index("ix_exam_templates_academy_archived_name", "academy_id", "is_archived", "name"),
    )

    academy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("academies.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    # 시험 유형 (예: 기초디자인, 소묘, 수채화, 사고의 전환). 학원마다 달라 자유 입력
    exam_type: Mapped[str] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(String(1000))
    total_minutes: Mapped[int] = mapped_column(SmallInteger)
    is_archived: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )


class ExamStageTarget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """템플릿의 단계별 목표 시각: 시작 후 `offset_minutes`분까지 그 단계를 마친다."""

    __tablename__ = "exam_stage_targets"
    __table_args__ = (
        UniqueConstraint("template_id", "stage"),
        ForeignKeyConstraint(
            ["academy_id", "template_id"],
            ["exam_templates.academy_id", "exam_templates.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("offset_minutes BETWEEN 1 AND 720", name="offset_range"),
    )

    academy_id: Mapped[uuid.UUID]
    template_id: Mapped[uuid.UUID]
    stage: Mapped[ArtworkStage] = mapped_column(enum_column(ArtworkStage, "exam_stage"))
    offset_minutes: Mapped[int] = mapped_column(SmallInteger)


class ExamSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exam_sessions"
    __table_args__ = (
        UniqueConstraint("academy_id", "id"),
        ForeignKeyConstraint(
            ["academy_id", "class_id"], ["classes.academy_id", "classes.id"], ondelete="CASCADE"
        ),
        CheckConstraint("total_minutes BETWEEN 1 AND 720", name="total_minutes_range"),
        CheckConstraint(
            "status IN ('SCHEDULED', 'CANCELLED')"
            " OR (started_at IS NOT NULL AND ends_at IS NOT NULL)",
            name="started_has_times",
        ),
        CheckConstraint(
            "status <> 'ENDED' OR (ended_at IS NOT NULL AND end_reason IS NOT NULL)",
            name="ended_has_reason",
        ),
        CheckConstraint("ends_at IS NULL OR ends_at > started_at", name="time_order"),
        # 한 반에서 동시에 진행 중인 시험은 1개 (동시 시작 요청도 DB가 차단)
        Index(
            "uq_exam_sessions_running_class",
            "class_id",
            unique=True,
            postgresql_where=text("status = 'RUNNING'"),
        ),
        Index("ix_exam_sessions_academy_status_created", "academy_id", "status", "created_at"),
        Index("ix_exam_sessions_class_created", "class_id", "created_at"),
    )

    academy_id: Mapped[uuid.UUID]
    class_id: Mapped[uuid.UUID]
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exam_templates.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(100))
    exam_type: Mapped[str] = mapped_column(String(50))
    total_minutes: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[ExamSessionStatus] = mapped_column(
        enum_column(ExamSessionStatus, "exam_session_status"),
        default=ExamSessionStatus.SCHEDULED,
    )
    started_at: Mapped[datetime | None]
    # 종료 예정 시각 = started_at + total_minutes
    ends_at: Mapped[datetime | None]
    # 실제 종료 시각 (강사 종료 또는 시간 만료)
    ended_at: Mapped[datetime | None]
    end_reason: Mapped[ExamEndReason | None] = mapped_column(
        enum_column(ExamEndReason, "exam_end_reason")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )
    started_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )
    ended_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )


class ExamSessionStage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """시험 세션의 단계별 목표 (템플릿 스냅샷). target_at은 시작할 때 저장된다."""

    __tablename__ = "exam_session_stages"
    __table_args__ = (
        UniqueConstraint("session_id", "stage"),
        ForeignKeyConstraint(
            ["academy_id", "session_id"],
            ["exam_sessions.academy_id", "exam_sessions.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("offset_minutes BETWEEN 1 AND 720", name="offset_range"),
    )

    academy_id: Mapped[uuid.UUID]
    session_id: Mapped[uuid.UUID]
    stage: Mapped[ArtworkStage] = mapped_column(enum_column(ArtworkStage, "exam_stage"))
    offset_minutes: Mapped[int] = mapped_column(SmallInteger)
    target_at: Mapped[datetime | None]


class ExamParticipant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exam_participants"
    __table_args__ = (
        UniqueConstraint("session_id", "student_membership_id"),
        ForeignKeyConstraint(
            ["academy_id", "session_id"],
            ["exam_sessions.academy_id", "exam_sessions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["academy_id", "student_membership_id"], _MEMBERSHIP_REF, ondelete="CASCADE"
        ),
        Index("ix_exam_participants_student_created", "student_membership_id", "created_at"),
    )

    academy_id: Mapped[uuid.UUID]
    session_id: Mapped[uuid.UUID]
    student_membership_id: Mapped[uuid.UUID]
    current_stage: Mapped[ExamWorkStage] = mapped_column(
        enum_column(ExamWorkStage, "exam_work_stage"), default=ExamWorkStage.NOT_STARTED
    )
    stage_updated_at: Mapped[datetime | None]
    # 각 단계에 처음 들어간 시각 (목표 시각과 비교용)
    sketch_at: Mapped[datetime | None]
    progress_at: Mapped[datetime | None]
    final_at: Mapped[datetime | None]
    done_at: Mapped[datetime | None]
