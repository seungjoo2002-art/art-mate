"""Worker 진입점 (backend/ 에서).

상시 실행:  `uv run python -m app.worker`
일괄 실행:  `uv run python -m app.worker --once --max-jobs 10 --max-seconds 1800`
            (GitHub Actions `stt-worker.yml`이 주기적으로 실행. 큐가 비면 바로 종료)

API 서버와 같은 DATABASE_URL을 쓰고, STT_ENABLED / AI_SUMMARY_ENABLED + GEMINI_API_KEY로
처리할 작업 종류를 켠다. 일괄 실행은 켜진 기능의 작업만 가져가므로, Gemini 키가 없으면 요약 작업은
실패시키지 않고 큐에 남겨 둔다. STT 모델은 전사 작업을 실제로 처리할 때 처음 로드한다.
SIGTERM/SIGINT를 받으면 현재 작업을 끝낸 뒤 종료한다 (강제 종료돼도 lease 만료 후 다음 실행이
이어받는다).
"""

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import create_database
from app.integrations.ai.llm import build_llm
from app.integrations.ai.stt import build_stt
from app.integrations.supabase.storage import HttpSignedUrlFetcher
from app.models.enums import AiJobType
from app.worker.runner import JobRunner

logger = logging.getLogger("app.worker")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m app.worker")
    parser.add_argument("--once", action="store_true", help="일괄 실행 후 종료")
    parser.add_argument("--max-jobs", type=int, default=10, help="일괄 실행 최대 작업 수")
    parser.add_argument(
        "--max-seconds", type=float, default=1800, help="이 시간이 지나면 새 작업을 잡지 않음"
    )
    parser.add_argument(
        "--no-maintenance", action="store_true", help="보관 기간 정리·알림 정기 작업 생략"
    )
    parser.add_argument(
        "--pending",
        action="store_true",
        help="처리 대기 작업 수만 출력 (GITHUB_OUTPUT이 있으면 transcribe/llm/total 기록)",
    )
    args = parser.parse_args(argv)
    if args.max_jobs < 1 or args.max_seconds <= 0:
        parser.error("--max-jobs and --max-seconds must be positive")
    return args


LLM_JOB_TYPES = (
    AiJobType.SUMMARIZE.value,
    AiJobType.GROWTH_REPORT.value,
    AiJobType.PRACTICE_RECOMMEND.value,
)


def pending_outputs(counts: dict[str, int]) -> dict[str, int]:
    transcribe = counts.get(AiJobType.TRANSCRIBE.value, 0)
    llm = sum(counts.get(t, 0) for t in LLM_JOB_TYPES)
    return {"transcribe": transcribe, "llm": llm, "total": sum(counts.values())}


def write_github_output(path: str, outputs: dict[str, int]) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.writelines(f"{k}={v}\n" for k, v in outputs.items())


def supported_job_types(
    settings: Settings, *, has_stt: bool, has_llm: bool
) -> frozenset[AiJobType]:
    """이 Worker가 끝까지 처리할 수 있는 작업 종류."""
    types: set[AiJobType] = set()
    if has_stt:
        types.add(AiJobType.TRANSCRIBE)
    if has_llm:
        types.add(AiJobType.SUMMARIZE)
        if settings.growth_ai_active:
            types |= {AiJobType.GROWTH_REPORT, AiJobType.PRACTICE_RECOMMEND}
    return frozenset(types)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = get_settings()
    configure_logging(settings)
    database = create_database(settings)
    if database is None:
        raise SystemExit("DATABASE_URL is required for the worker")
    if args.pending:
        try:
            runner = JobRunner(
                database, settings, stt=None, llm=None, fetcher=HttpSignedUrlFetcher(timeout=1)
            )
            outputs = pending_outputs(await runner.pending_counts())
        finally:
            await database.dispose()
        print(json.dumps(outputs))
        if path := os.environ.get("GITHUB_OUTPUT"):
            write_github_output(path, outputs)
        return
    stt = build_stt(settings)
    llm = build_llm(settings)
    job_types = (
        supported_job_types(settings, has_stt=stt is not None, has_llm=llm is not None)
        if args.once
        else None
    )
    logger.info(
        "worker configuration",
        extra={
            "mode": "batch" if args.once else "forever",
            "stt": settings.stt_model if stt else None,
            "llm": llm.model_name if llm else None,
            "job_types": sorted(t.value for t in job_types) if job_types is not None else "all",
        },
    )
    runner = JobRunner(
        database,
        settings,
        stt=stt,
        llm=llm,
        fetcher=HttpSignedUrlFetcher(timeout=settings.storage_timeout_seconds * 6),
        job_types=job_types,
    )
    try:
        if args.once:
            pending = await runner.pending_counts()
            logger.info("queue before batch", extra={"pending": pending})
            waiting_llm = pending_outputs(pending)["llm"]
            if waiting_llm and llm is None:
                logger.warning(
                    "AI jobs are waiting but this worker cannot process them: set GitHub Actions "
                    "variables AI_PROVIDER, AI_SUMMARY_ENABLED=true, "
                    "AI_PROVIDER_TERMS_CONFIRMED=true "
                    "(after the provider terms review) and secret OPENAI_API_KEY "
                    "(GEMINI_API_KEY for gemini)",
                    extra={"waiting": waiting_llm},
                )
            if pending.get(AiJobType.TRANSCRIBE.value) and stt is None:
                logger.warning(
                    "transcription jobs are waiting but STT is disabled on this worker",
                    extra={"waiting": pending.get(AiJobType.TRANSCRIBE.value)},
                )
            stats = await runner.run_batch(
                max_jobs=args.max_jobs,
                max_seconds=args.max_seconds,
                maintenance=not args.no_maintenance,
            )
            # v0.9.6: 처리 한도에 닿았으면 남은 작업이 있을 수 있음 → 워크플로가 다음 실행을 요청
            if path := os.environ.get("GITHUB_OUTPUT"):
                write_github_output(
                    path,
                    {
                        "processed": stats["processed"],
                        "hit_limit": int(stats["processed"] >= args.max_jobs),
                    },
                )
            return
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):  # Windows
                loop.add_signal_handler(sig, stop.set)
        await runner.run_forever(stop)
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
