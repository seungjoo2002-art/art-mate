"""Alembic 마이그레이션 검증: 왕복 적용, 모델과 스키마 일치, 보안 설정."""

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from tests.db.conftest import run_alembic

_INSERT_PROFILE = "INSERT INTO profiles (id, display_name, user_type) VALUES"


def _asyncpg_dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def test_upgrade_downgrade_roundtrip_and_no_model_drift(migrated_database: str) -> None:
    for args in (("downgrade", "base"), ("upgrade", "head"), ("check",)):
        result = run_alembic(*args)
        assert result.returncode == 0, f"alembic {' '.join(args)}: {result.stderr[-2000:]}"
    assert "No new upgrade operations detected" in result.stdout + result.stderr


async def test_schema_security_and_constraints(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        rls = dict(
            await conn.fetch(
                "SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY($1::text[])",
                ["profiles", "academies", "academy_memberships", "academy_join_requests"],
            )
        )
        constraints = {
            row["conname"]
            for row in await conn.fetch(
                "SELECT conname FROM pg_constraint WHERE conrelid = ANY(ARRAY["
                "'profiles'::regclass, 'academy_memberships'::regclass, "
                "'academy_join_requests'::regclass])"
            )
        }
        indexes = {
            row["indexname"]
            for row in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'academy_join_requests'"
            )
        }
    finally:
        await conn.close()

    assert rls == dict.fromkeys(rls, True) and len(rls) == 4
    assert {
        "uq_academy_memberships_academy_id_user_id",
        "ck_academy_join_requests_requested_role_allowed",
        "ck_profiles_display_name_not_blank",
        "ck_profiles_user_type",
    } <= constraints
    assert "uq_academy_join_requests_pending" in indexes


@pytest.mark.parametrize(
    "sql",
    [
        f"{_INSERT_PROFILE} (gen_random_uuid(), 'x', 'ROOT')",
        f"{_INSERT_PROFILE} (gen_random_uuid(), '  ', 'STUDENT')",
    ],
)
async def test_database_rejects_invalid_values(migrated_database: str, sql: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(sql)
    finally:
        await conn.close()
