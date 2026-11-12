"""v0.6 AI 첨삭: 전사 → 요약 → 검토·승인 → 아카이브, 권한, 동의, 실패·재시도, 재시작 복구.

STT·Gemini는 가짜 구현으로 대체하고 Worker(JobRunner)를 테스트에서 직접 한 건씩 실행한다.
"""

import asyncio
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import text

from app.integrations.ai.gemini import LlmError
from app.integrations.ai.stt import SttError
from app.worker.runner import JobRunner
from tests.db.conftest import Actor, World
from tests.db.test_recordings_api import _consent, _record
from tests.fake_ai import SEGMENTS, FakeFetcher, FakeLlm, FakeStt, ai_json
from tests.fake_storage import FakeStorage

API = "/api/v1"
AI_VERSION = "2026-12-ai-v2"


@dataclass
class Ai:
    runner: JobRunner
    stt: FakeStt
    llm: FakeLlm
    fetcher: FakeFetcher

    async def drain(self, limit: int = 10) -> int:
        count = 0
        while count < limit and await self.runner.run_once():
            count += 1
        return count


@pytest.fixture
def ai(app, client) -> Ai:  # type: ignore[no-untyped-def]
    stt, llm = FakeStt(), FakeLlm()
    fetcher = FakeFetcher(app.state.audio_storage)
    runner = JobRunner(
        app.state.database, app.state.settings, stt=stt, llm=llm, fetcher=fetcher, worker_id="w1"
    )
    return Ai(runner, stt, llm, fetcher)


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


async def _recording(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, audio: FakeStorage, student: Actor, **artwork
) -> tuple[str, str]:
    created = await client.post(
        f"{API}/artworks", json={"title": "정물 기초디자인"} | artwork, headers=student.headers
    )
    assert created.status_code == 201, created.text
    artwork_id = created.json()["id"]
    consent = await _consent(client, student)
    assert consent.status_code in (200, 201), consent.text
    recorded = await _record(client, audio, student, artwork_id)
    assert recorded.status_code == 200, recorded.text
    return artwork_id, recorded.json()["id"]


def _base(artwork_id: str, recording_id: str) -> str:
    return f"{API}/artworks/{artwork_id}/recordings/{recording_id}"


@pytest.fixture
def audio(app) -> FakeStorage:  # type: ignore[no-untyped-def]
    return app.state.audio_storage


# ============================================================================ 전체 흐름


