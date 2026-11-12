"""v0.9.6 AI provider OpenAI, consent age band and guardian confirmation

ai_processing_consents (기존 행은 그대로 — 새 컬럼은 모두 NULL 허용)
- provider CHECK에 'OPENAI' 추가 (varchar + CHECK라 값 추가만)
- age_band: 동의 시점 연령 구간 UNDER_13 / MINOR / ADULT (생년월은 저장하지 않음)
- guardian_name, guardian_relationship(PARENT / LEGAL_GUARDIAN), guardian_confirmed_at:
  미성년자 동의는 보호자가 별도 링크에서 확인해야 유효
- guardian_token_hash (UNIQUE) / guardian_token_expires_at: 보호자 확인 링크 (원문 토큰 미저장)
- CHECK guardian_confirmed_has_name: 확인됐으면 보호자 성명·관계 필수

기존 Gemini 동의(age_band NULL)는 새 동의서 버전(AI_CONSENT_VERSION)에서 유효하지 않으므로
학생은 다시 동의한다. 데이터 이관 없음.

downgrade: 새 컬럼 삭제. provider CHECK 원복 전에 OPENAI 동의 행을 삭제한다 (복원 불가 → 주의).

참고: 다른 브랜치(feature/ver2-p0-community-exam, PR #48)에 0011(down 0010)이 있다. 그 변경이
main에 먼저 들어오면 이 파일의 down_revision을 "0011"로 바꾼다.

Revision ID: 0012
Revises: 0010
Create Date: 2026-11-12 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ai_processing_consents"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_ai_processing_consents_provider"), TABLE, type_="check")
    op.create_check_constraint("provider", TABLE, "provider IN ('GOOGLE_GEMINI', 'OPENAI')")

    op.add_column(TABLE, sa.Column("age_band", sa.String(20), nullable=True))
    op.create_check_constraint("age_band", TABLE, "age_band IN ('UNDER_13', 'MINOR', 'ADULT')")
    op.add_column(TABLE, sa.Column("guardian_name", sa.String(50), nullable=True))
    op.add_column(TABLE, sa.Column("guardian_relationship", sa.String(20), nullable=True))
    op.create_check_constraint(
        "guardian_relationship",
        TABLE,
        "guardian_relationship IN ('PARENT', 'LEGAL_GUARDIAN')",
    )
    op.add_column(
        TABLE, sa.Column("guardian_confirmed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(TABLE, sa.Column("guardian_token_hash", sa.String(64), nullable=True))
    op.add_column(
        TABLE, sa.Column("guardian_token_expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_unique_constraint(
        op.f("uq_ai_processing_consents_guardian_token_hash"), TABLE, ["guardian_token_hash"]
    )
    op.create_check_constraint(
        "guardian_confirmed_has_name",
        TABLE,
        "guardian_confirmed_at IS NULL"
        " OR (guardian_name IS NOT NULL AND guardian_relationship IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_ai_processing_consents_guardian_confirmed_has_name"), TABLE, type_="check"
    )
    op.drop_constraint(
        op.f("uq_ai_processing_consents_guardian_token_hash"), TABLE, type_="unique"
    )
    op.drop_constraint(
        op.f("ck_ai_processing_consents_guardian_relationship"), TABLE, type_="check"
    )
    op.drop_constraint(op.f("ck_ai_processing_consents_age_band"), TABLE, type_="check")
    for column in (
        "guardian_token_expires_at",
        "guardian_token_hash",
        "guardian_confirmed_at",
        "guardian_relationship",
        "guardian_name",
        "age_band",
    ):
        op.drop_column(TABLE, column)
    op.execute(sa.text(f"DELETE FROM {TABLE} WHERE provider = 'OPENAI'"))
    op.drop_constraint(op.f("ck_ai_processing_consents_provider"), TABLE, type_="check")
    op.create_check_constraint("provider", TABLE, "provider IN ('GOOGLE_GEMINI')")
