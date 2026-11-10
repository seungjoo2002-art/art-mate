import datetime as dt
import uuid
from typing import Annotated, ClassVar

from pydantic import BaseModel, Field, StringConstraints

from app.models.enums import (
    ArtworkProgress,
    ArtworkStage,
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    PhotoStatus,
    PracticalType,
)
from app.schemas.fields import InputModel, PatchModel, Title
from app.schemas.students import StudentRef

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
    practical_type: PracticalType | None = Field(
        default=None,
        description="실기 유형 (선택). 프로필의 practical_type을 기본값으로 채워 보내도 된다",
    )
    work_category: ArtworkWorkCategory | None = Field(
        default=None, description="작업 목적 (선택): MOCK_EXAM / PERSONAL_PRACTICE / CLASS_WORK"
    )


class ArtworkUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"title", "work_date"})

    title: Title | None = None
    description: ArtworkDescription | None = None
    work_date: dt.date | None = None
    academy_id: uuid.UUID | None = None
    class_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    practical_type: PracticalType | None = Field(default=None, description="null이면 미분류")
    work_category: ArtworkWorkCategory | None = Field(default=None, description="null이면 미분류")


class StageSummary(BaseModel):
    stage: ArtworkStage
    photo_count: int
    representative_photo_id: uuid.UUID | None
    first_uploaded_at: dt.datetime | None
    last_uploaded_at: dt.datetime | None


class ArtworkProgressRead(BaseModel):
    artwork_id: uuid.UUID
    progress: ArtworkProgress = Field(description="사진이 있는 가장 늦은 단계")
    completed: bool = Field(
        description="[호환용] FINAL 사진이 있음 (= has_final_photo). 작품 완료 여부는 work_status"
    )
    has_final_photo: bool = Field(description="FINAL 단계 사진이 있음 (작품 완료 처리 조건)")
    work_status: ArtworkWorkStatus = Field(description="학생이 직접 완료 처리한 작업 상태")
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
    practical_type: PracticalType | None = Field(description="실기 유형 (미분류면 null)")
    work_category: ArtworkWorkCategory | None = Field(description="작업 목적 (미분류면 null)")
    work_status: ArtworkWorkStatus = Field(description="IN_PROGRESS 작업 중 / COMPLETED 작품 완료")
    completed_at: dt.datetime | None = Field(description="작품 완료 시각 (COMPLETED일 때만)")
    progress: ArtworkProgress = Field(description="사진 단계 진행 (업로드된 가장 늦은 단계)")
    photo_count: int
    recording_count: int = Field(
        description="재생 가능한(ACTIVE) 피드백 녹음 수. 삭제·업로드 미완료 녹음 제외"
    )
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
