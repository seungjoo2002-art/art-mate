"""정규 수업(매주 반복)·휴강·일정 변경·보강, 날짜 범위 일정 조회.

정규 수업은 DB에 회차별로 저장하지 않는다. 조회할 때 [from, to] 범위로 펼치고 예외를 적용한다.
- CANCELLATION: 그 회차를 status=CANCELLED로 표시
- RESCHEDULE: 원래 날짜에는 표시하지 않고, 바뀐 날짜에 status=RESCHEDULED(original_date 포함)로 표시
- MAKEUP: 보강 회차 (취소된 보강은 status=CANCELLED)
"""

import uuid
from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
)
from app.models.academy_class import AcademyClass, ClassSchedule, ScheduleException
from app.models.enums import (
    ClassMemberRole,
    ClassStatus,
    OccurrenceKind,
    OccurrenceStatus,
    ScheduleExceptionKind,
)
from app.models.membership import AcademyMembership
from app.repositories.classes import ClassRepository
from app.schemas.classes import (
    Occurrence,
    ScheduleCreate,
    ScheduleExceptionCreate,
    ScheduleExceptionUpdate,
    ScheduleUpdate,
)
from app.schemas.common import PaginationParams
from app.services.access import (
    AccessService,
    classes_taught_by,
    enrolled_class_ids,
    is_staff,
    taught_class_ids,
)
from app.services.classes import ensure_class_active

# 일정 조회 1회 최대 범위 (from ~ to, 양 끝 포함)
MAX_SCHEDULE_RANGE_DAYS = 62

_OVERRIDE_KINDS = frozenset({ScheduleExceptionKind.CANCELLATION, ScheduleExceptionKind.RESCHEDULE})


def validate_range(start: date, end: date, max_days: int) -> None:
    if end < start:
        raise UnprocessableError(
            "'to' must be on or after 'from'", code=ErrorCode.INVALID_DATE_RANGE
        )
    if (end - start).days + 1 > max_days:
        raise UnprocessableError(
            f"Date range must be {max_days} days or less", code=ErrorCode.INVALID_DATE_RANGE
        )


def is_occurrence(schedule: ClassSchedule, day: date) -> bool:
    return (
        schedule.is_active
        and day.weekday() == schedule.weekday
        and schedule.effective_from <= day
        and (schedule.effective_until is None or day <= schedule.effective_until)
    )


