"""실제 PostgreSQL이 필요한 API 테스트 공통 fixture.

- TEST_DATABASE_URL이 없으면 이 디렉터리의 테스트는 모두 skip.
- 안전장치: Supabase 호스트이거나 로컬이 아닌 DB면 테스트 세션을 중단한다
  (원격 테스트 DB를 의도적으로 쓰려면 ALLOW_REMOTE_TEST_DATABASE=true).
- 세션 시작 시 `alembic downgrade base` → `upgrade head`로 깨끗한 스키마를 만들고,
  각 테스트가 끝나면 모든 앱 테이블을 TRUNCATE 한다.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.main import create_app
from tests.auth_utils import TEST_SUPABASE_URL, TokenFactory, make_verifier
from tests.conftest import make_settings, running_client

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
APP_TABLES = "profiles, academies, academy_memberships, academy_join_requests"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

pytestmark = pytest.mark.integration


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if TEST_DATABASE_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if Path(str(item.fspath)).is_relative_to(Path(__file__).parent):
            item.add_marker(skip)


def _assert_safe_test_database(url: str) -> None:
    host = (make_url(url).host or "").lower()
    if "supabase" in host:
        pytest.exit("Refusing to run DB tests against a Supabase host", returncode=2)
    if host not in LOCAL_HOSTS and os.environ.get("ALLOW_REMOTE_TEST_DATABASE") != "true":
        pytest.exit(
            "TEST_DATABASE_URL must point to a local database "
            "(set ALLOW_REMOTE_TEST_DATABASE=true to override)",
            returncode=2,
        )


def run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    assert TEST_DATABASE_URL
    env = {**os.environ, "ENV_FILE": "", "APP_ENV": "test", "DATABASE_URL": TEST_DATABASE_URL}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@pytest.fixture(scope="session")
def migrated_database() -> str:
    assert TEST_DATABASE_URL
    _assert_safe_test_database(TEST_DATABASE_URL)
    for args in (("downgrade", "base"), ("upgrade", "head")):
        result = run_alembic(*args)
        assert result.returncode == 0, result.stderr[-2000:]
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
async def app(migrated_database: str, tokens: TokenFactory):  # type: ignore[no-untyped-def]
    application = create_app(
        make_settings(database_url=migrated_database, supabase_url=TEST_SUPABASE_URL)
    )
    application.state.token_verifier = make_verifier(tokens)
    yield application


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:  # type: ignore[no-untyped-def]
    async with running_client(app) as c:
        yield c
        async with app.state.database.engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {APP_TABLES} CASCADE"))


# --------------------------------------------------------------------------- helpers


@dataclass
class Actor:
    user_id: uuid.UUID
    headers: dict[str, str]


@pytest.fixture
def actors(client: httpx.AsyncClient, tokens: TokenFactory, app):  # type: ignore[no-untyped-def]
    """테스트 사용자 생성 도우미."""

    class Actors:
        def anonymous_token(self) -> Actor:
            user_id = uuid.uuid4()
            return Actor(user_id, tokens.auth_header(user_id))

        async def signup(self, user_type: str = "STUDENT", name: str | None = None) -> Actor:
            actor = self.anonymous_token()
            response = await client.post(
                "/api/v1/users/me",
                json={
                    "display_name": name or f"{user_type.lower()}-{actor.user_id.hex[:6]}",
                    "user_type": user_type,
                },
                headers=actor.headers,
            )
            assert response.status_code == 201, response.text
            return actor

        async def admin(self) -> Actor:
            """시스템 ADMIN은 API로 만들 수 없으므로 DB에서 직접 지정한다 (운영과 동일한 방식)."""
            actor = await self.signup("STUDENT", name="system-admin")
            async with app.state.database.engine.begin() as conn:
                await conn.execute(
                    text("UPDATE profiles SET user_type = 'ADMIN' WHERE id = :id"),
                    {"id": actor.user_id},
                )
            return actor

        async def active_academy(
            self, owner: Actor, admin: Actor, name: str = "아트메이트 미술학원"
        ) -> str:
            created = await client.post(
                "/api/v1/academies", json={"name": name}, headers=owner.headers
            )
            assert created.status_code == 201, created.text
            academy_id = created.json()["id"]
            approved = await client.patch(
                f"/api/v1/admin/academies/{academy_id}",
                json={"decision": "APPROVE"},
                headers=admin.headers,
            )
            assert approved.status_code == 200, approved.text
            return academy_id

        async def join(self, academy_id: str, member: Actor, approver: Actor) -> str:
            requested = await client.post(
                f"/api/v1/academies/{academy_id}/join-requests", json={}, headers=member.headers
            )
            assert requested.status_code == 201, requested.text
            reviewed = await client.patch(
                f"/api/v1/academies/{academy_id}/join-requests/{requested.json()['id']}",
                json={"decision": "APPROVE"},
                headers=approver.headers,
            )
            assert reviewed.status_code == 200, reviewed.text
            return requested.json()["id"]

    return Actors()
