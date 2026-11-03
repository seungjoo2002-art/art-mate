"""본인 계정 API.

회원가입·로그인·로그아웃·토큰 갱신·비밀번호 재설정은 프론트엔드의 Supabase Auth SDK가 처리하며,
백엔드는 그 결과인 access token을 검증만 한다 (docs/frontend-integration.md).
"""

from fastapi import APIRouter, Response, status

from app.api.deps import ActiveProfile, DbSession
from app.api.responses import AUTH_ERRORS, error_responses
from app.core.security import CurrentUser
from app.models.profile import Profile
from app.schemas.academy import JoinRequestRead, MyJoinRequest
from app.schemas.common import Page, PaginationQuery
from app.schemas.user import MeRead, ProfileCreate, ProfileRead, ProfileUpdate
from app.services.memberships import MembershipService
from app.services.profiles import ProfileService

router = APIRouter(prefix="/users", tags=["users"])


def _me(profile: Profile, email: str | None) -> MeRead:
    return MeRead(**ProfileRead.model_validate(profile).model_dump(), email=email)


@router.get(
    "/me",
    summary="내 프로필 조회 (로그인 상태 확인)",
    description="프로필이 아직 없으면 404 `PROFILE_NOT_FOUND` → 프로필 생성 화면으로 이동.",
    responses=error_responses(401, 404, 503),
)
async def get_me(user: CurrentUser, session: DbSession) -> MeRead:
    profile = await ProfileService(session).get_me(user)
    return _me(profile, user.email)


@router.post(
    "/me",
    summary="내 프로필 생성 (회원가입 직후, 멱등)",
    description=(
        "처음 호출하면 201로 생성. 이미 있으면 200으로 기존 프로필을 그대로 반환한다 "
        "(값은 바뀌지 않음). user_type은 STUDENT/INSTRUCTOR만 가능."
    ),
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": MeRead, "description": "이미 존재 (기존 프로필 반환)"}}
    | error_responses(401, 422, 503),
)
async def create_me(
    data: ProfileCreate, user: CurrentUser, session: DbSession, response: Response
) -> MeRead:
    profile, created = await ProfileService(session).create_me(user, data)
    if not created:
        response.status_code = status.HTTP_200_OK
    return _me(profile, user.email)


@router.patch(
    "/me",
    summary="내 프로필 수정 (display_name, avatar_path)",
    description="user_type, is_active 등 다른 필드를 보내면 422.",
    responses=AUTH_ERRORS | error_responses(422),
)
async def update_me(
    data: ProfileUpdate, user: CurrentUser, profile: ActiveProfile, session: DbSession
) -> MeRead:
    updated = await ProfileService(session).update_me(profile, data)
    return _me(updated, user.email)


@router.get("/me/join-requests", summary="내 학원 가입 요청 목록", responses=AUTH_ERRORS)
async def list_my_join_requests(
    profile: ActiveProfile, session: DbSession, pagination: PaginationQuery
) -> Page[MyJoinRequest]:
    rows, total = await MembershipService(session).list_my_join_requests(profile, pagination)
    items = [
        MyJoinRequest(**JoinRequestRead.model_validate(req).model_dump(), academy_name=name)
        for req, name in rows
    ]
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)
