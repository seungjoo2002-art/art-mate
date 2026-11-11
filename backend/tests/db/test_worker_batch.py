"""GitHub Actions 일괄 Worker (v0.9.1): 처리 종류 선택·작업 수/시간 제한·전사→요약→확정 흐름.

STT·Gemini·음성 다운로드는 가짜 구현. 실제 GitHub Actions 실행은 이 테스트로 검증되지 않는다.
"""

import httpx
from sqlalchemy import text

from app.integrations.ai.gemini import LlmError
from app.models.enums import AiJobType
from app.worker import runner as runner_module
from app.worker.runner import JobRunner
from tests.db.test_ai_feedback_api import _ai_consent, _base, _recording
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt

API = "/api/v1"


def _runner(app, *, stt=None, llm=None, types=None, name="gha"):  # type: ignore[no-untyped-def]
    return JobRunner(
        app.state.database,
        app.state.settings,
        stt=stt,
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id=name,
        job_types=types,
    )


async def _jobs(app) -> list[tuple[str, str, int]]:  # type: ignore[no-untyped-def]
    async with app.state.database.engine.begin() as conn:
        rows = await conn.execute(
            text("SELECT job_type, status, attempts FROM ai_processing_jobs ORDER BY created_at")
        )
        return [tuple(r) for r in rows.all()]


async def test_batch_stt_then_summary_then_confirm(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, monkeypatch
) -> None:
    student = await actors.signup("STUDENT")  # 학원 없는 학생
    audio = app.state.audio_storage
    await _ai_consent(client, student)
    first = await _recording(client, audio, student)
    second = await _recording(client, audio, student)
    for artwork_id, recording_id in (first, second):
        queued = await client.post(
            f"{_base(artwork_id, recording_id)}/transcription",
            json={"auto_summarize": True},
            headers=student.headers,
        )
        assert queued.status_code == 202

    stt = FakeStt()
    # Gemini 키가 없는 실행: 전사만 가져가고 요약 작업은 실패시키지 않고 남긴다
    stt_only = _runner(app, stt=stt, types=frozenset({AiJobType.TRANSCRIBE}))
    assert await stt_only.pending_counts() == {"TRANSCRIBE": 2}
    stats = await stt_only.run_batch(max_jobs=1, max_seconds=600, maintenance=False)
    assert stats["processed"] == 1  # 작업 수 제한
    stats = await stt_only.run_batch(max_jobs=10, max_seconds=600, maintenance=False)
    assert stats["processed"] == 1  # 큐가 비면 종료 (연쇄 요약은 이 Worker 대상이 아님)
    assert len(stt.calls) == 2
    assert sorted(await _jobs(app)) == [
        ("SUMMARIZE", "QUEUED", 0),
        ("SUMMARIZE", "QUEUED", 0),
        ("TRANSCRIBE", "SUCCEEDED", 1),
        ("TRANSCRIBE", "SUCCEEDED", 1),
    ]
    base = _base(*first)
    status = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert status["transcription_status"] == "COMPLETED" and status["job"]["status"] == "SUCCEEDED"
    summary = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert summary["job"]["status"] == "QUEUED" and summary["feedback_id"] is None

    # 제한 시간이 지나면 새 작업을 잡지 않는다 (시계를 100초씩 진행)
    llm = FakeLlm()
    llm_only = _runner(app, llm=llm, types=frozenset({AiJobType.SUMMARIZE}), name="gha-llm")
    ticks = iter(range(0, 10_000, 100))
    with monkeypatch.context() as m:
        m.setattr(runner_module.time, "monotonic", lambda: next(ticks))
        stats = await llm_only.run_batch(max_jobs=10, max_seconds=50, maintenance=False)
    assert stats["processed"] == 0
    # Gemini 할당량 초과 → 재시도 대기(QUEUED, 백오프), 다음 실행에서 처리
    llm.outcomes.append(LlmError("LLM_RATE_LIMITED", "quota", retryable=True))
    stats = await llm_only.run_batch(max_jobs=10, max_seconds=600, maintenance=False)
    assert stats["processed"] == 2
    statuses = sorted((t, s) for t, s, _ in await _jobs(app) if t == "SUMMARIZE")
    assert statuses == [("SUMMARIZE", "QUEUED"), ("SUMMARIZE", "SUCCEEDED")]
    async with app.state.database.engine.begin() as conn:
        await conn.execute(text("UPDATE ai_processing_jobs SET run_after = now()"))
    stats = await llm_only.run_batch(max_jobs=10, max_seconds=600, maintenance=False)
    assert stats["processed"] == 1
    assert all(s == "SUCCEEDED" for _, s, _ in await _jobs(app))

    # 학생이 전사·AI 요약을 확인하고 확정 → 성장 분석 데이터
    summary = (await client.get(f"{base}/summary", headers=student.headers)).json()
    feedback = (
        await client.get(f"{API}/feedbacks/{summary['feedback_id']}", headers=student.headers)
    ).json()
    assert feedback["review_mode"] == "SELF" and feedback["weaknesses"][0]["evidence"][0]["text"]
    approved = await client.post(
        f"{API}/feedbacks/{feedback['id']}/approve", json={"version": 1}, headers=student.headers
    )
    assert approved.json()["status"] == "APPROVED"
    weak = (await client.get(f"{API}/growth/me/weaknesses", headers=student.headers)).json()
    assert weak["totals"]["approved_feedback_count"] == 1


async def test_batch_runs_maintenance_and_skips_when_no_capability(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, app.state.audio_storage, student)
    await client.post(f"{_base(artwork_id, recording_id)}/transcription", headers=student.headers)
    nothing = _runner(app, types=frozenset())
    stats = await nothing.run_batch(max_jobs=5, max_seconds=60)
    assert stats == {"processed": 0, "expired_audio": 0, "notifications": 0}
    assert await _jobs(app) == [("TRANSCRIBE", "QUEUED", 0)]
    # 기존 상시 Worker(종류 제한 없음)는 그대로 모든 작업을 가져간다
    legacy = _runner(app, stt=FakeStt(), name="legacy")
    assert legacy.job_types is None and await legacy.run_once() is True
