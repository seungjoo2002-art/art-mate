"""Alembic 0006 (v0.6 AI 첨삭) 검증: RLS, 제약·인덱스, 기존 데이터 보존 왕복."""

import uuid

import asyncpg
import pytest

from tests.db.test_migrations import _asyncpg_dsn
from tests.db.test_migrations_v051 import _alembic

V06_TABLES = [
    "ai_processing_consents",
    "ai_processing_jobs",
    "feedback_transcripts",
    "feedback_summaries",
    "feedback_items",
    "feedback_categories",
    "feedback_review_history",
]


async def test_v06_schema(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        rls = dict(
            await conn.fetch(
                "SELECT relname, relrowsecurity FROM pg_class"
                " WHERE relname = ANY($1::text[]) AND relkind = 'r'",
                V06_TABLES,
            )
        )
        indexes = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])", V06_TABLES
            )
        }
        constraints = {
            r["conname"]
            for r in await conn.fetch(
                "SELECT conname FROM pg_constraint"
                " WHERE conrelid::regclass::text = ANY($1::text[])",
                V06_TABLES,
            )
        }
    finally:
        await conn.close()
    assert rls == dict.fromkeys(V06_TABLES, True)
    assert {
        "uq_ai_processing_jobs_active",
        "ix_ai_processing_jobs_queue",
        "ix_ai_processing_jobs_lease",
        "uq_ai_processing_consents_active",
        "uq_feedback_summaries_current",
        "ix_feedback_items_category",
        "ix_feedback_categories_category",
    } <= indexes
    assert {
        "ck_ai_processing_jobs_running_has_lease",
        "ck_ai_processing_jobs_attempts_range",
        "ck_feedback_summaries_approved_has_time",
        "ck_feedback_items_category",
        "ck_feedback_items_content_not_blank",
        "uq_feedback_categories_summary_id_category",
        "fk_feedback_summaries_recording_id_feedback_recordings",
        "fk_ai_processing_jobs_recording_id_feedback_recordings",
    } <= constraints


@pytest.fixture
async def seeded(migrated_database: str):  # type: ignore[no-untyped-def]
    """프로필·작품·동의·녹음 1건 (커밋, 끝나면 프로필 삭제로 CASCADE 정리)."""
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    ids = {k: uuid.uuid4() for k in ("profile", "artwork", "consent", "recording")}
    await conn.execute(
        "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, 's', 'STUDENT')",
        ids["profile"],
    )
    await conn.execute(
        "INSERT INTO artworks (id, owner_id, title, work_date) VALUES ($1, $2, 'a', '2026-11-01')",
        ids["artwork"],
        ids["profile"],
    )
    await conn.execute(
        "INSERT INTO recording_consents (id, user_id, consent_type, policy_version, granted_by,"
        " granted_at) VALUES ($1, $2, 'VOICE_RECORDING', 'v1', 'SELF', now())",
        ids["consent"],
        ids["profile"],
    )
    await conn.execute(
        "INSERT INTO feedback_recordings (id, artwork_id, owner_id, consent_id,"
        " speaker_notice_confirmed, status, storage_path, content_type, duration_ms,"
        " upload_expires_at, transcription_status) VALUES ($1, $2, $3, $4, true, 'PENDING', $5,"
        " 'audio/webm', 1000, now(), 'NOT_REQUESTED')",
        ids["recording"],
        ids["artwork"],
        ids["profile"],
        ids["consent"],
        f"p/{ids['recording']}",
    )
    try:
        yield conn, ids
    finally:
        await conn.execute("DELETE FROM profiles WHERE id = $1", ids["profile"])
        await conn.close()


