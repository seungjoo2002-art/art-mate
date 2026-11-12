"""OpenAI Responses API 연동 (v0.9.6, 첨삭 요약·성장 분석). Gemini 클라이언트와 같은 `SummaryLlm`.

- `POST {base}/responses` + Structured Outputs(`text.format` json_schema, strict) → 기존 요약 JSON
  스키마를 그대로 쓴다 (strict 요구사항에 맞게 `additionalProperties: false`만 더함).
- `store: false`: 응답을 OpenAI에 저장해 두지 않는다 (남용 감시 로그는 OpenAI 정책상 최대 30일).
- SDK 대신 httpx (의존성 최소화, MockTransport로 테스트). API 키는 Authorization 헤더로만.
- 요청·응답 본문(전사문·요약)은 로그에 남기지 않는다. 오류는 코드·HTTP 상태만.
- 오류 코드는 Gemini와 같다 → 작업 재시도·화면 문구 변경 없음.
  429 LLM_RATE_LIMITED(재시도) / 5xx·타임아웃 재시도 / 401·403 LLM_AUTH_FAILED / 그 밖 4xx
  LLM_BAD_REQUEST / max_output_tokens 도달 LLM_OUTPUT_TRUNCATED / 거절·콘텐츠 필터 LLM_BLOCKED
- 공식 문서 확인 (2026-11): gpt-6.1-terra·gpt-6-luna 모두 Responses API·Structured Outputs 지원,
  응답의 `output_text`는 SDK 전용 편의 속성이라 `output[].content[]`에서 직접 읽는다.
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.integrations.ai.gemini import LlmError, LlmResponse

logger = logging.getLogger(__name__)

SCHEMA_NAME = "artmate_feedback"


def to_strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """기존 JSON 스키마 → OpenAI strict 모드 스키마 (원본은 바꾸지 않음).

    strict 요구사항: 모든 object에 `additionalProperties: false`, 모든 속성이 `required`.
    기존 스키마는 이미 모든 속성이 required이고 nullable은 `["string","null"]` 형식이다.
    빠진 required가 있으면 오류로 알린다 (조용히 의미를 바꾸지 않기 위해).
    """
    result = copy.deepcopy(schema)

    def visit(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                props = node.get("properties", {})
                missing = set(props) - set(node.get("required", []))
                if missing:
                    raise ValueError(f"strict schema needs all properties required at {path}")
                node["additionalProperties"] = False
            for key, value in node.items():
                visit(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                visit(value, f"{path}[{i}]")

    visit(result, "$")
    return result


class OpenAiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,  # 테스트용 MockTransport
    ) -> None:
        assert settings.openai_api_key is not None
        self.model_name = settings.openai_model
        self._key = settings.openai_api_key.get_secret_value()
        self._url = f"{str(settings.openai_api_base).rstrip('/')}/responses"
        self._timeout = settings.openai_timeout_seconds
        self._max_output_tokens = settings.openai_max_output_tokens
        self._effort = settings.openai_reasoning_effort
        self._transport = transport

    def _body(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "instructions": system,
            "input": prompt,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": SCHEMA_NAME,
                    "schema": to_strict_schema(schema),
                    "strict": True,
                }
            },
            "reasoning": {"effort": self._effort},
            "max_output_tokens": self._max_output_tokens,
            "store": False,
        }

    async def generate(self, *, system: str, prompt: str, schema: dict[str, Any]) -> LlmResponse:
        body = self._body(system, prompt, schema)
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException:
            raise LlmError("LLM_TIMEOUT", "OpenAI request timed out", retryable=True) from None
        except httpx.HTTPError as exc:
            logger.warning("openai request failed", extra={"error_type": type(exc).__name__})
            raise LlmError(
                "LLM_UNAVAILABLE", "OpenAI request failed", retryable=True, called=False
            ) from None

        status = response.status_code
        if status >= 400:
            logger.warning("openai error response", extra={"status": status})
            if status == 429:
                raise LlmError("LLM_RATE_LIMITED", "OpenAI rate limit", retryable=True)
            if status >= 500:
                raise LlmError("LLM_UNAVAILABLE", f"OpenAI responded {status}", retryable=True)
            if status in (401, 403):
                raise LlmError("LLM_AUTH_FAILED", "OpenAI API key rejected", retryable=False)
            raise LlmError("LLM_BAD_REQUEST", f"OpenAI responded {status}", retryable=False)

        try:
            data = response.json()
        except ValueError:
            raise LlmError(
                "LLM_INVALID_RESPONSE", "OpenAI returned non-JSON", retryable=True
            ) from None
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        # output_tokens에 추론 토큰이 포함됨 (출력 단가로 과금)
        output_tokens = int(usage.get("output_tokens") or 0)

        def fail(code: str, message: str, *, retryable: bool) -> LlmError:
            error = LlmError(code, message, retryable=retryable)
            error.input_tokens, error.output_tokens = input_tokens, output_tokens
            return error

        state = data.get("status")
        if state == "incomplete":
            reason = (data.get("incomplete_details") or {}).get("reason")
            if reason == "max_output_tokens":
                raise fail("LLM_OUTPUT_TRUNCATED", "Output hit the token limit", retryable=False)
            raise fail("LLM_BLOCKED", f"Generation stopped ({reason})", retryable=False)
        if state == "failed":
            raise fail("LLM_UNAVAILABLE", "OpenAI response failed", retryable=True)
        if state not in (None, "completed"):
            raise fail("LLM_EMPTY_RESPONSE", f"OpenAI response {state}", retryable=True)

        texts: list[str] = []
        for item in data.get("output") or []:
            if item.get("type") != "message":
                continue  # reasoning 등
            for part in item.get("content") or []:
                if part.get("type") == "refusal":
                    raise fail("LLM_BLOCKED", "Model refused", retryable=False)
                if part.get("type") == "output_text":
                    texts.append(part.get("text", ""))
        text = "".join(texts)
        if not text.strip():
            raise fail("LLM_EMPTY_RESPONSE", "OpenAI returned empty text", retryable=True)
        return LlmResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason="STOP",
            model_name=self.model_name,
        )
