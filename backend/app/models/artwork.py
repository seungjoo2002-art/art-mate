"""작품과 단계별 사진 (v0.4, F-06).

- 작품의 소유자는 학생 개인(`owner_id` = profiles.id). 학원에 소속되지 않은 학생도 만들 수 있다.
- 학원 연결(선택): `academy_id` + `student_membership_id`(그 학원에서의 본인 소속) + 반·과제.
  (academy_id, student_membership_id, owner_id) 복합 FK로 '다른 사람의 소속'이나
  '다른 학원의 반·과제'를
  연결하는 행을 DB가 거부한다.
- 학원 연결 FK는 ON DELETE NO ACTION: 학원·소속 행을 물리 삭제하려면 작품(과 Storage 파일)을 먼저
  처리해야 한다 (파일이 고아가 되지 않도록). 계정 삭제는 owner_id CASCADE.
- 사진 파일은 Supabase Storage(비공개 버킷)에만 있고 DB에는 경로·메타데이터만 저장한다.
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
from app.models.enums import ArtworkStage, PhotoStatus


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
        # 단계별 대표 사진은 최대 1장
        Index(
            "uq_artwork_photos_representative",
            "artwork_id",
            "stage",
            unique=True,
            postgresql_where=text("is_representative"),
        ),
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
    stage: Mapped[ArtworkStage] = mapped_column(enum_column(ArtworkStage, "artwork_stage"))
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
