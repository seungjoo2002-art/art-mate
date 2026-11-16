"""v0.9.9 /health/db 스키마 버전 점검 — 실제 PostgreSQL(테스트 DB, head로 마이그레이션됨).

v0.9.8 장애 재현: 코드는 0015를 요구하는데 DB가 0014 → 503 DATABASE_SCHEMA_MISMATCH.
alembic_version만 잠깐 바꿨다가 되돌린다 (테스트 전용 DB).
"""

import httpx
from sqlalchemy import text

from app.db.schema_version import code_revisions

API = "/api/v1"


async def _set_revision(app, revision: str | None) -> None:  # type: ignore[no-untyped-def]
    async with app.state.database.engine.begin() as conn:
        await conn.execute(text("DELETE FROM alembic_version"))
        if revision is not None:
            await conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:r)"), {"r": revision}
            )


async def test_db_health_reports_matching_schema(client: httpx.AsyncClient) -> None:
    head = code_revisions()
    assert head is not None
    response = await client.get(f"{API}/health/db")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["schema_status"] == "ok"
    assert body["db_revision"] == body["code_revision"] == ",".join(head.heads)


async def test_db_health_fails_when_code_is_ahead_of_database(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, app
) -> None:
    head = code_revisions()
    assert head is not None and len(head.heads) == 1
    older = sorted(head.known - set(head.heads))[-1]  # 이전 revision (예: 0014)
    try:
        await _set_revision(app, older)
        behind = await client.get(f"{API}/health/db")
        await _set_revision(app, None)
        missing = await client.get(f"{API}/health/db")
        await _set_revision(app, "9999_future")
        ahead = await client.get(f"{API}/health/db")
    finally:
        await _set_revision(app, head.heads[0])

    assert behind.status_code == 503
    error = behind.json()["error"]
    assert error["code"] == "DATABASE_SCHEMA_MISMATCH"
    assert error["details"] == {
        "schema_status": "behind",
        "db_revision": older,
        "code_revision": head.heads[0],
    }
    for secret in ("postgresql", "127.0.0.1", "password"):
        assert secret not in behind.text

    assert missing.status_code == 503
    assert missing.json()["error"]["details"]["schema_status"] == "missing"

    # 마이그레이션을 먼저 적용한 정상 순서 (DB가 더 새 버전) → 장애 아님
    assert ahead.status_code == 200
    assert ahead.json()["schema_status"] == "ahead"

    restored = await client.get(f"{API}/health/db")
    assert restored.json()["schema_status"] == "ok"
