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

    # 연결 확인이 목적. v0.9.9부터 스키마 버전도 비교하므로, 이 테스트 시점에 마이그레이션이
    # 적용돼 있지 않으면(예: CI의 downgrade base 직후) 503 DATABASE_SCHEMA_MISMATCH가 정상이다.
    # 스키마 판정 자체는 tests/db/test_schema_version_health.py (head로 마이그레이션된 DB)에서 검증
    if response.status_code == 200:
        assert response.json()["database"] == "ok"
        assert response.json()["schema_status"] in ("ok", "ahead")
    else:
        assert response.status_code == 503, response.text
        error = response.json()["error"]
        assert error["code"] == "DATABASE_SCHEMA_MISMATCH"
        assert error["details"]["schema_status"] in ("behind", "missing")
