"""라우터에서 사용하는 공통 FastAPI 의존성.

    async def list_items(session: DbSession, settings: AppSettings): ...

트랜잭션 규칙: `DbSession`은 요청 단위 세션이다. 쓰기 작업은 서비스 계층에서
`await session.commit()`을 명시적으로 호출하며, 예외 발생 시 세션 종료와 함께 롤백된다.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import DatabaseNotConfiguredError
from app.db.session import Database


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    database: Database | None = request.app.state.database
    if database is None:
        raise DatabaseNotConfiguredError()
    return database


async def get_db_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async with database.session_factory() as session:
        yield session


AppSettings = Annotated[Settings, Depends(get_app_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
