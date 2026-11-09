"""수업 주제(lesson_topics)와 학원 과제(tasks / task_assignments).

- 주제: 반의 수업일별 1건. 미래 날짜로 등록하면 학생에게 '다음 수업 주제'로 보인다.
- 과제: 반 전체(CLASS) 또는 반의 특정 학생(STUDENTS)에게 배포. 대상 학생은 배포 시점 기준으로
  task_assignments에 저장된다 (이후 반에 들어온 학생에게는 자동 배포되지 않음).
- 취소(DELETE)는 status=CANCELLED. 학생 화면에서 사라지고 완료 체크도 막힌다.
- 완료 체크는 배정받은 학생 본인만 한다.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    UnprocessableError,
)
from app.models.academy_class import AcademyClass
from app.models.enums import TaskStatus, TaskTargetType
from app.models.membership import AcademyMembership
from app.models.task import LessonTopic, Task, TaskAssignment
from app.repositories.classes import ClassRepository
from app.repositories.tasks import LessonTopicRepository, TaskRepository
from app.schemas.common import PaginationParams
from app.schemas.students import StudentRef
from app.schemas.tasks import (
    LessonTopicCreate,
    LessonTopicUpdate,
    MyTask,
    TaskAssignmentRead,
    TaskCreate,
    TaskDetail,
    TaskRead,
    TaskUpdate,
)
from app.services.access import AccessService, scoped_class_ids
from app.services.classes import ensure_class_active


def task_read(task: Task, class_name: str, assigned: int, completed: int) -> TaskRead:
    return TaskRead(
        id=task.id,
        academy_id=task.academy_id,
        class_id=task.class_id,
        class_name=class_name,
        lesson_topic_id=task.lesson_topic_id,
        title=task.title,
        description=task.description,
        due_at=task.due_at,
        target_type=task.target_type,
        status=task.status,
        cancelled_at=task.cancelled_at,
        created_by=task.created_by,
        created_at=task.created_at,
        updated_at=task.updated_at,
        assigned_count=assigned,
        completed_count=completed,
    )


def my_task(assignment: TaskAssignment, task: Task, class_name: str) -> MyTask:
    now = clock.utc_now()
    return MyTask(
        assignment_id=assignment.id,
        task_id=task.id,
        academy_id=task.academy_id,
        class_id=task.class_id,
        class_name=class_name,
        lesson_topic_id=task.lesson_topic_id,
        title=task.title,
        description=task.description,
        due_at=task.due_at,
        completed=assignment.completed_at is not None,
        completed_at=assignment.completed_at,
        is_overdue=assignment.completed_at is None
        and task.due_at is not None
        and task.due_at < now,
        assigned_at=assignment.created_at,
    )


def _topic_exists() -> ConflictError:
    return ConflictError(
        "A lesson topic already exists for this class and date",
        code=ErrorCode.LESSON_TOPIC_EXISTS,
    )


class LessonTopicService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.topics = LessonTopicRepository(session)
        self.access = AccessService(session)

    async def create(
        self, actor: AcademyMembership, class_id: uuid.UUID, data: LessonTopicCreate
    ) -> LessonTopic:
        ensure_class_active(await self.access.require_class_manager(actor, class_id))
        topic = LessonTopic(
            id=uuid.uuid4(),
            academy_id=actor.academy_id,
            class_id=class_id,
            created_by=actor.id,
            **data.model_dump(),
        )
        self.topics.add(topic)
        await self._commit_unique()
        await self.session.refresh(topic)
        return topic

    async def _commit_unique(self) -> None:
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            raise _topic_exists() from None

    async def list_topics(
        self,
        actor: AcademyMembership,
        class_id: uuid.UUID,
        params: PaginationParams,
        start: date | None,
        end: date | None,
    ) -> tuple[list[LessonTopic], int]:
        await self.access.require_class_reader(actor, class_id)
        return await self.topics.list_for_class(class_id, params, start, end)

    async def _for_write(
        self, actor: AcademyMembership, class_id: uuid.UUID, topic_id: uuid.UUID
    ) -> LessonTopic:
        ensure_class_active(await self.access.require_class_manager(actor, class_id))
        topic = await self.topics.get(class_id, topic_id, for_update=True)
        if topic is None:
            raise NotFoundError("Lesson topic not found")
        return topic

    async def update(
        self,
        actor: AcademyMembership,
        class_id: uuid.UUID,
        topic_id: uuid.UUID,
        data: LessonTopicUpdate,
    ) -> LessonTopic:
        topic = await self._for_write(actor, class_id, topic_id)
        for field, value in data.changes().items():
            setattr(topic, field, value)
        await self._commit_unique()
        await self.session.refresh(topic)
        return topic

    async def delete(
        self, actor: AcademyMembership, class_id: uuid.UUID, topic_id: uuid.UUID
    ) -> None:
        """주제 삭제 (연결된 과제는 남고 lesson_topic_id만 null이 된다)."""
        topic = await self._for_write(actor, class_id, topic_id)
        await self.session.delete(topic)
        await self.session.commit()


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.tasks = TaskRepository(session)
        self.classes = ClassRepository(session)
        self.topics = LessonTopicRepository(session)
        self.access = AccessService(session)

    async def _check_topic(self, class_id: uuid.UUID, topic_id: uuid.UUID | None) -> None:
        if topic_id is not None and await self.topics.get(class_id, topic_id) is None:
            raise UnprocessableError(
                "lesson_topic_id does not belong to this class", code=ErrorCode.INVALID_TASK_TARGET
            )

    async def create(self, actor: AcademyMembership, data: TaskCreate) -> TaskDetail:
        # 반 행 잠금: 배포 대상(반 학생 목록) 확정과 저장을 한 트랜잭션에서 일관되게 처리
        academy_class = await self.access.require_class_manager(
            actor, data.class_id, for_update=True
        )
        ensure_class_active(academy_class)
        await self._check_topic(data.class_id, data.lesson_topic_id)
        if data.due_at is not None and data.due_at <= clock.utc_now():
            raise UnprocessableError(
                "due_at must be in the future", code=ErrorCode.INVALID_DATE_RANGE
            )

        class_students = await self.classes.active_student_ids(data.class_id)
        if data.target_type == TaskTargetType.STUDENTS:
            targets = set(data.student_membership_ids)
            if not targets <= class_students:
                raise UnprocessableError(
                    "Some students are not assigned to this class",
                    code=ErrorCode.INVALID_TASK_TARGET,
                )
        else:
            targets = class_students
        if not targets:
            raise UnprocessableError(
                "This class has no students to assign", code=ErrorCode.INVALID_TASK_TARGET
            )

        task = Task(
            id=uuid.uuid4(),
            academy_id=actor.academy_id,
            class_id=data.class_id,
            lesson_topic_id=data.lesson_topic_id,
            title=data.title,
            description=data.description,
            due_at=data.due_at,
            target_type=data.target_type,
            status=TaskStatus.ACTIVE,
            created_by=actor.id,
        )
        self.tasks.add(task)
        await self.session.flush()
        for student_id in sorted(targets):
            self.tasks.add(
                TaskAssignment(
                    id=uuid.uuid4(),
                    academy_id=actor.academy_id,
                    task_id=task.id,
                    student_membership_id=student_id,
                )
            )
        await self.session.commit()
        return await self._detail(task.id)

    async def _detail(self, task_id: uuid.UUID) -> TaskDetail:
        task, class_name, assigned, completed = await self.tasks.with_counts(task_id)
        assignments = [
            TaskAssignmentRead(
                assignment_id=a.id,
                student=StudentRef(
                    membership_id=m.id,
                    user_id=p.id,
                    display_name=p.display_name,
                    avatar_path=p.avatar_path,
                ),
                completed=a.completed_at is not None,
                completed_at=a.completed_at,
            )
            for a, m, p in await self.tasks.assignments(task_id)
        ]
        return TaskDetail(
            **task_read(task, class_name, assigned, completed).model_dump(),
            assignments=assignments,
        )

    async def list_tasks(
        self,
        actor: AcademyMembership,
        params: PaginationParams,
        *,
        class_id: uuid.UUID | None,
        status: TaskStatus | None,
        created_on: date | None,
    ) -> tuple[list[TaskRead], int]:
        """담당 반의 과제 (학원 관리자는 전체). class_id 지정 시 그 반을 관리할 수 있어야 한다."""
        if class_id is not None:
            await self.access.require_class_manager(actor, class_id)
            scope = select(AcademyClass.id).where(AcademyClass.id == class_id)
        else:
            scope = scoped_class_ids(actor, mine=False)
        rows, total = await self.tasks.list_tasks(
            actor.academy_id,
            params,
            class_ids=scope,
            status=status,
            created_between=clock.local_day_bounds(created_on) if created_on else None,
        )
        return [task_read(*row) for row in rows], total

    async def _managed_task(
        self, actor: AcademyMembership, task_id: uuid.UUID, *, for_update: bool = False
    ) -> Task:
        task = await self.tasks.get_in_academy(actor.academy_id, task_id, for_update=for_update)
        if task is None:
            raise NotFoundError("Task not found")
        await self.access.require_class_manager(actor, task.class_id)
        return task

    async def get(self, actor: AcademyMembership, task_id: uuid.UUID) -> TaskDetail:
        await self._managed_task(actor, task_id)
        return await self._detail(task_id)

    async def update(
        self, actor: AcademyMembership, task_id: uuid.UUID, data: TaskUpdate
    ) -> TaskDetail:
        task = await self._managed_task(actor, task_id, for_update=True)
        if task.status != TaskStatus.ACTIVE:
            raise ConflictError("This task has been cancelled", code=ErrorCode.TASK_CANCELLED)
        changes = data.changes()
        if "lesson_topic_id" in changes:
            await self._check_topic(task.class_id, changes["lesson_topic_id"])
        if changes.get("due_at") is not None and changes["due_at"] <= clock.utc_now():
            raise UnprocessableError(
                "due_at must be in the future", code=ErrorCode.INVALID_DATE_RANGE
            )
        for field, value in changes.items():
            setattr(task, field, value)
        await self.session.commit()
        return await self._detail(task_id)

    async def cancel(self, actor: AcademyMembership, task_id: uuid.UUID) -> None:
        task = await self._managed_task(actor, task_id, for_update=True)
        if task.status == TaskStatus.CANCELLED:
            return
        task.status = TaskStatus.CANCELLED
        task.cancelled_at = clock.utc_now()
        await self.session.commit()

    # ------------------------------------------------------------------ student

    async def list_mine(
        self, student: AcademyMembership, params: PaginationParams, completed: bool | None
    ) -> tuple[list[MyTask], int]:
        rows, total = await self.tasks.list_mine(
            select(AcademyMembership.id).where(AcademyMembership.id == student.id),
            params,
            completed=completed,
        )
        return [my_task(*row) for row in rows], total

    async def set_completion(
        self, student: AcademyMembership, task_id: uuid.UUID, completed: bool
    ) -> MyTask:
        task = await self.tasks.get_in_academy(student.academy_id, task_id)
        assignment = (
            await self.tasks.get_assignment_for_update(task_id, student.id) if task else None
        )
        if task is None or assignment is None:
            raise NotFoundError("Task not found")
        if task.status != TaskStatus.ACTIVE:
            raise ConflictError("This task has been cancelled", code=ErrorCode.TASK_CANCELLED)
        if completed and assignment.completed_at is None:
            assignment.completed_at = clock.utc_now()
        elif not completed:
            assignment.completed_at = None
        await self.session.commit()
        await self.session.refresh(assignment)
        class_name = (await self.tasks.with_counts(task_id))[1]
        return my_task(assignment, task, class_name)
