"""v0.5.1 planning alignment

기획 변경(AI 기반 실기 학습·성장 관리) 반영:
- profiles.practical_type: 실기 유형 (NULL 허용, 기존 회원 호환)
- artworks.practical_type / work_category: 실기 유형과 작업 목적을 분리 (둘 다 NULL = 미분류)
- artworks.work_status / completed_at: 학생이 직접 완료 처리하는 작업 상태
  (기존 작품은 IN_PROGRESS, completed_at NULL. FINAL 사진이 있어도 자동 완료하지 않는다)

설계 메모:
- 모든 변경은 추가(ADD COLUMN)만 한다. NULL 허용 컬럼과 상수 server_default 컬럼이라
  PostgreSQL 11+ 에서 테이블 재작성 없이 적용된다.
- enum은 기존과 같이 varchar(20) + 이름 있는 CHECK 제약 (ck_<table>_<name>).
- 제외 기능(출석·오늘 할 일·질문 콜·시험 타이머) 테이블은 이 리비전에서 건드리지 않는다.
  물리 삭제는 데이터 확인·승인 후 별도 리비전으로 진행한다.
- downgrade는 이 리비전이 추가한 컬럼·제약만 제거한다 (저장된 분류·완료 정보는 사라진다).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09 10:15:04.779582+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRACTICAL_TYPES = (
    "BASIC_DESIGN",
    "THINKING_SHIFT",
    "IDEA_EXPRESSION",
    "DRAWING",
    "WATERCOLOR",
    "OTHER",
)
WORK_CATEGORIES = ("MOCK_EXAM", "PERSONAL_PRACTICE", "CLASS_WORK")
WORK_STATUSES = ("IN_PROGRESS", "COMPLETED")


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column("profiles", sa.Column("practical_type", sa.String(20), nullable=True))
    op.create_check_constraint(
        "practical_type", "profiles", _in("practical_type", PRACTICAL_TYPES)
    )

    op.add_column("artworks", sa.Column("practical_type", sa.String(20), nullable=True))
    op.add_column("artworks", sa.Column("work_category", sa.String(20), nullable=True))
    op.add_column(
        "artworks",
        sa.Column("work_status", sa.String(20), server_default="IN_PROGRESS", nullable=False),
    )
    op.add_column("artworks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "practical_type", "artworks", _in("practical_type", PRACTICAL_TYPES)
    )
    op.create_check_constraint("work_category", "artworks", _in("work_category", WORK_CATEGORIES))
    op.create_check_constraint("work_status", "artworks", _in("work_status", WORK_STATUSES))
    op.create_check_constraint(
        "completed_has_time",
        "artworks",
        "(work_status = 'COMPLETED') = (completed_at IS NOT NULL)",
    )


def downgrade() -> None:
    for name in ("completed_has_time", "work_status", "work_category", "practical_type"):
        op.drop_constraint(op.f(f"ck_artworks_{name}"), "artworks", type_="check")
    op.drop_column("artworks", "completed_at")
    op.drop_column("artworks", "work_status")
    op.drop_column("artworks", "work_category")
    op.drop_column("artworks", "practical_type")
    op.drop_constraint(op.f("ck_profiles_practical_type"), "profiles", type_="check")
    op.drop_column("profiles", "practical_type")
