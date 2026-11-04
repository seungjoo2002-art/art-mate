"""시험 타이머 (F-10): 템플릿·목표 검증, 시작·종료, 학생 진행 상태, 시간 계산, 동시성, 격리."""

import asyncio
import datetime as dt

import httpx
import pytest

from app.core import timezone as clock
from tests.db.conftest import World

TARGETS = [
    {"stage": "SKETCH", "offset_minutes": 60},
    {"stage": "PROGRESS", "offset_minutes": 180},
    {"stage": "FINAL", "offset_minutes": 230},
]
T0 = dt.datetime(2026, 11, 10, 7, 0, tzinfo=dt.UTC)  # 서울 16:00


class Clock:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.now = T0
        monkeypatch.setattr(clock, "utc_now", lambda: self.now)

    def advance(self, **kw: int) -> None:
        self.now += dt.timedelta(**kw)


@pytest.fixture
def fixed_clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    return Clock(monkeypatch)


async def _template(client: httpx.AsyncClient, world: World, actor=None, **body) -> httpx.Response:  # type: ignore[no-untyped-def]
    payload = {
        "name": "기초디자인 모의고사",
        "exam_type": "기초디자인",
        "total_minutes": 240,
        "stage_targets": TARGETS,
    } | body
    return await client.post(
        f"{world.base}/exam-templates", json=payload, headers=(actor or world.teacher).headers
    )


