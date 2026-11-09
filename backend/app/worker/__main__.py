"""Worker 진입점: `uv run python -m app.worker` (backend/ 에서).

API 서버와 같은 DATABASE_URL을 쓰고, STT_ENABLED / AI_SUMMARY_ENABLED + GEMINI_API_KEY로
처리할 작업 종류를 켠다. SIGTERM/SIGINT를 받으면 현재 작업을 끝낸 뒤 종료한다
(강제 종료돼도 lease 만료 후 다른 Worker가 작업을 이어받는다).
"""

import asyncio
import contextlib
import logging
import signal

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import create_database
from app.integrations.ai.gemini import build_llm
from app.integrations.ai.stt import build_stt
from app.integrations.supabase.storage import HttpSignedUrlFetcher
from app.worker.runner import JobRunner

logger = logging.getLogger("app.worker")


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    database = create_database(settings)
    if database is None:
        raise SystemExit("DATABASE_URL is required for the worker")
    stt = build_stt(settings)
    llm = build_llm(settings)
    logger.info(
        "worker configuration",
        extra={
            "stt": settings.stt_model if stt else None,
            "llm": settings.gemini_model if llm else None,
        },
    )
    runner = JobRunner(
        database,
        settings,
        stt=stt,
        llm=llm,
        fetcher=HttpSignedUrlFetcher(timeout=settings.storage_timeout_seconds * 6),
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):  # Windows
            loop.add_signal_handler(sig, stop.set)
    try:
        await runner.run_forever(stop)
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
