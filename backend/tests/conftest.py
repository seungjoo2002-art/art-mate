"""테스트 공통 fixture.

원칙: 테스트는 개발자의 backend/.env 와 운영 Supabase DB에 절대 접근하지 않는다.
- 모든 Settings는 `make_settings()`로 만들며 .env 파일을 읽지 않는다 (_env_file=None).
- 실제 DB가 필요한 테스트는 `integration` 마커 + TEST_DATABASE_URL 이 있을 때만 실행된다.
"""

import os

# app.main 이 import 될 경우(모듈 레벨 create_app)에도 .env 를 읽지 않도록 가장 먼저 설정
os.environ["ENV_FILE"] = ""
os.environ["APP_ENV"] = "test"
os.environ.pop("DATABASE_URL", None)

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app

# 연결이 즉시 거부되는 주소 (포트 1). 비밀번호는 응답 노출 여부 검사용 더미 값.
UNREACHABLE_DATABASE_URL = "postgresql://artmate_user:super-secret-pw@127.0.0.1:1/artmate"

_ISOLATED_ENV_KEYS = (
    "APP_ENV",
    "DEBUG",
    "DATABASE_URL",
    "CORS_ORIGINS",
    "DOCS_ENABLED",
    "LOG_FORMAT",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "STORAGE_BUCKET",
    "STORAGE_SIGNED_URL_SECONDS",
    "ARTWORK_MAX_UPLOAD_BYTES",
    "ARTWORK_ALLOWED_CONTENT_TYPES",
    "ARTWORK_MAX_PHOTOS_PER_STAGE",
    "RECORDING_BUCKET",
    "RECORDING_ALLOWED_CONTENT_TYPES",
    "RECORDING_MAX_UPLOAD_BYTES",
    "RECORDING_CONSENT_VERSION",
)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test",
        "debug": False,
        "database_url": None,
        "cors_origins": ["http://localhost:5173"],
        "log_level": "WARNING",
        "db_connect_timeout": 2.0,
        "db_health_timeout": 3.0,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ISOLATED_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ENV_FILE", "")


@pytest.fixture
def settings_factory() -> Callable[..., Settings]:
    return make_settings


@asynccontextmanager
async def running_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """lifespan(startup/shutdown)까지 실행한 상태의 비동기 테스트 클라이언트."""
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """DB 미설정 상태의 기본 앱."""
    async with running_client(create_app(make_settings())) as c:
        yield c
