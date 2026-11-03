from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import PaginationParams


async def fetch_page(
    session: AsyncSession, stmt: Select[Any], params: PaginationParams
) -> tuple[list[Any], int]:
    """정렬된 select 문으로 (현재 페이지 행 목록, 전체 개수)를 반환한다."""
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (await session.execute(stmt.limit(params.limit).offset(params.offset))).all()
    return list(rows), total
