"""인증·권한 기반 (v0.1: 구조만 준비, 실제 토큰 검증은 v0.2에서 구현).

설계 (자세한 내용은 docs/architecture.md, docs/database-design.md 참고)
--------------------------------------------------------------------------
1. 클라이언트는 Supabase Auth로 로그인하고 받은 access token을
   `Authorization: Bearer <token>` 헤더로 보낸다.
2. 백엔드는 `verify_access_token()`에서 Supabase JWT를 검증한다.
   - 서명: 프로젝트 JWKS(`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`) 공개키,
     허용 알고리즘 화이트리스트
   - iss: `{SUPABASE_URL}/auth/v1`, aud: `authenticated`, exp/iat/nbf 검증
   - sub(UUID) → `AuthenticatedUser.user_id` (= auth.users.id = user_profiles.id)
3. 학원 소속·역할(admin/teacher/student)은 JWT가 아니라 DB의
   `academy_memberships`에서 조회한다 (역할 변경이 즉시 반영되도록).

v0.1 정책: 검증기가 구현되지 않았으므로 `get_current_user`는 **항상 401**을 반환한다
(fail-closed). 따라서 이 의존성을 붙인 API는 v0.2 전까지 절대 공개되지 않는다.
v0.2에서는 `verify_access_token()` 본문만 교체하면 되고, 라우터 코드는 바꿀 필요가 없다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.exceptions import ErrorCode, UnauthorizedError


class AcademyRole(StrEnum):
    """학원 내 역할. 한 사용자는 학원마다 다른 역할을 가질 수 있다."""

    ADMIN = "admin"  # 원장/관리자
    TEACHER = "teacher"  # 실기 강사
    STUDENT = "student"  # 학생


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """검증된 access token에서 얻은 사용자 정보 (DB 조회 전 단계)."""

    user_id: uuid.UUID
    email: str | None = None
    claims: dict[str, object] = field(default_factory=dict, repr=False)


# auto_error=False: 헤더 누락도 우리 에러 포맷(401 + WWW-Authenticate)으로 응답하기 위함
bearer_scheme = HTTPBearer(auto_error=False, description="Supabase Auth access token")


async def verify_access_token(token: str, settings: Settings) -> AuthenticatedUser:
    """Supabase access token 검증. v0.2에서 구현한다.

    구현 시 요구사항:
    - 서명 검증 필수 (`verify_signature=False` 금지), 허용 알고리즘 명시 (alg=none 거부)
    - iss/aud/exp 검증, 짧은 leeway(≤30s)만 허용
    - JWKS는 캐시하되 kid 미스 시 1회 재조회
    - 실패 사유는 로그에만 남기고 응답은 UnauthorizedError로 통일
    """
    raise UnauthorizedError(
        "Authentication is not available yet", code=ErrorCode.AUTH_NOT_CONFIGURED
    )


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    """보호 API용 의존성. 인증되지 않은 요청은 401로 거부한다."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    settings: Settings = request.app.state.settings
    return await verify_access_token(credentials.credentials, settings)


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
