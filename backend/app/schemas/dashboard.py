"""강사 대시보드·학생 '오늘' 화면 응답 (집계 응답이라 페이지네이션 없음)."""

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from app.models.enums import AttendanceStatus
from app.schemas.attendance import StudentRef
from app.schemas.classes import ClassInstructor, Occurrence
from app.schemas.personal_todo import PersonalTodoRead
from app.schemas.tasks import MyTask


class AttendanceSummary(BaseModel):
    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0
    not_recorded: int = Field(default=0, description="오늘 기록 없음 (미출석)")


class DashboardClass(BaseModel):
    id: uuid.UUID
    name: str
    subject: str | None
    student_count: int
    instructors: list[ClassInstructor]
    today_sessions: list[Occurrence]
    attendance: AttendanceSummary
    open_assignment_count: int = Field(description="이 반의 진행 중 과제 중 학생 미완료 건수")


class DashboardStudent(BaseModel):
    student: StudentRef
    class_ids: list[uuid.UUID]
    attendance_status: AttendanceStatus | None
    checked_in_at: dt.datetime | None
    open_assignment_count: int


class DashboardTask(BaseModel):
    id: uuid.UUID
    class_id: uuid.UUID
    class_name: str
    title: str
    due_at: dt.datetime | None
    assigned_count: int
    completed_count: int
    created_at: dt.datetime


class DashboardTotals(BaseModel):
    class_count: int
    student_count: int
    session_count: int = Field(description="오늘 진행(예정) 수업 수 (휴강 제외)")
    open_assignment_count: int
    tasks_distributed_today: int
    attendance: AttendanceSummary


class InstructorDashboard(BaseModel):
    date: dt.date
    scope: str = Field(description="mine = 담당 반, all = 학원 전체 (OWNER/MANAGER)")
    totals: DashboardTotals
    classes: list[DashboardClass]
    today_schedule: list[Occurrence]
    students: list[DashboardStudent]
    tasks_distributed_today: list[DashboardTask]


class TodayLessonTopic(BaseModel):
    id: uuid.UUID
    academy_id: uuid.UUID
    class_id: uuid.UUID
    class_name: str
    lesson_date: dt.date
    title: str
    description: str | None


class TodaySummary(BaseModel):
    academy_task_total: int
    academy_task_done: int
    personal_todo_total: int
    personal_todo_done: int


class StudentToday(BaseModel):
    """학생 '오늘 할 일' 통합 화면. 개인 할 일은 본인에게만 반환된다."""

    date: dt.date
    summary: TodaySummary
    academy_tasks: list[MyTask]
    personal_todos: list[PersonalTodoRead]
    lesson_topics: list[TodayLessonTopic]
