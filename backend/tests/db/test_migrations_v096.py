"""Alembic 0011(VER.2 P1) → 0012(v0.9.6 OpenAI·연령·보호자) 계보와 기존 DB 업그레이드 검증.

- 새 DB: 세션 fixture(migrated_database)가 base → head를 실행하고, CI가 왕복·드리프트를 검사한다.
- 기존 DB: 0010에 기존 데이터(Gemini 동의 v1 포함)를 넣고 0011 → 0012로 한 단계씩 올린다
  (운영 DB가 0010이나 0011인 경우). 기존 행은 그대로, Gemini·OpenAI 동의는 섞이지 않는다.
"""

import uuid

import asyncpg
import pytest

from tests.db.test_migrations import _asyncpg_dsn
from tests.db.test_migrations_v051 import _alembic


def test_lineage_is_linear() -> None:
    history = _alembic("history")
    assert "0010 -> 0011" in history
    assert "0011 -> 0012" in history
    assert "0012 -> 0013" in history
    assert "0013 -> 0014 (head)" in history
    heads = _alembic("heads")
    assert heads.count("(head)") == 1 and "0014" in heads


async def _consents(conn: asyncpg.Connection, user: uuid.UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM ai_processing_consents WHERE user_id = $1 ORDER BY provider", user
    )


async def test_existing_db_upgrades_step_by_step_and_keeps_data(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    user, legacy = uuid.uuid4(), uuid.uuid4()
    try:
        _alembic("downgrade", "0010")
        # 운영과 같은 상태의 기존 데이터: 학생 + Gemini 동의(v1, 연령 정보 없음)
        await conn.execute(
            "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, '학생', 'STUDENT')",
            user,
        )
        await conn.execute(
            "INSERT INTO ai_processing_consents (id, user_id, provider, purpose, policy_version,"
            " granted_by, granted_at) VALUES ($1, $2, 'GOOGLE_GEMINI', 'FEEDBACK_SUMMARY',"
            " '2026-11-ai-v1', 'SELF', now())",
            legacy,
            user,
        )

        _alembic("upgrade", "0011")  # PR #48 먼저 (운영 DB가 0011인 경우도 여기서부터 같다)
        assert await conn.fetchval("SELECT real_name FROM profiles WHERE id = $1", user) is None
        _alembic("upgrade", "0012")
        assert "0012" in _alembic("current")

        rows = await _consents(conn, user)
        assert len(rows) == 1
        old = rows[0]
        assert (old["id"], old["provider"], old["policy_version"]) == (
            legacy,
            "GOOGLE_GEMINI",
            "2026-11-ai-v1",
        )
        # 새 컬럼은 비어 있음 (이전 동의는 연령 정보 없음 → 앱에서 무효, 재동의 필요)
        assert old["age_band"] is None and old["guardian_confirmed_at"] is None

        # 같은 학생·목적이라도 제공자가 다르면 별도 행 (섞이지 않음)
        openai_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO ai_processing_consents (id, user_id, provider, purpose, policy_version,"
            " granted_by, granted_at, age_band) VALUES ($1, $2, 'OPENAI', 'FEEDBACK_SUMMARY',"
            " '2026-12-ai-v2', 'SELF', now(), 'ADULT')",
            openai_id,
            user,
        )
        assert [r["provider"] for r in await _consents(conn, user)] == ["GOOGLE_GEMINI", "OPENAI"]
        # 같은 제공자·목적의 유효 동의는 1개
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO ai_processing_consents (id, user_id, provider, purpose,"
                " policy_version, granted_by, granted_at, age_band) VALUES ($1, $2, 'OPENAI',"
                " 'FEEDBACK_SUMMARY', '2026-12-ai-v2', 'SELF', now(), 'ADULT')",
                uuid.uuid4(),
                user,
            )
        # 제약: 알 수 없는 제공자·연령 구간, 이름 없는 보호자 확인 거부
        for sql in (
            "UPDATE ai_processing_consents SET provider = 'ANTHROPIC' WHERE id = $1",
            "UPDATE ai_processing_consents SET age_band = 'TEEN' WHERE id = $1",
            "UPDATE ai_processing_consents SET guardian_confirmed_at = now() WHERE id = $1",
        ):
            with pytest.raises(asyncpg.CheckViolationError):
                await conn.execute(sql, openai_id)

        # 되돌리기: OpenAI 행만 지워지고 Gemini 기존 행은 남는다
        _alembic("downgrade", "0011")
        assert [r["provider"] for r in await _consents(conn, user)] == ["GOOGLE_GEMINI"]
        _alembic("upgrade", "head")
        assert "No new upgrade operations detected" in _alembic("check")
    finally:
        _alembic("upgrade", "head")
        await conn.execute("DELETE FROM profiles WHERE id = $1", user)
        await conn.close()


async def test_0013_maps_age_bands_conservatively(migrated_database: str) -> None:
    """0012의 UNDER_13·MINOR(13~17)는 만 14세 기준으로 구분할 수 없어 더 엄격한 UNDER_14로."""
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    users = {band: uuid.uuid4() for band in ("UNDER_13", "MINOR", "ADULT")}
    try:
        _alembic("downgrade", "0012")
        for band, user in users.items():
            await conn.execute(
                "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, 's', 'STUDENT')",
                user,
            )
            await conn.execute(
                "INSERT INTO ai_processing_consents (id, user_id, provider, purpose,"
                " policy_version, granted_by, granted_at, age_band) VALUES ($1, $2, 'OPENAI',"
                " 'FEEDBACK_SUMMARY', '2026-12-ai-v2', 'SELF', now(), $3)",
                uuid.uuid4(),
                user,
                band,
            )

        async def bands() -> dict[str, str]:
            rows = await conn.fetch(
                "SELECT user_id, age_band FROM ai_processing_consents WHERE user_id = ANY($1)",
                list(users.values()),
            )
            by_user = {r["user_id"]: r["age_band"] for r in rows}
            return {band: by_user[user] for band, user in users.items()}

        _alembic("upgrade", "0013")
        assert await bands() == {"UNDER_13": "UNDER_14", "MINOR": "UNDER_14", "ADULT": "ADULT"}
        await conn.execute(
            "UPDATE ai_processing_consents SET age_band = 'TEEN' WHERE user_id = $1",
            users["ADULT"],
        )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE ai_processing_consents SET age_band = 'MINOR' WHERE user_id = $1",
                users["ADULT"],
            )
        _alembic("downgrade", "0012")
        assert await bands() == {"UNDER_13": "UNDER_13", "MINOR": "UNDER_13", "ADULT": "MINOR"}
        _alembic("upgrade", "head")
        assert "No new upgrade operations detected" in _alembic("check")
    finally:
        _alembic("upgrade", "head")
        await conn.execute("DELETE FROM profiles WHERE id = ANY($1)", list(users.values()))
        await conn.close()
