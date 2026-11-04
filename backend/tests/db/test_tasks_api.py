"""수업 주제·과제 (F-02): 주제 공지, 반 전체/특정 학생 배포, 수정·취소, 완료 체크."""

import asyncio
import datetime as dt

import httpx

from app.core import timezone as clock
from tests.db.conftest import World


def _future(days: int = 3) -> str:
    return (clock.utc_now() + dt.timedelta(days=days)).astimezone(clock.ACADEMY_TZ).isoformat()


async def _task(client: httpx.AsyncClient, world: World, actor=None, **overrides):  # type: ignore[no-untyped-def]
    body = {"class_id": world.class_id, "title": "석고 소묘 1장", "due_at": _future()} | overrides
    return await client.post(
        f"{world.base}/tasks", json=body, headers=(actor or world.teacher).headers
    )


# ----------------------------------------------------------------------------- lesson topics


async def test_lesson_topics_and_next_notice(client: httpx.AsyncClient, world: World) -> None:
    today = clock.local_today()
    topics = f"{world.class_base}/lesson-topics"
    past = await client.post(
        topics,
        json={"lesson_date": (today - dt.timedelta(days=7)).isoformat(), "title": "지난 주제"},
        headers=world.teacher.headers,
    )
    upcoming = await client.post(
        topics,
        json={
            "lesson_date": (today + dt.timedelta(days=2)).isoformat(),
            "title": "다음 수업: 정물 수채화",
            "description": "물통·팔레트 준비",
        },
        headers=world.teacher.headers,
    )
    assert past.status_code == 201 and upcoming.status_code == 201

    duplicate = await client.post(
        topics,
        json={"lesson_date": (today + dt.timedelta(days=2)).isoformat(), "title": "중복"},
        headers=world.owner.headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "LESSON_TOPIC_EXISTS"

    # 학생은 기본적으로 다음 수업 주제(오늘 이후)를 본다
    notice = await client.get(topics, headers=world.students[0].headers)
    assert [t["title"] for t in notice.json()["items"]] == ["다음 수업: 정물 수채화"]
    history = await client.get(
        topics,
        params={"from": (today - dt.timedelta(days=30)).isoformat()},
        headers=world.students[0].headers,
    )
    assert history.json()["total"] == 2

    # 반 미배정 학생은 404, 비담당 강사는 조회만 가능
    assert (await client.get(topics, headers=world.students[2].headers)).status_code == 404
    assert (await client.get(topics, headers=world.other_teacher.headers)).status_code == 200
    by_other = await client.post(
        topics,
        json={"lesson_date": today.isoformat(), "title": "x"},
        headers=world.other_teacher.headers,
    )
    assert by_other.status_code == 403

    path = f"{topics}/{upcoming.json()['id']}"
    edited = await client.patch(path, json={"description": None}, headers=world.teacher.headers)
    assert edited.status_code == 200 and edited.json()["description"] is None
    assert (await client.delete(path, headers=world.teacher.headers)).status_code == 204
    assert (await client.get(topics, headers=world.students[0].headers)).json()["total"] == 0


# ----------------------------------------------------------------------------- tasks


async def test_distribute_to_whole_class(client: httpx.AsyncClient, world: World) -> None:
    created = await _task(client, world, description="4절, 2시간")
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["target_type"] == "CLASS"
    assert task["assigned_count"] == 2 and task["completed_count"] == 0
    assert {a["student"]["membership_id"] for a in task["assignments"]} == {
        world.students[0].membership_id,
        world.students[1].membership_id,
    }

    mine = await client.get(f"{world.base}/tasks/me", headers=world.students[0].headers)
    assert [t["task_id"] for t in mine.json()["items"]] == [task["id"]]
    assert mine.json()["items"][0]["class_name"] == "입시 A반"
    assert mine.json()["items"][0]["completed"] is False
    # 반 미배정 학생은 받지 않는다
    none = await client.get(f"{world.base}/tasks/me", headers=world.students[2].headers)
    assert none.json()["items"] == []


async def test_distribute_to_specific_students_and_validation(
    client: httpx.AsyncClient, world: World
) -> None:
    created = await _task(
        client,
        world,
        target_type="STUDENTS",
        student_membership_ids=[world.students[1].membership_id],
    )
    assert created.status_code == 201
    assert [a["student"]["membership_id"] for a in created.json()["assignments"]] == [
        world.students[1].membership_id
    ]
    first = await client.get(f"{world.base}/tasks/me", headers=world.students[0].headers)
    assert first.json()["items"] == []

    not_in_class = await _task(
        client,
        world,
        target_type="STUDENTS",
        student_membership_ids=[world.students[2].membership_id],
    )
    assert not_in_class.status_code == 422
    assert not_in_class.json()["error"]["code"] == "INVALID_TASK_TARGET"

    missing_targets = await _task(client, world, target_type="STUDENTS")
    assert missing_targets.status_code == 422
    past_due = await _task(client, world, due_at="2020-01-01T00:00:00+09:00")
    assert past_due.status_code == 422
    naive_due = await _task(client, world, due_at="2030-01-01T00:00:00")
    assert naive_due.status_code == 422
    blank = await _task(client, world, title="   ")
    assert blank.status_code == 422

    # 비담당 강사·학생은 배포 불가
    assert (await _task(client, world, world.other_teacher)).status_code == 403
    assert (await _task(client, world, world.students[0])).status_code == 403


async def test_task_update_cancel_and_completion(client: httpx.AsyncClient, world: World) -> None:
    task = (await _task(client, world)).json()
    path = f"{world.base}/tasks/{task['id']}"
    student = world.students[0]

    edited = await client.patch(
        path, json={"title": "석고 소묘 2장", "due_at": None}, headers=world.teacher.headers
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "석고 소묘 2장" and edited.json()["due_at"] is None

    done = await client.put(f"{path}/completion", json={"completed": True}, headers=student.headers)
    assert done.status_code == 200, done.text
    assert done.json()["completed"] is True
    completed_at = done.json()["completed_at"]
    # 다시 완료해도 처음 완료 시각 유지
    again = await client.put(
        f"{path}/completion", json={"completed": True}, headers=student.headers
    )
    assert again.json()["completed_at"] == completed_at

    detail = await client.get(path, headers=world.teacher.headers)
    assert detail.json()["completed_count"] == 1
    status_by_student = {
        a["student"]["membership_id"]: a["completed"] for a in detail.json()["assignments"]
    }
    assert status_by_student == {
        world.students[0].membership_id: True,
        world.students[1].membership_id: False,
    }

    undone = await client.put(
        f"{path}/completion", json={"completed": False}, headers=student.headers
    )
    assert undone.json()["completed"] is False

    # 배정되지 않은 학생은 완료 체크 불가 (404)
    stranger = await client.put(
        f"{path}/completion", json={"completed": True}, headers=world.students[2].headers
    )
    assert stranger.status_code == 404

    # 취소: 학생 화면에서 사라지고 완료·수정 불가
    assert (await client.delete(path, headers=world.teacher.headers)).status_code == 204
    assert (await client.delete(path, headers=world.teacher.headers)).status_code == 204
    gone = await client.get(f"{world.base}/tasks/me", headers=student.headers)
    assert gone.json()["items"] == []
    blocked = await client.put(
        f"{path}/completion", json={"completed": True}, headers=student.headers
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "TASK_CANCELLED"
    locked = await client.patch(path, json={"title": "x"}, headers=world.teacher.headers)
    assert locked.status_code == 409

    cancelled = await client.get(
        f"{world.base}/tasks?status=CANCELLED", headers=world.teacher.headers
    )
    assert [t["id"] for t in cancelled.json()["items"]] == [task["id"]]


async def test_task_listing_scope(client: httpx.AsyncClient, world: World) -> None:
    await _task(client, world)
    teacher = await client.get(f"{world.base}/tasks", headers=world.teacher.headers)
    owner = await client.get(f"{world.base}/tasks", headers=world.owner.headers)
    other = await client.get(f"{world.base}/tasks", headers=world.other_teacher.headers)
    assert teacher.json()["total"] == 1 and owner.json()["total"] == 1
    assert other.json()["total"] == 0
    today = await client.get(
        f"{world.base}/tasks?created_on={clock.local_today().isoformat()}",
        headers=world.teacher.headers,
    )
    assert today.json()["total"] == 1
    assert (
        await client.get(f"{world.base}/tasks", headers=world.students[0].headers)
    ).status_code == 403
    detail = await client.get(
        f"{world.base}/tasks/{teacher.json()['items'][0]['id']}",
        headers=world.other_teacher.headers,
    )
    assert detail.status_code == 403


async def test_concurrent_completion_is_consistent(client: httpx.AsyncClient, world: World) -> None:
    task = (await _task(client, world)).json()
    path = f"{world.base}/tasks/{task['id']}/completion"
    responses = await asyncio.gather(
        *[
            client.put(path, json={"completed": True}, headers=world.students[0].headers)
            for _ in range(6)
        ]
    )
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["completed_at"] for r in responses}) == 1
    detail = await client.get(f"{world.base}/tasks/{task['id']}", headers=world.teacher.headers)
    assert detail.json()["completed_count"] == 1
