"""Alembic 0003 검증: RLS·제약·인덱스, Storage 권한 함수.

대상 함수: artmate_private.can_access_artwork_object
"""

import uuid

import asyncpg
import pytest

from tests.db.test_migrations import _asyncpg_dsn

V04_TABLES = [
    "artworks",
    "artwork_photos",
    "exam_templates",
    "exam_stage_targets",
    "exam_sessions",
    "exam_session_stages",
    "exam_participants",
]


async def test_v04_schema(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        rls = dict(
            await conn.fetch(
                "SELECT relname, relrowsecurity FROM pg_class "
                "WHERE relname = ANY($1::text[]) AND relkind = 'r'",
                V04_TABLES,
            )
        )
        constraints = {
            r["conname"]
            for r in await conn.fetch(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid::regclass::text = ANY($1::text[])",
                [*V04_TABLES, "academy_memberships"],
            )
        }
        indexes = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])", V04_TABLES
            )
        }
        function = await conn.fetchrow(
            "SELECT p.prosecdef, p.proconfig, has_function_privilege('public', p.oid, 'EXECUTE')"
            " AS public_exec FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'artmate_private' AND p.proname = 'can_access_artwork_object'"
        )
        timestamps = await conn.fetch(
            "SELECT table_name, count(*) FROM information_schema.columns "
            "WHERE table_name = ANY($1::text[]) AND column_name IN ('created_at', 'updated_at') "
            "GROUP BY table_name",
            V04_TABLES,
        )
    finally:
        await conn.close()

    assert rls == dict.fromkeys(V04_TABLES, True)
    assert {r["table_name"]: r["count"] for r in timestamps} == dict.fromkeys(V04_TABLES, 2)
    assert {
        "uq_academy_memberships_academy_id_id_user_id",
        "fk_artworks_academy_id_academy_memberships",
        "fk_artworks_academy_id_classes",
        "fk_artworks_academy_id_tasks",
        "fk_artwork_photos_artwork_id_artworks",
        "ck_artworks_academy_link_pair",
        "ck_artwork_photos_active_has_metadata",
        "uq_artwork_photos_storage_path",
        "uq_exam_stage_targets_template_id_stage",
        "uq_exam_participants_session_id_student_membership_id",
        "ck_exam_sessions_started_has_times",
    } <= constraints
    assert {
        "uq_artwork_photos_representative",
        "uq_artwork_photos_active_sha256",
        "uq_exam_sessions_running_class",
        "ix_artworks_owner_work_date",
    } <= indexes
    # SECURITY DEFINER + search_path 고정 + PUBLIC 실행 불가
    assert function is not None and function["prosecdef"] is True
    assert function["proconfig"] == ['search_path=""']
    assert function["public_exec"] is False


@pytest.fixture
async def conn(migrated_database: str):  # type: ignore[no-untyped-def]
    connection = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    tx = connection.transaction()
    await tx.start()
    yield connection
    await tx.rollback()  # 이 테스트의 데이터는 남기지 않는다
    await connection.close()


