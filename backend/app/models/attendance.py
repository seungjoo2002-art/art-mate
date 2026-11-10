"""출석 기록과 수정 이력 (v0.3).

[v0.5.1 서비스 제외] 기획 변경으로 API·서비스는 제거했다. 테이블은 데이터 보존과 Alembic 모델 일치
(`alembic check`)를 위해 남겨 두며, 물리 삭제는 별도 승인 후 새 리비전으로 진행한다
(docs/v0.5.1-planning-changes.md)."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import AttendanceAuditAction, AttendanceSource, AttendanceStatus


class AttendanceRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """학생의 학원 출석 (학원 현지 날짜당 1건)."""

    __tablename__ = "attendance_records"
    __table_args__ = (
        # 중복 출석 방지: 같은 학생(학원 소속)·같은 날짜는 1건 (동시 요청도 DB가 차단)
        UniqueConstraint("student_membership_id", "attendance_date"),
        # attendance_audit_logs의 (academy_id, attendance_record_id) 복합 FK 대상
        UniqueConstraint("academy_id", "id"),
        ForeignKeyConstraint(
            ["academy_id", "student_membership_id"],
            ["academy_memberships.academy_id", "academy_memberships.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "source <> 'SELF_CHECK_IN' OR checked_in_at IS NOT NULL", name="self_check_in_time"
        ),
        Index("ix_attendance_records_academy_date", "academy_id", "attendance_date"),
    )

    academy_id: Mapped[uuid.UUID]
    student_membership_id: Mapped[uuid.UUID]
    attendance_date: Mapped[date]
    status: Mapped[AttendanceStatus] = mapped_column(
        enum_column(AttendanceStatus, "attendance_status")
    )
    source: Mapped[AttendanceSource] = mapped_column(
        enum_column(AttendanceSource, "attendance_source")
    )
    # 학생이 출석 버튼을 누른 시각 (강사가 기록한 경우 null 가능)
    checked_in_at: Mapped[datetime | None]
    note: Mapped[str | None] = mapped_column(String(300))
    # 마지막으로 기록·수정한 강사
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )


class AttendanceAuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """강사의 출석 기록 생성·수정 이력 (append-only, API로 수정·삭제 불가)."""

    __tablename__ = "attendance_audit_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["academy_id", "attendance_record_id"],
            ["attendance_records.academy_id", "attendance_records.id"],
            ondelete="CASCADE",
        ),
        Index("ix_attendance_audit_logs_record_created", "attendance_record_id", "created_at"),
    )

    academy_id: Mapped[uuid.UUID]
    attendance_record_id: Mapped[uuid.UUID]
    action: Mapped[AttendanceAuditAction] = mapped_column(
        enum_column(AttendanceAuditAction, "attendance_audit_action")
    )
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("academy_memberships.id", ondelete="SET NULL")
    )
    # {"status": "...", "note": "..."} 스냅샷. CREATED이면 previous는 null
    previous: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    current: Mapped[dict[str, Any]] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(String(300))
