"""피드백 음성 녹음과 녹음 동의 (v0.5, F-11).

- feedback_recordings: 작품에 연결된 녹음 파일의 메타데이터. 파일은 비공개 오디오 버킷에만 있다.
  학원 소속·접근 범위는 연결된 작품(artworks.academy_id, student_membership_id)을 따른다
  (같은 정보를 중복 저장하지 않음).
- recording_consents: 사용자의 녹음 동의 이력 (append-only, 철회는 revoked_at). 동의서 버전별로
  기록하고, 녹음마다 어떤 동의에 근거했는지(consent_id) 남긴다.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import ConsentGrantor, ConsentType, RecordingStatus, TranscriptionStatus


class RecordingConsent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recording_consents"
    __table_args__ = (
        # 유형별 유효한(철회되지 않은) 동의는 1개
        Index(
            "uq_recording_consents_active",
            "user_id",
            "consent_type",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index("ix_recording_consents_user_granted", "user_id", "granted_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    consent_type: Mapped[ConsentType] = mapped_column(enum_column(ConsentType, "consent_type"))
    policy_version: Mapped[str] = mapped_column(String(20))
    granted_by: Mapped[ConsentGrantor] = mapped_column(enum_column(ConsentGrantor, "granted_by"))
    granted_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class FeedbackRecording(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "feedback_recordings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artwork_id", "owner_id"], ["artworks.id", "artworks.owner_id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "status <> 'ACTIVE' OR (uploaded_at IS NOT NULL AND size_bytes IS NOT NULL"
            " AND sha256 IS NOT NULL)",
            name="active_has_metadata",
        ),
        CheckConstraint("duration_ms > 0", name="duration_positive"),
        # 같은 작품에 같은 파일 중복 업로드 방지
        Index(
            "uq_feedback_recordings_active_sha256",
            "artwork_id",
            "sha256",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_feedback_recordings_artwork_status", "artwork_id", "status", "created_at"),
        Index(
            "ix_feedback_recordings_owner_cleanup",
            "owner_id",
            postgresql_where=text("storage_cleanup_pending"),
        ),
        # v0.6 STT 작업 큐 조회용
        Index(
            "ix_feedback_recordings_transcription_pending",
            "transcription_status",
            "created_at",
            postgresql_where=text("transcription_status IN ('PENDING', 'PROCESSING')"),
        ),
    )

    artwork_id: Mapped[uuid.UUID]
    # 녹음한 학생 (= 작품 소유자)
    owner_id: Mapped[uuid.UUID]
    consent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recording_consents.id"))
    # 녹음에 다른 사람(강사)의 목소리가 담긴다는 사실을 알렸다고 학생이 확인함
    speaker_notice_confirmed: Mapped[bool] = mapped_column(Boolean)
    title: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[RecordingStatus] = mapped_column(
        enum_column(RecordingStatus, "recording_status"), default=RecordingStatus.PENDING
    )
    # "{owner_id}/{artwork_id}/{recording_id}.{ext}" (서버 생성)
    storage_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    # 녹음 길이 (클라이언트 MediaRecorder 측정값, 범위 검증). WAV는 서버가 헤더로 다시 계산
    duration_ms: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    recorded_at: Mapped[datetime | None]
    upload_expires_at: Mapped[datetime]
    uploaded_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    storage_cleanup_pending: Mapped[bool] = mapped_column(
        Boolean, server_default=false(), default=False
    )
    # STT (v0.6). v0.5에서는 NOT_REQUESTED 고정, 작업을 실행하지 않는다
    transcription_status: Mapped[TranscriptionStatus] = mapped_column(
        enum_column(TranscriptionStatus, "transcription_status"),
        default=TranscriptionStatus.NOT_REQUESTED,
    )
    transcription_updated_at: Mapped[datetime | None]