async def test_v06_constraints(seeded) -> None:  # type: ignore[no-untyped-def]
    conn, ids = seeded
    job_sql = (
        "INSERT INTO ai_processing_jobs (id, job_type, status, recording_id, artwork_id, owner_id,"
        " max_attempts, run_after) VALUES ($1, $2, $3, $4, $5, $6, 3, now())"
    )
    args = (ids["recording"], ids["artwork"], ids["profile"])
    await conn.execute(job_sql, uuid.uuid4(), "TRANSCRIBE", "QUEUED", *args)
    # 같은 녹음·종류의 진행 중 작업은 1개
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(job_sql, uuid.uuid4(), "TRANSCRIBE", "QUEUED", *args)
    await conn.execute(job_sql, uuid.uuid4(), "TRANSCRIBE", "FAILED", *args)  # 끝난 작업은 여러 개
    # RUNNING은 lease 필요, 알 수 없는 작업 종류 거부
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            "UPDATE ai_processing_jobs SET status = 'RUNNING' WHERE status = 'QUEUED'"
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(job_sql, uuid.uuid4(), "TRANSLATE", "QUEUED", *args)

    transcript = uuid.uuid4()
    await conn.execute(
        "INSERT INTO feedback_transcripts (id, recording_id, artwork_id, owner_id, language, text,"
        " segments, segment_count, engine, model_name) VALUES ($1, $2, $3, $4, 'ko', 't',"
        " '[]'::jsonb, 0, 'fw', 'small')",
        transcript,
        *args,
    )
    summary_sql = (
        "INSERT INTO feedback_summaries (id, recording_id, artwork_id, owner_id, transcript_id,"
        " status, review_mode, summary, ai_output, model_name, prompt_version, approved_at)"
        " VALUES ($1, $2, $3, $4, $5, $6, 'SELF', 's', '{}'::jsonb, 'm', 'p', NULL)"
    )
    await conn.execute(summary_sql, uuid.uuid4(), *args, transcript, "DRAFT")
    # 녹음당 현재 첨삭(DRAFT/IN_REVIEW/APPROVED) 1개
    with pytest.raises(asyncpg.UniqueViolationError):
        await conn.execute(summary_sql, uuid.uuid4(), *args, transcript, "IN_REVIEW")
    await conn.execute(summary_sql, uuid.uuid4(), *args, transcript, "SUPERSEDED")
    # APPROVED ⇔ approved_at
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            "UPDATE feedback_summaries SET status = 'APPROVED' WHERE status = 'DRAFT'"
        )
    summary_id = await conn.fetchval("SELECT id FROM feedback_summaries WHERE status = 'DRAFT'")
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            "INSERT INTO feedback_items (id, summary_id, kind, position, content, origin)"
            " VALUES ($1, $2, 'WEAKNESS', 0, '   ', 'AI')",
            uuid.uuid4(),
            summary_id,
        )
    with pytest.raises(asyncpg.CheckViolationError):
        await conn.execute(
            "INSERT INTO feedback_categories (id, summary_id, category, origin)"
            " VALUES ($1, $2, 'LIGHTING', 'AI')",
            uuid.uuid4(),
            summary_id,
        )
    # 녹음을 물리 삭제하면 파생 데이터도 CASCADE
    await conn.execute("DELETE FROM feedback_recordings WHERE id = $1", ids["recording"])
    remaining = await conn.fetchval(
        "SELECT (SELECT count(*) FROM ai_processing_jobs) + (SELECT count(*) FROM"
        " feedback_summaries) + (SELECT count(*) FROM feedback_transcripts)"
    )
    assert remaining == 0


async def test_v06_roundtrip_keeps_existing_data(seeded) -> None:  # type: ignore[no-untyped-def]
    conn, ids = seeded
    try:
        _alembic("downgrade", "0005")
        tables = await conn.fetchval(
            "SELECT count(*) FROM pg_class WHERE relname = ANY($1::text[]) AND relkind = 'r'",
            V06_TABLES,
        )
        assert tables == 0
        # 기존 녹음·작품은 그대로 (0006은 기존 테이블을 바꾸지 않는다)
        kept = await conn.fetchval(
            "SELECT count(*) FROM feedback_recordings WHERE id = $1", ids["recording"]
        )
        assert kept == 1
        _alembic("upgrade", "head")
        assert "No new upgrade operations detected" in _alembic("check")
        assert "0005 -> 0006" in _alembic("history")
    finally:
        _alembic("upgrade", "head")
