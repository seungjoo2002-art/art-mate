"""가입 요청·승인·거절, 멤버 관리, 학원 간 데이터 격리, 동시성."""

import asyncio

import httpx
import pytest
from sqlalchemy import text

from app.repositories.memberships import JoinRequestRepository


@pytest.fixture
async def academy(client: httpx.AsyncClient, actors):  # type: ignore[no-untyped-def]
    owner = await actors.signup("INSTRUCTOR", name="원장")
    admin = await actors.admin()
    academy_id = await actors.active_academy(owner, admin)
    return {"id": academy_id, "owner": owner, "admin": admin}


def _base(academy: dict) -> str:
    return f"/api/v1/academies/{academy['id']}"


async def test_student_join_request_approved(client: httpx.AsyncClient, actors, academy) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT", name="김학생")

    requested = await client.post(
        f"{_base(academy)}/join-requests", json={"message": "안녕하세요"}, headers=student.headers
    )
    assert requested.status_code == 201
    assert requested.json()["requested_role"] == "STUDENT"
    assert requested.json()["status"] == "PENDING"

    pending = await client.get(f"{_base(academy)}/join-requests", headers=academy["owner"].headers)
    assert pending.json()["items"][0]["applicant"]["display_name"] == "김학생"
    assert "email" not in pending.json()["items"][0]["applicant"]

    approved = await client.patch(
        f"{_base(academy)}/join-requests/{requested.json()['id']}",
        json={"decision": "APPROVE"},
        headers=academy["owner"].headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    members = await client.get(f"{_base(academy)}/members", headers=academy["owner"].headers)
    roles = {m["display_name"]: m["role"] for m in members.json()["items"]}
    assert roles == {"원장": "OWNER", "김학생": "STUDENT"}

    mine = await client.get("/api/v1/academies?mine=true", headers=student.headers)
    my_requests = await client.get("/api/v1/users/me/join-requests", headers=student.headers)
    assert mine.json()["items"][0]["my_role"] == "STUDENT"
    assert my_requests.json()["items"][0]["status"] == "APPROVED"
    assert my_requests.json()["items"][0]["academy_name"] == "아트메이트 미술학원"


async def test_instructor_joins_as_instructor(client: httpx.AsyncClient, actors, academy) -> None:  # type: ignore[no-untyped-def]
    instructor = await actors.signup("INSTRUCTOR")

    await actors.join(academy["id"], instructor, academy["owner"])

    # 강사의 소속 학원 확인
    mine = await client.get("/api/v1/academies?mine=true", headers=instructor.headers)
    assert [(a["id"], a["my_role"]) for a in mine.json()["items"]] == [
        (academy["id"], "INSTRUCTOR")
    ]


async def test_join_request_rejected_and_can_reapply(
    client: httpx.AsyncClient, actors, academy
) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    request_id = (
        await client.post(f"{_base(academy)}/join-requests", json={}, headers=student.headers)
    ).json()["id"]

    rejected = await client.patch(
        f"{_base(academy)}/join-requests/{request_id}",
        json={"decision": "REJECT", "note": "정원 초과"},
        headers=academy["owner"].headers,
    )
    detail = await client.get(_base(academy), headers=student.headers)
    reapply = await client.post(f"{_base(academy)}/join-requests", json={}, headers=student.headers)

    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["review_note"] == "정원 초과"
    assert detail.json()["my_membership"] is None
    assert reapply.status_code == 201


async def test_duplicate_join_request_and_membership(
    client: httpx.AsyncClient, actors, academy
) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")

    first = await client.post(f"{_base(academy)}/join-requests", json={}, headers=student.headers)
    duplicate = await client.post(
        f"{_base(academy)}/join-requests", json={}, headers=student.headers
    )
    await client.patch(
        f"{_base(academy)}/join-requests/{first.json()['id']}",
        json={"decision": "APPROVE"},
        headers=academy["owner"].headers,
    )
    after_join = await client.post(
        f"{_base(academy)}/join-requests", json={}, headers=student.headers
    )
    owner_request = await client.post(
        f"{_base(academy)}/join-requests", json={}, headers=academy["owner"].headers
    )

    assert duplicate.json()["error"]["code"] == "JOIN_REQUEST_ALREADY_PENDING"
    assert after_join.json()["error"]["code"] == "ALREADY_MEMBER"
    assert owner_request.json()["error"]["code"] == "ALREADY_MEMBER"


async def test_reviewed_request_cannot_be_reviewed_again(
    client: httpx.AsyncClient, actors, academy
) -> None:  # type: ignore[no-untyped-def]
    request_id = await actors.join(academy["id"], await actors.signup("STUDENT"), academy["owner"])

    again = await client.patch(
        f"{_base(academy)}/join-requests/{request_id}",
        json={"decision": "REJECT"},
        headers=academy["owner"].headers,
    )

    assert (again.status_code, again.json()["error"]["code"]) == (
        409,
        "JOIN_REQUEST_ALREADY_REVIEWED",
    )


async def test_admin_account_cannot_join_academy(client: httpx.AsyncClient, academy) -> None:  # type: ignore[no-untyped-def]
    response = await client.post(
        f"{_base(academy)}/join-requests", json={}, headers=academy["admin"].headers
    )

    assert response.status_code == 403


# --------------------------------------------------------------------------- permissions


async def test_role_permissions_within_academy(client: httpx.AsyncClient, actors, academy) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    instructor = await actors.signup("INSTRUCTOR")
    await actors.join(academy["id"], student, academy["owner"])
    await actors.join(academy["id"], instructor, academy["owner"])
    applicant = await actors.signup("STUDENT")
    request_id = (
        await client.post(f"{_base(academy)}/join-requests", json={}, headers=applicant.headers)
    ).json()["id"]

    # 학생: 멤버 목록·가입 요청 관리 불가 (403)
    assert (
        await client.get(f"{_base(academy)}/members", headers=student.headers)
    ).status_code == 403
    assert (
        await client.get(f"{_base(academy)}/join-requests", headers=student.headers)
    ).status_code == 403
    # 강사: 멤버 목록 가능, 가입 승인 불가
    assert (
        await client.get(f"{_base(academy)}/members", headers=instructor.headers)
    ).status_code == 200
    approve_by_instructor = await client.patch(
        f"{_base(academy)}/join-requests/{request_id}",
        json={"decision": "APPROVE"},
        headers=instructor.headers,
    )
    assert approve_by_instructor.status_code == 403
    # 시스템 ADMIN도 학원 소속이 아니면 학원 내부 데이터 접근 불가 (404)
    assert (
        await client.get(f"{_base(academy)}/members", headers=academy["admin"].headers)
    ).status_code == 404


async def test_manager_promotion_and_permissions(
    client: httpx.AsyncClient, actors, academy
) -> None:  # type: ignore[no-untyped-def]
    instructor = await actors.signup("INSTRUCTOR", name="부원장")
    student = await actors.signup("STUDENT", name="학생1")
    await actors.join(academy["id"], instructor, academy["owner"])
    await actors.join(academy["id"], student, academy["owner"])
    members = (
        await client.get(f"{_base(academy)}/members", headers=academy["owner"].headers)
    ).json()["items"]
    ids = {m["display_name"]: m["id"] for m in members}

    # OWNER만 MANAGER 지정 가능, 학생은 MANAGER가 될 수 없음
    by_instructor = await client.patch(
        f"{_base(academy)}/members/{ids['부원장']}",
        json={"role": "MANAGER"},
        headers=instructor.headers,
    )
    student_promote = await client.patch(
        f"{_base(academy)}/members/{ids['학생1']}",
        json={"role": "MANAGER"},
        headers=academy["owner"].headers,
    )
    owner_role = await client.patch(
        f"{_base(academy)}/members/{ids['부원장']}",
        json={"role": "OWNER"},
        headers=academy["owner"].headers,
    )
    promoted = await client.patch(
        f"{_base(academy)}/members/{ids['부원장']}",
        json={"role": "MANAGER"},
        headers=academy["owner"].headers,
    )
    assert by_instructor.status_code == 403
    assert student_promote.json()["error"]["code"] == "MEMBER_ROLE_NOT_CHANGEABLE"
    assert owner_role.status_code == 422
    assert promoted.json()["role"] == "MANAGER"

    # MANAGER: 가입 승인 가능, OWNER 제외 불가
    newcomer = await actors.signup("STUDENT")
    await actors.join(academy["id"], newcomer, instructor)
    remove_owner = await client.delete(
        f"{_base(academy)}/members/{ids['원장']}", headers=instructor.headers
    )
    remove_student = await client.delete(
        f"{_base(academy)}/members/{ids['학생1']}", headers=instructor.headers
    )
    assert remove_owner.status_code == 403
    assert remove_student.status_code == 204

    removed = await client.get(
        f"{_base(academy)}/members?status=REMOVED", headers=academy["owner"].headers
    )
    assert [m["display_name"] for m in removed.json()["items"]] == ["학생1"]


async def test_leave_academy_and_rejoin(client: httpx.AsyncClient, actors, academy) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    await actors.join(academy["id"], student, academy["owner"])

    left = await client.delete(f"{_base(academy)}/members/me", headers=student.headers)
    left_again = await client.delete(f"{_base(academy)}/members/me", headers=student.headers)
    owner_leave = await client.delete(
        f"{_base(academy)}/members/me", headers=academy["owner"].headers
    )

    assert left.status_code == 204
    assert left_again.status_code == 404
    assert (owner_leave.status_code, owner_leave.json()["error"]["code"]) == (
        409,
        "OWNER_CANNOT_LEAVE",
    )
    assert (await client.get("/api/v1/academies?mine=true", headers=student.headers)).json()[
        "total"
    ] == 0

    # 재가입: 같은 소속 행이 다시 ACTIVE가 된다
    await actors.join(academy["id"], student, academy["owner"])
    detail = await client.get(_base(academy), headers=student.headers)
    assert detail.json()["my_membership"]["status"] == "ACTIVE"


async def test_cross_academy_isolation(client: httpx.AsyncClient, actors, academy) -> None:  # type: ignore[no-untyped-def]
    other_owner = await actors.signup("INSTRUCTOR")
    other_id = await actors.active_academy(other_owner, academy["admin"], name="다른학원")
    student = await actors.signup("STUDENT")
    await actors.join(academy["id"], student, academy["owner"])
    request_id = (
        await client.post(
            f"{_base(academy)}/join-requests", json={}, headers=(await actors.signup()).headers
        )
    ).json()["id"]
    member_id = (
        await client.get(f"{_base(academy)}/members", headers=academy["owner"].headers)
    ).json()["items"][0]["id"]

    other = f"/api/v1/academies/{other_id}"
    mine = f"/api/v1/academies/{academy['id']}"
    h = other_owner.headers
    # 다른 학원 OWNER는 이 학원의 멤버·요청을 보거나 바꿀 수 없다 (404)
    assert (await client.get(f"{mine}/members", headers=h)).status_code == 404
    assert (await client.get(f"{mine}/join-requests", headers=h)).status_code == 404
    review = await client.patch(
        f"{mine}/join-requests/{request_id}", json={"decision": "APPROVE"}, headers=h
    )
    assert review.status_code == 404
    assert (await client.delete(f"{mine}/members/{member_id}", headers=h)).status_code == 404
    # 자기 학원 경로로 남의 학원 요청·멤버 ID를 넣어도 찾을 수 없다
    swapped = await client.patch(
        f"{other}/join-requests/{request_id}", json={"decision": "APPROVE"}, headers=h
    )
    assert swapped.status_code == 404
    assert (await client.delete(f"{other}/members/{member_id}", headers=h)).status_code == 404


async def test_user_id_in_body_is_ignored(client: httpx.AsyncClient, actors, academy) -> None:  # type: ignore[no-untyped-def]
    victim = await actors.signup("STUDENT")
    attacker = await actors.signup("STUDENT")

    response = await client.post(
        f"{_base(academy)}/join-requests",
        json={"user_id": str(victim.user_id)},
        headers=attacker.headers,
    )

    assert response.status_code == 422  # 알 수 없는 필드 거부, 사용자는 토큰으로만 식별


# --------------------------------------------------------------------------- concurrency


async def test_concurrent_join_requests_create_one(
    client: httpx.AsyncClient,
    actors,
    academy,
    app,  # type: ignore[no-untyped-def]
) -> None:
    student = await actors.signup("STUDENT")

    responses = await asyncio.gather(
        *[
            client.post(f"{_base(academy)}/join-requests", json={}, headers=student.headers)
            for _ in range(5)
        ]
    )

    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409, 409, 409, 409]
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} == {
        "JOIN_REQUEST_ALREADY_PENDING"
    }
    async with app.state.database.engine.connect() as conn:
        count = (
            await conn.execute(text("SELECT count(*) FROM academy_join_requests"))
        ).scalar_one()
    assert count == 1


