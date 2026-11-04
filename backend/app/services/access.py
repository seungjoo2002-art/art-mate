"""학원 운영 데이터(v0.3) 권한 판단.

역할 기준 (학원 역할 `academy_memberships.role`, 반 역할 `class_memberships.role`)
- 학원 관리자 (OWNER/MANAGER): 학원의 모든 반·학생을 관리한다.
- 강사 (INSTRUCTOR 이상): 반·일정·주제 **읽기**는 학원 전체. 쓰기와 학생 데이터(출석·과제 완료)는
  **담당 반 / 담당 학생**만.
  - 담당 반: 본인이 담당 강사(class_memberships.role=INSTRUCTOR, ACTIVE)로 지정된 ACTIVE 반
  - 담당 학생: 담당 반에 ACTIVE로 배정된, 학원 소속이 ACTIVE인 학생
- 학생: 배정된 반의 일정·주제, 본인 출석·과제만.

응답 규칙 (v0.2와 동일)
- 다른 학원 리소스, 학생에게 보이지 않는 리소스 → 404 (존재 여부 비노출)
- 같은 학원이지만 역할·담당 범위 부족 → 403
"""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.academy_class import AcademyClass, ClassMembership
from app.models.enums import (
    ACADEMY_ADMIN_ROLES,
    ACADEMY_STAFF_ROLES,
    ClassMemberRole,
    ClassMemberStatus,
    ClassStatus,
    MembershipRole,
    MembershipStatus,
)
from app.models.membership import AcademyMembership


def is_admin(actor: AcademyMembership) -> bool:
    return actor.role in ACADEMY_ADMIN_ROLES


def is_staff(actor: AcademyMembership) -> bool:
    return actor.role in ACADEMY_STAFF_ROLES


def taught_class_ids(actor: AcademyMembership) -> Select[tuple[uuid.UUID]]:
    """actor가 담당 강사로 지정된 ACTIVE 반 ID."""
    return classes_taught_by(actor.academy_id, actor.id)


def classes_taught_by(
    academy_id: uuid.UUID, instructor_membership_id: uuid.UUID
) -> Select[tuple[uuid.UUID]]:
    return (
        select(ClassMembership.class_id)
        .join(AcademyClass, AcademyClass.id == ClassMembership.class_id)
        .where(
            ClassMembership.academy_id == academy_id,
            ClassMembership.membership_id == instructor_membership_id,
            ClassMembership.role == ClassMemberRole.INSTRUCTOR,
            ClassMembership.status == ClassMemberStatus.ACTIVE,
            AcademyClass.status == ClassStatus.ACTIVE,
        )
    )


def enrolled_class_ids(student_membership_id: uuid.UUID) -> Select[tuple[uuid.UUID]]:
    """학생이 ACTIVE로 배정된 반 ID (반 상태와 무관)."""
    return select(ClassMembership.class_id).where(
        ClassMembership.membership_id == student_membership_id,
        ClassMembership.role == ClassMemberRole.STUDENT,
        ClassMembership.status == ClassMemberStatus.ACTIVE,
    )


def scoped_class_ids(actor: AcademyMembership, *, mine: bool) -> Select[tuple[uuid.UUID]]:
    """강사 화면의 대상 반: 학원 관리자 + mine=False 이면 학원의 ACTIVE 반 전체, 아니면 담당 반."""
    if is_admin(actor) and not mine:
        return select(AcademyClass.id).where(
            AcademyClass.academy_id == actor.academy_id, AcademyClass.status == ClassStatus.ACTIVE
        )
    return taught_class_ids(actor)


def class_student_ids(class_ids: Select[tuple[uuid.UUID]]) -> Select[tuple[uuid.UUID]]:
    """주어진 반들에 ACTIVE로 배정된 (학원 소속도 ACTIVE인) 학생 membership ID."""
    return (
        select(ClassMembership.membership_id)
        .join(AcademyMembership, AcademyMembership.id == ClassMembership.membership_id)
        .where(
            ClassMembership.class_id.in_(class_ids),
            ClassMembership.role == ClassMemberRole.STUDENT,
            ClassMembership.status == ClassMemberStatus.ACTIVE,
            AcademyMembership.status == MembershipStatus.ACTIVE,
        )
        .distinct()
    )


