"""Alembic 0008 (v0.8) 검증: RLS·제약·왕복, Storage 권한 함수 can_access_shared_image."""

import asyncpg
import httpx
import pytest
from sqlalchemy import text

from tests.db.conftest import World
from tests.db.test_community_api import _final_artwork, _post, _share
from tests.db.test_migrations import _asyncpg_dsn
from tests.db.test_migrations_v051 import _alembic

V08_TABLES = [
    "artwork_sharing_consents",
    "shared_artwork_images",
    "reference_artwork_reviews",
    "reference_recommendations",
    "community_posts",
    "community_comments",
    "community_likes",
    "community_bookmarks",
    "community_reports",
    "community_moderation_logs",
]


async def test_v08_schema_and_roundtrip(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        rls = dict(
            await conn.fetch(
                "SELECT relname, relrowsecurity FROM pg_class"
                " WHERE relname = ANY($1::text[]) AND relkind = 'r'",
                V08_TABLES,
            )
        )
        indexes = {
            r["indexname"]
            for r in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])", V08_TABLES
            )
        }
        fn = await conn.fetchrow(
            "SELECT p.prosecdef, p.proconfig, has_function_privilege('public', p.oid, 'EXECUTE')"
            " AS public_exec FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'artmate_private' AND p.proname = 'can_access_shared_image'"
        )
    finally:
        await conn.close()
    assert rls == dict.fromkeys(V08_TABLES, True)
    assert {
        "uq_artwork_sharing_consents_active",
        "uq_shared_artwork_images_live",
        "uq_reference_artwork_reviews_active",
        "uq_community_posts_live_artwork",
        "uq_community_likes_post_id_user_id",
        "uq_community_bookmarks_post_id_user_id",
        "uq_community_reports_post",
        "uq_community_reports_comment",
    } <= indexes
    assert fn["prosecdef"] is True and fn["proconfig"] == ['search_path=""']
    assert fn["public_exec"] is False
    try:
        _alembic("downgrade", "0007")
        _alembic("upgrade", "head")
        assert "No new upgrade operations detected" in _alembic("check")
        assert "0007 -> 0008," in _alembic("history")
    finally:
        _alembic("upgrade", "head")


async def test_shared_image_storage_policy_function(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, app, actors, build_world
) -> None:
    photos = app.state.storage
    author = world.students[0]
    academy_art = await _final_artwork(client, photos, author, academy_id=world.academy_id)
    await _share(client, author, academy_art, scope="ACADEMY")
    await _post(client, author, academy_art)
    platform_art = await _final_artwork(client, photos, author, "참고작")
    await _share(client, author, platform_art, purpose="REFERENCE")
    outsider = (await build_world("다른 학원", admin=world.admin)).students[0]
    loner = await actors.signup("STUDENT")

    async def path(artwork_id: str) -> str:
        async with app.state.database.engine.begin() as conn:
            return (
                await conn.execute(
                    text(
                        "SELECT storage_path FROM shared_artwork_images"
                        " WHERE artwork_id = :a AND status = 'ACTIVE'"
                    ),
                    {"a": artwork_id},
                )
            ).scalar_one()

    async def can(user, object_name: str, mode: str = "read") -> bool:  # type: ignore[no-untyped-def]
        async with app.state.database.engine.begin() as conn:
            return (
                await conn.execute(
                    text("SELECT artmate_private.can_access_shared_image(:u, :n, :m)"),
                    {"u": str(user.user_id), "n": object_name, "m": mode},
                )
            ).scalar_one()

    academy_path, platform_path = await path(academy_art), await path(platform_art)
    # ACADEMY 공개: 같은 학원 멤버만 (강사 포함), 소유자
    assert await can(author, academy_path)
    assert await can(world.students[1], academy_path)
    assert await can(world.teacher, academy_path)
    assert not await can(outsider, academy_path)
    assert not await can(loner, academy_path)
    # PLATFORM 참고작: 활성 프로필 누구나
    assert await can(loner, platform_path) and await can(outsider, platform_path)
    # 쓰기(업로드·삭제)는 소유자만
    assert await can(author, platform_path, "write")
    assert not await can(loner, platform_path, "write")
    # 원본 사진 경로로는 접근 불가 (이 함수는 공유 이미지 행만 인정)
    async with app.state.database.engine.begin() as conn:
        original = (
            await conn.execute(
                text("SELECT storage_path FROM artwork_photos WHERE artwork_id = :a"),
                {"a": platform_art},
            )
        ).scalar_one()
    assert not await can(loner, original)
    # 커뮤니티 게시물이 숨겨지면 커뮤니티 동의만 있는 이미지는 막힘
    async with app.state.database.engine.begin() as conn:
        await conn.execute(
            text("UPDATE community_posts SET status = 'HIDDEN' WHERE artwork_id = :a"),
            {"a": academy_art},
        )
    assert not await can(world.students[1], academy_path)
    assert await can(author, academy_path)  # 소유자는 계속
    # 공유 철회 → 아무도 못 읽음 (파일도 삭제됨)
    await client.delete(
        f"/api/v1/artworks/{platform_art}/sharing/REFERENCE", headers=author.headers
    )
    assert not await can(loner, platform_path)
    assert not await can(author, platform_path)


@pytest.mark.parametrize("bad", ["purpose", "scope"])
async def test_v08_constraints(migrated_database: str, bad: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                "INSERT INTO artwork_sharing_consents (id, artwork_id, owner_id, purpose, scope,"
                " academy_id, author_display, policy_version, granted_by, granted_at)"
                " VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), $1, $2, NULL,"
                " 'NAME', 'v', 'SELF', now())",
                "MARKETING" if bad == "purpose" else "COMMUNITY",
                "PLATFORM" if bad == "purpose" else "ACADEMY",  # ACADEMY인데 academy_id 없음
            )
    finally:
        await conn.close()
