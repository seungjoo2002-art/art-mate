"""반 생성·수정, 반 배정(학생), 담당 강사 지정."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    UnprocessableError,
)
from app.models.academy_class import AcademyClass
from app.models.enums import (
    ClassMemberRole,
    ClassMemberStatus,
    ClassStatus,
    MembershipRole,
)
from app.models.membership import AcademyMembership
from app.repositories.classes import ClassRepository
from app.repositories.memberships import MembershipRepository
from app.schemas.classes import (
    ClassCreate,
    ClassInstructor,
    ClassMemberRead,
    ClassRead,
    ClassUpdate,
)
from app.schemas.common import PaginationParams
from app.services.access import (
    AccessService,
    enrolled_class_ids,
    is_admin,
    is_staff,
    taught_class_ids,
)


def ensure_class_active(academy_class: AcademyClass) -> None:
    if academy_class.status != ClassStatus.ACTIVE:
        raise ConflictError("This class is archived", code=ErrorCode.CLASS_ARCHIVED)


class ClassService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.classes = ClassRepository(session)
        self.memberships = MembershipRepository(session)
        self.access = AccessService(session)

    async def _read_models(
        self, classes: list[AcademyClass], viewer: AcademyMembership
    ) -> list[ClassRead]:
        ids = [c.id for c in classes]
        counts = await self.classes.student_counts(ids)
        instructors = await self.classes.instructors(ids)
        roles = await self.classes.roles_of(ids, viewer.id)
        return [
            ClassRead(
                id=c.id,
                academy_id=c.academy_id,
                name=c.name,
                description=c.description,
                subject=c.subject,
                status=c.status,
                student_count=counts.get(c.id, 0),
                instructors=[
                    ClassInstructor(membership_id=m, display_name=n)
                    for m, n in instructors.get(c.id, [])
                ],
                my_role=roles.get(c.id),
                created_at=c.created_at,
            )
            for c in classes
        ]

    # ------------------------------------------------------------------ classes

    async def create(self, actor: AcademyMembership, data: ClassCreate) -> ClassRead:
        academy_class = AcademyClass(
            id=uuid.uuid4(),
            academy_id=actor.academy_id,
            name=data.name,
            description=data.description,
            subject=data.subject,
            status=ClassStatus.ACTIVE,
            created_by=actor.id,
        )
        self.classes.add(academy_class)
        await self.session.commit()
        await self.session.refresh(academy_class)
        return (await self._read_models([academy_class], actor))[0]

    async def list_classes(
        self,
        actor: AcademyMembership,
        params: PaginationParams,
        *,
        status: ClassStatus | None,
        mine: bool,
    ) -> tuple[list[ClassRead], int]:
        """강사 이상: 학원 전체 (mine=true면 담당 반). 학생: 배정된 반만."""
        if not is_staff(actor):
            within = enrolled_class_ids(actor.id)
        elif mine:
            within = taught_class_ids(actor)
        else:
            within = None
        classes, total = await self.classes.list_classes(
            actor.academy_id, params, status=status, within=within
        )
        return await self._read_models(classes, actor), total

    async def get(self, actor: AcademyMembership, class_id: uuid.UUID) -> ClassRead:
        academy_class = await self.access.require_class_reader(actor, class_id)
        return (await self._read_models([academy_class], actor))[0]

    async def update(
        self, actor: AcademyMembership, class_id: uuid.UUID, data: ClassUpdate
    ) -> ClassRead:
        academy_class = await self.access.get_class(actor.academy_id, class_id, for_update=True)
        for field, value in data.changes().items():
            setattr(academy_class, field, value)
        await self.session.commit()
        await self.session.refresh(academy_class)
        return (await self._read_models([academy_class], actor))[0]

    # ------------------------------------------------------------------ members

    async def list_members(
        self,
        actor: AcademyMembership,
        class_id: uuid.UUID,
        params: PaginationParams,
        *,
        status: ClassMemberStatus,
        role: ClassMemberRole | None,
    ) -> tuple[list[ClassMemberRead], int]:
        await self.access.get_class(actor.academy_id, class_id)
        rows, total = await self.classes.list_members(class_id, params, status=status, role=role)
        return [self._member(*row) for row in rows], total

    @staticmethod
    def _member(seat, membership, profile) -> ClassMemberRead:  # type: ignore[no-untyped-def]
        return ClassMemberRead(
            id=seat.id,
            class_id=seat.class_id,
            membership_id=membership.id,
            user_id=profile.id,
            display_name=profile.display_name,
            avatar_path=profile.avatar_path,
            role=seat.role,
            status=seat.status,
            joined_at=seat.joined_at,
            ended_at=seat.ended_at,
        )

    async def add_member(
        self, actor: AcademyMembership, class_id: uuid.UUID, membership_id: uuid.UUID
    ) -> ClassMemberRead:
        """학생 배정 또는 담당 강사 지정. 담당 강사는 학생만 배정할 수 있다."""
        academy_class = await self.access.require_class_manager(actor, class_id)
        ensure_class_active(academy_class)

        target = await self.memberships.get_active_in_academy(actor.academy_id, membership_id)
        if target is None:
            raise UnprocessableError(
                "Member not found in this academy", code=ErrorCode.INVALID_CLASS_MEMBER
            )
        role = (
            ClassMemberRole.STUDENT
            if target.role == MembershipRole.STUDENT
            else ClassMemberRole.INSTRUCTOR
        )
        if role == ClassMemberRole.INSTRUCTOR and not is_admin(actor):
            raise ForbiddenError("Only academy managers can assign class instructors")

        seat_id = await self.classes.activate_member(
            academy_id=actor.academy_id,
            class_id=class_id,
            membership_id=target.id,
            role=role,
            now=clock.utc_now(),
        )
        if seat_id is None:
            await self.session.rollback()
            raise ConflictError("Already assigned to this class", code=ErrorCode.ALREADY_IN_CLASS)
        await self.session.commit()
        return self._member(*await self.classes.member_view(seat_id))

    async def remove_member(
        self, actor: AcademyMembership, class_id: uuid.UUID, class_member_id: uuid.UUID
    ) -> None:
        await self.access.require_class_manager(actor, class_id)
        seat = await self.classes.get_member_for_update(class_id, class_member_id)
        if seat is None or seat.status != ClassMemberStatus.ACTIVE:
            raise NotFoundError("Class member not found")
        if seat.role == ClassMemberRole.INSTRUCTOR and not is_admin(actor):
            raise ForbiddenError("Only academy managers can unassign class instructors")
        seat.status = ClassMemberStatus.REMOVED
        seat.ended_at = clock.utc_now()
        await self.session.commit()