async def test_storage_access_function(conn: asyncpg.Connection) -> None:
    ids = {
        name: uuid.uuid4()
        for name in (
            "owner",
            "teacher",
            "other_teacher",
            "manager",
            "other_student",
            "outsider",
            "academy",
            "m_owner",
            "m_teacher",
            "m_other_teacher",
            "m_manager",
            "m_other_student",
            "class",
            "artwork",
            "personal",
            "photo",
            "personal_photo",
        )
    }
    for name in ("owner", "teacher", "other_teacher", "manager", "other_student", "outsider"):
        await conn.execute(
            "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, $2, $3)",
            ids[name],
            name,
            "STUDENT" if "student" in name or name == "owner" else "INSTRUCTOR",
        )
    await conn.execute(
        "INSERT INTO academies (id, name, status) VALUES ($1, 'A', 'ACTIVE')", ids["academy"]
    )
    memberships = {
        "m_owner": ("owner", "STUDENT"),
        "m_teacher": ("teacher", "INSTRUCTOR"),
        "m_other_teacher": ("other_teacher", "INSTRUCTOR"),
        "m_manager": ("manager", "MANAGER"),
        "m_other_student": ("other_student", "STUDENT"),
    }
    for key, (user, role) in memberships.items():
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
    for member, role in (("m_teacher", "INSTRUCTOR"), ("m_owner", "STUDENT")):
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
        " VALUES ($1, $2, $3, $4, '학원 작품', '2026-11-04')",
        ids["artwork"],
        ids["owner"],
        ids["academy"],
        ids["m_owner"],
    )
    await conn.execute(
        "INSERT INTO artworks (id, owner_id, title, work_date)"
        " VALUES ($1, $2, '개인', '2026-11-04')",
        ids["personal"],
        ids["owner"],
    )
    paths = {}
    for photo, artwork in (("photo", "artwork"), ("personal_photo", "personal")):
        paths[photo] = f"{ids['owner']}/{ids[artwork]}/{ids[photo]}.png"
        stage_id = uuid.uuid4()  # v0.9.7: 사진은 작품 단계에 연결된다
        await conn.execute(
            "INSERT INTO artwork_stages (id, artwork_id, owner_id, position, name, legacy_stage)"
            " VALUES ($1, $2, $3, 0, '스케치', 'SKETCH')",
            stage_id,
            ids[artwork],
            ids["owner"],
        )
        await conn.execute(
            "INSERT INTO artwork_photos (id, artwork_id, owner_id, stage, stage_id, status,"
            " storage_path, content_type, size_bytes, width, height, sha256, upload_expires_at,"
            " uploaded_at) VALUES ($1, $2, $3, 'SKETCH', $6, 'ACTIVE', $4, 'image/png', 1, 1, 1,"
            " $5, now(), now())",
            ids[photo],
            ids[artwork],
            ids["owner"],
            paths[photo],
            ids[photo].hex * 2,
            stage_id,
        )

    async def can(user: str, photo: str, mode: str) -> bool:
        return await conn.fetchval(
            "SELECT artmate_private.can_access_artwork_object($1, $2, $3)",
            ids[user],
            paths[photo],
            mode,
        )

    # 소유자: 읽기·쓰기
    assert await can("owner", "photo", "read") and await can("owner", "photo", "write")
    # 담당 강사·학원 관리자: 학원 작품 읽기만
    assert await can("teacher", "photo", "read") and not await can("teacher", "photo", "write")
    assert await can("manager", "photo", "read")
    # 비담당 강사, 다른 학생, 비소속: 불가
    for user in ("other_teacher", "other_student", "outsider"):
        assert not await can(user, "photo", "read"), user
    # 개인 작품은 소유자만
    assert await can("owner", "personal_photo", "read")
    assert not await can("teacher", "personal_photo", "read")
    assert not await can("manager", "personal_photo", "read")
    # 존재하지 않는 경로, NULL 사용자
    assert not await conn.fetchval(
        "SELECT artmate_private.can_access_artwork_object($1, 'x/y/z.png', 'read')", ids["owner"]
    )
    assert not await conn.fetchval(
        "SELECT artmate_private.can_access_artwork_object(NULL, $1, 'read')", paths["photo"]
    )
    # 학생이 학원을 떠나면 강사 읽기 불가, 삭제된 사진은 소유자도 읽기 불가 (정리용 쓰기는 가능)
    await conn.execute(
        "UPDATE academy_memberships SET status = 'LEFT' WHERE id = $1", ids["m_owner"]
    )
    assert not await can("teacher", "photo", "read")
    await conn.execute("UPDATE artwork_photos SET status = 'DELETED' WHERE id = $1", ids["photo"])
    assert not await can("owner", "photo", "read") and await can("owner", "photo", "write")


async def test_cross_owner_artwork_link_rejected(conn: asyncpg.Connection) -> None:
    """다른 사람의 학원 소속을 작품에 연결하면 3열 복합 FK가 거부한다."""
    owner, other, academy, membership = (uuid.uuid4() for _ in range(4))
    for user in (owner, other):
        await conn.execute(
            "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, 'x', 'STUDENT')", user
        )
    await conn.execute(
        "INSERT INTO academies (id, name, status) VALUES ($1, 'A', 'ACTIVE')", academy
    )
    await conn.execute(
        "INSERT INTO academy_memberships (id, academy_id, user_id, role, status, joined_at)"
        " VALUES ($1, $2, $3, 'STUDENT', 'ACTIVE', now())",
        membership,
        academy,
        other,
    )
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await conn.execute(
            "INSERT INTO artworks (id, owner_id, academy_id, student_membership_id, title,"
            " work_date) VALUES ($1, $2, $3, $4, 't', '2026-11-04')",
            uuid.uuid4(),
            owner,
            academy,
            membership,
        )
