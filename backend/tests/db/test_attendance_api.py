"""출석 (F-03): 체크인·중복 방지·본인 기록·강사 수정 권한·수정 이력·시간대·동시성."""

import asyncio
import datetime as dt

import httpx
import pytest

from app.core import timezone as clock
from tests.db.conftest import World


async def test_student_check_in_and_duplicate(client: httpx.AsyncClient, world: World) -> None:
    student = world.students[0]
    before = await client.get(f"{world.base}/attendance/me/today", headers=student.headers)
    assert before.json() == {
        "date": clock.local_today().isoformat(),
        "checked_in": False,
        "record": None,
    }

    checked = await client.post(f"{world.base}/attendance/check-in", headers=student.headers)
    assert checked.status_code == 201, checked.text
    record = checked.json()
    assert record["status"] == "PRESENT"
    assert record["source"] == "SELF_CHECK_IN"
    assert record["attendance_date"] == clock.local_today().isoformat()
    assert record["checked_in_at"] is not None
    assert record["student_membership_id"] == student.membership_id

    again = await client.post(f"{world.base}/attendance/check-in", headers=student.headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ALREADY_CHECKED_IN"

    today = await client.get(f"{world.base}/attendance/me/today", headers=student.headers)
    assert today.json()["checked_in"] is True
    assert today.json()["record"]["id"] == record["id"]

    mine = await client.get(f"{world.base}/attendance/me", headers=student.headers)
    assert [r["id"] for r in mine.json()["items"]] == [record["id"]]
    # 다른 학생의 기록은 보이지 않는다
    other = await client.get(f"{world.base}/attendance/me", headers=world.students[1].headers)
    assert other.json()["items"] == []


async def test_only_active_student_members_can_check_in(
    client: httpx.AsyncClient, world: World, actors
) -> None:  # type: ignore[no-untyped-def]
    outsider = await actors.signup("STUDENT")
    not_member = await client.post(f"{world.base}/attendance/check-in", headers=outsider.headers)
    assert not_member.status_code == 404

    by_teacher = await client.post(
        f"{world.base}/attendance/check-in", headers=world.teacher.headers
    )
    assert by_teacher.status_code == 403

    await client.delete(f"{world.base}/members/me", headers=world.students[2].headers)
    left = await client.post(f"{world.base}/attendance/check-in", headers=world.students[2].headers)
    assert left.status_code == 404


async def test_check_in_uses_seoul_date(
    client: httpx.AsyncClient, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # UTC 3/1 15:30 = 서울 3/2 00:30 → 출석일은 3/2
    fixed = dt.datetime(2026, 3, 1, 15, 30, tzinfo=dt.UTC)
    monkeypatch.setattr(clock, "utc_now", lambda: fixed)
    checked = await client.post(
        f"{world.base}/attendance/check-in", headers=world.students[0].headers
    )
    assert checked.json()["attendance_date"] == "2026-03-02"
    assert checked.json()["checked_in_at"].startswith("2026-03-01T15:30:00")

    # 같은 서울 날짜 안의 다른 UTC 날짜도 중복
    monkeypatch.setattr(clock, "utc_now", lambda: fixed + dt.timedelta(hours=10))
    again = await client.post(
        f"{world.base}/attendance/check-in", headers=world.students[0].headers
    )
    assert again.status_code == 409


async def test_concurrent_check_ins_record_once(client: httpx.AsyncClient, world: World) -> None:
    student = world.students[0]
    responses = await asyncio.gather(
        *[
            client.post(f"{world.base}/attendance/check-in", headers=student.headers)
            for _ in range(8)
        ]
    )
    assert sorted(r.status_code for r in responses) == [201] + [409] * 7
    mine = await client.get(f"{world.base}/attendance/me", headers=student.headers)
    assert mine.json()["total"] == 1


async def test_instructor_day_status(client: httpx.AsyncClient, world: World) -> None:
    await client.post(f"{world.base}/attendance/check-in", headers=world.students[0].headers)

    # 담당 강사: 반 학생 2명만 (학생3은 반 미배정)
    status = await client.get(f"{world.base}/attendance", headers=world.teacher.headers)
    assert status.status_code == 200
    body = status.json()
    assert body["date"] == clock.local_today().isoformat()
    rows = {i["student"]["display_name"]: i["record"] for i in body["items"]}
    assert set(rows) == {"아트메이트 미술학원-학생1", "아트메이트 미술학원-학생2"}
    assert rows["아트메이트 미술학원-학생1"]["status"] == "PRESENT"
    assert rows["아트메이트 미술학원-학생2"] is None

    # 원장은 학원 전체 학생
    by_owner = await client.get(f"{world.base}/attendance", headers=world.owner.headers)
    assert by_owner.json()["total"] == 3

    # 비담당 강사는 담당 학생이 없다, 반 필터는 403
    other = await client.get(f"{world.base}/attendance", headers=world.other_teacher.headers)
    assert other.json()["total"] == 0
    filtered = await client.get(
        f"{world.base}/attendance?class_id={world.class_id}", headers=world.other_teacher.headers
    )
    assert filtered.status_code == 403

    past = await client.get(
        f"{world.base}/attendance?date=2026-01-05", headers=world.teacher.headers
    )
    assert all(i["record"] is None for i in past.json()["items"])

    # 학생은 출석 현황 조회 불가
    by_student = await client.get(f"{world.base}/attendance", headers=world.students[0].headers)
    assert by_student.status_code == 403


async def test_instructor_edits_attendance_with_history(
    client: httpx.AsyncClient, world: World
) -> None:
    record = (
        await client.post(f"{world.base}/attendance/check-in", headers=world.students[0].headers)
    ).json()
    path = f"{world.base}/attendance/records/{record['id']}"

    updated = await client.patch(
        path, json={"status": "LATE", "reason": "20분 지각"}, headers=world.teacher.headers
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "LATE"
    assert updated.json()["updated_by"] == world.teacher.membership_id
    assert updated.json()["source"] == "SELF_CHECK_IN"

    noted = await client.patch(path, json={"note": "버스 지연"}, headers=world.owner.headers)
    assert noted.json()["note"] == "버스 지연"

    # 변경 없는 수정은 이력을 남기지 않는다
    await client.patch(path, json={"status": "LATE"}, headers=world.teacher.headers)

    history = await client.get(f"{path}/history", headers=world.teacher.headers)
    logs = history.json()["items"]
    assert [log["action"] for log in logs] == ["UPDATED", "UPDATED"]
    assert logs[0]["previous"] == {"status": "PRESENT", "note": None}
    assert logs[0]["current"] == {"status": "LATE", "note": None}
    assert logs[0]["reason"] == "20분 지각"
    assert logs[0]["changed_by_name"] == "아트메이트 미술학원-담당강사"
    assert logs[1]["changed_by"] == world.owner.membership_id

    # 학생 본인 기록에도 반영
    mine = await client.get(f"{world.base}/attendance/me", headers=world.students[0].headers)
    assert mine.json()["items"][0]["status"] == "LATE"


async def test_instructor_creates_missing_record(client: httpx.AsyncClient, world: World) -> None:
    body = {
        "student_membership_id": world.students[1].membership_id,
        "attendance_date": "2026-11-03",
        "status": "EXCUSED",
        "note": "병결",
        "reason": "보호자 연락",
    }
    created = await client.post(
        f"{world.base}/attendance/records", json=body, headers=world.teacher.headers
    )
    assert created.status_code == 201, created.text
    assert created.json()["source"] == "INSTRUCTOR"
    assert created.json()["checked_in_at"] is None

    duplicate = await client.post(
        f"{world.base}/attendance/records", json=body, headers=world.owner.headers
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "ATTENDANCE_ALREADY_RECORDED"

    history = await client.get(
        f"{world.base}/attendance/records/{created.json()['id']}/history",
        headers=world.teacher.headers,
    )
    assert history.json()["items"][0]["action"] == "CREATED"
    assert history.json()["items"][0]["previous"] is None

    records = await client.get(
        f"{world.base}/attendance/records",
        params={
            "student_membership_id": world.students[1].membership_id,
            "from": "2026-11-01",
            "to": "2026-11-05",
        },
        headers=world.teacher.headers,
    )
    assert [r["status"] for r in records.json()["items"]] == ["EXCUSED"]


async def test_attendance_edit_permissions(client: httpx.AsyncClient, world: World) -> None:
    record = (
        await client.post(f"{world.base}/attendance/check-in", headers=world.students[0].headers)
    ).json()
    path = f"{world.base}/attendance/records/{record['id']}"

    # 비담당 강사: 수정·이력 403, 학생: 403
    assert (
        await client.patch(path, json={"status": "ABSENT"}, headers=world.other_teacher.headers)
    ).status_code == 403
    assert (
        await client.get(f"{path}/history", headers=world.other_teacher.headers)
    ).status_code == 403
    assert (
        await client.patch(path, json={"status": "ABSENT"}, headers=world.students[0].headers)
    ).status_code == 403

    # 반 미배정 학생(학생3)은 담당 강사도 기록 불가
    not_mine = await client.post(
        f"{world.base}/attendance/records",
        json={
            "student_membership_id": world.students[2].membership_id,
            "attendance_date": "2026-11-03",
            "status": "ABSENT",
        },
        headers=world.teacher.headers,
    )
    assert not_mine.status_code == 403

    # 입력 검증
    invalid = await client.patch(path, json={"status": "SLEEPING"}, headers=world.teacher.headers)
    assert invalid.status_code == 422
    empty = await client.patch(path, json={"reason": "x"}, headers=world.teacher.headers)
    assert empty.status_code == 422
    null_status = await client.patch(path, json={"status": None}, headers=world.teacher.headers)
    assert null_status.status_code == 422


async def test_concurrent_edits_keep_consistent_history(
    client: httpx.AsyncClient, world: World
) -> None:
    record = (
        await client.post(f"{world.base}/attendance/check-in", headers=world.students[0].headers)
    ).json()
    path = f"{world.base}/attendance/records/{record['id']}"
    statuses = ["LATE", "ABSENT", "EXCUSED", "PRESENT", "LATE", "ABSENT"]
    responses = await asyncio.gather(
        *[client.patch(path, json={"status": s}, headers=world.teacher.headers) for s in statuses]
    )
    assert all(r.status_code == 200 for r in responses)

    logs = (await client.get(f"{path}/history?limit=100", headers=world.teacher.headers)).json()[
        "items"
    ]
    # 행 잠금으로 직렬화: 각 이력의 previous는 직전 이력의 current와 같다
    chain = [{"status": "PRESENT", "note": None}] + [log["current"] for log in logs]
    for i, log in enumerate(logs):
        assert log["previous"] == chain[i]
    final = (
        await client.get(f"{world.base}/attendance/me", headers=world.students[0].headers)
    ).json()
    assert final["items"][0]["status"] == chain[-1]["status"]
