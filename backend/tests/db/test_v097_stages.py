"""v0.9.7 사용자 정의 작품 단계 · 단계별 피드백 · 피드백 반영 수정 사진.

- 단계: 1개 / 5개 이상 / 이름 변경 / 순서 변경 / 사진이 있는 단계 삭제(숨김·복원)
  / 시험 모드 목표 시간
- 피드백: 단계 피드백과 작품 전체 피드백 분리, 녹음·글 첨삭 모두, 단계 변경
- 수정 사진: 피드백 전 단계 사진 → 피드백 → 수정 사진(여러 장), 대표 사진 불가, 다른 단계 거부
- STT·AI 요약 후에도 단계 연결 유지, 성장 분석에 그대로 반영
- 접근 권한: 다른 학생의 단계·이력·피드백 연결 불가
- 기존 데이터 호환: 0013 → 0014 마이그레이션이 기존 사진을 같은 단계로 옮기고
  피드백은 작품 전체로 유지
"""

from __future__ import annotations

import uuid

import asyncpg
import httpx
import pytest

from app.worker.runner import JobRunner
from tests.db.conftest import Actor
from tests.db.test_migrations import _asyncpg_dsn
from tests.db.test_migrations_v051 import _alembic
from tests.db.test_recordings_api import _consent, _record
from tests.db.test_v09_learning_cycle import Ai, _ai_consent, note_ai_json
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt
from tests.fake_storage import FakeStorage, image_bytes

API = "/api/v1"
NOTE = (
    "구도는 화면 중앙에 안정적으로 잘 잡았다. 오른쪽 컵의 명암이 너무 약해서 형태가 떠 보인다. "
    "어두운 면을 한 톤 더 눌러서 덩어리감을 살려라.\n시간 안에 배경까지 마무리하지 못했다."
)


@pytest.fixture
def storage(app) -> FakeStorage:  # type: ignore[no-untyped-def]
    return app.state.storage


@pytest.fixture
def ai(app, client) -> Ai:  # type: ignore[no-untyped-def]
    stt, llm = FakeStt(), FakeLlm()
    runner = JobRunner(
        app.state.database,
        app.state.settings,
        stt=stt,
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="w-v097",
    )
    return Ai(runner, stt, llm)


async def _artwork(client: httpx.AsyncClient, owner: Actor, **body) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"{API}/artworks", json={"title": "단계 작품"} | body, headers=owner.headers
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _detail(client: httpx.AsyncClient, owner: Actor, artwork_id: str) -> dict:
    response = await client.get(f"{API}/artworks/{artwork_id}", headers=owner.headers)
    assert response.status_code == 200, response.text
    return response.json()


_COLORS = iter(["red", "green", "blue", "yellow", "purple", "orange", "white", "black"] * 20)
_SEQ = iter(range(1, 10_000))


async def _photo(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, storage: FakeStorage, owner: Actor, artwork_id: str, **body
) -> httpx.Response:
    """업로드 요청 → Storage에 올림 → 완료. 사진마다 내용이 달라야 한다 (중복 거부)."""
    payload = image_bytes("PNG", color=next(_COLORS), size=(16 + next(_SEQ), 16))
    ticket = await client.post(
        f"{API}/artworks/{artwork_id}/photos",
        json={"content_type": "image/png", "file_size": len(payload)} | body,
        headers=owner.headers,
    )
    if ticket.status_code != 201:
        return ticket
    storage.put(ticket.json()["upload"]["path"], payload)
    return await client.post(
        f"{API}/artworks/{artwork_id}/photos/{ticket.json()['photo']['id']}/complete",
        headers=owner.headers,
    )


async def _put_stages(client, owner: Actor, artwork_id: str, stages: list) -> httpx.Response:  # type: ignore[no-untyped-def]
    return await client.put(
        f"{API}/artworks/{artwork_id}/stages", json={"stages": stages}, headers=owner.headers
    )


