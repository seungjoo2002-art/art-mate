"""반 생성·배정, 담당 강사, 정규 수업·휴강·변경·보강, 일정 조회 (F-04)."""

import asyncio
import datetime as dt

import httpx

from tests.db.conftest import World

# 2026-11-09 = 월요일
MON = dt.date(2026, 11, 9)


async def _schedule(client: httpx.AsyncClient, world: World, actor=None, **overrides):  # type: ignore[no-untyped-def]
    body = {
        "weekday": 1,  # 화요일
        "start_time": "16:00",
        "end_time": "18:00",
        "effective_from": MON.isoformat(),
        "location": "2층 실기실",
    } | overrides
    return await client.post(
        f"{world.class_base}/schedules", json=body, headers=(actor or world.teacher).headers
    )


async def _occurrences(client, world: World, actor, start: dt.date, end: dt.date, **params):  # type: ignore[no-untyped-def]
    query = {"from": start.isoformat(), "to": end.isoformat(), **params}
    response = await client.get(f"{world.base}/schedules", params=query, headers=actor.headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


# ----------------------------------------------------------------------------- classes


async def test_class_creation_and_assignment(client: httpx.AsyncClient, world: World) -> None:
    detail = await client.get(world.class_base, headers=world.owner.headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["student_count"] == 2
    assert [i["display_name"] for i in body["instructors"]] == ["아트메이트 미술학원-담당강사"]

    members = await client.get(f"{world.class_base}/members", headers=world.teacher.headers)
    roles = sorted((m["role"], m["display_name"]) for m in members.json()["items"])
    assert roles == [
        ("INSTRUCTOR", "아트메이트 미술학원-담당강사"),
        ("STUDENT", "아트메이트 미술학원-학생1"),
        ("STUDENT", "아트메이트 미술학원-학생2"),
    ]

    # 담당 강사는 학생을 배정할 수 있다
    added = await client.post(
        f"{world.class_base}/members",
        json={"membership_id": world.students[2].membership_id},
        headers=world.teacher.headers,
    )
    assert added.status_code == 201
    assert added.json()["role"] == "STUDENT"

    duplicate = await client.post(
        f"{world.class_base}/members",
        json={"membership_id": world.students[2].membership_id},
        headers=world.owner.headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ALREADY_IN_CLASS"

    # 해제 후 재배정 (같은 행 재활성화)
    removed = await client.delete(
        f"{world.class_base}/members/{added.json()['id']}", headers=world.teacher.headers
    )
    assert removed.status_code == 204
    again = await client.post(
        f"{world.class_base}/members",
        json={"membership_id": world.students[2].membership_id},
        headers=world.teacher.headers,
    )
    assert again.status_code == 201
    assert again.json()["id"] == added.json()["id"]


async def test_class_permissions(client: httpx.AsyncClient, world: World) -> None:
    # 반 생성은 OWNER/MANAGER만
    by_teacher = await client.post(
        f"{world.base}/classes", json={"name": "B반"}, headers=world.teacher.headers
    )
    assert by_teacher.status_code == 403

    # 담당 강사라도 다른 강사를 담당 강사로 지정할 수 없다
    assign_teacher = await client.post(
        f"{world.class_base}/members",
        json={"membership_id": world.other_teacher.membership_id},
        headers=world.teacher.headers,
    )
    assert assign_teacher.status_code == 403

    # 비담당 강사는 학생 배정 불가
    by_other = await client.post(
        f"{world.class_base}/members",
        json={"membership_id": world.students[2].membership_id},
        headers=world.other_teacher.headers,
    )
    assert by_other.status_code == 403

    # 학생: 배정된 반만 보이고, 반 멤버 목록은 볼 수 없다
    mine = await client.get(f"{world.base}/classes", headers=world.students[0].headers)
    assert [c["id"] for c in mine.json()["items"]] == [world.class_id]
    assert mine.json()["items"][0]["my_role"] == "STUDENT"
    not_enrolled = await client.get(f"{world.base}/classes", headers=world.students[2].headers)
    assert not_enrolled.json()["items"] == []
    hidden = await client.get(world.class_base, headers=world.students[2].headers)
    assert hidden.status_code == 404
    members = await client.get(f"{world.class_base}/members", headers=world.students[0].headers)
    assert members.status_code == 403

    # 강사 담당 반 필터
    taught = await client.get(f"{world.base}/classes?mine=true", headers=world.teacher.headers)
    other = await client.get(f"{world.base}/classes?mine=true", headers=world.other_teacher.headers)
    assert [c["id"] for c in taught.json()["items"]] == [world.class_id]
    assert other.json()["items"] == []

    # 다른 학원 멤버 ID로 배정 불가
    unknown = await client.post(
        f"{world.class_base}/members",
        json={"membership_id": "00000000-0000-4000-8000-000000000000"},
        headers=world.owner.headers,
    )
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "INVALID_CLASS_MEMBER"


async def test_archived_class_blocks_changes(client: httpx.AsyncClient, world: World) -> None:
    archived = await client.patch(
        world.class_base, json={"status": "ARCHIVED"}, headers=world.owner.headers
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "ARCHIVED"

    blocked = await _schedule(client, world, world.owner)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "CLASS_ARCHIVED"

    listing = await client.get(f"{world.base}/classes", headers=world.owner.headers)
    assert listing.json()["items"] == []
    archived_list = await client.get(
        f"{world.base}/classes?status=ARCHIVED", headers=world.owner.headers
    )
    assert len(archived_list.json()["items"]) == 1


async def test_leaving_academy_ends_class_assignment(
    client: httpx.AsyncClient, world: World
) -> None:
    left = await client.delete(f"{world.base}/members/me", headers=world.students[0].headers)
    assert left.status_code == 204
    detail = await client.get(world.class_base, headers=world.owner.headers)
    assert detail.json()["student_count"] == 1
    members = await client.get(
        f"{world.class_base}/members?status=REMOVED", headers=world.owner.headers
    )
    assert [m["membership_id"] for m in members.json()["items"]] == [
        world.students[0].membership_id
    ]


# ----------------------------------------------------------------------------- schedules


async def test_regular_schedule_expands_with_seoul_offset(
    client: httpx.AsyncClient, world: World
) -> None:
    created = await _schedule(
        client, world, effective_until=(MON + dt.timedelta(days=20)).isoformat()
    )
    assert created.status_code == 201, created.text
    assert created.json()["start_time"] == "16:00:00"

    items = await _occurrences(client, world, world.students[0], MON, MON + dt.timedelta(days=27))
    # 화요일 11/10, 11/17, 11/24 (effective_until 11/29 이전) → 3회
    assert [o["date"] for o in items] == ["2026-11-10", "2026-11-17", "2026-11-24"]
    first = items[0]
    assert first["starts_at"] == "2026-11-10T16:00:00+09:00"
    assert first["ends_at"] == "2026-11-10T18:00:00+09:00"
    assert first["kind"] == "REGULAR" and first["status"] == "SCHEDULED"
    assert first["class_name"] == "입시 A반"
    assert first["location"] == "2층 실기실"


async def test_schedule_validation_and_overlap(client: httpx.AsyncClient, world: World) -> None:
    assert (await _schedule(client, world)).status_code == 201

    overlap = await _schedule(client, world, start_time="17:00", end_time="19:00")
    assert overlap.status_code == 409
    assert overlap.json()["error"]["code"] == "SCHEDULE_OVERLAP"

    back_to_back = await _schedule(client, world, start_time="18:00", end_time="19:00")
    assert back_to_back.status_code == 201

    bad_times = await _schedule(client, world, weekday=3, start_time="18:00", end_time="16:00")
    assert bad_times.status_code == 422
    bad_weekday = await _schedule(client, world, weekday=7)
    assert bad_weekday.status_code == 422
    tz_time = await _schedule(client, world, weekday=4, start_time="16:00+09:00")
    assert tz_time.status_code == 422

    too_long = await client.get(
        f"{world.base}/schedules",
        params={"from": "2026-01-01", "to": "2026-12-31"},
        headers=world.owner.headers,
    )
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "INVALID_DATE_RANGE"

    # 비담당 강사·학생은 정규 수업 등록 불가
    assert (await _schedule(client, world, world.other_teacher, weekday=5)).status_code == 403
    # 반 학생: 반은 보이지만 권한 없음(403), 반 미배정 학생: 반 자체가 보이지 않음(404)
    assert (await _schedule(client, world, world.students[0], weekday=5)).status_code == 403
    assert (await _schedule(client, world, world.students[2], weekday=5)).status_code == 404


async def test_cancel_reschedule_and_makeup(client: httpx.AsyncClient, world: World) -> None:
    schedule_id = (await _schedule(client, world)).json()["id"]
    tue1, tue2 = MON + dt.timedelta(days=1), MON + dt.timedelta(days=8)
    exceptions = f"{world.class_base}/schedule-exceptions"

    cancelled = await client.post(
        exceptions,
        json={
            "kind": "CANCELLATION",
            "schedule_id": schedule_id,
            "original_date": tue1.isoformat(),
            "reason": "학원 휴무",
        },
        headers=world.teacher.headers,
    )
    assert cancelled.status_code == 201, cancelled.text

    duplicate = await client.post(
        exceptions,
        json={
            "kind": "RESCHEDULE",
            "schedule_id": schedule_id,
            "original_date": tue1.isoformat(),
            "session_date": "2026-11-12",
            "start_time": "10:00",
            "end_time": "12:00",
        },
        headers=world.teacher.headers,
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "SCHEDULE_EXCEPTION_EXISTS"

    not_a_session = await client.post(
        exceptions,
        json={"kind": "CANCELLATION", "schedule_id": schedule_id, "original_date": "2026-11-11"},
        headers=world.teacher.headers,
    )
    assert not_a_session.status_code == 422
    assert not_a_session.json()["error"]["code"] == "INVALID_OCCURRENCE"

    moved = await client.post(
        exceptions,
        json={
            "kind": "RESCHEDULE",
            "schedule_id": schedule_id,
            "original_date": tue2.isoformat(),
            "session_date": "2026-11-19",
            "start_time": "10:00",
            "end_time": "12:00",
        },
        headers=world.teacher.headers,
    )
    assert moved.status_code == 201

    class_makeup = await client.post(
        exceptions,
        json={
            "kind": "MAKEUP",
            "session_date": "2026-11-14",
            "start_time": "13:00",
            "end_time": "15:00",
            "reason": "휴강 보강",
        },
        headers=world.teacher.headers,
    )
    personal = await client.post(
        exceptions,
        json={
            "kind": "MAKEUP",
            "session_date": "2026-11-15",
            "start_time": "13:00",
            "end_time": "14:00",
            "student_membership_id": world.students[1].membership_id,
        },
        headers=world.teacher.headers,
    )
    assert class_makeup.status_code == 201 and personal.status_code == 201

    end = MON + dt.timedelta(days=13)
    student1 = await _occurrences(client, world, world.students[0], MON, end)
    assert [(o["date"], o["kind"], o["status"]) for o in student1] == [
        ("2026-11-10", "REGULAR", "CANCELLED"),
        ("2026-11-14", "MAKEUP", "SCHEDULED"),
        ("2026-11-19", "REGULAR", "RESCHEDULED"),
    ]
    assert student1[0]["reason"] == "학원 휴무"
    assert student1[2]["original_date"] == "2026-11-17"
    assert student1[2]["starts_at"] == "2026-11-19T10:00:00+09:00"

    # 학생2에게만 개인 보강이 보인다
    student2 = await _occurrences(client, world, world.students[1], MON, end)
    assert ("2026-11-15", "MAKEUP") in [(o["date"], o["kind"]) for o in student2]
    teacher_view = await _occurrences(client, world, world.teacher, MON, end, mine="true")
    assert len(teacher_view) == 4

    # 휴강 취소 → 정규 수업 복구, 보강 취소 → CANCELLED 표시
    await client.delete(f"{exceptions}/{cancelled.json()['id']}", headers=world.teacher.headers)
    await client.delete(f"{exceptions}/{class_makeup.json()['id']}", headers=world.teacher.headers)
    after = await _occurrences(client, world, world.students[0], MON, end)
    assert [(o["date"], o["status"]) for o in after] == [
        ("2026-11-10", "SCHEDULED"),
        ("2026-11-14", "CANCELLED"),
        ("2026-11-19", "RESCHEDULED"),
    ]

    # 변경 일정 수정
    patched = await client.patch(
        f"{exceptions}/{moved.json()['id']}",
        json={"start_time": "11:00", "end_time": "13:00"},
        headers=world.teacher.headers,
    )
    assert patched.status_code == 200
    assert patched.json()["start_time"] == "11:00:00"


async def test_schedule_update_and_delete(client: httpx.AsyncClient, world: World) -> None:
    schedule = (await _schedule(client, world)).json()
    path = f"{world.class_base}/schedules/{schedule['id']}"

    changed = await client.patch(
        path, json={"weekday": 3, "location": None}, headers=world.teacher.headers
    )
    assert changed.status_code == 200
    assert changed.json()["weekday"] == 3 and changed.json()["location"] is None

    null_weekday = await client.patch(path, json={"weekday": None}, headers=world.teacher.headers)
    assert null_weekday.status_code == 422

    items = await _occurrences(client, world, world.owner, MON, MON + dt.timedelta(days=6))
    assert [o["date"] for o in items] == ["2026-11-12"]

    assert (await client.delete(path, headers=world.teacher.headers)).status_code == 204
    assert await _occurrences(client, world, world.owner, MON, MON + dt.timedelta(days=6)) == []
    listed = await client.get(f"{world.class_base}/schedules", headers=world.students[0].headers)
    assert listed.json()["total"] == 0


async def test_student_and_instructor_schedule_views(
    client: httpx.AsyncClient, world: World
) -> None:
    await _schedule(client, world)
    week = (MON, MON + dt.timedelta(days=6))

    # 강사별 담당 수업
    by_instructor = await _occurrences(
        client, world, world.owner, *week, instructor_membership_id=world.teacher.membership_id
    )
    assert len(by_instructor) == 1
    other = await _occurrences(
        client,
        world,
        world.owner,
        *week,
        instructor_membership_id=world.other_teacher.membership_id,
    )
    assert other == []

    # 학생별 일정 (담당 강사)
    by_student = await _occurrences(
        client, world, world.teacher, *week, student_membership_id=world.students[0].membership_id
    )
    assert len(by_student) == 1
    # 반이 없는 학생은 일정 없음
    assert await _occurrences(client, world, world.students[2], *week) == []

    # 비담당 강사는 다른 학생 일정 조회 불가, 학생은 남의 일정 조회 불가
    forbidden = await client.get(
        f"{world.base}/schedules",
        params={"student_membership_id": world.students[0].membership_id},
        headers=world.other_teacher.headers,
    )
    assert forbidden.status_code == 403
    peek = await client.get(
        f"{world.base}/schedules",
        params={"student_membership_id": world.students[1].membership_id},
        headers=world.students[0].headers,
    )
    assert peek.status_code == 403


async def test_concurrent_cancellations_create_one_exception(
    client: httpx.AsyncClient, world: World
) -> None:
    schedule_id = (await _schedule(client, world)).json()["id"]
    body = {"kind": "CANCELLATION", "schedule_id": schedule_id, "original_date": "2026-11-10"}
    responses = await asyncio.gather(
        *[
            client.post(
                f"{world.class_base}/schedule-exceptions", json=body, headers=world.teacher.headers
            )
            for _ in range(5)
        ]
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [201, 409, 409, 409, 409]