def managed_student_ids(actor: AcademyMembership) -> Select[tuple[uuid.UUID]]:
    """actor가 학생 데이터를 볼 수 있는 학생 membership ID."""
    if is_admin(actor):
        return select(AcademyMembership.id).where(
            AcademyMembership.academy_id == actor.academy_id,
            AcademyMembership.role == MembershipRole.STUDENT,
            AcademyMembership.status == MembershipStatus.ACTIVE,
        )
    return class_student_ids(taught_class_ids(actor))


class AccessService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_class(
        self, academy_id: uuid.UUID, class_id: uuid.UUID, *, for_update: bool = False
    ) -> AcademyClass:
        stmt = select(AcademyClass).where(
            AcademyClass.academy_id == academy_id, AcademyClass.id == class_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        academy_class = (await self.session.execute(stmt)).scalar_one_or_none()
        if academy_class is None:
            raise NotFoundError("Class not found")
        return academy_class

    async def class_role(
        self, class_id: uuid.UUID, membership_id: uuid.UUID
    ) -> ClassMemberRole | None:
        stmt = select(ClassMembership.role).where(
            ClassMembership.class_id == class_id,
            ClassMembership.membership_id == membership_id,
            ClassMembership.status == ClassMemberStatus.ACTIVE,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def require_class_reader(
        self, actor: AcademyMembership, class_id: uuid.UUID
    ) -> AcademyClass:
        """강사 이상은 학원의 모든 반, 학생은 배정된 반만 (아니면 404)."""
        academy_class = await self.get_class(actor.academy_id, class_id)
        if not is_staff(actor) and await self.class_role(class_id, actor.id) is None:
            raise NotFoundError("Class not found")
        return academy_class

    async def require_class_manager(
        self, actor: AcademyMembership, class_id: uuid.UUID, *, for_update: bool = False
    ) -> AcademyClass:
        """학원 관리자 또는 그 반의 담당 강사. 학생에게는 반 존재를 숨긴다(404)."""
        academy_class = await self.get_class(actor.academy_id, class_id, for_update=for_update)
        if is_admin(actor):
            return academy_class
        if not is_staff(actor):
            if await self.class_role(class_id, actor.id) is None:
                raise NotFoundError("Class not found")
            raise ForbiddenError()
        if await self.class_role(class_id, actor.id) != ClassMemberRole.INSTRUCTOR:
            raise ForbiddenError("Only the class instructor or academy managers can do this")
        return academy_class

    async def get_student(
        self, academy_id: uuid.UUID, student_membership_id: uuid.UUID
    ) -> AcademyMembership | None:
        stmt = select(AcademyMembership).where(
            AcademyMembership.academy_id == academy_id,
            AcademyMembership.id == student_membership_id,
            AcademyMembership.role == MembershipRole.STUDENT,
            AcademyMembership.status == MembershipStatus.ACTIVE,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def is_managed_student(
        self, actor: AcademyMembership, student_membership_id: uuid.UUID
    ) -> bool:
        stmt = managed_student_ids(actor).subquery()
        found = await self.session.execute(
            select(stmt.c[0]).where(stmt.c[0] == student_membership_id).limit(1)
        )
        return found.first() is not None

    async def require_managed_student(
        self, actor: AcademyMembership, student_membership_id: uuid.UUID
    ) -> AcademyMembership:
        """학원의 ACTIVE 학생이 아니면 404, 담당 학생이 아니면 403."""
        if not is_staff(actor):
            raise ForbiddenError()
        student = await self.get_student(actor.academy_id, student_membership_id)
        if student is None:
            raise NotFoundError("Student not found")
        if not await self.is_managed_student(actor, student_membership_id):
            raise ForbiddenError("This student is not in your classes")
        return student
