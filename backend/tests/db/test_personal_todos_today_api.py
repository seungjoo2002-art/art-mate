"""개인 할 일 (F-05)과 오늘 할 일 통합 조회. 개인 할 일 비공개 원칙 검증."""

import datetime as dt

import httpx

from app.core import timezone as clock
from tests.db.conftest import World


async def test_personal_todo_crud(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    created = await client.post(
        "/api/v1/personal-todos",
        json={"title": " 크로키 10장 ", "due_date": "2026-11-10", "note": "인체"},
        headers=student.headers,
    )
    assert created.status_code == 201
    todo = created.json()
    assert todo["title"] == "크로키 10장"
    assert todo["is_done"] is False and todo["completed_at"] is None
    path = f"/api/v1/personal-todos/{todo['id']}"

    done = await client.patch(path, json={"is_done": True}, headers=student.headers)
    assert done.json()["is_done"] is True and done.json()["completed_at"] is not None
    reopened = await client.patch(
        path,
        json={"is_done": False, "due_date": None, "title": "크로키 20장"},
        headers=student.headers,
    )
    assert reopened.json()["is_done"] is False
    assert reopened.json()["due_date"] is None
    assert reopened.json()["title"] == "크로키 20장"
    assert reopened.json()["note"] == "인체"

    assert (
        await client.patch(path, json={"title": None}, headers=student.headers)
    ).status_code == 422
    assert (
        await client.patch(path, json={"owner": "x"}, headers=student.headers)
    ).status_code == 422

    await client.post(
        "/api/v1/personal-todos", json={"title": "완료한 일"}, headers=student.headers
    )
    listing = await client.get("/api/v1/personal-todos?is_done=false", headers=student.headers)
    assert listing.json()["total"] == 2

    assert (await client.delete(path, headers=student.headers)).status_code == 204
    assert (await client.delete(path, headers=student.headers)).status_code == 404


async def test_personal_todos_are_private(client: httpx.AsyncClient, world: World, actors) -> None:  # type: ignore[no-untyped-def]
    student = world.students[0]
    todo = (
        await client.post(
            "/api/v1/personal-todos", json={"title": "비밀 메모"}, headers=student.headers
        )
    ).json()
    path = f"/api/v1/personal-todos/{todo['id']}"

    # 다른 학생: 목록에 없고, ID로 접근해도 404
    other = world.students[1]
    assert (await client.get("/api/v1/personal-todos", headers=other.headers)).json()["total"] == 0
    assert (
        await client.patch(path, json={"is_done": True}, headers=other.headers)
    ).status_code == 404
    assert (await client.delete(path, headers=other.headers)).status_code == 404

    # 담당 강사·원장: 개인 할 일 API 자체를 쓸 수 없다 (학생 전용)
    for staff in (world.teacher, world.owner):
        assert (
            await client.get("/api/v1/personal-todos", headers=staff.headers)
        ).status_code == 403
        assert (
            await client.patch(path, json={"is_done": True}, headers=staff.headers)
        ).status_code == 403

    # 강사용 화면(대시보드·과제 상세·출석)에도 개인 할 일이 섞이지 않는다
    dashboard = await client.get(f"{world.base}/dashboard", headers=world.teacher.headers)
    assert "비밀 메모" not in dashboard.text
    assert "personal" not in dashboard.text

    # 시스템 ADMIN도 볼 수 없다
    assert (
        await client.get("/api/v1/personal-todos", headers=world.admin.headers)
    ).status_code == 403
    # 학생 '오늘' 화면도 학생만
    assert (
        await client.get("/api/v1/users/me/today", headers=world.teacher.headers)
    ).status_code == 403


async def test_today_combines_tasks_and_todos(client: httpx.AsyncClient, world: World) -> None:
    student = world.students[0]
    today = clock.local_today()
    now = clock.utc_now()
    _, end_of_today = clock.local_day_bounds(today)

    # 과제: 오늘 마감 / 내일 마감(제외) / 마감 없음
    due_today = (end_of_today - dt.timedelta(minutes=1)).isoformat()
    if dt.datetime.fromisoformat(due_today) <= now:  # 자정 직전 실행 대비
        due_today = (now + dt.timedelta(minutes=30)).isoformat()
    for title, due in (
        ("오늘 마감 과제", due_today),
        ("다음 주 과제", (now + dt.timedelta(days=7)).isoformat()),
        ("마감 없는 과제", None),
    ):
        response = await client.post(
            f"{world.base}/tasks",
            json={"class_id": world.class_id, "title": title, "due_at": due},
            headers=world.teacher.headers,
        )
        assert response.status_code == 201, response.text

    # 개인 할 일: 오늘 / 어제(미완료 → 포함) / 내일(제외) / 날짜 없음
    for title, due in (
        ("오늘 크로키", today),
        ("어제 못한 일", today - dt.timedelta(days=1)),
        ("내일 할 일", today + dt.timedelta(days=1)),
        ("언젠가", None),
    ):
        await client.post(
            "/api/v1/personal-todos",
            json={"title": title, "due_date": due.isoformat() if due else None},
            headers=student.headers,
        )
    await client.post(
        f"{world.class_base}/lesson-topics",
        json={"lesson_date": today.isoformat(), "title": "오늘의 주제: 손 묘사"},
        headers=world.teacher.headers,
    )

    response = await client.get("/api/v1/users/me/today", headers=student.headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["date"] == today.isoformat()
    assert {t["title"] for t in body["academy_tasks"]} == {"오늘 마감 과제", "마감 없는 과제"}
    assert {t["title"] for t in body["personal_todos"]} == {"오늘 크로키", "어제 못한 일", "언젠가"}
    assert [t["title"] for t in body["lesson_topics"]] == ["오늘의 주제: 손 묘사"]
    assert body["summary"] == {
        "academy_task_total": 2,
        "academy_task_done": 0,
        "personal_todo_total": 3,
        "personal_todo_done": 0,
    }

    # 완료하면 오늘 목록에 남고(오늘 완료), 미완료 항목이 먼저 온다
    task_id = next(t["task_id"] for t in body["academy_tasks"] if t["title"] == "마감 없는 과제")
    await client.put(
        f"{world.base}/tasks/{task_id}/completion",
        json={"completed": True},
        headers=student.headers,
    )
    after = (await client.get("/api/v1/users/me/today", headers=student.headers)).json()
    assert after["summary"]["academy_task_done"] == 1
    assert after["academy_tasks"][-1]["title"] == "마감 없는 과제"

    # 학원 필터: 다른 학원 ID면 학원 과제·주제는 비고 개인 할 일은 유지
    other = await client.get(
        "/api/v1/users/me/today",
        params={"academy_id": "00000000-0000-4000-8000-000000000000"},
        headers=student.headers,
    )
    assert other.json()["academy_tasks"] == [] and other.json()["lesson_topics"] == []
    assert len(other.json()["personal_todos"]) == 3
