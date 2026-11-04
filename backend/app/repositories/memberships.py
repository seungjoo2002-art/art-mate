import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academy import Academy
from app.models.enums import JoinRequestStatus, MembershipRole, MembershipStatus
from app.models.membership import AcademyJoinRequest, AcademyMembership
from app.models.profile import Profile
from app.repositories.pagination import fetch_page
from app.schemas.common import PaginationParams


class MembershipRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user(
        self, academy_id: uuid.UUID, user_id: uuid.UUID
    ) -> AcademyMembership | None:
        stmt = select(AcademyMembership).where(
            AcademyMembership.academy_id == academy_id, AcademyMembership.user_id == user_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_active_by_user(
        self, academy_id: uuid.UUID, user_id: uuid.UUID
    ) -> AcademyMembership | None:
        membership = await self.get_by_user(academy_id, user_id)
        if membership is None or membership.status != MembershipStatus.ACTIVE:
            return None
        return membership

    async def get_active_in_academy(
        self, academy_id: uuid.UUID, membership_id: uuid.UUID
    ) -> AcademyMembership | None:
        stmt = select(AcademyMembership).where(
            AcademyMembership.academy_id == academy_id,
            AcademyMembership.id == membership_id,
            AcademyMembership.status == MembershipStatus.ACTIVE,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_in_academy_for_update(
        self, academy_id: uuid.UUID, membership_id: uuid.UUID
    ) -> AcademyMembership | None:
        stmt = (
            select(AcademyMembership)
            .where(
                AcademyMembership.academy_id == academy_id, AcademyMembership.id == membership_id
            )
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def add(self, membership: AcademyMembership) -> None:
        self.session.add(membership)

    async def activate(
        self, academy_id: uuid.UUID, user_id: uuid.UUID, role: MembershipRole, now: datetime
    ) -> None:
        """소속을 ACTIVE로 만든다. 탈퇴·제외 이력이 있으면 같은 행을 재활성화한다.

        이미 ACTIVE인 소속은 바꾸지 않는다 (역할이 덮어써지지 않도록).
        """
        stmt = insert(AcademyMembership).values(
            id=uuid.uuid4(),
            academy_id=academy_id,
            user_id=user_id,
            role=role,
            status=MembershipStatus.ACTIVE,
            joined_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[AcademyMembership.academy_id, AcademyMembership.user_id],
            set_={
                "role": stmt.excluded.role,
                "status": MembershipStatus.ACTIVE,
                "joined_at": now,
                "left_at": None,
                "updated_at": func.now(),
            },
            where=AcademyMembership.status != MembershipStatus.ACTIVE,
        )
        await self.session.execute(stmt)

    async def list_members(
        self,
        academy_id: uuid.UUID,
        params: PaginationParams,
        *,
        status: MembershipStatus,
        role: MembershipRole | None = None,
    ) -> tuple[list[tuple[AcademyMembership, Profile]], int]:
        stmt = (
            select(AcademyMembership, Profile)
            .join(Profile, Profile.id == AcademyMembership.user_id)
            .where(AcademyMembership.academy_id == academy_id, AcademyMembership.status == status)
        )
        if role is not None:
            stmt = stmt.where(AcademyMembership.role == role)
        stmt = stmt.order_by(AcademyMembership.role, Profile.display_name, AcademyMembership.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return [(row[0], row[1]) for row in rows], total


class JoinRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def add(self, join_request: AcademyJoinRequest) -> None:
        self.session.add(join_request)

    async def get_pending(
        self, academy_id: uuid.UUID, user_id: uuid.UUID
    ) -> AcademyJoinRequest | None:
        stmt = select(AcademyJoinRequest).where(
            AcademyJoinRequest.academy_id == academy_id,
            AcademyJoinRequest.user_id == user_id,
            AcademyJoinRequest.status == JoinRequestStatus.PENDING,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_in_academy_for_update(
        self, academy_id: uuid.UUID, request_id: uuid.UUID
    ) -> AcademyJoinRequest | None:
        stmt = (
            select(AcademyJoinRequest)
            .where(AcademyJoinRequest.academy_id == academy_id, AcademyJoinRequest.id == request_id)
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_academy(
        self, academy_id: uuid.UUID, status: JoinRequestStatus, params: PaginationParams
    ) -> tuple[list[tuple[AcademyJoinRequest, Profile]], int]:
        stmt = (
            select(AcademyJoinRequest, Profile)
            .join(Profile, Profile.id == AcademyJoinRequest.user_id)
            .where(AcademyJoinRequest.academy_id == academy_id, AcademyJoinRequest.status == status)
            .order_by(AcademyJoinRequest.created_at, AcademyJoinRequest.id)
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [(row[0], row[1]) for row in rows], total

    async def list_for_user(
        self, user_id: uuid.UUID, params: PaginationParams
    ) -> tuple[list[tuple[AcademyJoinRequest, str]], int]:
        stmt = (
            select(AcademyJoinRequest, Academy.name)
            .join(Academy, Academy.id == AcademyJoinRequest.academy_id)
            .where(AcademyJoinRequest.user_id == user_id)
            .order_by(AcademyJoinRequest.created_at.desc(), AcademyJoinRequest.id)
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [(row[0], row[1]) for row in rows], total
