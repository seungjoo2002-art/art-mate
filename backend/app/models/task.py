"""수업 주제와 학원 과제 (v0.3). 주제(lesson_topics)와 과제(tasks)는 별도 테이블이다."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import TaskStatus, TaskTargetType

_CLASS_REF = ["classes.academy_id", "classes.id"]


class LessonTopic(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """반의 수업일별 주제. 미래 날짜로 등록하면 '다음 수업 주제 사전 공지'가 된다."""

    __tablename__ = "lesson_topics"
    __table_args__ = (
        UniqueConstraint("class_id", "lesson_date"),
        ForeignKeyConstraint(["academy_id", "class_id"], _CLASS_REF, ondelete="CASCADE"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
    )

    academy_id: Mapped[uuid.UUID]
    class_id: Mapped[uuid.UUID]
    lesson_date: Mapped[date]
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """강사가 반에 배포한 과제. 대상 학생은 task_assignments에 배포 시점 기준으로 저장된다."""

    __tablename__ = "tasks"
    __table_args__ = (
        UniqueConstraint("academy_id", "id"),
        ForeignKeyConstraint(["academy_id", "class_id"], _CLASS_REF, ondelete="CASCADE"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        Index("ix_tasks_class_status_created", "class_id", "status", "created_at"),
        Index("ix_tasks_academy_created", "academy_id", "created_at"),
    )

    academy_id: Mapped[uuid.UUID]
    class_id: Mapped[uuid.UUID]
    lesson_topic_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("lesson_topics.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000))
    due_at: Mapped[datetime | None]
    target_type: Mapped[TaskTargetType] = mapped_column(
        enum_column(TaskTargetType, "task_target_type")
    )
    status: Mapped[TaskStatus] = mapped_column(
        enum_column(TaskStatus, "task_status"), default=TaskStatus.ACTIVE
    )
    cancelled_at: Mapped[datetime | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )


class TaskAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """과제 1건 × 학생 1명. 완료 체크(completed_at)는 학생 본인만 한다."""

    __tablename__ = "task_assignments"
    __table_args__ = (
        UniqueConstraint("task_id", "student_membership_id"),
        ForeignKeyConstraint(
            ["academy_id", "task_id"], ["tasks.academy_id", "tasks.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["academy_id", "student_membership_id"],
            ["academy_memberships.academy_id", "academy_memberships.id"],
            ondelete="CASCADE",
        ),
        Index("ix_task_assignments_student_completed", "student_membership_id", "completed_at"),
    )

    academy_id: Mapped[uuid.UUID]
    task_id: Mapped[uuid.UUID]
    student_membership_id: Mapped[uuid.UUID]
    completed_at: Mapped[datetime | None]
