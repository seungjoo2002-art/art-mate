"""v0.9.6 오래 대기한 작업의 Worker 재요청, 운영 상태 API, 서버 STT → AI 요약 모의 통합.

GitHub(workflow_dispatch)·OpenAI 모두 httpx.MockTransport — 실제 호출 없음.
"""

import httpx
from pydantic import SecretStr

from app.services.worker_dispatch import WorkerDispatcher
from tests.db.test_ai_feedback_api import AI_VERSION, _base, _sql
from tests.db.test_recordings_api import _consent, _record
from tests.db.test_worker_openai_pipeline import _worker

API = "/api/v1"


class GitHubMock:
    def __init__(self, status: int = 204) -> None:
        self.calls: list[httpx.Request] = []
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(self.status)


def _dispatch_on(app, github: GitHubMock, **settings) -> WorkerDispatcher:  # type: ignore[no-untyped-def]
    app.state.settings = app.state.settings.model_copy(
        update={"worker_dispatch_token": SecretStr("ghp_mock")} | settings
    )
    dispatcher = WorkerDispatcher(transport=httpx.MockTransport(github.handler))
    app.state.worker_dispatcher = dispatcher
    return dispatcher


async def _queued_transcription(client, app, student, *, auto: bool = False) -> str:  # type: ignore[no-untyped-def]
    artwork = await client.post(f"{API}/artworks", json={"title": "정물"}, headers=student.headers)
    assert (await _consent(client, student)).status_code in (200, 201)
    recorded = await _record(client, app.state.audio_storage, student, artwork.json()["id"])
    base = _base(artwork.json()["id"], recorded.json()["id"])
    queued = await client.post(
        f"{base}/transcription", json={"auto_summarize": auto}, headers=student.headers
    )
    assert queued.status_code == 202, queued.text
    return base


async def _age_jobs(app, minutes: int) -> None:  # type: ignore[no-untyped-def]
    await _sql(
        app,
        "UPDATE ai_processing_jobs SET run_after = now() - make_interval(mins => :m)"
        " WHERE status = 'QUEUED'",
        m=minutes,
    )


