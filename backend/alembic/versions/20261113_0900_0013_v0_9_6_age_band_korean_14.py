"""v0.9.6 consent age bands by Korean age of consent (14)

ai_processing_consents.age_band 값을 한국 개인정보 보호법 기준으로 바꾼다.
- 이전: UNDER_13 / MINOR(13~17) / ADULT
- 이후: UNDER_14 / TEEN(14~17) / ADULT

기존 행 변환 (보수적 — 더 엄격한 구간으로):
- UNDER_13 → UNDER_14
- MINOR → UNDER_14 (13세와 14~17세를 구분할 수 없으므로. 학생이 생년월로 다시 동의하면 TEEN으로 바뀜)
2026-11-13 운영 DB 읽기 전용 확인: age_band가 있는 행 0건 (Gemini v1 동의 3건은 NULL) → 실제 변환 없음.

downgrade: UNDER_14 → UNDER_13, TEEN → MINOR (둘 다 이전 규칙에서 차단되는 쪽).

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-13 09:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "ai_processing_consents"
CHECK = "ck_ai_processing_consents_age_band"


def upgrade() -> None:
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.execute(
        sa.text(
            f"UPDATE {TABLE} SET age_band = 'UNDER_14' WHERE age_band IN ('UNDER_13', 'MINOR')"
        )
    )
    op.create_check_constraint("age_band", TABLE, "age_band IN ('UNDER_14', 'TEEN', 'ADULT')")


def downgrade() -> None:
    op.drop_constraint(op.f(CHECK), TABLE, type_="check")
    op.execute(sa.text(f"UPDATE {TABLE} SET age_band = 'UNDER_13' WHERE age_band = 'UNDER_14'"))
    op.execute(sa.text(f"UPDATE {TABLE} SET age_band = 'MINOR' WHERE age_band = 'TEEN'"))
    op.create_check_constraint("age_band", TABLE, "age_band IN ('UNDER_13', 'MINOR', 'ADULT')")
