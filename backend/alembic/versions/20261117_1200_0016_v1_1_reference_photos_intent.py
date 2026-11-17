"""v1.1 original subject (reference) photos, exam conditions, expression intent

artworks (모두 NULL 허용·기본값 → 기존 작품 그대로)
- paper_size, exam_conditions: 시험 조건 (실기 주제=topic, 제시물 설명=exam_materials,
  시험 시간=time_limit_minutes, 자유 메모=description 은 기존 열 재사용)
- expression_methods varchar[] DEFAULT '{}' + 값 CHECK, expression_intent

artwork_reference_photos (신규, RLS): 원본 제시물 사진. 학생 작품 사진(artwork_photos)과 분리해
단계·대표·진행률·공유 계산에 섞이지 않게 한다. 같은 비공개 버킷 'artworks'의
`{owner}/{artwork}/ref-{id}.{ext}` 경로 → 기존 사진 경로·Storage 정책은 바꾸지 않는다.

artmate_private.can_access_artwork_object(): 기존 조건(artwork_photos)은 그대로 두고, 원본 사진은
소유자 본인만 읽기·쓰기 허용하도록 OR 조건 추가. Storage 정책(storage-setup.sql)은 변경 없음.

downgrade: 함수 원복 → 표·열 삭제 (원본 사진 행이 지워진다. Storage 파일은 남는다).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-17 12:00:00+00:00
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPRESSION_METHODS = ("SCALE", "ROTATE", "REPEAT", "CUT", "DISTORT", "REARRANGE", "OTHER")

REFERENCE_ACCESS = """
        OR EXISTS (
            -- v1.1 원본 제시물 사진: 소유자 본인만 (경로 첫 폴더 = 본인 ID)
            SELECT 1
            FROM public.artwork_reference_photos r
            JOIN public.artworks a ON a.id = r.artwork_id
            WHERE r.storage_path = p_object_name
              AND r.owner_id = p_user_id
              AND split_part(p_object_name, '/', 1) = p_user_id::text
              AND (
                p_mode = 'write'
                OR (p_mode = 'read' AND r.status <> 'DELETED' AND a.deleted_at IS NULL)
              )
        )
"""


def _v04_function() -> str:
    """0003에서 만든 함수 정의 (원복용, 그리고 v1.1 확장의 바탕)."""
    path = next(Path(__file__).parent.glob("*_0003_*.py"))
    spec = importlib.util.spec_from_file_location("artmate_rev_0003", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.STORAGE_ACCESS_FUNCTION


def _v11_function() -> str:
    original = _v04_function()
    head = "SELECT p_user_id IS NOT NULL AND EXISTS ("
    tail = "\n    )\n$$;"
    assert original.count(head) == 1 and original.rstrip().endswith(tail.strip())
    body = original.replace(head, "SELECT p_user_id IS NOT NULL AND (\n        EXISTS (", 1)
    end = body.rstrip().rfind("$$;")
    return body[:end].rstrip() + "\n" + REFERENCE_ACCESS + "    )\n$$;\n"


def upgrade() -> None:
    op.add_column("artworks", sa.Column("paper_size", sa.String(50), nullable=True))
    op.add_column("artworks", sa.Column("exam_conditions", sa.String(500), nullable=True))
    op.add_column(
        "artworks",
        sa.Column(
            "expression_methods",
            postgresql.ARRAY(sa.String(20)),
            server_default=sa.text("'{}'::varchar[]"),
            nullable=False,
        ),
    )
    op.add_column("artworks", sa.Column("expression_intent", sa.String(1000), nullable=True))
    allowed = ", ".join(f"'{m}'" for m in EXPRESSION_METHODS)
    op.create_check_constraint(
        "expression_methods_valid", "artworks", f"expression_methods <@ ARRAY[{allowed}]::varchar[]"
    )

    op.create_table(
        "artwork_reference_photos",
        sa.Column("artwork_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaces_photo_id", sa.Uuid(), nullable=True),
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
            "position >= 0", name=op.f("ck_artwork_reference_photos_position_nonnegative")
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'ACTIVE', 'DELETED')",
            name=op.f("ck_artwork_reference_photos_status"),
        ),
        sa.ForeignKeyConstraint(
            ["artwork_id", "owner_id"],
            ["artworks.id", "artworks.owner_id"],
            name=op.f("fk_artwork_reference_photos_artwork_id_artworks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replaces_photo_id"],
            ["artwork_reference_photos.id"],
            name=op.f("fk_artwork_reference_photos_replaces_photo_id_artwork_reference_photos"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artwork_reference_photos")),
        sa.UniqueConstraint("storage_path", name=op.f("uq_artwork_reference_photos_storage_path")),
    )
    op.create_index(
        "ix_artwork_reference_photos_artwork",
        "artwork_reference_photos",
        ["artwork_id", "status", "position"],
    )
    op.create_index(
        "uq_artwork_reference_photos_active_sha256",
        "artwork_reference_photos",
        ["artwork_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_artwork_reference_photos_owner_cleanup",
        "artwork_reference_photos",
        ["owner_id"],
        postgresql_where=sa.text("storage_cleanup_pending"),
    )
    op.execute("ALTER TABLE artwork_reference_photos ENABLE ROW LEVEL SECURITY")
    op.execute(_v11_function())


def downgrade() -> None:
    op.execute(_v04_function())
    op.drop_index(
        "ix_artwork_reference_photos_owner_cleanup", table_name="artwork_reference_photos"
    )
    op.drop_index(
        "uq_artwork_reference_photos_active_sha256", table_name="artwork_reference_photos"
    )
    op.drop_index("ix_artwork_reference_photos_artwork", table_name="artwork_reference_photos")
    op.drop_table("artwork_reference_photos")
    op.drop_constraint("expression_methods_valid", "artworks", type_="check")
    op.drop_column("artworks", "expression_intent")
    op.drop_column("artworks", "expression_methods")
    op.drop_column("artworks", "exam_conditions")
    op.drop_column("artworks", "paper_size")
