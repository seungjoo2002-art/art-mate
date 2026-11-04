"""학생 개인 할 일 (v0.3).

학원 데이터가 아니므로 `academy_id`가 없다. 소유자(user_id) 본인만 `/personal-todos`로 접근하며,
학원 강사·관리자 API 어디에서도 조회되지 않는다 (권한 분리).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PersonalTodo(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "personal_todos"
    __table_args__ = (
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        Index("ix_personal_todos_user_due_date", "user_id", "due_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(String(1000))
    # 학원 현지(Asia/Seoul) 날짜. null = 날짜 없는 할 일
    due_date: Mapped[date | None]
    # null = 미완료
    completed_at: Mapped[datetime | None]
