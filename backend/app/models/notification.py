"""앱 내부 알림 (v0.9 F-9). 푸시·이메일은 보내지 않는다.

- notifications: 사용자별 알림 1건. (user_id, dedupe_key) 유니크로 같은 이벤트의 중복 알림을 막는다.
  읽음(read_at)·숨김(hidden_at). 관련 리포트·과제가 삭제되면 알림도 사라진다 (CASCADE).
- notification_preferences: 유형별 켜기/끄기와 미완료 과제 안내 기준 일수.
  행이 없으면 기본값(모두 켬).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import NotificationType


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("uq_notifications_user_dedupe", "user_id", "dedupe_key", unique=True),
        Index("ix_notifications_user_created", "user_id", "created_at"),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    type: Mapped[NotificationType] = mapped_column(enum_column(NotificationType, "type"))
    title: Mapped[str] = mapped_column(String(100))
    body: Mapped[str | None] = mapped_column(String(300))
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("growth_reports.id", ondelete="CASCADE")
    )
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("practice_recommendations.id", ondelete="CASCADE")
    )
    # 같은 이벤트 식별 키 (예: report:{id}, task-reminder:{id}:{주차})
    dedupe_key: Mapped[str] = mapped_column(String(150))
    read_at: Mapped[datetime | None]
    hidden_at: Mapped[datetime | None]


class NotificationPreference(TimestampMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        CheckConstraint("reminder_after_days BETWEEN 1 AND 30", name="reminder_days_range"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True
    )
    report_ready: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    task_recommended: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    task_reminder: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    goal_check: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    # 채택 후 이 일수가 지나도록 완료하지 않은 과제를 안내 (주 1회, 과제당 최대 3회)
    reminder_after_days: Mapped[int] = mapped_column(Integer, server_default="3", default=3)
