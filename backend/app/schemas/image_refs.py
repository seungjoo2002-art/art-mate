"""피드백 기준 이미지 (v0.9.8) 스키마."""

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from app.models.dataset import MAX_IMAGE_REFS
from app.models.enums import ImageRefStatus, PhotoStatus
from app.schemas.fields import InputModel


class FeedbackImageRefRead(BaseModel):
    photo_id: uuid.UUID
    stage_id: uuid.UUID | None
    position: int
    photo_status: PhotoStatus = Field(description="DELETED면 사진이 삭제됨 (연결 기록은 보존)")
    uploaded_at: dt.datetime | None


class ImageRefsRead(BaseModel):
    """이 피드백이 근거로 삼은 작품 사진."""

    status: ImageRefStatus = Field(
        default=ImageRefStatus.NONE,
        description="NONE 기준 사진 없음 / SUGGESTED 시스템 제안(확인 전) / CONFIRMED 확인됨",
    )
    confirmed_at: dt.datetime | None = None
    photos: list[FeedbackImageRefRead] = Field(default_factory=list)


class ImageRefsUpdate(InputModel):
    photo_ids: list[uuid.UUID] = Field(
        max_length=MAX_IMAGE_REFS,
        description=(
            "기준 사진 (순서대로, 같은 작품의 업로드 완료 사진). 빈 배열 = 사진 없이 받은 피드백"
        ),
    )
    confirmed: bool = Field(
        default=True,
        description="true: 이 사진을 보고 받은 피드백이 맞음을 확인 (학습 데이터 조건)",
    )
