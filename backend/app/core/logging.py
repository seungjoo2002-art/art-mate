"""구조화 로깅 설정.

- 운영(staging/production): 한 줄 JSON (Render 등 로그 수집기에서 필드 검색 가능)
- 개발/테스트: 사람이 읽기 쉬운 text
- 모든 로그 레코드에 `request_id`가 자동으로 포함된다.

사용법:
    logger = logging.getLogger(__name__)
    logger.info("artwork uploaded", extra={"artwork_id": str(artwork.id)})

주의: 비밀번호·토큰·연결 문자열·학생 개인정보를 로그에 남기지 않는다.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

from app.core.config import Settings

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

# LogRecord 기본 속성: 이 외의 속성은 `extra=`로 전달된 구조화 필드로 간주한다.
_RESERVED_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
    | {"message", "asctime", "request_id", "color_message", "taskName"}
)


def _extra_fields(record: logging.LogRecord) -> dict[str, object]:
    return {k: v for k, v in record.__dict__.items() if k not in _RESERVED_ATTRS}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-8s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        parts = []
        request_id = getattr(record, "request_id", None)
        if request_id:
            parts.append(f"request_id={request_id}")
        parts.extend(f"{key}={value}" for key, value in _extra_fields(record).items())
        if not parts:
            return base
        head, sep, tail = base.partition("\n")  # 예외 traceback은 줄바꿈 뒤에 온다
        return f"{head} | {' '.join(parts)}{sep}{tail}"


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        JsonFormatter() if settings.effective_log_format == "json" else TextFormatter()
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)

    # uvicorn 로거를 루트 핸들러로 통일한다. 접근 로그는 RequestContextMiddleware가 대신 남긴다.
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.handlers.clear()
    access_logger.propagate = False

    # SQL 로그는 DEBUG 모드에서만 (쿼리 파라미터에 개인정보가 있을 수 있으므로 운영에서는 끔)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.debug else logging.WARNING
    )
    # v0.6: HTTP 클라이언트는 요청 URL 전체를 INFO로 남긴다 → Storage Signed URL(토큰 포함)이 로그에
    # 남지 않도록 항상 WARNING 이상만. faster-whisper·HuggingFace도 처리 정보만 WARNING 이상으로.
    for name in ("httpx", "httpx2", "httpcore", "huggingface_hub", "faster_whisper"):
        logging.getLogger(name).setLevel(logging.WARNING)
