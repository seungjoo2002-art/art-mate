"""프로필 생성·조회·수정, 권한 상승 방지."""

import asyncio

import httpx
import pytest
from sqlalchemy import text


async def test_profile_lifecycle(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    actor = actors.anonymous_token()

    missing = await client.get("/api/v1/users/me", headers=actor.headers)
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "PROFILE_NOT_FOUND")

    created = await client.post(
        "/api/v1/users/me",
        json={"display_name": "  김학생  ", "user_type": "STUDENT"},
        headers=actor.headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["id"] == str(actor.user_id)
    assert body["display_name"] == "김학생"
    assert body["user_type"] == "STUDENT"
    assert body["is_active"] is True
    assert body["email"].endswith("@example.com")  # 토큰에서 읽음 (DB 미저장)

    me = await client.get("/api/v1/users/me", headers=actor.headers)
    assert me.status_code == 200
    assert me.json()["display_name"] == "김학생"


async def test_profile_creation_is_idempotent(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    actor = actors.anonymous_token()
    payload = {"display_name": "강사A", "user_type": "INSTRUCTOR"}

    first = await client.post("/api/v1/users/me", json=payload, headers=actor.headers)
    retry = await client.post(
        "/api/v1/users/me",
        json={"display_name": "다른이름", "user_type": "STUDENT"},
        headers=actor.headers,
    )

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json()["user_type"] == "INSTRUCTOR"  # 기존 값 유지
    assert retry.json()["display_name"] == "강사A"


async def test_concurrent_profile_creation_creates_one_profile(
    client: httpx.AsyncClient,
    actors,
    app,  # type: ignore[no-untyped-def]
) -> None:
    actor = actors.anonymous_token()
    payload = {"display_name": "동시가입", "user_type": "STUDENT"}

    responses = await asyncio.gather(
        *[client.post("/api/v1/users/me", json=payload, headers=actor.headers) for _ in range(5)]
    )

    assert sorted(r.status_code for r in responses) == [200, 200, 200, 200, 201]
    async with app.state.database.engine.connect() as conn:
        count = (await conn.execute(text("SELECT count(*) FROM profiles"))).scalar_one()
    assert count == 1


@pytest.mark.parametrize("user_type", ["ADMIN", "admin", "SUPERUSER"])
async def test_signup_cannot_request_admin(
    client: httpx.AsyncClient,
    actors,
    user_type: str,  # type: ignore[no-untyped-def]
) -> None:
    actor = actors.anonymous_token()

    response = await client.post(
        "/api/v1/users/me",
        json={"display_name": "해커", "user_type": user_type},
        headers=actor.headers,
    )

    assert response.status_code == 422
    assert (await client.get("/api/v1/users/me", headers=actor.headers)).status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"user_type": "ADMIN"},
        {"is_active": False},
        {"id": "00000000-0000-0000-0000-000000000000"},
        {"display_name": "x", "user_type": "INSTRUCTOR"},
    ],
)
async def test_profile_update_cannot_change_protected_fields(
    client: httpx.AsyncClient,
    actors,
    payload: dict,  # type: ignore[no-untyped-def]
) -> None:
    student = await actors.signup("STUDENT", name="학생")

    response = await client.patch("/api/v1/users/me", json=payload, headers=student.headers)

    assert response.status_code == 422
    me = (await client.get("/api/v1/users/me", headers=student.headers)).json()
    assert (me["user_type"], me["is_active"], me["display_name"]) == ("STUDENT", True, "학생")


async def test_profile_update(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    avatar = f"avatars/{student.user_id}/profile.png"

    updated = await client.patch(
        "/api/v1/users/me",
        json={"display_name": "새이름", "avatar_path": avatar},
        headers=student.headers,
    )
    cleared = await client.patch(
        "/api/v1/users/me", json={"avatar_path": None}, headers=student.headers
    )

    assert updated.status_code == 200
    assert (updated.json()["display_name"], updated.json()["avatar_path"]) == ("새이름", avatar)
    assert cleared.json()["avatar_path"] is None
    assert cleared.json()["display_name"] == "새이름"


@pytest.mark.parametrize(
    "avatar",
    [
        "https://evil.example.com/a.png",
        "avatars/../secret.png",
        "/avatars/x.png",
        "avatars/{other}/a.png",
        "avatars/{me}/..",
    ],
)
async def test_avatar_path_must_be_own_storage_path(
    client: httpx.AsyncClient,
    actors,
    avatar: str,  # type: ignore[no-untyped-def]
) -> None:
    student = await actors.signup("STUDENT")
    other = actors.anonymous_token()
    path = avatar.format(me=student.user_id, other=other.user_id)

    response = await client.patch(
        "/api/v1/users/me", json={"avatar_path": path}, headers=student.headers
    )

    assert response.status_code in {403, 422}


async def test_empty_or_blank_update_rejected(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")

    for payload in ({}, {"display_name": "   "}, {"display_name": None}):
        response = await client.patch("/api/v1/users/me", json=payload, headers=student.headers)
        assert response.status_code == 422, payload


async def test_disabled_account_is_blocked(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    async with app.state.database.engine.begin() as conn:
        await conn.execute(
            text("UPDATE profiles SET is_active = false WHERE id = :id"), {"id": student.user_id}
        )

    me = await client.get("/api/v1/users/me", headers=student.headers)
    patch = await client.patch(
        "/api/v1/users/me", json={"display_name": "x"}, headers=student.headers
    )
    academies = await client.get("/api/v1/academies", headers=student.headers)

    assert me.status_code == 200 and me.json()["is_active"] is False
    assert (patch.status_code, patch.json()["error"]["code"]) == (403, "ACCOUNT_DISABLED")
    assert academies.status_code == 403


async def test_endpoints_require_profile(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    no_profile = actors.anonymous_token()

    response = await client.get("/api/v1/academies", headers=no_profile.headers)

    assert (response.status_code, response.json()["error"]["code"]) == (403, "PROFILE_REQUIRED")


async def test_unauthenticated_requests_rejected(client: httpx.AsyncClient) -> None:
    for method, path in [
        ("GET", "/api/v1/users/me"),
        ("PATCH", "/api/v1/users/me"),
        ("GET", "/api/v1/academies"),
        ("POST", "/api/v1/academies"),
        ("GET", "/api/v1/admin/academies"),
    ]:
        response = await client.request(method, path, json={})
        assert response.status_code == 401, (method, path)
