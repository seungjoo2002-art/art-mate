"""Alembic 0005 (v0.5.1) 검증.

- 0004 시점의 기존 데이터가 있는 상태에서 적용 → 기본값(NULL, IN_PROGRESS)으로 호환
- downgrade 0004 → 기존 행 보존, 추가 컬럼만 제거 → 재적용
- CHECK 제약: 선택지 외 값, 완료 상태와 완료 시각 불일치를 DB가 거부
- 제외 기능 테이블은 0005가 건드리지 않는다 (삭제하지 않음)
"""

import uuid

import asyncpg
import pytest

from tests.db.conftest import run_alembic
from tests.db.test_migrations import _asyncpg_dsn

NEW_COLUMNS = {
    ("profiles", "practical_type"),
    ("artworks", "practical_type"),
    ("artworks", "work_category"),
    ("artworks", "work_status"),
    ("artworks", "completed_at"),
}
EXCLUDED_FEATURE_TABLES = [
    "attendance_records",
    "attendance_audit_logs",
    "personal_todos",
    "exam_templates",
    "exam_stage_targets",
    "exam_sessions",
    "exam_session_stages",
    "exam_participants",
    "help_requests",
    "help_queue_events",
]


def _alembic(*args: str) -> str:
    result = run_alembic(*args)
    assert result.returncode == 0, f"alembic {' '.join(args)}: {result.stderr[-2000:]}"
    return result.stdout + result.stderr


async def _columns(conn: asyncpg.Connection) -> set[tuple[str, str]]:
    rows = await conn.fetch(
        "SELECT table_name, column_name FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name IN ('profiles', 'artworks')"
    )
    return {(r["table_name"], r["column_name"]) for r in rows}


async def test_0005_follows_0004(migrated_database: str) -> None:
    history = _alembic("history")
    assert "0004 -> 0005" in history
    assert "0005 -> 0006" in history  # v0.6가 0005 다음에 연결됨


async def test_0005_upgrade_with_existing_data_and_roundtrip(migrated_database: str) -> None:
    dsn = _asyncpg_dsn(migrated_database)
    profile_id, artwork_id = uuid.uuid4(), uuid.uuid4()
    _alembic("downgrade", "0004")
    conn = await asyncpg.connect(dsn)
    try:
        assert not (NEW_COLUMNS & await _columns(conn))
        # v0.5 시점 데이터 (분류·완료 정보 없음)
        await conn.execute(
            "INSERT INTO profiles (id, display_name, user_type)"
            " VALUES ($1, '기존 학생', 'STUDENT')",
            profile_id,
        )
        await conn.execute(
            "INSERT INTO artworks (id, owner_id, title, work_date)"
            " VALUES ($1, $2, '기존 작품', '2026-11-01')",
            artwork_id,
            profile_id,
        )
        tables_before = {
            r["relname"]
            for r in await conn.fetch(
                "SELECT relname FROM pg_class WHERE relkind = 'r' AND relname = ANY($1::text[])",
                EXCLUDED_FEATURE_TABLES,
            )
        }

        _alembic("upgrade", "head")
        assert await _columns(conn) >= NEW_COLUMNS
        row = await conn.fetchrow(
            "SELECT practical_type, work_category, work_status, completed_at, title"
            " FROM artworks WHERE id = $1",
            artwork_id,
        )
        assert dict(row) == {
            "practical_type": None,
            "work_category": None,
            "work_status": "IN_PROGRESS",
            "completed_at": None,
            "title": "기존 작품",
        }
        assert (
            await conn.fetchval("SELECT practical_type FROM profiles WHERE id = $1", profile_id)
            is None
        )
        # 0005는 제외 기능 테이블을 삭제하지 않는다
        tables_after = {
            r["relname"]
            for r in await conn.fetch(
                "SELECT relname FROM pg_class WHERE relkind = 'r' AND relname = ANY($1::text[])",
                EXCLUDED_FEATURE_TABLES,
            )
        }
        assert tables_after == tables_before == set(EXCLUDED_FEATURE_TABLES)

        # 분류·완료 저장 후 되돌리기: 기존 행은 남고 추가 컬럼만 사라진다 → 재적용
        await conn.execute(
            "UPDATE artworks SET practical_type = 'BASIC_DESIGN', work_category = 'MOCK_EXAM',"
            " work_status = 'COMPLETED', completed_at = now() WHERE id = $1",
            artwork_id,
        )
        _alembic("downgrade", "0004")
        assert not (NEW_COLUMNS & await _columns(conn))
        assert await conn.fetchval("SELECT title FROM artworks WHERE id = $1", artwork_id) == (
            "기존 작품"
        )
        _alembic("upgrade", "head")
        assert (
            await conn.fetchval("SELECT work_status FROM artworks WHERE id = $1", artwork_id)
            == "IN_PROGRESS"
        )
        assert "No new upgrade operations detected" in _alembic("check")
    finally:
        _alembic("upgrade", "head")
        await conn.execute("DELETE FROM artworks WHERE id = $1", artwork_id)
        await conn.execute("DELETE FROM profiles WHERE id = $1", profile_id)
        await conn.close()


@pytest.mark.parametrize(
    ("sql", "constraint"),
    [
        ("UPDATE profiles SET practical_type = 'PAINTING'", "ck_profiles_practical_type"),
        ("UPDATE artworks SET practical_type = 'basic_design'", "ck_artworks_practical_type"),
        ("UPDATE artworks SET work_category = 'EXAM'", "ck_artworks_work_category"),
        ("UPDATE artworks SET work_status = 'DONE'", "ck_artworks_work_status"),
        ("UPDATE artworks SET work_status = 'COMPLETED'", "ck_artworks_completed_has_time"),
        ("UPDATE artworks SET completed_at = now()", "ck_artworks_completed_has_time"),
    ],
)
async def test_0005_check_constraints(migrated_database: str, sql: str, constraint: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    profile_id = uuid.uuid4()
    tx = conn.transaction()
    await tx.start()
    try:
        await conn.execute(
            "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, 's', 'STUDENT')",
            profile_id,
        )
        await conn.execute(
            "INSERT INTO artworks (id, owner_id, title, work_date)"
            " VALUES ($1, $2, 'a', '2026-11-01')",
            uuid.uuid4(),
            profile_id,
        )
        with pytest.raises(asyncpg.CheckViolationError) as exc:
            await conn.execute(
                f"{sql} WHERE {'id' if 'profiles' in sql else 'owner_id'} = $1", profile_id
            )
        assert exc.value.constraint_name == constraint
    finally:
        await tx.rollback()
        await conn.close()