async def test_academy_flow_transcribe_summarize_review_approve(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, audio: FakeStorage, ai: Ai, app
) -> None:
    student = world.students[0]
    artwork_id, recording_id = await _recording(client, audio, student, academy_id=world.academy_id)
    base = _base(artwork_id, recording_id)

    # 전사 요청 (202) → 중복 요청은 같은 작업 (200)
    first = await client.post(f"{base}/transcription", headers=student.headers)
    assert first.status_code == 202, first.text
    job = first.json()
    assert (job["job_type"], job["status"], job["attempts"]) == ("TRANSCRIBE", "QUEUED", 0)
    assert "source_url" not in job  # 내부 Signed URL은 응답에 없음
    again = await client.post(f"{base}/transcription", headers=student.headers)
    assert again.status_code == 200 and again.json()["id"] == job["id"]
    # Signed URL은 요청한 사용자 토큰으로 발급
    assert audio.calls[-1][0] == "sign"
    assert audio.calls[-1][2] == student.headers["Authorization"].removeprefix("Bearer ")
    pending = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert pending["transcription_status"] == "PENDING" and pending["transcript"] is None
    not_ready = await client.get(f"{base}/transcript", headers=student.headers)
    assert not_ready.json()["error"]["code"] == "TRANSCRIPT_NOT_READY"

    assert await ai.drain() == 1
    status = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert status["transcription_status"] == "COMPLETED"
    assert status["job"]["status"] == "SUCCEEDED" and status["transcript"]["segment_count"] == 4
    transcript = (await client.get(f"{base}/transcript", headers=student.headers)).json()
    assert transcript["segments"][1]["start_ms"] == 4000
    assert "명암" in transcript["text"]
    recording = (
        await client.get(
            f"{API}/artworks/{artwork_id}/recordings/{recording_id}", headers=student.headers
        )
    ).json()
    assert recording["transcription_status"] == "COMPLETED"
    # 다시 전사 요청 → 409
    done = await client.post(f"{base}/transcription", headers=student.headers)
    assert done.json()["error"]["code"] == "TRANSCRIPTION_ALREADY_DONE"
    # 처리 후 Signed URL은 DB에서 지운다
    assert (await _sql(app, "SELECT source_url FROM ai_processing_jobs"))[0][0] is None

    # AI 전송 동의 없이 요약 → 409 (녹음 동의로 대체되지 않음)
    no_consent = await client.post(f"{base}/summary", headers=student.headers)
    assert no_consent.json()["error"]["code"] == "AI_CONSENT_REQUIRED"
    await _ai_consent(client, student)
    # 강사도 요약을 요청할 수 있다 (학생 동의가 기준)
    staff_base = f"{world.base}/artworks/{artwork_id}/recordings/{recording_id}"
    queued = await client.post(f"{staff_base}/summary", headers=world.teacher.headers)
    assert queued.status_code == 202, queued.text
    assert await ai.drain() == 1
    # 외부로 보낸 프롬프트에는 전사 문장만 있고 이름·작품 제목은 없다
    assert "명암" in ai.llm.prompts[-1]
    assert "정물 기초디자인" not in ai.llm.prompts[-1]
    assert world.students[0].user_id.hex not in ai.llm.prompts[-1]

    summary = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert summary["feedback_status"] == "DRAFT" and summary["review_mode"] == "INSTRUCTOR"
    feedback_id = summary["feedback_id"]
    job_row = await _sql(
        app,
        "SELECT api_call_count, input_tokens, output_tokens FROM ai_processing_jobs"
        " WHERE job_type = 'SUMMARIZE'",
    )
    assert tuple(job_row[0]) == (1, 120, 80)

    # 학생: 승인 전 초안 내용 접근 불가, 아카이브 비어 있음
    hidden = await client.get(f"{API}/feedbacks/{feedback_id}", headers=student.headers)
    assert (hidden.status_code, hidden.json()["error"]["code"]) == (403, "FEEDBACK_NOT_APPROVED")
    assert (
        await client.get(f"{API}/artworks/{artwork_id}/feedbacks", headers=student.headers)
    ).json() == []
    # 학생은 학원 작품 첨삭을 수정·승인할 수 없다
    assert (
        await client.post(
            f"{API}/feedbacks/{feedback_id}/approve", json={"version": 1}, headers=student.headers
        )
    ).status_code == 403

    # 강사 검토 대기 목록·상세
    queue = (await client.get(f"{world.base}/feedbacks", headers=world.teacher.headers)).json()
    assert [i["id"] for i in queue["items"]] == [feedback_id]
    assert queue["items"][0]["student"]["membership_id"] == student.membership_id
    detail = (
        await client.get(f"{world.base}/feedbacks/{feedback_id}", headers=world.teacher.headers)
    ).json()
    assert detail["status"] == "DRAFT" and detail["version"] == 1
    assert detail["ai_draft"]["weaknesses"][0]["category"] == "VALUE"
    assert detail["categories"] == ["FORM", "VALUE"]
    # v0.9: 근거에 원문 문장(text)도 함께 내려준다
    assert detail["weaknesses"][0]["evidence"] == [
        {"index": 1, "start_ms": 4000, "end_ms": 7500, "text": SEGMENTS[1]}
    ]
    assert (detail["model_name"], detail["prompt_version"]) == (
        "gemini-3.1-flash-lite",
        "feedback-summary-v4",
    )

    # 강사 수정 → IN_REVIEW, AI 원본은 그대로
    weakness = detail["weaknesses"][0]
    edit = {
        "version": 1,
        "summary": "구도는 좋고, 오른쪽 사과 명암을 보강해야 한다.",
        "items": [
            {
                "id": detail["strengths"][0]["id"],
                "kind": "STRENGTH",
                "content": detail["strengths"][0]["content"],
                "category": "COMPOSITION",
            },
            {
                "id": weakness["id"],
                "kind": "WEAKNESS",
                "content": "오른쪽 사과 암부가 약하다.",
                "category": "VALUE",
            },
            {
                "kind": "FIX",
                "content": "암부를 4B로 한 톤 더 누른다.",
                "category": "VALUE",
                "evidence_segment_ids": [2],
            },
        ],
        "categories": ["VALUE", "PROPORTION"],
        "note": "표현 다듬음",
    }
    updated = await client.patch(
        f"{world.base}/feedbacks/{feedback_id}", json=edit, headers=world.teacher.headers
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert (body["status"], body["version"]) == ("IN_REVIEW", 2)
    assert body["weaknesses"][0]["origin"] == "EDITED"
    assert body["strengths"][0]["origin"] == "AI"
    assert body["fixes"][0]["origin"] == "ADDED" and body["next_tips"] == []
    assert body["categories"] == ["PROPORTION", "VALUE"]
    assert body["ai_draft"]["summary"].startswith("구도는 안정적")  # 원본 보존
    # 오래된 version → 409, 범위 밖 근거 구간 → 422
    stale = await client.patch(
        f"{world.base}/feedbacks/{feedback_id}", json=edit, headers=world.teacher.headers
    )
    assert stale.json()["error"]["code"] == "FEEDBACK_VERSION_CONFLICT"
    bad = edit | {
        "version": 2,
        "items": [{"kind": "FIX", "content": "x", "evidence_segment_ids": [9]}],
    }
    assert (
        await client.patch(
            f"{world.base}/feedbacks/{feedback_id}", json=bad, headers=world.teacher.headers
        )
    ).status_code == 422

    # 승인
    approved = await client.post(
        f"{world.base}/feedbacks/{feedback_id}/approve",
        json={"version": 2},
        headers=world.teacher.headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["approved_by_name"].endswith("담당강사")
    # 승인 후 수정 불가, 재생성 불가
    after = await client.patch(
        f"{world.base}/feedbacks/{feedback_id}",
        json=edit | {"version": 3},
        headers=world.teacher.headers,
    )
    assert after.json()["error"]["code"] == "FEEDBACK_ALREADY_APPROVED"
    regen = await client.post(f"{base}/summary/regenerate", headers=student.headers)
    assert regen.json()["error"]["code"] == "FEEDBACK_ALREADY_APPROVED"

    # 학생 아카이브·상세 (AI 원본·모델 정보는 없음)
    archive = (
        await client.get(f"{API}/artworks/{artwork_id}/feedbacks", headers=student.headers)
    ).json()
    assert [f["id"] for f in archive] == [feedback_id]
    assert archive[0]["summary"] == edit["summary"] and "ai_draft" not in archive[0]
    view = (await client.get(f"{API}/feedbacks/{feedback_id}", headers=student.headers)).json()
    assert view["status"] == "APPROVED" and "ai_draft" not in view

    history = (
        await client.get(
            f"{world.base}/feedbacks/{feedback_id}/history", headers=world.teacher.headers
        )
    ).json()
    assert [h["action"] for h in history] == ["CREATED", "EDITED", "APPROVED"]
    assert history[0]["actor_name"] is None  # 시스템(AI)
    assert history[1]["changes"]["before"]["summary"].startswith("구도는 안정적")
    assert history[1]["note"] == "표현 다듬음"
    # 학원 작품 이력은 학생에게 비공개
    assert (
        await client.get(f"{API}/feedbacks/{feedback_id}/history", headers=student.headers)
    ).status_code == 403

    # 승인 취소 → 아카이브에서 빠짐 → 재생성 가능
    reopened = await client.post(
        f"{world.base}/feedbacks/{feedback_id}/reopen",
        json={"version": 3},
        headers=world.teacher.headers,
    )
    assert reopened.json()["status"] == "IN_REVIEW"
    assert (
        await client.get(f"{API}/artworks/{artwork_id}/feedbacks", headers=student.headers)
    ).json() == []
    assert (
        await client.post(f"{base}/summary/regenerate", headers=student.headers)
    ).status_code == 202
    assert await ai.drain() == 1
    old = await _sql(app, "SELECT status FROM feedback_summaries WHERE id = :id", id=feedback_id)
    assert old[0][0] == "SUPERSEDED"
    current = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert current["feedback_id"] != feedback_id and current["feedback_status"] == "DRAFT"


async def test_staff_access_control(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, audio: FakeStorage, ai: Ai, build_world
) -> None:
    s1, s3 = world.students[0], world.students[2]  # s3은 반 미배정
    artwork_id, recording_id = await _recording(client, audio, s1, academy_id=world.academy_id)
    await _ai_consent(client, s1)
    await client.post(
        f"{_base(artwork_id, recording_id)}/transcription",
        json={"auto_summarize": True},
        headers=s1.headers,
    )
    assert await ai.drain() == 2  # 전사 후 자동 요약
    feedback_id = (
        await client.get(f"{_base(artwork_id, recording_id)}/summary", headers=s1.headers)
    ).json()["feedback_id"]
    staff_base = f"{world.base}/artworks/{artwork_id}/recordings/{recording_id}"

    # 비담당 강사: 403, 목록에도 없음
    other = world.other_teacher.headers
    for method, path in [
        ("GET", f"{world.base}/feedbacks/{feedback_id}"),
        ("GET", f"{staff_base}/transcript"),
        ("POST", f"{staff_base}/summary/regenerate"),
    ]:
        assert (await client.request(method, path, headers=other)).status_code == 403, path
    assert (await client.get(f"{world.base}/feedbacks", headers=other)).json()["total"] == 0
    # 원장(학원 관리자): 접근 가능
    assert (
        await client.get(f"{world.base}/feedbacks/{feedback_id}", headers=world.owner.headers)
    ).status_code == 200
    # 다른 학원 원장: 404
    other_world = await build_world("다른 학원", admin=world.admin)
    assert (
        await client.get(
            f"{other_world.base}/feedbacks/{feedback_id}", headers=other_world.owner.headers
        )
    ).status_code == 404
    assert (
        await client.get(
            f"{other_world.base}/artworks/{artwork_id}/recordings/{recording_id}/transcript",
            headers=other_world.owner.headers,
        )
    ).status_code == 404
    # 다른 학생: 404 (타인 작품·첨삭 비노출)
    intruder = world.students[1]
    for path in (
        f"{API}/feedbacks/{feedback_id}",
        f"{_base(artwork_id, recording_id)}/transcript",
        f"{API}/artworks/{artwork_id}/feedbacks",
    ):
        assert (await client.get(path, headers=intruder.headers)).status_code == 404, path
    # 반 미배정 학생 필터 → 403
    assert (
        await client.get(
            f"{world.base}/feedbacks?student_membership_id={s3.membership_id}",
            headers=world.teacher.headers,
        )
    ).status_code == 403


async def test_personal_artwork_self_review(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, world: World, audio: FakeStorage, ai: Ai
) -> None:
    """학원 미연결 작품: 강사에게 보이지 않고 학생 본인이 확정한다."""
    student = world.students[0]
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    await _ai_consent(client, student)
    await client.post(
        f"{base}/transcription", json={"auto_summarize": True}, headers=student.headers
    )
    assert await ai.drain() == 2
    summary = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert summary["review_mode"] == "SELF"
    feedback_id = summary["feedback_id"]

    # 강사: 학원 경로로도 개인 작품은 404, 검토 목록에도 없음
    staff = world.teacher.headers
    assert (
        await client.get(f"{world.base}/feedbacks/{feedback_id}", headers=staff)
    ).status_code == 404
    assert (
        await client.get(
            f"{world.base}/artworks/{artwork_id}/recordings/{recording_id}/transcript",
            headers=staff,
        )
    ).status_code == 404
    assert (await client.get(f"{world.base}/feedbacks", headers=world.owner.headers)).json()[
        "total"
    ] == 0

    # 학생 본인: 초안 전체 조회·수정·확정
    draft = (await client.get(f"{API}/feedbacks/{feedback_id}", headers=student.headers)).json()
    assert draft["status"] == "DRAFT" and "ai_draft" in draft and draft["student"] is None
    rejected = await client.post(
        f"{API}/feedbacks/{feedback_id}/reject",
        json={"version": 1, "reason": "다른 작품 첨삭이 섞임"},
        headers=student.headers,
    )
    assert rejected.json()["status"] == "REJECTED"
    # 반려 후 재생성
    assert (
        await client.post(f"{base}/summary/regenerate", headers=student.headers)
    ).status_code == 202
    assert await ai.drain() == 1
    new_id = (await client.get(f"{base}/summary", headers=student.headers)).json()["feedback_id"]
    approved = await client.post(
        f"{API}/feedbacks/{new_id}/approve", json={"version": 1}, headers=student.headers
    )
    assert approved.status_code == 200 and approved.json()["review_mode"] == "SELF"
    archive = (
        await client.get(f"{API}/artworks/{artwork_id}/feedbacks", headers=student.headers)
    ).json()
    assert [f["id"] for f in archive] == [new_id]
    history = (
        await client.get(f"{API}/feedbacks/{new_id}/history", headers=student.headers)
    ).json()
    assert [h["actor_mode"] for h in history] == [None, "SELF"]


# ============================================================================ 실패·재시도·복구


async def test_stt_failures_retry_and_recovery(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, ai: Ai, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    await client.post(f"{base}/transcription", headers=student.headers)

    # 재시도 가능한 오류 3번 → 백오프 후 다시 QUEUED, 마지막에 FAILED
    ai.stt.outcomes.extend([SttError("STT_TIMEOUT", "t", retryable=True)] * 3)
    for attempt in (1, 2, 3):
        await _sql(app, "UPDATE ai_processing_jobs SET run_after = now()")
        assert await ai.drain(1) == 1
        job = (await client.get(f"{base}/transcription", headers=student.headers)).json()
        assert job["job"]["attempts"] == attempt
        assert job["job"]["error_code"] == "STT_TIMEOUT"
    assert job["job"]["status"] == "FAILED" and job["job"]["retryable"] is True
    assert job["transcription_status"] == "FAILED"
    # QUEUED 대기 중(run_after 미래)인 작업은 실행하지 않는다
    assert await ai.drain() == 0

    # 재시도 API → 새 작업 → 성공
    retry = await client.post(f"{base}/transcription/retry", headers=student.headers)
    assert retry.status_code == 202 and retry.json()["id"] != job["job"]["id"]
    not_retryable = await client.post(f"{base}/transcription/retry", headers=student.headers)
    assert not_retryable.status_code == 200  # 진행 중 작업 반환
    assert await ai.drain() == 1
    status = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert status["transcription_status"] == "COMPLETED"
    assert (await client.post(f"{base}/transcription/retry", headers=student.headers)).json()[
        "error"
    ]["code"] == "JOB_NOT_RETRYABLE"


async def test_non_retryable_stt_error_fails_immediately(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    await client.post(f"{base}/transcription", headers=student.headers)
    ai.stt.outcomes.append(SttError("EMPTY_TRANSCRIPT", "none", retryable=False))
    assert await ai.drain() == 1
    job = (await client.get(f"{base}/transcription", headers=student.headers)).json()["job"]
    assert (job["status"], job["attempts"], job["error_code"]) == ("FAILED", 1, "EMPTY_TRANSCRIPT")


async def test_gemini_errors_retry_and_usage(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, ai: Ai, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    await client.post(f"{base}/transcription", headers=student.headers)
    await ai.drain()
    await _ai_consent(client, student)
    await client.post(f"{base}/summary", headers=student.headers)

    rate_limited = LlmError("LLM_RATE_LIMITED", "429", retryable=True)
    ai.llm.outcomes.extend([rate_limited, "{not json", ai_json()])
    for expected in ("LLM_RATE_LIMITED", "LLM_INVALID_OUTPUT"):
        await _sql(app, "UPDATE ai_processing_jobs SET run_after = now()")
        await ai.drain(1)
        job = (await client.get(f"{base}/summary", headers=student.headers)).json()["job"]
        assert (job["status"], job["error_code"]) == ("QUEUED", expected)
    await _sql(app, "UPDATE ai_processing_jobs SET run_after = now()")
    await ai.drain(1)
    status = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert status["job"]["status"] == "SUCCEEDED" and status["feedback_status"] == "DRAFT"
    usage = await _sql(
        app,
        "SELECT attempts, api_call_count, input_tokens FROM ai_processing_jobs"
        " WHERE job_type = 'SUMMARIZE'",
    )
    assert tuple(usage[0]) == (3, 3, 240)  # 3번 호출, 토큰은 응답을 받은 2번만

    # 재시도 불가 오류 → 즉시 FAILED
    await client.post(f"{base}/summary/regenerate", headers=student.headers)
    ai.llm.outcomes.append(LlmError("LLM_AUTH_FAILED", "401", retryable=False))
    await ai.drain()
    job = (await client.get(f"{base}/summary", headers=student.headers)).json()["job"]
    assert (job["status"], job["error_code"]) == ("FAILED", "LLM_AUTH_FAILED")


async def test_worker_crash_recovery(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, ai: Ai, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    await client.post(f"{base}/transcription", headers=student.headers)

    # Worker A가 작업을 잡은 뒤 죽음 (lease 만료 전에는 다른 Worker가 가져가지 않음)
    crashed = JobRunner(
        app.state.database,
        app.state.settings,
        stt=ai.stt,
        llm=ai.llm,
        fetcher=ai.fetcher,
        worker_id="crashed",
    )
    job_id = await crashed.claim()
    assert job_id is not None
    assert await ai.drain() == 0
    await _sql(app, "UPDATE ai_processing_jobs SET lease_expires_at = now() - interval '1 second'")
    # Worker B(재시작)가 회수해서 완료
    assert await ai.drain() == 1
    job = (await client.get(f"{base}/transcription", headers=student.headers)).json()["job"]
    assert (job["id"], job["status"], job["attempts"]) == (str(job_id), "SUCCEEDED", 2)

    # 늦게 깨어난 Worker A는 결과를 저장하지 못한다 (이미 B가 끝냄)
    await crashed._process(job_id)
    job = (await client.get(f"{base}/transcription", headers=student.headers)).json()["job"]
    assert job["status"] == "SUCCEEDED" and job["error_code"] is None
    count = await _sql(app, "SELECT count(*) FROM feedback_transcripts")
    assert count[0][0] == 1


async def test_crash_on_last_attempt_marks_worker_lost(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, ai: Ai, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    await client.post(f"{base}/transcription", headers=student.headers)
    await _sql(
        app,
        "UPDATE ai_processing_jobs SET status = 'RUNNING', attempts = max_attempts,"
        " locked_by = 'dead', lease_expires_at = now() - interval '1 second'",
    )
    assert await ai.drain() == 0
    status = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert status["job"]["error_code"] == "WORKER_LOST" and status["job"]["status"] == "FAILED"
    assert status["transcription_status"] == "FAILED"


async def test_concurrent_requests_create_one_job(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    responses = await asyncio.gather(
        *[client.post(f"{base}/transcription", headers=student.headers) for _ in range(5)]
    )
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 200, 202]
    assert len({r.json()["id"] for r in responses}) == 1
    assert (await _sql(app, "SELECT count(*) FROM ai_processing_jobs"))[0][0] == 1


async def test_two_workers_do_not_take_the_same_job(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, ai: Ai, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    await client.post(f"{_base(artwork_id, recording_id)}/transcription", headers=student.headers)
    other = JobRunner(
        app.state.database,
        app.state.settings,
        stt=ai.stt,
        llm=ai.llm,
        fetcher=ai.fetcher,
        worker_id="w2",
    )
    claimed = await asyncio.gather(ai.runner.claim(), other.claim())
    assert sum(c is not None for c in claimed) == 1


# ============================================================================ 동의·삭제


async def test_consent_revocation_blocks_and_cancels(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, ai: Ai, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    await client.post(f"{base}/transcription", headers=student.headers)
    await ai.drain()
    await _ai_consent(client, student)
    status = (await client.get(f"{API}/ai-processing-consents/me", headers=student.headers)).json()
    assert status["is_valid"] and status["consent"]["provider"] == "OPENAI"

    # 대기 중 요약 작업 → 철회하면 취소
    await client.post(f"{base}/summary", headers=student.headers)
    assert (
        await client.delete(f"{API}/ai-processing-consents/me", headers=student.headers)
    ).status_code == 204
    job = (await client.get(f"{base}/summary", headers=student.headers)).json()["job"]
    assert (job["status"], job["error_code"]) == ("CANCELLED", "AI_CONSENT_REVOKED")
    assert await ai.drain() == 0 and ai.llm.prompts == []  # 외부 전송 없음
    blocked = await client.post(f"{base}/summary", headers=student.headers)
    assert blocked.json()["error"]["code"] == "AI_CONSENT_REQUIRED"

    # 처리 중(Worker가 잡은 상태)에 철회 → 결과를 저장하지 않음
    await _ai_consent(client, student)
    await client.post(f"{base}/summary", headers=student.headers)
    job_id = await ai.runner.claim()
    assert job_id is not None
    await client.delete(f"{API}/ai-processing-consents/me", headers=student.headers)
    await ai.runner._process(job_id)
    assert (await _sql(app, "SELECT count(*) FROM feedback_summaries"))[0][0] == 0
    # 동의 이력은 보존 (철회 시각만 기록)
    rows = await _sql(app, "SELECT revoked_at IS NOT NULL FROM ai_processing_consents")
    assert [r[0] for r in rows] == [True, True]


async def test_recording_consent_revocation_blocks_transcription(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, ai: Ai
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    await client.post(f"{base}/transcription", headers=student.headers)
    await client.delete(f"{API}/recording-consents/me", headers=student.headers)
    status = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert status["job"]["status"] == "CANCELLED"
    assert status["job"]["error_code"] == "RECORDING_CONSENT_REVOKED"
    assert await ai.drain() == 0 and ai.stt.calls == []
    retry = await client.post(f"{base}/transcription/retry", headers=student.headers)
    assert retry.json()["error"]["code"] == "RECORDING_CONSENT_REQUIRED"


async def test_deleting_recording_purges_ai_data(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, ai: Ai, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    await _ai_consent(client, student)
    await client.post(
        f"{base}/transcription", json={"auto_summarize": True}, headers=student.headers
    )
    await ai.drain()
    # 두 번째 녹음은 전사 대기 중
    second = await _record(client, audio, student, artwork_id)
    second_base = _base(artwork_id, second.json()["id"])
    await client.post(f"{second_base}/transcription", headers=student.headers)

    assert (
        await client.delete(
            f"{API}/artworks/{artwork_id}/recordings/{recording_id}", headers=student.headers
        )
    ).status_code == 204
    counts = await _sql(
        app,
        "SELECT (SELECT count(*) FROM feedback_transcripts),"
        " (SELECT count(*) FROM feedback_summaries)",
    )
    assert tuple(counts[0]) == (0, 0)
    # 작품 삭제 → 대기 중 작업 취소
    assert (
        await client.delete(f"{API}/artworks/{artwork_id}", headers=student.headers)
    ).status_code == 204
    statuses = await _sql(
        app,
        "SELECT status, last_error_code FROM ai_processing_jobs"
        " WHERE job_type = 'TRANSCRIBE' ORDER BY created_at",
    )
    assert tuple(statuses[-1]) == ("CANCELLED", "RECORDING_DELETED")
    assert await ai.drain() == 0


async def test_processing_disabled_returns_503(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    settings = app.state.settings
    settings.stt_enabled, settings.ai_summary_enabled = False, False
    try:
        stt = await client.post(f"{base}/transcription", headers=student.headers)
        summary = await client.post(f"{base}/summary", headers=student.headers)
    finally:
        settings.stt_enabled, settings.ai_summary_enabled = True, True
    assert (stt.status_code, stt.json()["error"]["code"]) == (503, "STT_NOT_CONFIGURED")
    assert (summary.status_code, summary.json()["error"]["code"]) == (503, "AI_NOT_CONFIGURED")


async def test_ai_consent_validation(client: httpx.AsyncClient, actors) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    old = await client.post(
        f"{API}/ai-processing-consents",
        json={"policy_version": "old", "agreed": True},
        headers=student.headers,
    )
    assert old.status_code == 422
    disagreed = await client.post(
        f"{API}/ai-processing-consents",
        json={"policy_version": AI_VERSION, "agreed": False},
        headers=student.headers,
    )
    assert disagreed.status_code == 422
    teacher = await actors.signup("INSTRUCTOR")
    assert (
        await client.get(f"{API}/ai-processing-consents/me", headers=teacher.headers)
    ).status_code == 403
    # v0.9.6: 연령 확인(생년월) 필수, granted_by는 서버가 연령으로 정한다
    no_age = await client.post(
        f"{API}/ai-processing-consents",
        json={"policy_version": AI_VERSION, "agreed": True},
        headers=student.headers,
    )
    assert (no_age.status_code, no_age.json()["error"]["code"]) == (422, "AI_AGE_REQUIRED")
    adult = await client.post(
        f"{API}/ai-processing-consents",
        json={
            "policy_version": AI_VERSION,
            "agreed": True,
            "birth_year_month": "2000-01",
            "granted_by": "GUARDIAN",
        },
        headers=student.headers,
    )
    assert adult.json()["consent"]["granted_by"] == "SELF"
    assert adult.json()["consent"]["age_band"] == "ADULT" and adult.json()["is_valid"]
    assert (
        await client.delete(f"{API}/ai-processing-consents/me", headers=student.headers)
    ).status_code == 204
    assert (
        await client.delete(f"{API}/ai-processing-consents/me", headers=student.headers)
    ).status_code == 404


async def test_duplicate_insert_race_returns_existing_job(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, audio: FakeStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """진행 중 작업 확인과 INSERT 사이에 다른 요청이 끼어든 경우.

    부분 유니크 위반 → 기존 작업 반환.

    rollback 후 만료된 ORM 객체를 다시 읽지 않아야 한다 (CI에서 발견된 MissingGreenlet 500).
    """
    from app.services.ai_feedback import AiFeedbackService

    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    first = await client.post(f"{base}/transcription", headers=student.headers)
    assert first.status_code == 202

    original = AiFeedbackService._active_job
    calls = {"n": 0}

    async def racing(self, recording_id, job_type):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:  # 첫 확인에서는 아직 없는 것처럼 → INSERT가 유니크 위반
            return None
        return await original(self, recording_id, job_type)

    monkeypatch.setattr(AiFeedbackService, "_active_job", racing)
    second = await client.post(f"{base}/transcription", headers=student.headers)
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
