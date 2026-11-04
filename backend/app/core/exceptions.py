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
    INVALID_TOKEN = "INVALID_TOKEN"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    AUTH_NOT_CONFIGURED = "AUTH_NOT_CONFIGURED"
    AUTH_PROVIDER_UNAVAILABLE = "AUTH_PROVIDER_UNAVAILABLE"
    FORBIDDEN = "FORBIDDEN"
    PROFILE_REQUIRED = "PROFILE_REQUIRED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    NOT_FOUND = "NOT_FOUND"
    PROFILE_NOT_FOUND = "PROFILE_NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    ALREADY_MEMBER = "ALREADY_MEMBER"
    JOIN_REQUEST_ALREADY_PENDING = "JOIN_REQUEST_ALREADY_PENDING"
    JOIN_REQUEST_ALREADY_REVIEWED = "JOIN_REQUEST_ALREADY_REVIEWED"
    ACADEMY_NOT_ACCEPTING_MEMBERS = "ACADEMY_NOT_ACCEPTING_MEMBERS"
    ACADEMY_ALREADY_REVIEWED = "ACADEMY_ALREADY_REVIEWED"
    ACADEMY_APPLICATION_LIMIT = "ACADEMY_APPLICATION_LIMIT"
    OWNER_CANNOT_LEAVE = "OWNER_CANNOT_LEAVE"
    MEMBER_ROLE_NOT_CHANGEABLE = "MEMBER_ROLE_NOT_CHANGEABLE"
    APPLICANT_INACTIVE = "APPLICANT_INACTIVE"
    # v0.3 학원 운영
    ACADEMY_NOT_ACTIVE = "ACADEMY_NOT_ACTIVE"
    ALREADY_CHECKED_IN = "ALREADY_CHECKED_IN"
    ATTENDANCE_ALREADY_RECORDED = "ATTENDANCE_ALREADY_RECORDED"
    CLASS_ARCHIVED = "CLASS_ARCHIVED"
    ALREADY_IN_CLASS = "ALREADY_IN_CLASS"
    INVALID_CLASS_MEMBER = "INVALID_CLASS_MEMBER"
    SCHEDULE_OVERLAP = "SCHEDULE_OVERLAP"
    INVALID_OCCURRENCE = "INVALID_OCCURRENCE"
    SCHEDULE_EXCEPTION_EXISTS = "SCHEDULE_EXCEPTION_EXISTS"
    INVALID_DATE_RANGE = "INVALID_DATE_RANGE"
    LESSON_TOPIC_EXISTS = "LESSON_TOPIC_EXISTS"
    TASK_CANCELLED = "TASK_CANCELLED"
    INVALID_TASK_TARGET = "INVALID_TASK_TARGET"
    # v0.4 작품 사진
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_IMAGE = "INVALID_IMAGE"
    PHOTO_LIMIT_REACHED = "PHOTO_LIMIT_REACHED"
    DUPLICATE_PHOTO = "DUPLICATE_PHOTO"
    UPLOAD_NOT_FOUND = "UPLOAD_NOT_FOUND"
    UPLOAD_EXPIRED = "UPLOAD_EXPIRED"
    PHOTO_NOT_ACTIVE = "PHOTO_NOT_ACTIVE"
    INVALID_ARTWORK_LINK = "INVALID_ARTWORK_LINK"
    STORAGE_NOT_CONFIGURED = "STORAGE_NOT_CONFIGURED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    # v0.4 시험 타이머
    INVALID_STAGE_TARGETS = "INVALID_STAGE_TARGETS"
    TEMPLATE_ARCHIVED = "TEMPLATE_ARCHIVED"
    EXAM_ALREADY_RUNNING = "EXAM_ALREADY_RUNNING"
    EXAM_INVALID_STATE = "EXAM_INVALID_STATE"
    EXAM_NOT_RUNNING = "EXAM_NOT_RUNNING"
    NOT_EXAM_PARTICIPANT = "NOT_EXAM_PARTICIPANT"
    # v0.5 질문 콜
    HELP_REQUEST_ALREADY_ACTIVE = "HELP_REQUEST_ALREADY_ACTIVE"
    HELP_REQUEST_INVALID_STATE = "HELP_REQUEST_INVALID_STATE"
    HELP_QUEUE_EMPTY = "HELP_QUEUE_EMPTY"
    NOT_IN_CLASS = "NOT_IN_CLASS"
    # v0.5 피드백 녹음
    RECORDING_CONSENT_REQUIRED = "RECORDING_CONSENT_REQUIRED"
    INVALID_AUDIO = "INVALID_AUDIO"
    AUDIO_TOO_LONG = "AUDIO_TOO_LONG"
    RECORDING_LIMIT_REACHED = "RECORDING_LIMIT_REACHED"
    DUPLICATE_RECORDING = "DUPLICATE_RECORDING"
    RECORDING_NOT_ACTIVE = "RECORDING_NOT_ACTIVE"
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


class InvalidTokenError(UnauthorizedError):
    code = ErrorCode.INVALID_TOKEN
    message = "Invalid access token"


class TokenExpiredError(UnauthorizedError):
    code = ErrorCode.TOKEN_EXPIRED
    message = "Access token has expired"


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


class UnprocessableError(AppError):
    """형식은 맞지만 도메인 규칙상 처리할 수 없는 입력 (예: 존재하지 않는 수업 회차)."""

    status_code = 422  # Unprocessable Content (3.12 HTTPStatus 이름이 버전마다 다름)
    code = ErrorCode.VALIDATION_ERROR
    message = "Request cannot be processed"


class ServiceUnavailableError(AppError):
    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = ErrorCode.SERVICE_UNAVAILABLE
    message = "Service temporarily unavailable"


class AuthProviderUnavailableError(ServiceUnavailableError):
    code = ErrorCode.AUTH_PROVIDER_UNAVAILABLE
    message = "Authentication provider is temporarily unavailable"


class DatabaseNotConfiguredError(ServiceUnavailableError):
    code = ErrorCode.DATABASE_NOT_CONFIGURED
    message = "Database is not configured"


class StorageNotConfiguredError(ServiceUnavailableError):
    code = ErrorCode.STORAGE_NOT_CONFIGURED
    message = "File storage is not configured"


class StorageUnavailableError(ServiceUnavailableError):
    code = ErrorCode.STORAGE_UNAVAILABLE
    message = "File storage is temporarily unavailable"


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
