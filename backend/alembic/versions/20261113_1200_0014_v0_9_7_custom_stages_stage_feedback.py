"""v0.9.7 custom artwork stages, stage-linked feedback, revision photos

artwork_stages (신규, RLS)
- 작품별 단계 (위치·이름·시험 목표 시간·숨김). 기존 작품은 고정 3단계를 그대로 옮긴다:
  스케치(SKETCH) / 중간 작업(PROGRESS) / 완성(FINAL) — 화면에 보이던 이름 유지
- (id, artwork_id) UNIQUE: 사진·녹음·글 첨삭이 같은 작품의 단계에만 연결되도록 복합 FK 대상

artwork_photos
- stage_id NOT NULL: 기존 사진은 같은 작품의 같은 legacy 단계로 연결 (데이터 손실 없음)
- kind STAGE(기본, 기존 사진 전부) / REVISION(피드백 반영 수정 사진)
- feedback_note_id / feedback_recording_id: 수정 사진이 반영한 피드백 (피드백 삭제 시 SET NULL)
- 대표 사진 유니크: (artwork_id, stage) → (stage_id)
- stage(legacy) 컬럼은 호환용으로 유지 (진행도·작품 완료 조건 계산)

feedback_recordings, feedback_notes
- stage_id NULL 허용 (NULL = 작품 전체 피드백). 기존 피드백은 모두 작품 전체로 유지

downgrade: 새 컬럼·테이블 삭제, 대표 사진 유니크를 (artwork_id, stage)로 되돌린다
(같은 legacy 단계에 대표가 여럿이면 가장 먼저 올린 사진만 대표로 남김). 수정 사진은 일반 사진으로 남는다.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-13 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY = "('SKETCH', 'PROGRESS', 'FINAL')"


def upgrade() -> None:
    op.create_table(
        "artwork_stages",
        sa.Column("artwork_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("legacy_stage", sa.String(20), nullable=False),
        sa.Column("target_minutes", sa.Integer(), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("position >= 0", name=op.f("ck_artwork_stages_position_nonnegative")),
        sa.CheckConstraint(
            "length(btrim(name)) > 0 AND char_length(name) <= 30",
            name=op.f("ck_artwork_stages_name_length"),
        ),
        sa.CheckConstraint(
            "target_minutes IS NULL OR target_minutes BETWEEN 1 AND 1440",
            name=op.f("ck_artwork_stages_target_minutes_range"),
        ),
        sa.CheckConstraint(
            f"legacy_stage IN {LEGACY}", name=op.f("ck_artwork_stages_legacy_stage")
        ),
        sa.ForeignKeyConstraint(
            ["artwork_id", "owner_id"],
            ["artworks.id", "artworks.owner_id"],
            name=op.f("fk_artwork_stages_artwork_id_artworks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artwork_stages")),
        sa.UniqueConstraint("id", "artwork_id", name=op.f("uq_artwork_stages_id_artwork_id")),
    )
    op.create_index(
        "uq_artwork_stages_active_position",
        "artwork_stages",
        ["artwork_id", "position"],
        unique=True,
        postgresql_where=sa.text("archived_at IS NULL"),
    )
    op.execute("ALTER TABLE artwork_stages ENABLE ROW LEVEL SECURITY")

    # 기존 작품: 이전 고정 3단계를 그대로 (화면에 보이던 이름)
    op.execute(
        "INSERT INTO artwork_stages (id, artwork_id, owner_id, position, name, legacy_stage)"
        " SELECT gen_random_uuid(), a.id, a.owner_id, s.pos, s.name, s.code FROM artworks a"
        " CROSS JOIN (VALUES (0, '스케치', 'SKETCH'), (1, '중간 작업', 'PROGRESS'),"
        " (2, '완성', 'FINAL')) AS s(pos, name, code)"
    )

    # ---------------------------------------------------------------- artwork_photos
    op.add_column("artwork_photos", sa.Column("stage_id", sa.Uuid(), nullable=True))
    op.execute(
        "UPDATE artwork_photos p SET stage_id = s.id FROM artwork_stages s"
        " WHERE s.artwork_id = p.artwork_id AND s.legacy_stage = p.stage"
    )
    op.alter_column("artwork_photos", "stage_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_artwork_photos_stage_id_artwork_stages"),
        "artwork_photos",
        "artwork_stages",
        ["stage_id", "artwork_id"],
        ["id", "artwork_id"],
    )
    op.add_column(
        "artwork_photos",
        sa.Column("kind", sa.String(20), server_default="STAGE", nullable=False),
    )
    op.create_check_constraint("photo_kind", "artwork_photos", "kind IN ('STAGE', 'REVISION')")
    op.add_column("artwork_photos", sa.Column("feedback_note_id", sa.Uuid(), nullable=True))
    op.add_column("artwork_photos", sa.Column("feedback_recording_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_artwork_photos_feedback_note_id_feedback_notes"),
        "artwork_photos",
        "feedback_notes",
        ["feedback_note_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_artwork_photos_feedback_recording_id_feedback_recordings"),
        "artwork_photos",
        "feedback_recordings",
        ["feedback_recording_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "revision_not_representative", "artwork_photos", "kind = 'STAGE' OR NOT is_representative"
    )
    op.create_check_constraint(
        "one_feedback_ref",
        "artwork_photos",
        "feedback_note_id IS NULL OR feedback_recording_id IS NULL",
    )
    op.create_check_constraint(
        "stage_photo_no_feedback_ref",
        "artwork_photos",
        "kind = 'REVISION' OR (feedback_note_id IS NULL AND feedback_recording_id IS NULL)",
    )
    op.drop_index("uq_artwork_photos_representative", table_name="artwork_photos")
    op.create_index(
        "uq_artwork_photos_representative",
        "artwork_photos",
        ["stage_id"],
        unique=True,
        postgresql_where=sa.text("is_representative"),
    )
    op.create_index("ix_artwork_photos_stage", "artwork_photos", ["stage_id", "kind", "status"])

    # ------------------------------------------------ 녹음·글 첨삭: 단계 연결 (NULL = 작품 전체)
    for table in ("feedback_recordings", "feedback_notes"):
        op.add_column(table, sa.Column("stage_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_{table}_stage_id_artwork_stages"),
            table,
            "artwork_stages",
            ["stage_id", "artwork_id"],
            ["id", "artwork_id"],
        )


def downgrade() -> None:
    for table in ("feedback_notes", "feedback_recordings"):
        op.drop_constraint(op.f(f"fk_{table}_stage_id_artwork_stages"), table, type_="foreignkey")
        op.drop_column(table, "stage_id")

    op.drop_index("ix_artwork_photos_stage", table_name="artwork_photos")
    op.drop_index("uq_artwork_photos_representative", table_name="artwork_photos")
    # 같은 legacy 단계에 대표가 여럿이면 가장 먼저 올린 사진만 남긴다
    op.execute(
        "UPDATE artwork_photos p SET is_representative = false WHERE is_representative AND EXISTS ("
        " SELECT 1 FROM artwork_photos q WHERE q.artwork_id = p.artwork_id AND q.stage = p.stage"
        " AND q.is_representative AND (q.uploaded_at, q.id) < (p.uploaded_at, p.id))"
    )
    op.create_index(
        "uq_artwork_photos_representative",
        "artwork_photos",
        ["artwork_id", "stage"],
        unique=True,
        postgresql_where=sa.text("is_representative"),
    )
    for name in (
        "stage_photo_no_feedback_ref",
        "one_feedback_ref",
        "revision_not_representative",
        "photo_kind",
    ):
        op.drop_constraint(op.f(f"ck_artwork_photos_{name}"), "artwork_photos", type_="check")
    op.drop_constraint(
        op.f("fk_artwork_photos_feedback_recording_id_feedback_recordings"),
        "artwork_photos",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_artwork_photos_feedback_note_id_feedback_notes"),
        "artwork_photos",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_artwork_photos_stage_id_artwork_stages"), "artwork_photos", type_="foreignkey"
    )
    for column in ("feedback_recording_id", "feedback_note_id", "kind", "stage_id"):
        op.drop_column("artwork_photos", column)
    op.drop_index("uq_artwork_stages_active_position", table_name="artwork_stages")
    op.drop_table("artwork_stages")
