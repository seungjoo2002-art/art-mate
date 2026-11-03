"""실제 PostgreSQL 연결 테스트 (선택).

TEST_DATABASE_URL 이 설정된 경우에만 실행된다. 반드시 테스트 전용 DB를 사용하고,
운영 Supabase 프로젝트의 URL을 넣지 마세요.

    export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/artmate_test
    uv run pytest -m integration
"""

import os

import pytest

from app.main import create_app
from tests.conftest import make_settings, running_client

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set"),
]


async def test_db_health_against_real_database() -> None:
    app = create_app(make_settings(database_url=TEST_DATABASE_URL))

    async with running_client(app) as client:
        response = await client.get("/api/v1/health/db")

    assert response.status_code == 200, response.text
    assert response.json()["database"] == "ok"
