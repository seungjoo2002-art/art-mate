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
    # 백엔드는 사용하지 않는다 (프론트엔드 SDK용 공개 키). service_role 키는 두지 않는다.
    supabase_anon_key: SecretStr | None = None
    auth_jwt_audience: str = "authenticated"
    auth_jwt_leeway_seconds: int = Field(default=10, ge=0, le=60)
    auth_jwks_cache_seconds: int = Field(default=600, ge=60, le=86400)

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