async def _note(client, owner: Actor, artwork_id: str, **body) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"{API}/artworks/{artwork_id}/feedback-notes",
        json={"source": "INSTRUCTOR", "body": NOTE} | body,
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _history(client, owner: Actor, artwork_id: str) -> dict:  # type: ignore[no-untyped-def]
    response = await client.get(f"{API}/artworks/{artwork_id}/stage-history", headers=owner.headers)
    assert response.status_code == 200, response.text
    return response.json()


# ============================================================================ 단계 설정


async def test_default_one_and_many_stages(client: httpx.AsyncClient, actors, storage) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    default = await _artwork(client, student)
    assert [s["name"] for s in default["stage_plan"]] == ["스케치", "채색", "완성"]
    assert [s["legacy_stage"] for s in default["stage_plan"]] == ["SKETCH", "PROGRESS", "FINAL"]

    # 단계 1개: 그 단계가 완성 단계 → 사진 1장으로 작품 완료 가능
    single = await _artwork(client, student, stages=[{"name": "한 번에 완성"}])
    assert [(s["name"], s["legacy_stage"]) for s in single["stage_plan"]] == [
        ("한 번에 완성", "FINAL")
    ]
    stage_id = single["stage_plan"][0]["id"]
    photo = await _photo(client, storage, student, single["id"], stage_id=stage_id)
    assert photo.status_code == 200, photo.text
    assert photo.json()["stage_id"] == stage_id and photo.json()["is_representative"] is True
    done = await client.post(f"{API}/artworks/{single['id']}/complete", headers=student.headers)
    assert done.status_code == 200, done.text

    # 단계 7개 (5개 이상)
    names = ["아이디어", "구도", "스케치", "밑색", "묘사", "배경", "마무리"]
    many = await _artwork(client, student, stages=[{"name": n} for n in names])
    plan = many["stage_plan"]
    assert [s["name"] for s in plan] == names and [s["position"] for s in plan] == list(range(7))
    assert [s["legacy_stage"] for s in plan] == ["SKETCH"] + ["PROGRESS"] * 5 + ["FINAL"]
    for stage in plan[:3]:
        assert (
            await _photo(client, storage, student, many["id"], stage_id=stage["id"])
        ).status_code == 200
    detail = await _detail(client, student, many["id"])
    assert [p["stage_id"] for p in detail["photos"]] == [s["id"] for s in plan[:3]]
    # 단계마다 대표 1장 (같은 legacy 단계 PROGRESS가 여러 단계여도)
    assert all(p["is_representative"] for p in detail["photos"])

    # 검증: 0개, 11개, 빈 이름, 31자, 같은 id 두 번
    for bad in (
        [],
        [{"name": f"단계{i}"} for i in range(11)],
        [{"name": "   "}],
        [{"name": "가" * 31}],
    ):
        assert (
            await client.post(
                f"{API}/artworks", json={"title": "x", "stages": bad}, headers=student.headers
            )
        ).status_code == 422
    dup = await _put_stages(client, student, many["id"], [{"id": plan[0]["id"], "name": "a"}] * 2)
    assert dup.status_code == 422


