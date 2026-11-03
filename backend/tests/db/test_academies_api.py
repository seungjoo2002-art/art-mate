"""학원 등록·심사·조회와 역할별 권한."""

import uuid

import httpx


async def test_only_instructor_can_apply_for_academy(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    admin = await actors.admin()
    instructor = await actors.signup("INSTRUCTOR")

    by_student = await client.post(
        "/api/v1/academies", json={"name": "학생학원"}, headers=student.headers
    )
    by_admin = await client.post(
        "/api/v1/academies", json={"name": "관리자학원"}, headers=admin.headers
    )
    by_instructor = await client.post(
        "/api/v1/academies",
        json={"name": "  아트메이트 미술학원 ", "description": "예고 입시 전문"},
        headers=instructor.headers,
    )

    assert by_student.status_code == 403
    assert by_admin.status_code == 403
    assert by_instructor.status_code == 201
    body = by_instructor.json()
    assert body["name"] == "아트메이트 미술학원"
    assert body["status"] == "PENDING_APPROVAL"
    assert body["my_membership"]["role"] == "OWNER"


async def test_academy_approval_flow(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    owner = await actors.signup("INSTRUCTOR")
    admin = await actors.admin()
    student = await actors.signup("STUDENT")
    created = (
        await client.post("/api/v1/academies", json={"name": "승인대기학원"}, headers=owner.headers)
    ).json()

    # 승인 전: 디렉터리에 없고, 비소속자는 상세 조회 불가 (404)
    directory = await client.get("/api/v1/academies", headers=student.headers)
    hidden = await client.get(f"/api/v1/academies/{created['id']}", headers=student.headers)
    owner_view = await client.get(f"/api/v1/academies/{created['id']}", headers=owner.headers)
    mine = await client.get("/api/v1/academies?mine=true", headers=owner.headers)
    assert directory.json()["total"] == 0
    assert hidden.status_code == 404
    assert owner_view.status_code == 200
    assert mine.json()["items"][0]["my_role"] == "OWNER"

    pending = await client.get("/api/v1/admin/academies", headers=admin.headers)
    assert [a["id"] for a in pending.json()["items"]] == [created["id"]]

    approved = await client.patch(
        f"/api/v1/admin/academies/{created['id']}",
        json={"decision": "APPROVE", "note": "확인 완료"},
        headers=admin.headers,
    )
    again = await client.patch(
        f"/api/v1/admin/academies/{created['id']}",
        json={"decision": "REJECT"},
        headers=admin.headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "ACTIVE"
    assert approved.json()["reviewed_by"] == str(admin.user_id)
    assert (again.status_code, again.json()["error"]["code"]) == (409, "ACADEMY_ALREADY_REVIEWED")

    directory = await client.get("/api/v1/academies?q=승인", headers=student.headers)
    assert [a["name"] for a in directory.json()["items"]] == ["승인대기학원"]
    detail = await client.get(f"/api/v1/academies/{created['id']}", headers=student.headers)
    assert detail.status_code == 200 and detail.json()["my_membership"] is None


async def test_rejected_academy_not_listed(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    owner = await actors.signup("INSTRUCTOR")
    admin = await actors.admin()
    academy_id = (
        await client.post("/api/v1/academies", json={"name": "반려학원"}, headers=owner.headers)
    ).json()["id"]

    rejected = await client.patch(
        f"/api/v1/admin/academies/{academy_id}",
        json={"decision": "REJECT", "note": "정보 부족"},
        headers=admin.headers,
    )
    join = await client.post(
        f"/api/v1/academies/{academy_id}/join-requests",
        json={},
        headers=(await actors.signup("STUDENT")).headers,
    )

    assert rejected.json()["status"] == "REJECTED"
    assert join.status_code == 404


async def test_non_admin_cannot_use_admin_api(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    owner = await actors.signup("INSTRUCTOR")
    academy_id = (
        await client.post("/api/v1/academies", json={"name": "셀프승인"}, headers=owner.headers)
    ).json()["id"]

    listing = await client.get("/api/v1/admin/academies", headers=owner.headers)
    self_approve = await client.patch(
        f"/api/v1/admin/academies/{academy_id}",
        json={"decision": "APPROVE"},
        headers=owner.headers,
    )

    assert listing.status_code == 403
    assert self_approve.status_code == 403


async def test_application_limit(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    owner = await actors.signup("INSTRUCTOR")
    for i in range(3):
        response = await client.post(
            "/api/v1/academies", json={"name": f"학원{i}"}, headers=owner.headers
        )
        assert response.status_code == 201

    fourth = await client.post("/api/v1/academies", json={"name": "학원4"}, headers=owner.headers)

    assert (fourth.status_code, fourth.json()["error"]["code"]) == (
        409,
        "ACADEMY_APPLICATION_LIMIT",
    )


async def test_academy_input_validation(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    owner = await actors.signup("INSTRUCTOR")

    for payload in ({}, {"name": "a"}, {"name": "x" * 101}, {"name": "ok학원", "status": "ACTIVE"}):
        response = await client.post("/api/v1/academies", json=payload, headers=owner.headers)
        assert response.status_code == 422, payload


async def test_pagination(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    admin = await actors.admin()
    student = await actors.signup("STUDENT")
    for i in range(5):
        await actors.active_academy(await actors.signup("INSTRUCTOR"), admin, name=f"학원-{i}")

    page1 = await client.get("/api/v1/academies?limit=2&offset=0", headers=student.headers)
    page3 = await client.get("/api/v1/academies?limit=2&offset=4", headers=student.headers)
    too_big = await client.get("/api/v1/academies?limit=101", headers=student.headers)

    assert (page1.json()["total"], len(page1.json()["items"])) == (5, 2)
    assert [a["name"] for a in page3.json()["items"]] == ["학원-4"]
    assert too_big.status_code == 422


async def test_unknown_academy_returns_404(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")

    response = await client.get(f"/api/v1/academies/{uuid.uuid4()}", headers=student.headers)

    assert response.status_code == 404
