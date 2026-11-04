"""라우터에서 사용하는 공통 FastAPI 의존성.

    async def list_items(session: DbSession, settings: AppSettings): ...

트랜잭션 규칙: `DbSession`은 요청 단위 세션이다. 쓰기 작업은 서비스 계층에서
`await session.commit()`을 명시적으로 호출하며, 예외 발생 시 세션 종료와 함께 롤백된다.

권한 의존성 (아래로 갈수록 엄격)
- `CurrentUser`: 유효한 Supabase access token (프로필 없어도 됨) → 401
- `ActiveProfile`: + 프로필 생성 완료, 계정 활성 → 403 PROFILE_REQUIRED / ACCOUNT_DISABLED
- `require_user_types(...)`: + 서비스 사용자 유형(STUDENT/INSTRUCTOR/ADMIN) → 403
- `require_academy_roles(...)`: + 경로의 academy_id 학원에 ACTIVE 소속과 역할
  → 404(비소속) / 403(역할 부족)
  단축형: `AcademyMember`(모든 역할), `AcademyStudent`, `AcademyStaff`(INSTRUCTOR 이상),
  `AcademyAdmin`(OWNER/MANAGER), `AcademyOwner`
"""

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import (
    DatabaseNotConfiguredError,
    ErrorCode,
    ForbiddenError,
    NotFoundError,
    StorageNotConfiguredError,
)
from app.core.security import CurrentUser
from app.db.session import Database
from app.integrations.supabase.storage import StorageClient
from app.models.enums import ACADEMY_ADMIN_ROLES, ACADEMY_STAFF_ROLES, MembershipRole, UserType
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.repositories.memberships import MembershipRepository
from app.repositories.profiles import ProfileRepository
from app.services.help_events import HelpQueuePublisher


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise DatabaseNotConfiguredError()
    return database


async def get_db_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async with database.session_factory() as session:
        yield session


def get_storage(request: Request) -> StorageClient:
    storage: StorageClient | None = request.app.state.storage
    if storage is None:
        raise StorageNotConfiguredError()
    return storage


def get_optional_storage(request: Request) -> StorageClient | None:
    return request.app.state.storage


AppSettings = Annotated[Settings, Depends(get_app_settings)]
Storage = Annotated[StorageClient, Depends(get_storage)]


def get_optional_audio_storage(request: Request) -> StorageClient | None:
    return request.app.state.audio_storage


def get_help_publisher(request: Request) -> HelpQueuePublisher:
    return request.app.state.help_publisher


AudioStorage = Annotated[StorageClient | None, Depends(get_optional_audio_storage)]
HelpPublisher = Annotated[HelpQueuePublisher, Depends(get_help_publisher)]
# Storage가 필요 없는 요청(작품 생성 등)도 있는 서비스용. 필요한 시점에 서비스가 503을 낸다.
OptionalStorage = Annotated[StorageClient | None, Depends(get_optional_storage)]
DatabaseDep = Annotated[Database, Depends(get_database)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


# --------------------------------------------------------------------------- profile


async def get_active_profile(user: CurrentUser, session: DbSession) -> Profile:
    """토큰의 sub로만 프로필을 찾는다. 클라이언트가 보낸 user_id는 신뢰하지 않는다."""
    profile = await ProfileRepository(session).get(user.user_id)
    if profile is None:
        raise ForbiddenError(
            "Create your profile first (POST /api/v1/users/me)", code=ErrorCode.PROFILE_REQUIRED
        )
    if not profile.is_active:
        raise ForbiddenError("This account is disabled", code=ErrorCode.ACCOUNT_DISABLED)
    return profile


ActiveProfile = Annotated[Profile, Depends(get_active_profile)]


def require_user_types(*allowed: UserType) -> Callable[..., Awaitable[Profile]]:
    """서비스 사용자 유형 검사. 예: `Depends(require_user_types(UserType.ADMIN))`"""
    allowed_set = frozenset(allowed)

    async def dependency(profile: ActiveProfile) -> Profile:
        if profile.user_type not in allowed_set:
            raise ForbiddenError()
        return profile

    return dependency


def require_academy_roles(*allowed: MembershipRole) -> Callable[..., Awaitable[AcademyMembership]]:
    """경로 파라미터 `academy_id`의 학원 소속·역할 검사.

    - 소속(ACTIVE)이 아니면 404: 다른 학원의 존재·내부 정보를 노출하지 않는다
    - 소속이지만 역할이 부족하면 403
    - 시스템 ADMIN도 소속이 아니면 학원 내부 데이터에 접근할 수 없다 (권한 분리)
    """
    allowed_set = frozenset(allowed)

    async def dependency(
        academy_id: uuid.UUID, profile: ActiveProfile, session: DbSession
    ) -> AcademyMembership:
        membership = await MembershipRepository(session).get_active_by_user(academy_id, profile.id)
        if membership is None:
            raise NotFoundError("Academy not found")
        if allowed_set and membership.role not in allowed_set:
            raise ForbiddenError()
        return membership

    return dependency


# 학원 역할별 의존성 (경로 파라미터 academy_id 기준)
AcademyAdmin = Annotated[AcademyMembership, Depends(require_academy_roles(*ACADEMY_ADMIN_ROLES))]
AcademyStaff = Annotated[AcademyMembership, Depends(require_academy_roles(*ACADEMY_STAFF_ROLES))]
AcademyOwner = Annotated[AcademyMembership, Depends(require_academy_roles(MembershipRole.OWNER))]
AcademyStudent = Annotated[
    AcademyMembership, Depends(require_academy_roles(MembershipRole.STUDENT))
]
AcademyMember = Annotated[AcademyMembership, Depends(require_academy_roles())]