async def test_rename_reorder_add_and_delete_stage_keeps_data(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, storage
) -> None:
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    sketch, color, final = artwork["stage_plan"]
    photo = (await _photo(client, storage, student, artwork["id"], stage_id=color["id"])).json()
    assert photo["stage"] == "PROGRESS"

    # 이름 변경 + 순서 변경 + 새 단계 추가 → 위치에 맞춰 legacy 단계도 다시 계산
    changed = await _put_stages(
        client,
        student,
        artwork["id"],
        [
            {"id": color["id"], "name": "밑색 칠하기"},
            {"id": sketch["id"], "name": "스케치"},
            {"name": "묘사"},
            {"id": final["id"], "name": "완성"},
        ],
    )
    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert [s["name"] for s in body["stages"]] == ["밑색 칠하기", "스케치", "묘사", "완성"]
    assert body["stages"][0]["id"] == color["id"] and body["stages"][0]["legacy_stage"] == "SKETCH"
    assert body["archived_stage_ids"] == [] and body["deleted_stage_ids"] == []
    detail = await _detail(client, student, artwork["id"])
    assert detail["photos"][0]["stage_id"] == color["id"]
    assert detail["photos"][0]["stage"] == "SKETCH"  # 호환 값도 새 위치로

    # 사진이 있는 단계 삭제 → 숨김(사진 보존), 빈 단계 삭제 → 실제 삭제
    new_stage = body["stages"][2]
    removed = await _put_stages(
        client,
        student,
        artwork["id"],
        [{"id": sketch["id"], "name": "스케치"}, {"id": final["id"], "name": "완성"}],
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["archived_stage_ids"] == [color["id"]]
    assert removed.json()["deleted_stage_ids"] == [new_stage["id"]]
    detail = await _detail(client, student, artwork["id"])
    assert [s["name"] for s in detail["stage_plan"]] == ["스케치", "완성"]
    assert detail["photos"] == [] and detail["photo_count"] == 0  # 숨긴 단계의 사진은 목록에서 빠짐
    listed = (
        await client.get(f"{API}/artworks/{artwork['id']}/stages", headers=student.headers)
    ).json()
    assert [(s["name"], s["archived"]) for s in listed] == [
        ("스케치", False),
        ("완성", False),
        ("밑색 칠하기", True),
    ]
    history = await _history(client, student, artwork["id"])
    archived = history["stages"][-1]
    assert archived["stage"]["archived"] is True
    assert [p["id"] for p in archived["photos"]] == [photo["id"]]  # 사진은 그대로 남아 있음
    # 숨긴 단계에는 새 사진을 올릴 수 없다
    assert (
        await _photo(client, storage, student, artwork["id"], stage_id=color["id"])
    ).status_code == 422

    # 복원: id를 다시 넣으면 사진과 함께 돌아온다
    restored = await _put_stages(
        client,
        student,
        artwork["id"],
        [
            {"id": sketch["id"], "name": "스케치"},
            {"id": color["id"], "name": "채색"},
            {"id": final["id"], "name": "완성"},
        ],
    )
    assert restored.status_code == 200
    detail = await _detail(client, student, artwork["id"])
    assert [p["id"] for p in detail["photos"]] == [photo["id"]]
    assert detail["photos"][0]["is_representative"] is True

    # 다른 작품의 단계 id는 쓸 수 없다
    other = await _artwork(client, student)
    foreign = await _put_stages(
        client, student, artwork["id"], [{"id": other["stage_plan"][0]["id"], "name": "x"}]
    )
    assert foreign.status_code == 422
    assert (
        await _photo(client, storage, student, artwork["id"], stage_id=other["stage_plan"][0]["id"])
    ).status_code == 422


async def test_complete_requires_last_active_stage_photo(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, storage
) -> None:
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student, stages=[{"name": "스케치"}, {"name": "완성"}])
    first, last = artwork["stage_plan"]
    await _photo(client, storage, student, artwork["id"], stage_id=last["id"])
    # 완성 단계를 빼면(사진 있음 → 숨김) 남은 단계가 마지막 단계가 된다
    await _put_stages(client, student, artwork["id"], [{"id": first["id"], "name": "스케치"}])
    blocked = await client.post(f"{API}/artworks/{artwork['id']}/complete", headers=student.headers)
    assert blocked.status_code == 409  # 숨긴 단계의 사진은 완료 조건이 아님
    await _photo(client, storage, student, artwork["id"], stage_id=first["id"])
    done = await client.post(f"{API}/artworks/{artwork['id']}/complete", headers=student.headers)
    assert done.status_code == 200, done.text


