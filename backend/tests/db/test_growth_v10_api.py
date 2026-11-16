"""v1.0 학생 성장 분석 API: 9개 태그·최근 연습 과제(NEXT_TIP) → 내 연습 과제로 담기·완료 기록.

AI는 가짜(FakeLlm), 실제 외부 호출 없음. 학생 본인 데이터만.
"""

from __future__ import annotations

import httpx
import pytest

from app.worker.runner import JobRunner
from tests.db.test_v09_learning_cycle import API, Ai, _ai_consent, _artwork, _note, note_ai_json
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt


@pytest.fixture
def ai(app, client) -> Ai:  # type: ignore[no-untyped-def]
    stt, llm = FakeStt(), FakeLlm()
    runner = JobRunner(
        app.state.database,
        app.state.settings,
        stt=stt,
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="w-v10",
    )
    return Ai(runner, stt, llm)


TIP = {"text": "어두운 면을 한 톤 더 눌러 덩어리감을 살린다.", "category": "VALUE", "evidence": [2]}


async def _approved_tip(client: httpx.AsyncClient, ai: Ai, student) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """확정된 첨삭 1건(연습 과제 포함)을 만들고 (artwork_id, tip item_id)를 돌려준다."""
    artwork_id = await _artwork(client, student)
    note = await _note(client, student, artwork_id)
    queued = await client.post(
        f"{API}/feedback-notes/{note['id']}/summary", headers=student.headers
    )
    assert queued.status_code == 202, queued.text
    ai.llm.outcomes.append(note_ai_json(next_tips=[TIP]))
    assert await ai.drain() == 1
    fid = (await client.get(f"{API}/feedback-notes/{note['id']}", headers=student.headers)).json()[
        "feedback_id"
    ]
    draft = (await client.get(f"{API}/feedbacks/{fid}", headers=student.headers)).json()
    tip_id = draft["next_tips"][0]["id"]
    approved = await client.post(
        f"{API}/feedbacks/{fid}/approve",
        json={"version": draft["version"]},
        headers=student.headers,
    )
    assert approved.status_code == 200, approved.text
    return artwork_id, tip_id


async def test_analysis_tags_and_practice_tip_task_lifecycle(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    _, tip_id = await _approved_tip(client, ai, student)
    calls = len(ai.llm.prompts)

    analysis = (await client.get(f"{API}/growth/me/weaknesses", headers=student.headers)).json()
    # 9개 태그: 잘한 점(구도)·약점(명암·시간 관리)
    by_tag = {t["tag"]: t for t in analysis["tags"]}
    assert by_tag["COMPOSITION"]["strength_artwork_count"] == 1
    assert by_tag["VALUE"]["weakness_artwork_count"] == 1
    assert by_tag["TIME_MANAGEMENT"]["weakness_artwork_count"] == 1
    assert analysis["timeline"][0]["feedback_count"] == 1
    assert analysis["comparison_context"] is None  # 비교할 작품 부족
    (tip,) = analysis["practice_tips"]
    assert tip["tip"]["item_id"] == tip_id and tip["tip"]["kind"] == "NEXT_TIP"
    assert tip["tip"]["content"] == TIP["text"] and tip["tag"] == "VALUE"
    assert tip["task"] is None

    # 담기 → 채택된 개인 과제 (AI 호출 없음), 다시 담아도 같은 과제
    created = await client.post(
        f"{API}/growth/me/practice-tips/{tip_id}/task", headers=student.headers
    )
    assert created.status_code == 200, created.text
    task = created.json()
    assert (task["status"], task["source"], task["weakness_category"]) == (
        "ADOPTED",
        "RULE",
        "VALUE",
    )
    assert task["title"] == TIP["text"] and task["evidence"][0]["item_id"] == tip_id
    again = await client.post(
        f"{API}/growth/me/practice-tips/{tip_id}/task", headers=student.headers
    )
    assert again.json()["id"] == task["id"]
    assert len(ai.llm.prompts) == calls  # 외부 AI 호출 없음

    # 완료 기록 (기존 API) → 분석 화면의 과제 상태에 반영
    done = await client.put(
        f"{API}/growth/me/recommendations/{task['id']}/completion",
        json={"version": task["version"], "completed": True},
        headers=student.headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "COMPLETED"
    tip = (await client.get(f"{API}/growth/me/weaknesses", headers=student.headers)).json()[
        "practice_tips"
    ][0]
    assert tip["task"]["id"] == task["id"] and tip["task"]["status"] == "COMPLETED"
    undo = await client.put(
        f"{API}/growth/me/recommendations/{task['id']}/completion",
        json={"version": done.json()["version"], "completed": False},
        headers=student.headers,
    )
    assert undo.json()["status"] == "ADOPTED"

    # 맞춤 과제 목록에도 보인다 (기존 화면 재사용)
    listed = (
        await client.get(
            f"{API}/growth/me/recommendations?scope=PERSONAL&limit=50", headers=student.headers
        )
    ).json()
    assert task["id"] in [r["id"] for r in listed["items"]]


async def test_practice_tip_task_access_rules(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    other = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    _, tip_id = await _approved_tip(client, ai, student)

    # 다른 학생은 남의 첨삭 연습 과제를 담을 수 없다 (존재도 노출하지 않음)
    denied = await client.post(
        f"{API}/growth/me/practice-tips/{tip_id}/task", headers=other.headers
    )
    assert denied.status_code == 404
    other_view = (await client.get(f"{API}/growth/me/weaknesses", headers=other.headers)).json()
    assert other_view["practice_tips"] == [] and other_view["tags"] == []

    # 확정 전 첨삭의 연습 과제·연습 과제가 아닌 항목은 담을 수 없다
    artwork_id = await _artwork(client, student, title="두 번째")
    note = await _note(client, student, artwork_id)
    await client.post(f"{API}/feedback-notes/{note['id']}/summary", headers=student.headers)
    ai.llm.outcomes.append(note_ai_json(next_tips=[TIP]))
    assert await ai.drain() == 1
    fid = (await client.get(f"{API}/feedback-notes/{note['id']}", headers=student.headers)).json()[
        "feedback_id"
    ]
    draft = (await client.get(f"{API}/feedbacks/{fid}", headers=student.headers)).json()
    draft_tip = draft["next_tips"][0]["id"]
    not_approved = await client.post(
        f"{API}/growth/me/practice-tips/{draft_tip}/task", headers=student.headers
    )
    assert not_approved.status_code == 404
    strength = draft["strengths"][0]["id"]
    not_tip = await client.post(
        f"{API}/growth/me/practice-tips/{strength}/task", headers=student.headers
    )
    assert not_tip.status_code == 404
