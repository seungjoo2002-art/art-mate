"""테스트용 Supabase 형식 JWT 발급기. 실제 Supabase에 접근하지 않는다."""

import json
import time
import uuid
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from app.core.exceptions import InvalidTokenError
from app.core.security import SupabaseJWTVerifier

TEST_SUPABASE_URL = "https://test-project.supabase.co"
TEST_ISSUER = f"{TEST_SUPABASE_URL}/auth/v1"
TEST_AUDIENCE = "authenticated"
OMIT = object()


class TokenFactory:
    def __init__(self, kid: str = "test-key-1") -> None:
        self.kid = kid
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        public_jwk = json.loads(ECAlgorithm.to_jwk(self.private_key.public_key()))
        public_jwk.update(kid=kid, alg="ES256", use="sig")
        self.public_jwk = public_jwk
        self.jwk = jwt.PyJWK.from_dict(public_jwk)

    def claims(self, user_id: uuid.UUID | str, **overrides: Any) -> dict[str, Any]:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": str(user_id),
            "aud": TEST_AUDIENCE,
            "iss": TEST_ISSUER,
            "role": "authenticated",
            "iat": now,
            "exp": now + 3600,
            "email": f"{str(user_id)[:8]}@example.com",
            "is_anonymous": False,
        }
        claims.update(overrides)
        return {k: v for k, v in claims.items() if v is not OMIT}

    def token(
        self,
        user_id: uuid.UUID | str,
        *,
        headers: dict[str, Any] | None = None,
        **overrides: Any,
    ) -> str:
        return jwt.encode(
            self.claims(user_id, **overrides),
            self.private_key,
            algorithm="ES256",
            headers={"kid": self.kid, **(headers or {})},
        )

    def auth_header(self, user_id: uuid.UUID | str, **overrides: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(user_id, **overrides)}"}


class StaticKeyResolver:
    def __init__(self, *keys: jwt.PyJWK) -> None:
        self._keys = {key.key_id: key for key in keys}

    async def get_key(self, kid: str) -> jwt.PyJWK:
        key = self._keys.get(kid)
        if key is None:
            raise InvalidTokenError()
        return key


def make_verifier(factory: TokenFactory) -> SupabaseJWTVerifier:
    return SupabaseJWTVerifier(
        issuer=TEST_ISSUER,
        audience=TEST_AUDIENCE,
        key_resolver=StaticKeyResolver(factory.jwk),
        leeway_seconds=0,
    )
