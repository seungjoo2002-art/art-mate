"""OpenAI Responses API 클라이언트 (모의 HTTP — 실제 API 호출 없음)."""

import json

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.integrations.ai.gemini import GeminiClient, LlmError
from app.integrations.ai.llm import build_llm
from app.integrations.ai.openai_llm import OpenAiClient, to_strict_schema
from app.services.ai_summary import RESPONSE_SCHEMA, AiSummaryOutput
from app.services.growth_ai import NARRATIVE_SCHEMA, RECOMMEND_SCHEMA
from tests.conftest import make_settings
from tests.fake_ai import ai_json

KEY = "sk-test-not-real"


def _settings(**overrides):  # type: ignore[no-untyped-def]
    values = {
        "ai_summary_enabled": True,
        "ai_provider": "openai",
        "openai_api_key": SecretStr(KEY),
    }
    return make_settings(**(values | overrides))


def _client(handler) -> OpenAiClient:  # type: ignore[no-untyped-def]
    return OpenAiClient(_settings(), transport=httpx.MockTransport(handler))


def _completed(text: str, **extra) -> dict:  # type: ignore[no-untyped-def]
    return {
        "id": "resp_1",
        "object": "response",
        "status": "completed",
        "model": "gpt-6.1-terra",
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": []},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            },
        ],
        "usage": {
            "input_tokens": 1500,
            "output_tokens": 700,
            "output_tokens_details": {"reasoning_tokens": 200},
        },
    } | extra


def test_strict_schema_adds_additional_properties_and_keeps_original() -> None:
    strict = to_strict_schema(RESPONSE_SCHEMA)
    assert strict["additionalProperties"] is False
    item = strict["properties"]["strengths"]["items"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])
    assert item["properties"]["category"]["type"] == ["string", "null"]
    assert "additionalProperties" not in RESPONSE_SCHEMA  # 원본 그대로 (Gemini 경로 영향 없음)
    for schema in (NARRATIVE_SCHEMA, RECOMMEND_SCHEMA):
        to_strict_schema(schema)  # 성장 분석 스키마도 그대로 쓸 수 있음
    with pytest.raises(ValueError):
        to_strict_schema({"type": "object", "properties": {"a": {"type": "string"}}})


async def test_request_shape_and_success_parsing() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_completed(ai_json()))

    result = await _client(handler).generate(
        system="규칙", prompt="[0] 00:00 구도는 좋아", schema=RESPONSE_SCHEMA
    )
    request = seen[0]
    assert str(request.url) == "https://api.openai.com/v1/responses"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "gpt-6.1-terra"
    assert body["instructions"] == "규칙" and body["input"].startswith("[0]")
    assert body["store"] is False
    assert body["reasoning"] == {"effort": "low"}
    fmt = body["text"]["format"]
    assert (fmt["type"], fmt["strict"]) == ("json_schema", True)
    assert fmt["schema"]["additionalProperties"] is False
    # 결과는 기존 요약 검증(Pydantic)을 그대로 통과
    AiSummaryOutput.model_validate_json(result.text)
    assert (result.input_tokens, result.output_tokens, result.model_name) == (
        1500,
        700,
        "gpt-6.1-terra",
    )


@pytest.mark.parametrize(
    ("status", "body", "code", "retryable"),
    [
        (429, {"error": {"message": "rate"}}, "LLM_RATE_LIMITED", True),
        (500, {}, "LLM_UNAVAILABLE", True),
        (401, {}, "LLM_AUTH_FAILED", False),
        (400, {}, "LLM_BAD_REQUEST", False),
    ],
)
async def test_http_errors_map_to_existing_codes(status, body, code, retryable) -> None:  # type: ignore[no-untyped-def]
    client = _client(lambda request: httpx.Response(status, json=body))
    with pytest.raises(LlmError) as info:
        await client.generate(system="s", prompt="p", schema=RESPONSE_SCHEMA)
    assert (info.value.code, info.value.retryable) == (code, retryable)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (
            _completed("", status="incomplete", incomplete_details={"reason": "max_output_tokens"}),
            "LLM_OUTPUT_TRUNCATED",
        ),
        (
            _completed("", status="incomplete", incomplete_details={"reason": "content_filter"}),
            "LLM_BLOCKED",
        ),
        (
            {
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
            "LLM_BLOCKED",
        ),
        (_completed("   "), "LLM_EMPTY_RESPONSE"),
    ],
)
async def test_response_states(payload, code) -> None:  # type: ignore[no-untyped-def]
    client = _client(lambda request: httpx.Response(200, json=payload))
    with pytest.raises(LlmError) as info:
        await client.generate(system="s", prompt="p", schema=RESPONSE_SCHEMA)
    assert info.value.code == code


async def test_non_json_and_network_errors() -> None:
    client = _client(lambda request: httpx.Response(200, text="<html>"))
    with pytest.raises(LlmError) as info:
        await client.generate(system="s", prompt="p", schema=RESPONSE_SCHEMA)
    assert info.value.code == "LLM_INVALID_RESPONSE"

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(LlmError) as info:
        await _client(boom).generate(system="s", prompt="p", schema=RESPONSE_SCHEMA)
    assert (info.value.code, info.value.called) == ("LLM_UNAVAILABLE", False)


def test_provider_selection_and_verified_models_only() -> None:
    assert isinstance(build_llm(_settings()), OpenAiClient)
    assert build_llm(_settings(openai_api_key=None)) is None  # 키 없음
    assert build_llm(_settings(ai_summary_enabled=False)) is None
    gemini = _settings(ai_provider="gemini", gemini_api_key=SecretStr("g"))
    assert isinstance(build_llm(gemini), GeminiClient)
    assert build_llm(_settings(openai_model="gpt-6-luna")).model_name == "gpt-6-luna"
    with pytest.raises(ValidationError):
        make_settings(openai_model="gpt-unknown")  # 공식 확인 안 된 모델명 거부


# 공식 Structured Outputs "Supported schemas" 키워드·한도 (2026-11 확인)
SUPPORTED_KEYWORDS = {
    "type", "properties", "required", "additionalProperties", "items", "enum", "anyOf",
    "description", "minItems", "maxItems", "pattern", "format", "multipleOf", "maximum",
    "exclusiveMaximum", "minimum", "exclusiveMinimum", "$ref", "$defs", "const",
}  # fmt: skip


def _walk(node, stats, depth=0):  # type: ignore[no-untyped-def]
    if not isinstance(node, dict):
        return
    stats["keywords"] |= set(node) - ({"properties"} if "properties" in node else set())
    stats["depth"] = max(stats["depth"], depth)
    stats["enum"] += len(node.get("enum", []))
    if "properties" in node:
        assert node["additionalProperties"] is False
        assert set(node["required"]) == set(node["properties"])
        stats["props"] += len(node["properties"])
        for child in node["properties"].values():
            _walk(child, stats, depth + 1)
    if "items" in node:
        _walk(node["items"], stats, depth + 1)


@pytest.mark.parametrize("schema", [RESPONSE_SCHEMA, NARRATIVE_SCHEMA, RECOMMEND_SCHEMA])
def test_strict_schemas_use_only_supported_keywords(schema) -> None:  # type: ignore[no-untyped-def]
    stats = {"keywords": set(), "depth": 0, "enum": 0, "props": 0}
    strict = to_strict_schema(schema)
    assert strict["type"] == "object"  # 최상위는 object여야 함
    _walk(strict, stats)
    assert stats["keywords"] <= SUPPORTED_KEYWORDS
    assert stats["depth"] <= 10 and stats["props"] <= 5000 and stats["enum"] <= 1000
