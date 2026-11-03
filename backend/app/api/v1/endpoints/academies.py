"""학원·소속·가입 요청 API.

접근 규칙 요약
- 학원 등록 신청: INSTRUCTOR (시스템 ADMIN 승인 후 ACTIVE)
- 학원 찾기/상세: 로그인 사용자. ACTIVE가 아닌 학원은 소속 멤버·시스템 ADMIN만
- 멤버 목록: OWNER/MANAGER/INSTRUCTOR (학생은 다른 학생 정보를 볼 수 없음)
- 가입 요청 목록·승인·거절, 멤버 제외: OWNER/MANAGER
- MANAGER 지정/해제: OWNER
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import ActiveProfile, DbSession, require_academy_roles, require_user_types
from app.api.responses import AUTH_ERRORS, error_responses
from app.models.enums import (
    ACADEMY_ADMIN_ROLES,
    ACADEMY_STAFF_ROLES,
    JoinRequestStatus,
    MembershipRole,
    MembershipStatus,
    UserType,
)
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.schemas.academy import (
    AcademyCreate,
    AcademyListItem,
    AcademyRead,
    AcademySummary,
    Applicant,
    JoinRequestCreate,
    JoinRequestRead,
    JoinRequestReview,
    JoinRequestWithApplicant,
    MemberRead,
    MemberRoleUpdate,
    MyMembership,
)
from app.schemas.common import Page, PaginationQuery
from app.services.academies import AcademyService
from app.services.memberships import MembershipService

router = APIRouter(prefix="/academies", tags=["academies"])

AcademyAdmin = Annotated[AcademyMembership, Depends(require_academy_roles(*ACADEMY_ADMIN_ROLES))]
AcademyStaff = Annotated[AcademyMembership, Depends(require_academy_roles(*ACADEMY_STAFF_ROLES))]
AcademyOwner = Annotated[AcademyMembership, Depends(require_academy_roles(MembershipRole.OWNER))]
AcademyMember = Annotated[AcademyMembership, Depends(require_academy_roles())]
Instructor = Annotated[Profile, Depends(require_user_types(UserType.INSTRUCTOR))]

NOT_MEMBER = error_responses(404)


def _member(membership: AcademyMembership, profile: Profile) -> MemberRead:
    return MemberRead(
        id=membership.id,
        user_id=membership.user_id,
        display_name=profile.display_name,
        avatar_path=profile.avatar_path,
        role=membership.role,
        status=membership.status,
        joined_at=membership.joined_at,
        left_at=membership.left_at,
    )


# ----------------------------------------------------------------------------- academies


@router.post(
    "",
    summary="학원 등록 신청 (강사)",
    description=(
        "학원은 PENDING_APPROVAL로 생성되고 신청자는 OWNER가 된다. 시스템 ADMIN 승인 후 ACTIVE."
    ),
    status_code=status.HTTP_201_CREATED,
    responses=AUTH_ERRORS | error_responses(409, 422),
)
async def create_academy(data: AcademyCreate, owner: Instructor, session: DbSession) -> AcademyRead:
    academy, membership = await AcademyService(session).create(owner, data)
    return AcademyRead(
        **AcademySummary.model_validate(academy).model_dump(),
        my_membership=MyMembership.model_validate(membership),
    )


@router.get(
    "",
    summary="학원 목록",
    description=(
        "기본: 승인된(ACTIVE) 학원 찾기 (`q`로 이름 검색). `mine=true`: 내가 소속된 학원과 내 역할."
    ),
    responses=AUTH_ERRORS,
)
async def list_academies(
    profile: ActiveProfile,
    session: DbSession,
    pagination: PaginationQuery,
    q: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    mine: bool = False,
) -> Page[AcademyListItem]:
    service = AcademyService(session)
    if mine:
        pairs, total = await service.list_mine(profile, pagination)
        items = [
            AcademyListItem(
                **AcademySummary.model_validate(academy).model_dump(), my_role=membership.role
            )
            for academy, membership in pairs
        ]
    else:
        academies, total = await service.list_directory(pagination, q)
        items = [AcademyListItem.model_validate(academy) for academy in academies]
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.get("/{academy_id}", summary="학원 상세", responses=AUTH_ERRORS | NOT_MEMBER)
async def get_academy(
    academy_id: uuid.UUID, profile: ActiveProfile, session: DbSession
) -> AcademyRead:
    academy, membership = await AcademyService(session).get_visible(academy_id, profile)
    return AcademyRead(
        **AcademySummary.model_validate(academy).model_dump(),
        my_membership=MyMembership.model_validate(membership) if membership else None,
    )


# ----------------------------------------------------------------------------- members


@router.get(
    "/{academy_id}/members",
    summary="학원 멤버 목록 (OWNER/MANAGER/INSTRUCTOR)",
    responses=AUTH_ERRORS | NOT_MEMBER,
)
async def list_members(
    academy_id: uuid.UUID,
    _: AcademyStaff,
    session: DbSession,
    pagination: PaginationQuery,
    role: MembershipRole | None = None,
    member_status: Annotated[MembershipStatus, Query(alias="status")] = MembershipStatus.ACTIVE,
) -> Page[MemberRead]:
    pairs, total = await MembershipService(session).list_members(
        academy_id, pagination, status=member_status, role=role
    )
    items = [_member(membership, profile) for membership, profile in pairs]
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


# 주의: "/members/me"는 "/members/{membership_id}"보다 먼저 선언해야 한다.
@router.delete(
    "/{academy_id}/members/me",
    summary="학원 탈퇴 (본인)",
    description="OWNER는 탈퇴할 수 없다 (409 OWNER_CANNOT_LEAVE).",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=AUTH_ERRORS | NOT_MEMBER | error_responses(409),
)
async def leave_academy(
    academy_id: uuid.UUID, membership: AcademyMember, session: DbSession
) -> None:
    await MembershipService(session).leave(membership)


@router.patch(
    "/{academy_id}/members/{membership_id}",
    summary="MANAGER 지정/해제 (OWNER)",
    responses=AUTH_ERRORS | NOT_MEMBER | error_responses(409, 422),
)
async def change_member_role(
    academy_id: uuid.UUID,
    membership_id: uuid.UUID,
    data: MemberRoleUpdate,
    actor: AcademyOwner,
    session: DbSession,
) -> MemberRead:
    membership, profile = await MembershipService(session).change_role(
        academy_id, membership_id, actor, data.role
    )
    return _member(membership, profile)


@router.delete(
    "/{academy_id}/members/{membership_id}",
    summary="멤버 내보내기 (OWNER/MANAGER)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=AUTH_ERRORS | NOT_MEMBER | error_responses(409),
)
async def remove_member(
    academy_id: uuid.UUID, membership_id: uuid.UUID, actor: AcademyAdmin, session: DbSession
) -> None:
    await MembershipService(session).remove_member(academy_id, membership_id, actor)


# ----------------------------------------------------------------------------- join requests


@router.post(
    "/{academy_id}/join-requests",
    summary="학원 가입 요청 (학생·강사)",
    description="학생은 STUDENT, 강사는 INSTRUCTOR 역할로 신청된다 (사용자 유형에서 결정).",
    status_code=status.HTTP_201_CREATED,
    responses=AUTH_ERRORS | NOT_MEMBER | error_responses(409, 422),
)
async def create_join_request(
    academy_id: uuid.UUID, data: JoinRequestCreate, profile: ActiveProfile, session: DbSession
) -> JoinRequestRead:
    join_request = await MembershipService(session).request_to_join(academy_id, profile, data)
    return JoinRequestRead.model_validate(join_request)


@router.get(
    "/{academy_id}/join-requests",
    summary="가입 요청 목록 (OWNER/MANAGER)",
    responses=AUTH_ERRORS | NOT_MEMBER,
)
async def list_join_requests(
    academy_id: uuid.UUID,
    _: AcademyAdmin,
    session: DbSession,
    pagination: PaginationQuery,
    request_status: Annotated[JoinRequestStatus, Query(alias="status")] = JoinRequestStatus.PENDING,
) -> Page[JoinRequestWithApplicant]:
    pairs, total = await MembershipService(session).list_join_requests(
        academy_id, request_status, pagination
    )
    items = [
        JoinRequestWithApplicant(
            **JoinRequestRead.model_validate(req).model_dump(),
            applicant=Applicant.model_validate(profile),
        )
        for req, profile in pairs
    ]
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.patch(
    "/{academy_id}/join-requests/{request_id}",
    summary="가입 요청 승인·거절 (OWNER/MANAGER)",
    responses=AUTH_ERRORS | NOT_MEMBER | error_responses(409, 422),
)
async def review_join_request(
    academy_id: uuid.UUID,
    request_id: uuid.UUID,
    data: JoinRequestReview,
    reviewer: AcademyAdmin,
    session: DbSession,
) -> JoinRequestRead:
    join_request = await MembershipService(session).review_join_request(
        academy_id, request_id, reviewer, data
    )
    return JoinRequestRead.model_validate(join_request)
