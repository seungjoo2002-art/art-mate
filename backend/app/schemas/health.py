from typing import Literal

from pydantic import BaseModel


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
