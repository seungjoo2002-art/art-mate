"""Alembic 0007 (v0.7 성장 코치) 검증: RLS, 제약, 기존 동의·작업 호환, 왕복."""

import uuid

import asyncpg
import pytest

from tests.db.test_migrations import _asyncpg_dsn
from tests.db.test_migrations_v051 import _alembic

V07_TABLES = ["growth_reports", "practice_recommendations", "practice_recommendation_history"]


async def test_v07_schema(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        rls = dict(
            await conn.fetch(
                "SELECT relname, relrowsecurity FROM pg_class"
                " WHERE relname = ANY($1::text[]) AND relkind = 'r'",
                V07_TABLES,
            )
        )
        indexes = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])",
                [*V07_TABLES, "ai_processing_jobs", "ai_processing_consents"],
            )
        }
        constraints = {
            r["conname"]
            for r in await conn.fetch(
                "SELECT conname FROM pg_constraint"
                " WHERE conrelid::regclass::text = ANY($1::text[])",
                [*V07_TABLES, "ai_processing_jobs", "ai_processing_consents"],
            )
        }
    finally:
        await conn.close()
    assert rls == dict.fromkeys(V07_TABLES, True)
    assert {
        "uq_growth_reports_dedupe",
        "ix_growth_reports_source_feedback",
        "uq_practice_recommendations_live",
        "uq_ai_processing_jobs_active_dedupe",
        "uq_ai_processing_consents_active",
    } <= indexes
    assert {
        "ck_growth_reports_scope_academy",
        "ck_practice_recommendations_distributed_task",
        "ck_practice_recommendations_scope_not_all",
        "fk_practice_recommendations_academy_id_tasks",
        "ck_ai_processing_jobs_recording_job_has_recording",
        "ck_ai_processing_jobs_job_type",
        "ck_ai_processing_consents_purpose",
    } <= constraints


@pytest.fixture
async def conn(migrated_database: str):  # type: ignore[no-untyped-def]
    connection = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    user = uuid.uuid4()
    await connection.execute(
        "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, 's', 'STUDENT')", user
    )
    try:
        yield connection, user
    finally:
        await connection.execute("DELETE FROM profiles WHERE id = $1", user)
        await connection.close()


async def test_v07_constraints(conn) -> None:  # type: ignore[no-untyped-def]
    connection, user = conn
    job = (
        "INSERT INTO ai_processing_jobs (id, job_type, status, owner_id, max_attempts, run_after,"
        " dedupe_key) VALUES ($1, $2, 'QUEUED', $3, 3, now(), $4)"
    )
    # 성장 작업은 녹음 없이 가능, 같은 dedupe_key 진행 중 작업은 1개
    await connection.execute(job, uuid.uuid4(), "PRACTICE_RECOMMEND", user, "k1")
    with pytest.raises(asyncpg.UniqueViolationError):
        await connection.execute(job, uuid.uuid4(), "PRACTICE_RECOMMEND", user, "k1")
    # 녹음 작업은 여전히 녹음 필수
    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(job, uuid.uuid4(), "TRANSCRIBE", user, None)
    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(job, uuid.uuid4(), "UNKNOWN", user, None)
    consent = (
        "INSERT INTO ai_processing_consents (id, user_id, provider, purpose, policy_version,"
        " granted_by, granted_at) VALUES ($1, $2, 'GOOGLE_GEMINI', $3, 'v', 'SELF', now())"
    )
    # 목적별로 유효 동의 1개씩
    await connection.execute(consent, uuid.uuid4(), user, "FEEDBACK_SUMMARY")
    await connection.execute(consent, uuid.uuid4(), user, "GROWTH_COACHING")
    with pytest.raises(asyncpg.UniqueViolationError):
        await connection.execute(consent, uuid.uuid4(), user, "GROWTH_COACHING")
    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(consent, uuid.uuid4(), user, "MARKETING")
    report = (
        "INSERT INTO growth_reports (id, owner_id, scope, academy_id, period_type, period_end,"
        " status, metrics, data_fingerprint, dedupe_key, analysis_version, narrative_status)"
        " VALUES ($1, $2, $3, NULL, 'ALL', current_date, 'READY', '{}'::jsonb, 'f', $4, 'v',"
        " 'NOT_REQUESTED')"
    )
    await connection.execute(report, uuid.uuid4(), user, "ALL", "d1")
    with pytest.raises(asyncpg.UniqueViolationError):
        await connection.execute(report, uuid.uuid4(), user, "ALL", "d1")
    with pytest.raises(asyncpg.CheckViolationError):  # ACADEMY인데 academy_id 없음
        await connection.execute(report, uuid.uuid4(), user, "ACADEMY", "d2")


async def test_v07_roundtrip_keeps_feedback_consent(conn) -> None:  # type: ignore[no-untyped-def]
    connection, user = conn
    try:
        _alembic("downgrade", "0006")
        # 0006 시점의 첨삭 요약 동의 (purpose 컬럼 없음)
        await connection.execute(
            "INSERT INTO ai_processing_consents (id, user_id, provider, policy_version, granted_by,"
            " granted_at) VALUES ($1, $2, 'GOOGLE_GEMINI', 'v', 'SELF', now())",
            uuid.uuid4(),
            user,
        )
        _alembic("upgrade", "0007")
        assert (
            await connection.fetchval(
                "SELECT purpose FROM ai_processing_consents WHERE user_id = $1", user
            )
            == "FEEDBACK_SUMMARY"
        )
        await connection.execute(
            "INSERT INTO ai_processing_consents (id, user_id, provider, purpose, policy_version,"
            " granted_by, granted_at) VALUES ($1, $2, 'GOOGLE_GEMINI', 'GROWTH_COACHING', 'g',"
            " 'SELF', now())",
            uuid.uuid4(),
            user,
        )
        await connection.execute(
            "INSERT INTO ai_processing_jobs (id, job_type, status, owner_id, max_attempts,"
            " run_after) VALUES ($1, 'GROWTH_REPORT', 'QUEUED', $2, 3, now())",
            uuid.uuid4(),
            user,
        )
        # 되돌리면 성장 동의·작업만 지우고 첨삭 요약 동의는 보존
        _alembic("downgrade", "0006")
        rows = await connection.fetch(
            "SELECT policy_version FROM ai_processing_consents WHERE user_id = $1", user
        )
        assert [r["policy_version"] for r in rows] == ["v"]
        assert await connection.fetchval("SELECT count(*) FROM ai_processing_jobs") == 0
        _alembic("upgrade", "head")
        assert "No new upgrade operations detected" in _alembic("check")
        assert "0006 -> 0007 (head)" in _alembic("history")
    finally:
        _alembic("upgrade", "head")
