import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import JoinRequestStatus, MembershipRole, MembershipStatus


class AcademyMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """실제 학원 소속. (학원, 사용자)당 1행이며 탈퇴 후 재가입 시 같은 행을 재활성화한다."""

    __tablename__ = "academy_memberships"
    __table_args__ = (
        UniqueConstraint("academy_id", "user_id"),
        # v0.3: 학원 소유 테이블의 (academy_id, *_membership_id) 복합 FK 대상.
        # 다른 학원의 학생·강사를 참조하는 행을 DB가 거부한다.
        UniqueConstraint("academy_id", "id"),
        # v0.4: artworks의 (academy_id, student_membership_id, owner_id) 복합 FK 대상.
        # 작품에 연결한 소속이 '작품 소유자 본인의 그 학원 소속'인지 DB가 보장한다.
        UniqueConstraint("academy_id", "id", "user_id"),
        Index("ix_academy_memberships_academy_status_role", "academy_id", "status", "role"),
        Index("ix_academy_memberships_user_status", "user_id", "status"),
    )

    academy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("academies.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    role: Mapped[MembershipRole] = mapped_column(enum_column(MembershipRole, "membership_role"))
    status: Mapped[MembershipStatus] = mapped_column(
        enum_column(MembershipStatus, "membership_status"), default=MembershipStatus.ACTIVE
    )
    joined_at: Mapped[datetime]
    left_at: Mapped[datetime | None]


class AcademyJoinRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """학원 가입 요청. 소속(AcademyMembership)과 별도로 요청 이력을 남긴다."""

    __tablename__ = "academy_join_requests"
    __table_args__ = (
        # 가입 요청으로는 학생·강사 역할만 신청할 수 있다 (OWNER/MANAGER 불가)
        CheckConstraint(
            "requested_role IN ('STUDENT', 'INSTRUCTOR')", name="requested_role_allowed"
        ),
        # 같은 학원에 대기 중인 요청은 1개만 (동시 요청도 DB가 차단)
        Index(
            "uq_academy_join_requests_pending",
            "academy_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
        Index("ix_academy_join_requests_academy_status", "academy_id", "status", "created_at"),
        Index("ix_academy_join_requests_user", "user_id", "created_at"),
    )

    academy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("academies.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    requested_role: Mapped[MembershipRole] = mapped_column(
        enum_column(MembershipRole, "requested_role")
    )
    status: Mapped[JoinRequestStatus] = mapped_column(
        enum_column(JoinRequestStatus, "join_request_status"), default=JoinRequestStatus.PENDING
    )
    message: Mapped[str | None] = mapped_column(String(300))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("profiles.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None]
    review_note: Mapped[str | None] = mapped_column(String(300))
