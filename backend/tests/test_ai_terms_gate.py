"""배포 환경의 외부 AI(Gemini) 전송 차단: 운영자의 유료 등급·약관 확인 전에는 보내지 않는다."""

import httpx
import pytest
from pydantic import SecretStr

from app.integrations.ai.gemini import GeminiClient, build_llm
from app.main import create_app
from app.worker.__main__ import supported_job_types
from tests.conftest import make_settings

DB = "postgresql://u:p@127.0.0.1:1/none"


def _prod(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "app_env": "production",
        "database_url": DB,
        "ai_summary_enabled": True,
        "growth_ai_enabled": True,
        "gemini_api_key": SecretStr("test-key"),
    }
    return make_settings(**(values | overrides))


def test_production_blocks_external_ai_until_operator_confirms() -> None:
    blocked = _prod()
    assert (blocked.ai_summary_active, blocked.growth_ai_active) == (False, False)
    assert build_llm(blocked) is None  # Worker도 Gemini 클라이언트를 만들지 않음
    assert supported_job_types(blocked, has_stt=True, has_llm=False) == {"TRANSCRIBE"}

    confirmed = _prod(ai_provider_terms_confirmed=True)
    assert (confirmed.ai_summary_active, confirmed.growth_ai_active) == (True, True)
    assert isinstance(build_llm(confirmed), GeminiClient)


def test_local_and_test_environments_are_unaffected() -> None:
    settings = make_settings(ai_summary_enabled=True)
    assert settings.ai_summary_active is True
    assert make_settings(ai_summary_enabled=False).ai_summary_active is False


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({}, "TERMS_UNCONFIRMED"),
        ({"ai_provider_terms_confirmed": True}, "ENABLED"),
        ({"ai_summary_enabled": False}, "DISABLED"),
    ],
)
async def test_ai_features_reports_reason_without_secrets(overrides, status) -> None:  # type: ignore[no-untyped-def]
    app = create_app(_prod(**overrides))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        body = (await client.get("/api/v1/meta/ai-features")).json()
    assert body["ai_summary_status"] == status
    assert body["ai_summary"] is (status == "ENABLED")
    assert "test-key" not in str(body) and "GEMINI" not in str(body)
