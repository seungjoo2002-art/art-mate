"""인증: Supabase Auth access token(JWT) 검증.

흐름
----
1. 클라이언트는 Supabase Auth SDK로 로그인하고 받은 access token을
   `Authorization: Bearer <token>` 헤더로 보낸다.
2. `get_current_user`가 `app.state.token_verifier`로 토큰을 검증한다.
   - 서명: 프로젝트 JWKS(`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`) 공개키,
     비대칭 알고리즘(ES256/RS256)만 허용 (alg=none, HS256 등은 거부)
   - iss = `{SUPABASE_URL}/auth/v1`, aud = `authenticated`, exp/iat 필수, leeway 설정값
   - role = `authenticated` (anon 키 토큰 거부), 익명 로그인 사용자 거부
   - sub(UUID) → `AuthenticatedUser.user_id` (= auth.users.id = profiles.id)
3. 학원 소속·역할은 JWT가 아니라 DB(`academy_memberships`)에서 확인한다 (api/deps.py).

SUPABASE_URL이 없으면 verifier가 None이고, 보호 API는 모두 401(AUTH_NOT_CONFIGURED)로 거부된다.
토큰 원문과 실패 상세는 로그·응답에 남기지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Annotated, Any, Protocol

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings
from app.core.exceptions import (
    AuthProviderUnavailableError,
    ErrorCode,
    InvalidTokenError,
    TokenExpiredError,
    UnauthorizedError,
)

logger = logging.getLogger(__name__)

# Supabase 비대칭 서명 키 알고리즘. 대칭키(HS256)·none은 허용하지 않는다.
ALLOWED_ALGORITHMS: frozenset[str] = frozenset({"ES256", "RS256"})
REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss"]


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """서명·클레임 검증을 통과한 토큰의 사용자 정보."""

    user_id: uuid.UUID
    email: str | None = None
    claims: dict[str, Any] = field(default_factory=dict, repr=False)


class SigningKeyResolver(Protocol):
    async def get_key(self, kid: str) -> jwt.PyJWK: ...


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> AuthenticatedUser: ...


class JWKSKeyResolver:
    """JWKS 공개키 조회 + 메모리 캐시.

    - 캐시는 `cache_seconds` 동안 유지
    - 모르는 kid(키 교체 직후)는 재조회하되, 위조 kid로 Supabase를 반복 호출하지 않도록
      최소 `min_refresh_seconds` 간격을 둔다
    """

    def __init__(
        self,
        jwks_url: str,
        *,
        cache_seconds: int = 600,
        min_refresh_seconds: int = 30,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._url = jwks_url
        self._cache_seconds = cache_seconds
        self._min_refresh_seconds = min_refresh_seconds
        self._timeout = timeout_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    def _fetch(self) -> dict[str, Any]:
        request = urllib.request.Request(self._url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            return json.load(response)

    async def _refresh(self) -> None:
        try:
            data = await asyncio.to_thread(self._fetch)
            keyset = jwt.PyJWKSet.from_dict(data)
        except Exception as exc:
            logger.warning("JWKS fetch failed", extra={"error_type": type(exc).__name__})
            if not self._keys:
                raise AuthProviderUnavailableError() from exc
            return  # 기존 캐시로 계속 동작
        self._keys = {key.key_id: key for key in keyset.keys if key.key_id}
        self._fetched_at = time.monotonic()

    def _age(self) -> float:
        return float("inf") if self._fetched_at is None else time.monotonic() - self._fetched_at

    async def get_key(self, kid: str) -> jwt.PyJWK:
        if kid not in self._keys or self._age() > self._cache_seconds:
            async with self._lock:
                expired = self._age() > self._cache_seconds
                unknown = kid not in self._keys
                if expired or (unknown and self._age() > self._min_refresh_seconds):
                    await self._refresh()
        key = self._keys.get(kid)
        if key is None:
            raise InvalidTokenError()
        return key


class SupabaseJWTVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        key_resolver: SigningKeyResolver,
        leeway_seconds: int = 10,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._keys = key_resolver
        self._leeway = leeway_seconds

    async def verify(self, token: str) -> AuthenticatedUser:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise InvalidTokenError() from None

        alg, kid = header.get("alg"), header.get("kid")
        if alg not in ALLOWED_ALGORITHMS or not isinstance(kid, str) or not kid:
            raise InvalidTokenError()

        key = await self._keys.get_key(kid)
        # 키에 지정된 알고리즘과 토큰 헤더의 alg가 다르면 거부 (알고리즘 혼동 방지)
        if key.algorithm_name and key.algorithm_name != alg:
            raise InvalidTokenError()

        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=[alg],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError() from None
        except jwt.PyJWTError as exc:
            logger.info("access token rejected", extra={"reason": type(exc).__name__})
            raise InvalidTokenError() from None

        if claims.get("role") != "authenticated" or claims.get("is_anonymous") is True:
            raise InvalidTokenError()
        try:
            user_id = uuid.UUID(str(claims["sub"]))
        except ValueError:
            raise InvalidTokenError() from None

        email = claims.get("email")
        return AuthenticatedUser(
            user_id=user_id, email=email if isinstance(email, str) else None, claims=claims
        )


def build_token_verifier(settings: Settings) -> TokenVerifier | None:
    if not settings.auth_configured:
        return None
    assert settings.auth_jwt_issuer and settings.auth_jwks_url
    return SupabaseJWTVerifier(
        issuer=settings.auth_jwt_issuer,
        audience=settings.auth_jwt_audience,
        key_resolver=JWKSKeyResolver(
            settings.auth_jwks_url, cache_seconds=settings.auth_jwks_cache_seconds
        ),
        leeway_seconds=settings.auth_jwt_leeway_seconds,
    )


# auto_error=False: 헤더 누락도 공통 에러 포맷(401 + WWW-Authenticate)으로 응답하기 위함
bearer_scheme = HTTPBearer(auto_error=False, description="Supabase Auth access token")


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AuthenticatedUser:
    """보호 API용 의존성. 토큰이 없거나 검증에 실패하면 401."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    verifier: TokenVerifier | None = request.app.state.token_verifier
    if verifier is None:
        raise UnauthorizedError(
            "Authentication is not available", code=ErrorCode.AUTH_NOT_CONFIGURED
        )
    return await verifier.verify(credentials.credentials)


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
