"""모든 API가 공유하는 응답 규칙.

- 성공 응답: 리소스 스키마를 그대로 반환 (envelope 없음)
- 목록 응답: `Page[T]` (items + 페이지 정보)
- 에러 응답: `ErrorResponse` (app.core.exceptions.error_response 와 동일한 형태)
- 날짜/시간: UTC로 저장, ISO 8601(타임존 포함)로 응답 → `datetime` 필드는 aware datetime 사용
- 식별자: UUID
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


class APIModel(BaseModel):
    """응답 스키마 기본 클래스. ORM 객체에서 바로 변환할 수 있다."""

    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str = Field(examples=["NOT_FOUND"])
    message: str = Field(examples=["Resource not found"])
    details: Any | None = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class PaginationParams(BaseModel):
    """offset 기반 기본 페이지네이션. 라우터에서 `Annotated[PaginationParams, Query()]`로 사용."""

    limit: Annotated[int, Field(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT
    offset: Annotated[int, Field(ge=0)] = 0


PaginationQuery = Annotated[PaginationParams, Query()]


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
