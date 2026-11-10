"""앱 내부 알림 API (v0.9 F-9)."""

import datetime as dt
import uuid

from pydantic import BaseModel, Field, model_validator

from app.models.enums import NotificationType
from app.schemas.common import Page
from app.schemas.fields import InputModel


class NotificationRead(BaseModel):
    id: uuid.UUID
    type: NotificationType
    title: str
    body: str | None
    report_id: uuid.UUID | None = Field(
        description="관련 성장 리포트 → GET /growth/me/reports/{id}"
    )
    recommendation_id: uuid.UUID | None = Field(
        description="관련 맞춤 과제 → GET /growth/me/recommendations/{id}"
    )
    is_read: bool
    read_at: dt.datetime | None
    created_at: dt.datetime


class NotificationPage(Page[NotificationRead]):
    unread_count: int = Field(description="숨기지 않은 안 읽은 알림 수 (배지 표시용)")


class NotificationPreferenceRead(BaseModel):
    report_ready: bool = Field(description="새 성장 리포트")
    task_recommended: bool = Field(description="새 맞춤 과제 (추천·학원 배포)")
    task_reminder: bool = Field(description="채택 후 미완료 과제 안내")
    goal_check: bool = Field(description="학습 목표 확인 안내 (월 1회)")
    reminder_after_days: int = Field(description="채택 후 며칠 지나면 미완료 안내 (1~30)")


class NotificationPreferenceUpdate(InputModel):
    report_ready: bool | None = None
    task_recommended: bool | None = None
    task_reminder: bool | None = None
    goal_check: bool | None = None
    reminder_after_days: int | None = Field(default=None, ge=1, le=30)

    @model_validator(mode="after")
    def _some(self) -> "NotificationPreferenceUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"'{name}' cannot be null")
        return self


class ReadAllResult(BaseModel):
    updated: int
