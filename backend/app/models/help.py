"""질문 콜·대기열 (v0.5, F-07).

[v0.5.1 서비스 제외] 기획 변경으로 API·서비스는 제거했다. 테이블은 데이터 보존과 Alembic 모델 일치
(`alembic check`)를 위해 남겨 두며, 물리 삭제는 별도 승인 후 새 리비전으로 진행한다
(docs/v0.5.1-planning-changes.md).

- help_requests: 학생의 질문 요청 1건. 반 단위 대기열이며 요청 순서(queue_seq)대로 처리한다.
  같은 학생은 같은 반에 활성(WAITING/CALLED/IN_PROGRESS) 요청을 1개만 가질 수 있다 (부분 유니크).
- help_queue_events: 상태 전이 기록 (append-only). 감사·평균 처리시간 분석·향후 SSE 재동기화용.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import HelpQueueEventType, HelpRequestStatus

_MEMBER = "academy_memberships.id"


class HelpRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "help_requests"
    __table_args__ = (
        UniqueConstraint("academy_id", "id"),
        ForeignKeyConstraint(
            ["academy_id", "class_id"], ["classes.academy_id", "classes.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["academy_id", "student_membership_id"],
            ["academy_memberships.academy_id", "academy_memberships.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("status <> 'CALLED' OR called_at IS NOT NULL", name="called_has_time"),
        CheckConstraint(
            "status <> 'IN_PROGRESS' OR started_at IS NOT NULL", name="in_progress_has_time"
        ),
        CheckConstraint(
            "status <> 'COMPLETED' OR completed_at IS NOT NULL", name="completed_has_time"
        ),
        CheckConstraint(
            "status NOT IN ('CANCELLED', 'SKIPPED') OR closed_at IS NOT NULL",
            name="closed_has_time",
        ),
        # 동일 학생·동일 반의 활성 요청은 1개 (동시 요청도 DB가 차단)
        Index(
            "uq_help_requests_active_student",
            "class_id",
            "student_membership_id",
            unique=True,
            postgresql_where=text("status IN ('WAITING', 'CALLED', 'IN_PROGRESS')"),
        ),
        # 대기열 조회·다음 학생 호출
        Index("ix_help_requests_class_status_seq", "class_id", "status", "queue_seq"),
        # 평균 처리시간 계산
        Index(
            "ix_help_requests_class_completed",
            "class_id",
            "completed_at",
            postgresql_where=text("status = 'COMPLETED'"),
        ),
        Index("ix_help_requests_student_requested", "student_membership_id", "requested_at"),
    )

    academy_id: Mapped[uuid.UUID]
    class_id: Mapped[uuid.UUID]
    student_membership_id: Mapped[uuid.UUID]
    # 질문 대상 작품 (선택). 학생 본인 작품만 (서비스 검증)
    artwork_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artworks.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[HelpRequestStatus] = mapped_column(
        enum_column(HelpRequestStatus, "help_request_status"), default=HelpRequestStatus.WAITING
    )
    # 대기 순서의 기준: DB가 INSERT 순서대로 부여하는 번호 (같은 시각 요청도 순서가 확정됨)
    queue_seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)
    requested_at: Mapped[datetime]
    called_at: Mapped[datetime | None]
    called_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(_MEMBER, ondelete="SET NULL"))
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    # 질문을 실제로 처리한(시작·완료한) 강사
    handled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(_MEMBER, ondelete="SET NULL"))
    # 취소·건너뛰기 시각과 수행자
    closed_at: Mapped[datetime | None]
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(_MEMBER, ondelete="SET NULL"))


class HelpQueueEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "help_queue_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["academy_id", "help_request_id"],
            ["help_requests.academy_id", "help_requests.id"],
            ondelete="CASCADE",
        ),
        Index("ix_help_queue_events_class_created", "class_id", "created_at"),
        Index("ix_help_queue_events_request_created", "help_request_id", "created_at"),
    )

    academy_id: Mapped[uuid.UUID]
    help_request_id: Mapped[uuid.UUID]
    # 반별 변경 감지(폴링의 last_changed_at, 향후 SSE)용. help_requests.class_id와 같다
    class_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"))
    event_type: Mapped[HelpQueueEventType] = mapped_column(
        enum_column(HelpQueueEventType, "help_queue_event_type")
    )
    from_status: Mapped[HelpRequestStatus | None] = mapped_column(
        enum_column(HelpRequestStatus, "help_event_from_status")
    )
    to_status: Mapped[HelpRequestStatus] = mapped_column(
        enum_column(HelpRequestStatus, "help_event_to_status")
    )
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(_MEMBER, ondelete="SET NULL")
    )
