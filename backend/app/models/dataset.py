"""AI 미대입시 첨삭 데이터셋 기반 (v0.9.8).

- feedback_image_refs: 피드백(녹음·글 첨삭)이 근거로 삼은 작품 사진 (여러 장 가능).
  피드백을 만들 때 고정 저장한다 → 나중에 사진이 추가돼도 과거 피드백의 기준 이미지는 바뀌지 않는다.
  STT 전사·AI 요약은 원본 피드백(녹음·글)에 매달리므로 같은 연결을 그대로 쓴다.
- dataset_consents: AI 학습 활용 동의 (AI 요약 동의와 별개).
  동의가 없으면 학습 데이터로 내보내지 않는다.
- feedback_labels: 피드백 구조화 레이블 (문제 유형·대상·위치·내용·권장 수정·중요도·근거).
  원문(피드백·전사)과 분리하고, AI 추정과 전문가 확인을 origin·verification으로 구분한다.
  언급되지 않은 항목은 행이 없을 뿐 "정상"을 뜻하지 않는다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import (
    AiAgeBand,
    LabelOrigin,
    LabelVerification,
    WeaknessCategory,
)

MAX_IMAGE_REFS = 10  # 피드백 1개가 참조할 수 있는 사진 수
_ONE_FEEDBACK = "(feedback_recording_id IS NULL) <> (feedback_note_id IS NULL)"


class FeedbackImageRef(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """피드백 1개 ↔ 기준 사진 N장. 같은 작품의 사진만 (복합 FK)."""

    __tablename__ = "feedback_image_refs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artwork_id", "owner_id"], ["artworks.id", "artworks.owner_id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["photo_id", "artwork_id"], ["artwork_photos.id", "artwork_photos.artwork_id"]
        ),
        CheckConstraint(_ONE_FEEDBACK, name="one_feedback"),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        Index(
            "uq_feedback_image_refs_recording_photo",
            "feedback_recording_id",
            "photo_id",
            unique=True,
            postgresql_where=text("feedback_recording_id IS NOT NULL"),
        ),
        Index(
            "uq_feedback_image_refs_note_photo",
            "feedback_note_id",
            "photo_id",
            unique=True,
            postgresql_where=text("feedback_note_id IS NOT NULL"),
        ),
        Index("ix_feedback_image_refs_photo", "photo_id"),
    )

    artwork_id: Mapped[uuid.UUID]
    owner_id: Mapped[uuid.UUID]
    feedback_recording_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feedback_recordings.id", ondelete="CASCADE")
    )
    feedback_note_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feedback_notes.id", ondelete="CASCADE")
    )
    photo_id: Mapped[uuid.UUID]
    position: Mapped[int] = mapped_column(Integer)


class DatasetConsent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """AI 첨삭 모델 학습 활용 동의 (학생 본인). 사용자당 유효 동의 1개, 철회하면 revoked_at."""

    __tablename__ = "dataset_consents"
    __table_args__ = (
        Index(
            "uq_dataset_consents_active",
            "user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    policy_version: Mapped[str] = mapped_column(String(20))
    # 동의 시점 연령 구간 (생년월은 저장하지 않음). 만 14세 미만은 현재 동의 불가
    age_band: Mapped[AiAgeBand] = mapped_column(enum_column(AiAgeBand, "age_band"))
    granted_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]


class FeedbackLabel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """피드백 구조화 레이블 1개 (원문과 분리). 강사가 확인한 것만 정답 레이블로 쓴다."""

    __tablename__ = "feedback_labels"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artwork_id", "owner_id"], ["artworks.id", "artworks.owner_id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["photo_id", "artwork_id"], ["artwork_photos.id", "artwork_photos.artwork_id"]
        ),
        CheckConstraint(_ONE_FEEDBACK, name="one_feedback"),
        CheckConstraint("severity IS NULL OR severity BETWEEN 1 AND 3", name="severity_range"),
        CheckConstraint(
            "verification = 'UNVERIFIED' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)",
            name="verified_has_actor",
        ),
        CheckConstraint("length(btrim(description)) > 0", name="description_not_blank"),
        Index("ix_feedback_labels_recording", "feedback_recording_id"),
        Index("ix_feedback_labels_note", "feedback_note_id"),
    )

    artwork_id: Mapped[uuid.UUID]
    owner_id: Mapped[uuid.UUID]
    feedback_recording_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feedback_recordings.id", ondelete="CASCADE")
    )
    feedback_note_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feedback_notes.id", ondelete="CASCADE")
    )
    # AI 요약에서 나온 레이블이면 그 요약 (요약이 지워져도 레이블 기록은 남김)
    summary_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feedback_summaries.id", ondelete="SET NULL")
    )
    origin: Mapped[LabelOrigin] = mapped_column(enum_column(LabelOrigin, "label_origin"))
    verification: Mapped[LabelVerification] = mapped_column(
        enum_column(LabelVerification, "label_verification"),
        server_default=LabelVerification.UNVERIFIED.value,
        default=LabelVerification.UNVERIFIED,
    )
    problem_type: Mapped[WeaknessCategory] = mapped_column(
        enum_column(WeaknessCategory, "problem_type")
    )
    target_object: Mapped[str | None] = mapped_column(String(100))  # 지적 대상 사물
    photo_id: Mapped[uuid.UUID | None]  # 위치를 표시한 사진
    # 이미지 내 위치 {x, y, w, h} (0~1 정규화, 사진 기준). 없으면 위치 미지정
    region: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    description: Mapped[str] = mapped_column(Text)  # 문제의 구체적인 내용
    recommendation: Mapped[str | None] = mapped_column(Text)  # 권장 수정 방향
    severity: Mapped[int | None] = mapped_column(SmallInteger)  # 1 낮음 · 2 보통 · 3 높음
    # 원문 근거: 전사·글 첨삭 문장 index (segments)
    evidence_segment_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=text("'{}'::integer[]"), default=list
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None]
