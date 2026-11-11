"""v0.9.2 브라우저 STT 결과 저장: 소유권·검증·서버(GitHub Actions) 전사와 중복 방지·요약 연결."""

import httpx
from sqlalchemy import text

from app.models.enums import AiJobType
from app.worker.runner import JobRunner
from tests.db.test_ai_feedback_api import _ai_consent, _base, _recording
from tests.fake_ai import FakeFetcher, FakeLlm, FakeStt

API = "/api/v1"
SEGMENTS = [
    {"start_ms": 0, "end_ms": 3500, "text": "전체적으로 구도는 안정적으로 잘 잡았어."},
    {
        "start_ms": 4000,
        "end_ms": 7500,
        "text": "근데 오른쪽 사과의 명암이 너무 약해서 형태가 떠 보여.",
    },
    {
        "start_ms": 8000,
        "end_ms": 11500,
        "text": "어두운 면을 한 톤 더 눌러주고 반사광은 조금만 남겨.",
    },
    {
        "start_ms": 12000,
        "end_ms": 15500,
        "text": "다음 작품에서는 처음부터 큰 덩어리 명암을 먼저 잡자.",
    },
]


def _body(**overrides):  # type: ignore[no-untyped-def]
    return {
        "device": "webgpu",
        "model_name": "onnx-community/whisper-base",
        "segments": SEGMENTS,
        "processing_ms": 2100,
    } | overrides


def _runner(app, **kwargs):  # type: ignore[no-untyped-def]
    return JobRunner(
        app.state.database,
        app.state.settings,
        fetcher=FakeFetcher(app.state.audio_storage),
        worker_id="gha",
        **({"stt": FakeStt(), "llm": FakeLlm()} | kwargs),
    )


async def _sql(app, sql: str, **params):  # type: ignore[no-untyped-def]
    async with app.state.database.engine.begin() as conn:
        result = await conn.execute(text(sql), params)
        return result.all() if result.returns_rows else []