async def test_exam_mode_custom_stage_targets(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    exam = await _artwork(
        client,
        student,
        work_category="MOCK_EXAM",
        stages=[
            {"name": "아이디어", "target_minutes": 20},
            {"name": "스케치", "target_minutes": 60},
            {"name": "채색", "target_minutes": 140},
            {"name": "정리", "target_minutes": 20},
            {"name": "검토", "target_minutes": 10},
        ],
    )
    assert [s["target_minutes"] for s in exam["stage_plan"]] == [20, 60, 140, 20, 10]
    assert exam["time_limit_minutes"] == 250  # 단계 목표 시간의 합
    plan = exam["stage_plan"]
    changed = await _put_stages(
        client,
        student,
        exam["id"],
        [
            {"id": plan[0]["id"], "name": "아이디어", "target_minutes": 30},
            {"id": plan[2]["id"], "name": "채색", "target_minutes": 150},
        ],
    )
    assert changed.status_code == 200
    assert [s["target_minutes"] for s in changed.json()["stages"]] == [30, 150]
    assert (await _detail(client, student, exam["id"]))["time_limit_minutes"] == 180
    # 직접 정한 제한 시간은 그대로
    fixed = await _artwork(
        client,
        student,
        work_category="MOCK_EXAM",
        time_limit_minutes=240,
        stages=[{"name": "a", "target_minutes": 10}],
    )
    assert fixed["time_limit_minutes"] == 240
    bad = await _put_stages(client, student, exam["id"], [{"name": "a", "target_minutes": 0}])
    assert bad.status_code == 422


# ============================================================ 단계별 피드백 · 수정 사진


async def test_stage_and_overall_feedback_with_revision_photos(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, storage
) -> None:
    student = await actors.signup("STUDENT")
    artwork = await _artwork(client, student)
    sketch, color, _ = artwork["stage_plan"]
    before = (await _photo(client, storage, student, artwork["id"], stage_id=sketch["id"])).json()

    stage_note = await _note(client, student, artwork["id"], stage_id=sketch["id"])
    overall_note = await _note(client, student, artwork["id"], source="SELF_NOTE", body="전체 톤")
    assert stage_note["stage_id"] == sketch["id"] and overall_note["stage_id"] is None
    assert (await _consent(client, student)).status_code in (200, 201)
    recorded = await _record(
        client, app.state.audio_storage, student, artwork["id"], stage_id=color["id"]
    )
    assert recorded.status_code == 200, recorded.text
    recording = recorded.json()
    assert recording["stage_id"] == color["id"]

    # 피드백 반영 수정 사진: 같은 피드백에 여러 장
    rev1 = await _photo(
        client,
        storage,
        student,
        artwork["id"],
        stage_id=sketch["id"],
        kind="REVISION",
        feedback_note_id=stage_note["id"],
    )
    assert rev1.status_code == 200, rev1.text
    assert rev1.json()["kind"] == "REVISION" and rev1.json()["is_representative"] is False
    rev2 = await _photo(
        client,
        storage,
        student,
        artwork["id"],
        stage_id=sketch["id"],
        kind="REVISION",
        feedback_note_id=stage_note["id"],
    )
    assert rev2.status_code == 200
    # 작품 전체 피드백의 수정 사진은 어느 단계에나
    rev3 = await _photo(
        client,
        storage,
        student,
        artwork["id"],
        stage_id=color["id"],
        kind="REVISION",
        feedback_note_id=overall_note["id"],
    )
    assert rev3.status_code == 200
    rev4 = await _photo(
        client,
        storage,
        student,
        artwork["id"],
        stage_id=color["id"],
        kind="REVISION",
        feedback_recording_id=recording["id"],
    )
    assert rev4.status_code == 200

    # 거부: 피드백 없음 / 둘 다 / 다른 단계 / 단계 사진에 피드백 / 수정 사진을 대표로
    for body, code in (
        ({"stage_id": sketch["id"], "kind": "REVISION"}, 422),
        (
            {
                "stage_id": sketch["id"],
                "kind": "REVISION",
                "feedback_note_id": stage_note["id"],
                "feedback_recording_id": recording["id"],
            },
            422,
        ),
        ({"stage_id": color["id"], "kind": "REVISION", "feedback_note_id": stage_note["id"]}, 422),
        ({"stage_id": sketch["id"], "feedback_note_id": stage_note["id"]}, 422),
        (
            {"stage_id": sketch["id"], "kind": "REVISION", "feedback_note_id": str(uuid.uuid4())},
            404,
        ),
    ):
        assert (await _photo(client, storage, student, artwork["id"], **body)).status_code == code
    # v0.9.8: 피드백 뒤에 올린 사진도 일반 단계 사진과 같다 (대표 지정 가능, 사진 수에 포함)
    photo_url = f"{API}/artworks/{artwork['id']}/photos"
    rep = await client.patch(
        f"{photo_url}/{rev1.json()['id']}",
        json={"is_representative": True},
        headers=student.headers,
    )
    assert rep.status_code == 200 and rep.json()["is_representative"] is True
    back = await client.patch(
        f"{photo_url}/{before['id']}", json={"is_representative": True}, headers=student.headers
    )
    assert back.status_code == 200

    detail = await _detail(client, student, artwork["id"])
    assert detail["photo_count"] == 5  # 단계 사진 1 + 피드백 뒤 사진 4 (같은 사진으로 셈)
    reps = [p["id"] for p in detail["photos"] if p["is_representative"]]
    assert sorted(reps) == sorted([before["id"], rev3.json()["id"]])  # 단계마다 대표 1장
    assert len(detail["photos"]) == 5

    history = await _history(client, student, artwork["id"])
    s0, s1, s2 = history["stages"]
    assert [p["id"] for p in s0["photos"]] == [before["id"]]
    assert [f["id"] for f in s0["feedback"]] == [stage_note["id"]]
    assert s0["feedback"][0]["type"] == "NOTE"
    assert [p["id"] for p in s0["feedback"][0]["revisions"]] == [
        rev1.json()["id"],
        rev2.json()["id"],
    ]
    assert s0["feedback"][0]["revision_count"] == 2 and s0["revision_count"] == 2
    assert [f["id"] for f in s1["feedback"]] == [recording["id"]]
    assert s1["feedback"][0]["revisions"][0]["id"] == rev4.json()["id"]
    assert s1["revision_count"] == 2  # rev3(전체 피드백) + rev4
    assert s2["feedback"] == [] and s2["photos"] == []
    assert [f["id"] for f in history["overall_feedback"]] == [overall_note["id"]]
    assert history["overall_feedback"][0]["revisions"][0]["id"] == rev3.json()["id"]

    # 피드백 단계 변경: 수정 사진이 다른 단계에 있으면 거부, 작품 전체로는 허용
    moved = await client.patch(
        f"{API}/feedback-notes/{stage_note['id']}",
        json={"version": stage_note["version"], "stage_id": color["id"]},
        headers=student.headers,
    )
    assert moved.status_code == 422
    to_overall = await client.patch(
        f"{API}/feedback-notes/{stage_note['id']}",
        json={"version": stage_note["version"], "stage_id": None},
        headers=student.headers,
    )
    assert to_overall.status_code == 200 and to_overall.json()["stage_id"] is None
    rec_base = f"{API}/artworks/{artwork['id']}/recordings/{recording['id']}"
    assert (
        await client.patch(rec_base, json={"stage_id": sketch["id"]}, headers=student.headers)
    ).status_code == 422
    rec_overall = await client.patch(rec_base, json={"stage_id": None}, headers=student.headers)
    assert rec_overall.status_code == 200 and rec_overall.json()["stage_id"] is None

    # 피드백을 지워도 수정 사진은 남는다 (연결만 끊김)
    assert (
        await client.delete(f"{API}/feedback-notes/{overall_note['id']}", headers=student.headers)
    ).status_code == 204
    history = await _history(client, student, artwork["id"])
    assert [p["id"] for p in history["stages"][1]["unlinked_revisions"]] == [rev3.json()["id"]]

    # 수정 사진이 있는 단계는 빼도 숨김 (데이터 보존)
    kept = await _put_stages(client, student, artwork["id"], [{"name": "새 단계"}])
    assert set(kept.json()["archived_stage_ids"]) == {sketch["id"], color["id"]}


async def test_stt_and_ai_summary_keep_stage_and_growth(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    artwork = await _artwork(client, student, practical_type="DRAWING")
    sketch = artwork["stage_plan"][0]

    # 녹음 → STT: 단계 연결 유지
    assert (await _consent(client, student)).status_code in (200, 201)
    audio = app.state.audio_storage
    recording = (await _record(client, audio, student, artwork["id"], stage_id=sketch["id"])).json()
    base = f"{API}/artworks/{artwork['id']}/recordings/{recording['id']}"
    assert (await client.post(f"{base}/transcription", headers=student.headers)).status_code == 202
    assert await ai.drain() == 1
    after = (await client.get(base, headers=student.headers)).json()
    assert after["stage_id"] == sketch["id"] and after["transcription_status"] == "COMPLETED"

    # 단계 글 첨삭 → AI 요약 → 확정: 요약에 단계 정보, 성장 분석에 반영
    note = await _note(client, student, artwork["id"], stage_id=sketch["id"])
    note_url = f"{API}/feedback-notes/{note['id']}"
    queued = await client.post(f"{note_url}/summary", headers=student.headers)
    assert queued.status_code == 202, queued.text
    ai.llm.outcomes.append(note_ai_json())
    assert await ai.drain() == 1
    current = (await client.get(note_url, headers=student.headers)).json()
    feedback = (
        await client.get(f"{API}/feedbacks/{current['feedback_id']}", headers=student.headers)
    ).json()
    assert (feedback["stage_id"], feedback["stage_name"]) == (sketch["id"], "스케치")
    approved = await client.post(
        f"{API}/feedbacks/{current['feedback_id']}/approve",
        json={"version": feedback["version"]},
        headers=student.headers,
    )
    assert approved.status_code == 200, approved.text
    archive = (
        await client.get(f"{API}/artworks/{artwork['id']}/feedbacks", headers=student.headers)
    ).json()
    assert archive[0]["stage_name"] == "스케치"
    history = await _history(client, student, artwork["id"])
    entries = {f["id"]: f for f in history["stages"][0]["feedback"]}
    assert entries[note["id"]]["ai_feedback_status"] == "APPROVED"
    assert entries[recording["id"]]["transcription_status"] == "COMPLETED"

    # 성장 분석: 단계 피드백도 약점별 과거 첨삭에 그대로 들어간다
    past = (
        await client.get(f"{API}/growth/me/weaknesses/VALUE/feedbacks", headers=student.headers)
    ).json()
    assert past["total"] >= 1


async def test_stage_access_control(client: httpx.AsyncClient, actors, storage) -> None:  # type: ignore[no-untyped-def]
    owner = await actors.signup("STUDENT")
    other = await actors.signup("STUDENT")
    teacher = await actors.signup("INSTRUCTOR")
    artwork = await _artwork(client, owner)
    stage = artwork["stage_plan"][0]
    note = await _note(client, owner, artwork["id"], stage_id=stage["id"])
    for actor, code in ((other, 404), (teacher, 403)):
        assert (
            await client.get(f"{API}/artworks/{artwork['id']}/stages", headers=actor.headers)
        ).status_code == code
        assert (
            await client.get(f"{API}/artworks/{artwork['id']}/stage-history", headers=actor.headers)
        ).status_code == code
        assert (
            await _put_stages(client, actor, artwork["id"], [{"name": "탈취"}])
        ).status_code == code
    # 다른 학생이 자기 작품에 남의 피드백·단계를 연결할 수 없다
    mine = await _artwork(client, other)
    assert (
        await _photo(
            client,
            storage,
            other,
            mine["id"],
            stage_id=mine["stage_plan"][0]["id"],
            kind="REVISION",
            feedback_note_id=note["id"],
        )
    ).status_code == 404
    foreign_stage = await client.post(
        f"{API}/artworks/{mine['id']}/feedback-notes",
        json={"source": "SELF_NOTE", "body": "메모", "stage_id": stage["id"]},
        headers=other.headers,
    )
    assert foreign_stage.status_code == 422


# ================================================================ 기존 데이터 (0013 → 0014)


async def test_0014_moves_existing_photos_and_keeps_feedback(migrated_database: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(migrated_database))
    user, artwork = uuid.uuid4(), uuid.uuid4()
    photos = {code: uuid.uuid4() for code in ("SKETCH", "PROGRESS", "FINAL")}
    extra = uuid.uuid4()
    note = uuid.uuid4()
    try:
        _alembic("downgrade", "0013")
        await conn.execute(
            "INSERT INTO profiles (id, display_name, user_type) VALUES ($1, '학생', 'STUDENT')",
            user,
        )
        await conn.execute(
            "INSERT INTO artworks (id, owner_id, title, work_date)"
            " VALUES ($1, $2, '기존 작품', current_date)",
            artwork,
            user,
        )
        for i, (code, photo_id) in enumerate([*photos.items(), ("SKETCH", extra)]):
            await conn.execute(
                "INSERT INTO artwork_photos (id, artwork_id, owner_id, stage, status,"
                " storage_path, content_type, upload_expires_at, is_representative)"
                " VALUES ($1, $2, $3, $4, 'PENDING', $5, 'image/png', now(), false)",
                photo_id,
                artwork,
                user,
                code,
                f"{user}/{artwork}/{i}.png",
            )
        await conn.execute(
            "INSERT INTO feedback_notes (id, artwork_id, owner_id, source, body, segments,"
            " segment_count, feedback_date) VALUES ($1, $2, $3, 'SELF_NOTE', '메모',"
            ' \'[{"index": 0, "text": "메모"}]\', 1,'
            " current_date)",
            note,
            artwork,
            user,
        )

        _alembic("upgrade", "0014")
        stages = await conn.fetch(
            "SELECT id, position, name, legacy_stage, archived_at FROM artwork_stages"
            " WHERE artwork_id = $1 ORDER BY position",
            artwork,
        )
        assert [(s["position"], s["name"], s["legacy_stage"]) for s in stages] == [
            (0, "스케치", "SKETCH"),
            (1, "중간 작업", "PROGRESS"),
            (2, "완성", "FINAL"),
        ]
        by_code = {s["legacy_stage"]: s["id"] for s in stages}
        rows = await conn.fetch(
            "SELECT id, stage, stage_id, kind FROM artwork_photos WHERE artwork_id = $1", artwork
        )
        assert len(rows) == 4  # 사진 손실 없음
        for row in rows:
            assert row["stage_id"] == by_code[row["stage"]] and row["kind"] == "STAGE"
        note_stage = await conn.fetchval("SELECT stage_id FROM feedback_notes WHERE id = $1", note)
        assert note_stage is None  # 기존 피드백은 작품 전체

        # 다른 작품의 단계에는 연결할 수 없다 (복합 FK)
        other_artwork = uuid.uuid4()
        await conn.execute(
            "INSERT INTO artworks (id, owner_id, title, work_date)"
            " VALUES ($1, $2, '다른 작품', current_date)",
            other_artwork,
            user,
        )
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "UPDATE feedback_notes SET stage_id = $1 WHERE id = $2", by_code["SKETCH"], note
            )
            await conn.execute(
                "UPDATE feedback_notes SET artwork_id = $1 WHERE id = $2", other_artwork, note
            )
        # 수정 사진 규칙
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "UPDATE artwork_photos SET feedback_note_id = $1 WHERE id = $2", note, extra
            )

        _alembic("downgrade", "0013")
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM artwork_photos WHERE artwork_id = $1", artwork
            )
            == 4
        )
        _alembic("upgrade", "head")
        assert "No new upgrade operations detected" in _alembic("check")
    finally:
        _alembic("upgrade", "head")
        await conn.execute("DELETE FROM profiles WHERE id = $1", user)
        await conn.close()
