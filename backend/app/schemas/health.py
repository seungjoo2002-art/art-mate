from typing import Literal

from pydantic import BaseModel, Field


class ServiceInfo(BaseModel):
    service: str
    version: str
    status: Literal["running"] = "running"


class HealthStatus(BaseModel):
    status: Literal["ok"] = "ok"


class ApiHealthStatus(HealthStatus):
    api_version: str = "v1"


class DatabaseHealthStatus(HealthStatus):
    database: Literal["ok"] = "ok"
    latency_ms: float
    # v0.9.9 스키마 버전 점검 (behind·missing이면 이 응답 대신 503 DATABASE_SCHEMA_MISMATCH)
    schema_status: Literal["ok", "ahead", "unknown"] = Field(
        description="ok 일치 / ahead DB가 더 새 버전(마이그레이션 선적용, 정상) / unknown 비교 불가"
    )
    db_revision: str | None = Field(description="운영 DB의 Alembic revision")
    code_revision: str | None = Field(description="이 코드가 요구하는 Alembic revision (head)")