async def test_status_poll_redispatches_stale_jobs_once_per_interval(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    github = GitHubMock()
    student = await actors.signup("STUDENT")
    # 토큰 없이 만든 작업 = 처음 실행 요청을 못 받은 작업 (운영에서 대기 중인 작업과 같은 상황)
    base = await _queued_transcription(client, app, student)
    _dispatch_on(app, github)

    # 아직 오래되지 않음(2분 미만) → 요청 안 함
    await client.get(f"{base}/transcription", headers=student.headers)
    assert github.calls == []

    await _age_jobs(app, 30)
    await client.get(f"{base}/transcription", headers=student.headers)
    assert len(github.calls) == 1
    call = github.calls[0]
    assert call.url.path.endswith("/actions/workflows/stt-worker.yml/dispatches")
    assert call.read() == b'{"ref":"main"}'  # 작업·사용자 정보 없음

    # 카드가 계속 확인해도 재요청 간격(10분) 안에는 한 번뿐
    for _ in range(5):
        await client.get(f"{base}/transcription", headers=student.headers)
        await client.get(f"{base}/summary", headers=student.headers)
    assert len(github.calls) == 1


async def test_deferred_backup_job_is_redispatched_once_due(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    github = GitHubMock()
    _dispatch_on(app, github)
    student = await actors.signup("STUDENT")
    artwork = await client.post(f"{API}/artworks", json={"title": "정물"}, headers=student.headers)
    await _consent(client, student)
    recorded = await _record(client, app.state.audio_storage, student, artwork.json()["id"])
    base = _base(artwork.json()["id"], recorded.json()["id"])
    backup = await client.post(
        f"{base}/transcription", json={"defer_seconds": 900}, headers=student.headers
    )
    assert backup.status_code == 202
    await client.get(f"{base}/transcription", headers=student.headers)
    assert github.calls == []  # 아직 실행 시각 전

    # 기기 변환이 끝나지 못하고 실행 시각이 지남 → 상태 확인 때 Worker 실행 요청
    await _age_jobs(app, 5)
    await client.get(f"{base}/transcription", headers=student.headers)
    assert len(github.calls) == 1


async def test_no_token_or_no_jobs_means_no_request(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    github = GitHubMock()
    student = await actors.signup("STUDENT")
    base = await _queued_transcription(client, app, student)
    await _age_jobs(app, 30)
    app.state.worker_dispatcher = WorkerDispatcher(transport=httpx.MockTransport(github.handler))
    await client.get(f"{base}/transcription", headers=student.headers)  # 토큰 없음
    assert github.calls == []

    await _sql(app, "UPDATE ai_processing_jobs SET status = 'CANCELLED', finished_at = now()")
    _dispatch_on(app, github)
    await client.get(f"{base}/transcription", headers=student.headers)  # 대기 작업 없음
    assert github.calls == []


async def test_worker_status_shows_configuration_queue_and_last_result(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    off = (await client.get(f"{API}/meta/worker-status")).json()
    assert off["dispatch_configured"] is False and off["last_dispatch"] is None

    github = GitHubMock(status=403)  # 권한 없는 토큰
    student = await actors.signup("STUDENT")
    base = await _queued_transcription(client, app, student)
    await _age_jobs(app, 45)
    _dispatch_on(app, github)
    await client.get(f"{base}/transcription", headers=student.headers)

    status = await client.get(f"{API}/meta/worker-status")
    assert status.headers["cache-control"] == "no-store"
    body = status.json()
    assert body["dispatch_configured"] is True
    assert body["due_jobs"] >= 1 and body["oldest_due_minutes"] >= 44
    assert body["last_dispatch"]["ok"] is False and body["last_dispatch"]["status"] == 403
    assert body["last_dispatch"]["reason"] == "stale"
    assert "ghp_mock" not in status.text


async def test_stale_server_transcription_to_ai_summary(  # type: ignore[no-untyped-def]
    client: httpx.AsyncClient, actors, app
) -> None:
    """운영 상황 재현: 실행 요청을 못 받은 서버 전사(요약 이어받기) → 상태 확인 시 재요청 →
    Worker 실행 → STT 완료 → 요약 작업 자동 생성 → OpenAI(모의)로 요약 → 결과 저장."""
    github = GitHubMock()
    student = await actors.signup("STUDENT")
    granted = await client.post(
        f"{API}/ai-processing-consents",
        json={"policy_version": AI_VERSION, "agreed": True, "birth_year_month": "1999-01"},
        headers=student.headers,
    )
    assert granted.json()["is_valid"]
    base = await _queued_transcription(client, app, student, auto=True)
    await _age_jobs(app, 400)  # 6시간 넘게 대기
    _dispatch_on(app, github)

    await client.get(f"{base}/transcription", headers=student.headers)
    assert len(github.calls) == 1  # Worker 실행 요청됨

    calls: list[dict] = []
    stats = await _worker(app, calls).run_batch(max_jobs=10, max_seconds=60, maintenance=False)
    assert stats["processed"] == 2  # TRANSCRIBE → SUMMARIZE
    assert len(calls) == 1 and calls[0]["store"] is False
    assert (await client.get(f"{base}/transcription", headers=student.headers)).json()[
        "transcription_status"
    ] == "COMPLETED"
    summary = (await client.get(f"{base}/summary", headers=student.headers)).json()
    assert summary["job"]["status"] == "SUCCEEDED" and summary["feedback_id"]
    # 처리 후에는 대기 작업이 없어 더 요청하지 않음
    status = (await client.get(f"{API}/meta/worker-status")).json()
    assert status["due_jobs"] == 0 and status["oldest_due_minutes"] is None
