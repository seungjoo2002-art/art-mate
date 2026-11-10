"""Alembic 0009 (v0.9) 검증: 새 테이블 RLS·제약·인덱스, 기존 행 기본값, 왕복(downgrade 0008)."""

import asyncpg
import pytest

from tests.db.test_migrations import _asyncpg_dsn
from tests.db.test_migrations_v051 import _alembic

V09_TABLES = [
    "target_universities",
    "artwork_timer_events",
    "feedback_notes",
    "practice_recommendation_artworks",
    "notifications",
    "notification_preferences",
]


async def test_v09_schema_and_roundtrip(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        rls = dict(
            await conn.fetch(
                "SELECT relname, relrowsecurity FROM pg_class"
                " WHERE relname = ANY($1::text[]) AND relkind = 'r'",
                V09_TABLES,
            )
        )
        indexes = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])",
                [*V09_TABLES, "feedback_summaries", "ai_processing_jobs"],
            )
        }
        checks = {
            r["conname"]
            for r in await conn.fetch("SELECT conname FROM pg_constraint WHERE contype = 'c'")
        }
        deferrable = await conn.fetchval(
            "SELECT condeferrable AND condeferred FROM pg_constraint"
            " WHERE conname = 'uq_target_universities_user_priority'"
        )
        nullable = dict(
            await conn.fetch(
                "SELECT column_name, is_nullable FROM information_schema.columns"
                " WHERE table_name = 'feedback_summaries'"
                " AND column_name IN ('recording_id', 'transcript_id', 'note_id')"
            )
        )
        category_check = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conname = 'ck_feedback_categories_category'"
        )
    finally:
        await conn.close()
    assert rls == dict.fromkeys(V09_TABLES, True)
    assert {
        "uq_feedback_summaries_current_note",
        "uq_ai_processing_jobs_active_note",
        "uq_feedback_notes_comment",
        "uq_notifications_user_dedupe",
    } <= indexes
    assert {
        "ck_feedback_summaries_one_source",
        "ck_ai_processing_jobs_summarize_has_source",
        "ck_artworks_actual_minutes_range",
        "ck_artworks_time_limit_range",
        "ck_community_comments_categories_known",
        "ck_practice_recommendations_started_after_adopt",
    } <= checks
    assert deferrable is True
    assert nullable == {"recording_id": "YES", "transcript_id": "YES", "note_id": "YES"}
    assert "TIME_MANAGEMENT" in category_check
    try:
        _alembic("downgrade", "0008")
        _alembic("upgrade", "head")
        assert "No new upgrade operations detected" in _alembic("check")
        assert "0008 -> 0009 (head)" in _alembic("history")
    finally:
        _alembic("upgrade", "head")


@pytest.mark.parametrize(
    "sql",
    [
        # 실제 소요 시간 0분·음수 거부
        "INSERT INTO artworks (id, owner_id, title, work_date, work_status, actual_minutes,"
        " time_source) VALUES (gen_random_uuid(), $1, 't', current_date, 'IN_PROGRESS', 0,"
        " 'MANUAL')",
        # 시간 출처 없이 시간만 기록 불가
        "INSERT INTO artworks (id, owner_id, title, work_date, work_status, actual_minutes)"
        " VALUES (gen_random_uuid(), $1, 't', current_date, 'IN_PROGRESS', 30)",
        # 알 수 없는 출처
        "INSERT INTO feedback_notes (id, artwork_id, owner_id, source, body, segments,"
        " segment_count, feedback_date) VALUES (gen_random_uuid(), gen_random_uuid(), $1,"
        " 'TEACHER', 'x', '[]', 1, current_date)",
        # 지망 순위 0
        "INSERT INTO target_universities (id, user_id, university_name, priority)"
        " VALUES (gen_random_uuid(), $1, '대학', 0)",
    ],
)
async def test_v09_constraints(migrated_database: str, sql: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        user = await conn.fetchval(
            "INSERT INTO profiles (id, display_name, user_type) VALUES (gen_random_uuid(),"
            " 'mig', 'STUDENT') RETURNING id"
        )
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(sql, user)
    finally:
        await conn.execute("DELETE FROM profiles WHERE display_name = 'mig'")
        await conn.close()
