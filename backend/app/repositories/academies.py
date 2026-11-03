import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.academy import Academy
from app.models.enums import AcademyStatus, MembershipStatus
from app.models.membership import AcademyMembership
from app.repositories.pagination import fetch_page
from app.schemas.common import PaginationParams


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class AcademyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, academy_id: uuid.UUID) -> Academy | None:
        return await self.session.get(Academy, academy_id)

    async def get_for_update(self, academy_id: uuid.UUID) -> Academy | None:
        stmt = select(Academy).where(Academy.id == academy_id).with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    def add(self, academy: Academy) -> None:
        self.session.add(academy)

    async def count_pending_created_by(self, user_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            Academy.created_by == user_id, Academy.status == AcademyStatus.PENDING_APPROVAL
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def list_by_status(
        self, status: AcademyStatus, params: PaginationParams, query: str | None = None
    ) -> tuple[list[Academy], int]:
        stmt = select(Academy).where(Academy.status == status)
        if query:
            stmt = stmt.where(Academy.name.ilike(f"%{_escape_like(query)}%", escape="\\"))
        stmt = stmt.order_by(Academy.name, Academy.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return [row[0] for row in rows], total

    async def list_by_status_oldest_first(
        self, status: AcademyStatus, params: PaginationParams
    ) -> tuple[list[Academy], int]:
        stmt = select(Academy).where(Academy.status == status).order_by(Academy.created_at)
        rows, total = await fetch_page(self.session, stmt, params)
        return [row[0] for row in rows], total

    async def list_for_member(
        self, user_id: uuid.UUID, params: PaginationParams
    ) -> tuple[list[tuple[Academy, AcademyMembership]], int]:
        """사용자가 ACTIVE로 소속된 학원 (학원 상태와 무관: 승인 대기 중인 OWNER 학원 포함)."""
        stmt = (
            select(Academy, AcademyMembership)
            .join(AcademyMembership, AcademyMembership.academy_id == Academy.id)
            .where(
                AcademyMembership.user_id == user_id,
                AcademyMembership.status == MembershipStatus.ACTIVE,
            )
            .order_by(Academy.name, Academy.id)
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [(row[0], row[1]) for row in rows], total
