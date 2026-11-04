"""강사 수업 현황 대시보드 데이터 정확성 (F-09 v0.3 범위)."""

import datetime as dt

import httpx

from app.core import timezone as clock
from tests.db.conftest import World


async def test_dashboard_numbers(client: httpx.AsyncClient, world: World) -> None:
    today = clock.local_today()
    s1, s2, s3 = world.students

    # 두 번째 반: 원장 담당, 학생3 + 학생1
    second = await client.post(
        f"{world.base}/classes", json={"name": "기초 B반"}, headers=world.owner.headers
    )
    second_id = second.json()["id"]
    for member in (world.owner, s3, s1):
        await client.post(
            f"{world.base}/classes/{second_id}/members",
            json={"membership_id": member.membership_id},
            headers=world.owner.headers,
        )

    # 오늘 정규 수업 (A반) + 오늘 보강 (A반) + 다른 요일 수업 (A반, 제외)
    await client.post(
        f"{world.class_base}/schedules",
        json={
            "weekday": today.weekday(),
            "start_time": "16:00",
            "end_time": "18:00",
            "effective_from": (today - dt.timedelta(days=14)).isoformat(),
        },
        headers=world.teacher.headers,
    )
    await client.post(
        f"{world.class_base}/schedules",
        json={
            "weekday": (today.weekday() + 1) % 7,
            "start_time": "16:00",
            "end_time": "18:00",
            "effective_from": (today - dt.timedelta(days=14)).isoformat(),
        },
        headers=world.teacher.headers,
    )
    await client.post(
        f"{world.class_base}/schedule-exceptions",
        json={
            "kind": "MAKEUP",
            "session_date": today.isoformat(),
            "start_time": "10:00",
            "end_time": "11:00",
        },
        headers=world.teacher.headers,
    )

    # 출석: 학생1 체크인, 학생2 강사가 ABSENT 기록
    await client.post(f"{world.base}/attendance/check-in", headers=s1.headers)
    await client.post(
        f"{world.base}/attendance/records",
        json={
            "student_membership_id": s2.membership_id,
            "attendance_date": today.isoformat(),
            "status": "ABSENT",
        },
        headers=world.teacher.headers,
    )

    # 과제: A반 전체 2건 (학생1이 1건 완료), B반 1건
    due = (clock.utc_now() + dt.timedelta(days=2)).isoformat()
    task_ids = []
    for title in ("과제1", "과제2"):
        created = await client.post(
            f"{world.base}/tasks",
            json={"class_id": world.class_id, "title": title, "due_at": due},
            headers=world.teacher.headers,
        )
        task_ids.append(created.json()["id"])
    await client.post(
        f"{world.base}/tasks",
        json={"class_id": second_id, "title": "B반 과제"},
        headers=world.owner.headers,
    )
    await client.put(
        f"{world.base}/tasks/{task_ids[0]}/completion", json={"completed": True}, headers=s1.headers
    )
    # 취소된 과제는 집계에서 제외
    cancelled = await client.post(
        f"{world.base}/tasks",
        json={"class_id": world.class_id, "title": "취소될 과제"},
        headers=world.teacher.headers,
    )
    await client.delete(
        f"{world.base}/tasks/{cancelled.json()['id']}", headers=world.teacher.headers
    )

    # ---------------------------------------------------------------- 담당 강사 (A반만)
    response = await client.get(f"{world.base}/dashboard", headers=world.teacher.headers)
    assert response.status_code == 200, response.text
    board = response.json()
    assert board["date"] == today.isoformat()
    assert board["scope"] == "mine"  # 강사는 all을 요청해도 담당 반만
    assert [c["name"] for c in board["classes"]] == ["입시 A반"]
    a_class = board["classes"][0]
    assert a_class["student_count"] == 2
    assert [s["kind"] for s in a_class["today_sessions"]] == ["MAKEUP", "REGULAR"]
    assert a_class["attendance"] == {
        "present": 1,
        "late": 0,
        "absent": 1,
        "excused": 0,
        "not_recorded": 0,
    }
    # 과제1(학생2 미완료) + 과제2(학생1·2 미완료) = 3
    assert a_class["open_assignment_count"] == 3

    students = {s["student"]["display_name"].rsplit("-", 1)[1]: s for s in board["students"]}
    assert set(students) == {"학생1", "학생2"}
    assert students["학생1"]["attendance_status"] == "PRESENT"
    assert students["학생1"]["checked_in_at"] is not None
    assert students["학생1"]["open_assignment_count"] == 1
    assert students["학생2"]["attendance_status"] == "ABSENT"
    assert students["학생2"]["open_assignment_count"] == 2

    assert [t["title"] for t in board["tasks_distributed_today"]] == ["과제2", "과제1"]
    first = next(t for t in board["tasks_distributed_today"] if t["title"] == "과제1")
    assert (first["assigned_count"], first["completed_count"]) == (2, 1)
    assert board["totals"] == {
        "class_count": 1,
        "student_count": 2,
        "session_count": 2,
        "open_assignment_count": 3,
        "tasks_distributed_today": 2,
        "attendance": {"present": 1, "late": 0, "absent": 1, "excused": 0, "not_recorded": 0},
    }
    assert [o["starts_at"][11:16] for o in board["today_schedule"]] == ["10:00", "16:00"]

    # ---------------------------------------------------------------- 원장 (학원 전체)
    owner_board = (await client.get(f"{world.base}/dashboard", headers=world.owner.headers)).json()
    assert owner_board["scope"] == "all"
    assert [c["name"] for c in owner_board["classes"]] == ["기초 B반", "입시 A반"]
    b_class = owner_board["classes"][0]
    assert b_class["student_count"] == 2
    assert b_class["attendance"]["present"] == 1 and b_class["attendance"]["not_recorded"] == 1
    assert b_class["open_assignment_count"] == 2
    assert owner_board["totals"]["student_count"] == 3  # 학생1은 두 반에 속하지만 1명
    assert owner_board["totals"]["open_assignment_count"] == 5
    assert owner_board["totals"]["tasks_distributed_today"] == 3
    student1 = next(
        s for s in owner_board["students"] if s["student"]["membership_id"] == s1.membership_id
    )
    assert sorted(student1["class_ids"]) == sorted([world.class_id, second_id])

    owner_mine = (
        await client.get(f"{world.base}/dashboard?scope=mine", headers=world.owner.headers)
    ).json()
    assert [c["name"] for c in owner_mine["classes"]] == ["기초 B반"]

    # 다른 날짜: 출석·배포 과제 없음 (미완료 과제 수는 날짜와 무관)
    other_day = (today + dt.timedelta(days=1)).isoformat()
    tomorrow = (
        await client.get(f"{world.base}/dashboard?date={other_day}", headers=world.teacher.headers)
    ).json()
    assert tomorrow["totals"]["attendance"]["not_recorded"] == 2
    assert tomorrow["tasks_distributed_today"] == []

    # 비담당 강사: 빈 대시보드, 학생: 403
    empty = (
        await client.get(f"{world.base}/dashboard", headers=world.other_teacher.headers)
    ).json()
    assert empty["classes"] == [] and empty["totals"]["student_count"] == 0
    assert (await client.get(f"{world.base}/dashboard", headers=s1.headers)).status_code == 403


async def test_dashboard_excludes_students_who_left(
    client: httpx.AsyncClient, world: World
) -> None:
    await client.post(
        f"{world.base}/tasks",
        json={"class_id": world.class_id, "title": "과제"},
        headers=world.teacher.headers,
    )
    await client.delete(f"{world.base}/members/me", headers=world.students[1].headers)
    board = (await client.get(f"{world.base}/dashboard", headers=world.teacher.headers)).json()
    assert board["totals"]["student_count"] == 1
    assert board["totals"]["open_assignment_count"] == 1
