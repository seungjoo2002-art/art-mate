import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from app.models.enums import (
    ConsentGrantor,
    ConsentType,
    RecordingStatus,
    SpeakerConsentStatus,
    TranscriptionStatus,
)
from app.schemas.artworks import UploadTarget
from app.schemas.fields import InputModel
from app.schemas.image_refs import ImageRefsRead

RecordingTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]
FileName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


# ----------------------------------------------------------------------------- consent


class RecordingConsentCreate(InputModel):
    policy_version: str = Field(
        min_length=1,
        max_length=20,
        description="화면에 보여준 동의서 버전 (GET 응답의 required_version)",
    )
    agreed: Literal[True] = Field(description="녹음·저장에 동의함 (true만 허용)")
    granted_by: ConsentGrantor = Field(
        default=ConsentGrantor.SELF, description="만 14세 미만은 GUARDIAN (법정대리인 동의)"
    )


class RecordingConsentRead(BaseModel):
    id: uuid.UUID
    consent_type: ConsentType
    policy_version: str
    granted_by: ConsentGrantor
    granted_at: dt.datetime
    revoked_at: dt.datetime | None


class ConsentStatus(BaseModel):
    required_version: str
    is_valid: bool = Field(description="현재 버전에 유효한 동의가 있음 → 녹음 가능")
    consent: RecordingConsentRead | None = Field(description="철회되지 않은 최신 동의")


# ----------------------------------------------------------------------------- recordings


class RecordingUploadRequest(InputModel):
    content_type: str = Field(examples=["audio/webm;codecs=opus"])
    file_size: int = Field(gt=0, description="바이트")
    duration_ms: int = Field(gt=0, description="녹음 길이 (MediaRecorder 측정값, 밀리초)")
    file_name: FileName | None = Field(default=None, description="확장자 검증용 (저장하지 않음)")
    title: RecordingTitle | None = Field(default=None, examples=["11/4 명암 첨삭"])
    recorded_at: AwareDatetime | None = Field(default=None, description="녹음 시작 시각")
    stage_id: uuid.UUID | None = Field(
        default=None, description="v0.9.7 단계 피드백이면 작품 단계 id. 생략하면 작품 전체 피드백"
    )
    # v0.9.8 피드백 기준 이미지
    reference_photo_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=10,
        description=(
            "이 피드백을 받을 때 본 작품 사진. 생략하면 지금 최신 사진을 제안(SUGGESTED)으로"
        ),
    )
    reference_confirmed: bool = Field(
        default=False, description="reference_photo_ids를 확인함 → CONFIRMED (학습 데이터 조건)"
    )
    speaker_notice_confirmed: Literal[True] = Field(
        description="녹음되는 강사에게 녹음 사실을 알렸음 (true만 허용)"
    )
    speaker_consent_status: Literal[
        SpeakerConsentStatus.NOTICE_GIVEN, SpeakerConsentStatus.CONSENT_REPORTED
    ] = Field(
        default=SpeakerConsentStatus.NOTICE_GIVEN,
        description="v0.9: NOTICE_GIVEN(녹음 사실을 알림) / CONSENT_REPORTED(강사가 동의했다고 "
        "학생이 기록). 학생의 기록일 뿐 강사의 동의를 법적으로 대신하지 않는다",
    )


class RecordingStageUpdate(InputModel):
    """녹음을 어느 단계의 피드백으로 볼지 (v0.9.7). null이면 작품 전체 피드백."""

    stage_id: uuid.UUID | None


class RecordingRead(BaseModel):
    id: uuid.UUID
    artwork_id: uuid.UUID
    stage_id: uuid.UUID | None = Field(
        default=None, description="v0.9.7 연결된 작품 단계 (null = 작품 전체 피드백)"
    )
    title: str | None
    status: RecordingStatus
    content_type: str
    size_bytes: int | None
    duration_ms: int
    recorded_at: dt.datetime | None
    uploaded_at: dt.datetime | None
    created_at: dt.datetime
    consent_id: uuid.UUID
    speaker_notice_confirmed: bool
    speaker_consent_status: SpeakerConsentStatus = Field(
        default=SpeakerConsentStatus.NOT_RECORDED,
        description="강사 고지·동의 상태 (학생 기록, v0.9)",
    )
    speaker_consent_verified: bool = Field(
        default=False,
        description="항상 false: 서비스는 강사의 동의를 직접 확인하지 않는다 (학생 기록만 보관)",
    )
    audio_available: bool = Field(
        default=True, description="음성 파일 재생 가능 (보관 기간이 지나면 false, 전사는 유지)"
    )
    audio_deleted_at: dt.datetime | None = Field(default=None, description="음성 원본 삭제 시각")
    transcription_status: TranscriptionStatus = Field(
        description="STT 상태 (v0.6, 현재 NOT_REQUESTED)"
    )
    url: str | None = Field(default=None, description="include_urls=true일 때 재생용 Signed URL")
    url_expires_at: dt.datetime | None = None
    image_refs: ImageRefsRead = Field(
        default_factory=ImageRefsRead, description="v0.9.8 피드백 기준 이미지"
    )


class RecordingUploadTicket(BaseModel):
    recording: RecordingRead
    upload: UploadTarget


class RecordingUrl(BaseModel):
    recording_id: uuid.UUID
    url: str
    expires_at: dt.datetime
