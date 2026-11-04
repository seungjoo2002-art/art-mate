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
from tests.fake_storage import FakeStorage

BACKEND_DIR = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
APP_TABLES = (
    "profiles, academies, academy_memberships, academy_join_requests, "
    "classes, class_memberships, class_schedules, schedule_exceptions, "
    "attendance_records, attendance_audit_logs, lesson_topics, tasks, task_assignments, "
    "personal_todos, artworks, artwork_photos, exam_templates, exam_stage_targets, "
    "exam_sessions, exam_session_stages, exam_participants"
)
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
    # 외부 Storage 대신 메모리 구현 (lifespan은 storage를 다시 만들지 않는다)
    application.state.storage = FakeStorage()
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
    # 학원 멤버 ID (academy_memberships.id). v0.3 시나리오 fixture에서 채운다.
    membership_id: str | None = None


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


# --------------------------------------------------------------------------- v0.3 시나리오


@dataclass
class World:
    """학원 1곳: 원장(OWNER), 담당 강사, 비담당 강사, 학생 3명, 반 1개(강사 + 학생 2명)."""

    academy_id: str
    owner: Actor
    teacher: Actor
    other_teacher: Actor
    students: list[Actor]
    class_id: str
    admin: Actor

    @property
    def base(self) -> str:
        return f"/api/v1/academies/{self.academy_id}"

    @property
    def class_base(self) -> str:
        return f"{self.base}/classes/{self.class_id}"


async def membership_ids(client: httpx.AsyncClient, academy_id: str, viewer: Actor) -> dict:
    members = await client.get(
        f"/api/v1/academies/{academy_id}/members?limit=100", headers=viewer.headers
    )
    assert members.status_code == 200, members.text
    return {m["user_id"]: m["id"] for m in members.json()["items"]}


@pytest.fixture
def build_world(client: httpx.AsyncClient, actors):  # type: ignore[no-untyped-def]
    async def build(name: str = "아트메이트 미술학원", admin: Actor | None = None) -> World:
        admin = admin or await actors.admin()
        owner = await actors.signup("INSTRUCTOR", name=f"{name}-원장")
        academy_id = await actors.active_academy(owner, admin, name=name)
        teacher = await actors.signup("INSTRUCTOR", name=f"{name}-담당강사")
        other_teacher = await actors.signup("INSTRUCTOR", name=f"{name}-다른강사")
        students = [await actors.signup("STUDENT", name=f"{name}-학생{i}") for i in (1, 2, 3)]
        for member in (teacher, other_teacher, *students):
            await actors.join(academy_id, member, owner)
        ids = await membership_ids(client, academy_id, owner)
        for member in (owner, teacher, other_teacher, *students):
            member.membership_id = ids[str(member.user_id)]

        created = await client.post(
            f"/api/v1/academies/{academy_id}/classes",
            json={"name": "입시 A반", "subject": "소묘"},
            headers=owner.headers,
        )
        assert created.status_code == 201, created.text
        class_id = created.json()["id"]
        for member in (teacher, students[0], students[1]):
            added = await client.post(
                f"/api/v1/academies/{academy_id}/classes/{class_id}/members",
                json={"membership_id": member.membership_id},
                headers=owner.headers,
            )
            assert added.status_code == 201, added.text
        return World(academy_id, owner, teacher, other_teacher, students, class_id, admin)

    return build


@pytest.fixture
async def world(build_world) -> World:  # type: ignore[no-untyped-def]
    return await build_world()
