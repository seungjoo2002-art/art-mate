"""Worker 즉시 실행 요청 (GitHub Actions workflow_dispatch).

stt-worker 워크플로의 예약 실행(cron)은 GitHub 사정으로 실제로는 수 시간씩 밀린다
(2026-11-11~12 기록: 첫 실행이 병합 29시간 뒤, 이후 5.8~7.1시간 간격). 그래서 API가 직접 워크플로
실행을 요청한다. GitHub가 실행을 보장하지는 않으므로 예약 실행은 그대로 둔다.

실행 요청 시점 (v0.9.6 보강)
1. 작업을 큐에 넣을 때 (`notify`)
2. **오래 대기한 작업이 있을 때 (`sweep`)** — 처음 요청 실패, 토큰을 나중에 설정, 미뤄 둔
   백업 작업이 실행 시각이 된 경우. 학생 화면이 상태를 확인할 때와 API 서버의 주기 점검에서 부른다.
   같은 프로세스에서 `WORKER_REDISPATCH_INTERVAL_SECONDS`(기본 10분)에 한 번만 다시 요청한다
   (실패해도 그 간격 뒤에 다시 시도).

- 토큰(WORKER_DISPATCH_TOKEN)이 없으면 아무것도 하지 않는다.
- 요청 본문에는 작업·사용자 정보를 넣지 않는다 (Worker가 DB 큐에서 직접 가져감).
- 워크플로 concurrency 설정으로 실행 중에 들어온 요청은 다음 실행 1건으로 합쳐진다.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings

logger = logging.getLogger("app.worker_dispatch")

GITHUB_API = "https://api.github.com"


@dataclass(frozen=True, slots=True)
class QueueHealth:
    due_jobs: int  # 지금 가져갈 수 있는 작업 (실행 시각이 지난 QUEUED + lease 만료 RUNNING)
    oldest_due_at: dt.datetime | None  # 그중 가장 오래된 실행 예정 시각


async def queue_health(session: AsyncSession) -> QueueHealth:
    """대기 작업 수와 가장 오래 기다린 시각 (내용·사용자 정보는 읽지 않음)."""
    row = (
        await session.execute(
            text(
                "SELECT count(*), min(CASE WHEN status = 'QUEUED' THEN run_after"
                " ELSE lease_expires_at END) FROM ai_processing_jobs"
                " WHERE (status = 'QUEUED' AND run_after <= now())"
                "    OR (status = 'RUNNING' AND lease_expires_at < now())"
            )
        )
    ).one()
    return QueueHealth(due_jobs=int(row[0]), oldest_due_at=row[1])


@dataclass(frozen=True, slots=True)
class DispatchResult:
    at: dt.datetime
    reason: str
    ok: bool
    status: int | None  # GitHub 응답 코드 (네트워크 오류면 None)


class WorkerDispatcher:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._last_sent: float | None = None
        self._last_sweep: float | None = None
        self._monotonic = monotonic
        # 마지막 요청 결과 (운영 확인용 /meta/worker-status, 토큰·본문 없음)
        self.last_result: DispatchResult | None = None

    @staticmethod
    def enabled(settings: Settings) -> bool:
        token = settings.worker_dispatch_token
        return token is not None and bool(token.get_secret_value())

    def _due(self, settings: Settings) -> bool:
        if self._last_sent is None:
            return True
        interval = settings.worker_dispatch_min_interval_seconds
        return self._monotonic() - self._last_sent >= interval

    def _record(self, reason: str, *, ok: bool, status: int | None) -> None:
        self.last_result = DispatchResult(
            at=dt.datetime.now(dt.UTC), reason=reason, ok=ok, status=status
        )

    async def notify(self, settings: Settings, reason: str, *, force: bool = False) -> bool:
        """워크플로 실행 요청. 보냈으면 True (실패·생략은 False, 예외를 던지지 않는다)."""
        if not self.enabled(settings) or (not force and not self._due(settings)):
            return False
        assert settings.worker_dispatch_token is not None
        self._last_sent = self._monotonic()
        url = (
            f"{GITHUB_API}/repos/{settings.worker_dispatch_repo}/actions/workflows/"
            f"{settings.worker_dispatch_workflow}/dispatches"
        )
        headers = {
            "Authorization": f"Bearer {settings.worker_dispatch_token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "artmate-api",
        }
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=5.0) as client:
                res = await client.post(
                    url, headers=headers, json={"ref": settings.worker_dispatch_ref}
                )
        except httpx.HTTPError as exc:
            self._last_sent = None  # 다음 요청에서 다시 시도
            self._record(reason, ok=False, status=None)
            logger.warning(
                "worker dispatch failed",
                extra={"reason": reason, "error_type": type(exc).__name__},
            )
            return False
        if res.status_code != 204:
            self._last_sent = None
            self._record(reason, ok=False, status=res.status_code)
            # 401/403: 토큰 권한(Actions: write)·만료 확인, 404: 저장소·워크플로 이름 확인
            logger.warning(
                "worker dispatch rejected",
                extra={"reason": reason, "status": res.status_code},
            )
            return False
        self._record(reason, ok=True, status=res.status_code)
        logger.info("worker dispatched", extra={"reason": reason})
        return True

    async def sweep(self, settings: Settings, session: AsyncSession) -> bool:
        """오래 대기한 작업이 있으면 다시 실행 요청 (보냈으면 True).

        실행 시각이 `WORKER_STALE_AFTER_SECONDS` 넘게 지난 작업이 있을 때만, 같은 프로세스에서
        `WORKER_REDISPATCH_INTERVAL_SECONDS`에 한 번만 시도한다 (상태 확인이 자주 와도 스팸 없음).
        """
        if not self.enabled(settings):
            return False
        now = self._monotonic()
        if (
            self._last_sweep is not None
            and now - self._last_sweep < settings.worker_redispatch_interval_seconds
        ):
            return False
        health = await queue_health(session)
        if not health.due_jobs or health.oldest_due_at is None:
            return False
        waited = (dt.datetime.now(dt.UTC) - health.oldest_due_at).total_seconds()
        if waited < settings.worker_stale_after_seconds:
            return False
        self._last_sweep = now
        logger.warning(
            "jobs waiting for the worker",
            extra={"due_jobs": health.due_jobs, "waited_seconds": int(waited)},
        )
        return await self.notify(settings, "stale", force=True)


async def sweep_with_new_session(state) -> bool:  # type: ignore[no-untyped-def]
    """응답 뒤(BackgroundTasks)·주기 점검에서 쓰는 sweep. 요청 세션과 별도로 짧게 연결한다."""
    dispatcher: WorkerDispatcher | None = getattr(state, "worker_dispatcher", None)
    database = getattr(state, "database", None)
    settings: Settings = state.settings
    if dispatcher is None or database is None or not dispatcher.enabled(settings):
        return False
    try:
        async with database.session_factory() as session:
            return await dispatcher.sweep(settings, session)
    except Exception as exc:  # 점검 실패가 API 응답·서버를 멈추지 않게
        logger.warning("worker sweep failed", extra={"error_type": type(exc).__name__})
        return False
