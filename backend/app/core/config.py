"""애플리케이션 설정.

모든 환경변수는 이 모듈의 `Settings` 하나로 읽는다. 다른 모듈은 `os.environ`을 직접 읽지 말고
`get_settings()`(또는 FastAPI 의존성으로 주입된 Settings)를 사용한다.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

Environment = Literal["development", "test", "staging", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LogFormat = Literal["json", "text"]

# 운영 성격의 환경: DEBUG 금지, CORS 와일드카드 금지, API 문서 기본 비공개
DEPLOYED_ENVIRONMENTS: frozenset[str] = frozenset({"staging", "production"})

# 작품 사진으로 허용할 수 있는 이미지 형식 (실제 바이트 검증은 app/services/images.py)
SUPPORTED_IMAGE_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/png", "image/webp"})

# 피드백 녹음으로 허용할 수 있는 오디오 형식 (실제 바이트 검증은 app/services/audio.py)
SUPPORTED_AUDIO_TYPES: frozenset[str] = frozenset(
    {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav"}
)

# Supabase Supavisor transaction pooler 기본 포트 (prepared statement 미지원)
SUPABASE_TRANSACTION_POOLER_PORT = 6543


class ConfigurationError(RuntimeError):
    """환경변수가 없거나 잘못되었을 때 발생한다. 메시지에 비밀값은 포함하지 않는다."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # `DATABASE_URL=` 처럼 빈 값은 "미설정"(기본값)으로 취급한다.
        env_ignore_empty=True,
    )

    # --- Application -------------------------------------------------------
    app_name: str = "ART MATE API"
    app_version: str = "0.1.0"
    app_env: Environment = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    # None이면 환경에 따라 자동 결정 (staging/production에서는 비공개)
    docs_enabled: bool | None = None

    # --- Database ----------------------------------------------------------
    database_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_pool_timeout: float = Field(default=10.0, gt=0)
    db_pool_recycle: int = Field(default=1800, ge=-1)
    db_connect_timeout: float = Field(default=5.0, gt=0)
    db_health_timeout: float = Field(default=3.0, gt=0)
    # None이면 포트 6543(transaction pooler)일 때 자동으로 prepared statement를 끈다.
    db_disable_prepared_statements: bool | None = None

    # --- Supabase Auth ------------------------------------------------------
    # 프로젝트 URL (https://<ref>.supabase.co). JWT 발급자(iss)와 JWKS 주소를 여기서 만든다.
    # 비어 있으면 보호 API는 모두 401(AUTH_NOT_CONFIGURED)로 거부된다 (fail-closed).
    supabase_url: AnyHttpUrl | None = None
    # 공개 키. v0.4부터 Storage API 호출의 apikey 헤더로 사용한다 (권한은 사용자 토큰으로 판단).
    # service_role 키는 두지 않는다.
    supabase_anon_key: SecretStr | None = None
    auth_jwt_audience: str = "authenticated"
    auth_jwt_leeway_seconds: int = Field(default=10, ge=0, le=60)
    auth_jwks_cache_seconds: int = Field(default=600, ge=60, le=86400)

    # --- Supabase Storage (v0.4 작품 사진) -----------------------------------
    # 비공개 버킷 이름. backend/supabase/storage-setup.sql 과 같아야 한다.
    storage_bucket: str = Field(default="artworks", pattern=r"^[a-z0-9][a-z0-9_-]{1,62}$")
    storage_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    # 사진 조회용 Signed URL 만료 (초)
    storage_signed_url_seconds: int = Field(default=300, ge=30, le=3600)
    # 업로드 요청 후 완료 처리까지 허용 시간 (초). Supabase signed upload URL 유효시간(2시간) 이하
    artwork_upload_ttl_seconds: int = Field(default=3600, ge=60, le=7200)
    artwork_max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    # 허용 MIME 타입 (쉼표 구분). 지원: image/jpeg, image/png, image/webp
    artwork_allowed_content_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["image/jpeg", "image/png", "image/webp"]
    )
    artwork_max_photos_per_stage: int = Field(default=10, ge=1, le=50)
    # 디컴프레션 폭탄 방지: 이미지 최대 픽셀 수
    artwork_max_image_pixels: int = Field(default=50_000_000, ge=1_000_000, le=200_000_000)

    # --- 피드백 녹음 (v0.5) -------------------------------------------------
    # 비공개 오디오 버킷. backend/supabase/storage-setup.sql 과 같아야 한다.
    recording_bucket: str = Field(default="feedback-audio", pattern=r"^[a-z0-9][a-z0-9_-]{1,62}$")
    recording_upload_ttl_seconds: int = Field(default=3600, ge=60, le=7200)
    recording_max_upload_bytes: int = Field(default=25 * 1024 * 1024, ge=1024, le=100 * 1024 * 1024)
    recording_max_duration_seconds: int = Field(default=1200, ge=10, le=7200)
    # 허용 MIME 타입 (쉼표 구분). 지원: audio/webm, audio/ogg, audio/mp4, audio/mpeg, audio/wav
    recording_allowed_content_types: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: sorted(SUPPORTED_AUDIO_TYPES)
    )
    recording_max_per_artwork: int = Field(default=20, ge=1, le=100)
    # v0.9 음성 원본 보관 기간 (일). 지나면 음성 파일만 삭제하고 전사·첨삭은 남긴다. 0 = 무기한
    recording_audio_retention_days: int = Field(default=180, ge=0, le=3650)
    # 현재 녹음 동의서 버전. 바꾸면 학생은 새 버전에 다시 동의해야 녹음할 수 있다.
    recording_consent_version: str = Field(
        default="2026-11-v1", min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._-]+$"
    )

    # --- AI 첨삭 처리 (v0.6) ------------------------------------------------
    # 기본은 모두 꺼짐: 켜지 않으면 API가 전사·요약 요청을 503으로 거부한다 (비용·개인정보 보호).
    # 실제 처리는 별도 Worker 프로세스(`python -m app.worker`)가 DB 작업 큐에서 가져가 실행한다.
    stt_enabled: bool = False
    # faster-whisper 모델 (tiny/base/small/medium/large-v3 또는 로컬 경로). CPU 기본 small + int8
    stt_model: str = Field(default="small", min_length=1, max_length=200)
    stt_device: Literal["cpu", "cuda", "auto"] = "cpu"
    stt_compute_type: str = Field(default="int8", pattern=r"^[a-z0-9_]+$")
    # 0이면 CTranslate2 기본값 (가용 코어 수)
    stt_cpu_threads: int = Field(default=0, ge=0, le=64)
    # 1 = greedy (CPU 비용 최소). 정확도가 부족하면 3~5로 올린다
    stt_beam_size: int = Field(default=1, ge=1, le=10)
    stt_language: str = Field(default="ko", pattern=r"^[a-z]{2}$")
    # 모델 다운로드 위치 (Worker 디스크·볼륨). 비우면 HuggingFace 기본 캐시
    stt_model_dir: str | None = None
    # 녹음 길이 상한(RECORDING_MAX_DURATION_SECONDS)과 별도로 전사 처리 상한
    stt_max_audio_seconds: int = Field(default=1200, ge=10, le=7200)
    # 전사 1건 처리 제한 시간 (구간 단위로 확인해 넘으면 중단 → 재시도)
    stt_timeout_seconds: int = Field(default=1800, ge=30, le=10800)
    # Worker가 음성을 내려받을 Signed URL 유효시간.
    # 요청한 사용자 토큰으로 발급한다 (service_role 미사용)
    # 24시간: GitHub Actions 예약 실행은 실제로 6~7시간씩 밀린 기록이 있어(2026-11-11)
    # 6시간이면 Worker가 받기 전에 만료(SOURCE_URL_EXPIRED)됐다
    stt_source_url_seconds: int = Field(default=86400, ge=600, le=86400)
    # 기기 전사 중 만들어 두는 "백업" 서버 전사 작업의 최대 지연 (요청값 상한)
    stt_max_defer_seconds: int = Field(default=3600, ge=0, le=21600)

    # --- Worker 즉시 실행 (GitHub Actions workflow_dispatch) ------------------
    # 작업을 큐에 넣으면 stt-worker 워크플로를 바로 실행 요청한다 (예약 실행 15분 주기는 실제로
    # 수 시간씩 밀림). 토큰이 없으면 아무것도 하지 않고 예약 실행만 쓴다.
    # 토큰: 이 저장소 하나에 Actions: Read and write 권한만 준 fine-grained PAT
    worker_dispatch_token: SecretStr | None = None
    worker_dispatch_repo: str = Field(
        default="seungjoo2002-art/art-mate", pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
    )
    worker_dispatch_workflow: str = Field(default="stt-worker.yml", pattern=r"^[A-Za-z0-9_.-]+$")
    worker_dispatch_ref: str = Field(default="main", min_length=1, max_length=100)
    # 같은 API 프로세스에서 이 간격 안의 요청은 한 번으로 합친다 (실행 중인 Worker가 함께 처리)
    worker_dispatch_min_interval_seconds: int = Field(default=30, ge=0, le=3600)

    ai_summary_enabled: bool = False
    # 운영자 확인 (배포 환경 필수, v0.9.5):
    #  - Gemini 유료 등급 (입력이 모델 개선에 쓰이지 않음)
    #  - 제공자 약관(연령 조항 포함)과 학생·보호자 동의 범위 검토 완료
    # false면 배포 환경에서는 AI_SUMMARY_ENABLED 등이 켜져 있어도 외부 AI로 보내지 않는다
    ai_provider_terms_confirmed: bool = False
    # 요약을 만드는 외부 AI (v0.9.6). openai(기본) | gemini. 동의는 제공자별로 받는다
    ai_provider: Literal["openai", "gemini"] = "openai"
    # 운영자 승인: OpenAI 데이터 무보관(ZDR)이 이 조직에 승인·적용됨. false면 만 13세 미만 학생의
    # 전사문은 보호자 동의가 있어도 보내지 않는다 (OpenAI Under-18 guidance)
    ai_zdr_approved: bool = False
    # 운영자 승인 (v0.9.6 배포 준비): 만 18세 미만 학생의 전사문 외부 전송 허용.
    # 보호자 확인 방식의 법률 검토·OpenAI 약관 원문 확인 전까지 false — 보호자가 확인해도 차단
    ai_minors_enabled: bool = False

    # --- OpenAI (Worker 전용, 키는 GitHub Actions Secret에만) -------------------
    openai_api_key: SecretStr | None = None
    # 공식 모델 페이지에서 확인한 ID만 (2026-11): gpt-6.1-terra(기본), gpt-6-luna(저비용)
    openai_model: Literal["gpt-6.1-terra", "gpt-6-luna"] = "gpt-6.1-terra"
    openai_api_base: AnyHttpUrl = AnyHttpUrl("https://api.openai.com/v1")
    openai_timeout_seconds: float = Field(default=90.0, gt=0, le=300)
    # 추론 토큰도 출력으로 과금 → 근거 있는 요약에는 낮게 (모델 기본값은 medium)
    openai_reasoning_effort: Literal["none", "low", "medium", "high"] = "low"
    # 추론 토큰 포함 출력 상한
    openai_max_output_tokens: int = Field(default=8192, ge=512, le=32768)

    # Gemini API 키 (Worker 전용).
    # 무료 등급은 입력이 모델 개선에 쓰일 수 있으므로 유료 등급 키만 사용
    gemini_api_key: SecretStr | None = None
    gemini_model: str = Field(default="gemini-3.1-flash-lite", pattern=r"^[a-z0-9.-]+$")
    gemini_api_base: AnyHttpUrl = AnyHttpUrl("https://generativelanguage.googleapis.com/v1beta")
    gemini_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    gemini_max_output_tokens: int = Field(default=4096, ge=256, le=32768)
    # 한 번에 보내는 전사문 최대 글자 수 (넘으면 요약 실패 처리)
    ai_max_transcript_chars: int = Field(default=30000, ge=1000, le=200000)
    # 학생 1명이 하루(Asia/Seoul)에 요청할 수 있는 AI 요약 수 (무료 한도·남용 방지). 0 = 제한 없음
    ai_summary_daily_limit: int = Field(default=20, ge=0, le=1000)
    # 외부 AI 전송 동의서 버전. 바꾸면 학생은 새 버전에 다시 동의해야 AI 요약을 요청할 수 있다
    # v2 (v0.9.6): 제공자 OpenAI, 연령 확인, 미성년자 보호자 동의
    ai_consent_version: str = Field(
        default="2026-12-ai-v2", min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._-]+$"
    )

    # --- 성장 코치 (v0.7) ----------------------------------------------------
    # 성장 리포트 설명문·AI 연습 과제 (Gemini). 통계·규칙 기반 추천은 이 설정과 무관하게 동작
    growth_ai_enabled: bool = False
    # 성장 분석 목적의 외부 AI 전송 동의서 버전 (첨삭 요약 동의와 별개)
    ai_growth_consent_version: str = Field(
        default="2026-12-growth-v2", min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._-]+$"
    )
    # 분석 대상(승인된 첨삭이 있는) 작품이 이보다 적으면 INSUFFICIENT_DATA
    growth_min_artworks: int = Field(default=3, ge=1, le=50)
    # '최근 N개 작품' 비교 구간 크기
    growth_recent_window: int = Field(default=5, ge=2, le=50)
    # 한 번에 만드는 추천 과제 수 (약점 카테고리당 1개)
    growth_max_recommendations: int = Field(default=3, ge=1, le=10)

    # --- 참고작·커뮤니티 (v0.8) ---------------------------------------------
    # 공유용 파생 이미지 비공개 버킷 (원본 버킷과 분리). storage-setup.sql 과 같아야 한다
    shared_bucket: str = Field(default="shared-artworks", pattern=r"^[a-z0-9][a-z0-9_-]{1,62}$")
    # 파생 이미지 긴 변 최대 픽셀 (원본 해상도·EXIF를 공유하지 않는다)
    shared_image_max_px: int = Field(default=1600, ge=320, le=4096)
    shared_image_quality: int = Field(default=82, ge=50, le=95)
    # 작품 공유 동의서 버전 (커뮤니티·참고작 공통)
    sharing_consent_version: str = Field(
        default="2026-11-share-v1", min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._-]+$"
    )
    reference_per_weakness: int = Field(default=3, ge=1, le=10)
    reference_max_results: int = Field(default=9, ge=1, le=30)
    # 남용 방지 (사용자별, DB 기준이라 서버 여러 대에서도 동일)
    community_posts_per_day: int = Field(default=10, ge=1, le=100)
    community_comments_per_10min: int = Field(default=20, ge=1, le=200)
    community_reports_per_day: int = Field(default=20, ge=1, le=200)
    # 서로 다른 사용자의 미처리 신고가 이 수에 도달하면 자동 숨김 (관리자 검토 대기)
    community_auto_hide_reports: int = Field(default=3, ge=2, le=100)

    # 작업 큐·Worker
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    # Worker가 작업을 잡고 있는 동안 주기적으로 연장. 만료되면 다른 Worker가 회수(서버 재시작 복구)
    job_lease_seconds: int = Field(default=300, ge=30, le=3600)
    job_retry_base_seconds: int = Field(default=30, ge=1, le=3600)
    worker_poll_seconds: float = Field(default=5.0, gt=0, le=300)
    # v0.9 Worker 정기 작업 간격 (음성 보관 기간 정리·미완료 과제 알림·목표 확인 알림)
    worker_maintenance_seconds: int = Field(default=3600, ge=60, le=86400)

    # --- HTTP --------------------------------------------------------------
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Logging -----------------------------------------------------------
    log_level: LogLevel = "INFO"
    # None이면 development/test는 text, 그 외에는 json
    log_format: LogFormat | None = None

    # ------------------------------------------------------------------ validators

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("api_v1_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/") or len(value) < 2:
            raise ValueError("'/'로 시작하고 '/'로 끝나지 않아야 합니다 (예: /api/v1)")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list | tuple):
            origins = [str(item).strip().rstrip("/") for item in value]
            origins = [origin for origin in origins if origin]
            for origin in origins:
                if origin != "*" and not origin.startswith(("http://", "https://")):
                    raise ValueError(
                        f"'{origin}'은(는) 올바른 Origin이 아닙니다. "
                        "http:// 또는 https:// 로 시작해야 합니다"
                    )
            return origins
        return value

    @field_validator("artwork_allowed_content_types", mode="before")
    @classmethod
    def _split_content_types(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list | tuple):
            types = [str(item).strip().lower() for item in value if str(item).strip()]
            unsupported = sorted(set(types) - SUPPORTED_IMAGE_TYPES)
            if unsupported:
                raise ValueError(
                    f"지원하지 않는 이미지 형식입니다: {', '.join(unsupported)} "
                    f"(지원: {', '.join(sorted(SUPPORTED_IMAGE_TYPES))})"
                )
            if not types:
                raise ValueError("허용 이미지 형식이 비어 있습니다")
            return types
        return value

    @field_validator("recording_allowed_content_types", mode="before")
    @classmethod
    def _split_audio_types(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.split(",")
        if isinstance(value, list | tuple):
            types = [str(item).strip().lower() for item in value if str(item).strip()]
            unsupported = sorted(set(types) - SUPPORTED_AUDIO_TYPES)
            if unsupported:
                raise ValueError(
                    f"지원하지 않는 오디오 형식입니다: {', '.join(unsupported)} "
                    f"(지원: {', '.join(sorted(SUPPORTED_AUDIO_TYPES))})"
                )
            if not types:
                raise ValueError("허용 오디오 형식이 비어 있습니다")
            return types
        return value

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: object) -> object:
        raw = value.get_secret_value() if isinstance(value, SecretStr) else value
        if raw is None or not isinstance(raw, str):
            return value
        raw = raw.strip()
        if not raw:
            return None
        try:
            url = make_url(raw)
        except ArgumentError:
            # 원본 값(비밀번호 포함 가능)은 메시지에 넣지 않는다.
            raise ValueError("DATABASE_URL 형식을 해석할 수 없습니다") from None

        if url.drivername in {"postgres", "postgresql", "postgresql+asyncpg"}:
            url = url.set(drivername="postgresql+asyncpg")
        else:
            raise ValueError(
                "PostgreSQL URL이어야 합니다 (postgresql:// 또는 postgresql+asyncpg://)"
            )

        # Supabase 대시보드의 `?sslmode=require`는 asyncpg에서 `ssl=require`로 받는다.
        if "sslmode" in url.query:
            query = dict(url.query)
            query.setdefault("ssl", query.pop("sslmode"))
            url = url.set(query=query)
        return SecretStr(url.render_as_string(hide_password=False))

    @model_validator(mode="after")
    def _validate_environment_rules(self) -> Settings:
        if self.app_env in DEPLOYED_ENVIRONMENTS:
            if self.debug:
                raise ValueError(f"APP_ENV={self.app_env}에서는 DEBUG=false 여야 합니다")
            if "*" in self.cors_origins:
                raise ValueError(
                    f"APP_ENV={self.app_env}에서는 CORS_ORIGINS에 '*'를 사용할 수 없습니다. "
                    "허용할 Origin을 명시하세요"
                )
        if self.app_env == "production" and self.database_url is None:
            raise ValueError("APP_ENV=production에서는 DATABASE_URL이 필요합니다")
        return self

    # ------------------------------------------------------------------ derived values

    @property
    def is_deployed(self) -> bool:
        return self.app_env in DEPLOYED_ENVIRONMENTS

    @property
    def api_docs_enabled(self) -> bool:
        if self.docs_enabled is not None:
            return self.docs_enabled
        return not self.is_deployed

    @property
    def effective_log_format(self) -> LogFormat:
        if self.log_format is not None:
            return self.log_format
        return "text" if self.app_env in {"development", "test"} else "json"

    @property
    def auth_configured(self) -> bool:
        return self.supabase_url is not None

    @property
    def supabase_base_url(self) -> str | None:
        return str(self.supabase_url).rstrip("/") if self.supabase_url else None

    @property
    def auth_jwt_issuer(self) -> str | None:
        base = self.supabase_base_url
        return f"{base}/auth/v1" if base else None

    @property
    def auth_jwks_url(self) -> str | None:
        base = self.supabase_base_url
        return f"{base}/auth/v1/.well-known/jwks.json" if base else None

    @property
    def storage_configured(self) -> bool:
        """Storage API 호출에는 프로젝트 URL과 공개 anon(publishable) 키가 필요하다."""
        return self.supabase_url is not None and self.supabase_anon_key is not None

    @property
    def storage_api_url(self) -> str | None:
        base = self.supabase_base_url
        return f"{base}/storage/v1" if base else None

    @property
    def ai_terms_blocked(self) -> bool:
        """배포 환경에서 운영자 확인(AI_PROVIDER_TERMS_CONFIRMED) 없이 외부 AI를 켜려 함."""
        return self.is_deployed and not self.ai_provider_terms_confirmed

    @property
    def ai_summary_active(self) -> bool:
        """AI 첨삭 요약을 실제로 쓸 수 있음 (플래그 + 배포 환경에서는 운영자 확인)."""
        return self.ai_summary_enabled and not self.ai_terms_blocked

    @property
    def growth_ai_active(self) -> bool:
        return self.growth_ai_enabled and not self.ai_terms_blocked

    @property
    def llm_configured(self) -> bool:
        """선택한 제공자의 API 키가 있음 (Worker)."""
        key = self.openai_api_key if self.ai_provider == "openai" else self.gemini_api_key
        return key is not None and bool(key.get_secret_value())

    @property
    def gemini_configured(self) -> bool:
        return self.gemini_api_key is not None and bool(self.gemini_api_key.get_secret_value())

    @property
    def database_configured(self) -> bool:
        return self.database_url is not None

    @property
    def disable_prepared_statements(self) -> bool:
        if self.db_disable_prepared_statements is not None:
            return self.db_disable_prepared_statements
        if self.database_url is None:
            return False
        port = make_url(self.database_url.get_secret_value()).port
        return port == SUPABASE_TRANSACTION_POOLER_PORT


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors(include_input=False, include_url=False):
        field = ".".join(str(part) for part in error["loc"]).upper() or "SETTINGS"
        message = error["msg"].removeprefix("Value error, ")
        lines.append(f"  - {field}: {message}")
    return (
        "환경변수 설정이 올바르지 않습니다:\n"
        + "\n".join(lines)
        + "\n.env.example을 참고해 backend/.env 또는 환경변수를 확인하세요."
    )


def load_settings(**overrides: object) -> Settings:
    """Settings를 생성하고, 실패 시 비밀값이 없는 읽기 쉬운 ConfigurationError를 던진다.

    `ENV_FILE` 환경변수로 읽을 .env 파일 경로를 바꿀 수 있다 (빈 값이면 .env 파일을 읽지 않음).
    """
    env_file = os.environ.get("ENV_FILE", ".env") or None
    try:
        return Settings(_env_file=env_file, **overrides)  # type: ignore[call-arg]
    except ValidationError as exc:
        # `from None`: pydantic 원본 예외에는 입력값(비밀번호 등)이 포함될 수 있다.
        raise ConfigurationError(_format_validation_error(exc)) from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