def expand_occurrences(
    class_names: dict[uuid.UUID, str],
    schedules: Iterable[ClassSchedule],
    exceptions: Iterable[ScheduleException],
    start: date,
    end: date,
    *,
    student_id: uuid.UUID | None,
) -> list[Occurrence]:
    """정규 수업을 펼치고 예외를 적용한다.

    `student_id`가 있으면 그 학생 기준(다른 학생의 개인 보강 제외), None이면 강사 기준(전부 표시).
    """
    schedules = [s for s in schedules if s.is_active]
    by_id = {s.id: s for s in schedules}
    exceptions = list(exceptions)
    overrides = {
        (e.schedule_id, e.original_date): e
        for e in exceptions
        if e.is_active and e.kind in _OVERRIDE_KINDS
    }
    result: list[Occurrence] = []

    for s in schedules:
        first = max(start, s.effective_from)
        last = min(end, s.effective_until) if s.effective_until else end
        day = first + timedelta(days=(s.weekday - first.weekday()) % 7)
        while day <= last:
            override = overrides.get((s.id, day))
            if override is None or override.kind == ScheduleExceptionKind.CANCELLATION:
                result.append(
                    Occurrence(
                        class_id=s.class_id,
                        class_name=class_names[s.class_id],
                        kind=OccurrenceKind.REGULAR,
                        status=OccurrenceStatus.CANCELLED
                        if override
                        else OccurrenceStatus.SCHEDULED,
                        date=day,
                        starts_at=clock.local_datetime(day, s.start_time),
                        ends_at=clock.local_datetime(day, s.end_time),
                        schedule_id=s.id,
                        exception_id=override.id if override else None,
                        location=s.location,
                        reason=override.reason if override else None,
                    )
                )
            day += timedelta(days=7)

    for e in exceptions:
        if e.session_date is None or not (start <= e.session_date <= end):
            continue
        assert e.start_time is not None and e.end_time is not None
        if e.kind == ScheduleExceptionKind.RESCHEDULE:
            source = by_id.get(e.schedule_id) if e.schedule_id else None
            if not e.is_active or source is None or e.original_date is None:
                continue
            if not is_occurrence(source, e.original_date):
                continue
            kind, status = OccurrenceKind.REGULAR, OccurrenceStatus.RESCHEDULED
            location = e.location or source.location
        elif e.kind == ScheduleExceptionKind.MAKEUP:
            if student_id is not None and e.student_membership_id not in (None, student_id):
                continue
            kind = OccurrenceKind.MAKEUP
            status = OccurrenceStatus.SCHEDULED if e.is_active else OccurrenceStatus.CANCELLED
            location = e.location
        else:
            continue
        result.append(
            Occurrence(
                class_id=e.class_id,
                class_name=class_names[e.class_id],
                kind=kind,
                status=status,
                date=e.session_date,
                starts_at=clock.local_datetime(e.session_date, e.start_time),
                ends_at=clock.local_datetime(e.session_date, e.end_time),
                original_date=e.original_date,
                schedule_id=e.schedule_id,
                exception_id=e.id,
                location=location,
                reason=e.reason,
                student_membership_id=e.student_membership_id,
            )
        )

    result.sort(key=lambda o: (o.starts_at, o.class_name, str(o.class_id)))
    return result


def _overlaps(a: ClassSchedule | ScheduleCreate, b: ClassSchedule) -> bool:
    if a.weekday != b.weekday or not (a.start_time < b.end_time and b.start_time < a.end_time):
        return False
    a_from = a.effective_from or date.min
    a_until = a.effective_until or date.max
    return a_from <= (b.effective_until or date.max) and b.effective_from <= a_until


