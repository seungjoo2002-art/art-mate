"""Supabase JWT 검증 단위 테스트 (DB 불필요)."""

import base64
import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import patch

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization

from app.core.exceptions import (
    AuthProviderUnavailableError,
    InvalidTokenError,
    TokenExpiredError,
)
from app.core.security import JWKSKeyResolver, build_token_verifier
from app.main import create_app
from tests.auth_utils import (
    OMIT,
    TEST_SUPABASE_URL,
    TokenFactory,
    make_verifier,
)
from tests.conftest import make_settings, running_client

USER_ID = uuid.UUID("2b1f9f3e-7a43-4d2c-9a55-3c7e0a6d1f10")


@pytest.fixture(scope="module")
def factory() -> TokenFactory:
    return TokenFactory()


def _b64(data: dict[str, object]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


# --------------------------------------------------------------------------- verifier


async def test_valid_token_is_accepted(factory: TokenFactory) -> None:
    user = await make_verifier(factory).verify(factory.token(USER_ID))

    assert user.user_id == USER_ID
    assert user.email is not None


async def test_expired_token_is_rejected(factory: TokenFactory) -> None:
    now = int(time.time())
    token = factory.token(USER_ID, iat=now - 7200, exp=now - 60)

    with pytest.raises(TokenExpiredError):
        await make_verifier(factory).verify(token)


async def test_tampered_payload_is_rejected(factory: TokenFactory) -> None:
    header, _, signature = factory.token(USER_ID).split(".")
    forged_payload = _b64(factory.claims(uuid.uuid4()))  # 다른 사용자로 바꿔치기

    with pytest.raises(InvalidTokenError):
        await make_verifier(factory).verify(f"{header}.{forged_payload}.{signature}")


async def test_token_signed_by_other_key_is_rejected(factory: TokenFactory) -> None:
    attacker = TokenFactory(kid=factory.kid)  # 같은 kid, 다른 개인키

    with pytest.raises(InvalidTokenError):
        await make_verifier(factory).verify(attacker.token(USER_ID))


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.supabase.co/auth/v1"},
        {"aud": "anon"},
        {"role": "anon"},
        {"role": "service_role"},
        {"is_anonymous": True},
        {"sub": "not-a-uuid"},
        {"exp": OMIT},
        {"sub": OMIT},
        {"iat": OMIT},
    ],
    ids=lambda o: next(iter(o)) + "=" + str(next(iter(o.values())))[:20],
)
async def test_invalid_claims_are_rejected(factory: TokenFactory, overrides: dict) -> None:
    with pytest.raises(InvalidTokenError):
        await make_verifier(factory).verify(factory.token(USER_ID, **overrides))


async def test_alg_none_is_rejected(factory: TokenFactory) -> None:
    token = f"{_b64({'alg': 'none', 'typ': 'JWT', 'kid': factory.kid})}."
    token += f"{_b64(factory.claims(USER_ID))}."

    with pytest.raises(InvalidTokenError):
        await make_verifier(factory).verify(token)


async def test_hs256_signed_with_public_key_is_rejected(factory: TokenFactory) -> None:
    """알고리즘 혼동 공격: 공개키(PEM)를 HMAC 비밀키로 써서 서명한 토큰."""
    public_pem = factory.jwk.key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    header = _b64({"alg": "HS256", "typ": "JWT", "kid": factory.kid})
    payload = _b64(factory.claims(USER_ID))
    signature = hmac.new(public_pem, f"{header}.{payload}".encode(), hashlib.sha256).digest()
    token = f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"

    with pytest.raises(InvalidTokenError):
        await make_verifier(factory).verify(token)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "Bearer x.y.z"])
async def test_garbage_tokens_are_rejected(factory: TokenFactory, token: str) -> None:
    with pytest.raises(InvalidTokenError):
        await make_verifier(factory).verify(token)


async def test_unknown_kid_is_rejected(factory: TokenFactory) -> None:
    with pytest.raises(InvalidTokenError):
        await make_verifier(factory).verify(factory.token(USER_ID, headers={"kid": "other"}))


