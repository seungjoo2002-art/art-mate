"""DB 엔진·세션 관리.

`Database` 인스턴스는 앱 lifespan에서 한 번 만들어 `app.state.database`에 보관한다.
DATABASE_URL이 없으면 None이며, 이 경우에도 앱은 정상 기동한다 (`/health`는 DB와 무관).

Supabase 연결 방식
-------------------
- Direct connection (db.<ref>.supabase.co:5432): IPv6 전용일 수 있음
- Session pooler (pooler.supabase.com:5432): 상시 실행 서버(Render 등)에 권장
- Transaction pooler (pooler.supabase.com:6543): prepared statement 미지원 →
  포트 6543이면 자동으로 prepared statement 캐시를 끈다 (DB_DISABLE_PREPARED_STATEMENTS로 강제 가능)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings

logger = logging.getLogger(__name__)


def _connect_args(settings: Settings) -> dict[str, Any]:
    args: dict[str, Any] = {
        "timeout": settings.db_connect_timeout,
        "server_settings": {"application_name": "artmate-api"},
    }
    if settings.disable_prepared_statements:
        args.update(
            statement_cache_size=0,  # asyncpg
            prepared_statement_cache_size=0,  # SQLAlchemy asyncpg adapter
            prepared_statement_name_func=lambda: f"__asyncpg_{uuid.uuid4()}__",
        )
    return args


def build_engine(settings: Settings, *, use_null_pool: bool = False) -> AsyncEngine:
    """설정으로 AsyncEngine 생성. 실제 연결은 첫 사용 시점에 이루어진다."""
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is not configured")

    url = settings.database_url.get_secret_value()
    common: dict[str, Any] = {
        "connect_args": _connect_args(settings),
        "echo": False,  # SQL 로그는 logging 설정(DEBUG)으로 제어
    }
    if use_null_pool:
        return create_async_engine(url, poolclass=NullPool, **common)
    return create_async_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
        pool_pre_ping=True,
        **common,
    )


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self.session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
        )

    async def ping(self, timeout_s: float) -> None:
        """`SELECT 1` 실행. 실패/시간초과 시 예외를 그대로 던진다 (호출자가 변환)."""
        async with asyncio.timeout(timeout_s), self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()


def create_database(settings: Settings) -> Database | None:
    if not settings.database_configured:
        return None
    return Database(build_engine(settings))
