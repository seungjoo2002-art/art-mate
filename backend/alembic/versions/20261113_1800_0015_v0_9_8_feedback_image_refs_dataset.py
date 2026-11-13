"""v0.9.8 photo timeline, feedback reference images, dataset foundation

artwork_photos
- 수정 사진(REVISION)도 일반 단계 사진과 같게 취급: 대표 사진 제한(revision_not_representative) 해제.
  kind·feedback_*_id 컬럼과 기존 데이터는 그대로 보존한다 (어떤 피드백 뒤에 올린 사진인지 기록).
- (id, artwork_id) UNIQUE: 피드백 기준 이미지·레이블이 같은 작품의 사진만 가리키도록 복합 FK 대상

artworks.exam_materials (신규, NULL): 시험 제시물 메타데이터

feedback_recordings, feedback_notes
- image_ref_status NONE / SUGGESTED / CONFIRMED (+ 확인 시각·확인한 사람)

feedback_image_refs (신규, RLS): 피드백 ↔ 기준 사진 N장 (생성 시 고정)
- 기존 피드백 백필: 피드백 시점(녹음 시각·작성 시각) 이전에 올린 같은 단계(단계 미지정이면 작품 전체)의
  최신 ACTIVE 사진 1장을 **제안(SUGGESTED)** 으로만 연결한다. 확인(CONFIRMED)으로 올리지 않으므로
  학습 데이터에 자동 등록되지 않는다. 시점 이전 사진이 없으면 NONE.

dataset_consents (신규, RLS): AI 학습 활용 동의
feedback_labels (신규, RLS): 피드백 구조화 레이블 (원문과 분리, AI 추정 / 전문가 확인 구분)

downgrade: 새 테이블·컬럼 삭제. 수정 사진 대표 제한을 되돌리기 전에 대표로 지정된 수정 사진은 대표에서 내린다
(사진 자체는 삭제하지 않음).

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-13 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ONE_FEEDBACK = "(feedback_recording_id IS NULL) <> (feedback_note_id IS NULL)"
PROBLEM_TYPES = (
    "('COMPOSITION', 'FORM', 'PROPORTION', 'PERSPECTIVE', 'VALUE', 'COLOR', 'TEXTURE',"
    " 'RENDERING', 'FINISH', 'OTHER', 'TIME_MANAGEMENT')"
)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    ]


def upgrade() -> None:
    # ---------------------------------------------------------------- artwork_photos / artworks
    op.drop_constraint(
        op.f("ck_artwork_photos_revision_not_representative"), "artwork_photos", type_="check"
    )
    op.create_unique_constraint(
        op.f("uq_artwork_photos_id_artwork_id"), "artwork_photos", ["id", "artwork_id"]
    )
    op.add_column("artworks", sa.Column("exam_materials", sa.String(500), nullable=True))

    # ------------------------------------------------------ 녹음·글 첨삭: 기준 이미지 확인 상태
    for table in ("feedback_recordings", "feedback_notes"):
        op.add_column(
            table,
            sa.Column("image_ref_status", sa.String(20), server_default="NONE", nullable=False),
        )
        op.add_column(
            table, sa.Column("image_ref_confirmed_at", sa.DateTime(timezone=True), nullable=True)
        )
        op.add_column(table, sa.Column("image_ref_confirmed_by", sa.Uuid(), nullable=True))
        op.create_check_constraint(
            "image_ref_status", table, "image_ref_status IN ('NONE', 'SUGGESTED', 'CONFIRMED')"
        )
        op.create_foreign_key(
            op.f(f"fk_{table}_image_ref_confirmed_by_profiles"),
            table,
            "profiles",
            ["image_ref_confirmed_by"],
            ["id"],
            ondelete="SET NULL",
        )

    # ---------------------------------------------------------------- feedback_image_refs
    op.create_table(
        "feedback_image_refs",
        sa.Column("artwork_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("feedback_recording_id", sa.Uuid(), nullable=True),
        sa.Column("feedback_note_id", sa.Uuid(), nullable=True),
        sa.Column("photo_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(ONE_FEEDBACK, name=op.f("ck_feedback_image_refs_one_feedback")),
        sa.CheckConstraint("position >= 0", name=op.f("ck_feedback_image_refs_position_nonnegative")),
        sa.ForeignKeyConstraint(
            ["artwork_id", "owner_id"],
            ["artworks.id", "artworks.owner_id"],
            name=op.f("fk_feedback_image_refs_artwork_id_artworks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["photo_id", "artwork_id"],
            ["artwork_photos.id", "artwork_photos.artwork_id"],
            name=op.f("fk_feedback_image_refs_photo_id_artwork_photos"),
        ),
        sa.ForeignKeyConstraint(
            ["feedback_recording_id"],
            ["feedback_recordings.id"],
            name=op.f("fk_feedback_image_refs_feedback_recording_id_feedback_r_99c0"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["feedback_note_id"],
            ["feedback_notes.id"],
            name=op.f("fk_feedback_image_refs_feedback_note_id_feedback_notes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_image_refs")),
    )
    op.create_index(
        "uq_feedback_image_refs_recording_photo",
        "feedback_image_refs",
        ["feedback_recording_id", "photo_id"],
        unique=True,
        postgresql_where=sa.text("feedback_recording_id IS NOT NULL"),
    )
    op.create_index(
        "uq_feedback_image_refs_note_photo",
        "feedback_image_refs",
        ["feedback_note_id", "photo_id"],
        unique=True,
        postgresql_where=sa.text("feedback_note_id IS NOT NULL"),
    )
    op.create_index("ix_feedback_image_refs_photo", "feedback_image_refs", ["photo_id"])
    op.execute("ALTER TABLE feedback_image_refs ENABLE ROW LEVEL SECURITY")

    # 기존 피드백: 피드백 시점 이전 최신 사진을 '제안'으로만 연결 (확인 아님 → 학습 데이터 자동 등록 없음)
    for table, column, at in (
        (
            "feedback_recordings",
            "feedback_recording_id",
            "COALESCE(f.recorded_at, f.uploaded_at, f.created_at)",
        ),
        ("feedback_notes", "feedback_note_id", "f.created_at"),
    ):
        op.execute(
            f"INSERT INTO feedback_image_refs (id, artwork_id, owner_id, {column}, photo_id, position)"
            " SELECT DISTINCT ON (f.id) gen_random_uuid(), f.artwork_id, f.owner_id, f.id, p.id, 0"
            f" FROM {table} f JOIN artwork_photos p ON p.artwork_id = f.artwork_id"
            " AND p.status = 'ACTIVE' AND p.uploaded_at IS NOT NULL"
            f" AND p.uploaded_at <= {at}"
            " AND (f.stage_id IS NULL OR p.stage_id = f.stage_id)"
            f" ORDER BY f.id, p.uploaded_at DESC, p.id DESC"
        )
        op.execute(
            f"UPDATE {table} f SET image_ref_status = 'SUGGESTED' WHERE EXISTS ("
            f" SELECT 1 FROM feedback_image_refs r WHERE r.{column} = f.id)"
        )

    # ---------------------------------------------------------------- dataset_consents
    op.create_table(
        "dataset_consents",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.String(20), nullable=False),
        sa.Column("age_band", sa.String(20), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "age_band IN ('UNDER_14', 'TEEN', 'ADULT')", name=op.f("ck_dataset_consents_age_band")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["profiles.id"],
            name=op.f("fk_dataset_consents_user_id_profiles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_consents")),
    )
    op.create_index(
        "uq_dataset_consents_active",
        "dataset_consents",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.execute("ALTER TABLE dataset_consents ENABLE ROW LEVEL SECURITY")

    # ---------------------------------------------------------------- feedback_labels
    op.create_table(
        "feedback_labels",
        sa.Column("artwork_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("feedback_recording_id", sa.Uuid(), nullable=True),
        sa.Column("feedback_note_id", sa.Uuid(), nullable=True),
        sa.Column("summary_id", sa.Uuid(), nullable=True),
        sa.Column("origin", sa.String(20), nullable=False),
        sa.Column("verification", sa.String(20), server_default="UNVERIFIED", nullable=False),
        sa.Column("problem_type", sa.String(20), nullable=False),
        sa.Column("target_object", sa.String(100), nullable=True),
        sa.Column("photo_id", sa.Uuid(), nullable=True),
        sa.Column("region", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("severity", sa.SmallInteger(), nullable=True),
        sa.Column(
            "evidence_segment_ids",
            postgresql.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"),
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("verified_by", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(ONE_FEEDBACK, name=op.f("ck_feedback_labels_one_feedback")),
        sa.CheckConstraint(
            "severity IS NULL OR severity BETWEEN 1 AND 3",
            name=op.f("ck_feedback_labels_severity_range"),
        ),
        sa.CheckConstraint(
            "verification = 'UNVERIFIED' OR (verified_by IS NOT NULL AND verified_at IS NOT NULL)",
            name=op.f("ck_feedback_labels_verified_has_actor"),
        ),
        sa.CheckConstraint(
            "length(btrim(description)) > 0", name=op.f("ck_feedback_labels_description_not_blank")
        ),
        sa.CheckConstraint(
            "origin IN ('AI', 'EXPERT', 'STUDENT')", name=op.f("ck_feedback_labels_label_origin")
        ),
        sa.CheckConstraint(
            "verification IN ('UNVERIFIED', 'CONFIRMED', 'REJECTED')",
            name=op.f("ck_feedback_labels_label_verification"),
        ),
        sa.CheckConstraint(
            f"problem_type IN {PROBLEM_TYPES}", name=op.f("ck_feedback_labels_problem_type")
        ),
        sa.ForeignKeyConstraint(
            ["artwork_id", "owner_id"],
            ["artworks.id", "artworks.owner_id"],
            name=op.f("fk_feedback_labels_artwork_id_artworks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["photo_id", "artwork_id"],
            ["artwork_photos.id", "artwork_photos.artwork_id"],
            name=op.f("fk_feedback_labels_photo_id_artwork_photos"),
        ),
        sa.ForeignKeyConstraint(
            ["feedback_recording_id"],
            ["feedback_recordings.id"],
            name=op.f("fk_feedback_labels_feedback_recording_id_feedback_recordings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["feedback_note_id"],
            ["feedback_notes.id"],
            name=op.f("fk_feedback_labels_feedback_note_id_feedback_notes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["summary_id"],
            ["feedback_summaries.id"],
            name=op.f("fk_feedback_labels_summary_id_feedback_summaries"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["profiles.id"],
            name=op.f("fk_feedback_labels_created_by_profiles"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by"],
            ["profiles.id"],
            name=op.f("fk_feedback_labels_verified_by_profiles"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_labels")),
    )
    op.create_index("ix_feedback_labels_recording", "feedback_labels", ["feedback_recording_id"])
    op.create_index("ix_feedback_labels_note", "feedback_labels", ["feedback_note_id"])
    op.execute("ALTER TABLE feedback_labels ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_feedback_labels_note", table_name="feedback_labels")
    op.drop_index("ix_feedback_labels_recording", table_name="feedback_labels")
    op.drop_table("feedback_labels")
    op.drop_index("uq_dataset_consents_active", table_name="dataset_consents")
    op.drop_table("dataset_consents")
    op.drop_index("ix_feedback_image_refs_photo", table_name="feedback_image_refs")
    op.drop_index("uq_feedback_image_refs_note_photo", table_name="feedback_image_refs")
    op.drop_index("uq_feedback_image_refs_recording_photo", table_name="feedback_image_refs")
    op.drop_table("feedback_image_refs")
    for table in ("feedback_notes", "feedback_recordings"):
        op.drop_constraint(
            op.f(f"fk_{table}_image_ref_confirmed_by_profiles"), table, type_="foreignkey"
        )
        op.drop_constraint(op.f(f"ck_{table}_image_ref_status"), table, type_="check")
        for column in ("image_ref_confirmed_by", "image_ref_confirmed_at", "image_ref_status"):
            op.drop_column(table, column)
    op.drop_column("artworks", "exam_materials")
    op.drop_constraint(op.f("uq_artwork_photos_id_artwork_id"), "artwork_photos", type_="unique")
    # 대표로 지정된 수정 사진은 대표에서 내린다 (사진은 보존)
    op.execute(
        "UPDATE artwork_photos SET is_representative = false"
        " WHERE kind = 'REVISION' AND is_representative"
    )
    op.create_check_constraint(
        "revision_not_representative", "artwork_photos", "kind = 'STAGE' OR NOT is_representative"
    )