class ScheduleService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.classes = ClassRepository(session)
        self.access = AccessService(session)

    # ------------------------------------------------------------------ regular schedules

    async def _check_overlap(self, candidate: ClassSchedule) -> None:
        for other in await self.classes.active_schedules([candidate.class_id]):
            if other.id != candidate.id and _overlaps(candidate, other):
                raise ConflictError(
                    "Overlaps another regular schedule of this class",
                    code=ErrorCode.SCHEDULE_OVERLAP,
                )

    async def create_schedule(
        self, actor: AcademyMembership, class_id: uuid.UUID, data: ScheduleCreate
    ) -> ClassSchedule:
        # 반 행 잠금: 같은 반 일정의 겹침 검사·생성을 직렬화한다
        academy_class = await self.access.require_class_manager(actor, class_id, for_update=True)
        ensure_class_active(academy_class)
        schedule = ClassSchedule(
            id=uuid.uuid4(),
            academy_id=actor.academy_id,
            class_id=class_id,
            weekday=data.weekday,
            start_time=data.start_time,
            end_time=data.end_time,
            effective_from=data.effective_from or clock.local_today(),
            effective_until=data.effective_until,
            location=data.location,
            is_active=True,
        )
        if schedule.effective_until and schedule.effective_until < schedule.effective_from:
            raise UnprocessableError(
                "effective_until must be on or after effective_from",
                code=ErrorCode.INVALID_DATE_RANGE,
            )
        await self._check_overlap(schedule)
        self.classes.add(schedule)
        await self.session.commit()
        await self.session.refresh(schedule)
        return schedule

    async def list_schedules(
        self,
        actor: AcademyMembership,
        class_id: uuid.UUID,
        params: PaginationParams,
        *,
        include_inactive: bool,
    ) -> tuple[list[ClassSchedule], int]:
        await self.access.require_class_reader(actor, class_id)
        return await self.classes.list_schedules(
            class_id, params, include_inactive=include_inactive and is_staff(actor)
        )

    async def _schedule_for_write(
        self, actor: AcademyMembership, class_id: uuid.UUID, schedule_id: uuid.UUID
    ) -> ClassSchedule:
        academy_class = await self.access.require_class_manager(actor, class_id, for_update=True)
        ensure_class_active(academy_class)
        schedule = await self.classes.get_schedule(class_id, schedule_id, for_update=True)
        if schedule is None or not schedule.is_active:
            raise NotFoundError("Schedule not found")
        return schedule

    async def update_schedule(
        self,
        actor: AcademyMembership,
        class_id: uuid.UUID,
        schedule_id: uuid.UUID,
        data: ScheduleUpdate,
    ) -> ClassSchedule:
        schedule = await self._schedule_for_write(actor, class_id, schedule_id)
        for field, value in data.changes().items():
            setattr(schedule, field, value)
        if schedule.end_time <= schedule.start_time:
            raise UnprocessableError("end_time must be after start_time")
        if schedule.effective_until and schedule.effective_until < schedule.effective_from:
            raise UnprocessableError(
                "effective_until must be on or after effective_from",
                code=ErrorCode.INVALID_DATE_RANGE,
            )
        await self._check_overlap(schedule)
        await self.session.commit()
        await self.session.refresh(schedule)
        return schedule

    async def delete_schedule(
        self, actor: AcademyMembership, class_id: uuid.UUID, schedule_id: uuid.UUID
    ) -> None:
        schedule = await self._schedule_for_write(actor, class_id, schedule_id)
        schedule.is_active = False
        await self.session.commit()

    # ------------------------------------------------------------------ exceptions

    async def create_exception(
        self, actor: AcademyMembership, class_id: uuid.UUID, data: ScheduleExceptionCreate
    ) -> ScheduleException:
        academy_class = await self.access.require_class_manager(actor, class_id)
        ensure_class_active(academy_class)

        if data.kind in _OVERRIDE_KINDS:
            assert data.schedule_id is not None and data.original_date is not None
            schedule = await self.classes.get_schedule(class_id, data.schedule_id)
            if schedule is None or not is_occurrence(schedule, data.original_date):
                raise UnprocessableError(
                    "original_date is not a session of this schedule",
                    code=ErrorCode.INVALID_OCCURRENCE,
                )
            if await self.classes.active_override_exists(schedule.id, data.original_date):
                raise self._exception_exists()
        if data.student_membership_id is not None:
            role = await self.access.class_role(class_id, data.student_membership_id)
            if role != ClassMemberRole.STUDENT:
                raise UnprocessableError(
                    "The student is not assigned to this class",
                    code=ErrorCode.INVALID_CLASS_MEMBER,
                )

        exception = ScheduleException(
            id=uuid.uuid4(),
            academy_id=actor.academy_id,
            class_id=class_id,
            created_by=actor.id,
            is_active=True,
            **data.model_dump(),
        )
        self.classes.add(exception)
        try:
            await self.session.commit()
        except IntegrityError:
            # 동시 요청: 부분 유니크 인덱스(uq_schedule_exceptions_occurrence)가 차단
            await self.session.rollback()
            raise self._exception_exists() from None
        await self.session.refresh(exception)
        return exception

    @staticmethod
    def _exception_exists() -> ConflictError:
        return ConflictError(
            "This session is already cancelled or rescheduled",
            code=ErrorCode.SCHEDULE_EXCEPTION_EXISTS,
        )

    async def list_exceptions(
        self,
        actor: AcademyMembership,
        class_id: uuid.UUID,
        start: date,
        end: date,
        params: PaginationParams,
    ) -> tuple[list[ScheduleException], int]:
        await self.access.get_class(actor.academy_id, class_id)
        validate_range(start, end, 366)
        return await self.classes.list_exceptions(class_id, start, end, params)

    async def _exception_for_write(
        self, actor: AcademyMembership, class_id: uuid.UUID, exception_id: uuid.UUID
    ) -> ScheduleException:
        academy_class = await self.access.require_class_manager(actor, class_id)
        ensure_class_active(academy_class)
        exception = await self.classes.get_exception(class_id, exception_id, for_update=True)
        if exception is None or not exception.is_active:
            raise NotFoundError("Schedule exception not found")
        return exception

    async def update_exception(
        self,
        actor: AcademyMembership,
        class_id: uuid.UUID,
        exception_id: uuid.UUID,
        data: ScheduleExceptionUpdate,
    ) -> ScheduleException:
        exception = await self._exception_for_write(actor, class_id, exception_id)
        changes = data.changes()
        timing = {"session_date", "start_time", "end_time", "location"}
        if exception.kind == ScheduleExceptionKind.CANCELLATION and timing & changes.keys():
            raise UnprocessableError("A cancellation only has a reason to update")
        for field, value in changes.items():
            setattr(exception, field, value)
        if (
            exception.start_time
            and exception.end_time
            and exception.end_time <= exception.start_time
        ):
            raise UnprocessableError("end_time must be after start_time")
        await self.session.commit()
        await self.session.refresh(exception)
        return exception

    async def delete_exception(
        self, actor: AcademyMembership, class_id: uuid.UUID, exception_id: uuid.UUID
    ) -> None:
        """휴강·변경 취소(원래 일정 복구) 또는 보강 취소."""
        exception = await self._exception_for_write(actor, class_id, exception_id)
        exception.is_active = False
        await self.session.commit()

    # ------------------------------------------------------------------ occurrences

    async def occurrences_for_classes(
        self,
        classes: list[AcademyClass],
        start: date,
        end: date,
        *,
        student_id: uuid.UUID | None = None,
    ) -> list[Occurrence]:
        active = [c for c in classes if c.status == ClassStatus.ACTIVE]
        ids = [c.id for c in active]
        return expand_occurrences(
            {c.id: c.name for c in active},
            await self.classes.active_schedules(ids),
            await self.classes.exceptions_in_range(ids, start, end),
            start,
            end,
            student_id=student_id,
        )

    async def occurrences(
        self,
        actor: AcademyMembership,
        start: date,
        end: date,
        *,
        class_id: uuid.UUID | None,
        student_membership_id: uuid.UUID | None,
        instructor_membership_id: uuid.UUID | None,
        mine: bool,
    ) -> list[Occurrence]:
        """학생: 배정된 반의 일정 + 본인 개인 보강.
        강사 이상: 기본 학원 전체, `mine`=담당 반, `instructor_membership_id`=그 강사의 담당 반,
        `student_membership_id`=그 학생의 일정 (담당 학생만).
        """
        validate_range(start, end, MAX_SCHEDULE_RANGE_DAYS)
        student_view: uuid.UUID | None = None
        if not is_staff(actor):
            if instructor_membership_id or student_membership_id not in (None, actor.id):
                raise ForbiddenError()
            scope = enrolled_class_ids(actor.id)
            student_view = actor.id
        elif student_membership_id is not None:
            await self.access.require_managed_student(actor, student_membership_id)
            scope = enrolled_class_ids(student_membership_id)
            student_view = student_membership_id
        elif instructor_membership_id is not None:
            scope = classes_taught_by(actor.academy_id, instructor_membership_id)
        elif mine:
            scope = taught_class_ids(actor)
        else:
            scope = select(AcademyClass.id).where(AcademyClass.academy_id == actor.academy_id)

        if class_id is not None:
            await self.access.require_class_reader(actor, class_id)
        classes = [
            c
            for c in await self.classes.classes_by_ids(scope)
            if c.academy_id == actor.academy_id and (class_id is None or c.id == class_id)
        ]
        return await self.occurrences_for_classes(classes, start, end, student_id=student_view)
