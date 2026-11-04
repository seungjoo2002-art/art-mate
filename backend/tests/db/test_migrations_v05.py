"""Alembic 0004 검증: RLS·제약·인덱스, 녹음 Storage 권한 함수, 대기열 제약."""

import uuid

import asyncpg
import pytest

from tests.db.test_migrations import _asyncpg_dsn

V05_TABLES = ["help_requests", "help_queue_events", "feedback_recordings", "recording_consents"]


async def test_v05_schema(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        rls = dict(
            await conn.fetch(
                "SELECT relname, relrowsecurity FROM pg_class "
                "WHERE relname = ANY($1::text[]) AND relkind = 'r'",
                V05_TABLES,
            )
        )
        indexes = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])", V05_TABLES
            )
        }
        constraints = {
            r["conname"]
            for r in await conn.fetch(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid::regclass::text = ANY($1::text[])",
                V05_TABLES,
            )
        }
        functions = await conn.fetch(
            "SELECT p.proname, p.prosecdef, p.proconfig,"
            " has_function_privilege('public', p.oid, 'EXECUTE') AS public_exec"
            " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'artmate_private'"
        )
        identity = await conn.fetchval(
            "SELECT is_identity FROM information_schema.columns"
            " WHERE table_name = 'help_requests' AND column_name = 'queue_seq'"
        )
    finally:
        await conn.close()

    assert rls == dict.fromkeys(V05_TABLES, True)
    assert identity == "YES"
    assert {
        "uq_help_requests_active_student",
        "ix_help_requests_class_status_seq",
        "ix_help_requests_class_completed",
        "uq_feedback_recordings_active_sha256",
        "uq_recording_consents_active",
        "ix_feedback_recordings_transcription_pending",
    } <= indexes
    assert {
        "fk_help_requests_academy_id_classes",
        "fk_help_requests_academy_id_academy_memberships",
        "fk_help_queue_events_academy_id_help_requests",
        "fk_feedback_recordings_artwork_id_artworks",
        "fk_feedback_recordings_consent_id_recording_consents",
        "uq_feedback_recordings_storage_path",
        "ck_help_requests_called_has_time",
        "ck_feedback_recordings_transcription_status",
    } <= constraints
    by_name = {f["proname"]: f for f in functions}
    for name in ("can_access_artwork_object", "manages_student", "can_access_recording_object"):
        assert by_name[name]["prosecdef"] is True, name
        assert by_name[name]["proconfig"] == ['search_path=""'], name
        assert by_name[name]["public_exec"] is False, name


@pytest.fixture
async def conn(migrated_database: str):  # type: ignore[no-untyped-def]
    connection = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    tx = connection.transaction()
    await tx.start()
    yield connection
    await tx.rollback()
    await connection.close()


async def _seed(conn: asyncpg.Connection) -> dict[str, uuid.UUID]:
    ids = {
        k: uuid.uuid4()
        for k in (
            "student",
            "teacher",
            "other_teacher",
            "stranger",
            "academy",
            "m_student",
            "m_teacher",
            "m_other",
            "class",
            "art",
            "personal",
            "consent",
            "rec",
            "personal_rec",
        )
    }
    for user, kind in (
        ("student", "STUDENT"),
        ("teacher", "INSTRUCTOR"),
        ("other_teacher", "INSTRUCTOR"),
        ("stranger", "STUDENT"),
    ):
        await conn.execute(
            "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, $2, $3)",
            ids[user],
            user,
            kind,
        )
    await conn.execute(
        "INSERT INTO academies (id, name, status) VALUES ($1, 'A', 'ACTIVE')", ids["academy"]
    )
    for key, user, role in (
        ("m_student", "student", "STUDENT"),
        ("m_teacher", "teacher", "INSTRUCTOR"),
        ("m_other", "other_teacher", "INSTRUCTOR"),
    ):
        await conn.execute(
            "INSERT INTO academy_memberships (id, academy_id, user_id, role, status, joined_at)"
            " VALUES ($1, $2, $3, $4, 'ACTIVE', now())",
            ids[key],
            ids["academy"],
            ids[user],
            role,
        )
    await conn.execute(
        "INSERT INTO classes (id, academy_id, name, status) VALUES ($1, $2, 'A반', 'ACTIVE')",
        ids["class"],
        ids["academy"],
    )
    for member, role in (("m_teacher", "INSTRUCTOR"), ("m_student", "STUDENT")):
        await conn.execute(
            "INSERT INTO class_memberships (id, academy_id, class_id, membership_id, role, status,"
            " joined_at) VALUES ($1, $2, $3, $4, $5, 'ACTIVE', now())",
            uuid.uuid4(),
            ids["academy"],
            ids["class"],
            ids[member],
            role,
        )
    await conn.execute(
        "INSERT INTO artworks (id, owner_id, academy_id, student_membership_id, title, work_date)"
        " VALUES ($1, $2, $3, $4, 'a', '2026-11-04')",
        ids["art"],
        ids["student"],
        ids["academy"],
        ids["m_student"],
    )
    await conn.execute(
        "INSERT INTO artworks (id, owner_id, title, work_date) VALUES ($1, $2, 'p', '2026-11-04')",
        ids["personal"],
        ids["student"],
    )
    await conn.execute(
        "INSERT INTO recording_consents (id, user_id, consent_type, policy_version, granted_by,"
        " granted_at) VALUES ($1, $2, 'VOICE_RECORDING', 'v1', 'SELF', now())",
        ids["consent"],
        ids["student"],
    )
    return ids


