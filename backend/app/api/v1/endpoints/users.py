"""본인 계정 API.

회원가입·로그인·로그아웃·토큰 갱신·비밀번호 재설정은 프론트엔드의 Supabase Auth SDK가 처리하며,
백엔드는 그 결과인 access token을 검증만 한다 (docs/frontend-integration.md).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import ActiveProfile, DbSession, require_user_types
from app.api.responses import AUTH_ERRORS, error_responses
from app.core.security import CurrentUser
from app.models.enums import UserType
from app.models.profile import Profile
from app.schemas.academy import JoinRequestRead, MyJoinRequest
from app.schemas.common import Page, PaginationQuery
from app.schemas.goals import (
    LearningContext,
    TargetUniversityCreate,
    TargetUniversityOrder,
    TargetUniversityRead,
    TargetUniversityUpdate,
)
from app.schemas.user import MeRead, ProfileCreate, ProfileRead, ProfileUpdate
from app.services.goals import GoalService
from app.services.memberships import MembershipService
from app.services.profiles import ProfileService

router = APIRouter(prefix="/users", tags=["users"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]


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
        "(값은 바뀌지 않음). user_type은 STUDENT/INSTRUCTOR만 가능. "
        "practical_type(실기 유형)은 선택이며 나중에 PATCH로 바꿀 수 있다."
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
    summary="내 프로필 수정 (표시 이름·사진·실기 유형·학년·학습 목표)",
    description="user_type, is_active 등 다른 필드를 보내면 422. "
    "practical_type·grade는 선택지 외 값이면 422, null이면 미선택으로 되돌린다. "
    "learning_goal을 바꾸면 learning_goal_updated_at(목표 수정일)이 갱신된다.",
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


# ============================================================================ v0.9 학습 목표 (F-1)

GOAL_WRITE = AUTH_ERRORS | error_responses(404, 409, 422)


@router.get(
    "/me/learning-context",
    summary="내 학습 목표 맥락 (실기 유형·학년·학습 목표·지망 대학)",
    description="성장 리포트·과제 화면에서 함께 보여 줄 값. 학원 가입과 무관하다.",
    responses=AUTH_ERRORS,
)
async def my_learning_context(owner: Student, session: DbSession) -> LearningContext:
    return await GoalService(session).context(owner.id)


@router.get(
    "/me/target-universities",
    summary="내 지망 대학 목록 (1지망부터)",
    responses=AUTH_ERRORS,
)
async def list_target_universities(
    owner: Student, session: DbSession
) -> list[TargetUniversityRead]:
    return await GoalService(session).list(owner)


@router.post(
    "/me/target-universities",
    summary="지망 대학 추가 (최대 10개)",
    description="직접 입력한다 (입시 정보 API·합격 예측 없음). priority를 생략하면 맨 뒤, "
    "지정하면 그 순위에 넣고 기존 대학을 한 칸씩 민다. 10개를 넘으면 409 "
    "`TARGET_UNIVERSITY_LIMIT`.",
    status_code=status.HTTP_201_CREATED,
    responses=GOAL_WRITE,
)
async def create_target_university(
    data: TargetUniversityCreate, owner: Student, session: DbSession
) -> TargetUniversityRead:
    return await GoalService(session).create(owner, data)


@router.put(
    "/me/target-universities/order",
    summary="지망 순위 한 번에 바꾸기",
    description="ids = 새 순서 (1지망부터). 내 지망 대학 전체를 한 번씩 보내야 한다 (아니면 422).",
    responses=GOAL_WRITE,
)
async def reorder_target_universities(
    data: TargetUniversityOrder, owner: Student, session: DbSession
) -> list[TargetUniversityRead]:
    return await GoalService(session).reorder(owner, data)


@router.patch(
    "/me/target-universities/{target_id}",
    summary="지망 대학 수정 (이름·학과·메모, priority로 순위 이동)",
    responses=GOAL_WRITE,
)
async def update_target_university(
    target_id: uuid.UUID, data: TargetUniversityUpdate, owner: Student, session: DbSession
) -> TargetUniversityRead:
    return await GoalService(session).update(owner, target_id, data)


@router.delete(
    "/me/target-universities/{target_id}",
    summary="지망 대학 삭제 (뒤 순위가 한 칸씩 당겨짐)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=AUTH_ERRORS | error_responses(404),
)
async def delete_target_university(
    target_id: uuid.UUID, owner: Student, session: DbSession
) -> None:
    await GoalService(session).delete(owner, target_id)
