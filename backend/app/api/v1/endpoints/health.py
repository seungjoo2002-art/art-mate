import logging
import time

from fastapi import APIRouter

from app.api.deps import AppSettings, DatabaseDep
from app.core.exceptions import DatabaseSchemaMismatchError, DatabaseUnavailableError
from app.db.schema_version import code_revisions, compare
from app.schemas.common import ErrorResponse
from app.schemas.health import ApiHealthStatus, DatabaseHealthStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", summary="API v1 상태 확인")
async def api_health() -> ApiHealthStatus:
    return ApiHealthStatus()


@router.get(
    "/db",
    summary="DB 연결·스키마 버전 확인",
    description=(
        "PostgreSQL에 `SELECT 1`을 실행하고, DB의 Alembic revision을 이 코드가 요구하는 revision과 "
        "비교한다. 미설정·연결 실패 시 503 `DATABASE_UNAVAILABLE`, "
        "코드가 DB보다 새 버전이면(마이그레이션 미적용 배포) 503 `DATABASE_SCHEMA_MISMATCH`. "
        "DB가 더 새 버전이면(마이그레이션 선적용) 200."
    ),
    responses={
        503: {
            "model": ErrorResponse,
            "description": "DB 미설정·연결 불가, 또는 스키마가 이 코드보다 오래됨",
        }
    },
)
async def database_health(database: DatabaseDep, settings: AppSettings) -> DatabaseHealthStatus:
    started = time.perf_counter()
    try:
        await database.ping(timeout_s=settings.db_health_timeout)
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        revisions = await database.schema_revisions(timeout_s=settings.db_health_timeout)
    except Exception as exc:
        # 상세 원인은 서버 로그에만 남긴다 (연결 문자열·계정 정보는 응답에 포함하지 않음).
        logger.warning("database health check failed", extra={"error_type": type(exc).__name__})
        raise DatabaseUnavailableError() from exc
    check = compare(revisions, code_revisions())
    if check.failing:
        logger.error(
            "database schema mismatch",
            extra={
                "schema_status": check.status,
                "db_revision": check.db_revision,
                "code_revision": check.code_revision,
            },
        )
        raise DatabaseSchemaMismatchError(
            details={
                "schema_status": check.status,
                "db_revision": check.db_revision,
                "code_revision": check.code_revision,
            }
        )
    if check.status != "ok":
        logger.warning(
            "database schema check",
            extra={
                "schema_status": check.status,
                "db_revision": check.db_revision,
                "code_revision": check.code_revision,
            },
        )
    return DatabaseHealthStatus(
        latency_ms=latency_ms,
        schema_status=check.status,  # type: ignore[arg-type]  # failing은 위에서 처리
        db_revision=check.db_revision,
        code_revision=check.code_revision,
    )
