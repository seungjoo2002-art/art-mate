"""CORS, 공통 예외 처리, API 문서 노출 정책, 인증 fail-closed 동작."""

import httpx
from fastapi import APIRouter

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.core.security import CurrentUser
from app.main import create_app
from tests.conftest import make_settings, running_client

ALLOWED = "http://localhost:5173"
DISALLOWED = "https://evil.example.com"


# --------------------------------------------------------------------------- CORS


async def test_cors_allows_configured_origin(client: httpx.AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": ALLOWED})

    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_cors_simple_request_from_disallowed_origin_has_no_cors_headers(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/health", headers={"Origin": DISALLOWED})

    assert "access-control-allow-origin" not in response.headers


async def test_cors_preflight_from_disallowed_origin_is_rejected(
    client: httpx.AsyncClient,
) -> None:
    response = await client.options(
        "/api/v1/health",
        headers={"Origin": DISALLOWED, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


async def test_cors_preflight_from_allowed_origin_succeeds(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/api/v1/health",
        headers={
            "Origin": ALLOWED,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED


# --------------------------------------------------------------------------- errors


def _app_with_test_routes():  # type: ignore[no-untyped-def]
    app = create_app(make_settings())
    router = APIRouter(prefix="/_test")

    @router.get("/crash")
    async def crash() -> None:
        raise RuntimeError("db password is hunter2")

    @router.get("/not-found")
    async def not_found() -> None:
        raise NotFoundError("Artwork not found")

    @router.get("/forbidden")
    async def forbidden() -> None:
        raise ForbiddenError()

    @router.get("/conflict")
    async def conflict() -> None:
        raise ConflictError()

    @router.get("/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @router.get("/protected")
    async def protected(user: CurrentUser) -> dict[str, str]:
        return {"user_id": str(user.user_id)}

    app.include_router(router)
    return app


async def test_unhandled_exception_returns_safe_500() -> None:
    async with running_client(_app_with_test_routes()) as client:
        response = await client.get("/_test/crash")

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "INTERNAL_SERVER_ERROR"
    assert error["message"] == "Internal server error"
    assert "hunter2" not in response.text
    assert "Traceback" not in response.text
    assert error["request_id"] == response.headers["X-Request-ID"]


async def test_app_errors_map_to_status_codes() -> None:
    async with running_client(_app_with_test_routes()) as client:
        not_found = await client.get("/_test/not-found")
        forbidden = await client.get("/_test/forbidden")
        conflict = await client.get("/_test/conflict")

    assert (not_found.status_code, not_found.json()["error"]["code"]) == (404, "NOT_FOUND")
    assert not_found.json()["error"]["message"] == "Artwork not found"
    assert (forbidden.status_code, forbidden.json()["error"]["code"]) == (403, "FORBIDDEN")
    assert (conflict.status_code, conflict.json()["error"]["code"]) == (409, "CONFLICT")


async def test_validation_error_format_does_not_echo_input() -> None:
    async with running_client(_app_with_test_routes()) as client:
        response = await client.get("/_test/items/secret-value")

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "path.item_id"
    assert "secret-value" not in response.text


async def test_unknown_route_and_method_use_error_format(client: httpx.AsyncClient) -> None:
    missing = await client.get("/does-not-exist")
    wrong_method = await client.post("/health")

    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "NOT_FOUND")
    assert wrong_method.status_code == 405
    assert wrong_method.json()["error"]["code"] == "METHOD_NOT_ALLOWED"


async def test_request_id_is_propagated_when_valid(client: httpx.AsyncClient) -> None:
    ok = await client.get("/health", headers={"X-Request-ID": "trace-123"})
    bad = await client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})

    assert ok.headers["X-Request-ID"] == "trace-123"
    assert bad.headers["X-Request-ID"] != "bad id\nwith newline"


# --------------------------------------------------------------------------- auth


async def test_protected_route_rejects_missing_token() -> None:
    async with running_client(_app_with_test_routes()) as client:
        response = await client.get("/_test/protected")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_protected_route_fails_closed_until_auth_is_implemented() -> None:
    async with running_client(_app_with_test_routes()) as client:
        response = await client.get(
            "/_test/protected", headers={"Authorization": "Bearer any.jwt.token"}
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"


# --------------------------------------------------------------------------- docs


async def test_docs_available_in_development() -> None:
    async with running_client(create_app(make_settings(app_env="development"))) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 200, path


async def test_docs_hidden_in_production_by_default() -> None:
    settings = make_settings(app_env="production", database_url="postgresql://u:p@127.0.0.1:1/db")
    async with running_client(create_app(settings)) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404, path
