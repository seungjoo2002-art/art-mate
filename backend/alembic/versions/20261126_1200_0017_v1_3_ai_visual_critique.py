"""v1.3 AI visual critique: AI revision examples (artwork_ai_revisions)

artwork_ai_revisions (신규, RLS): 작품 사진 1장 + 기존 AI 첨삭 정리 개선사항으로 만든 AI 수정본.
학생 작품 사진(artwork_photos)과 분리해 사진 수·대표 사진·성장 분석·공유·데이터셋에 섞이지 않게
한다.

기존 표 (값·열 추가만, 기존 행 변경 없음)
- ai_processing_jobs: job_type에 IMAGE_REVISE, revision_id 열 + 진행 중 작업 유니크 인덱스 + CHECK
- ai_processing_consents: purpose에 VISUAL_CRITIQUE (작품 이미지 외부 전송 별도 동의)
- notifications: type에 AI_REVISION_READY, ai_revision_id 열

Storage
- artmate_private.can_access_ai_revision_object(): 새 비공개 버킷 'ai-revisions'용. 수정본 소유자
  본인만
  (정책은 backend/supabase/storage-setup.sql).
- artmate_private.can_access_artwork_object(): 소유자 본인 읽기에 '교체됐지만 피드백 기준 사진·AI
  수정본 원본이라 파일을 남겨 둔 사진'(status DELETED + storage_cleanup_pending = false + 교체 사진이 있음)을
  허용한다. 그냥 삭제한 사진은 지금처럼 읽을 수 없다.
  기존에는 DELETED면 읽기가 막혀 교체 전 사진 Signed URL 발급이 Storage RLS에서 거부됐다.

downgrade: 함수 원복 → 새 표·열 삭제 (수정본 행이 지워진다. Storage 파일은 남는다).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-26 12:00:00+00:00
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_TYPES_V07 = "('TRANSCRIBE', 'SUMMARIZE', 'GROWTH_REPORT', 'PRACTICE_RECOMMEND')"
JOB_TYPES_V13 = "('TRANSCRIBE', 'SUMMARIZE', 'GROWTH_REPORT', 'PRACTICE_RECOMMEND', 'IMAGE_REVISE')"
PURPOSES_V07 = "('FEEDBACK_SUMMARY', 'GROWTH_COACHING')"
PURPOSES_V13 = "('FEEDBACK_SUMMARY', 'GROWTH_COACHING', 'VISUAL_CRITIQUE')"
NOTIFICATION_TYPES_V09 = "('REPORT_READY', 'TASK_RECOMMENDED', 'TASK_REMINDER', 'GOAL_CHECK')"
NOTIFICATION_TYPES_V13 = (
    "('REPORT_READY', 'TASK_RECOMMENDED', 'TASK_REMINDER', 'GOAL_CHECK', 'AI_REVISION_READY')"
)
REVISION_STATUSES = "('QUEUED', 'RUNNING', 'STORING', 'SUCCEEDED', 'FAILED', 'CANCELLED')"

# 기존 함수의 소유자 읽기 조건 (0003). 교체 후 남겨 둔 파일도 소유자는 읽을 수 있게 넓힌다
OWNER_READ_V04 = """(p_mode = 'read' AND p.status <> 'DELETED' AND a.deleted_at IS NULL
              AND p.owner_id = p_user_id)"""
OWNER_READ_V13 = """(p_mode = 'read' AND a.deleted_at IS NULL AND p.owner_id = p_user_id
              AND (p.status <> 'DELETED'
                OR (p.storage_cleanup_pending = false AND EXISTS (
                  -- 교체됐지만 남겨 둔 사진만 (그냥 삭제한 사진은 읽기 불가)
                  SELECT 1 FROM public.artwork_photos n
                  WHERE n.replaces_photo_id = p.id AND n.uploaded_at IS NOT NULL))))"""

REVISION_ACCESS_FUNCTION = """
CREATE OR REPLACE FUNCTION artmate_private.can_access_ai_revision_object(
    p_user_id uuid, p_object_name text, p_mode text
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT p_user_id IS NOT NULL AND EXISTS (
        SELECT 1
        FROM public.artwork_ai_revisions r
        JOIN public.artworks a ON a.id = r.artwork_id
        WHERE r.storage_path = p_object_name
          AND r.owner_id = p_user_id
          AND split_part(p_object_name, '/', 1) = p_user_id::text
          AND (
            p_mode = 'write'
            OR (p_mode = 'read' AND r.deleted_at IS NULL AND a.deleted_at IS NULL)
          )
    )
$$;
"""


def _module(number: str):  # type: ignore[no-untyped-def]
    path = next(Path(__file__).parent.glob(f"*_{number}_*.py"))
    spec = importlib.util.spec_from_file_location(f"artmate_rev_{number}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _v11_function() -> str:
    return _module("0016")._v11_function()  # type: ignore[no-any-return]


def _v13_function() -> str:
    original = _v11_function()
    assert original.count(OWNER_READ_V04) == 1
    return original.replace(OWNER_READ_V04, OWNER_READ_V13, 1)


def _replace_check(table: str, name: str, condition: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(name, table, condition)


def upgrade() -> None:
    op.create_table(
        "artwork_ai_revisions",
        sa.Column("artwork_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("stage_id", sa.Uuid(), nullable=False),
        sa.Column("photo_id", sa.Uuid(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("source_feedback", postgresql.JSONB(), nullable=False),
        sa.Column("improvements", postgresql.JSONB(), nullable=False),
        sa.Column("selection", postgresql.JSONB(), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("retry_of_id", sa.Uuid(), nullable=True),
        sa.Column("storage_path", sa.String(512), nullable=True),
        sa.Column("content_type", sa.String(50), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("result_staging", sa.LargeBinary(), nullable=True),
        sa.Column("storage_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("storage_error_code", sa.String(50), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("api_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("api_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("staged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("storage_ms", sa.Integer(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("api_call_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("input_image_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "estimated_cost_usd",
            sa.Numeric(10, 5),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.String(300), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "storage_cleanup_pending", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"status IN {REVISION_STATUSES}", name=op.f("ck_artwork_ai_revisions_status")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_artwork_ai_revisions_version_positive")),
        sa.CheckConstraint(
            "status <> 'SUCCEEDED' OR (stored_at IS NOT NULL AND storage_path IS NOT NULL)",
            name=op.f("ck_artwork_ai_revisions_succeeded_is_stored"),
        ),
        sa.CheckConstraint(
            "status <> 'STORING' OR result_staging IS NOT NULL",
            name=op.f("ck_artwork_ai_revisions_storing_has_result"),
        ),
        sa.CheckConstraint(
            "api_call_count >= 0 AND input_tokens >= 0 AND output_tokens >= 0",
            name=op.f("ck_artwork_ai_revisions_usage_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["artwork_id", "owner_id"],
            ["artworks.id", "artworks.owner_id"],
            name=op.f("fk_artwork_ai_revisions_artwork_id_artworks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stage_id", "artwork_id"],
            ["artwork_stages.id", "artwork_stages.artwork_id"],
            name=op.f("fk_artwork_ai_revisions_stage_id_artwork_stages"),
        ),
        sa.ForeignKeyConstraint(
            ["photo_id", "artwork_id"],
            ["artwork_photos.id", "artwork_photos.artwork_id"],
            name=op.f("fk_artwork_ai_revisions_photo_id_artwork_photos"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ai_processing_jobs.id"],
            name=op.f("fk_artwork_ai_revisions_job_id_ai_processing_jobs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_id"],
            ["artwork_ai_revisions.id"],
            name=op.f("fk_artwork_ai_revisions_retry_of_id_artwork_ai_revisions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artwork_ai_revisions")),
        sa.UniqueConstraint(
            "photo_id", "version", name=op.f("uq_artwork_ai_revisions_photo_id_version")
        ),
        sa.UniqueConstraint("storage_path", name=op.f("uq_artwork_ai_revisions_storage_path")),
    )
    op.create_index(
        "uq_artwork_ai_revisions_request",
        "artwork_ai_revisions",
        ["owner_id", "request_hash"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('QUEUED', 'RUNNING', 'STORING', 'SUCCEEDED') AND deleted_at IS NULL"
        ),
    )
    op.create_index(
        "ix_artwork_ai_revisions_photo", "artwork_ai_revisions", ["photo_id", "created_at"]
    )
    op.create_index(
        "ix_artwork_ai_revisions_stage",
        "artwork_ai_revisions",
        ["artwork_id", "stage_id", "created_at"],
    )
    op.create_index(
        "ix_artwork_ai_revisions_owner_created",
        "artwork_ai_revisions",
        ["owner_id", "created_at"],
    )
    op.create_index(
        "ix_artwork_ai_revisions_staged",
        "artwork_ai_revisions",
        ["staged_at"],
        postgresql_where=sa.text("status = 'STORING'"),
    )
    op.create_index(
        "ix_artwork_ai_revisions_owner_cleanup",
        "artwork_ai_revisions",
        ["owner_id"],
        postgresql_where=sa.text("storage_cleanup_pending"),
    )
    op.execute("ALTER TABLE artwork_ai_revisions ENABLE ROW LEVEL SECURITY")

    # ai_processing_jobs
    op.add_column("ai_processing_jobs", sa.Column("revision_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ai_processing_jobs_revision_id_artwork_ai_revisions"),
        "ai_processing_jobs",
        "artwork_ai_revisions",
        ["revision_id"],
        ["id"],
        ondelete="CASCADE",
    )
    _replace_check("ai_processing_jobs", "job_type", f"job_type IN {JOB_TYPES_V13}")
    op.create_check_constraint(
        "image_revise_has_revision",
        "ai_processing_jobs",
        "job_type <> 'IMAGE_REVISE' OR (revision_id IS NOT NULL AND artwork_id IS NOT NULL)",
    )
    op.create_index(
        "uq_ai_processing_jobs_active_revision",
        "ai_processing_jobs",
        ["revision_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED', 'RUNNING') AND revision_id IS NOT NULL"),
    )

    # ai_processing_consents
    _replace_check("ai_processing_consents", "purpose", f"purpose IN {PURPOSES_V13}")

    # notifications
    op.add_column("notifications", sa.Column("ai_revision_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_notifications_ai_revision_id_artwork_ai_revisions"),
        "notifications",
        "artwork_ai_revisions",
        ["ai_revision_id"],
        ["id"],
        ondelete="CASCADE",
    )
    _replace_check("notifications", "type", f"type IN {NOTIFICATION_TYPES_V13}")

    # Storage 접근 함수
    op.execute(_v13_function())
    op.execute(REVISION_ACCESS_FUNCTION)
    op.execute(
        "REVOKE ALL ON FUNCTION artmate_private.can_access_ai_revision_object(uuid, text, text) "
        "FROM PUBLIC"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN "
        "GRANT EXECUTE ON FUNCTION "
        "artmate_private.can_access_ai_revision_object(uuid, text, text) TO authenticated; "
        "END IF; END $$"
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS artmate_private.can_access_ai_revision_object(uuid, text, text)"
    )
    op.execute(_v11_function())

    op.execute("DELETE FROM notifications WHERE type = 'AI_REVISION_READY'")
    _replace_check("notifications", "type", f"type IN {NOTIFICATION_TYPES_V09}")
    op.drop_constraint(
        op.f("fk_notifications_ai_revision_id_artwork_ai_revisions"),
        "notifications",
        type_="foreignkey",
    )
    op.drop_column("notifications", "ai_revision_id")

    op.execute("DELETE FROM ai_processing_consents WHERE purpose = 'VISUAL_CRITIQUE'")
    _replace_check("ai_processing_consents", "purpose", f"purpose IN {PURPOSES_V07}")

    op.execute("DELETE FROM ai_processing_jobs WHERE job_type = 'IMAGE_REVISE'")
    op.drop_index("uq_ai_processing_jobs_active_revision", table_name="ai_processing_jobs")
    op.drop_constraint(
        op.f("ck_ai_processing_jobs_image_revise_has_revision"),
        "ai_processing_jobs",
        type_="check",
    )
    _replace_check("ai_processing_jobs", "job_type", f"job_type IN {JOB_TYPES_V07}")
    op.drop_constraint(
        op.f("fk_ai_processing_jobs_revision_id_artwork_ai_revisions"),
        "ai_processing_jobs",
        type_="foreignkey",
    )
    op.drop_column("ai_processing_jobs", "revision_id")

    for index in (
        "ix_artwork_ai_revisions_owner_cleanup",
        "ix_artwork_ai_revisions_staged",
        "ix_artwork_ai_revisions_owner_created",
        "ix_artwork_ai_revisions_stage",
        "ix_artwork_ai_revisions_photo",
        "uq_artwork_ai_revisions_request",
    ):
        op.drop_index(index, table_name="artwork_ai_revisions")
    op.drop_table("artwork_ai_revisions")
