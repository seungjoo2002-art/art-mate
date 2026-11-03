import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import AcademyStatus


class Academy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "academies"
    __table_args__ = (Index("ix_academies_status_name", "status", "name"),)

    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[AcademyStatus] = mapped_column(
        enum_column(AcademyStatus, "academy_status"), default=AcademyStatus.PENDING_APPROVAL
    )
    # 등록 신청자. 계정 삭제 시에도 학원 기록은 남긴다.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL"), index=True
    )
    # 시스템 ADMIN 심사 정보
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None]
    review_note: Mapped[str | None] = mapped_column(String(500))
