import datetime as dt
import uuid
from typing import Annotated, ClassVar

from pydantic import BaseModel, Field, StringConstraints

from app.models.enums import ArtworkProgress, ArtworkStage, PhotoStatus
from app.schemas.attendance import StudentRef
from app.schemas.fields import InputModel, PatchModel, Title

ArtworkDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
FileName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class ArtworkCreate(InputModel):
    title: Title = Field(examples=["석고 아그리파 소묘"])
    description: ArtworkDescription | None = None
    work_date: dt.date | None = Field(
        default=None, description="작업 날짜 (Asia/Seoul). 기본: 오늘"
    )
    academy_id: uuid.UUID | None = Field(
        default=None, description="학원 연결(선택). 그 학원에 학생으로 ACTIVE 소속이어야 한다"
    )
    class_id: uuid.UUID | None = Field(default=None, description="수업(반) 연결. academy_id 필요")
    task_id: uuid.UUID | None = Field(default=None, description="과제 연결. 본인에게 배정된 과제")


class ArtworkUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"title", "work_date"})

    title: Title | None = None
    description: ArtworkDescription | None = None
    work_date: dt.date | None = None
    academy_id: uuid.UUID | None = None
    class_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None


class StageSummary(BaseModel):
    stage: ArtworkStage
    photo_count: int
    representative_photo_id: uuid.UUID | None
    first_uploaded_at: dt.datetime | None
    last_uploaded_at: dt.datetime | None


class ArtworkProgressRead(BaseModel):
    artwork_id: uuid.UUID
    progress: ArtworkProgress = Field(description="사진이 있는 가장 늦은 단계")
    completed: bool = Field(description="완성(FINAL) 사진이 있음")
    stages: list[StageSummary]


class ArtworkRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    work_date: dt.date
    academy_id: uuid.UUID | None
    student_membership_id: uuid.UUID | None
    class_id: uuid.UUID | None
    task_id: uuid.UUID | None
    progress: ArtworkProgress
    photo_count: int
    cover_photo_id: uuid.UUID | None = Field(description="대표 사진 (가장 늦은 단계의 대표 사진)")
    created_at: dt.datetime
    updated_at: dt.datetime


class StaffArtworkRead(ArtworkRead):
    student: StudentRef


class PhotoRead(BaseModel):
    id: uuid.UUID
    artwork_id: uuid.UUID
    stage: ArtworkStage
    status: PhotoStatus
    content_type: str
    size_bytes: int | None
    width: int | None
    height: int | None
    is_representative: bool
    uploaded_at: dt.datetime | None
    created_at: dt.datetime
    url: str | None = Field(default=None, description="include_urls=true일 때 Signed URL")
    url_expires_at: dt.datetime | None = None


class ArtworkDetail(ArtworkRead):
    stages: list[StageSummary]
    photos: list[PhotoRead]


class StaffArtworkDetail(ArtworkDetail):
    student: StudentRef


class UploadRequest(InputModel):
    stage: ArtworkStage | None = Field(
        default=None, description="SKETCH / PROGRESS / FINAL. 교체(replaces_photo_id)면 생략 가능"
    )
    content_type: str = Field(examples=["image/jpeg"])
    file_size: int = Field(gt=0, description="바이트")
    file_name: FileName | None = Field(default=None, description="확장자 검증용 (저장하지 않음)")
    replaces_photo_id: uuid.UUID | None = Field(
        default=None, description="교체할 기존 사진. 완료 처리 시 기존 사진이 삭제된다"
    )


class UploadTarget(BaseModel):
    bucket: str
    path: str
    url: str = Field(description="Signed upload URL (PUT으로 파일 업로드)")
    token: str = Field(description="supabase-js uploadToSignedUrl(path, token, file)용")
    expires_at: dt.datetime = Field(description="이 시각 전에 업로드 + 완료 처리")


class UploadTicket(BaseModel):
    photo: PhotoRead
    upload: UploadTarget


class PhotoUpdate(InputModel):
    is_representative: bool = Field(description="true: 이 사진을 단계 대표 사진으로 지정")


class SignedUrl(BaseModel):
    photo_id: uuid.UUID
    url: str
    expires_at: dt.datetime
