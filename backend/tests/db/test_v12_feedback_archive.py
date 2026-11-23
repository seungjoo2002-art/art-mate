"""v1.2 첨삭 정리·아카이브·홈 브리핑 (가짜 LLM — 실제 외부 호출 없음).

- STT 문맥 보정: 원본 보존, 보정본 별도 저장, 의미를 바꾸는 보정 거절, 실패해도 요약 계속
- 아카이브 분석 리포트·홈 브리핑: 0건 → 확정 대기 → 1건(데이터 부족) → 여러 건(반복 실수·강점),
  확정 취소·삭제 즉시 반영, 다른 학생 데이터 미포함, 조회 때 LLM 호출 없음
- AI 설명문 자동 갱신: 같은 데이터에 1번만, 알림 없음, 데이터가 바뀌면 STALE
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.worker.runner import JobRunner
from tests.db.test_ai_feedback_api import _ai_consent, _sql
from tests.db.test_ai_summary_scenarios import CRITIQUE, _browser, _recording
from tests.db.test_growth_api import _growth_consent, _narrative_json
from tests.db.test_v09_learning_cycle import _artwork, _note, note_ai_json
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt

API = "/api/v1"


def _runner(app, llm: FakeLlm, *, correction: bool = True) -> JobRunner:  # type: ignore[no-untyped-def]
    settings = app.state.settings.model_copy(update={"stt_context_correction_enabled": correction})
    return JobRunner(
        app.state.database,
        settings,
        stt=FakeStt(),
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="w-v12",
    )


async def _drain(runner: JobRunner, limit: int = 10) -> int:
    count = 0
    while count < limit and await runner.run_once():
        count += 1
    return count


# STT가 틀린 문장 (명함·반사과) + 정상 문장
MISHEARD = [
    CRITIQUE[0],
    "근데 오른쪽 사과의 명함이 너무 약해서 형태가 떠 보여.",
    "어두운 면을 한 톤 더 눌러주고 반사과는 조금만 남겨.",
    CRITIQUE[3],
]


def _timed(texts: list[str]) -> list[dict]:
    return [
        {"start_ms": i * 4000, "end_ms": i * 4000 + 3500, "text": t} for i, t in enumerate(texts)
    ]


# ================================================================== STT 문맥 보정


async def test_stt_context_correction_keeps_original_and_rejects_meaning_changes(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    base = await _recording(client, app, student, 16_000)
    saved = await client.post(
        f"{base}/transcript/browser",
        json=_browser(_timed(MISHEARD), auto=True),
        headers=student.headers,
    )
    assert saved.status_code == 201, saved.text

    llm = FakeLlm()
    llm.correction_outcomes.append(
        json.dumps(
            {
                "corrections": [
                    # 의미를 바꾸는 보정 → 서버가 거절 (원문 유지)
                    {"index": 0, "text": "전체적으로 구도는 불안정하게 잡았어."},
                    {"index": 1, "text": "근데 오른쪽 사과의 명암이 너무 약해서 형태가 떠 보여."},
                    {"index": 2, "text": "어두운 면을 한 톤 더 눌러주고 반사광은 조금만 남겨."},
                ]
            },
            ensure_ascii=False,
        )
    )
    assert await _runner(app, llm).run_once() is True

    # 보정 → 요약 순서. 요약에는 보정된 문장이 들어간다
    assert "[1] 근데 오른쪽 사과의 명함이" in llm.correction_prompts[0]
    assert "명암이 너무 약해서" in llm.prompts[0] and "명함" not in llm.prompts[0]

    transcript = (await client.get(f"{base}/transcript", headers=student.headers)).json()
    assert transcript["origin"] == "AI_CORRECTED"
    assert transcript["segments"][0]["text"] == CRITIQUE[0]  # 거절된 보정은 원문 그대로
    assert transcript["segments"][1]["text"].startswith("근데 오른쪽 사과의 명암이")
    assert transcript["segments"][1]["start_ms"] == 4000  # 시각·번호 유지
    original = transcript["stt_original"]
    assert original["segments"][1]["text"] == MISHEARD[1]  # STT 원문 보존
    assert original["differs_from_current"] == [1, 2]
    correction = transcript["ai_correction"]
    assert correction["changed_segments"] == [1, 2]
    assert "다시 듣고 확인한 것은 아니에요" in correction["notice"]

    # 요약은 보정 전사를 가리키고, 원본 전사 행은 그대로 남는다
    rows = await _sql(
        app,
        "SELECT t.engine, t.edited_from_id IS NULL FROM feedback_transcripts t ORDER BY created_at",
    )
    assert [tuple(r) for r in rows] == [("browser-wasm", True), ("ai-context-correction", False)]
    linked = await _sql(
        app,
        "SELECT s.transcript_id = CAST(:tid AS uuid) FROM feedback_summaries s",
        tid=transcript["id"],
    )
    assert linked[0][0] is True
    usage = await _sql(
        app, "SELECT api_call_count FROM ai_processing_jobs WHERE job_type = 'SUMMARIZE'"
    )
    assert usage[0][0] == 2  # 보정 1 + 요약 1 (비용 기록)

    # 학생이 보정본을 다시 고칠 수 있고, 원문 비교·AI 보정 정보는 그대로 따라온다
    edited = await client.put(
        f"{base}/transcript",
        json={
            "base_transcript_id": transcript["id"],
            "segments": [{"index": 3, "text": "다음 작품에서는 큰 덩어리 명암부터 잡자."}],
        },
        headers=student.headers,
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert body["origin"] == "EDITED"
    assert body["stt_original"]["differs_from_current"] == [1, 2, 3]
    assert body["ai_correction"]["changed_segments"] == [1, 2]


async def test_stt_correction_failure_or_human_edit_falls_back_to_original(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    base = await _recording(client, app, student, 16_000)
    await client.post(
        f"{base}/transcript/browser",
        json=_browser(_timed(MISHEARD), auto=True),
        headers=student.headers,
    )
    llm = FakeLlm()
    llm.correction_outcomes.append("이건 JSON이 아님")  # 형식 오류 → 보정 생략, 요약은 계속
    assert await _runner(app, llm).run_once() is True
    status = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert status["job"]["status"] == "SUCCEEDED" and status["feedback_id"]
    transcript = (await client.get(f"{base}/transcript", headers=student.headers)).json()
    assert transcript["origin"] == "BROWSER"
    assert transcript["stt_original"] is None and transcript["ai_correction"] is None

    # 학생이 직접 고친 전사는 다시 요약해도 AI가 고치지 않는다 (사람이 쓴 글이 우선)
    await client.put(
        f"{base}/transcript",
        json={
            "base_transcript_id": transcript["id"],
            "segments": [{"index": 1, "text": "근데 오른쪽 사과의 명암이 너무 약해."}],
        },
        headers=student.headers,
    )
    queued = await client.post(f"{base}/summary", headers=student.headers)
    assert queued.status_code == 202, queued.text
    assert await _runner(app, llm).run_once() is True
    assert len(llm.correction_prompts) == 1  # 두 번째 요약에서는 보정 호출 없음


# ================================================================== 아카이브·홈 브리핑


async def _confirmed_note(
    client, runner: JobRunner, llm: FakeLlm, student, **artwork
) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """작품 + 강사 텍스트 첨삭 → AI 정리 → 확정. (note_id, feedback_id)."""
    artwork_id = await _artwork(client, student, **artwork)
    note = await _note(client, student, artwork_id)
    queued = await client.post(
        f"{API}/feedback-notes/{note['id']}/summary", headers=student.headers
    )
    assert queued.status_code == 202, queued.text
    llm.outcomes.append(note_ai_json())
    assert await _drain(runner) == 1
    fid = (await client.get(f"{API}/feedback-notes/{note['id']}", headers=student.headers)).json()[
        "feedback_id"
    ]
    draft = (await client.get(f"{API}/feedbacks/{fid}", headers=student.headers)).json()
    approved = await client.post(
        f"{API}/feedbacks/{fid}/approve",
        json={"version": draft["version"]},
        headers=student.headers,
    )
    assert approved.status_code == 200, approved.text
    return note["id"], fid


async def _get(client, student, path: str) -> dict:  # type: ignore[no-untyped-def]
    response = await client.get(f"{API}/growth/me/{path}", headers=student.headers)
    assert response.status_code == 200, response.text
    return response.json()


async def test_archive_report_and_briefing_lifecycle(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    other = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    llm = FakeLlm()
    runner = _runner(app, llm)

    # 신규 학생: 존재하지 않는 첨삭을 만들지 않는다
    briefing = await _get(client, student, "briefing")
    assert briefing["status"] == "NO_RECORDS"
    assert briefing["headline"] == (
        "아직 첨삭 기록이 없어요. 첫 작품을 등록하고 선생님의 피드백을 기록해 보세요!"
    )
    report = await _get(client, student, "analysis-report")
    assert report["status"] == "NO_FEEDBACK" and report["tags"] == []

    # AI 정리는 끝났지만 아직 확정 전 → 확정 안내
    artwork_id = await _artwork(client, student)
    note = await _note(client, student, artwork_id)
    await client.post(f"{API}/feedback-notes/{note['id']}/summary", headers=student.headers)
    llm.outcomes.append(note_ai_json())
    assert await _drain(runner) == 1
    briefing = await _get(client, student, "briefing")
    assert briefing["status"] == "NEEDS_CONFIRMATION"
    assert briefing["counts"]["pending_review_count"] == 1

    # 확정 1건 → 데이터 부족: 그 첨삭만 근거로 짧게, 추세·강점 판단 보류
    fid = (await client.get(f"{API}/feedback-notes/{note['id']}", headers=student.headers)).json()[
        "feedback_id"
    ]
    draft = (await client.get(f"{API}/feedbacks/{fid}", headers=student.headers)).json()
    await client.post(
        f"{API}/feedbacks/{fid}/approve",
        json={"version": draft["version"]},
        headers=student.headers,
    )
    briefing = await _get(client, student, "briefing")
    assert briefing["status"] == "INSUFFICIENT_DATA"
    assert briefing["focus"]["reason"] == "RECENT"
    assert any("충분하지 않아요" in line for line in briefing["lines"])
    assert all(e["artwork_id"] == artwork_id for e in briefing["evidence"])
    report = await _get(client, student, "analysis-report")
    assert report["status"] == "INSUFFICIENT_DATA"
    assert report["repeated_mistakes"] == report["improving"] == report["strengths"] == []
    assert report["recent_feedbacks"][0]["feedback_id"] == fid

    # 여러 건 (자유 연습 2 + 실기시험 1) → 반복 실수·강점, 실제 첨삭 인용
    note2, _ = await _confirmed_note(client, runner, llm, student)
    await _confirmed_note(
        client, runner, llm, student, work_category="MOCK_EXAM", time_limit_minutes=180
    )
    calls = len(llm.prompts)
    report = await _get(client, student, "analysis-report")
    assert report["status"] == "READY"
    counts = report["counts"]
    assert (
        counts["artwork_count"],
        counts["mock_exam_count"],
        counts["practice_artwork_count"],
    ) == (
        3,
        1,
        2,
    )
    assert counts["instructor_feedback_count"] == 3 and counts["analyzed_artwork_count"] == 3
    repeated = {t["tag"]: t for t in report["repeated_mistakes"]}
    assert repeated["VALUE"]["issue_artwork_count"] == 3
    assert {a["id"] for a in repeated["VALUE"]["related_artworks"]} >= {artwork_id}
    evidence = repeated["VALUE"]["issue_evidence"][0]
    assert evidence["content"] and evidence["source_text"]  # 정리 문장 + 원문 문장
    strengths = {t["tag"]: t for t in report["strengths"]}
    assert strengths["COMPOSITION"]["progress"] == "CONSISTENT_STRENGTH"
    assert report["improving"] == []  # 긍정 첨삭 없는 개선 주장 없음
    briefing = await _get(client, student, "briefing")
    assert briefing["status"] == "READY"
    assert briefing["focus"]["tag"] == "VALUE" and briefing["focus"]["reason"] == "REPEATED"
    assert briefing["practice"]["content"] == "어두운 면을 한 톤 더 눌러 덩어리감을 살린다."
    assert briefing["highlight"]["tag"] == "COMPOSITION"
    assert briefing["ai_comment"]["status"] == "NONE"  # 성장 AI 동의 없음 → 갱신 요청 안 함
    assert len(llm.prompts) == calls  # 조회만으로는 LLM을 부르지 않는다
    fingerprint = briefing["data_fingerprint"]

    # 다른 학생 데이터는 섞이지 않는다
    assert (await _get(client, other, "briefing"))["status"] == "NO_RECORDS"
    assert (await _get(client, other, "analysis-report"))["counts"]["artwork_count"] == 0

    # 확정 취소(수정을 위해 다시 열기) → 즉시 분석에서 빠지고 확정 대기로
    current = (await client.get(f"{API}/feedbacks/{fid}", headers=student.headers)).json()
    reopened = await client.post(
        f"{API}/feedbacks/{fid}/reopen",
        json={"version": current["version"]},
        headers=student.headers,
    )
    assert reopened.status_code == 200, reopened.text
    report = await _get(client, student, "analysis-report")
    assert report["counts"]["instructor_feedback_count"] == 2
    assert report["counts"]["pending_review_count"] == 1
    assert report["status"] == "INSUFFICIENT_DATA"  # 분석 대상 작품 2 < 3
    assert report["data_fingerprint"] != fingerprint

    # 첨삭 삭제 → 근거에서도 사라진다
    deleted = await client.delete(f"{API}/feedback-notes/{note2}", headers=student.headers)
    assert deleted.status_code == 204, deleted.text
    report = await _get(client, student, "analysis-report")
    assert report["counts"]["instructor_feedback_count"] == 1
    assert all(f["feedback_id"] != fid for f in report["recent_feedbacks"])


async def test_briefing_requests_ai_narrative_once_per_data_without_notifications(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    await _growth_consent(client, student)
    llm = FakeLlm()
    runner = _runner(app, llm)
    for _ in range(3):
        await _confirmed_note(client, runner, llm, student)

    first = await _get(client, student, "briefing")
    assert first["status"] == "READY"
    assert first["ai_comment"]["status"] == "PENDING"
    second = await _get(client, student, "briefing")  # 같은 데이터 → 다시 요청하지 않음
    assert second["ai_comment"]["status"] == "PENDING"
    jobs = await _sql(
        app, "SELECT count(*) FROM ai_processing_jobs WHERE job_type = 'GROWTH_REPORT'"
    )
    assert jobs[0][0] == 1
    notices = await _sql(app, "SELECT count(*) FROM notifications WHERE type = 'REPORT_READY'")
    assert notices[0][0] == 0  # 자동 갱신은 알림을 보내지 않는다

    llm.outcomes.append(_narrative_json(overview="최근 첨삭에서 명암이 반복적으로 언급되었다."))
    assert await _drain(runner) == 1
    ready = await _get(client, student, "briefing")
    assert ready["ai_comment"]["status"] == "READY"
    assert ready["ai_comment"]["based_on_current_data"] is True
    assert ready["ai_comment"]["overview"] == "최근 첨삭에서 명암이 반복적으로 언급되었다."
    report = await _get(client, student, "analysis-report")
    assert report["ai_narrative"]["status"] == "READY"

    # 새 첨삭 → 이전 설명문은 STALE로 표시 (최소 간격 안이라 바로 다시 요청하지 않음)
    await _confirmed_note(client, runner, llm, student)
    stale = await _get(client, student, "briefing")
    assert stale["ai_comment"]["status"] == "STALE"
    assert stale["ai_comment"]["based_on_current_data"] is False
    assert stale["ai_comment"]["overview"] == "최근 첨삭에서 명암이 반복적으로 언급되었다."
    jobs = await _sql(
        app, "SELECT count(*) FROM ai_processing_jobs WHERE job_type = 'GROWTH_REPORT'"
    )
    assert jobs[0][0] == 1


@pytest.mark.parametrize("path", ["briefing", "analysis-report"])
async def test_insight_endpoints_require_student_login(
    client: httpx.AsyncClient, path: str
) -> None:
    response = await client.get(f"{API}/growth/me/{path}")
    assert response.status_code == 401
