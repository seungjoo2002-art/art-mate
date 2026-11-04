"""강사 수업 현황 대시보드(F-09, v0.3 범위)와 학생 '오늘 할 일' 통합 조회."""

import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.models.academy import Academy
from app.models.academy_class import AcademyClass, ClassMembership
from app.models.enums import (
    AcademyStatus,
    AttendanceStatus,
    ClassMemberRole,
    ClassMemberStatus,
    ClassStatus,
    MembershipRole,
    MembershipStatus,
    OccurrenceStatus,
    TaskStatus,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.repositories.attendance import AttendanceRepository
from app.repositories.classes import ClassRepository
from app.repositories.tasks import LessonTopicRepository, TaskRepository
from app.schemas.attendance import StudentRef
from app.schemas.classes import ClassInstructor
from app.schemas.common import PaginationParams
from app.schemas.dashboard import (
    AttendanceSummary,
    DashboardClass,
    DashboardStudent,
    DashboardTask,
    DashboardTotals,
    InstructorDashboard,
    StudentToday,
    TodayLessonTopic,
    TodaySummary,
)
from app.services.access import is_admin, scoped_class_ids
from app.services.personal_todos import PersonalTodoService, todo_read
from app.services.schedules import ScheduleService
from app.services.tasks import my_task

# '오늘' 화면 각 목록의 최대 건수 (집계 화면이라 페이지네이션 대신 상한)
TODAY_ITEM_LIMIT = 200


def _summarize(statuses: list[AttendanceStatus | None]) -> AttendanceSummary:
    summary = AttendanceSummary()
    for status in statuses:
        field = status.lower() if status else "not_recorded"
        setattr(summary, field, getattr(summary, field) + 1)
    return summary


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.classes = ClassRepository(session)
        self.attendance = AttendanceRepository(session)
        self.tasks = TaskRepository(session)
        self.topics = LessonTopicRepository(session)
        self.schedules = ScheduleService(session)

    async def instructor(
        self, actor: AcademyMembership, day: date | None, *, mine: bool
    ) -> InstructorDashboard:
        day = day or clock.local_today()
        mine = mine or not is_admin(actor)
        scope = scoped_class_ids(actor, mine=mine)
        classes = await self.classes.classes_by_ids(scope)
        class_ids = [c.id for c in classes]

        # 반별 학생 (학원 소속 ACTIVE)
        seats = (
            await self.session.execute(
                select(ClassMembership.class_id, AcademyMembership, Profile)
                .join(AcademyMembership, AcademyMembership.id == ClassMembership.membership_id)
                .join(Profile, Profile.id == AcademyMembership.user_id)
                .where(
                    ClassMembership.class_id.in_(scope),
                    ClassMembership.role == ClassMemberRole.STUDENT,
                    ClassMembership.status == ClassMemberStatus.ACTIVE,
                    AcademyMembership.status == MembershipStatus.ACTIVE,
                )
                .order_by(Profile.display_name, AcademyMembership.id)
            )
        ).all()
        students_by_class: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        classes_by_student: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        profiles: dict[uuid.UUID, tuple[AcademyMembership, Profile]] = {}
        for class_id, membership, profile in seats:
            students_by_class[class_id].append(membership.id)
            classes_by_student[membership.id].append(class_id)
            profiles[membership.id] = (membership, profile)

        records = await self.attendance.records_for_day(
            select(AcademyMembership.id).where(AcademyMembership.id.in_(list(profiles))), day
        )
        status_of = {sid: (records[sid].status if sid in records else None) for sid in profiles}
        open_by_class = await self.tasks.open_counts_by_class(scope)
        open_by_student = await self.tasks.open_counts_by_student(scope)
        instructors = await self.classes.instructors(class_ids)
        sessions = await self.schedules.occurrences_for_classes(classes, day, day)
        sessions_by_class: dict[uuid.UUID, list] = defaultdict(list)  # type: ignore[type-arg]
        for occurrence in sessions:
            sessions_by_class[occurrence.class_id].append(occurrence)

        dashboard_classes = [
            DashboardClass(
                id=c.id,
                name=c.name,
                subject=c.subject,
                student_count=len(students_by_class[c.id]),
                instructors=[
                    ClassInstructor(membership_id=m, display_name=n)
                    for m, n in instructors.get(c.id, [])
                ],
                today_sessions=sessions_by_class[c.id],
                attendance=_summarize([status_of[s] for s in students_by_class[c.id]]),
                open_assignment_count=open_by_class.get(c.id, 0),
            )
            for c in classes
        ]
        students = [
            DashboardStudent(
                student=StudentRef(
                    membership_id=membership.id,
                    user_id=profile.id,
                    display_name=profile.display_name,
                    avatar_path=profile.avatar_path,
                ),
                class_ids=classes_by_student[sid],
                attendance_status=status_of[sid],
                checked_in_at=records[sid].checked_in_at if sid in records else None,
                open_assignment_count=open_by_student.get(sid, 0),
            )
            for sid, (membership, profile) in profiles.items()
        ]

        tasks_today, _ = await self.tasks.list_tasks(
            actor.academy_id,
            PaginationParams(limit=100, offset=0),
            class_ids=scope,
            status=TaskStatus.ACTIVE,
            created_between=clock.local_day_bounds(day),
        )
        distributed = [
            DashboardTask(
                id=task.id,
                class_id=task.class_id,
                class_name=class_name,
                title=task.title,
                due_at=task.due_at,
                assigned_count=assigned,
                completed_count=completed,
                created_at=task.created_at,
            )
            for task, class_name, assigned, completed in tasks_today
        ]

        return InstructorDashboard(
            date=day,
            scope="mine" if mine else "all",
            totals=DashboardTotals(
                class_count=len(classes),
                student_count=len(profiles),
                session_count=sum(1 for o in sessions if o.status != OccurrenceStatus.CANCELLED),
                open_assignment_count=sum(open_by_class.values()),
                tasks_distributed_today=len(distributed),
                attendance=_summarize(list(status_of.values())),
            ),
            classes=dashboard_classes,
            today_schedule=sessions,
            students=students,
            tasks_distributed_today=distributed,
        )

    # ------------------------------------------------------------------ student today

    async def student_today(
        self, owner: Profile, day: date | None, academy_id: uuid.UUID | None
    ) -> StudentToday:
        day = day or clock.local_today()
        bounds = clock.local_day_bounds(day)
        # 학생으로 ACTIVE 소속된 ACTIVE 학원만
        my_memberships = (
            select(AcademyMembership.id)
            .join(Academy, Academy.id == AcademyMembership.academy_id)
            .where(
                AcademyMembership.user_id == owner.id,
                AcademyMembership.role == MembershipRole.STUDENT,
                AcademyMembership.status == MembershipStatus.ACTIVE,
                Academy.status == AcademyStatus.ACTIVE,
            )
        )
        if academy_id is not None:
            my_memberships = my_memberships.where(AcademyMembership.academy_id == academy_id)
        my_classes = (
            select(ClassMembership.class_id)
            .join(AcademyClass, AcademyClass.id == ClassMembership.class_id)
            .where(
                ClassMembership.membership_id.in_(my_memberships),
                ClassMembership.status == ClassMemberStatus.ACTIVE,
                AcademyClass.status == ClassStatus.ACTIVE,
            )
        )

        tasks = [
            my_task(*row)
            for row in await self.tasks.for_today(
                my_memberships, bounds[0], bounds[1], TODAY_ITEM_LIMIT
            )
        ]
        todos = [
            todo_read(t)
            for t in await PersonalTodoService(self.session).for_today(
                owner, day, bounds, TODAY_ITEM_LIMIT
            )
        ]
        topics = [
            TodayLessonTopic(
                id=topic.id,
                academy_id=topic.academy_id,
                class_id=topic.class_id,
                class_name=class_name,
                lesson_date=topic.lesson_date,
                title=topic.title,
                description=topic.description,
            )
            for topic, class_name in await self.topics.for_day(my_classes, day)
        ]
        return StudentToday(
            date=day,
            summary=TodaySummary(
                academy_task_total=len(tasks),
                academy_task_done=sum(t.completed for t in tasks),
                personal_todo_total=len(todos),
                personal_todo_done=sum(t.is_done for t in todos),
            ),
            academy_tasks=tasks,
            personal_todos=todos,
            lesson_topics=topics,
        )
