import pytest
from pydantic import ValidationError

from app.core.config import ConfigurationError, load_settings
from tests.conftest import make_settings


def test_defaults_for_development() -> None:
    settings = make_settings(app_env="development")

    assert settings.app_name == "ART MATE API"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.api_docs_enabled is True
    assert settings.database_configured is False
    assert settings.effective_log_format == "text"


def test_cors_origins_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173/ ,")

    settings = load_settings()

    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_empty_database_url_env_means_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")

    assert load_settings().database_configured is False


@pytest.mark.parametrize(
    "raw",
    [
        "postgresql://u:p@db.example.supabase.co:5432/postgres",
        "postgres://u:p@db.example.supabase.co:5432/postgres",
        "postgresql+asyncpg://u:p@db.example.supabase.co:5432/postgres",
    ],
)
def test_database_url_normalized_to_asyncpg(raw: str) -> None:
    settings = make_settings(database_url=raw)

    assert settings.database_url is not None
    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://u:p@")
    # SecretStr: repr/str 에 비밀번호가 노출되지 않는다
    assert "u:p@" not in repr(settings)


def test_database_url_sslmode_converted_for_asyncpg() -> None:
    settings = make_settings(database_url="postgresql://u:p@h:5432/postgres?sslmode=require")

    assert settings.database_url is not None
    url = settings.database_url.get_secret_value()
    assert "ssl=require" in url
    assert "sslmode" not in url


def test_transaction_pooler_disables_prepared_statements() -> None:
    pooler = make_settings(database_url="postgresql://u:p@pooler.supabase.com:6543/postgres")
    session = make_settings(database_url="postgresql://u:p@pooler.supabase.com:5432/postgres")
    forced = make_settings(
        database_url="postgresql://u:p@pooler.supabase.com:5432/postgres",
        db_disable_prepared_statements=True,
    )

    assert pooler.disable_prepared_statements is True
    assert session.disable_prepared_statements is False
    assert forced.disable_prepared_statements is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"app_env": "local"},
        {"log_level": "VERBOSE"},
        {"database_url": "mysql://u:p@localhost/db"},
        {"cors_origins": ["localhost:5173"]},
        {"api_v1_prefix": "api/v1"},
        {"db_pool_size": 0},
    ],
)
def test_invalid_values_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        make_settings(**overrides)


def test_production_rejects_debug() -> None:
    with pytest.raises(ValidationError, match="DEBUG=false"):
        make_settings(app_env="production", debug=True, database_url="postgresql://u:p@h/db")


def test_production_rejects_cors_wildcard() -> None:
    with pytest.raises(ValidationError, match="CORS_ORIGINS"):
        make_settings(
            app_env="production", cors_origins=["*"], database_url="postgresql://u:p@h/db"
        )


def test_production_requires_database_url() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        make_settings(app_env="production")


def test_production_hides_docs_by_default_and_uses_json_logs() -> None:
    settings = make_settings(app_env="production", database_url="postgresql://u:p@h/db")

    assert settings.api_docs_enabled is False
    assert settings.effective_log_format == "json"
    assert make_settings(
        app_env="production", database_url="postgresql://u:p@h/db", docs_enabled=True
    ).api_docs_enabled


def test_load_settings_error_is_readable_and_hides_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("DATABASE_URL", "mysql://admin:top-secret@host/db")

    with pytest.raises(ConfigurationError) as exc_info:
        load_settings()

    message = str(exc_info.value)
    assert "DATABASE_URL" in message
    assert "top-secret" not in message
    assert exc_info.value.__cause__ is None