async def _recording(conn: asyncpg.Connection, ids: dict, rec: str, art: str) -> str:  # type: ignore[type-arg]
    path = f"{ids['student']}/{ids[art]}/{ids[rec]}.webm"
    await conn.execute(
        "INSERT INTO feedback_recordings (id, artwork_id, owner_id, consent_id,"
        " speaker_notice_confirmed, status, storage_path, content_type, size_bytes, duration_ms,"
        " sha256, upload_expires_at, uploaded_at, transcription_status)"
        " VALUES ($1, $2, $3, $4, true, 'ACTIVE', $5, 'audio/webm', 1, 1000, $6, now(), now(),"
        " 'NOT_REQUESTED')",
        ids[rec],
        ids[art],
        ids["student"],
        ids["consent"],
        path,
        ids[rec].hex * 2,
    )
    return path


async def test_recording_storage_access_function(conn: asyncpg.Connection) -> None:
    ids = await _seed(conn)
    path = await _recording(conn, ids, "rec", "art")
    personal = await _recording(conn, ids, "personal_rec", "personal")

    async def can(user: str, object_path: str, mode: str) -> bool:
        return await conn.fetchval(
            "SELECT artmate_private.can_access_recording_object($1, $2, $3)",
            ids[user],
            object_path,
            mode,
        )

    assert await can("student", path, "read") and await can("student", path, "write")
    assert await can("teacher", path, "read") and not await can("teacher", path, "write")
    assert not await can("other_teacher", path, "read")  # 반 담당 아님
    assert not await can("stranger", path, "read")
    assert not await can("teacher", personal, "read")  # 개인 작품
    assert await can("student", personal, "read")
    await conn.execute(
        "UPDATE feedback_recordings SET status = 'DELETED' WHERE id = $1", ids["rec"]
    )
    assert not await can("teacher", path, "read") and not await can("student", path, "read")
    assert await can("student", path, "write")  # 정리용 삭제는 가능


async def test_help_request_constraints(conn: asyncpg.Connection) -> None:
    ids = await _seed(conn)
    insert = (
        "INSERT INTO help_requests (id, academy_id, class_id, student_membership_id, status,"
        " requested_at) VALUES ($1, $2, $3, $4, $5, now())"
    )
    await conn.execute(
        insert, uuid.uuid4(), ids["academy"], ids["class"], ids["m_student"], "WAITING"
    )
    # 같은 학생·같은 반 활성 요청 2개 → 부분 유니크 위반
    with pytest.raises(asyncpg.UniqueViolationError):
        async with conn.transaction():
            await conn.execute(
                insert, uuid.uuid4(), ids["academy"], ids["class"], ids["m_student"], "WAITING"
            )
    # CALLED인데 called_at 없음 → CHECK 위반
    with pytest.raises(asyncpg.CheckViolationError):
        async with conn.transaction():
            await conn.execute(
                insert, uuid.uuid4(), ids["academy"], ids["class"], ids["m_teacher"], "CALLED"
            )
    # 다른 학원 반에 연결 → 복합 FK 위반
    other_academy = uuid.uuid4()
    await conn.execute(
        "INSERT INTO academies (id, name, status) VALUES ($1, 'B', 'ACTIVE')", other_academy
    )
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        async with conn.transaction():
            await conn.execute(
                insert, uuid.uuid4(), other_academy, ids["class"], ids["m_other"], "WAITING"
            )
