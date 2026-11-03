"""Alembic 실행 환경 (async).

- DB URL은 app.core.config.Settings(DATABASE_URL)에서 읽는다.
- `app.models`를 import 해야 autogenerate가 모델을 인식한다.
- 안전장치: APP_ENV=production 에서는 ALLOW_PRODUCTION_MIGRATIONS=true 일 때만 실행된다.
  (운영 DB 마이그레이션은 자동 실행하지 않고, 리뷰된 리비전을 사람이 명시적으로 적용한다)
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy.engine import Connection

import app.models  # noqa: F401 - 모델 등록
from alembic import context
from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import build_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _load_settings() -> Settings:
    settings = get_settings()
    if settings.database_url is None:
        raise SystemExit("DATABASE_URL이 설정되지 않았습니다. backend/.env 를 확인하세요.")
    if settings.app_env == "production" and os.environ.get("ALLOW_PRODUCTION_MIGRATIONS") != "true":
        raise SystemExit(
            "APP_ENV=production 대상 마이그레이션이 차단되었습니다. 의도한 작업이라면 "
            "ALLOW_PRODUCTION_MIGRATIONS=true 를 명시하고 다시 실행하세요."
        )
    return settings


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    # Supabase 전용 FK(profiles.id -> auth.users.id)는 마이그레이션에서 조건부로 만들며
    # ORM 메타데이터에는 없다. autogenerate/check가 이를 "삭제 대상"으로 보지 않게 제외한다.
    if type_ == "foreign_key_constraint" and reflected:
        referred = getattr(obj, "referred_table", None)
        if referred is not None and referred.schema == "auth":
            return False
    return True


def _configure(**kwargs: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: DB 연결 없이 SQL 스크립트만 출력."""
    settings = _load_settings()
    assert settings.database_url is not None
    _configure(
        url=settings.database_url.get_secret_value(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = build_engine(_load_settings(), use_null_pool=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_sync_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
