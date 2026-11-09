"""OpenAPI 문서용 공통 에러 응답 정의."""

from typing import Any

from app.schemas.common import ErrorResponse

_DESCRIPTIONS = {
    400: "Bad request",
    401: "인증 필요 / 토큰 무효·만료 (UNAUTHORIZED, INVALID_TOKEN, TOKEN_EXPIRED)",
    403: "권한 없음 (FORBIDDEN, PROFILE_REQUIRED, ACCOUNT_DISABLED)",
    404: "리소스 없음 또는 접근 불가 학원 (NOT_FOUND)",
    409: "상태 충돌 (도메인별 코드는 docs/frontend-integration.md 참고)",
    422: "입력값 검증 실패 (VALIDATION_ERROR)",
    429: "요청 제한 초과 (RATE_LIMITED, details.retry_after_seconds)",
    503: "DB·인증 공급자 일시 불가",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    return {
        code: {"model": ErrorResponse, "description": _DESCRIPTIONS.get(code, "Error")}
        for code in status_codes
    }


AUTH_ERRORS = error_responses(401, 403, 503)
