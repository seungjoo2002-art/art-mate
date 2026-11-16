"""Alembic 운영 DB 안전장치 (app/db/migration_guard.py)."""

import pytest

from app.db.migration_guard import is_supabase_host, migration_block_reason

POOLER = "postgresql://postgres.abc:pw@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres"
DIRECT = "postgresql://postgres:pw@db.abcdefghijkl.supabase.co:5432/postgres"
LOCAL = "postgresql://postgres:postgres@localhost:5432/artmate_test"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (POOLER, True),
        (DIRECT, True),
        ("postgresql://u:p@DB.ABC.SUPABASE.CO./postgres", True),
        (LOCAL, False),
        ("postgresql://u:p@127.0.0.1:5432/x", False),
        ("postgresql://u:p@supabase.co.example.com/x", False),
        ("postgresql://u:p@notsupabase.com/x", False),
    ],
)
def test_is_supabase_host(url: str, expected: bool) -> None:
    assert is_supabase_host(url) is expected


@pytest.mark.parametrize("url", [POOLER, DIRECT])
def test_development_env_pointing_at_supabase_is_blocked(url: str) -> None:
    # 로컬 .env가 APP_ENV=development 로 운영 Supabase를 가리키던 실제 사례
    assert migration_block_reason("development", url, None)
    assert migration_block_reason("development", url, "false")
    assert migration_block_reason("test", url, "1")


def test_production_env_is_blocked_even_for_local_host() -> None:
    assert migration_block_reason("production", LOCAL, None) == "APP_ENV=production"


@pytest.mark.parametrize("app_env", ["development", "test", "production"])
def test_explicit_allow_unblocks(app_env: str) -> None:
    assert migration_block_reason(app_env, POOLER, "true") is None


@pytest.mark.parametrize("app_env", ["development", "test", "staging"])
def test_local_database_is_allowed(app_env: str) -> None:
    # CI(backend-ci.yml)와 로컬 테스트 DB는 그대로 동작해야 한다
    assert migration_block_reason(app_env, LOCAL, None) is None
