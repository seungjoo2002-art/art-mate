"""ver2 p0 community exam stages

VER.2 P0 (프론트 VER.2 연동). 기존 데이터 보존 (컬럼 추가·NULL 허용·데이터 이관).

community_posts
- artwork_id NULL 허용 → 사진 없는 글 (작품·공유 동의 없이 작성, 본문 필수)
- category (PRACTICE_QUESTION / FEEDBACK_REQUEST / ARTWORK_SHARE / FREE).
  기존 행: question이 있으면 FEEDBACK_REQUEST, 없으면 ARTWORK_SHARE (지금 프론트 표시 규칙과 같음)
- photo_id (작품에서 고른 사진, SET NULL), author_display (사진 없는 글의 작성자 표시)
- CHECK: ARTWORK_SHARE는 작품 필수, 사진 없는 글은 본문 필수, photo_id는 작품 게시물만
shared_artwork_images
- kind PRIMARY(기존 행 전부) / POST(게시물에 고른 사진). 살아 있는 PRIMARY는 작품당 1개(기존 유니크를
  PRIMARY로 한정), POST는 (작품, 원본 사진)당 1개
- Storage 권한 함수 can_access_shared_image: POST 이미지는 커뮤니티 동의 + 그 이미지를 쓰는 ACTIVE
  게시물이 있을 때만 읽기 허용 (참고작 동의로는 열리지 않음)
artwork_exam_stages (신규, RLS)
- 실기시험 단계 계획·진행 (아이디어·스케치·채색·마무리)

downgrade: 사진 없는 글 삭제(댓글 등 CASCADE), POST 이미지 DELETED 처리(파일 정리 대상),
artwork_exam_stages 삭제, 권한 함수 0008 버전으로 복원.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-11 05:36:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIGNATURE = "artmate_private.can_access_shared_image(uuid, text, text)"
CATEGORIES = "('PRACTICE_QUESTION', 'FEEDBACK_REQUEST', 'ARTWORK_SHARE', 'FREE')"

SHARED_IMAGE_FUNCTION_V10 = """
CREATE OR REPLACE FUNCTION artmate_private.can_access_shared_image(
    p_user_id uuid, p_object_name text, p_mode text
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT p_user_id IS NOT NULL AND EXISTS (
        SELECT 1
        FROM public.shared_artwork_images i
        JOIN public.artworks a ON a.id = i.artwork_id
        WHERE i.storage_path = p_object_name
          AND (
            (p_mode = 'write' AND i.owner_id = p_user_id)
            OR
            (p_mode = 'read' AND i.status = 'ACTIVE' AND a.deleted_at IS NULL AND (
              i.owner_id = p_user_id
              OR EXISTS (
                SELECT 1
                FROM public.artwork_sharing_consents c
                WHERE c.artwork_id = i.artwork_id
                  AND c.revoked_at IS NULL
                  AND (
                    -- 대표 이미지: 참고작 동의, 또는 커뮤니티 동의 + 작품의 ACTIVE 게시물
                    (i.kind = 'PRIMARY' AND (
                      c.purpose = 'REFERENCE'
                      OR EXISTS (
                        SELECT 1 FROM public.community_posts p
                        WHERE p.artwork_id = i.artwork_id AND p.status = 'ACTIVE'
                      )
                    ))
                    OR
                    -- 게시물용 이미지: 커뮤니티 동의 + 이 이미지를 쓰는 ACTIVE 게시물만
                    (i.kind = 'POST' AND c.purpose = 'COMMUNITY' AND EXISTS (
                      SELECT 1 FROM public.community_posts p
                      WHERE p.image_id = i.id AND p.status = 'ACTIVE'
                    ))
                  )
                  AND (
                    (c.scope = 'PLATFORM' AND EXISTS (
                      SELECT 1 FROM public.profiles pr
                      WHERE pr.id = p_user_id AND pr.is_active))
                    OR
                    (c.scope = 'ACADEMY' AND EXISTS (
                      SELECT 1 FROM public.academy_memberships m
                      WHERE m.academy_id = c.academy_id
                        AND m.user_id = p_user_id
                        AND m.status = 'ACTIVE'))
                  )
              )
            ))
          )
    )
$$;
"""

SHARED_IMAGE_FUNCTION_V08 = """
CREATE OR REPLACE FUNCTION artmate_private.can_access_shared_image(
    p_user_id uuid, p_object_name text, p_mode text
) RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT p_user_id IS NOT NULL AND EXISTS (
        SELECT 1
        FROM public.shared_artwork_images i
        JOIN public.artworks a ON a.id = i.artwork_id
        WHERE i.storage_path = p_object_name
          AND (
            (p_mode = 'write' AND i.owner_id = p_user_id)
            OR
            (p_mode = 'read' AND i.status = 'ACTIVE' AND a.deleted_at IS NULL AND (
              i.owner_id = p_user_id
              OR EXISTS (
                SELECT 1
                FROM public.artwork_sharing_consents c
                WHERE c.artwork_id = i.artwork_id
                  AND c.revoked_at IS NULL
                  AND (
                    c.purpose = 'REFERENCE'
                    OR EXISTS (
                      SELECT 1 FROM public.community_posts p
                      WHERE p.artwork_id = i.artwork_id AND p.status = 'ACTIVE'
                    )
                  )
                  AND (
                    (c.scope = 'PLATFORM' AND EXISTS (
                      SELECT 1 FROM public.profiles pr
                      WHERE pr.id = p_user_id AND pr.is_active))
                    OR
                    (c.scope = 'ACADEMY' AND EXISTS (
                      SELECT 1 FROM public.academy_memberships m
                      WHERE m.academy_id = c.academy_id
                        AND m.user_id = p_user_id
                        AND m.status = 'ACTIVE'))
                  )
              )
            ))
          )
    )
$$;
"""


def _function(sql: str) -> None:
    op.execute(sql)
    op.execute(f"REVOKE ALL ON FUNCTION {_SIGNATURE} FROM PUBLIC")


def upgrade() -> None:
    op.create_table(
        "artwork_exam_stages",
        sa.Column("artwork_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "stage",
            sa.Enum(
                "IDEA",
                "SKETCH",
                "COLOR",
                "FINISH",
                name="stage",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("target_minutes", sa.Integer(), nullable=False),
        sa.Column("started_elapsed", sa.Integer(), nullable=True),
        sa.Column("ended_elapsed", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
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
            "(ended_elapsed IS NULL) = (ended_at IS NULL)",
            name=op.f("ck_artwork_exam_stages_ended_pair"),
        ),
        sa.CheckConstraint(
            "(started_elapsed IS NULL) = (started_at IS NULL)",
            name=op.f("ck_artwork_exam_stages_started_pair"),
        ),
        sa.CheckConstraint(
            "ended_elapsed IS NULL OR (started_elapsed IS NOT NULL AND ended_elapsed >= started_elapsed)",
            name=op.f("ck_artwork_exam_stages_ended_after_started"),
        ),
        sa.CheckConstraint(
            "position >= 0", name=op.f("ck_artwork_exam_stages_position_nonnegative")
        ),
        sa.CheckConstraint(
            "target_minutes BETWEEN 1 AND 1440",
            name=op.f("ck_artwork_exam_stages_target_minutes_range"),
        ),
        sa.ForeignKeyConstraint(
            ["artwork_id", "owner_id"],
            ["artworks.id", "artworks.owner_id"],
            name=op.f("fk_artwork_exam_stages_artwork_id_artworks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artwork_exam_stages")),
        sa.UniqueConstraint(
            "artwork_id", "position", name=op.f("uq_artwork_exam_stages_artwork_id_position")
        ),
        sa.UniqueConstraint(
            "artwork_id", "stage", name=op.f("uq_artwork_exam_stages_artwork_id_stage")
        ),
    )
    op.execute("ALTER TABLE artwork_exam_stages ENABLE ROW LEVEL SECURITY")

    # ------------------------------------------------------------ community_posts
    op.add_column(
        "community_posts",
        sa.Column("category", sa.String(length=20), server_default="ARTWORK_SHARE", nullable=False),
    )
    op.add_column("community_posts", sa.Column("photo_id", sa.Uuid(), nullable=True))
    op.add_column(
        "community_posts", sa.Column("author_display", sa.String(length=20), nullable=True)
    )
    # 기존 게시물 분류 이관 (question 기반)
    op.execute(
        "UPDATE community_posts SET category = 'FEEDBACK_REQUEST'"
        " WHERE question IS NOT NULL AND length(btrim(question)) > 0"
    )
    op.create_check_constraint("category", "community_posts", f"category IN {CATEGORIES}")
    op.create_check_constraint(
        "author_display", "community_posts", "author_display IN ('NAME', 'ANONYMOUS')"
    )
    op.alter_column("community_posts", "artwork_id", existing_type=sa.UUID(), nullable=True)
    op.create_check_constraint(
        "share_has_artwork",
        "community_posts",
        "category <> 'ARTWORK_SHARE' OR artwork_id IS NOT NULL",
    )
    op.create_check_constraint(
        "text_post_has_body",
        "community_posts",
        "artwork_id IS NOT NULL OR (body IS NOT NULL AND length(btrim(body)) > 0)",
    )
    op.create_check_constraint(
        "photo_needs_artwork", "community_posts", "photo_id IS NULL OR artwork_id IS NOT NULL"
    )
    op.create_foreign_key(
        op.f("fk_community_posts_photo_id_artwork_photos"),
        "community_posts",
        "artwork_photos",
        ["photo_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_community_posts_category_feed",
        "community_posts",
        ["category", "status", "created_at"],
        unique=False,
    )

    # ------------------------------------------------------------ shared_artwork_images
    op.add_column(
        "shared_artwork_images",
        sa.Column("kind", sa.String(length=20), server_default="PRIMARY", nullable=False),
    )
    op.create_check_constraint("kind", "shared_artwork_images", "kind IN ('PRIMARY', 'POST')")
    op.drop_index(
        "uq_shared_artwork_images_live",
        table_name="shared_artwork_images",
        postgresql_where=sa.text("status IN ('PENDING', 'ACTIVE')"),
    )
    op.create_index(
        "uq_shared_artwork_images_live",
        "shared_artwork_images",
        ["artwork_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'ACTIVE') AND kind = 'PRIMARY'"),
    )
    op.create_index(
        "uq_shared_artwork_images_live_post",
        "shared_artwork_images",
        ["artwork_id", "source_photo_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'ACTIVE') AND kind = 'POST'"),
    )
    _function(SHARED_IMAGE_FUNCTION_V10)


def downgrade() -> None:
    _function(SHARED_IMAGE_FUNCTION_V08)
    # 게시물용 이미지는 이전 구조(작품당 이미지 1개)에 담을 수 없음 → 삭제 처리 (파일 정리 대상)
    op.execute(
        "UPDATE community_posts SET image_id = NULL WHERE image_id IN"
        " (SELECT id FROM shared_artwork_images WHERE kind = 'POST')"
    )
    op.execute(
        "UPDATE shared_artwork_images SET status = 'DELETED', deleted_at = now(),"
        " storage_cleanup_pending = true WHERE kind = 'POST' AND status <> 'DELETED'"
    )
    op.drop_index(
        "uq_shared_artwork_images_live_post",
        table_name="shared_artwork_images",
        postgresql_where=sa.text("status IN ('PENDING', 'ACTIVE') AND kind = 'POST'"),
    )
    op.drop_index(
        "uq_shared_artwork_images_live",
        table_name="shared_artwork_images",
        postgresql_where=sa.text("status IN ('PENDING', 'ACTIVE') AND kind = 'PRIMARY'"),
    )
    op.create_index(
        "uq_shared_artwork_images_live",
        "shared_artwork_images",
        ["artwork_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'ACTIVE')"),
    )
    op.drop_column("shared_artwork_images", "kind")

    # 사진 없는 글은 artwork_id NOT NULL 구조에 담을 수 없음 → 삭제 (댓글·좋아요·신고 CASCADE)
    op.execute("DELETE FROM community_posts WHERE artwork_id IS NULL")
    op.drop_index("ix_community_posts_category_feed", table_name="community_posts")
    op.drop_constraint(
        op.f("fk_community_posts_photo_id_artwork_photos"), "community_posts", type_="foreignkey"
    )
    for name in ("photo_needs_artwork", "text_post_has_body", "share_has_artwork"):
        op.drop_constraint(op.f(f"ck_community_posts_{name}"), "community_posts", type_="check")
    op.alter_column("community_posts", "artwork_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("community_posts", "author_display")
    op.drop_column("community_posts", "photo_id")
    op.drop_column("community_posts", "category")
    op.drop_table("artwork_exam_stages")
