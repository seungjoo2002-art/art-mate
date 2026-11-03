"""학원 가입 요청·승인과 소속 관리.

요청(academy_join_requests)과 실제 소속(academy_memberships)은 별도 테이블이다.
- 요청: PENDING → APPROVED / REJECTED (이력으로 남음)
- 소속: ACTIVE → LEFT(본인 탈퇴) / REMOVED(관리자 제외), 재가입 승인 시 같은 행을 ACTIVE로 재활성화
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ErrorCode, ForbiddenError, NotFoundError
from app.models.enums import (
    AcademyStatus,
    JoinRequestStatus,
    MembershipRole,
    MembershipStatus,
    ReviewDecision,
    UserType,
)
from app.models.membership import AcademyJoinRequest, AcademyMembership
from app.models.profile import Profile
from app.repositories.academies import AcademyRepository
from app.repositories.memberships import JoinRequestRepository, MembershipRepository
from app.repositories.profiles import ProfileRepository
from app.schemas.academy import JoinRequestCreate, JoinRequestReview
from app.schemas.common import PaginationParams

# 사용자 유형 → 가입 요청 시 신청되는 학원 역할
_REQUESTED_ROLE_BY_USER_TYPE: dict[UserType, MembershipRole] = {
    UserType.STUDENT: MembershipRole.STUDENT,
    UserType.INSTRUCTOR: MembershipRole.INSTRUCTOR,
}


class MembershipService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.academies = AcademyRepository(session)
        self.memberships = MembershipRepository(session)
        self.join_requests = JoinRequestRepository(session)
        self.profiles = ProfileRepository(session)

    # ------------------------------------------------------------------ join requests

    async def request_to_join(
        self, academy_id: uuid.UUID, applicant: Profile, data: JoinRequestCreate
    ) -> AcademyJoinRequest:
        requested_role = _REQUESTED_ROLE_BY_USER_TYPE.get(applicant.user_type)
        if requested_role is None:  # 시스템 ADMIN은 학원 소속 대상이 아니다
            raise ForbiddenError("This account type cannot join an academy")

        academy = await self.academies.get(academy_id)
        existing = await self.memberships.get_active_by_user(academy_id, applicant.id)
        if academy is None or (academy.status != AcademyStatus.ACTIVE and existing is None):
            raise NotFoundError("Academy not found")
        if existing is not None:
            raise ConflictError(
                "You are already a member of this academy", code=ErrorCode.ALREADY_MEMBER
            )
        if academy.status != AcademyStatus.ACTIVE:
            raise ConflictError(
                "This academy is not accepting members",
                code=ErrorCode.ACADEMY_NOT_ACCEPTING_MEMBERS,
            )
        if await self.join_requests.get_pending(academy_id, applicant.id) is not None:
            raise self._already_pending()

        join_request = AcademyJoinRequest(
            id=uuid.uuid4(),
            academy_id=academy_id,
            user_id=applicant.id,
            requested_role=requested_role,
            status=JoinRequestStatus.PENDING,
            message=data.message,
        )
        self.join_requests.add(join_request)
        try:
            await self.session.commit()
        except IntegrityError:
            # 동시에 들어온 중복 요청: 부분 유니크 인덱스(uq_academy_join_requests_pending)가 차단
            await self.session.rollback()
            raise self._already_pending() from None
        await self.session.refresh(join_request)
        return join_request

    @staticmethod
    def _already_pending() -> ConflictError:
        return ConflictError(
            "A join request is already pending", code=ErrorCode.JOIN_REQUEST_ALREADY_PENDING
        )

    async def list_join_requests(
        self, academy_id: uuid.UUID, status: JoinRequestStatus, params: PaginationParams
    ) -> tuple[list[tuple[AcademyJoinRequest, Profile]], int]:
        return await self.join_requests.list_for_academy(academy_id, status, params)

    async def list_my_join_requests(
        self, user: Profile, params: PaginationParams
    ) -> tuple[list[tuple[AcademyJoinRequest, str]], int]:
        return await self.join_requests.list_for_user(user.id, params)

    async def review_join_request(
        self,
        academy_id: uuid.UUID,
        request_id: uuid.UUID,
        reviewer: AcademyMembership,
        data: JoinRequestReview,
    ) -> AcademyJoinRequest:
        # 행 잠금: 두 관리자가 동시에 처리해도 한 번만 처리된다
        join_request = await self.join_requests.get_in_academy_for_update(academy_id, request_id)
        if join_request is None:
            raise NotFoundError("Join request not found")
        if join_request.status != JoinRequestStatus.PENDING:
            raise ConflictError(
                "Join request has already been reviewed",
                code=ErrorCode.JOIN_REQUEST_ALREADY_REVIEWED,
            )

        now = datetime.now(UTC)
        if data.decision == ReviewDecision.APPROVE:
            applicant = await self.profiles.get(join_request.user_id)
            if applicant is None or not applicant.is_active:
                raise ConflictError(
                    "Applicant account is not active", code=ErrorCode.APPLICANT_INACTIVE
                )
            await self.memberships.activate(
                academy_id, join_request.user_id, join_request.requested_role, now
            )
            join_request.status = JoinRequestStatus.APPROVED
        else:
            join_request.status = JoinRequestStatus.REJECTED

        join_request.reviewed_by = reviewer.user_id
        join_request.reviewed_at = now
        join_request.review_note = data.note
        await self.session.commit()
        await self.session.refresh(join_request)
        return join_request

    # ------------------------------------------------------------------ members

    async def list_members(
        self,
        academy_id: uuid.UUID,
        params: PaginationParams,
        *,
        status: MembershipStatus,
        role: MembershipRole | None,
    ) -> tuple[list[tuple[AcademyMembership, Profile]], int]:
        return await self.memberships.list_members(academy_id, params, status=status, role=role)

    async def leave(self, membership: AcademyMembership) -> None:
        if membership.role == MembershipRole.OWNER:
            raise ConflictError(
                "The academy owner cannot leave the academy", code=ErrorCode.OWNER_CANNOT_LEAVE
            )
        locked = await self.memberships.get_in_academy_for_update(
            membership.academy_id, membership.id
        )
        if locked is None or locked.status != MembershipStatus.ACTIVE:
            raise NotFoundError("Membership not found")
        locked.status = MembershipStatus.LEFT
        locked.left_at = datetime.now(UTC)
        await self.session.commit()

    async def change_role(
        self,
        academy_id: uuid.UUID,
        membership_id: uuid.UUID,
        actor: AcademyMembership,
        new_role: MembershipRole,
    ) -> tuple[AcademyMembership, Profile]:
        """OWNER가 소속 강사를 MANAGER로 지정/해제한다."""
        target = await self.memberships.get_in_academy_for_update(academy_id, membership_id)
        if target is None or target.status != MembershipStatus.ACTIVE:
            raise NotFoundError("Member not found")
        if target.id == actor.id or target.role not in {
            MembershipRole.INSTRUCTOR,
            MembershipRole.MANAGER,
        }:
            raise ConflictError(
                "Only instructors can be promoted to or demoted from manager",
                code=ErrorCode.MEMBER_ROLE_NOT_CHANGEABLE,
            )
        target.role = new_role
        await self.session.commit()
        await self.session.refresh(target)
        profile = await self.profiles.get(target.user_id)
        assert profile is not None
        return target, profile

    async def remove_member(
        self, academy_id: uuid.UUID, membership_id: uuid.UUID, actor: AcademyMembership
    ) -> None:
        """학원 관리자가 멤버를 내보낸다. OWNER는 제외 불가, MANAGER는 MANAGER를 제외할 수 없다."""
        target = await self.memberships.get_in_academy_for_update(academy_id, membership_id)
        if target is None or target.status != MembershipStatus.ACTIVE:
            raise NotFoundError("Member not found")
        if target.id == actor.id:
            raise ConflictError("Use the leave endpoint to leave the academy")
        if target.role == MembershipRole.OWNER or (
            target.role == MembershipRole.MANAGER and actor.role != MembershipRole.OWNER
        ):
            raise ForbiddenError("You cannot remove this member")
        target.status = MembershipStatus.REMOVED
        target.left_at = datetime.now(UTC)
        await self.session.commit()
