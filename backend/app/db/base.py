"""SQLAlchemy Declarative Base와 공통 mixin.

- 제약조건 이름 규칙(naming convention)을 고정해 Alembic 마이그레이션이 두 개발자 환경에서
  동일한 이름을 생성하도록 한다.
- 시각은 항상 timezone-aware(`timestamptz`)로 저장하며, DB에는 UTC로 기록된다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy가 요구하는 클래스 속성
        datetime: DateTime(timezone=True),
    }


class UUIDPrimaryKeyMixin:
    """UUID v4 기본키. (user_profiles처럼 외부 ID를 그대로 쓰는 테이블에는 사용하지 않는다.)"""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
