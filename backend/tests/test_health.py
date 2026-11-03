from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from app.main import create_app
from app.schemas.common import ErrorResponse
from tests.conftest import UNREACHABLE_DATABASE_URL, make_settings, running_client


def test_create_app_registers_core_routes() -> None:
    app = create_app(make_settings())

    assert isinstance(app, FastAPI)
    assert app.title == "ART MATE API"
    assert app.version == "0.1.0"
    paths = set(app.openapi()["paths"])
    assert {"/", "/health", "/api/v1/health", "/api/v1/health/db"} <= paths


async def test_root_returns_service_info(client: httpx.AsyncClient) -> None:
    response = await client.get("/")

    assert response.status_code == 200
    assert response.json() == {"service": "ART MATE API", "version": "0.1.0", "status": "running"}
    assert response.headers["X-Request-ID"]


async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_api_v1_health_returns_ok(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api_version": "v1"}


async def test_db_health_when_database_not_configured(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/db")

    assert response.status_code == 503
    body = ErrorResponse.model_validate(response.json())
    assert body.error.code == "DATABASE_NOT_CONFIGURED"
    assert body.error.request_id == response.headers["X-Request-ID"]


async def test_db_health_when_database_unreachable_hides_details() -> None:
    """실제 asyncpg 연결 시도가 거부되는 경우 (외부 서비스 없이 재현)."""
    app = create_app(make_settings(database_url=UNREACHABLE_DATABASE_URL))

    async with running_client(app) as client:
        response = await client.get("/api/v1/health/db")
        # DB 장애와 무관하게 liveness는 정상이어야 한다
        liveness = await client.get("/health")

    assert response.status_code == 503
    body = ErrorResponse.model_validate(response.json())
    assert body.error.code == "DATABASE_UNAVAILABLE"
    assert body.error.message == "Database is unavailable"
    raw = response.text
    for secret in ("super-secret-pw", "artmate_user", "127.0.0.1", "postgresql", "Error"):
        assert secret not in raw
    assert liveness.status_code == 200


async def test_db_health_timeout_returns_503() -> None:
    app = create_app(make_settings(database_url=UNREACHABLE_DATABASE_URL))

    async with running_client(app) as client:
        with patch.object(
            app.state.database, "ping", AsyncMock(side_effect=TimeoutError())
        ) as ping:
            response = await client.get("/api/v1/health/db")

    ping.assert_awaited_once()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"


async def test_db_health_success_with_mocked_database() -> None:
    app = create_app(make_settings(database_url=UNREACHABLE_DATABASE_URL))

    async with running_client(app) as client:
        with patch.object(app.state.database, "ping", AsyncMock(return_value=None)):
            response = await client.get("/api/v1/health/db")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert isinstance(body["latency_ms"], float)
