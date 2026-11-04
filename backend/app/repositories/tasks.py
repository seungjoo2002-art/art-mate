import uuid
from datetime import date, datetime

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academy_class import AcademyClass, ClassMembership
from app.models.enums import ClassMemberRole, ClassMemberStatus, MembershipStatus, TaskStatus
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.models.task import LessonTopic, Task, TaskAssignment
from app.repositories.pagination import fetch_page
from app.schemas.common import PaginationParams


def _live_assignment():  # type: ignore[no-untyped-def]
    """집계 대상 배정: 학생이 아직 그 반에 ACTIVE로 배정되어 있고 학원 소속도 ACTIVE.

    (반을 떠난 학생의 미완료 과제가 강사 화면 집계에 남지 않도록)
    """
    return (
        select(ClassMembership.id)
        .join(AcademyMembership, AcademyMembership.id == ClassMembership.membership_id)
        .where(
            ClassMembership.class_id == Task.class_id,
            ClassMembership.membership_id == TaskAssignment.student_membership_id,
            ClassMembership.role == ClassMemberRole.STUDENT,
            ClassMembership.status == ClassMemberStatus.ACTIVE,
            AcademyMembership.status == MembershipStatus.ACTIVE,
        )
        .exists()
    )


class LessonTopicRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, topic: LessonTopic) -> None:
        self.session.add(topic)

    async def get(
        self, class_id: uuid.UUID, topic_id: uuid.UUID, *, for_update: bool = False
    ) -> LessonTopic | None:
        stmt = select(LessonTopic).where(
            LessonTopic.class_id == class_id, LessonTopic.id == topic_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_class(
        self, class_id: uuid.UUID, params: PaginationParams, start: date | None, end: date | None
    ) -> tuple[list[LessonTopic], int]:
        stmt = select(LessonTopic).where(LessonTopic.class_id == class_id)
        if start is not None:
            stmt = stmt.where(LessonTopic.lesson_date >= start)
        if end is not None:
            stmt = stmt.where(LessonTopic.lesson_date <= end)
        stmt = stmt.order_by(LessonTopic.lesson_date, LessonTopic.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return [row[0] for row in rows], total

    async def for_day(
        self, class_ids: Select[tuple[uuid.UUID]], day: date
    ) -> list[tuple[LessonTopic, str]]:
        stmt = (
            select(LessonTopic, AcademyClass.name)
            .join(AcademyClass, AcademyClass.id == LessonTopic.class_id)
            .where(LessonTopic.class_id.in_(class_ids), LessonTopic.lesson_date == day)
            .order_by(AcademyClass.name)
        )
        return [(row[0], row[1]) for row in (await self.session.execute(stmt)).all()]


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, obj: object) -> None:
        self.session.add(obj)

    async def get_in_academy(
        self, academy_id: uuid.UUID, task_id: uuid.UUID, *, for_update: bool = False
    ) -> Task | None:
        stmt = select(Task).where(Task.academy_id == academy_id, Task.id == task_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def _with_counts() -> Select[tuple[Task, str, int, int]]:
        live = _live_assignment()
        assigned = (
            select(func.count(TaskAssignment.id))
            .where(TaskAssignment.task_id == Task.id, live)
            .scalar_subquery()
        )
        completed = (
            select(func.count(TaskAssignment.id))
            .where(
                TaskAssignment.task_id == Task.id, TaskAssignment.completed_at.is_not(None), live
            )
            .scalar_subquery()
        )
        return select(Task, AcademyClass.name, assigned, completed).join(
            AcademyClass, AcademyClass.id == Task.class_id
        )

    async def list_tasks(
        self,
        academy_id: uuid.UUID,
        params: PaginationParams,
        *,
        class_ids: Select[tuple[uuid.UUID]],
        status: TaskStatus | None,
        created_between: tuple[datetime, datetime] | None,
    ) -> tuple[list[tuple[Task, str, int, int]], int]:
        stmt = self._with_counts().where(
            Task.academy_id == academy_id, Task.class_id.in_(class_ids)
        )
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if created_between is not None:
            stmt = stmt.where(
                Task.created_at >= created_between[0], Task.created_at < created_between[1]
            )
        stmt = stmt.order_by(Task.created_at.desc(), Task.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return [(row[0], row[1], row[2], row[3]) for row in rows], total

    async def with_counts(self, task_id: uuid.UUID) -> tuple[Task, str, int, int]:
        row = (await self.session.execute(self._with_counts().where(Task.id == task_id))).one()
        return row[0], row[1], row[2], row[3]

    async def assignments(
        self, task_id: uuid.UUID
    ) -> list[tuple[TaskAssignment, AcademyMembership, Profile]]:
        stmt = (
            select(TaskAssignment, AcademyMembership, Profile)
            .join(AcademyMembership, AcademyMembership.id == TaskAssignment.student_membership_id)
            .join(Profile, Profile.id == AcademyMembership.user_id)
            .where(TaskAssignment.task_id == task_id)
            .order_by(Profile.display_name, TaskAssignment.id)
        )
        return [(row[0], row[1], row[2]) for row in (await self.session.execute(stmt)).all()]

    async def get_assignment_for_update(
        self, task_id: uuid.UUID, student_membership_id: uuid.UUID
    ) -> TaskAssignment | None:
        stmt = (
            select(TaskAssignment)
            .where(
                TaskAssignment.task_id == task_id,
                TaskAssignment.student_membership_id == student_membership_id,
            )
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ------------------------------------------------------------------ student view

    @staticmethod
    def _my_tasks(
        student_ids: Select[tuple[uuid.UUID]],
    ) -> Select[tuple[TaskAssignment, Task, str]]:
        return (
            select(TaskAssignment, Task, AcademyClass.name)
            .join(Task, Task.id == TaskAssignment.task_id)
            .join(AcademyClass, AcademyClass.id == Task.class_id)
            .where(
                TaskAssignment.student_membership_id.in_(student_ids),
                Task.status == TaskStatus.ACTIVE,
            )
        )

    async def list_mine(
        self,
        student_ids: Select[tuple[uuid.UUID]],
        params: PaginationParams,
        *,
        completed: bool | None,
    ) -> tuple[list[tuple[TaskAssignment, Task, str]], int]:
        stmt = self._my_tasks(student_ids)
        if completed is True:
            stmt = stmt.where(TaskAssignment.completed_at.is_not(None))
        elif completed is False:
            stmt = stmt.where(TaskAssignment.completed_at.is_(None))
        stmt = stmt.order_by(
            Task.due_at.asc().nulls_last(), Task.created_at.desc(), TaskAssignment.id
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [(row[0], row[1], row[2]) for row in rows], total

    async def for_today(
        self, student_ids: Select[tuple[uuid.UUID]], start: datetime, end: datetime, limit: int
    ) -> list[tuple[TaskAssignment, Task, str]]:
        """오늘 할 일: 오늘 마감 + 마감 지난 미완료 + 마감 없는 미완료 + 오늘 완료한 과제."""
        open_ = TaskAssignment.completed_at.is_(None)
        stmt = (
            self._my_tasks(student_ids)
            .where(
                or_(
                    and_(Task.due_at >= start, Task.due_at < end),
                    and_(open_, or_(Task.due_at.is_(None), Task.due_at < start)),
                    and_(TaskAssignment.completed_at >= start, TaskAssignment.completed_at < end),
                )
            )
            .order_by(
                case((open_, 0), else_=1),
                Task.due_at.asc().nulls_last(),
                Task.created_at,
                TaskAssignment.id,
            )
            .limit(limit)
        )
        return [(row[0], row[1], row[2]) for row in (await self.session.execute(stmt)).all()]

    # ------------------------------------------------------------------ dashboard

    async def open_counts_by_class(
        self, class_ids: Select[tuple[uuid.UUID]]
    ) -> dict[uuid.UUID, int]:
        stmt = (
            select(Task.class_id, func.count(TaskAssignment.id))
            .join(TaskAssignment, TaskAssignment.task_id == Task.id)
            .where(
                Task.class_id.in_(class_ids),
                Task.status == TaskStatus.ACTIVE,
                TaskAssignment.completed_at.is_(None),
                _live_assignment(),
            )
            .group_by(Task.class_id)
        )
        return {key: value for key, value in (await self.session.execute(stmt)).all()}

    async def open_counts_by_student(
        self, class_ids: Select[tuple[uuid.UUID]]
    ) -> dict[uuid.UUID, int]:
        stmt = (
            select(TaskAssignment.student_membership_id, func.count(TaskAssignment.id))
            .join(Task, Task.id == TaskAssignment.task_id)
            .where(
                Task.class_id.in_(class_ids),
                Task.status == TaskStatus.ACTIVE,
                TaskAssignment.completed_at.is_(None),
                _live_assignment(),
            )
            .group_by(TaskAssignment.student_membership_id)
        )
        return {key: value for key, value in (await self.session.execute(stmt)).all()}
