"""AI·음성 변환 설정 상태: 기능 플래그, 운영자 로그, 미설정 시 동작, 하루 요청 한도."""

import logging

import httpx

from app.worker.runner import JobRunner
from tests.db.test_ai_feedback_api import _ai_consent, _base, _recording
from tests.db.test_browser_transcript import _body
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt

API = "/api/v1"


def _settings(app, **changes):  # type: ignore[no-untyped-def]
    app.state.settings = app.state.settings.model_copy(update=changes)


async def test_ai_features_flags(client: httpx.AsyncClient, app) -> None:  # type: ignore[no-untyped-def]
    on = (await client.get(f"{API}/meta/ai-features")).json()
    assert on == {
        "browser_transcription": True,
        "server_transcription": True,
        "ai_summary": True,
        "ai_summary_status": "ENABLED",
        "ai_summary_daily_limit": 20,
    }
    _settings(app, stt_enabled=False, ai_summary_enabled=False)
    off = (await client.get(f"{API}/meta/ai-features")).json()
    assert (off["server_transcription"], off["ai_summary"]) == (False, False)
    assert "GEMINI" not in str(off) and "key" not in str(off).lower()


async def test_disabled_ai_keeps_transcript_and_logs_setup(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app, caplog
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    artwork_id, recording_id = await _recording(client, app.state.audio_storage, student)
    base = _base(artwork_id, recording_id)
    _settings(app, stt_enabled=False, ai_summary_enabled=False)
    caplog.set_level(logging.WARNING, logger="app.ai.setup")

    # 서버 변환이 꺼져 있으면 503 + 운영자 로그 (사용자 응답에는 설정 이름이 없음)
    server = await client.post(f"{base}/transcription", headers=student.headers)
    assert server.status_code == 503 and server.json()["error"]["code"] == "STT_NOT_CONFIGURED"
    assert "STT_ENABLED" not in server.text
    assert any("STT_ENABLED=true on Render" in r.getMessage() for r in caplog.records)

    # 기기 전사는 서버 설정과 무관하게 저장되고, 요약만 건너뜀 (이유를 알려 줌)
    saved = await client.post(
        f"{base}/transcript/browser", json=_body(auto_summarize=True), headers=student.headers
    )
    assert saved.status_code == 201
    assert (saved.json()["summary_status"], saved.json()["summary_job"]) == ("AI_DISABLED", None)
    assert any("GEMINI_API_KEY" in r.getMessage() for r in caplog.records)
    transcript = await client.get(f"{base}/transcript", headers=student.headers)
    assert transcript.status_code == 200 and transcript.json()["origin"] == "BROWSER"

    summary = await client.post(f"{base}/summary", headers=student.headers)
    assert summary.status_code == 503 and summary.json()["error"]["code"] == "AI_NOT_CONFIGURED"
    assert "GEMINI" not in summary.text and "AI_SUMMARY_ENABLED" not in summary.text
    # 녹음 파일·전사는 그대로
    assert (await client.get(f"{base}/url", headers=student.headers)).status_code == 200

    # 설정을 켜면 같은 전사로 요약 요청 가능
    _settings(app, ai_summary_enabled=True)
    assert (await client.post(f"{base}/summary", headers=student.headers)).status_code == 202


async def test_consent_missing_status_and_worker_not_running(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")  # AI 동의 없음
    artwork_id, recording_id = await _recording(client, app.state.audio_storage, student)
    base = _base(artwork_id, recording_id)
    saved = await client.post(
        f"{base}/transcript/browser", json=_body(auto_summarize=True), headers=student.headers
    )
    assert saved.json()["summary_status"] == "CONSENT_REQUIRED"
    denied = await client.post(f"{base}/summary", headers=student.headers)
    assert denied.json()["error"]["code"] == "AI_CONSENT_REQUIRED"

    # Worker가 돌지 않으면 요약 작업은 QUEUED로 남는다 (실패로 바뀌지 않음) → 돌면 처리
    await _ai_consent(client, student)
    queued = await client.post(f"{base}/summary", headers=student.headers)
    assert queued.status_code == 202
    again = await client.post(f"{base}/summary", headers=student.headers)
    assert again.status_code == 200 and again.json()["id"] == queued.json()["id"]  # 중복 방지
    status = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert status["job"]["status"] == "QUEUED" and status["feedback_id"] is None
    runner = JobRunner(
        app.state.database,
        app.state.settings,
        stt=FakeStt(),
        llm=FakeLlm(),
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="late",
    )
    assert (await runner.run_batch(max_jobs=5, max_seconds=60, maintenance=False))["processed"] == 1
    done = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert done["feedback_id"] is not None


async def test_daily_summary_limit(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    _settings(app, ai_summary_daily_limit=2)
    statuses = []
    for _ in range(3):
        artwork_id, recording_id = await _recording(client, app.state.audio_storage, student)
        base = _base(artwork_id, recording_id)
        await client.post(f"{base}/transcript/browser", json=_body(), headers=student.headers)
        statuses.append(await client.post(f"{base}/summary", headers=student.headers))
    assert [r.status_code for r in statuses] == [202, 202, 429]
    assert statuses[2].json()["error"]["code"] == "RATE_LIMITED"
    assert int(statuses[2].headers["Retry-After"]) > 0
    # 다른 학생은 영향 없음
    other = await actors.signup("STUDENT")
    await _ai_consent(client, other)
    artwork_id, recording_id = await _recording(client, app.state.audio_storage, other)
    base = _base(artwork_id, recording_id)
    await client.post(f"{base}/transcript/browser", json=_body(), headers=other.headers)
    assert (await client.post(f"{base}/summary", headers=other.headers)).status_code == 202
