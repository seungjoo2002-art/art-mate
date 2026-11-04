import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints

from app.models.enums import ConsentGrantor, ConsentType, RecordingStatus, TranscriptionStatus
from app.schemas.artworks import UploadTarget
from app.schemas.fields import InputModel

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
    speaker_notice_confirmed: Literal[True] = Field(
        description="녹음되는 강사에게 녹음 사실을 알렸음 (true만 허용)"
    )


class RecordingRead(BaseModel):
    id: uuid.UUID
    artwork_id: uuid.UUID
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
    transcription_status: TranscriptionStatus = Field(
        description="STT 상태 (v0.6, 현재 NOT_REQUESTED)"
    )
    url: str | None = Field(default=None, description="include_urls=true일 때 재생용 Signed URL")
    url_expires_at: dt.datetime | None = None


class RecordingUploadTicket(BaseModel):
    recording: RecordingRead
    upload: UploadTarget


class RecordingUrl(BaseModel):
    recording_id: uuid.UUID
    url: str
    expires_at: dt.datetime
