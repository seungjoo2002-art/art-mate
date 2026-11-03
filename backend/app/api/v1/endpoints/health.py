import logging
import time

from fastapi import APIRouter

from app.api.deps import AppSettings, DatabaseDep
from app.core.exceptions import DatabaseUnavailableError
from app.schemas.common import ErrorResponse
from app.schemas.health import ApiHealthStatus, DatabaseHealthStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="API v1 상태 확인")
async def api_health() -> ApiHealthStatus:
    return ApiHealthStatus()


@router.get(
    "/db",
    summary="DB 연결 상태 확인",
    description="PostgreSQL에 `SELECT 1`을 실행한다. 미설정·연결 실패 시 503.",
    responses={503: {"model": ErrorResponse, "description": "DB 미설정 또는 연결 불가"}},
)
async def database_health(database: DatabaseDep, settings: AppSettings) -> DatabaseHealthStatus:
    started = time.perf_counter()
    try:
        await database.ping(timeout_s=settings.db_health_timeout)
    except Exception as exc:
        # 상세 원인은 서버 로그에만 남긴다 (연결 문자열·계정 정보는 응답에 포함하지 않음).
        logger.warning("database health check failed", extra={"error_type": type(exc).__name__})
        raise DatabaseUnavailableError() from exc
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return DatabaseHealthStatus(latency_ms=latency_ms)
