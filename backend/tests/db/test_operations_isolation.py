"""학원 간 데이터 격리 (v0.3 리소스 전체) + DB 복합 FK의 교차 학원 연결 차단."""

import uuid

import asyncpg
import httpx
import pytest

from tests.db.conftest import World
from tests.db.test_migrations import _asyncpg_dsn


@pytest.fixture
async def two_worlds(build_world) -> tuple[World, World]:  # type: ignore[no-untyped-def]
    first = await build_world("가나 미술학원")
    second = await build_world("다라 미술학원", admin=first.admin)
    return first, second


async def _seed(client: httpx.AsyncClient, w: World) -> dict[str, str]:
    schedule = await client.post(
        f"{w.class_base}/schedules",
        json={
            "weekday": 1,
            "start_time": "16:00",
            "end_time": "18:00",
            "effective_from": "2026-11-09",
        },
        headers=w.teacher.headers,
    )
    exception = await client.post(
        f"{w.class_base}/schedule-exceptions",
        json={
            "kind": "MAKEUP",
            "session_date": "2026-11-14",
            "start_time": "10:00",
            "end_time": "11:00",
        },
        headers=w.teacher.headers,
    )
    topic = await client.post(
        f"{w.class_base}/lesson-topics",
        json={"lesson_date": "2026-12-01", "title": "주제"},
        headers=w.teacher.headers,
    )
    task = await client.post(
        f"{w.base}/tasks", json={"class_id": w.class_id, "title": "과제"}, headers=w.teacher.headers
    )
    record = await client.post(f"{w.base}/attendance/check-in", headers=w.students[0].headers)
    for response in (schedule, exception, topic, task, record):
        assert response.status_code == 201, response.text
    return {
        "schedule": schedule.json()["id"],
        "exception": exception.json()["id"],
        "topic": topic.json()["id"],
        "task": task.json()["id"],
        "record": record.json()["id"],
    }


async def test_cross_academy_access_is_blocked(
    client: httpx.AsyncClient, two_worlds: tuple[World, World]
) -> None:
    a, b = two_worlds
    ids = await _seed(client, a)
    await _seed(client, b)

    # B 학원 원장이 A 학원 경로로 접근 → 비소속 404
    outsider = b.owner.headers
    for method, path in [
        ("GET", f"{a.base}/classes"),
        ("GET", a.class_base),
        ("GET", f"{a.base}/schedules"),
        ("GET", f"{a.base}/attendance"),
        ("GET", f"{a.base}/tasks"),
        ("GET", f"{a.base}/dashboard"),
        ("PATCH", f"{a.base}/attendance/records/{ids['record']}"),
        ("DELETE", f"{a.base}/tasks/{ids['task']}"),
    ]:
        response = await client.request(method, path, headers=outsider, json={"status": "ABSENT"})
        assert response.status_code == 404, (method, path, response.status_code)

    # B 학원 경로에 A 학원 리소스 ID → 404 (ID만으로는 접근 불가)
    for method, path, body in [
        ("GET", f"{b.base}/classes/{a.class_id}", None),
        ("PATCH", f"{b.base}/classes/{a.class_id}", {"name": "탈취"}),
        ("PATCH", f"{b.base}/classes/{a.class_id}/schedules/{ids['schedule']}", {"weekday": 2}),
        ("DELETE", f"{b.class_base}/schedules/{ids['schedule']}", None),
        ("DELETE", f"{b.class_base}/schedule-exceptions/{ids['exception']}", None),
        ("PATCH", f"{b.class_base}/lesson-topics/{ids['topic']}", {"title": "x"}),
        ("GET", f"{b.base}/tasks/{ids['task']}", None),
        ("PATCH", f"{b.base}/tasks/{ids['task']}", {"title": "x"}),
        ("PATCH", f"{b.base}/attendance/records/{ids['record']}", {"status": "ABSENT"}),
        ("GET", f"{b.base}/attendance/records/{ids['record']}/history", None),
    ]:
        response = await client.request(method, path, headers=b.owner.headers, json=body)
        assert response.status_code == 404, (method, path, response.status_code)

    # B 학원 학생이 A 학원 과제 완료 체크 → 404
    complete = await client.put(
        f"{b.base}/tasks/{ids['task']}/completion",
        json={"completed": True},
        headers=b.students[0].headers,
    )
    assert complete.status_code == 404

    # A 학원 학생 membership_id를 B 학원 작업에 사용 → 거부
    cross_member = await client.post(
        f"{b.class_base}/members",
        json={"membership_id": a.students[2].membership_id},
        headers=b.owner.headers,
    )
    assert cross_member.status_code == 422
    cross_attendance = await client.post(
        f"{b.base}/attendance/records",
        json={
            "student_membership_id": a.students[0].membership_id,
            "attendance_date": "2026-11-03",
            "status": "ABSENT",
        },
        headers=b.owner.headers,
    )
    assert cross_attendance.status_code == 404
    cross_task = await client.post(
        f"{b.base}/tasks",
        json={
            "class_id": b.class_id,
            "title": "x",
            "target_type": "STUDENTS",
            "student_membership_ids": [a.students[0].membership_id],
        },
        headers=b.owner.headers,
    )
    assert cross_task.status_code == 422
    cross_class_task = await client.post(
        f"{b.base}/tasks", json={"class_id": a.class_id, "title": "x"}, headers=b.owner.headers
    )
    assert cross_class_task.status_code == 404

    # 각 학원 데이터 수는 자기 것만
    a_tasks = await client.get(f"{a.base}/tasks", headers=a.owner.headers)
    assert a_tasks.json()["total"] == 1
    a_attendance = await client.get(f"{a.base}/attendance/records", headers=a.owner.headers)
    assert {r["academy_id"] for r in a_attendance.json()["items"]} == {a.academy_id}


async def test_database_rejects_cross_academy_links(
    client: httpx.AsyncClient, two_worlds: tuple[World, World], migrated_database: str
) -> None:
    """API를 우회해도 복합 FK (academy_id, *_id)가 다른 학원 행 연결을 거부한다."""
    a, b = two_worlds
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    try:
        statements = [
            # A 학원 반에 B 학원 학생 배정
            (
                "INSERT INTO class_memberships (id, academy_id, class_id, membership_id, role,"
                " status, joined_at) VALUES ($1, $2, $3, $4, 'STUDENT', 'ACTIVE', now())",
                [
                    uuid.uuid4(),
                    uuid.UUID(a.academy_id),
                    uuid.UUID(a.class_id),
                    uuid.UUID(b.students[0].membership_id),
                ],
            ),
            # A 학원 출석에 B 학원 학생
            (
                "INSERT INTO attendance_records (id, academy_id, student_membership_id,"
                " attendance_date, status, source)"
                " VALUES ($1, $2, $3, '2026-11-03', 'ABSENT', 'INSTRUCTOR')",
                [uuid.uuid4(), uuid.UUID(a.academy_id), uuid.UUID(b.students[0].membership_id)],
            ),
            # A 학원 과제를 B 학원 반에
            (
                "INSERT INTO tasks (id, academy_id, class_id, title, target_type, status)"
                " VALUES ($1, $2, $3, 'x', 'CLASS', 'ACTIVE')",
                [uuid.uuid4(), uuid.UUID(a.academy_id), uuid.UUID(b.class_id)],
            ),
        ]
        for sql, args in statements:
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(sql, *args)
    finally:
        await conn.close()