async def test_browser_transcript_replaces_queued_server_job(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    artwork_id, recording_id = await _recording(client, app.state.audio_storage, student)
    base = _base(artwork_id, recording_id)
    # 대체 경로(서버 전사)가 먼저 큐에 들어가 있어도 브라우저 결과가 오면 취소
    queued = await client.post(f"{base}/transcription", headers=student.headers)
    assert queued.status_code == 202

    saved = await client.post(
        f"{base}/transcript/browser", json=_body(auto_summarize=True), headers=student.headers
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    transcript = body["transcript"]
    assert (transcript["origin"], transcript["engine"], transcript["model_name"]) == (
        "BROWSER",
        "browser-webgpu",
        "onnx-community/whisper-base",
    )
    assert [s["index"] for s in transcript["segments"]] == [0, 1, 2, 3]
    assert body["summary_job"]["job_type"] == "SUMMARIZE"
    status = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert status["transcription_status"] == "COMPLETED"
    assert (status["job"]["status"], status["job"]["error_code"]) == (
        "CANCELLED",
        "BROWSER_TRANSCRIBED",
    )
    assert status["transcript"]["origin"] == "BROWSER"

    # GitHub Actions Worker는 요약만 처리 (취소된 전사는 가져가지 않음)
    runner = _runner(app)
    stats = await runner.run_batch(max_jobs=10, max_seconds=60, maintenance=False)
    assert stats["processed"] == 1 and runner.stt.calls == []
    summary = (await client.get(f"{base}/summary", headers=student.headers)).json()
    feedback = (
        await client.get(f"{API}/feedbacks/{summary['feedback_id']}", headers=student.headers)
    ).json()
    assert feedback["weaknesses"][0]["evidence"][0]["text"] == SEGMENTS[1]["text"]
    assert feedback["dropped_item_count"] == 0  # 근거 대조 통과

    # 이미 전사됨 → 다시 저장·서버 요청 모두 409
    again = await client.post(f"{base}/transcript/browser", json=_body(), headers=student.headers)
    assert again.json()["error"]["code"] == "TRANSCRIPTION_ALREADY_DONE"
    server = await client.post(f"{base}/transcription", headers=student.headers)
    assert server.json()["error"]["code"] == "TRANSCRIPTION_ALREADY_DONE"

    # 수정·원본 보존은 기존과 같다
    edited = await client.put(
        f"{base}/transcript",
        json={"base_transcript_id": transcript["id"], "segments": [{"index": 1, "text": "수정"}]},
        headers=student.headers,
    )
    # 요약이 아직 초안(DRAFT)이면 수정 가능 (초안은 대체됨), 원본 브라우저 전사는 보존
    assert edited.status_code == 200, edited.text
    assert edited.json()["origin"] == "EDITED"
    assert edited.json()["edited_from_id"] == transcript["id"]


async def test_browser_and_worker_race(client: httpx.AsyncClient, actors, app) -> None:  # type: ignore[no-untyped-def]
    student = await actors.signup("STUDENT")
    audio = app.state.audio_storage
    # 1) Worker가 작업을 잡은 상태에서 브라우저 결과 도착 → 브라우저 결과 저장, Worker 결과는 버림
    artwork_id, recording_id = await _recording(client, audio, student)
    base = _base(artwork_id, recording_id)
    await client.post(f"{base}/transcription", headers=student.headers)
    runner = _runner(app, job_types=frozenset({AiJobType.TRANSCRIBE}))
    job_id = await runner.claim()
    assert job_id is not None
    saved = await client.post(f"{base}/transcript/browser", json=_body(), headers=student.headers)
    assert saved.status_code == 201
    await runner._process(job_id)
    rows = await _sql(
        app,
        "SELECT engine FROM feedback_transcripts WHERE recording_id = :r",
        r=recording_id,
    )
    assert [r[0] for r in rows] == ["browser-webgpu"]
    status = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert status["job"]["status"] == "CANCELLED"

    # 2) Worker가 먼저 저장 → 늦게 온 브라우저 결과는 409 (전사 1개 유지)
    artwork2, recording2 = await _recording(client, audio, student)
    base2 = _base(artwork2, recording2)
    await client.post(f"{base2}/transcription", headers=student.headers)
    assert (await runner.run_batch(max_jobs=5, max_seconds=60, maintenance=False))["processed"] == 1
    late = await client.post(f"{base2}/transcript/browser", json=_body(), headers=student.headers)
    assert late.status_code == 409 and late.json()["error"]["code"] == "TRANSCRIPTION_ALREADY_DONE"
    origin = (await client.get(f"{base2}/transcript", headers=student.headers)).json()["origin"]
    assert origin == "SERVER"


async def test_browser_transcript_validation_and_access(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, app.state.audio_storage, student)
    url = f"{_base(artwork_id, recording_id)}/transcript/browser"
    too_long = [{"start_ms": 0, "end_ms": 60_000, "text": "녹음보다 긴 구간"}]  # 녹음 42초
    unordered = [SEGMENTS[1], SEGMENTS[0]]
    for bad in (
        _body(segments=too_long),
        _body(segments=unordered),
        _body(segments=[]),
        _body(device="cuda"),
        _body(model_name="https://evil.example/model"),
        _body(language="en"),
        _body(segments=[{"start_ms": 5, "end_ms": 1, "text": "x"}]),
    ):
        response = await client.post(url, json=bad, headers=student.headers)
        assert response.status_code == 422, bad
    other = await actors.signup("STUDENT")
    assert (await client.post(url, json=_body(), headers=other.headers)).status_code == 404
    teacher = await actors.signup("INSTRUCTOR")
    assert (await client.post(url, json=_body(), headers=teacher.headers)).status_code == 403
    # 녹음 동의를 철회하면 저장 불가
    await client.delete(f"{API}/recording-consents/me", headers=student.headers)
    revoked = await client.post(url, json=_body(device="wasm"), headers=student.headers)
    assert revoked.json()["error"]["code"] == "RECORDING_CONSENT_REQUIRED"
