import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import Select, and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academy_class import (
    AcademyClass,
    ClassMembership,
    ClassSchedule,
    ScheduleException,
)
from app.models.enums import (
    ClassMemberRole,
    ClassMemberStatus,
    ClassStatus,
    MembershipStatus,
    ScheduleExceptionKind,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.repositories.pagination import fetch_page
from app.schemas.common import PaginationParams


class ClassRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, obj: object) -> None:
        self.session.add(obj)

    # ------------------------------------------------------------------ classes

    async def list_classes(
        self,
        academy_id: uuid.UUID,
        params: PaginationParams,
        *,
        status: ClassStatus | None,
        within: Select[tuple[uuid.UUID]] | None,
    ) -> tuple[list[AcademyClass], int]:
        stmt = select(AcademyClass).where(AcademyClass.academy_id == academy_id)
        if status is not None:
            stmt = stmt.where(AcademyClass.status == status)
        if within is not None:
            stmt = stmt.where(AcademyClass.id.in_(within))
        stmt = stmt.order_by(AcademyClass.name, AcademyClass.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return [row[0] for row in rows], total

    async def classes_by_ids(self, class_ids: Select[tuple[uuid.UUID]]) -> list[AcademyClass]:
        stmt = (
            select(AcademyClass)
            .where(AcademyClass.id.in_(class_ids))
            .order_by(AcademyClass.name, AcademyClass.id)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def student_counts(self, class_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, int]:
        ids = list(class_ids)
        if not ids:
            return {}
        stmt = (
            select(ClassMembership.class_id, func.count())
            .join(AcademyMembership, AcademyMembership.id == ClassMembership.membership_id)
            .where(
                ClassMembership.class_id.in_(ids),
                ClassMembership.role == ClassMemberRole.STUDENT,
                ClassMembership.status == ClassMemberStatus.ACTIVE,
                AcademyMembership.status == MembershipStatus.ACTIVE,
            )
            .group_by(ClassMembership.class_id)
        )
        return {class_id: count for class_id, count in (await self.session.execute(stmt)).all()}

    async def instructors(
        self, class_ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, list[tuple[uuid.UUID, str]]]:
        ids = list(class_ids)
        result: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = defaultdict(list)
        if not ids:
            return result
        stmt = (
            select(ClassMembership.class_id, ClassMembership.membership_id, Profile.display_name)
            .join(AcademyMembership, AcademyMembership.id == ClassMembership.membership_id)
            .join(Profile, Profile.id == AcademyMembership.user_id)
            .where(
                ClassMembership.class_id.in_(ids),
                ClassMembership.role == ClassMemberRole.INSTRUCTOR,
                ClassMembership.status == ClassMemberStatus.ACTIVE,
                AcademyMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(Profile.display_name)
        )
        for class_id, membership_id, name in (await self.session.execute(stmt)).all():
            result[class_id].append((membership_id, name))
        return result

    async def roles_of(
        self, class_ids: Iterable[uuid.UUID], membership_id: uuid.UUID
    ) -> dict[uuid.UUID, ClassMemberRole]:
        ids = list(class_ids)
        if not ids:
            return {}
        stmt = select(ClassMembership.class_id, ClassMembership.role).where(
            ClassMembership.class_id.in_(ids),
            ClassMembership.membership_id == membership_id,
            ClassMembership.status == ClassMemberStatus.ACTIVE,
        )
        return {key: value for key, value in (await self.session.execute(stmt)).all()}

    # ------------------------------------------------------------------ class members

    async def list_members(
        self,
        class_id: uuid.UUID,
        params: PaginationParams,
        *,
        status: ClassMemberStatus,
        role: ClassMemberRole | None,
    ) -> tuple[list[tuple[ClassMembership, AcademyMembership, Profile]], int]:
        stmt = (
            select(ClassMembership, AcademyMembership, Profile)
            .join(AcademyMembership, AcademyMembership.id == ClassMembership.membership_id)
            .join(Profile, Profile.id == AcademyMembership.user_id)
            .where(ClassMembership.class_id == class_id, ClassMembership.status == status)
        )
        if role is not None:
            stmt = stmt.where(ClassMembership.role == role)
        stmt = stmt.order_by(ClassMembership.role, Profile.display_name, ClassMembership.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return [(row[0], row[1], row[2]) for row in rows], total

    async def member_view(
        self, class_member_id: uuid.UUID
    ) -> tuple[ClassMembership, AcademyMembership, Profile]:
        stmt = (
            select(ClassMembership, AcademyMembership, Profile)
            .join(AcademyMembership, AcademyMembership.id == ClassMembership.membership_id)
            .join(Profile, Profile.id == AcademyMembership.user_id)
            .where(ClassMembership.id == class_member_id)
        )
        row = (await self.session.execute(stmt)).one()
        return row[0], row[1], row[2]

    async def activate_member(
        self,
        *,
        academy_id: uuid.UUID,
        class_id: uuid.UUID,
        membership_id: uuid.UUID,
        role: ClassMemberRole,
        now: datetime,
    ) -> uuid.UUID | None:
        """반 배정. 해제 이력이 있으면 같은 행을 재활성화. 이미 ACTIVE면 None (동시 요청 포함)."""
        stmt = insert(ClassMembership).values(
            id=uuid.uuid4(),
            academy_id=academy_id,
            class_id=class_id,
            membership_id=membership_id,
            role=role,
            status=ClassMemberStatus.ACTIVE,
            joined_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ClassMembership.class_id, ClassMembership.membership_id],
            set_={
                "role": stmt.excluded.role,
                "status": ClassMemberStatus.ACTIVE,
                "joined_at": now,
                "ended_at": None,
                "updated_at": func.now(),
            },
            where=ClassMembership.status != ClassMemberStatus.ACTIVE,
        ).returning(ClassMembership.id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_member_for_update(
        self, class_id: uuid.UUID, class_member_id: uuid.UUID
    ) -> ClassMembership | None:
        stmt = (
            select(ClassMembership)
            .where(ClassMembership.class_id == class_id, ClassMembership.id == class_member_id)
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def active_student_ids(self, class_id: uuid.UUID) -> set[uuid.UUID]:
        stmt = (
            select(ClassMembership.membership_id)
            .join(AcademyMembership, AcademyMembership.id == ClassMembership.membership_id)
            .where(
                ClassMembership.class_id == class_id,
                ClassMembership.role == ClassMemberRole.STUDENT,
                ClassMembership.status == ClassMemberStatus.ACTIVE,
                AcademyMembership.status == MembershipStatus.ACTIVE,
            )
        )
        return set((await self.session.execute(stmt)).scalars())

    async def end_all_for_membership(self, membership_id: uuid.UUID, now: datetime) -> None:
        """학원 탈퇴·제외 시 그 사람의 반 배정을 모두 해제한다."""
        await self.session.execute(
            update(ClassMembership)
            .where(
                ClassMembership.membership_id == membership_id,
                ClassMembership.status == ClassMemberStatus.ACTIVE,
            )
            .values(status=ClassMemberStatus.REMOVED, ended_at=now, updated_at=func.now())
        )

    # ------------------------------------------------------------------ schedules

    async def list_schedules(
        self, class_id: uuid.UUID, params: PaginationParams, *, include_inactive: bool
    ) -> tuple[list[ClassSchedule], int]:
        stmt = select(ClassSchedule).where(ClassSchedule.class_id == class_id)
        if not include_inactive:
            stmt = stmt.where(ClassSchedule.is_active)
        stmt = stmt.order_by(
            ClassSchedule.weekday, ClassSchedule.start_time, ClassSchedule.effective_from
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [row[0] for row in rows], total

    async def get_schedule(
        self, class_id: uuid.UUID, schedule_id: uuid.UUID, *, for_update: bool = False
    ) -> ClassSchedule | None:
        stmt = select(ClassSchedule).where(
            ClassSchedule.class_id == class_id, ClassSchedule.id == schedule_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def active_schedules(
        self, class_ids: Iterable[uuid.UUID], start: date | None = None, end: date | None = None
    ) -> list[ClassSchedule]:
        ids = list(class_ids)
        if not ids:
            return []
        stmt = select(ClassSchedule).where(ClassSchedule.class_id.in_(ids), ClassSchedule.is_active)
        if end is not None:
            stmt = stmt.where(ClassSchedule.effective_from <= end)
        if start is not None:
            stmt = stmt.where(
                or_(ClassSchedule.effective_until.is_(None), ClassSchedule.effective_until >= start)
            )
        return list((await self.session.execute(stmt)).scalars())

    # ------------------------------------------------------------------ exceptions

    async def get_exception(
        self, class_id: uuid.UUID, exception_id: uuid.UUID, *, for_update: bool = False
    ) -> ScheduleException | None:
        stmt = select(ScheduleException).where(
            ScheduleException.class_id == class_id, ScheduleException.id == exception_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def _in_range(self, start: date, end: date):  # type: ignore[no-untyped-def]
        return or_(
            and_(ScheduleException.session_date >= start, ScheduleException.session_date <= end),
            and_(ScheduleException.original_date >= start, ScheduleException.original_date <= end),
        )

    async def list_exceptions(
        self, class_id: uuid.UUID, start: date, end: date, params: PaginationParams
    ) -> tuple[list[ScheduleException], int]:
        stmt = (
            select(ScheduleException)
            .where(ScheduleException.class_id == class_id, self._in_range(start, end))
            .order_by(
                func.coalesce(ScheduleException.session_date, ScheduleException.original_date),
                ScheduleException.created_at,
                ScheduleException.id,
            )
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [row[0] for row in rows], total

    async def exceptions_in_range(
        self, class_ids: Iterable[uuid.UUID], start: date, end: date
    ) -> list[ScheduleException]:
        ids = list(class_ids)
        if not ids:
            return []
        stmt = select(ScheduleException).where(
            ScheduleException.class_id.in_(ids), self._in_range(start, end)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def active_override_exists(self, schedule_id: uuid.UUID, original_date: date) -> bool:
        stmt = select(ScheduleException.id).where(
            ScheduleException.schedule_id == schedule_id,
            ScheduleException.original_date == original_date,
            ScheduleException.is_active,
            ScheduleException.kind.in_(
                [ScheduleExceptionKind.CANCELLATION, ScheduleExceptionKind.RESCHEDULE]
            ),
        )
        return (await self.session.execute(stmt.limit(1))).first() is not None
