"""v1.1 원본 제시물 사진 (작품당 0~N장, 학생 본인만)."""

import datetime as dt
import uuid

from pydantic import BaseModel, Field

from app.models.enums import PhotoStatus
from app.schemas.artworks import FileName, UploadTarget
from app.schemas.fields import InputModel


class ReferenceUploadRequest(InputModel):
    content_type: str = Field(
        min_length=1, max_length=50, description="image/jpeg · image/png · image/webp"
    )
    file_size: int = Field(ge=1, description="바이트 (서버 상한 ARTWORK_MAX_UPLOAD_BYTES)")
    file_name: FileName | None = Field(default=None, description="확장자 확인용 (저장에는 안 씀)")
    replaces_photo_id: uuid.UUID | None = Field(
        default=None, description="교체할 원본 사진 (완료되면 이전 사진은 삭제, 같은 순서 자리)"
    )


class ReferencePhotoRead(BaseModel):
    id: uuid.UUID
    artwork_id: uuid.UUID
    position: int = Field(description="보여 줄 순서 (0부터)")
    status: PhotoStatus
    content_type: str
    size_bytes: int | None
    width: int | None
    height: int | None
    uploaded_at: dt.datetime | None
    created_at: dt.datetime
    url: str | None = Field(default=None, description="include_urls=true일 때 짧은 만료 Signed URL")
    url_expires_at: dt.datetime | None = None


class ReferencePhotoList(BaseModel):
    items: list[ReferencePhotoRead] = Field(description="업로드 완료(ACTIVE) 사진, 순서대로")
    max_count: int = Field(description="작품당 최대 장수 (설정 ARTWORK_MAX_REFERENCE_PHOTOS)")


class ReferenceUploadTicket(BaseModel):
    photo: ReferencePhotoRead
    upload: UploadTarget