async def _running_exam(client: httpx.AsyncClient, world: World) -> dict:  # type: ignore[type-arg]
    template = (await _template(client, world)).json()
    created = await client.post(
        f"{world.base}/exam-sessions",
        json={"template_id": template["id"], "class_id": world.class_id, "start_now": True},
        headers=world.teacher.headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


# ----------------------------------------------------------------------------- templates


async def test_template_create_and_validation(client: httpx.AsyncClient, world: World) -> None:
    created = await _template(client, world, description="4시간")
    assert created.status_code == 201, created.text
    body = created.json()
    assert [t["stage"] for t in body["stage_targets"]] == ["SKETCH", "PROGRESS", "FINAL"]

    invalid = [
        [
            {"stage": "SKETCH", "offset_minutes": 60},
            {"stage": "PROGRESS", "offset_minutes": 50},
            {"stage": "FINAL", "offset_minutes": 230},
        ],  # 순서 역전
        [
            {"stage": "SKETCH", "offset_minutes": 60},
            {"stage": "SKETCH", "offset_minutes": 90},
            {"stage": "FINAL", "offset_minutes": 230},
        ],  # 단계 중복
        [
            {"stage": "SKETCH", "offset_minutes": 60},
            {"stage": "PROGRESS", "offset_minutes": 180},
            {"stage": "FINAL", "offset_minutes": 300},
        ],  # 총시간 초과
    ]
    for targets in invalid:
        response = await _template(client, world, stage_targets=targets)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVALID_STAGE_TARGETS"
    assert (await _template(client, world, stage_targets=TARGETS[:2])).status_code == 422
    assert (await _template(client, world, total_minutes=0)).status_code == 422

    # 총시간을 줄이면 기존 목표와 충돌 → 422, 목표와 함께 바꾸면 성공
    path = f"{world.base}/exam-templates/{body['id']}"
    shrink = await client.patch(path, json={"total_minutes": 200}, headers=world.teacher.headers)
    assert shrink.status_code == 422
    targets = await client.put(
        f"{path}/stage-targets",
        json={
            "stage_targets": [
                {"stage": "SKETCH", "offset_minutes": 30},
                {"stage": "PROGRESS", "offset_minutes": 90},
                {"stage": "FINAL", "offset_minutes": 120},
            ]
        },
        headers=world.teacher.headers,
    )
    assert targets.status_code == 200
    assert (
        await client.patch(path, json={"total_minutes": 150}, headers=world.teacher.headers)
    ).json()["total_minutes"] == 150

    # 수정 권한: 만든 사람·관리자만. 학생은 템플릿 API 사용 불가
    assert (
        await client.patch(path, json={"name": "x"}, headers=world.other_teacher.headers)
    ).status_code == 403
    assert (
        await client.patch(path, json={"name": "원장 수정"}, headers=world.owner.headers)
    ).status_code == 200
    assert (
        await client.get(f"{world.base}/exam-templates", headers=world.students[0].headers)
    ).status_code == 403

    # 보관된 템플릿은 목록·새 시험에서 제외
    assert (await client.delete(path, headers=world.teacher.headers)).status_code == 204
    assert (await client.get(f"{world.base}/exam-templates", headers=world.teacher.headers)).json()[
        "total"
    ] == 0
    archived = await client.post(
        f"{world.base}/exam-sessions",
        json={"template_id": body["id"], "class_id": world.class_id},
        headers=world.teacher.headers,
    )
    assert archived.status_code == 409 and archived.json()["error"]["code"] == "TEMPLATE_ARCHIVED"


# ----------------------------------------------------------------------------- sessions


async def test_session_lifecycle_and_timer(
    client: httpx.AsyncClient, world: World, fixed_clock: Clock
) -> None:
    template = (await _template(client, world)).json()
    created = await client.post(
        f"{world.base}/exam-sessions",
        json={"template_id": template["id"], "class_id": world.class_id, "title": "11월 모의고사"},
        headers=world.teacher.headers,
    )
    session = created.json()
    assert session["timer"]["status"] == "SCHEDULED"
    assert session["timer"]["remaining_seconds"] == 240 * 60
    assert session["participants"] == []
    base = f"{world.base}/exam-sessions/{session['id']}"

    # 비담당 강사·학생은 시작 불가
    assert (
        await client.post(f"{base}/start", headers=world.other_teacher.headers)
    ).status_code == 403
    assert (
        await client.post(f"{base}/start", headers=world.students[0].headers)
    ).status_code == 403

    started = await client.post(f"{base}/start", headers=world.teacher.headers)
    assert started.status_code == 200, started.text
    body = started.json()
    timer = body["timer"]
    assert timer["status"] == "RUNNING"
    assert timer["started_at"] == "2026-11-10T07:00:00Z"
    assert timer["ends_at"] == "2026-11-10T11:00:00Z"
    assert [s["target_at"] for s in timer["stages"]] == [
        "2026-11-10T08:00:00Z",
        "2026-11-10T10:00:00Z",
        "2026-11-10T10:50:00Z",
    ]
    assert body["participant_count"] == 2  # 반 학생 2명 (반 미배정 학생 제외)
    assert {p["current_stage"] for p in body["participants"]} == {"SKETCH"}
    assert (await client.post(f"{base}/start", headers=world.teacher.headers)).status_code == 409

    # 학생 화면: 남은 시간·목표 단계·다음 단계까지 남은 시간
    s1, s2 = world.students[0], world.students[1]
    fixed_clock.advance(minutes=75)
    mine = (await client.get(f"{base}/me", headers=s1.headers)).json()
    t = mine["timer"]
    assert t["server_time"] == "2026-11-10T08:15:00Z"
    assert t["remaining_seconds"] == 165 * 60 and t["elapsed_seconds"] == 75 * 60
    assert t["expected_stage"] == "PROGRESS"
    assert t["current_target"]["stage"] == "PROGRESS"
    assert t["current_target"]["seconds_remaining"] == 105 * 60
    assert t["next_alert_at"] == "2026-11-10T10:00:00Z"
    assert mine["me"]["current_stage"] == "SKETCH" and mine["me"]["behind_schedule"] is True

    changed = await client.put(f"{base}/me/stage", json={"stage": "PROGRESS"}, headers=s1.headers)
    assert changed.status_code == 200
    assert changed.json()["me"]["current_stage"] == "PROGRESS"
    assert changed.json()["me"]["progress_at"] == "2026-11-10T08:15:00Z"
    assert changed.json()["me"]["behind_schedule"] is False
    assert (
        await client.put(f"{base}/me/stage", json={"stage": "NOT_STARTED"}, headers=s1.headers)
    ).status_code == 422

    # 강사 반 현황
    detail = (await client.get(base, headers=world.teacher.headers)).json()
    counts = {c["stage"]: c["count"] for c in detail["stage_counts"]}
    assert counts["SKETCH"] == 1 and counts["PROGRESS"] == 1
    assert detail["behind_count"] == 1
    behind = {p["student"]["membership_id"]: p["behind_schedule"] for p in detail["participants"]}
    assert behind == {s1.membership_id: False, s2.membership_id: True}

    # 참가 시험 목록, 다른 학생은 참가하지 않은 시험 404
    active = (await client.get(f"{world.base}/exam-sessions/me", headers=s1.headers)).json()
    assert [e["id"] for e in active["items"]] == [session["id"]]
    assert (await client.get(f"{base}/me", headers=world.students[2].headers)).status_code == 404

    # 강사 종료 → 학생은 단계 변경 불가, 상태 ENDED(MANUAL)
    fixed_clock.advance(minutes=10)
    ended = (await client.post(f"{base}/end", headers=world.teacher.headers)).json()
    assert (ended["timer"]["status"], ended["timer"]["end_reason"]) == ("ENDED", "MANUAL")
    assert ended["timer"]["elapsed_seconds"] == 85 * 60
    late = await client.put(f"{base}/me/stage", json={"stage": "FINAL"}, headers=s2.headers)
    assert late.status_code == 409 and late.json()["error"]["code"] == "EXAM_NOT_RUNNING"
    assert (await client.get(f"{world.base}/exam-sessions/me", headers=s1.headers)).json()[
        "total"
    ] == 0
    history = await client.get(f"{world.base}/exam-sessions/me?active=false", headers=s1.headers)
    assert history.json()["items"][0]["timer"]["status"] == "ENDED"
    assert (await client.post(f"{base}/end", headers=world.teacher.headers)).status_code == 200


async def test_time_up_is_reported_and_finalized(
    client: httpx.AsyncClient, world: World, fixed_clock: Clock
) -> None:
    session = await _running_exam(client, world)
    base = f"{world.base}/exam-sessions/{session['id']}"
    fixed_clock.advance(minutes=241)

    mine = (await client.get(f"{base}/me", headers=world.students[0].headers)).json()
    assert (mine["timer"]["status"], mine["timer"]["end_reason"]) == ("ENDED", "TIME_UP")
    assert mine["timer"]["remaining_seconds"] == 0
    stage = await client.put(
        f"{base}/me/stage", json={"stage": "DONE"}, headers=world.students[0].headers
    )
    assert stage.status_code == 409

    # 같은 반의 새 시험은 시작할 수 있다 (만료된 시험은 자동 종료 처리)
    second = await _running_exam(client, world)
    assert second["timer"]["status"] == "RUNNING"
    listing = await client.get(
        f"{world.base}/exam-sessions?status=ENDED", headers=world.teacher.headers
    )
    assert [s["id"] for s in listing.json()["items"]] == [session["id"]]


async def test_restore_state_across_devices(
    client: httpx.AsyncClient, world: World, fixed_clock: Clock
) -> None:
    session = await _running_exam(client, world)
    base = f"{world.base}/exam-sessions/{session['id']}"
    await client.put(f"{base}/me/stage", json={"stage": "FINAL"}, headers=world.students[0].headers)
    fixed_clock.advance(minutes=1)
    # 새로고침·다른 기기: 같은 API가 같은 상태를 돌려준다 (클라이언트 상태에 의존하지 않음)
    first = (await client.get(f"{base}/me", headers=world.students[0].headers)).json()
    second = (await client.get(f"{base}/me", headers=world.students[0].headers)).json()
    assert first == second
    assert first["me"]["current_stage"] == "FINAL"
    assert first["timer"]["ends_at"] == session["timer"]["ends_at"]


async def test_concurrent_start_and_stage_changes(client: httpx.AsyncClient, world: World) -> None:
    template = (await _template(client, world)).json()
    sessions = [
        (
            await client.post(
                f"{world.base}/exam-sessions",
                json={"template_id": template["id"], "class_id": world.class_id},
                headers=world.teacher.headers,
            )
        ).json()["id"]
        for _ in range(4)
    ]
    responses = await asyncio.gather(
        *[
            client.post(f"{world.base}/exam-sessions/{sid}/start", headers=world.teacher.headers)
            for sid in sessions
        ]
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [200, 409, 409, 409]
    assert all(
        r.json()["error"]["code"] == "EXAM_ALREADY_RUNNING"
        for r in responses
        if r.status_code == 409
    )
    running = next(r.json()["id"] for r in responses if r.status_code == 200)

    stages = ["PROGRESS", "FINAL", "DONE", "PROGRESS", "FINAL"]
    changes = await asyncio.gather(
        *[
            client.put(
                f"{world.base}/exam-sessions/{running}/me/stage",
                json={"stage": s},
                headers=world.students[0].headers,
            )
            for s in stages
        ]
    )
    assert all(r.status_code == 200 for r in changes)
    final = (
        await client.get(
            f"{world.base}/exam-sessions/{running}/me", headers=world.students[0].headers
        )
    ).json()
    assert final["me"]["current_stage"] in set(stages)
    assert final["me"]["progress_at"] and final["me"]["final_at"] and final["me"]["done_at"]


async def test_cancel_and_cross_academy_access(
    client: httpx.AsyncClient, world: World, build_world
) -> None:  # type: ignore[no-untyped-def]
    session = await _running_exam(client, world)
    other = await build_world("다른 학원", admin=world.admin)
    base = f"{world.base}/exam-sessions/{session['id']}"

    # 다른 학원 원장: A 학원 경로 404(비소속), 자기 학원 경로에 A 세션 ID도 404
    assert (await client.get(base, headers=other.owner.headers)).status_code == 404
    own_path = f"{other.base}/exam-sessions/{session['id']}"
    assert (await client.get(own_path, headers=other.owner.headers)).status_code == 404
    assert (await client.post(f"{own_path}/end", headers=other.owner.headers)).status_code == 404
    assert (
        await client.get(f"{own_path}/me", headers=other.students[0].headers)
    ).status_code == 404
    template_path = f"{other.base}/exam-templates/{session['template_id']}"
    assert (await client.get(template_path, headers=other.owner.headers)).status_code == 404
    cross_class = await client.post(
        f"{other.base}/exam-sessions",
        json={"template_id": session["template_id"], "class_id": world.class_id},
        headers=other.owner.headers,
    )
    assert cross_class.status_code == 404

    # 진행 중 시험은 취소 불가, 예정 시험은 취소 가능
    assert (await client.delete(base, headers=world.teacher.headers)).status_code == 409
    scheduled = await client.post(
        f"{world.base}/exam-sessions",
        json={"template_id": session["template_id"], "class_id": world.class_id},
        headers=world.teacher.headers,
    )
    cancel_path = f"{world.base}/exam-sessions/{scheduled.json()['id']}"
    assert (await client.delete(cancel_path, headers=world.teacher.headers)).status_code == 204
    assert (
        await client.post(f"{cancel_path}/start", headers=world.teacher.headers)
    ).status_code == 409

    # 목록: 담당 강사 2건, 비담당 강사 0건
    assert (await client.get(f"{world.base}/exam-sessions", headers=world.teacher.headers)).json()[
        "total"
    ] == 2
    assert (
        await client.get(f"{world.base}/exam-sessions", headers=world.other_teacher.headers)
    ).json()["total"] == 0
