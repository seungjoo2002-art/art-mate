"""질문 콜·대기열 (F-07): 생성·취소, 중복 방지, 순서, 예상 대기시간, 동시 호출, 권한, 격리."""

import asyncio
import datetime as dt

import httpx
import pytest

from app.core import timezone as clock
from tests.db.conftest import Actor, World


@pytest.fixture
async def queue_world(client: httpx.AsyncClient, world: World) -> World:
    """반에 학생 3명 + 담당 강사 2명."""
    for member in (world.students[2], world.other_teacher):
        added = await client.post(
            f"{world.class_base}/members",
            json={"membership_id": member.membership_id},
            headers=world.owner.headers,
        )
        assert added.status_code == 201, added.text
    return world


async def _ask(client: httpx.AsyncClient, w: World, student: Actor, **body) -> httpx.Response:  # type: ignore[no-untyped-def]
    return await client.post(
        f"{w.base}/help-requests", json={"class_id": w.class_id} | body, headers=student.headers
    )


def _queue_url(w: World) -> str:
    return f"{w.class_base}/help-queue"


async def test_create_status_and_cancel(client: httpx.AsyncClient, queue_world: World, app) -> None:  # type: ignore[no-untyped-def]
    w = queue_world
    s1 = w.students[0]
    created = await _ask(client, w, s1, note="명암이 어려워요")
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "WAITING" and body["position"] == 1 and body["is_active"]
    assert body["class_name"] == "입시 A반"
    assert body["estimate"]["is_default"] is True and body["estimate"]["source"] == "DEFAULT"
    assert body["estimate"]["estimated_wait_seconds"] == 0  # 앞에 아무도 없음

    duplicate = await _ask(client, w, s1)
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "HELP_REQUEST_ALREADY_ACTIVE"
    assert duplicate.json()["error"]["details"]["help_request_id"] == body["id"]

    mine = await client.get(f"{w.base}/help-requests/me/{body['id']}", headers=s1.headers)
    assert mine.json()["status"] == "WAITING"
    cancelled = await client.post(
        f"{w.base}/help-requests/me/{body['id']}/cancel", headers=s1.headers
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED" and cancelled.json()["is_active"] is False
    again = await client.post(f"{w.base}/help-requests/me/{body['id']}/cancel", headers=s1.headers)
    assert again.status_code == 409

    # 취소 후 새 요청 가능, 지난 요청은 active=false 목록에
    assert (await _ask(client, w, s1)).status_code == 201
    active = await client.get(f"{w.base}/help-requests/me", headers=s1.headers)
    history = await client.get(f"{w.base}/help-requests/me?active=false", headers=s1.headers)
    assert active.json()["total"] == 1 and history.json()["total"] == 2

    # 상태 변경은 publisher로 알린다 (v0.5 no-op 확장 지점)
    events = [c.event_type for c in app.state.help_publisher.changes]
    assert events == ["CREATED", "CANCELLED", "CREATED"]


async def test_queue_order_positions_and_staff_flow(
    client: httpx.AsyncClient, queue_world: World
) -> None:
    w = queue_world
    s1, s2, s3 = w.students
    ids = [(await _ask(client, w, s)).json()["id"] for s in (s1, s2, s3)]

    positions = [
        (await client.get(f"{w.base}/help-requests/me/{rid}", headers=s.headers)).json()["position"]
        for rid, s in zip(ids, (s1, s2, s3), strict=True)
    ]
    assert positions == [1, 2, 3]

    queue = (await client.get(_queue_url(w), headers=w.teacher.headers)).json()
    assert [r["id"] for r in queue["waiting"]] == ids
    assert [r["position"] for r in queue["waiting"]] == [1, 2, 3]
    assert queue["waiting_count"] == 3 and queue["active_count"] == 0
    assert queue["recommended_poll_seconds"] == 5
    assert queue["last_changed_at"] is not None
    assert queue["waiting"][0]["student"]["membership_id"] == s1.membership_id

    # 다음 학생 호출 → 순서대로, 학생 화면에 호출한 강사 표시
    called = await client.post(f"{_queue_url(w)}/call-next", headers=w.teacher.headers)
    assert called.status_code == 200
    assert called.json()["id"] == ids[0] and called.json()["status"] == "CALLED"
    view = (await client.get(f"{w.base}/help-requests/me/{ids[0]}", headers=s1.headers)).json()
    assert view["status"] == "CALLED" and view["position"] is None
    assert view["called_by_name"] == "아트메이트 미술학원-담당강사"
    # 나머지 순번이 당겨진다
    s2_view = (await client.get(f"{w.base}/help-requests/me/{ids[1]}", headers=s2.headers)).json()
    assert s2_view["position"] == 1 and s2_view["estimate"]["ahead_count"] == 1  # 처리 중 1명

    base = f"{w.base}/help-requests"
    started = await client.post(f"{base}/{ids[0]}/start", headers=w.teacher.headers)
    assert started.json()["status"] == "IN_PROGRESS"
    done = await client.post(f"{base}/{ids[0]}/complete", headers=w.teacher.headers)
    assert done.json()["status"] == "COMPLETED"
    assert done.json()["handled_by_name"] == "아트메이트 미술학원-담당강사"
    finished = (await client.get(f"{base}/me/{ids[0]}", headers=s1.headers)).json()
    assert finished["status"] == "COMPLETED" and finished["is_active"] is False

    # 허용되지 않는 전이 → 409
    again = await client.post(f"{base}/{ids[0]}/complete", headers=w.teacher.headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "HELP_REQUEST_INVALID_STATE"

    # 호출 취소(requeue)는 원래 순번 유지, 건너뛰기(skip)는 대기열에서 제거
    await client.post(f"{base}/{ids[2]}/call", headers=w.teacher.headers)
    requeued = await client.post(f"{base}/{ids[2]}/requeue", headers=w.teacher.headers)
    assert requeued.json()["status"] == "WAITING" and requeued.json()["position"] == 2
    skipped = await client.post(f"{base}/{ids[1]}/skip", headers=w.teacher.headers)
    assert skipped.json()["status"] == "SKIPPED"
    queue = (await client.get(_queue_url(w), headers=w.teacher.headers)).json()
    assert [r["id"] for r in queue["waiting"]] == [ids[2]]
    # 처리 중 요청은 학생이 취소할 수 없지만 강사는 가능
    await client.post(f"{base}/{ids[2]}/start", headers=w.teacher.headers)
    blocked = await client.post(f"{base}/me/{ids[2]}/cancel", headers=s3.headers)
    assert blocked.status_code == 409
    staff_cancel = await client.post(f"{base}/{ids[2]}/cancel", headers=w.teacher.headers)
    assert staff_cancel.json()["status"] == "CANCELLED"

    empty = await client.post(f"{_queue_url(w)}/call-next", headers=w.teacher.headers)
    assert empty.status_code == 409 and empty.json()["error"]["code"] == "HELP_QUEUE_EMPTY"
    bad_action = await client.post(f"{base}/{ids[0]}/explode", headers=w.teacher.headers)
    assert bad_action.status_code == 422


async def test_estimated_wait_from_recent_average(
    client: httpx.AsyncClient, queue_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = queue_world
    now = {"t": dt.datetime(2026, 11, 10, 7, 0, tzinfo=dt.UTC)}
    monkeypatch.setattr(clock, "utc_now", lambda: now["t"])
    base = f"{w.base}/help-requests"

    # 3건 처리: 처리시간 60s, 120s, 180s (평균 120s)
    for student, seconds in zip(w.students, (60, 120, 180), strict=True):
        rid = (await _ask(client, w, student)).json()["id"]
        await client.post(f"{base}/{rid}/start", headers=w.teacher.headers)
        now["t"] += dt.timedelta(seconds=seconds)
        await client.post(f"{base}/{rid}/complete", headers=w.teacher.headers)

    estimate = (await client.get(f"{_queue_url(w)}/estimate", headers=w.students[0].headers)).json()
    assert estimate["estimate"]["source"] == "RECENT_AVERAGE"
    assert estimate["estimate"]["average_handle_seconds"] == 120
    assert estimate["estimate"]["sample_size"] == 3
    assert estimate["estimate"]["estimated_wait_seconds"] == 0

    # 대기 3명, 담당 강사 2명: 세 번째 학생 앞 2명 → 2 × 120 / 2 = 120초
    ids = [(await _ask(client, w, s)).json()["id"] for s in w.students]
    third = (await client.get(f"{base}/me/{ids[2]}", headers=w.students[2].headers)).json()
    assert third["estimate"]["ahead_count"] == 2
    assert third["estimate"]["active_handlers"] == 2
    assert third["estimate"]["estimated_wait_seconds"] == 120
    assert third["estimate"]["is_default"] is False

    # 반 미배정 학생·다른 반은 예상 시간 조회 불가
    other_class = await client.post(
        f"{w.base}/classes", json={"name": "B반"}, headers=w.owner.headers
    )
    hidden = await client.get(
        f"{w.base}/classes/{other_class.json()['id']}/help-queue/estimate",
        headers=w.students[0].headers,
    )
    assert hidden.status_code == 404


async def test_concurrent_requests_and_calls(client: httpx.AsyncClient, queue_world: World) -> None:
    w = queue_world
    # 같은 학생의 동시 요청 → 1건만 생성
    responses = await asyncio.gather(*[_ask(client, w, w.students[0]) for _ in range(6)])
    assert sorted(r.status_code for r in responses) == [201] + [409] * 5

    for student in w.students[1:]:
        await _ask(client, w, student)
    # 두 강사가 동시에 '다음 학생 호출' → 서로 다른 학생, 중복 호출 없음
    calls = await asyncio.gather(
        *[
            client.post(f"{_queue_url(w)}/call-next", headers=t.headers)
            for t in (w.teacher, w.other_teacher, w.teacher, w.other_teacher)
        ]
    )
    ok = [r.json()["id"] for r in calls if r.status_code == 200]
    assert len(ok) == 3 and len(set(ok)) == 3
    assert sorted(r.status_code for r in calls) == [200, 200, 200, 409]

    # 같은 요청을 동시에 처리 시작 → 1명만 성공
    target = ok[0]
    starts = await asyncio.gather(
        *[
            client.post(f"{w.base}/help-requests/{target}/start", headers=t.headers)
            for t in (w.teacher, w.other_teacher)
        ]
    )
    assert sorted(r.status_code for r in starts) == [200, 409]


async def test_permissions_and_isolation(
    client: httpx.AsyncClient, queue_world: World, build_world
) -> None:  # type: ignore[no-untyped-def]
    w = queue_world
    rid = (await _ask(client, w, w.students[0])).json()["id"]

    # 반에 없는 학생은 요청 불가, 강사는 학생 API 불가, 학생은 강사 API 불가
    other_class = await client.post(
        f"{w.base}/classes", json={"name": "B반"}, headers=w.owner.headers
    )
    not_in_class = await client.post(
        f"{w.base}/help-requests",
        json={"class_id": other_class.json()["id"]},
        headers=w.students[0].headers,
    )
    assert not_in_class.status_code == 404
    assert (await _ask(client, w, w.teacher)).status_code == 403
    assert (await client.get(_queue_url(w), headers=w.students[0].headers)).status_code == 403
    assert (
        await client.post(f"{w.base}/help-requests/{rid}/call", headers=w.students[1].headers)
    ).status_code == 403
    # 다른 학생의 요청 조회·취소 → 404
    assert (
        await client.get(f"{w.base}/help-requests/me/{rid}", headers=w.students[1].headers)
    ).status_code == 404

    # 반 담당이 아닌 강사는 대기열·처리 불가(403), 원장은 관리자라 가능
    await client.delete(
        f"{w.class_base}/members/"
        + next(
            m["id"]
            for m in (await client.get(f"{w.class_base}/members", headers=w.owner.headers)).json()[
                "items"
            ]
            if m["membership_id"] == w.other_teacher.membership_id
        ),
        headers=w.owner.headers,
    )
    assert (await client.get(_queue_url(w), headers=w.other_teacher.headers)).status_code == 403
    assert (
        await client.post(f"{w.base}/help-requests/{rid}/call", headers=w.other_teacher.headers)
    ).status_code == 403
    assert (await client.get(_queue_url(w), headers=w.owner.headers)).status_code == 200

    outsider_teacher = await build_world("다른 미술학원", admin=w.admin)

    # 다른 학원: 경로 404, 자기 학원 경로에 남의 요청 ID도 404
    assert (
        await client.get(_queue_url(w), headers=outsider_teacher.owner.headers)
    ).status_code == 404
    cross = await client.post(
        f"{outsider_teacher.base}/help-requests/{rid}/call", headers=outsider_teacher.owner.headers
    )
    assert cross.status_code == 404
    cross_class = await client.post(
        f"{outsider_teacher.base}/help-requests",
        json={"class_id": w.class_id},
        headers=outsider_teacher.students[0].headers,
    )
    assert cross_class.status_code == 404

    # 남의 작품은 질문에 연결할 수 없다
    other_art = await client.post(
        "/api/v1/artworks", json={"title": "남의 작품"}, headers=w.students[1].headers
    )
    linked = await _ask(client, w, w.students[2], artwork_id=other_art.json()["id"])
    assert linked.status_code == 422 and linked.json()["error"]["code"] == "INVALID_ARTWORK_LINK"
    mine = await client.post(
        "/api/v1/artworks", json={"title": "내 작품"}, headers=w.students[2].headers
    )
    ok = await _ask(client, w, w.students[2], artwork_id=mine.json()["id"])
    assert ok.status_code == 201 and ok.json()["artwork_id"] == mine.json()["id"]
