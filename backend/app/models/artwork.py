"""작품과 단계별 사진 (v0.4, F-06).

- 작품의 소유자는 학생 개인(`owner_id` = profiles.id). 학원에 소속되지 않은 학생도 만들 수 있다.
- 학원 연결(선택): `academy_id` + `student_membership_id`(그 학원에서의 본인 소속) + 반·과제.
  (academy_id, student_membership_id, owner_id) 복합 FK로 '다른 사람의 소속'이나
  '다른 학원의 반·과제'를
  연결하는 행을 DB가 거부한다.
- 학원 연결 FK는 ON DELETE NO ACTION: 학원·소속 행을 물리 삭제하려면 작품(과 Storage 파일)을 먼저
  처리해야 한다 (파일이 고아가 되지 않도록). 계정 삭제는 owner_id CASCADE.
- 사진 파일은 Supabase Storage(비공개 버킷)에만 있고 DB에는 경로·메타데이터만 저장한다.
- v0.5.1 분류·완료: practical_type(실기 유형)과 work_category(작업 목적)는 독립 속성이다.
  work_status(IN_PROGRESS/COMPLETED)는 학생이 직접 바꾸는 작업 상태로, 사진 단계(progress)와 다르다.
  COMPLETED ⇔ completed_at IS NOT NULL (CHECK). 완료에는 FINAL 사진이 필요하다 (서비스 검증).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import (
    ArtworkExamStageCode,
    ArtworkStage,
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    PhotoKind,
    PhotoStatus,
    PracticalType,
    TimerEventType,
    TimeSource,
)

# 작업 시간·제한 시간 상한 (분). 하루를 넘는 기록은 입력 오류로 본다
MAX_WORK_MINUTES = 1440
# 작품 단계 (v0.9.7) 개수·이름 길이
MAX_ARTWORK_STAGES = 10
MAX_STAGE_NAME = 30


class Artwork(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "artworks"
    __table_args__ = (
        # artwork_photos의 (artwork_id, owner_id) 복합 FK 대상
        UniqueConstraint("id", "owner_id"),
        ForeignKeyConstraint(
            ["academy_id", "student_membership_id", "owner_id"],
            [
                "academy_memberships.academy_id",
                "academy_memberships.id",
                "academy_memberships.user_id",
            ],
        ),
        ForeignKeyConstraint(["academy_id", "class_id"], ["classes.academy_id", "classes.id"]),
        ForeignKeyConstraint(["academy_id", "task_id"], ["tasks.academy_id", "tasks.id"]),
        CheckConstraint(
            "(academy_id IS NULL) = (student_membership_id IS NULL)", name="academy_link_pair"
        ),
        CheckConstraint(
            "academy_id IS NOT NULL OR (class_id IS NULL AND task_id IS NULL)",
            name="links_require_academy",
        ),
        CheckConstraint("length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint(
            "(work_status = 'COMPLETED') = (completed_at IS NOT NULL)",
            name="completed_has_time",
        ),
        # v0.9 F-2 시간 기록
        CheckConstraint(
            f"actual_minutes IS NULL OR actual_minutes BETWEEN 1 AND {MAX_WORK_MINUTES}",
            name="actual_minutes_range",
        ),
        CheckConstraint(
            f"time_limit_minutes IS NULL OR time_limit_minutes BETWEEN 1 AND {MAX_WORK_MINUTES}",
            name="time_limit_range",
        ),
        CheckConstraint(
            "(actual_minutes IS NULL) = (time_source IS NULL)", name="actual_minutes_source"
        ),
        Index("ix_artworks_owner_work_date", "owner_id", "work_date"),
        Index("ix_artworks_academy_student", "academy_id", "student_membership_id", "work_date"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    academy_id: Mapped[uuid.UUID | None]
    student_membership_id: Mapped[uuid.UUID | None]
    class_id: Mapped[uuid.UUID | None]
    task_id: Mapped[uuid.UUID | None]
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(1000))
    # 작업 날짜 (Asia/Seoul)
    work_date: Mapped[date]
    # 삭제 시각 (soft delete). 사진은 DELETED 처리 후 Storage에서 정리한다.
    deleted_at: Mapped[datetime | None]
    # v0.5.1 분류 (NULL = 미분류, 기존 작품 호환)
    practical_type: Mapped[PracticalType | None] = mapped_column(
        enum_column(PracticalType, "practical_type")
    )
    work_category: Mapped[ArtworkWorkCategory | None] = mapped_column(
        enum_column(ArtworkWorkCategory, "work_category")
    )
    # v0.5.1 작업 상태. 기존 작품은 IN_PROGRESS
    work_status: Mapped[ArtworkWorkStatus] = mapped_column(
        enum_column(ArtworkWorkStatus, "work_status"),
        server_default=ArtworkWorkStatus.IN_PROGRESS.value,
        default=ArtworkWorkStatus.IN_PROGRESS,
    )
    completed_at: Mapped[datetime | None]
    # v0.9 F-2 작품 정보·시간 기록 (모두 선택)
    topic: Mapped[str | None] = mapped_column(String(200))  # 실기 주제 (시험 제시어 등)
    # v0.9.8 시험 제시물 (예: "유리컵, 사과 2개, 흰 천"). 데이터셋 메타데이터
    exam_materials: Mapped[str | None] = mapped_column(String(500))
    work_method: Mapped[str | None] = mapped_column(String(100))  # 작업 방식 (재료·기법)
    actual_minutes: Mapped[int | None] = mapped_column(Integer)  # 실제 소요 시간 (분)
    time_limit_minutes: Mapped[int | None] = mapped_column(Integer)  # 제한 시간 (분, 모의시험)
    time_source: Mapped[TimeSource | None] = mapped_column(enum_column(TimeSource, "time_source"))


class ArtworkTimerEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """작품 타이머 이벤트 (v0.9 F-2, append-only).

    서버는 타이머 프로세스를 돌리지 않는다. 클라이언트가 시작·일시정지·재개·종료를 보내면 기록만
    하고, 현재 상태와 누적 시간은 조회할 때 이벤트로 계산한다 → 새로고침·앱 종료 후에도 복원된다.
    STOP 시 누적 시간을 artworks.actual_minutes(time_source=TIMER)에 기록한다.
    """

    __tablename__ = "artwork_timer_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artwork_id", "owner_id"], ["artworks.id", "artworks.owner_id"], ondelete="CASCADE"
        ),
        CheckConstraint("elapsed_seconds >= 0", name="elapsed_nonnegative"),
        Index("ix_artwork_timer_events_artwork", "artwork_id", "occurred_at", "created_at"),
    )

    artwork_id: Mapped[uuid.UUID]
    owner_id: Mapped[uuid.UUID]
    event_type: Mapped[TimerEventType] = mapped_column(enum_column(TimerEventType, "event_type"))
    # 이벤트 시각 (오프라인으로 늦게 보낸 이벤트는 클라이언트 시각, 서버가 범위 검증)
    occurred_at: Mapped[datetime]
    # 이 이벤트 직후 현재 세션의 누적 작업 시간 (감사·복원 확인용)
    elapsed_seconds: Mapped[int] = mapped_column(Integer)


class ArtworkExamStage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """실기시험 단계 계획·진행 (VER.2). 작품 타이머의 누적 시간(일시정지 제외)을 기준으로 기록한다.

    - 계획: 단계 순서(position)와 목표 시간(분). 시작 전에만 단계 구성을 바꿀 수 있다.
    - 진행: 타이머 START → 첫 단계 시작, "다음 단계" → 현재 단계 종료 + 다음 단계 시작,
      STOP → 현재 단계 종료, RESET·새 세션 START → 진행 기록 초기화.
    - started/ended_elapsed는 타이머 누적 초 → 일시정지 시간이 단계 시간에 들어가지 않는다.
    """

    __tablename__ = "artwork_exam_stages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artwork_id", "owner_id"], ["artworks.id", "artworks.owner_id"], ondelete="CASCADE"
        ),
        UniqueConstraint("artwork_id", "stage"),
        UniqueConstraint("artwork_id", "position"),
        CheckConstraint(
            f"target_minutes BETWEEN 1 AND {MAX_WORK_MINUTES}", name="target_minutes_range"
        ),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint(
            "ended_elapsed IS NULL OR (started_elapsed IS NOT NULL"
            " AND ended_elapsed >= started_elapsed)",
            name="ended_after_started",
        ),
        CheckConstraint("(started_elapsed IS NULL) = (started_at IS NULL)", name="started_pair"),
        CheckConstraint("(ended_elapsed IS NULL) = (ended_at IS NULL)", name="ended_pair"),
    )

    artwork_id: Mapped[uuid.UUID]
    owner_id: Mapped[uuid.UUID]
    stage: Mapped[ArtworkExamStageCode] = mapped_column(enum_column(ArtworkExamStageCode, "stage"))
    position: Mapped[int] = mapped_column(Integer)
    target_minutes: Mapped[int] = mapped_column(Integer)
    started_elapsed: Mapped[int | None] = mapped_column(Integer)
    ended_elapsed: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]


class ArtworkStageDef(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """작품별 제작 단계 (v0.9.7). 학생이 개수·이름·순서를 정한다 (기본: 스케치·채색·완성).

    - 사진·녹음·글 첨삭이 stage_id로 연결된다. 연결된 데이터가 있는 단계를 빼면 지우지 않고
      archived_at만 기록해 숨긴다 (데이터 보존, 다시 넣으면 복원).
    - legacy_stage: 이전 고정 3단계(SKETCH·PROGRESS·FINAL)와의 호환 값. 위치로 정한다
      (첫 단계 SKETCH, 마지막 단계 FINAL, 나머지 PROGRESS)
      → 진행도·작품 완료 조건 등 기존 기능 유지.
    - target_minutes: 시험 모드의 단계 목표 시간 (선택).
    """

    __tablename__ = "artwork_stages"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artwork_id", "owner_id"], ["artworks.id", "artworks.owner_id"], ondelete="CASCADE"
        ),
        # 사진·녹음·글 첨삭의 (stage_id, artwork_id) 복합 FK 대상 → 다른 작품의 단계에 연결 불가
        UniqueConstraint("id", "artwork_id"),
        Index(
            "uq_artwork_stages_active_position",
            "artwork_id",
            "position",
            unique=True,
            postgresql_where=text("archived_at IS NULL"),
        ),
        CheckConstraint("position >= 0", name="position_nonnegative"),
        CheckConstraint(
            f"length(btrim(name)) > 0 AND char_length(name) <= {MAX_STAGE_NAME}",
            name="name_length",
        ),
        CheckConstraint(
            f"target_minutes IS NULL OR target_minutes BETWEEN 1 AND {MAX_WORK_MINUTES}",
            name="target_minutes_range",
        ),
    )

    artwork_id: Mapped[uuid.UUID]
    owner_id: Mapped[uuid.UUID]
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(MAX_STAGE_NAME))
    legacy_stage: Mapped[ArtworkStage] = mapped_column(enum_column(ArtworkStage, "legacy_stage"))
    target_minutes: Mapped[int | None] = mapped_column(Integer)
    archived_at: Mapped[datetime | None]


class ArtworkPhoto(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """작품 단계 사진 1장. 업로드 요청(PENDING) → 완료 검증(ACTIVE) → 삭제·교체(DELETED)."""

    __tablename__ = "artwork_photos"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artwork_id", "owner_id"], ["artworks.id", "artworks.owner_id"], ondelete="CASCADE"
        ),
        CheckConstraint(
            "status <> 'ACTIVE' OR (uploaded_at IS NOT NULL AND size_bytes IS NOT NULL"
            " AND sha256 IS NOT NULL AND width IS NOT NULL AND height IS NOT NULL)",
            name="active_has_metadata",
        ),
        CheckConstraint(
            "NOT is_representative OR status = 'ACTIVE'", name="representative_is_active"
        ),
        # 단계별 대표 사진은 최대 1장 (v0.9.7: 사용자 정의 단계 기준)
        Index(
            "uq_artwork_photos_representative",
            "stage_id",
            unique=True,
            postgresql_where=text("is_representative"),
        ),
        ForeignKeyConstraint(
            ["stage_id", "artwork_id"], ["artwork_stages.id", "artwork_stages.artwork_id"]
        ),
        # v0.9.8: 피드백 기준 이미지·레이블의 (photo_id, artwork_id) 복합 FK 대상
        UniqueConstraint("id", "artwork_id"),
        # 단계 사진은 피드백에 연결하지 않는다 (v0.9.8부터 수정 사진도 일반 사진과 같게 대표 가능)
        CheckConstraint(
            "feedback_note_id IS NULL OR feedback_recording_id IS NULL", name="one_feedback_ref"
        ),
        CheckConstraint(
            "kind = 'REVISION' OR (feedback_note_id IS NULL AND feedback_recording_id IS NULL)",
            name="stage_photo_no_feedback_ref",
        ),
        Index("ix_artwork_photos_stage", "stage_id", "kind", "status"),
        # 같은 작품에 같은 파일(내용 해시) 중복 업로드 방지
        Index(
            "uq_artwork_photos_active_sha256",
            "artwork_id",
            "sha256",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_artwork_photos_artwork_status_stage", "artwork_id", "status", "stage"),
        Index(
            "ix_artwork_photos_owner_cleanup",
            "owner_id",
            postgresql_where=text("storage_cleanup_pending"),
        ),
    )

    artwork_id: Mapped[uuid.UUID]
    owner_id: Mapped[uuid.UUID]
    # 이전 고정 3단계 값 (호환용). v0.9.7부터 stage_id의 위치로 계산해 함께 저장한다
    stage: Mapped[ArtworkStage] = mapped_column(enum_column(ArtworkStage, "artwork_stage"))
    # v0.9.7 사용자 정의 단계·사진 종류·연결된 피드백
    stage_id: Mapped[uuid.UUID]
    kind: Mapped[PhotoKind] = mapped_column(
        enum_column(PhotoKind, "photo_kind"),
        server_default=PhotoKind.STAGE.value,
        default=PhotoKind.STAGE,
    )
    # 수정 사진이 반영한 피드백 (피드백을 지워도 사진은 남는다 → SET NULL)
    feedback_note_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feedback_notes.id", ondelete="SET NULL")
    )
    feedback_recording_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feedback_recordings.id", ondelete="SET NULL")
    )
    status: Mapped[PhotoStatus] = mapped_column(
        enum_column(PhotoStatus, "photo_status"), default=PhotoStatus.PENDING
    )
    # 버킷 내 경로 "{owner_id}/{artwork_id}/{photo_id}.{ext}" (서버가 생성, 사용자 입력 미사용)
    storage_path: Mapped[str] = mapped_column(String(512), unique=True)
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    is_representative: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    # 이 시각까지 완료 처리하지 않으면 업로드 요청은 만료된다
    upload_expires_at: Mapped[datetime]
    uploaded_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    # 교체 업로드: 완료되면 이 사진을 DELETED로 바꾸고 대표 여부를 이어받는다
    replaces_photo_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artwork_photos.id", ondelete="SET NULL")
    )
    # DB에서는 DELETED인데 Storage 파일 삭제가 아직 확인되지 않음 → 다음 요청 때 재시도
    storage_cleanup_pending: Mapped[bool] = mapped_column(
        Boolean, server_default=false(), default=False
    )
