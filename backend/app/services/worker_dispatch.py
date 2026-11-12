"""Worker 즉시 실행 요청 (GitHub Actions workflow_dispatch).

stt-worker 워크플로의 예약 실행(cron */15)은 GitHub 사정으로 실제로는 수 시간씩 밀린다
(2026-11-11~12 기록: 20시간 동안 4회, 간격 6~7시간). 작업을 큐에 넣은 직후 워크플로 실행을
요청하면 보통 수십 초 안에 Worker가 시작된다. 그래도 GitHub가 실행을 보장하지는 않으므로
예약 실행은 그대로 둔다 (실패해도 작업은 큐에 남아 다음 실행이 처리).

- 토큰(WORKER_DISPATCH_TOKEN)이 없으면 아무것도 하지 않는다.
- 요청 본문에는 작업·사용자 정보를 넣지 않는다 (Worker가 DB 큐에서 직접 가져감).
- 같은 프로세스에서 짧은 간격의 요청은 한 번으로 합친다. 워크플로 concurrency 설정으로
  실행 중에 들어온 요청은 다음 실행 1건으로 합쳐진다.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import httpx

from app.core.config import Settings

logger = logging.getLogger("app.worker_dispatch")

GITHUB_API = "https://api.github.com"


class WorkerDispatcher:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._last_sent: float | None = None
        self._monotonic = monotonic

    @staticmethod
    def enabled(settings: Settings) -> bool:
        token = settings.worker_dispatch_token
        return token is not None and bool(token.get_secret_value())

    def _due(self, settings: Settings) -> bool:
        if self._last_sent is None:
            return True
        interval = settings.worker_dispatch_min_interval_seconds
        return self._monotonic() - self._last_sent >= interval

    async def notify(self, settings: Settings, reason: str) -> bool:
        """워크플로 실행 요청. 보냈으면 True (실패·생략은 False, 예외를 던지지 않는다)."""
        if not self.enabled(settings) or not self._due(settings):
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
            logger.warning(
                "worker dispatch failed",
                extra={"reason": reason, "error_type": type(exc).__name__},
            )
            return False
        if res.status_code != 204:
            self._last_sent = None
            # 401/403: 토큰 권한(Actions: write)·만료 확인, 404: 저장소·워크플로 이름 확인
            logger.warning(
                "worker dispatch rejected",
                extra={"reason": reason, "status": res.status_code},
            )
            return False
        logger.info("worker dispatched", extra={"reason": reason})
        return True
