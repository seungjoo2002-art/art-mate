import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import PracticalType, StudentGrade, UserType


class Profile(TimestampMixin, Base):
    """서비스 사용자 프로필. id = Supabase auth.users.id (JWT sub).

    이메일·비밀번호 등 인증 정보는 저장하지 않는다 (Supabase Auth가 관리).
    auth.users FK(ON DELETE CASCADE)는 마이그레이션에서 auth 스키마가 있을 때만 추가한다.
    """

    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint("length(btrim(display_name)) > 0", name="display_name_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str] = mapped_column(String(50))
    user_type: Mapped[UserType] = mapped_column(enum_column(UserType, "user_type"), index=True)
    avatar_path: Mapped[str | None] = mapped_column(String(512))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    # 실기 유형 (v0.5.1). 기존 회원은 NULL. AI 맞춤 피드백·참고작 추천(F-15)에 사용 예정
    practical_type: Mapped[PracticalType | None] = mapped_column(
        enum_column(PracticalType, "practical_type")
    )
    # v0.9 F-1 학습 목표 (모두 선택, 학원 가입과 무관)
    grade: Mapped[StudentGrade | None] = mapped_column(enum_column(StudentGrade, "grade"))
    learning_goal: Mapped[str | None] = mapped_column(String(500))
    # 학습 목표를 마지막으로 바꾼 시각 (목표 확인 알림 기준)
    learning_goal_updated_at: Mapped[datetime | None]
    # VER.2 실명 (본인 /users/me 응답에만, 공개 프로필·커뮤니티·강사 화면에는 display_name만)
    real_name: Mapped[str | None] = mapped_column(String(50))
    # VER.2 기본 실기시험 단계 목표 [{"stage": "IDEA", "target_minutes": 40}, ...] (NULL = 앱
    # 기본값)
    exam_stage_targets: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)


class TargetUniversity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """지망 대학 (v0.9 F-1). 사용자가 직접 입력한다 (외부 입시 정보·합격 예측 없음).

    우선순위는 사용자별 1부터 연속. (user_id, priority) 유니크는 DEFERRABLE이라 한 트랜잭션
    안에서 순서를 바꿀 수 있다.
    """

    __tablename__ = "target_universities"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "priority",
            name="uq_target_universities_user_priority",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("priority >= 1", name="priority_positive"),
        CheckConstraint("length(btrim(university_name)) > 0", name="name_not_blank"),
        Index("ix_target_universities_user", "user_id", "priority"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    university_name: Mapped[str] = mapped_column(String(100))
    department: Mapped[str | None] = mapped_column(String(100))
    # 전형·메모 (예: 수시 실기, 정시) — 자유 입력
    admission_note: Mapped[str | None] = mapped_column(String(200))
    priority: Mapped[int] = mapped_column(Integer)
