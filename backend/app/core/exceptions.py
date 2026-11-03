"""공통 예외와 에러 응답 규칙.

모든 에러 응답은 다음 형식을 따른다 (`app.schemas.common.ErrorResponse`):

    {
      "error": {
        "code": "NOT_FOUND",            # 기계가 읽는 대문자 스네이크 코드
        "message": "Resource not found", # 사람이 읽는 메시지 (내부 정보 미포함)
        "details": null,                  # 선택: 검증 오류 목록 등
        "request_id": "..."               # 로그 추적용
      }
    }

서비스/리포지토리 계층에서는 HTTPException 대신 아래 AppError 하위 클래스를 던진다.
"""

from __future__ import annotations

import logging
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_ctx

logger = logging.getLogger(__name__)


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    AUTH_NOT_CONFIGURED = "AUTH_NOT_CONFIGURED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    DATABASE_NOT_CONFIGURED = "DATABASE_NOT_CONFIGURED"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    HTTP_ERROR = "HTTP_ERROR"


class AppError(Exception):
    """API 응답으로 변환되는 애플리케이션 예외의 기반 클래스."""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    code: ErrorCode = ErrorCode.INTERNAL_SERVER_ERROR
    message: str = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: ErrorCode | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class BadRequestError(AppError):
    status_code = HTTPStatus.BAD_REQUEST
    code = ErrorCode.BAD_REQUEST
    message = "Bad request"


class UnauthorizedError(AppError):
    status_code = HTTPStatus.UNAUTHORIZED
    code = ErrorCode.UNAUTHORIZED
    message = "Authentication required"

    def __init__(self, message: str | None = None, **kwargs: Any) -> None:
        kwargs.setdefault("headers", {"WWW-Authenticate": "Bearer"})
        super().__init__(message, **kwargs)


class ForbiddenError(AppError):
    status_code = HTTPStatus.FORBIDDEN
    code = ErrorCode.FORBIDDEN
    message = "You do not have permission to perform this action"


class NotFoundError(AppError):
    status_code = HTTPStatus.NOT_FOUND
    code = ErrorCode.NOT_FOUND
    message = "Resource not found"


class ConflictError(AppError):
    status_code = HTTPStatus.CONFLICT
    code = ErrorCode.CONFLICT
    message = "Resource conflict"


class ServiceUnavailableError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = ErrorCode.SERVICE_UNAVAILABLE
    message = "Service temporarily unavailable"


class DatabaseNotConfiguredError(ServiceUnavailableError):
    code = ErrorCode.DATABASE_NOT_CONFIGURED
    message = "Database is not configured"


class DatabaseUnavailableError(ServiceUnavailableError):
    code = ErrorCode.DATABASE_UNAVAILABLE
    message = "Database is unavailable"


# --------------------------------------------------------------------------- responses


def error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "request_id": request_id_ctx.get(),
            }
        },
        headers=headers,
    )


_HTTP_STATUS_CODES: dict[int, ErrorCode] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    if exc.status_code >= 500:
        logger.warning("application error", extra={"error_code": str(exc.code)})
    return error_response(
        exc.status_code, exc.code, exc.message, details=exc.details, headers=exc.headers
    )


async def _validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # 입력값(input)은 응답에 포함하지 않는다 (비밀번호 등 민감정보가 섞일 수 있음).
    details = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ())),
            "message": error.get("msg", "Invalid value"),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return error_response(
        422,  # Unprocessable Content
        ErrorCode.VALIDATION_ERROR,
        "Request validation failed",
        details=details,
    )


async def _http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_STATUS_CODES.get(exc.status_code, ErrorCode.HTTP_ERROR)
    if isinstance(exc.detail, str) and exc.detail:
        message = exc.detail
    else:
        message = HTTPStatus(exc.status_code).phrase
    return error_response(exc.status_code, code, message, headers=exc.headers)


def register_exception_handlers(app: FastAPI) -> None:
    """예외 핸들러 등록.

    처리되지 않은 예외(500)는 `RequestContextMiddleware`가 로그를 남기고 안전한 응답으로 바꾼다.
    """
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
