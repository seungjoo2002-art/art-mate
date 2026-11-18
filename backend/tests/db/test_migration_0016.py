"""0015 → 0016 (v1.1 원본 제시물·시험 조건·표현 의도).

기존 작품·사진 데이터를 그대로 두고 기본값만 추가한다.
"""

import uuid

import asyncpg

from tests.db.test_migrations import _asyncpg_dsn
from tests.db.test_migrations_v051 import _alembic


async def test_upgrade_keeps_existing_artworks_and_photos(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    user, artwork, stage, photo = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    path = f"{user}/{artwork}/{photo}.png"
    try:
        _alembic("downgrade", "0015")
        await conn.execute(
            "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, '학생', 'STUDENT')",
            user,
        )
        await conn.execute(
            "INSERT INTO artworks (id, owner_id, title, work_date, topic, description)"
            " VALUES ($1, $2, '기존 작품', current_date, '유리컵', '메모')",
            artwork,
            user,
        )
        await conn.execute(
            "INSERT INTO artwork_stages (id, artwork_id, owner_id, position, name, legacy_stage)"
            " VALUES ($1, $2, $3, 0, '스케치', 'SKETCH')",
            stage,
            artwork,
            user,
        )
        await conn.execute(
            "INSERT INTO artwork_photos (id, artwork_id, owner_id, stage, stage_id, kind, status,"
            " storage_path, content_type, upload_expires_at, uploaded_at, size_bytes, width,"
            " height, sha256) VALUES ($1, $2, $3, 'SKETCH', $4, 'STAGE', 'ACTIVE', $5,"
            " 'image/png', now(), now(), 100, 32, 24, repeat('a', 64))",
            photo,
            artwork,
            user,
            stage,
            path,
        )

        _alembic("upgrade", "head")
        row = await conn.fetchrow(
            "SELECT title, topic, description, paper_size, exam_conditions, expression_methods,"
            " expression_intent FROM artworks WHERE id = $1",
            artwork,
        )
        assert (row["title"], row["topic"], row["description"]) == ("기존 작품", "유리컵", "메모")
        assert row["paper_size"] is None and row["exam_conditions"] is None
        assert row["expression_methods"] == [] and row["expression_intent"] is None
        # 기존 사진 경로·권한은 그대로
        assert (
            await conn.fetchval("SELECT storage_path FROM artwork_photos WHERE id = $1", photo)
            == path
        )
        assert await conn.fetchval(
            "SELECT artmate_private.can_access_artwork_object($1, $2, 'read')", user, path
        )
        assert await conn.fetchval("SELECT count(*) FROM artwork_reference_photos") == 0
        # 표현 방식 값 제한
        try:
            await conn.execute(
                "UPDATE artworks SET expression_methods = ARRAY['MAGIC']::varchar[] WHERE id = $1",
                artwork,
            )
            raise AssertionError("invalid method accepted")
        except asyncpg.CheckViolationError:
            pass
    finally:
        await conn.execute("DELETE FROM profiles WHERE id = $1", user)
        await conn.close()
