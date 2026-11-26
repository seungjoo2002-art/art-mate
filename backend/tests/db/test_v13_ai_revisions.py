"""v1.3 AI 시각적 첨삭 (AI 수정본) 통합 테스트.

이미지 수정 API는 가짜 구현 (실제 호출·비용 없음).

- 개선사항: 지금 사진에 연결된 같은 단계 피드백의 AI 정리(부족한 점·수정 방법)만, 시간 관리 제외
- 동의(VISUAL_CRITIQUE)·한도(개인 일·월, 서비스)·중복 요청 재사용·동시 요청 1건
- Worker 결과는 DB 임시 저장(STORING) → 학생 조회 때 학생 토큰으로 Storage 저장
  (실패하면 저장만 재시도)
- 자동 재시도는 일시적 오류만, 처리 여부가 불분명하면 재호출하지 않음
- 사진 교체·삭제, 작품 삭제, 동의 철회, 다른 사용자 접근 차단, 실제 작품 데이터와 분리
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
import pytest

from app.integrations.ai.openai_image import ImageEditError
from app.worker.runner import JobRunner
from tests.db.conftest import Actor
from tests.db.test_photo_replace_refs import _replace
from tests.db.test_v09_learning_cycle import note_ai_json
from tests.db.test_v098_timeline_refs import _photo, _sql
from tests.fake_ai import FakeFetcher, FakeImageEditor, FakeLlm, FakeStt
from tests.fake_storage import FakeStorage

API = "/api/v1"
VISUAL_VERSION = "2026-12-visual-v1"
AI_VERSION = "2026-12-ai-v2"
NOTE_TEXT = (
    "구도는 화면 중앙에 안정적으로 잘 잡았다. 오른쪽 컵의 명암이 너무 약해서 형태가 떠 보인다. "
    "어두운 면을 한 톤 더 눌러서 덩어리감을 살려라.\n시간 안에 배경까지 마무리하지 못했다."
)


@dataclass
class World:
    runner: JobRunner
    editor: FakeImageEditor
    llm: FakeLlm
    storage: FakeStorage
    revisions: FakeStorage

    async def drain(self, limit: int = 10) -> int:
        count = 0
        while count < limit and await self.runner.run_once():
            count += 1
        return count


@pytest.fixture
def world(app, client) -> World:  # type: ignore[no-untyped-def]
    editor, llm = FakeImageEditor(), FakeLlm()
    runner = JobRunner(
        app.state.database,
        app.state.settings,
        stt=FakeStt(),
        llm=llm,
        fetcher=FakeFetcher(app.state.storage),
        worker_id="w-v13",
        image_editor=editor,
    )
    return World(runner, editor, llm, app.state.storage, app.state.revision_storage)


async def _consent(client, student: Actor, purpose: str, version: str) -> None:  # type: ignore[no-untyped-def]
    granted = await client.post(
        f"{API}/ai-processing-consents",
        json={
            "policy_version": version,
            "agreed": True,
            "birth_year_month": "2000-01",
            "purpose": purpose,
        },
        headers=student.headers,
    )
    assert granted.status_code == 201, granted.text


async def _setup(client, world: World, student: Actor) -> dict:  # type: ignore[no-untyped-def]
    """작품 + 스케치 사진 2장 + 사진별 피드백(AI 정리) + 단계 공통·작품 전체·다른 단계 피드백."""
    await _consent(client, student, "FEEDBACK_SUMMARY", AI_VERSION)
    created = await client.post(
        f"{API}/artworks",
        json={"title": "정물 소묘", "practical_type": "DRAWING", "topic": "유리병과 사과"},
        headers=student.headers,
    )
    assert created.status_code == 201, created.text
    artwork = created.json()
    sketch, color, _ = artwork["stage_plan"]
    p1 = await _photo(client, world.storage, student, artwork["id"], stage_id=sketch["id"])
    p2 = await _photo(client, world.storage, student, artwork["id"], stage_id=sketch["id"])

    async def note(
        photo_ids: list[str] | None, stage_id: str | None, ai: str, extra: str = ""
    ) -> dict:
        body = {"source": "INSTRUCTOR", "body": NOTE_TEXT + extra}
        if stage_id:
            body["stage_id"] = stage_id
        if photo_ids is not None:
            body |= {"reference_photo_ids": photo_ids, "reference_confirmed": True}
        made = await client.post(
            f"{API}/artworks/{artwork['id']}/feedback-notes", json=body, headers=student.headers
        )
        assert made.status_code == 201, made.text
        queued = await client.post(
            f"{API}/feedback-notes/{made.json()['id']}/summary", headers=student.headers
        )
        assert queued.status_code == 202, queued.text
        world.llm.outcomes.append(ai)
        assert await world.drain() == 1
        return made.json()

    n1 = await note([p1["id"]], sketch["id"], note_ai_json())
    n1_dup = await note(
        [p1["id"]],
        sketch["id"],
        note_ai_json(
            weaknesses=[
                {
                    "text": "오른쪽 컵의 명암이 약해 형태가 떠 보인다",
                    "category": "VALUE",
                    "evidence": [1],
                },
                {"text": "사과의 비례가 어색하다.", "category": "PROPORTION", "evidence": [4]},
            ],
            fixes=[],
            weakness_categories=["VALUE", "PROPORTION"],
        ),
        extra=" 사과의 비례가 어색하다.",
    )
    n2 = await note(
        [p2["id"]],
        sketch["id"],
        note_ai_json(
            weaknesses=[
                {"text": "유리병 입구 타원이 납작하다.", "category": "FORM", "evidence": [4]}
            ],
            fixes=[],
            weakness_categories=["FORM"],
        ),
        extra=" 유리병 입구 타원이 납작하다.",
    )
    common = await note([], sketch["id"], note_ai_json())  # 단계 공통 (사진 없음)
    overall = await note([p1["id"]], None, note_ai_json())  # 작품 전체
    other = await note(None, color["id"], note_ai_json())  # 다른 단계
    return {
        "artwork": artwork,
        "sketch": sketch,
        "color": color,
        "p1": p1,
        "p2": p2,
        "notes": [n1, n1_dup, n2, common, overall, other],
    }


async def _candidates(client, student: Actor, artwork_id: str, photo_id: str) -> dict:  # type: ignore[no-untyped-def]
    got = await client.get(
        f"{API}/artworks/{artwork_id}/photos/{photo_id}/ai-revision-candidates",
        headers=student.headers,
    )
    assert got.status_code == 200, got.text
    return got.json()


async def _create(client, student: Actor, artwork_id: str, photo_id: str, keys: list[str]):  # type: ignore[no-untyped-def]
    return await client.post(
        f"{API}/artworks/{artwork_id}/photos/{photo_id}/ai-revisions",
        json={"selected_keys": keys},
        headers=student.headers,
    )


# ============================================================================ 기본 흐름


async def test_full_flow_candidates_consent_generation_and_storage(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT", name="홍길동")
    s = await _setup(client, world, student)
    artwork_id, p1, p2 = s["artwork"]["id"], s["p1"], s["p2"]

    # 사진 1: 사진 1 피드백 2개의 부족한 점·수정 방법만 (시간 관리 제외, 같은 문장은 하나로)
    c1 = await _candidates(client, student, artwork_id, p1["id"])
    texts = [(c["category"], c["kind"], c["text"]) for c in c1["candidates"]]
    assert texts == [
        ("PROPORTION", "WEAKNESS", "사과의 비례가 어색하다."),
        ("VALUE", "WEAKNESS", "오른쪽 컵의 명암이 약해 형태가 떠 보인다."),
        ("VALUE", "FIX", "어두운 면을 한 톤 더 눌러 덩어리감을 살린다."),
    ]
    merged = next(
        c for c in c1["candidates"] if c["kind"] == "WEAKNESS" and c["category"] == "VALUE"
    )
    assert len(merged["sources"]) == 2  # 중복 통합
    assert c1["feedback_count"] == 2 and c1["unsummarized_count"] == 0
    assert c1["consent_valid"] is False and c1["feature_status"] == "ENABLED"
    assert c1["latest"] is None and c1["revision_count"] == 0
    assert c1["quota"] == {
        "daily_used": 0,
        "daily_limit": 3,
        "monthly_used": 0,
        "monthly_limit": 20,
        "can_create": True,
        "blocked_scope": None,
    }
    # 사진 2: 사진 2 피드백만 (다른 사진·단계 공통·작품 전체·다른 단계 피드백 제외)
    c2 = await _candidates(client, student, artwork_id, p2["id"])
    assert [c["text"] for c in c2["candidates"]] == ["유리병 입구 타원이 납작하다."]

    keys = [c["key"] for c in c1["candidates"] if c["category"] == "VALUE"]
    # 동의 전
    blocked = await _create(client, student, artwork_id, p1["id"], keys)
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "AI_CONSENT_REQUIRED"
    assert blocked.json()["error"]["details"]["purpose"] == "VISUAL_CRITIQUE"
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    status = (
        await client.get(
            f"{API}/ai-processing-consents/me?purpose=VISUAL_CRITIQUE", headers=student.headers
        )
    ).json()
    assert status["is_valid"] is True and status["provider"] == "OPENAI"

    # 동시에 여러 번 눌러도 1건 (첫 응답 202, 나머지는 같은 수정본 200)
    responses = await asyncio.gather(
        *(_create(client, student, artwork_id, p1["id"], keys) for _ in range(3))
    )
    assert sorted(r.status_code for r in responses) == [200, 200, 202]
    ids = {r.json()["id"] for r in responses}
    assert len(ids) == 1
    revision = responses[0].json()
    assert revision["status"] == "QUEUED" and revision["version"] == 1
    assert revision["is_ai_generated"] is True
    assert [i["text"] for i in revision["improvements"]] == [
        "오른쪽 컵의 명암이 약해 형태가 떠 보인다.",
        "어두운 면을 한 톤 더 눌러 덩어리감을 살린다.",
    ]
    jobs = await _sql(app, "SELECT count(*) FROM ai_processing_jobs WHERE job_type='IMAGE_REVISE'")
    assert jobs[0][0] == 1

    # Worker: 이미지 수정 1번, 결과는 DB 임시 저장 (Storage에는 아직 없음)
    assert await world.drain() == 1
    assert len(world.editor.calls) == 1
    call = world.editor.calls[0]
    prompt = call["prompt"]
    assert "어두운 면을 한 톤 더 눌러 덩어리감을 살린다." in prompt
    assert "현재 작업 단계: 스케치" in prompt and "원본에 없던 채색을 추가하지 마십시오." in prompt
    assert "유리병과 사과" in prompt and "소묘" in prompt
    assert "사과의 비례가 어색하다." not in prompt  # 고르지 않은 개선사항은 보내지 않음
    assert "홍길동" not in prompt and "시간 안에" not in prompt
    assert len(call["images"]) == 1 and call["user_key"] == str(student.user_id)
    row = (
        await _sql(
            app,
            "SELECT status, result_staging IS NOT NULL, api_call_count, input_tokens, "
            "output_tokens, estimated_cost_usd, storage_path FROM artwork_ai_revisions",
        )
    )[0]
    assert row[0] == "STORING" and row[1] is True and row[2] == 1
    assert (row[3], row[4]) == (1500, 1400)
    assert float(row[5]) == pytest.approx((300 * 5 + 1200 * 8 + 1400 * 30) / 1_000_000)
    assert not world.revisions.objects
    # 알림
    notes = (await client.get(f"{API}/notifications", headers=student.headers)).json()
    ready = [n for n in notes["items"] if n["type"] == "AI_REVISION_READY"]
    assert len(ready) == 1 and ready[0]["ai_revision_id"] == revision["id"]

    # 학생 조회 → 학생 토큰으로 Storage 저장, 임시 이미지 삭제, URL
    got = await client.get(f"{API}/ai-revisions/{revision['id']}", headers=student.headers)
    assert got.status_code == 200, got.text
    done = got.json()
    assert done["status"] == "SUCCEEDED" and done["url"] and done["width"] == 48
    assert row[6] in world.revisions.objects
    uploads = [c for c in world.revisions.calls if c[0] == "upload"]
    assert len(uploads) == 1 and uploads[0][2] == student.headers["Authorization"].split()[1]
    staged = await _sql(
        app, "SELECT result_staging IS NULL, delivered_at IS NOT NULL FROM artwork_ai_revisions"
    )
    assert staged[0] == (True, True)
    assert done["timings"]["total_ms"] is not None and done["timings"]["generation_ms"] is not None

    # 같은 요청 다시 → 기존 결과 (API 재호출·한도 차감 없음)
    again = await _create(client, student, artwork_id, p1["id"], list(reversed(keys)))
    assert again.status_code == 200 and again.json()["id"] == revision["id"]
    await world.drain()
    assert len(world.editor.calls) == 1

    # 다른 선택 → 새 버전
    other = await _create(client, student, artwork_id, p1["id"], keys[:1])
    assert other.status_code == 202 and other.json()["version"] == 2

    # 아카이브 버튼 개수 (완성 1, 진행 중 1), 단계 수정본 목록 (최신 먼저)
    summary = (
        await client.get(
            f"{API}/artworks/{artwork_id}/ai-revisions/summary", headers=student.headers
        )
    ).json()
    assert summary["stages"] == [{"stage_id": s["sketch"]["id"], "count": 1, "in_progress": 1}]
    listed = (
        await client.get(
            f"{API}/artworks/{artwork_id}/stages/{s['sketch']['id']}/ai-revisions",
            headers=student.headers,
        )
    ).json()
    assert [r["version"] for r in listed["revisions"]] == [2, 1]
    assert listed["replaced_photos"] == []

    # 실제 작품 데이터와 분리: 사진 수·대표·목록 썸네일·단계 사진 그대로
    detail = (await client.get(f"{API}/artworks/{artwork_id}", headers=student.headers)).json()
    assert detail["photo_count"] == 2
    assert {p["id"] for p in detail["photos"]} == {p1["id"], p2["id"]}
    assert detail["cover_photo_id"] in {p1["id"], p2["id"]}
    history = (
        await client.get(f"{API}/artworks/{artwork_id}/stage-history", headers=student.headers)
    ).json()
    sketch_photos = next(st for st in history["stages"] if st["stage"]["id"] == s["sketch"]["id"])
    assert {p["id"] for p in sketch_photos["photos"]} == {p1["id"], p2["id"]}


async def test_other_users_cannot_see_or_touch_revisions(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    c1 = await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"])
    made = await _create(
        client, student, s["artwork"]["id"], s["p1"]["id"], [c1["candidates"][0]["key"]]
    )
    revision_id = made.json()["id"]

    stranger = await actors.signup("STUDENT")
    await _consent(client, stranger, "VISUAL_CRITIQUE", VISUAL_VERSION)
    for method, path in [
        ("GET", f"/ai-revisions/{revision_id}"),
        ("POST", f"/ai-revisions/{revision_id}/retry"),
        ("DELETE", f"/ai-revisions/{revision_id}"),
        ("GET", f"/artworks/{s['artwork']['id']}/ai-revisions/summary"),
        ("GET", f"/artworks/{s['artwork']['id']}/stages/{s['sketch']['id']}/ai-revisions"),
        ("GET", f"/artworks/{s['artwork']['id']}/photos/{s['p1']['id']}/ai-revision-candidates"),
    ]:
        response = await client.request(method, f"{API}{path}", headers=stranger.headers)
        assert response.status_code == 404, (method, path, response.text)
    hijack = await _create(client, stranger, s["artwork"]["id"], s["p1"]["id"], ["x"])
    assert hijack.status_code == 404
    # 강사 계정은 학생 전용 API를 쓸 수 없음
    teacher = await actors.signup("INSTRUCTOR")
    response = await client.get(f"{API}/ai-revisions/{revision_id}", headers=teacher.headers)
    assert response.status_code == 403


# ============================================================================ 실패·재시도·저장


async def test_storage_failure_retries_only_the_upload(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    c1 = await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"])
    made = (
        await _create(
            client, student, s["artwork"]["id"], s["p1"]["id"], [c1["candidates"][0]["key"]]
        )
    ).json()
    assert await world.drain() == 1

    world.revisions.fail.add("upload")
    first = (await client.get(f"{API}/ai-revisions/{made['id']}", headers=student.headers)).json()
    assert first["status"] == "STORING" and first["url"] is None
    row = (
        await _sql(
            app, "SELECT result_staging IS NOT NULL, storage_attempts FROM artwork_ai_revisions"
        )
    )[0]
    assert row == (True, 1)  # 임시 이미지 유지

    world.revisions.fail.clear()
    # 여러 조회가 동시에 와도 업로드는 1번
    results = await asyncio.gather(
        *(client.get(f"{API}/ai-revisions/{made['id']}", headers=student.headers) for _ in range(3))
    )
    assert all(r.status_code == 200 for r in results)
    final = (await client.get(f"{API}/ai-revisions/{made['id']}", headers=student.headers)).json()
    assert final["status"] == "SUCCEEDED" and final["url"]
    successful_uploads = [c for c in world.revisions.calls if c[0] == "upload"]
    assert len(successful_uploads) == 2  # 실패 1 + 성공 1
    assert len(world.editor.calls) == 1  # 이미지 수정 API는 다시 부르지 않음


async def test_transient_errors_retry_but_ambiguous_timeouts_do_not(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    keys = [
        c["key"]
        for c in (await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"]))[
            "candidates"
        ]
    ]

    # 1) 429 rate limit → 재시도 → 성공 (최대 2회)
    world.editor.outcomes.append(ImageEditError("IMAGE_RATE_LIMITED", "rate", retryable=True))
    first = (await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys[:1])).json()
    assert await world.drain() == 1
    queued = (await client.get(f"{API}/ai-revisions/{first['id']}", headers=student.headers)).json()
    assert queued["status"] == "QUEUED"
    await _sql(app, "UPDATE ai_processing_jobs SET run_after = now()")
    assert await world.drain() == 1
    assert len(world.editor.calls) == 2
    done = (await client.get(f"{API}/ai-revisions/{first['id']}", headers=student.headers)).json()
    assert done["status"] == "SUCCEEDED"
    usage = (
        await _sql(
            app, "SELECT api_call_count FROM artwork_ai_revisions WHERE id = :i", i=first["id"]
        )
    )[0]
    assert usage[0] == 2  # 실패한 호출도 기록

    # 2) 응답 대기 시간 초과 → 처리 여부 불분명 → 자동 재호출 없이 실패, 학생이 다시 만들 수 있음
    world.editor.outcomes.append(ImageEditError("IMAGE_RESULT_UNKNOWN", "timeout", retryable=False))
    second = (await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys[1:2])).json()
    assert await world.drain() == 1
    failed = (
        await client.get(f"{API}/ai-revisions/{second['id']}", headers=student.headers)
    ).json()
    assert failed["status"] == "FAILED" and failed["error_code"] == "IMAGE_RESULT_UNKNOWN"
    assert failed["retryable"] is True
    await _sql(app, "UPDATE ai_processing_jobs SET run_after = now()")
    assert await world.drain() == 0
    assert len(world.editor.calls) == 3

    # 3) 정책 오류 등은 재시도 안 함
    world.editor.outcomes.append(ImageEditError("IMAGE_BLOCKED", "policy", retryable=False))
    retried = await client.post(f"{API}/ai-revisions/{second['id']}/retry", headers=student.headers)
    assert retried.status_code == 202, retried.text
    assert retried.json()["version"] == 3
    assert await world.drain() == 1
    blocked = (
        await client.get(f"{API}/ai-revisions/{retried.json()['id']}", headers=student.headers)
    ).json()
    assert blocked["error_code"] == "IMAGE_BLOCKED"
    await _sql(app, "UPDATE ai_processing_jobs SET run_after = now()")
    assert await world.drain() == 0
    assert len(world.editor.calls) == 4


async def test_worker_lost_after_sending_is_not_resent(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    c1 = await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"])
    made = (
        await _create(
            client, student, s["artwork"]["id"], s["p1"]["id"], [c1["candidates"][0]["key"]]
        )
    ).json()
    # Worker가 요청을 보낸 직후 죽은 상태를 재현 (lease 만료)
    await _sql(
        app,
        "UPDATE ai_processing_jobs SET status='RUNNING', attempts=1, locked_by='dead', "
        "lease_expires_at = now() - interval '1 minute', started_at = now() "
        "WHERE job_type = 'IMAGE_REVISE'",
    )
    await _sql(
        app,
        "UPDATE artwork_ai_revisions SET status='RUNNING', "
        "api_started_at = now() - interval '2 minutes'",
    )
    assert await world.drain() == 1
    assert world.editor.calls == []
    read = (await client.get(f"{API}/ai-revisions/{made['id']}", headers=student.headers)).json()
    assert read["status"] == "FAILED" and read["error_code"] == "IMAGE_RESULT_UNKNOWN"


# ============================================================================ 한도·기능 꺼짐


async def test_limits_are_enforced_on_the_server(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    keys = [
        c["key"]
        for c in (await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"]))[
            "candidates"
        ]
    ]
    app.state.settings = app.state.settings.model_copy(update={"image_edit_daily_limit": 2})
    assert (
        await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys[:1])
    ).status_code == 202
    assert (
        await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys[1:2])
    ).status_code == 202
    limited = await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "AI_REVISION_LIMIT_REACHED"
    assert limited.json()["error"]["details"]["scope"] == "DAILY"
    assert "Retry-After" in limited.headers
    # 같은 요청 재사용은 한도와 무관
    reuse = await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys[:1])
    assert reuse.status_code == 200
    quota = (await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"]))["quota"]
    assert (
        quota["daily_used"] == 2
        and quota["can_create"] is False
        and quota["blocked_scope"] == "DAILY"
    )
    # 실제로 생성(API 호출)한 뒤에는 지워도 한도는 돌아오지 않음
    assert await world.drain() == 2
    rid = reuse.json()["id"]
    assert (
        await client.delete(f"{API}/ai-revisions/{rid}", headers=student.headers)
    ).status_code == 204
    assert (
        await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys)
    ).status_code == 429

    # 서비스 전체 월 예상 비용 한도
    app.state.settings = app.state.settings.model_copy(
        update={"image_edit_daily_limit": 0, "image_edit_service_monthly_budget_usd": 0.01}
    )
    service = await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys)
    assert service.status_code == 429 and service.json()["error"]["details"]["scope"] == "SERVICE"

    # 기능 꺼짐 → 생성 503, 조회는 상태만
    app.state.settings = app.state.settings.model_copy(update={"image_edit_enabled": False})
    off = await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys)
    assert off.status_code == 503 and off.json()["error"]["code"] == "AI_REVISION_DISABLED"
    c = await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"])
    assert c["feature_status"] == "DISABLED"
    features = (await client.get(f"{API}/meta/ai-features")).json()
    assert features["ai_revision_status"] == "DISABLED"


async def test_invalid_selection_and_missing_summary(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    changed = await _create(client, student, s["artwork"]["id"], s["p1"]["id"], ["not-a-key"])
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "AI_REVISION_CANDIDATES_CHANGED"
    empty = await _create(client, student, s["artwork"]["id"], s["p1"]["id"], [])
    assert empty.status_code == 422
    # AI 정리가 없는 피드백만 있는 사진 → 후보 없음, 정리 안내 수
    p3 = await _photo(
        client, world.storage, student, s["artwork"]["id"], stage_id=s["sketch"]["id"]
    )
    made = await client.post(
        f"{API}/artworks/{s['artwork']['id']}/feedback-notes",
        json={
            "source": "INSTRUCTOR",
            "body": NOTE_TEXT,
            "stage_id": s["sketch"]["id"],
            "reference_photo_ids": [p3["id"]],
            "reference_confirmed": True,
        },
        headers=student.headers,
    )
    assert made.status_code == 201
    c3 = await _candidates(client, student, s["artwork"]["id"], p3["id"])
    assert c3["candidates"] == [] and c3["feedback_count"] == 1 and c3["unsummarized_count"] == 1
    none = await _create(client, student, s["artwork"]["id"], p3["id"], ["x"])
    assert none.status_code == 422
    assert none.json()["error"]["code"] == "AI_REVISION_NO_IMPROVEMENTS"


# ================================================ 사진 교체·삭제, 작품 삭제, 동의 철회


async def test_photo_replacement_keeps_history_separate(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    artwork_id, p1 = s["artwork"]["id"], s["p1"]
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    c1 = await _candidates(client, student, artwork_id, p1["id"])
    made = (
        await _create(client, student, artwork_id, p1["id"], [c1["candidates"][0]["key"]])
    ).json()
    await world.drain()
    await client.get(f"{API}/ai-revisions/{made['id']}", headers=student.headers)
    p1_path = next(path for path in world.storage.objects if p1["id"] in path)

    new = await _replace(client, world.storage, student, artwork_id, p1, "orange")
    # 교체 전 원본 파일 유지 (비교용), 새 사진은 새 원본: 수정본·개선사항 없음
    assert p1_path in world.storage.objects
    fresh = await _candidates(client, student, artwork_id, new["id"])
    assert fresh["candidates"] == [] and fresh["latest"] is None and fresh["revision_count"] == 0
    listed = (
        await client.get(
            f"{API}/artworks/{artwork_id}/stages/{s['sketch']['id']}/ai-revisions",
            headers=student.headers,
        )
    ).json()
    old = listed["revisions"][0]
    assert old["photo_id"] == p1["id"]
    assert old["source_photo"] == {
        "photo_id": p1["id"],
        "photo_status": "DELETED",
        "replaced": True,
        "current_photo_id": new["id"],
    }
    assert old["retryable"] is False
    assert listed["replaced_photos"][0]["current_photo_id"] == new["id"]
    url = await client.get(
        f"{API}/artworks/{artwork_id}/photos/{p1['id']}/url", headers=student.headers
    )
    assert url.status_code == 200
    # 수정본 삭제는 원본 사진에 영향 없음 (피드백 기준 사진이라 파일도 유지)
    assert (
        await client.delete(f"{API}/ai-revisions/{old['id']}", headers=student.headers)
    ).status_code == 204
    assert p1_path in world.storage.objects
    detail = (await client.get(f"{API}/artworks/{artwork_id}", headers=student.headers)).json()
    assert detail["photo_count"] == 2


async def test_replaced_original_kept_only_for_revisions_is_released(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    artwork_id, p2 = s["artwork"]["id"], s["p2"]
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    c2 = await _candidates(client, student, artwork_id, p2["id"])
    made = (
        await _create(client, student, artwork_id, p2["id"], [c2["candidates"][0]["key"]])
    ).json()
    await world.drain()
    await client.get(f"{API}/ai-revisions/{made['id']}", headers=student.headers)
    # p2 피드백의 기준 사진 연결을 지워 '수정본만 참조' 상태로 만든다
    await _sql(app, "DELETE FROM feedback_image_refs WHERE photo_id = :p", p=p2["id"])
    p2_path = next(path for path in world.storage.objects if p2["id"] in path)
    await _replace(client, world.storage, student, artwork_id, p2, "green")
    assert p2_path in world.storage.objects  # 수정본 원본이라 유지
    assert (
        await client.delete(f"{API}/ai-revisions/{made['id']}", headers=student.headers)
    ).status_code == 204
    assert p2_path not in world.storage.objects  # 더는 참조가 없어 정리


async def test_photo_and_artwork_deletion_clean_up_revisions(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    artwork_id = s["artwork"]["id"]
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    c1 = await _candidates(client, student, artwork_id, s["p1"]["id"])
    done = (
        await _create(client, student, artwork_id, s["p1"]["id"], [c1["candidates"][0]["key"]])
    ).json()
    await world.drain()
    await client.get(f"{API}/ai-revisions/{done['id']}", headers=student.headers)
    assert len(world.revisions.objects) == 1
    queued = (
        await _create(client, student, artwork_id, s["p1"]["id"], [c1["candidates"][1]["key"]])
    ).json()

    # 원본 사진 삭제 → 그 자리 수정본 삭제·진행 중 작업 취소·파일 정리
    deleted = await client.delete(
        f"{API}/artworks/{artwork_id}/photos/{s['p1']['id']}", headers=student.headers
    )
    assert deleted.status_code == 204
    assert world.revisions.objects == {}
    rows = await _sql(
        app, "SELECT status, deleted_at IS NOT NULL FROM artwork_ai_revisions ORDER BY version"
    )
    assert rows == [("SUCCEEDED", True), ("CANCELLED", True)]
    job = await _sql(
        app, "SELECT status FROM ai_processing_jobs WHERE revision_id = :r", r=queued["id"]
    )
    assert job[0][0] == "CANCELLED"
    assert await world.drain() == 0
    assert len(world.editor.calls) == 1

    # 작품 삭제 → 남은 수정본 파일까지 정리
    c2 = await _candidates(client, student, artwork_id, s["p2"]["id"])
    other = (
        await _create(client, student, artwork_id, s["p2"]["id"], [c2["candidates"][0]["key"]])
    ).json()
    await world.drain()
    await client.get(f"{API}/ai-revisions/{other['id']}", headers=student.headers)
    assert len(world.revisions.objects) == 1
    assert (
        await client.delete(f"{API}/artworks/{artwork_id}", headers=student.headers)
    ).status_code == 204
    assert world.revisions.objects == {}
    gone = await client.get(f"{API}/ai-revisions/{other['id']}", headers=student.headers)
    assert gone.status_code == 404


async def test_consent_revocation_cancels_queued_generation(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    c1 = await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"])
    made = (
        await _create(
            client, student, s["artwork"]["id"], s["p1"]["id"], [c1["candidates"][0]["key"]]
        )
    ).json()
    revoked = await client.delete(
        f"{API}/ai-processing-consents/me?purpose=VISUAL_CRITIQUE", headers=student.headers
    )
    assert revoked.status_code == 204
    assert await world.drain() == 0
    read = (await client.get(f"{API}/ai-revisions/{made['id']}", headers=student.headers)).json()
    assert read["status"] == "CANCELLED" and read["error_code"] == "AI_CONSENT_REVOKED"
    assert world.editor.calls == []
    # 요약 동의는 그대로 (목적별 동의)
    summary = (await client.get(f"{API}/ai-processing-consents/me", headers=student.headers)).json()
    assert summary["is_valid"] is True


async def test_staged_results_expire_after_retention(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    c1 = await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"])
    made = (
        await _create(
            client, student, s["artwork"]["id"], s["p1"]["id"], [c1["candidates"][0]["key"]]
        )
    ).json()
    await world.drain()
    await _sql(app, "UPDATE artwork_ai_revisions SET staged_at = now() - interval '30 days'")
    await world.runner.maintenance()
    row = (
        await _sql(
            app, "SELECT status, error_code, result_staging IS NULL FROM artwork_ai_revisions"
        )
    )[0]
    assert row == ("FAILED", "RESULT_EXPIRED", True)
    read = (await client.get(f"{API}/ai-revisions/{made['id']}", headers=student.headers)).json()
    assert read["status"] == "FAILED" and read["retryable"] is True
    assert len(world.editor.calls) == 1


async def test_admin_usage(client: httpx.AsyncClient, actors, world: World) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    c1 = await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"])
    await _create(client, student, s["artwork"]["id"], s["p1"]["id"], [c1["candidates"][0]["key"]])
    await world.drain()
    admin = await actors.admin()
    usage = (await client.get(f"{API}/admin/ai-revisions/usage", headers=admin.headers)).json()
    assert usage["requests"] == 1 and usage["api_calls"] == 1 and usage["staged_results"] == 1
    assert usage["output_tokens"] == 1400 and float(usage["estimated_cost_usd"]) > 0
    denied = await client.get(f"{API}/admin/ai-revisions/usage", headers=student.headers)
    assert denied.status_code == 403


async def test_storage_read_rule_allows_only_kept_replaced_photos(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    """0017: 교체 후 남겨 둔 사진은 소유자가 읽고, 그냥 삭제한 사진은 여전히 읽을 수 없다."""
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    artwork_id, p1, p2 = s["artwork"]["id"], s["p1"], s["p2"]
    await _replace(client, world.storage, student, artwork_id, p1, "orange")  # 피드백 기준 → 보존
    deleted = await client.delete(
        f"{API}/artworks/{artwork_id}/photos/{p2['id']}", headers=student.headers
    )
    assert deleted.status_code == 204
    rows = await _sql(
        app,
        "SELECT id::text, storage_path FROM artwork_photos WHERE id IN (:a, :b)",
        a=p1["id"],
        b=p2["id"],
    )
    paths = dict(rows)
    # 정리가 끝난 상태(플래그 해제)를 재현해도 그냥 삭제한 사진은 읽기 불가
    await _sql(
        app, "UPDATE artwork_photos SET storage_cleanup_pending = false WHERE id = :b", b=p2["id"]
    )

    async def can(path: str) -> bool:
        found = await _sql(
            app,
            "SELECT artmate_private.can_access_artwork_object(CAST(:u AS uuid), :p, 'read')",
            u=str(student.user_id),
            p=path,
        )
        return bool(found[0][0])

    assert await can(paths[p1["id"]]) is True
    assert await can(paths[p2["id"]]) is False
    other = await actors.signup("STUDENT")
    found = await _sql(
        app,
        "SELECT artmate_private.can_access_artwork_object(CAST(:u AS uuid), :p, 'read')",
        u=str(other.user_id),
        p=paths[p1["id"]],
    )
    assert found[0][0] is False


# ================================================ 비용 제한 (v1.3 최종 검증)


async def test_service_budget_holds_under_concurrent_requests(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    """여러 학생이 동시에 요청해도 서비스 월 예산(진행 중 예상분 포함)을 넘는 생성은 받지 않는다."""
    # 1회 예상 0.12 → 예산 0.30이면 진행 중 2건까지만 (3번째는 0.36 > 0.30)
    app.state.settings = app.state.settings.model_copy(
        update={"image_edit_service_monthly_budget_usd": 0.30, "image_edit_service_daily_limit": 0}
    )
    students = [await actors.signup("STUDENT") for _ in range(5)]
    setups = []
    for student in students:
        s = await _setup(client, world, student)
        await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
        c = await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"])
        setups.append((student, s, c["candidates"][0]["key"]))
    responses = await asyncio.gather(
        *(_create(client, st, s["artwork"]["id"], s["p1"]["id"], [k]) for st, s, k in setups)
    )
    codes = sorted(r.status_code for r in responses)
    assert codes == [202, 202, 429, 429, 429], codes
    assert all(
        r.json()["error"]["details"]["scope"] == "SERVICE"
        for r in responses
        if r.status_code == 429
    )
    rows = await _sql(app, "SELECT count(*) FROM artwork_ai_revisions")
    assert rows[0][0] == 2


async def test_worker_rechecks_budget_and_records_unknown_cost(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    keys = [
        c["key"]
        for c in (await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"]))[
            "candidates"
        ]
    ]
    # 1) 응답 대기 초과(처리 여부 불분명): 재호출 없음 + 1회 예상 비용으로 기록
    world.editor.outcomes.append(ImageEditError("IMAGE_RESULT_UNKNOWN", "timeout", retryable=False))
    first = (await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys[:1])).json()
    assert await world.drain() == 1
    row = (
        await _sql(
            app,
            "SELECT status, api_call_count, estimated_cost_usd FROM artwork_ai_revisions "
            "WHERE id = :i",
            i=first["id"],
        )
    )[0]
    assert row[0] == "FAILED" and row[1] == 1 and float(row[2]) == pytest.approx(0.12)
    assert len(world.editor.calls) == 1

    # 2) 요청 뒤 실제 기록이 예산을 넘으면 Worker가 보내기 직전에 막는다 (호출 0)
    second = (await _create(client, student, s["artwork"]["id"], s["p1"]["id"], keys[1:2])).json()
    await _sql(
        app,
        "UPDATE artwork_ai_revisions SET estimated_cost_usd = 9.95 WHERE id = :i",
        i=first["id"],
    )
    assert await world.drain() == 1
    blocked = (
        await client.get(f"{API}/ai-revisions/{second['id']}", headers=student.headers)
    ).json()
    assert blocked["status"] == "FAILED" and blocked["error_code"] == "SERVICE_BUDGET_EXCEEDED"
    assert len(world.editor.calls) == 1
    usage = await _sql(
        app, "SELECT api_call_count FROM artwork_ai_revisions WHERE id = :i", i=second["id"]
    )
    assert usage[0][0] == 0


async def test_lost_worker_records_estimated_cost(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    student = await actors.signup("STUDENT")
    s = await _setup(client, world, student)
    await _consent(client, student, "VISUAL_CRITIQUE", VISUAL_VERSION)
    c1 = await _candidates(client, student, s["artwork"]["id"], s["p1"]["id"])
    made = (
        await _create(
            client, student, s["artwork"]["id"], s["p1"]["id"], [c1["candidates"][0]["key"]]
        )
    ).json()
    await _sql(
        app,
        "UPDATE ai_processing_jobs SET status='RUNNING', attempts=1, locked_by='dead', "
        "lease_expires_at = now() - interval '1 minute', started_at = now() "
        "WHERE job_type = 'IMAGE_REVISE'",
    )
    await _sql(app, "UPDATE artwork_ai_revisions SET status='RUNNING', api_started_at = now()")
    assert await world.drain() == 1
    row = (
        await _sql(
            app,
            "SELECT status, error_code, api_call_count, estimated_cost_usd "
            "FROM artwork_ai_revisions WHERE id = :i",
            i=made["id"],
        )
    )[0]
    assert row[:3] == ("FAILED", "IMAGE_RESULT_UNKNOWN", 1)
    assert float(row[3]) == pytest.approx(0.12)
    assert world.editor.calls == []


async def test_teen_visual_consent_requires_guardian(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, world: World
) -> None:
    """만 14~17세 작품 이미지 동의는 보호자 확인 전까지 무효 (OpenAI 약관 §3.3(c))."""
    app.state.settings = app.state.settings.model_copy(
        update={"ai_teens_enabled": True, "ai_teen_guardian_required": False}
    )
    teen = await actors.signup("STUDENT")
    year = __import__("datetime").date.today().year - 16
    granted = await client.post(
        f"{API}/ai-processing-consents",
        json={
            "policy_version": VISUAL_VERSION,
            "agreed": True,
            "birth_year_month": f"{year}-01",
            "purpose": "VISUAL_CRITIQUE",
        },
        headers=teen.headers,
    )
    assert granted.status_code == 201, granted.text
    body = granted.json()
    assert body["is_valid"] is False and body["reason"] == "GUARDIAN_PENDING"
    assert body["guardian_token"]
    assert body["consent"]["granted_by"] == "GUARDIAN"
    # 요약 동의는 기존 설정대로 (보호자 확인 요구 꺼짐 → 바로 유효)
    summary = await client.post(
        f"{API}/ai-processing-consents",
        json={"policy_version": AI_VERSION, "agreed": True, "birth_year_month": f"{year}-01"},
        headers=teen.headers,
    )
    assert summary.json()["is_valid"] is True
    # 보호자 확인 후 유효
    confirmed = await client.post(
        f"{API}/guardian-consents/confirm",
        json={
            "token": body["guardian_token"],
            "guardian_name": "보호자",
            "relationship": "PARENT",
            "agreed": True,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    status = (
        await client.get(
            f"{API}/ai-processing-consents/me?purpose=VISUAL_CRITIQUE", headers=teen.headers
        )
    ).json()
    assert status["is_valid"] is True
