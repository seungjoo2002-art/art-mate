"""학원 등록·조회·심사 (학원 단위 데이터 접근 규칙의 중심)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ErrorCode, NotFoundError
from app.models.academy import Academy
from app.models.enums import (
    AcademyStatus,
    MembershipRole,
    MembershipStatus,
    ReviewDecision,
    UserType,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.repositories.academies import AcademyRepository
from app.repositories.memberships import MembershipRepository
from app.schemas.academy import AcademyCreate, AcademyReview
from app.schemas.common import PaginationParams

# 한 강사가 동시에 승인 대기로 둘 수 있는 학원 등록 신청 수 (스팸 방지)
MAX_PENDING_ACADEMY_APPLICATIONS = 3


class AcademyService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.academies = AcademyRepository(session)
        self.memberships = MembershipRepository(session)

    async def create(
        self, owner: Profile, data: AcademyCreate
    ) -> tuple[Academy, AcademyMembership]:
        """강사의 학원 등록 신청. 학원은 PENDING_APPROVAL, 신청자는 OWNER 소속으로 함께 생성."""
        pending = await self.academies.count_pending_created_by(owner.id)
        if pending >= MAX_PENDING_ACADEMY_APPLICATIONS:
            raise ConflictError(
                "Too many academy applications are waiting for approval",
                code=ErrorCode.ACADEMY_APPLICATION_LIMIT,
            )
        now = datetime.now(UTC)
        academy = Academy(
            id=uuid.uuid4(),
            name=data.name,
            description=data.description,
            status=AcademyStatus.PENDING_APPROVAL,
            created_by=owner.id,
        )
        membership = AcademyMembership(
            id=uuid.uuid4(),
            academy_id=academy.id,
            user_id=owner.id,
            role=MembershipRole.OWNER,
            status=MembershipStatus.ACTIVE,
            joined_at=now,
        )
        self.academies.add(academy)
        await self.session.flush()  # FK 순서 보장
        self.memberships.add(membership)
        await self.session.commit()
        await self.session.refresh(academy)
        await self.session.refresh(membership)
        return academy, membership

    async def list_directory(
        self, params: PaginationParams, query: str | None
    ) -> tuple[list[Academy], int]:
        """학원 찾기: 승인된(ACTIVE) 학원만, 이름 검색."""
        return await self.academies.list_by_status(AcademyStatus.ACTIVE, params, query)

    async def list_mine(
        self, profile: Profile, params: PaginationParams
    ) -> tuple[list[tuple[Academy, AcademyMembership]], int]:
        return await self.academies.list_for_member(profile.id, params)

    async def get_visible(
        self, academy_id: uuid.UUID, viewer: Profile
    ) -> tuple[Academy, AcademyMembership | None]:
        """ACTIVE 학원은 누구나, 그 외 상태는 소속 멤버와 시스템 ADMIN만 볼 수 있다."""
        academy = await self.academies.get(academy_id)
        if academy is None:
            raise NotFoundError("Academy not found")
        membership = await self.memberships.get_active_by_user(academy_id, viewer.id)
        visible = (
            academy.status == AcademyStatus.ACTIVE
            or membership is not None
            or viewer.user_type == UserType.ADMIN
        )
        if not visible:
            raise NotFoundError("Academy not found")
        return academy, membership

    # ------------------------------------------------------------------ system admin

    async def list_for_review(
        self, status: AcademyStatus, params: PaginationParams
    ) -> tuple[list[Academy], int]:
        return await self.academies.list_by_status_oldest_first(status, params)

    async def review(self, academy_id: uuid.UUID, admin: Profile, data: AcademyReview) -> Academy:
        academy = await self.academies.get_for_update(academy_id)
        if academy is None:
            raise NotFoundError("Academy not found")
        if academy.status != AcademyStatus.PENDING_APPROVAL:
            raise ConflictError(
                "Academy has already been reviewed", code=ErrorCode.ACADEMY_ALREADY_REVIEWED
            )
        academy.status = (
            AcademyStatus.ACTIVE
            if data.decision == ReviewDecision.APPROVE
            else AcademyStatus.REJECTED
        )
        academy.reviewed_by = admin.id
        academy.reviewed_at = datetime.now(UTC)
        academy.review_note = data.note
        await self.session.commit()
        await self.session.refresh(academy)
        return academy
