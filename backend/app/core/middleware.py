"""요청 컨텍스트 미들웨어 (request id, 접근 로그, 처리되지 않은 예외 → 안전한 500 응답)."""

from __future__ import annotations

import logging
import re
import time
import uuid
from http import HTTPStatus

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.exceptions import ErrorCode, error_response
from app.core.logging import request_id_ctx

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"
# 외부에서 들어온 request id는 형식이 안전할 때만 재사용한다 (로그 인젝션 방지)
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestContextMiddleware:
    """순수 ASGI 미들웨어.

    - 요청마다 request id를 만들고 응답 헤더 `X-Request-ID`와 모든 로그에 포함한다.
    - 요청 1건당 접근 로그 1줄(method, path, status, duration)을 남긴다.
    - 처리되지 않은 예외는 traceback을 서버 로그에만 남기고, 클라이언트에는
      내부 정보가 없는 500 응답을 반환한다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        request_id = (
            incoming if incoming and _VALID_REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        )
        token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status_code = HTTPStatus.INTERNAL_SERVER_ERROR.value
        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("unhandled exception")
            if response_started:
                raise  # 이미 응답을 보내기 시작했다면 서버가 연결을 정리하도록 한다
            response = error_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                ErrorCode.INTERNAL_SERVER_ERROR,
                "Internal server error",
            )
            await response(scope, receive, send_wrapper)
        finally:
            logger.info(
                "request completed",
                extra={
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                },
            )
            request_id_ctx.reset(token)