async def test_concurrent_reviews_process_once(
    client: httpx.AsyncClient,
    actors,  # type: ignore[no-untyped-def]
    academy,  # type: ignore[no-untyped-def]
    app,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """두 관리자가 같은 요청을 동시에 처리: 행 잠금으로 한 번만 처리되어야 한다.

    요청 행을 읽은 직후 지연을 넣어 두 트랜잭션이 반드시 겹치게 만든다.
    (잠금이 없으면 둘 다 PENDING을 읽고 둘 다 200이 되어 실패한다)
    """
    original = JoinRequestRepository.get_in_academy_for_update

    async def slow_get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = await original(self, *args, **kwargs)
        await asyncio.sleep(0.3)
        return result

    manager = await actors.signup("INSTRUCTOR")
    await actors.join(academy["id"], manager, academy["owner"])
    manager_member_id = next(
        m["id"]
        for m in (
            await client.get(f"{_base(academy)}/members", headers=academy["owner"].headers)
        ).json()["items"]
        if m["user_id"] == str(manager.user_id)
    )
    await client.patch(
        f"{_base(academy)}/members/{manager_member_id}",
        json={"role": "MANAGER"},
        headers=academy["owner"].headers,
    )
    student = await actors.signup("STUDENT")
    request_id = (
        await client.post(f"{_base(academy)}/join-requests", json={}, headers=student.headers)
    ).json()["id"]

    monkeypatch.setattr(JoinRequestRepository, "get_in_academy_for_update", slow_get)
    responses = await asyncio.gather(
        client.patch(
            f"{_base(academy)}/join-requests/{request_id}",
            json={"decision": "APPROVE"},
            headers=academy["owner"].headers,
        ),
        client.patch(
            f"{_base(academy)}/join-requests/{request_id}",
            json={"decision": "REJECT"},
            headers=manager.headers,
        ),
    )

    assert sorted(r.status_code for r in responses) == [200, 409]
    async with app.state.database.engine.connect() as conn:
        memberships = (
            await conn.execute(
                text("SELECT count(*) FROM academy_memberships WHERE user_id = :id"),
                {"id": student.user_id},
            )
        ).scalar_one()
    winner = next(r for r in responses if r.status_code == 200).json()["status"]
    assert memberships == (1 if winner == "APPROVED" else 0)