# --------------------------------------------------------------------------- JWKS resolver


async def test_jwks_resolver_caches_and_limits_refresh(factory: TokenFactory) -> None:
    resolver = JWKSKeyResolver("https://example.invalid/jwks", min_refresh_seconds=30)
    calls = 0

    def fake_fetch() -> dict:
        nonlocal calls
        calls += 1
        return {"keys": [factory.public_jwk]}

    with patch.object(resolver, "_fetch", fake_fetch):
        assert (await resolver.get_key(factory.kid)).key_id == factory.kid
        assert (await resolver.get_key(factory.kid)).key_id == factory.kid
        # 위조 kid가 반복돼도 최소 간격 안에서는 다시 조회하지 않는다
        for _ in range(3):
            with pytest.raises(InvalidTokenError):
                await resolver.get_key("forged-kid")

    assert calls == 1


async def test_jwks_resolver_provider_down_returns_503_error() -> None:
    resolver = JWKSKeyResolver("https://example.invalid/jwks")

    def failing_fetch() -> dict:
        raise OSError("network down")

    with (
        patch.object(resolver, "_fetch", failing_fetch),
        pytest.raises(AuthProviderUnavailableError),
    ):
        await resolver.get_key("any")


def test_verifier_built_only_when_supabase_url_configured() -> None:
    assert build_token_verifier(make_settings()) is None
    assert build_token_verifier(make_settings(supabase_url=TEST_SUPABASE_URL)) is not None


def test_jwks_url_and_issuer_derived_from_supabase_url() -> None:
    settings = make_settings(supabase_url=TEST_SUPABASE_URL + "/")

    assert settings.auth_jwt_issuer == f"{TEST_SUPABASE_URL}/auth/v1"
    assert settings.auth_jwks_url == f"{TEST_SUPABASE_URL}/auth/v1/.well-known/jwks.json"


# --------------------------------------------------------------------------- HTTP layer


@pytest.fixture
async def client(factory: TokenFactory):  # type: ignore[no-untyped-def]
    app = create_app(make_settings(supabase_url=TEST_SUPABASE_URL))
    app.state.token_verifier = make_verifier(factory)
    async with running_client(app) as c:
        yield c


async def test_missing_token_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_invalid_and_expired_tokens_return_distinct_401_codes(
    client: httpx.AsyncClient, factory: TokenFactory
) -> None:
    now = int(time.time())
    invalid = await client.get("/api/v1/users/me", headers={"Authorization": "Bearer x.y.z"})
    expired = await client.get(
        "/api/v1/users/me", headers=factory.auth_header(USER_ID, iat=now - 100, exp=now - 10)
    )

    assert (invalid.status_code, invalid.json()["error"]["code"]) == (401, "INVALID_TOKEN")
    assert (expired.status_code, expired.json()["error"]["code"]) == (401, "TOKEN_EXPIRED")


async def test_valid_token_without_database_returns_503(
    client: httpx.AsyncClient, factory: TokenFactory
) -> None:
    """인증은 통과하지만 DB가 없으면 503 (토큰 검증이 DB보다 먼저 수행됨)."""
    response = await client.get("/api/v1/users/me", headers=factory.auth_header(USER_ID))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_NOT_CONFIGURED"


async def test_token_is_never_logged(
    client: httpx.AsyncClient, factory: TokenFactory, caplog: pytest.LogCaptureFixture
) -> None:
    token = factory.token(USER_ID, aud="wrong")
    caplog.set_level("DEBUG")

    await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})

    assert token not in caplog.text
    assert token.split(".")[1] not in caplog.text


def test_jwt_library_rejects_none_algorithm_by_default() -> None:
    """회귀 방지: PyJWT 업그레이드 후에도 none 알고리즘이 거부되는지."""
    with pytest.raises(jwt.InvalidAlgorithmError):
        jwt.decode(jwt.encode({"a": 1}, None, algorithm="none"), "k", algorithms=["ES256"])
