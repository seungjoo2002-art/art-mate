"""v0.9.3 기기 전사 중 백업 서버 작업(defer_seconds)과 Worker 즉시 실행 요청."""

import datetime as dt

import httpx
from pydantic import SecretStr

from app.core import timezone as clock
from tests.db.test_ai_feedback_api import _ai_consent, _base, _recording, _sql
from tests.db.test_browser_transcript import _body, _runner

API = "/api/v1"


class SpyDispatcher:
    def __init__(self) -> None:
        self.reasons: list[str] = []

    @staticmethod
    def enabled(settings) -> bool:  # type: ignore[no-untyped-def]
        return False  # 오래 대기 재요청(sweep)은 이 테스트 대상이 아님

    async def notify(self, settings, reason: str) -> bool:  # type: ignore[no-untyped-def]
        self.reasons.append(reason)
        return True


def _spy(app) -> SpyDispatcher:  # type: ignore[no-untyped-def]
    spy = SpyDispatcher()
    app.state.worker_dispatcher = spy
    return spy


async def test_deferred_backup_job_is_not_claimed_then_cancelled_by_browser(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    spy = _spy(app)
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, app.state.audio_storage, student)
    base = _base(artwork_id, recording_id)

    backup = await client.post(
        f"{base}/transcription", json={"defer_seconds": 600}, headers=student.headers
    )
    assert backup.status_code == 202, backup.text
    job = backup.json()
    next_at = dt.datetime.fromisoformat(job["next_attempt_at"])
    assert next_at > clock.utc_now() + dt.timedelta(seconds=500)
    assert spy.reasons == []  # 미뤄 둔 작업은 Worker를 깨우지 않음

    # Worker가 돌아도 아직 가져가지 않는다
    assert await _runner(app).run_once() is False

    # 기기 전사 저장 → 백업 작업 취소 (기존 BROWSER_TRANSCRIBED 흐름)
    saved = await client.post(f"{base}/transcript/browser", json=_body(), headers=student.headers)
    assert saved.status_code == 201, saved.text
    status = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert status["transcription_status"] == "COMPLETED"
    assert (status["job"]["status"], status["job"]["error_code"]) == (
        "CANCELLED",
        "BROWSER_TRANSCRIBED",
    )


async def test_backup_job_promoted_when_device_fails(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    spy = _spy(app)
    student = await actors.signup("STUDENT")
    artwork_id, recording_id = await _recording(client, app.state.audio_storage, student)
    base = _base(artwork_id, recording_id)
    first = await client.post(
        f"{base}/transcription", json={"defer_seconds": 900}, headers=student.headers
    )
    assert first.status_code == 202

    # 기기 변환 실패 → 같은 요청을 defer 0으로 → 새로 만들지 않고 앞당김 + Worker 실행 요청
    now_req = await client.post(
        f"{base}/transcription", json={"auto_summarize": False}, headers=student.headers
    )
    assert now_req.status_code == 200
    assert now_req.json()["id"] == first.json()["id"]
    assert dt.datetime.fromisoformat(now_req.json()["next_attempt_at"]) <= clock.utc_now()
    assert spy.reasons == ["transcription"]

    assert await _runner(app).run_once() is True
    status = (await client.get(f"{base}/transcription", headers=student.headers)).json()
    assert status["transcription_status"] == "COMPLETED"


async def test_defer_is_capped_and_summary_kicks_worker(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    spy = _spy(app)
    app.state.settings = app.state.settings.model_copy(update={"stt_max_defer_seconds": 60})
    student = await actors.signup("STUDENT")
    await _ai_consent(client, student)
    artwork_id, recording_id = await _recording(client, app.state.audio_storage, student)
    base = _base(artwork_id, recording_id)
    job = await client.post(
        f"{base}/transcription", json={"defer_seconds": 3600}, headers=student.headers
    )
    rows = await _sql(
        app,
        "SELECT run_after - created_at FROM ai_processing_jobs WHERE id = :id",
        id=job.json()["id"],
    )
    assert rows[0][0] <= dt.timedelta(seconds=61)

    saved = await client.post(
        f"{base}/transcript/browser", json=_body(auto_summarize=True), headers=student.headers
    )
    assert saved.json()["summary_status"] == "QUEUED"
    assert spy.reasons == ["summary"]


async def test_dispatcher_posts_workflow_dispatch_once_per_interval(app) -> None:  # type: ignore[no-untyped-def]
    from app.services.worker_dispatch import WorkerDispatcher

    calls: list[httpx.Request] = []
    responses = iter([204, 204, 403, 204])

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(next(responses))

    now = [100.0]
    dispatcher = WorkerDispatcher(transport=httpx.MockTransport(handler), monotonic=lambda: now[0])
    off = app.state.settings
    assert await dispatcher.notify(off, "summary") is False  # 토큰 없음 → 아무것도 안 함
    assert calls == []

    on = off.model_copy(
        update={
            "worker_dispatch_token": SecretStr("ghp_test"),
            "worker_dispatch_min_interval_seconds": 30,
        }
    )
    assert await dispatcher.notify(on, "summary") is True
    request = calls[0]
    assert (
        request.url.path
        == "/repos/seungjoo2002-art/art-mate/actions/workflows/stt-worker.yml/dispatches"
    )
    assert request.headers["authorization"] == "Bearer ghp_test"
    assert request.read() == b'{"ref":"main"}'

    assert await dispatcher.notify(on, "summary") is False  # 30초 안에는 합침
    now[0] += 31
    assert await dispatcher.notify(on, "transcription") is True
    now[0] += 31
    assert await dispatcher.notify(on, "summary") is False  # 403 → 실패, 다음에 다시 시도
    assert len(calls) == 3
    assert await dispatcher.notify(on, "summary") is True  # 실패 직후에는 간격 없이 다시 시도
