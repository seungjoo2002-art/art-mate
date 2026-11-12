"""모의 통합: GitHub Actions Worker가 STT 완료 후 AI 요약을 이어받아 OpenAI Responses API로 처리.

실제 OpenAI 호출 없음 — `OpenAiClient`를 그대로 쓰고 HTTP만 httpx.MockTransport로 대신한다.
Worker 실행 방식(`supported_job_types` + `run_batch`)도 `python -m app.worker --once`와 같다.
"""

import json

import httpx
from pydantic import SecretStr

from app.integrations.ai.openai_llm import OpenAiClient
from app.worker.__main__ import supported_job_types
from app.worker.runner import JobRunner
from tests.db.test_ai_feedback_api import AI_VERSION, _base, _sql
from tests.db.test_recordings_api import _consent, _record
from tests.fake_ai import FakeFetcher, FakeStt, ai_json

API = "/api/v1"


def _openai_mock(calls: list[dict]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append({"url": str(request.url), "auth": request.headers["authorization"], **body})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {"type": "reasoning", "summary": []},
                    {"type": "message", "content": [{"type": "output_text", "text": ai_json()}]},
                ],
                "usage": {"input_tokens": 900, "output_tokens": 400},
            },
        )

    return httpx.MockTransport(handler)


def _worker(app, calls: list[dict]) -> JobRunner:  # type: ignore[no-untyped-def]
    settings = app.state.settings.model_copy(
        update={"ai_provider": "openai", "openai_api_key": SecretStr("sk-mock")}
    )
    llm = OpenAiClient(settings, transport=_openai_mock(calls))
    return JobRunner(
        app.state.database,
        settings,
        stt=FakeStt(),
        llm=llm,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="gha-mock",
        job_types=supported_job_types(settings, has_stt=True, has_llm=True),
    )


async def _server_transcription(client, app, student, *, auto: bool) -> str:  # type: ignore[no-untyped-def]
    artwork = await client.post(f"{API}/artworks", json={"title": "정물"}, headers=student.headers)
    assert (await _consent(client, student)).status_code in (200, 201)
    recorded = await _record(client, app.state.audio_storage, student, artwork.json()["id"])
    base = _base(artwork.json()["id"], recorded.json()["id"])
    queued = await client.post(
        f"{base}/transcription", json={"auto_summarize": auto}, headers=student.headers
    )
    assert queued.status_code == 202, queued.text
    return base


async def test_worker_transcribes_then_summarizes_with_openai(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    granted = await client.post(
        f"{API}/ai-processing-consents",
        json={"policy_version": AI_VERSION, "agreed": True, "birth_year_month": "2000-01"},
        headers=student.headers,
    )
    assert granted.json()["is_valid"]
    base = await _server_transcription(client, app, student, auto=True)

    calls: list[dict] = []
    result = await _worker(app, calls).run_batch(max_jobs=10, max_seconds=60, maintenance=False)
    assert result["processed"] == 2  # TRANSCRIBE → (자동) SUMMARIZE

    assert len(calls) == 1
    call = calls[0]
    assert call["url"].endswith("/v1/responses") and call["auth"] == "Bearer sk-mock"
    assert call["model"] == "gpt-6.1-terra" and call["store"] is False
    assert call["text"]["format"]["strict"] is True
    assert "[0]" in call["input"]  # 전사 구간 번호·문장만

    summary = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert summary["job"]["status"] == "SUCCEEDED" and summary["feedback_id"]
    feedback = (
        await client.get(f"{API}/feedbacks/{summary['feedback_id']}", headers=student.headers)
    ).json()
    assert feedback["summary"] and feedback["strengths"] and feedback["next_tips"]
    usage = await _sql(
        app,
        "SELECT input_tokens, output_tokens, api_call_count FROM ai_processing_jobs"
        " WHERE job_type = 'SUMMARIZE' AND owner_id = :o",
        o=student.user_id,
    )
    assert tuple(usage[0]) == (900, 400, 1)
    model = await _sql(
        app,
        "SELECT model_name FROM feedback_summaries WHERE id = :id",
        id=summary["feedback_id"],
    )
    assert model[0][0] == "gpt-6.1-terra"


async def test_minor_gets_transcript_but_nothing_is_sent(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    pending = await client.post(
        f"{API}/ai-processing-consents",
        json={"policy_version": AI_VERSION, "agreed": True, "birth_year_month": "2010-05"},
        headers=student.headers,
    )
    assert pending.json()["reason"] == "MINOR_BLOCKED"  # 배포 기본값: 미성년자 전송 차단
    base = await _server_transcription(client, app, student, auto=True)

    calls: list[dict] = []
    await _worker(app, calls).run_batch(max_jobs=10, max_seconds=60, maintenance=False)
    assert calls == []  # 외부 전송 없음
    status = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert status["transcription_status"] == "COMPLETED"  # 대본은 정상
    summary = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert summary["feedback_id"] is None
    assert summary["job"] is None or summary["job"]["status"] != "SUCCEEDED"


async def test_legacy_gemini_consent_is_not_used_for_openai(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    # 0012 이전에 저장된 Gemini v1 동의 (운영 DB의 기존 행과 같은 모양)
    await _sql(
        app,
        "INSERT INTO ai_processing_consents (id, user_id, provider, purpose, policy_version,"
        " granted_by, granted_at) VALUES (gen_random_uuid(), :u, 'GOOGLE_GEMINI',"
        " 'FEEDBACK_SUMMARY', '2026-11-ai-v1', 'SELF', now())",
        u=student.user_id,
    )
    me = (await client.get(f"{API}/ai-processing-consents/me", headers=student.headers)).json()
    assert (me["provider"], me["is_valid"], me["consent"]) == ("OPENAI", False, None)
    base = await _server_transcription(client, app, student, auto=True)
    calls: list[dict] = []
    await _worker(app, calls).run_batch(max_jobs=10, max_seconds=60, maintenance=False)
    assert calls == []
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 409

    # OpenAI 동의 후: 새 행이 생기고 Gemini 행은 그대로, 철회도 OpenAI 행만
    await client.post(
        f"{API}/ai-processing-consents",
        json={"policy_version": AI_VERSION, "agreed": True, "birth_year_month": "1999-09"},
        headers=student.headers,
    )
    assert (
        await client.delete(f"{API}/ai-processing-consents/me", headers=student.headers)
    ).status_code == 204
    rows = await _sql(
        app,
        "SELECT provider, revoked_at IS NULL FROM ai_processing_consents WHERE user_id = :u"
        " ORDER BY provider",
        u=student.user_id,
    )
    assert [tuple(r) for r in rows] == [("GOOGLE_GEMINI", True), ("OPENAI", False)]
