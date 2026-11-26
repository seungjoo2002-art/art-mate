"""AI 시각적 첨삭: AI 수정본 (v1.3).

학생이 고른 작품 사진 1장 + 그 사진에 연결된 기존 AI 첨삭 정리의 개선사항(부족한 점·수정 방법)을
이미지 수정 AI로 보내 만든 **학습용 참고 이미지**다.

원칙
- 학생 작품 사진(artwork_photos)과 완전히 분리한다. 단계 사진 슬라이드·사진 수·대표 사진·
  아카이브 썸네일·성장 분석·참고작·커뮤니티 공유·학습 데이터셋은 모두 artwork_photos만 읽으므로
  이 표의 행은 구조적으로 섞이지 않는다.
- 원본 연결은 `photo_id`(생성 당시의 사진 행) + `source_sha256`(파일 내용)으로 고정한다. 사진을
  교체하면 새 사진 행이 생기므로 교체 전 수정본은 새 사진의 수정본으로 보이지 않는다.
- 생성 당시 개선사항은 `improvements`에 스냅샷으로 저장한다 (이후 피드백이 바뀌어도 그대로).
- 같은 원본·같은 개선사항·같은 생성 설정(request_hash)의 진행 중·성공 결과는 하나만 둔다 (부분
  유니크 인덱스) → 동시에 여러 번 눌러도, 다시 눌러도 이미지 수정 API를 다시 부르지 않는다.
- Worker에는 사용자 토큰이 없어 Storage에 쓸 수 없다. 결과 이미지는 `result_staging`(DB)에 잠시
  두고(STORING), 학생이 다음에 조회할 때 서버가 그 학생의 토큰으로 Storage에 올린 뒤 비운다.
- RLS 활성화(정책 없음): PostgREST 직접 접근 차단, 백엔드만 접근.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import AiRevisionStatus


class ArtworkAiRevision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """AI 수정본 1개 = 생성 요청 1건 (원본 사진 1장당 여러 버전)."""

    __tablename__ = "artwork_ai_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["artwork_id", "owner_id"], ["artworks.id", "artworks.owner_id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["stage_id", "artwork_id"], ["artwork_stages.id", "artwork_stages.artwork_id"]
        ),
        ForeignKeyConstraint(
            ["photo_id", "artwork_id"], ["artwork_photos.id", "artwork_photos.artwork_id"]
        ),
        UniqueConstraint("photo_id", "version"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(
            "status <> 'SUCCEEDED' OR (stored_at IS NOT NULL AND storage_path IS NOT NULL)",
            name="succeeded_is_stored",
        ),
        CheckConstraint(
            "status <> 'STORING' OR result_staging IS NOT NULL", name="storing_has_result"
        ),
        CheckConstraint(
            "api_call_count >= 0 AND input_tokens >= 0 AND output_tokens >= 0",
            name="usage_nonnegative",
        ),
        # 같은 요청의 진행 중·성공 결과는 1개 (중복 생성 방지·결과 재사용)
        Index(
            "uq_artwork_ai_revisions_request",
            "owner_id",
            "request_hash",
            unique=True,
            postgresql_where=text(
                "status IN ('QUEUED', 'RUNNING', 'STORING', 'SUCCEEDED') AND deleted_at IS NULL"
            ),
        ),
        Index("ix_artwork_ai_revisions_photo", "photo_id", "created_at"),
        Index("ix_artwork_ai_revisions_stage", "artwork_id", "stage_id", "created_at"),
        # 사용자별 일·월 한도 집계
        Index("ix_artwork_ai_revisions_owner_created", "owner_id", "created_at"),
        Index(
            "ix_artwork_ai_revisions_staged",
            "staged_at",
            postgresql_where=text("status = 'STORING'"),
        ),
        Index(
            "ix_artwork_ai_revisions_owner_cleanup",
            "owner_id",
            postgresql_where=text("storage_cleanup_pending"),
        ),
    )

    artwork_id: Mapped[uuid.UUID]
    owner_id: Mapped[uuid.UUID]
    stage_id: Mapped[uuid.UUID]
    # 생성 당시 원본 사진 행 (교체하면 새 행 → 이 연결은 바뀌지 않음)
    photo_id: Mapped[uuid.UUID]
    # 생성 당시 원본 파일 내용 해시 (Worker가 받은 파일과 대조)
    source_sha256: Mapped[str] = mapped_column(String(64))
    # 같은 원본 사진 안에서 1, 2, 3…
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[AiRevisionStatus] = mapped_column(
        enum_column(AiRevisionStatus, "status"), default=AiRevisionStatus.QUEUED
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_processing_jobs.id", ondelete="SET NULL")
    )

    # ---------------------------------------------------------------- 요청 (생성 당시 스냅샷, 불변)
    # [{"type": "RECORDING"|"NOTE", "id", "summary_id", "summary_version"}]
    source_feedback: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # 실제로 보낸 개선사항: [{"key", "category", "category_label", "kind", "text", "sources"}]
    improvements: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    # 선택 정보: {"candidate_keys": [...], "selected_keys": [...]}
    selection: Mapped[dict[str, Any]] = mapped_column(JSONB)
    provider: Mapped[str] = mapped_column(String(30))
    model_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    # {"quality", "size", "output_format", "reference_photo_id"}
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # sha256(원본 해시 + 개선사항 + 모델 + 설정 + 프롬프트 버전)
    request_hash: Mapped[str] = mapped_column(String(64))
    retry_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artwork_ai_revisions.id", ondelete="SET NULL")
    )

    # ---------------------------------------------------------------- 결과
    # AI 수정본 비공개 버킷 경로 "{owner}/{artwork}/{revision}.{ext}" (Worker가 정해 둠, 업로드 후
    # 확정)
    storage_path: Mapped[str | None] = mapped_column(String(512), unique=True)
    content_type: Mapped[str | None] = mapped_column(String(50))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    # Worker 결과 임시 저장 (Storage 업로드 후 NULL). 목록 조회 때 읽지 않도록 deferred
    result_staging: Mapped[bytes | None] = deferred(mapped_column(LargeBinary))
    storage_attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    storage_error_code: Mapped[str | None] = mapped_column(String(50))

    # ---------------------------------------------------------------- 시각 (소요 시간 측정)
    started_at: Mapped[datetime | None]  # Worker가 작업을 잡음 (대기 시간 = started - created)
    api_started_at: Mapped[datetime | None]  # 이미지 수정 API 요청 전송
    api_finished_at: Mapped[datetime | None]  # 응답 수신
    staged_at: Mapped[datetime | None]  # DB 임시 저장
    stored_at: Mapped[datetime | None]  # Storage 저장 완료
    storage_ms: Mapped[int | None] = mapped_column(Integer)  # Storage 업로드 자체 소요
    delivered_at: Mapped[datetime | None]  # 완성 이미지를 처음 학생 화면에 내려준 시각
    finished_at: Mapped[datetime | None]

    # ---------------------------------------------------------------- 사용량·비용 (모든 시도 누적)
    api_call_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    input_image_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 5), server_default=text("0"), default=Decimal("0")
    )

    # 안전한 오류 코드·짧은 문장만 (키·URL·이미지·개선사항 내용 금지)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(300))

    deleted_at: Mapped[datetime | None]
    storage_cleanup_pending: Mapped[bool] = mapped_column(
        Boolean, server_default=false(), default=False
    )
