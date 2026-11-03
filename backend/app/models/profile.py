import uuid

from sqlalchemy import Boolean, CheckConstraint, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, enum_column
from app.models.enums import UserType


class Profile(TimestampMixin, Base):
    """서비스 사용자 프로필. id = Supabase auth.users.id (JWT sub).

    이메일·비밀번호 등 인증 정보는 저장하지 않는다 (Supabase Auth가 관리).
    auth.users FK(ON DELETE CASCADE)는 마이그레이션에서 auth 스키마가 있을 때만 추가한다.
    """

    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("length(btrim(display_name)) > 0", name="display_name_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(50))
    user_type: Mapped[UserType] = mapped_column(enum_column(UserType, "user_type"), index=True)
    avatar_path: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
