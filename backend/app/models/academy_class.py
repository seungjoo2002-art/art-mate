"""반(Class)·반 배정·정규 수업·일정 예외 (v0.3).

학원 격리: 모든 테이블이 `academy_id`를 갖고, 부모 참조는 `(academy_id, <id>)` 복합 FK로 건다.
→ 다른 학원의 반·학생을 연결하는 행은 DB가 거부한다 (애플리케이션 검사와 별개의 2차 방어).
"""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import (
    ClassMemberRole,
    ClassMemberStatus,
    ClassStatus,
    ScheduleExceptionKind,
)

_MEMBERSHIP_REF = ["academy_memberships.academy_id", "academy_memberships.id"]
_CLASS_REF = ["classes.academy_id", "classes.id"]


class AcademyClass(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """학원의 반. (`class`는 Python 예약어라 모델명은 AcademyClass)"""

    __tablename__ = "classes"
    __table_args__ = (
        # 자식 테이블의 (academy_id, class_id) 복합 FK 대상
        UniqueConstraint("academy_id", "id"),
        CheckConstraint("length(btrim(name)) > 0", name="name_not_blank"),
        Index("ix_classes_academy_status_name", "academy_id", "status", "name"),
    )

    academy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("academies.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(1000))
    subject: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[ClassStatus] = mapped_column(
        enum_column(ClassStatus, "class_status"), default=ClassStatus.ACTIVE
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )


class ClassMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """반 배정 (학생) 및 담당 강사 지정. (반, 학원 소속)당 1행, 재배정 시 같은 행을 재활성화."""

    __tablename__ = "class_memberships"
    __table_args__ = (
        UniqueConstraint("class_id", "membership_id"),
        ForeignKeyConstraint(["academy_id", "class_id"], _CLASS_REF, ondelete="CASCADE"),
        ForeignKeyConstraint(["academy_id", "membership_id"], _MEMBERSHIP_REF, ondelete="CASCADE"),
        Index("ix_class_memberships_class_status_role", "class_id", "status", "role"),
        Index("ix_class_memberships_membership_status", "membership_id", "status"),
    )

    academy_id: Mapped[uuid.UUID]
    class_id: Mapped[uuid.UUID]
    membership_id: Mapped[uuid.UUID]
    role: Mapped[ClassMemberRole] = mapped_column(enum_column(ClassMemberRole, "class_member_role"))
    status: Mapped[ClassMemberStatus] = mapped_column(
        enum_column(ClassMemberStatus, "class_member_status"), default=ClassMemberStatus.ACTIVE
    )
    joined_at: Mapped[datetime]
    ended_at: Mapped[datetime | None]


class ClassSchedule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """정규 수업 (매주 반복). 시간은 학원 현지(Asia/Seoul) 벽시계 시간."""

    __tablename__ = "class_schedules"
    __table_args__ = (
        # schedule_exceptions의 (class_id, schedule_id) 복합 FK 대상
        UniqueConstraint("class_id", "id"),
        ForeignKeyConstraint(["academy_id", "class_id"], _CLASS_REF, ondelete="CASCADE"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="time_order"),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from", name="effective_range"
        ),
        Index("ix_class_schedules_class_active", "class_id", "is_active"),
    )

    academy_id: Mapped[uuid.UUID]
    class_id: Mapped[uuid.UUID]
    # 0=월요일 ... 6=일요일 (Python date.weekday()와 동일)
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time]
    end_time: Mapped[time]
    effective_from: Mapped[date]
    effective_until: Mapped[date | None]
    location: Mapped[str | None] = mapped_column(String(100))
    # 삭제(DELETE) 시 false. 과거 일정·예외 기록을 보존한다.
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)


class ScheduleException(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """정규 수업의 1회 휴강·변경, 또는 보강.

    - CANCELLATION: schedule_id + original_date (그 회차 휴강)
    - RESCHEDULE: schedule_id + original_date → session_date/start_time/end_time 로 이동
    - MAKEUP: schedule_id 없음, session_date/start_time/end_time. student_membership_id가
      있으면 그 학생 개인 보강, 없으면 반 전체 보강
    """

    __tablename__ = "schedule_exceptions"
    __table_args__ = (
        ForeignKeyConstraint(["academy_id", "class_id"], _CLASS_REF, ondelete="CASCADE"),
        ForeignKeyConstraint(
            ["class_id", "schedule_id"],
            ["class_schedules.class_id", "class_schedules.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["academy_id", "student_membership_id"], _MEMBERSHIP_REF, ondelete="CASCADE"
        ),
        CheckConstraint(
            "(kind = 'CANCELLATION' AND schedule_id IS NOT NULL AND original_date IS NOT NULL"
            " AND session_date IS NULL AND start_time IS NULL AND end_time IS NULL)"
            " OR (kind = 'RESCHEDULE' AND schedule_id IS NOT NULL AND original_date IS NOT NULL"
            " AND session_date IS NOT NULL AND start_time IS NOT NULL AND end_time IS NOT NULL)"
            " OR (kind = 'MAKEUP' AND schedule_id IS NULL AND original_date IS NULL"
            " AND session_date IS NOT NULL AND start_time IS NOT NULL AND end_time IS NOT NULL)",
            name="kind_fields",
        ),
        CheckConstraint("end_time IS NULL OR end_time > start_time", name="time_order"),
        CheckConstraint(
            "student_membership_id IS NULL OR kind = 'MAKEUP'", name="student_only_makeup"
        ),
        # 정규 회차 하나에는 유효한 휴강/변경이 1개만 (동시 요청도 DB가 차단)
        Index(
            "uq_schedule_exceptions_occurrence",
            "schedule_id",
            "original_date",
            unique=True,
            postgresql_where=text("is_active AND kind IN ('CANCELLATION', 'RESCHEDULE')"),
        ),
        Index("ix_schedule_exceptions_class_session_date", "class_id", "session_date"),
        Index("ix_schedule_exceptions_class_original_date", "class_id", "original_date"),
    )

    academy_id: Mapped[uuid.UUID]
    class_id: Mapped[uuid.UUID]
    schedule_id: Mapped[uuid.UUID | None]
    kind: Mapped[ScheduleExceptionKind] = mapped_column(
        enum_column(ScheduleExceptionKind, "schedule_exception_kind")
    )
    original_date: Mapped[date | None]
    session_date: Mapped[date | None]
    start_time: Mapped[time | None]
    end_time: Mapped[time | None]
    location: Mapped[str | None] = mapped_column(String(100))
    student_membership_id: Mapped[uuid.UUID | None]
    reason: Mapped[str | None] = mapped_column(String(300))
    # 삭제(DELETE) 시 false: 휴강/변경은 원래 일정으로 복구, 보강은 '취소됨'으로 표시
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )
