"""v0.9 기능명세서 V2 1~2단계: 학원 없는 학생의 학습 사이클 (F-1~F-5, F-7).

학생 회원가입 → 학습 목표·지망 대학 → 작품(시간 기록·타이머) → 텍스트·음성 첨삭 → AI 요약(가짜 LLM)
→ 본인 확정 → 성장 분석(출처 구분·학습 시간) → 아카이브(약점별 과거 첨삭·작품 비교).
STT·Gemini는 가짜 구현, Worker는 테스트에서 직접 실행한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import text

from app.core import timezone as clock
from app.worker.runner import JobRunner
from tests.db.conftest import Actor, World
from tests.db.test_artworks_api import _upload
from tests.db.test_recordings_api import _consent, _record
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt, ai_json
from tests.fake_storage import FakeStorage

API = "/api/v1"
AI_VERSION = "2026-12-ai-v2"

NOTE_TEXT = (
    "구도는 화면 중앙에 안정적으로 잘 잡았다. 오른쪽 컵의 명암이 너무 약해서 형태가 떠 보인다. "
    "어두운 면을 한 톤 더 눌러서 덩어리감을 살려라.\n시간 안에 배경까지 마무리하지 못했다."
)


def note_ai_json(**overrides) -> str:  # type: ignore[no-untyped-def]
    """NOTE_TEXT 문장(0~3)에 근거한 가짜 AI 응답."""
    data = {
        "summary": "구도는 안정적이나 컵의 명암이 약하고 시간 안에 마무리하지 못했다.",
        "strengths": [
            {
                "text": "구도를 화면 중앙에 안정적으로 잡았다.",
                "category": "COMPOSITION",
                "evidence": [0],
            }
        ],
        "weaknesses": [
            {
                "text": "오른쪽 컵의 명암이 약해 형태가 떠 보인다.",
                "category": "VALUE",
                "evidence": [1],
            },
            {
                "text": "시간 안에 배경까지 마무리하지 못했다.",
                "category": "TIME_MANAGEMENT",
                "evidence": [3],
            },
        ],
        "fixes": [
            {
                "text": "어두운 면을 한 톤 더 눌러 덩어리감을 살린다.",
                "category": "VALUE",
                "evidence": [2],
            }
        ],
        "next_tips": [],
        "weakness_categories": ["VALUE", "TIME_MANAGEMENT"],
        "insufficient_content": False,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


@dataclass
class Ai:
    runner: JobRunner
    stt: FakeStt
    llm: FakeLlm

    async def drain(self, limit: int = 10) -> int:
        count = 0
        while count < limit and await self.runner.run_once():
            count += 1
        return count


@pytest.fixture
def ai(app, client) -> Ai:  # type: ignore[no-untyped-def]
    stt, llm = FakeStt(), FakeLlm()
    runner = JobRunner(
        app.state.database,
        app.state.settings,
        stt=stt,
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="w-v09",
    )
    return Ai(runner, stt, llm)


async def _sql(app, sql: str, **params):  # type: ignore[no-untyped-def]
    async with app.state.database.engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        return result.all() if result.returns_rows else []


async def _ai_consent(client: httpx.AsyncClient, student: Actor) -> None:
    granted = await client.post(
        f"{API}/ai-processing-consents",
        json={"policy_version": AI_VERSION, "agreed": True, "birth_year_month": "2000-01"},
        headers=student.headers,
    )
    assert granted.status_code == 201, granted.text


async def _artwork(client: httpx.AsyncClient, owner: Actor, **body) -> str:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"{API}/artworks",
        json={"title": "정물 소묘", "practical_type": "DRAWING"} | body,
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _note(client, owner: Actor, artwork_id: str, **body) -> dict:  # type: ignore[no-untyped-def]
    created = await client.post(
        f"{API}/artworks/{artwork_id}/feedback-notes",
        json={"source": "INSTRUCTOR", "body": NOTE_TEXT} | body,
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    return created.json()


async def _summarize_and_approve(client, ai: Ai, owner: Actor, note: dict) -> dict:  # type: ignore[no-untyped-def]
    queued = await client.post(f"{API}/feedback-notes/{note['id']}/summary", headers=owner.headers)
    assert queued.status_code == 202, queued.text
    ai.llm.outcomes.append(note_ai_json())
    assert await ai.drain() == 1
    current = (await client.get(f"{API}/feedback-notes/{note['id']}", headers=owner.headers)).json()
    feedback_id = current["feedback_id"]
    assert current["feedback_status"] == "DRAFT"
    approved = await client.post(
        f"{API}/feedbacks/{feedback_id}/approve", json={"version": 1}, headers=owner.headers
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


# ============================================================================ F-1 학습 목표


async def test_profile_goals_and_target_universities(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")  # 학원 가입 없음
    patched = await client.patch(
        f"{API}/users/me",
        json={
            "grade": "HIGH_2",
            "practical_type": "BASIC_DESIGN",
            "learning_goal": "명암 단계 익히기",
        },
        headers=student.headers,
    )
    assert patched.status_code == 200, patched.text
    me = patched.json()
    assert (me["grade"], me["learning_goal"]) == ("HIGH_2", "명암 단계 익히기")
    first_updated = me["learning_goal_updated_at"]
    assert first_updated is not None
    # 목표가 바뀌지 않으면 수정일 유지
    same = await client.patch(
        f"{API}/users/me", json={"learning_goal": "명암 단계 익히기"}, headers=student.headers
    )
    assert same.json()["learning_goal_updated_at"] == first_updated
    bad = await client.patch(f"{API}/users/me", json={"grade": "HIGH_9"}, headers=student.headers)
    assert bad.status_code == 422

    base = f"{API}/users/me/target-universities"
    names = ["홍익대", "국민대", "건국대"]
    ids = []
    for name in names:
        created = await client.post(
            base,
            json={"university_name": name, "department": "시각디자인"},
            headers=student.headers,
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["id"])
    # 2지망 자리에 끼워 넣기 → 뒤로 밀림
    inserted = await client.post(
        base, json={"university_name": "서울여대", "priority": 2}, headers=student.headers
    )
    assert inserted.json()["priority"] == 2
    listed = (await client.get(base, headers=student.headers)).json()
    assert [u["university_name"] for u in listed] == ["홍익대", "서울여대", "국민대", "건국대"]
    assert [u["priority"] for u in listed] == [1, 2, 3, 4]
    # 순위 이동·수정·삭제
    moved = await client.patch(
        f"{base}/{ids[2]}",
        json={"priority": 1, "admission_note": "수시 실기"},
        headers=student.headers,
    )
    assert moved.status_code == 200 and moved.json()["priority"] == 1
    assert (await client.delete(f"{base}/{ids[0]}", headers=student.headers)).status_code == 204
    listed = (await client.get(base, headers=student.headers)).json()
    assert [(u["university_name"], u["priority"]) for u in listed] == [
        ("건국대", 1),
        ("서울여대", 2),
        ("국민대", 3),
    ]
    # 전체 순서 바꾸기: 빠짐없이 보내야 함
    order = [u["id"] for u in reversed(listed)]
    reordered = await client.put(f"{base}/order", json={"ids": order}, headers=student.headers)
    assert [u["id"] for u in reordered.json()] == order
    partial = await client.put(f"{base}/order", json={"ids": order[:2]}, headers=student.headers)
    assert partial.status_code == 422
    # 다른 사용자는 볼 수도 고칠 수도 없다
    other = await actors.signup("STUDENT")
    assert (await client.get(base, headers=other.headers)).json() == []
    hidden = await client.patch(
        f"{base}/{order[0]}", json={"university_name": "x"}, headers=other.headers
    )
    assert hidden.status_code == 404
    # 학습 맥락 (성장 화면용)
    context = (await client.get(f"{API}/users/me/learning-context", headers=student.headers)).json()
    assert context["grade"] == "HIGH_2" and len(context["target_universities"]) == 3
    # 최대 10개
    for i in range(7):
        await client.post(base, json={"university_name": f"대학{i}"}, headers=student.headers)
    over = await client.post(base, json={"university_name": "11번째"}, headers=student.headers)
    assert over.status_code == 409 and over.json()["error"]["code"] == "TARGET_UNIVERSITY_LIMIT"
    # 강사 계정은 지망 대학 API 대상이 아님
    teacher = await actors.signup("INSTRUCTOR")
    assert (await client.get(base, headers=teacher.headers)).status_code == 403


# ============================================================================ F-2 시간 기록·타이머


async def test_artwork_time_record_and_timer(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    created = await client.post(
        f"{API}/artworks",
        json={
            "title": "모의 실기 1회",
            "topic": "일상 속 사물의 재해석",
            "work_method": "수채",
            "work_category": "MOCK_EXAM",
            "time_limit_minutes": 240,
            "actual_minutes": 250,
        },
        headers=student.headers,
    )
    assert created.status_code == 201, created.text
    art = created.json()
    assert (art["topic"], art["work_method"], art["time_source"]) == (
        "일상 속 사물의 재해석",
        "수채",
        "MANUAL",
    )
    assert art["over_time_limit"] is True
    for bad in ({"actual_minutes": 0}, {"actual_minutes": -5}, {"time_limit_minutes": 1441}):
        response = await client.patch(
            f"{API}/artworks/{art['id']}", json=bad, headers=student.headers
        )
        assert response.status_code == 422, bad
    cleared = await client.patch(
        f"{API}/artworks/{art['id']}", json={"actual_minutes": None}, headers=student.headers
    )
    assert cleared.json()["time_source"] is None and cleared.json()["over_time_limit"] is None

    timer = f"{API}/artworks/{art['id']}/timer"
    idle = (await client.get(timer, headers=student.headers)).json()
    assert (idle["state"], idle["elapsed_seconds"]) == ("IDLE", 0)
    wrong = await client.post(f"{timer}/events", json={"event": "PAUSE"}, headers=student.headers)
    assert wrong.status_code == 409 and wrong.json()["error"]["code"] == "TIMER_INVALID_TRANSITION"

    now = clock.utc_now()
    start = now - timedelta(minutes=100)

    async def event(name: str, at) -> dict:  # type: ignore[no-untyped-def]
        response = await client.post(
            f"{timer}/events",
            json={"event": name, "occurred_at": at.isoformat()},
            headers=student.headers,
        )
        assert response.status_code == 200, response.text
        return response.json()

    await event("START", start)
    paused = await event("PAUSE", start + timedelta(minutes=30))
    assert paused["state"] == "PAUSED" and paused["elapsed_seconds"] == 1800
    # 직전 이벤트보다 이른 시각은 거절
    early = await client.post(
        f"{timer}/events",
        json={"event": "RESUME", "occurred_at": (start + timedelta(minutes=10)).isoformat()},
        headers=student.headers,
    )
    assert early.status_code == 422 and early.json()["error"]["code"] == "TIMER_INVALID_TIME"
    await event("RESUME", start + timedelta(minutes=40))
    # 새로고침: 저장된 이벤트로 RUNNING 복원 (30분 + 재개 후 60분)
    restored = (await client.get(timer, headers=student.headers)).json()
    assert restored["state"] == "RUNNING" and restored["running_since"] is not None
    assert 5390 <= restored["elapsed_seconds"] <= 5420
    assert restored["remaining_seconds"] == 240 * 60 - restored["elapsed_seconds"]
    stopped = await event("STOP", start + timedelta(minutes=95))
    assert stopped["state"] == "STOPPED" and stopped["elapsed_seconds"] == 85 * 60
    assert (stopped["actual_minutes"], stopped["time_source"]) == (85, "TIMER")
    assert [e["event"] for e in stopped["events"]] == ["START", "PAUSE", "RESUME", "STOP"]
    detail = (await client.get(f"{API}/artworks/{art['id']}", headers=student.headers)).json()
    assert (detail["actual_minutes"], detail["over_time_limit"]) == (85, False)
    reset = await client.post(f"{timer}/events", json={"event": "RESET"}, headers=student.headers)
    assert reset.json()["state"] == "IDLE"
    # 24시간 넘게 켜 둔 타이머는 종료 기록 불가 → RESET 또는 직접 입력
    long_art = await _artwork(client, student)
    long_timer = f"{API}/artworks/{long_art}/timer"
    started = await client.post(
        f"{long_timer}/events",
        json={"event": "START", "occurred_at": (now - timedelta(hours=23)).isoformat()},
        headers=student.headers,
    )
    assert started.status_code == 200, started.text
    await _sql(
        app,
        "UPDATE artwork_timer_events SET occurred_at = occurred_at - interval '2 hours'"
        " WHERE artwork_id = :a",
        a=long_art,
    )
    too_long = await client.post(
        f"{long_timer}/events", json={"event": "STOP"}, headers=student.headers
    )
    assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "TIMER_TOO_LONG"
    # 다른 학생은 타이머에 접근 불가
    other = await actors.signup("STUDENT")
    assert (await client.get(timer, headers=other.headers)).status_code == 404


# ================================================================ F-3·F-4 텍스트 첨삭 → 성장 분석


async def test_text_feedback_cycle_without_academy(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    artworks = [await _artwork(client, student, work_date=f"2026-10-0{d}") for d in (1, 2, 3)]

    # 하나의 작품에 여러 첨삭 (출처 구분)
    note = await _note(client, student, artworks[0], feedback_date="2026-10-01")
    assert note["review_mode"] == "SELF" and note["segments"][3]["text"].startswith("시간 안에")
    self_note = await _note(
        client, student, artworks[0], source="SELF_NOTE", body="비례를 다시 재 보자."
    )
    listed = (
        await client.get(f"{API}/artworks/{artworks[0]}/feedback-notes", headers=student.headers)
    ).json()
    assert {n["source"] for n in listed} == {"INSTRUCTOR", "SELF_NOTE"}

    # AI 요약 (같은 SUMMARIZE 파이프라인) → 원문 근거 연결 → 본인 수정·확정
    queued = await client.post(
        f"{API}/feedback-notes/{note['id']}/summary", headers=student.headers
    )
    assert queued.status_code == 202
    again = await client.post(f"{API}/feedback-notes/{note['id']}/summary", headers=student.headers)
    assert again.status_code == 200 and again.json()["id"] == queued.json()["id"]  # 중복 방지
    ai.llm.outcomes.append(note_ai_json())
    assert await ai.drain() == 1
    assert "[3] 시간 안에 배경까지 마무리하지 못했다." in ai.llm.prompts[-1]
    assert "정물 소묘" not in ai.llm.prompts[-1]  # 작품 정보는 보내지 않는다
    feedback_id = (
        await client.get(f"{API}/feedback-notes/{note['id']}", headers=student.headers)
    ).json()["feedback_id"]
    draft = (await client.get(f"{API}/feedbacks/{feedback_id}", headers=student.headers)).json()
    assert (draft["note_id"], draft["recording_id"], draft["source"]) == (
        note["id"],
        None,
        "INSTRUCTOR",
    )
    assert draft["prompt_version"] == "feedback-text-summary-v1"
    assert draft["categories"] == ["VALUE", "TIME_MANAGEMENT"]
    assert draft["weaknesses"][1]["evidence"] == [
        {
            "index": 3,
            "start_ms": None,
            "end_ms": None,
            "text": "시간 안에 배경까지 마무리하지 못했다.",
        }
    ]
    assert draft["ai_draft"]["summary"]  # AI 원본 보존
    edited = await client.patch(
        f"{API}/feedbacks/{feedback_id}",
        json={
            "version": 1,
            "summary": "컵 명암 보강, 시간 배분 필요",
            "items": [
                {
                    "id": draft["weaknesses"][0]["id"],
                    "kind": "WEAKNESS",
                    "content": draft["weaknesses"][0]["content"],
                    "category": "VALUE",
                },
                {
                    "id": draft["weaknesses"][1]["id"],
                    "kind": "WEAKNESS",
                    "content": draft["weaknesses"][1]["content"],
                    "category": "TIME_MANAGEMENT",
                },
            ],
            "categories": ["VALUE", "TIME_MANAGEMENT"],
        },
        headers=student.headers,
    )
    assert edited.status_code == 200, edited.text
    history = (
        await client.get(f"{API}/feedbacks/{feedback_id}/history", headers=student.headers)
    ).json()
    assert [h["action"] for h in history] == ["CREATED", "EDITED"]
    approved = await client.post(
        f"{API}/feedbacks/{feedback_id}/approve", json={"version": 2}, headers=student.headers
    )
    assert approved.status_code == 200 and approved.json()["status"] == "APPROVED"

    # 확정 후 원문 수정 불가 → 다시 열면 가능
    locked = await client.patch(
        f"{API}/feedback-notes/{note['id']}",
        json={"version": 1, "body": "바뀐 첨삭"},
        headers=student.headers,
    )
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "FEEDBACK_NOTE_LOCKED"
    dated = await client.patch(
        f"{API}/feedback-notes/{note['id']}",
        json={"version": 1, "feedback_date": "2026-10-02"},
        headers=student.headers,
    )
    assert dated.status_code == 200 and dated.json()["version"] == 2

    # 나머지 두 작품도 강사 첨삭 확정 → 반복 약점 분석 가능 (학원 없이)
    for artwork_id in artworks[1:]:
        await _summarize_and_approve(client, ai, student, await _note(client, student, artwork_id))
    # 자기 메모는 확정해도 반복 약점에 넣지 않음 (참고 통계만)
    queued = await client.post(
        f"{API}/feedback-notes/{self_note['id']}/summary", headers=student.headers
    )
    assert queued.status_code == 202
    ai.llm.outcomes.append(
        ai_json(
            summary="비례를 다시 잴 것",
            strengths=[],
            weaknesses=[{"text": "비례를 다시 재 본다", "category": "PROPORTION", "evidence": [0]}],
            fixes=[],
            next_tips=[],
            weakness_categories=["PROPORTION"],
        )
    )
    assert await ai.drain() == 1
    self_feedback = (
        await client.get(f"{API}/feedback-notes/{self_note['id']}", headers=student.headers)
    ).json()["feedback_id"]
    assert (
        await client.post(
            f"{API}/feedbacks/{self_feedback}/approve", json={"version": 1}, headers=student.headers
        )
    ).status_code == 200

    weak = (
        await client.get(f"{API}/growth/me/weaknesses?scope=PERSONAL", headers=student.headers)
    ).json()
    assert weak["status"] == "READY" and weak["totals"]["analyzed_artwork_count"] == 3
    # 작품 수·최근 비율·언급 수가 같으면 코드 순
    assert weak["top_weaknesses"] == ["TIME_MANAGEMENT", "VALUE"]
    assert "PROPORTION" not in {w["category"] for w in weak["weaknesses"]}
    assert weak["source_breakdown"] == {"INSTRUCTOR": 3, "SELF_NOTE": 1, "PEER": 0}
    assert weak["unverified_mentions"][0]["category"] == "PROPORTION"
    evidence = weak["weaknesses"][0]["evidence"][0]
    assert evidence["note_id"] and evidence["source_text"]  # 원문 근거 확인 가능

    # 특정 약점의 과거 첨삭
    history = (
        await client.get(f"{API}/growth/me/weaknesses/VALUE/feedbacks", headers=student.headers)
    ).json()
    # 첫 작품은 수정 때 수정 방법 항목을 뺐으므로 1 + 나머지 작품 2개 × (부족한 점 + 수정 방법)
    assert history["total"] == 5
    assert history["items"][0]["evidence"]["source_text"]
    with_unverified = (
        await client.get(
            f"{API}/growth/me/weaknesses/PROPORTION/feedbacks?include_unverified=true",
            headers=student.headers,
        )
    ).json()
    assert with_unverified["total"] == 1
    assert with_unverified["items"][0]["evidence"]["source"] == "SELF_NOTE"

    # 원문 삭제 → 요약·항목 함께 삭제, 분석에서 제외
    assert (
        await client.delete(f"{API}/feedback-notes/{note['id']}", headers=student.headers)
    ).status_code == 204
    after = (
        await client.get(f"{API}/growth/me/weaknesses?scope=PERSONAL", headers=student.headers)
    ).json()
    assert after["totals"]["analyzed_artwork_count"] == 2 and after["status"] == "INSUFFICIENT_DATA"
    assert (
        await client.get(f"{API}/feedbacks/{feedback_id}", headers=student.headers)
    ).status_code == 404

    # 다른 학생은 원문·요약에 접근 불가
    other = await actors.signup("STUDENT")
    assert (
        await client.get(f"{API}/feedback-notes/{self_note['id']}", headers=other.headers)
    ).status_code == 404
    assert (
        await client.post(
            f"{API}/artworks/{artworks[1]}/feedback-notes",
            json={"source": "SELF_NOTE", "body": "x"},
            headers=other.headers,
        )
    ).status_code == 404


async def test_note_edit_supersedes_draft_and_cancels_job(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    artwork_id = await _artwork(client, student)
    # 동의가 있으면 생성과 동시에 요약 요청
    note = await _note(client, student, artwork_id, request_summary=True)
    assert note["summary_job"]["status"] == "QUEUED"
    # 작업이 돌기 전에 원문 수정 → 작업 취소
    edited = await client.patch(
        f"{API}/feedback-notes/{note['id']}",
        json={"version": 1, "body": NOTE_TEXT + " 마지막 문장."},
        headers=student.headers,
    )
    assert edited.json()["summary_job"]["status"] == "CANCELLED"
    assert edited.json()["summary_job"]["error_code"] == "NOTE_EDITED"
    assert len(edited.json()["segments"]) == 5
    assert await ai.drain() == 0
    # 새로 요청 → 초안 → 원문을 또 고치면 초안은 대체됨
    await client.post(f"{API}/feedback-notes/{note['id']}/summary", headers=student.headers)
    ai.llm.outcomes.append(note_ai_json())
    assert await ai.drain() == 1
    draft = (await client.get(f"{API}/feedback-notes/{note['id']}", headers=student.headers)).json()
    assert draft["feedback_status"] == "DRAFT"
    exists = await client.post(
        f"{API}/feedback-notes/{note['id']}/summary", headers=student.headers
    )
    assert exists.status_code == 409 and exists.json()["error"]["code"] == "FEEDBACK_INVALID_STATE"
    changed = await client.patch(
        f"{API}/feedback-notes/{note['id']}",
        json={"version": 2, "source": "SELF_NOTE"},
        headers=student.headers,
    )
    assert changed.json()["feedback_id"] is None and changed.json()["source"] == "SELF_NOTE"
    stale = await client.patch(
        f"{API}/feedback-notes/{note['id']}",
        json={"version": 1, "body": "x"},
        headers=student.headers,
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "FEEDBACK_VERSION_CONFLICT"
    # 동의 없는 학생: 저장만 되고 요약은 409
    plain = await actors.signup("STUDENT")
    plain_note = await _note(client, plain, await _artwork(client, plain), request_summary=True)
    assert plain_note["summary_job"] is None
    denied = await client.post(
        f"{API}/feedback-notes/{plain_note['id']}/summary", headers=plain.headers
    )
    assert denied.status_code == 409 and denied.json()["error"]["code"] == "AI_CONSENT_REQUIRED"


async def test_grounding_drops_items_not_in_source(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    note = await _note(client, student, await _artwork(client, student))
    await client.post(f"{API}/feedback-notes/{note['id']}/summary", headers=student.headers)
    invented = {"text": "채색의 채도 대비가 훌륭하다", "category": "COLOR", "evidence": [0]}
    ai.llm.outcomes.append(note_ai_json(strengths=[invented]))
    assert await ai.drain() == 1
    feedback_id = (
        await client.get(f"{API}/feedback-notes/{note['id']}", headers=student.headers)
    ).json()["feedback_id"]
    detail = (await client.get(f"{API}/feedbacks/{feedback_id}", headers=student.headers)).json()
    assert detail["strengths"] == [] and detail["dropped_item_count"] == 1


async def test_academy_artwork_note_review_rules(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, ai: Ai
) -> None:
    """학원 작품: 강사 첨삭 텍스트는 담당 강사가 확정, 자기 메모는 학생 본인만 (강사 비공개)."""
    student = world.students[0]
    await _ai_consent(client, student)
    artwork_id = await _artwork(client, student, academy_id=world.academy_id)
    instructor_note = await _note(client, student, artwork_id)
    memo = await _note(client, student, artwork_id, source="SELF_NOTE", body="명암을 더 눌러 보자.")
    assert (instructor_note["review_mode"], memo["review_mode"]) == ("INSTRUCTOR", "SELF")
    for n in (instructor_note, memo):
        await client.post(f"{API}/feedback-notes/{n['id']}/summary", headers=student.headers)
    ai.llm.outcomes.extend(
        [
            note_ai_json(),
            ai_json(
                summary="명암을 더 누를 것",
                strengths=[],
                weaknesses=[{"text": "명암을 더 눌러 본다", "category": "VALUE", "evidence": [0]}],
                fixes=[],
                next_tips=[],
                weakness_categories=["VALUE"],
            ),
        ]
    )
    assert await ai.drain() == 2
    teacher_fb = (
        await client.get(f"{API}/feedback-notes/{instructor_note['id']}", headers=student.headers)
    ).json()["feedback_id"]
    memo_fb = (
        await client.get(f"{API}/feedback-notes/{memo['id']}", headers=student.headers)
    ).json()["feedback_id"]
    # 학생은 강사 첨삭 초안을 볼 수 없고 확정할 수 없다 (기존 승인 흐름 유지)
    assert (
        await client.get(f"{API}/feedbacks/{teacher_fb}", headers=student.headers)
    ).status_code == 403
    assert (
        await client.post(
            f"{API}/feedbacks/{teacher_fb}/approve", json={"version": 1}, headers=student.headers
        )
    ).status_code == 403
    # 강사 검토 대기열에는 강사 첨삭만, 자기 메모는 강사에게 404
    queue = (await client.get(f"{world.base}/feedbacks", headers=world.teacher.headers)).json()
    assert [i["id"] for i in queue["items"]] == [teacher_fb]
    assert queue["items"][0]["note_id"] == instructor_note["id"]
    assert queue["items"][0]["recording_id"] is None
    assert (
        await client.get(f"{world.base}/feedbacks/{memo_fb}", headers=world.teacher.headers)
    ).status_code == 404
    staff_view = (
        await client.get(f"{world.base}/feedbacks/{teacher_fb}", headers=world.teacher.headers)
    ).json()
    assert staff_view["weaknesses"][0]["evidence"][0]["text"]  # 원문 근거 함께
    assert (
        await client.post(
            f"{world.base}/feedbacks/{teacher_fb}/approve",
            json={"version": 1},
            headers=world.teacher.headers,
        )
    ).status_code == 200
    # 자기 메모는 학원 작품이어도 학생 본인이 확정
    assert (
        await client.post(
            f"{API}/feedbacks/{memo_fb}/approve", json={"version": 1}, headers=student.headers
        )
    ).status_code == 200
    # 강사 성장 화면에는 자기 메모가 섞이지 않는다
    weak = (
        await client.get(
            f"{world.base}/growth/students/{student.membership_id}/weaknesses",
            headers=world.teacher.headers,
        )
    ).json()
    assert weak["source_breakdown"] == {"INSTRUCTOR": 1, "SELF_NOTE": 0, "PEER": 0}


# ============================================================================ STT 수정·보관 기간


async def test_transcript_edit_and_audio_retention(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    artwork_id = await _artwork(client, student)
    assert (await _consent(client, student)).status_code in (200, 201)
    recorded = await _record(
        client,
        app.state.audio_storage,
        student,
        artwork_id,
        speaker_consent_status="CONSENT_REPORTED",
    )
    assert recorded.status_code == 200, recorded.text
    recording = recorded.json()
    assert recording["speaker_consent_status"] == "CONSENT_REPORTED"
    assert recording["speaker_consent_verified"] is False and recording["audio_available"] is True
    base = f"{API}/artworks/{artwork_id}/recordings/{recording['id']}"
    assert (await client.post(f"{base}/transcription", headers=student.headers)).status_code == 202
    assert await ai.drain() == 1
    original = (await client.get(f"{base}/transcript", headers=student.headers)).json()
    assert original["edited"] is False

    edit = {
        "base_transcript_id": original["id"],
        "segments": [
            {"index": 1, "text": "근데 오른쪽 사과의 명암이 너무 약해서 형태가 떠 보인다."}
        ],
    }
    edited = await client.put(f"{base}/transcript", json=edit, headers=student.headers)
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["edited"] is True and body["edited_from_id"] == original["id"]
    assert body["segments"][1]["text"].endswith("떠 보인다.")
    assert body["segments"][1]["start_ms"] == original["segments"][1]["start_ms"]
    stale = await client.put(f"{base}/transcript", json=edit, headers=student.headers)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "FEEDBACK_VERSION_CONFLICT"
    bad_index = await client.put(
        f"{base}/transcript",
        json={"base_transcript_id": body["id"], "segments": [{"index": 99, "text": "x"}]},
        headers=student.headers,
    )
    assert bad_index.status_code == 422
    # 원본 전사는 보존
    rows = await _sql(
        app, "SELECT count(*) FROM feedback_transcripts WHERE recording_id = :r", r=recording["id"]
    )
    assert rows[0][0] == 2

    # 수정된 전사로 요약 → 확정 후에는 전사 수정 불가
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202
    assert await ai.drain() == 1
    assert "떠 보인다." in ai.llm.prompts[-1]
    status = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert (
        await client.post(
            f"{API}/feedbacks/{status['feedback_id']}/approve",
            json={"version": 1},
            headers=student.headers,
        )
    ).status_code == 200
    locked = await client.put(
        f"{base}/transcript",
        json={"base_transcript_id": body["id"], "segments": [{"index": 0, "text": "x"}]},
        headers=student.headers,
    )
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "TRANSCRIPT_LOCKED"

    # 보관 기간(기본 180일)이 지나면 음성만 삭제, 전사·첨삭은 유지
    await _sql(
        app,
        "UPDATE feedback_recordings SET uploaded_at = now() - interval '181 days' WHERE id = :r",
        r=recording["id"],
    )
    listed = (
        await client.get(f"{API}/artworks/{artwork_id}/recordings", headers=student.headers)
    ).json()
    assert listed[0]["audio_available"] is False and listed[0]["audio_deleted_at"]
    assert recording_path_deleted(app, student, artwork_id, recording["id"])
    url = await client.get(f"{base}/url", headers=student.headers)
    assert url.status_code == 409 and url.json()["error"]["code"] == "RECORDING_AUDIO_EXPIRED"
    assert (await client.get(f"{base}/transcript", headers=student.headers)).status_code == 200
    assert (
        await client.get(f"{API}/feedbacks/{status['feedback_id']}", headers=student.headers)
    ).status_code == 200
    options = (await client.get(f"{API}/meta/options")).json()
    assert options["data_policy"] == {
        "recording_audio_retention_days": 180,
        "model_training_data_collection": False,
        "speaker_consent_verified_by_service": False,
    }


def recording_path_deleted(app, student: Actor, artwork_id: str, recording_id: str) -> bool:  # type: ignore[no-untyped-def]
    storage: FakeStorage = app.state.audio_storage
    prefix = f"{student.user_id}/{artwork_id}/{recording_id}."
    return not any(path.startswith(prefix) for path in storage.objects)


# ================================================================ F-5·F-7 아카이브·리포트


async def test_archive_compare_and_time_report(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    # 데이터 없는 신규 사용자 안내
    empty = (await client.get(f"{API}/growth/me/weaknesses", headers=student.headers)).json()
    assert empty["status"] == "INSUFFICIENT_DATA"
    assert any("첫 작품" in g for g in empty["guidance"])

    await _ai_consent(client, student)
    ids = []
    for day, minutes in ((1, 200), (8, 260), (15, None)):
        artwork_id = await _artwork(
            client,
            student,
            work_date=f"2026-10-{day:02d}",
            work_category="MOCK_EXAM",
            time_limit_minutes=240,
            **({"actual_minutes": minutes} if minutes else {}),
        )
        ids.append(artwork_id)
        uploaded = await _upload(client, app.state.storage, student, artwork_id, "FINAL")
        assert uploaded.status_code == 200, uploaded.text
        await _summarize_and_approve(client, ai, student, await _note(client, student, artwork_id))

    report = await client.post(
        f"{API}/growth/me/reports",
        json={"period": "CUSTOM", "from": "2026-10-01", "to": "2026-10-31", "scope": "ALL"},
        headers=student.headers,
    )
    assert report.status_code == 201, report.text
    stats = report.json()["statistics"]
    assert report.json()["analysis_version"] == "growth-v2"
    assert stats["time_stats"]["recorded_artwork_count"] == 2
    assert stats["time_stats"]["total_minutes"] == 460
    assert stats["time_stats"]["mock_exam"] == {
        "artwork_count": 3,
        "timed_count": 2,
        "over_limit_count": 1,
        "average_time_ratio": round((200 / 240 + 260 / 240) / 2, 3),
    }
    assert sum(b["artwork_count"] for b in stats["activity"]) == 3
    assert stats["strengths"][0]["category"] == "COMPOSITION"
    assert "과제를 완료했다는 것과 실력이 향상되었다는 것은 같은 뜻이 아닙니다." in stats["notes"]

    # 작품 비교: 직전 작품 자동 선택, 대표 사진 Signed URL, 카테고리 차이
    compared = await client.get(
        f"{API}/growth/me/compare?current_artwork_id={ids[1]}", headers=student.headers
    )
    assert compared.status_code == 200, compared.text
    body = compared.json()
    assert body["previous"]["artwork_id"] == ids[0] and body["current"]["artwork_id"] == ids[1]
    assert body["current"]["photos"][0]["stage"] == "FINAL"
    assert body["current"]["photos"][0]["url"]
    assert body["still_mentioned"] == ["VALUE", "TIME_MANAGEMENT"]
    assert body["current"]["actual_minutes"] == 260
    first = await client.get(
        f"{API}/growth/me/compare?current_artwork_id={ids[0]}", headers=student.headers
    )
    assert first.status_code == 409 and first.json()["error"]["code"] == "ARTWORK_NOT_COMPARABLE"
    other = await actors.signup("STUDENT")
    assert (
        await client.get(
            f"{API}/growth/me/compare?current_artwork_id={ids[1]}", headers=other.headers
        )
    ).status_code == 404

    # 타임라인: 시간 기록·출처·텍스트 첨삭 id
    timeline = (await client.get(f"{API}/growth/me/timeline", headers=student.headers)).json()
    newest = timeline["items"][0]
    assert newest["artwork_id"] == ids[2] and newest["actual_minutes"] is None
    assert newest["feedbacks"][0]["note_id"] and newest["feedbacks"][0]["source"] == "INSTRUCTOR"
