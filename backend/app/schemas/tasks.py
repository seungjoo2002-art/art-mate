import datetime as dt
import uuid
from typing import ClassVar, Self

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.models.enums import TaskStatus, TaskTargetType
from app.schemas.attendance import StudentRef
from app.schemas.common import APIModel
from app.schemas.fields import InputModel, LongText, PatchModel, Title

MAX_TASK_STUDENTS = 200

# ----------------------------------------------------------------------------- lesson topics


class LessonTopicCreate(InputModel):
    lesson_date: dt.date = Field(description="수업 날짜 (Asia/Seoul). 미래 날짜 = 사전 공지")
    title: Title = Field(examples=["석고 아그리파 명암 4시간"])
    description: LongText | None = None


class LessonTopicUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"lesson_date", "title"})

    lesson_date: dt.date | None = None
    title: Title | None = None
    description: LongText | None = None


class LessonTopicRead(APIModel):
    id: uuid.UUID
    academy_id: uuid.UUID
    class_id: uuid.UUID
    lesson_date: dt.date
    title: str
    description: str | None
    created_by: uuid.UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime


# ----------------------------------------------------------------------------- tasks


class TaskCreate(InputModel):
    class_id: uuid.UUID
    title: Title
    description: LongText | None = None
    due_at: AwareDatetime | None = Field(
        default=None, description="마감 시각 (타임존 포함 ISO 8601, 예: 2026-11-10T23:59:00+09:00)"
    )
    lesson_topic_id: uuid.UUID | None = None
    target_type: TaskTargetType = TaskTargetType.CLASS
    student_membership_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=MAX_TASK_STUDENTS,
        description="target_type=STUDENTS일 때 대상 학생 (반에 배정된 학생만)",
    )

    @model_validator(mode="after")
    def _check_target(self) -> Self:
        if self.target_type == TaskTargetType.STUDENTS and not self.student_membership_ids:
            raise ValueError("student_membership_ids is required when target_type is STUDENTS")
        if self.target_type == TaskTargetType.CLASS and self.student_membership_ids:
            raise ValueError("student_membership_ids must be empty when target_type is CLASS")
        if len(set(self.student_membership_ids)) != len(self.student_membership_ids):
            raise ValueError("student_membership_ids must not contain duplicates")
        return self


class TaskUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"title"})

    title: Title | None = None
    description: LongText | None = None
    due_at: AwareDatetime | None = None
    lesson_topic_id: uuid.UUID | None = None


class TaskRead(APIModel):
    id: uuid.UUID
    academy_id: uuid.UUID
    class_id: uuid.UUID
    class_name: str
    lesson_topic_id: uuid.UUID | None
    title: str
    description: str | None
    due_at: dt.datetime | None
    target_type: TaskTargetType
    status: TaskStatus
    cancelled_at: dt.datetime | None
    created_by: uuid.UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime
    assigned_count: int
    completed_count: int


class TaskAssignmentRead(BaseModel):
    assignment_id: uuid.UUID
    student: StudentRef
    completed: bool
    completed_at: dt.datetime | None


class TaskDetail(TaskRead):
    assignments: list[TaskAssignmentRead]


class MyTask(BaseModel):
    """학생 본인에게 배정된 과제."""

    assignment_id: uuid.UUID
    task_id: uuid.UUID
    academy_id: uuid.UUID
    class_id: uuid.UUID
    class_name: str
    lesson_topic_id: uuid.UUID | None
    title: str
    description: str | None
    due_at: dt.datetime | None
    completed: bool
    completed_at: dt.datetime | None
    is_overdue: bool = Field(description="마감이 지났고 아직 완료하지 않음")
    assigned_at: dt.datetime


class TaskCompletionUpdate(InputModel):
    completed: bool
