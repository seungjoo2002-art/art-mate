"""Gemini API 연동 (첨삭 요약·분류). REST `models/{model}:generateContent` + 구조화 JSON 출력.

- SDK 대신 httpx로 직접 호출한다 (의존성 최소화, MockTransport로 테스트).
- 응답 본문·요청 본문(전사문)은 로그에 남기지 않는다. 오류는 코드와 HTTP 상태만 기록한다.
- API 키는 `x-goog-api-key` 헤더로만 보낸다 (URL 쿼리 금지 → 접근 로그 노출 방지).
- 무료 등급은 입력이 모델 개선에 쓰일 수 있다 → 개인정보가 포함되므로 유료 등급 키만 사용한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class LlmError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool, called: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        # 실제로 외부 API까지 요청이 나갔는지 (호출 횟수 기록용)
        self.called = called
        self.input_tokens = 0
        self.output_tokens = 0


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None
    model_name: str


class SummaryLlm(Protocol):
    model_name: str

    async def generate(
        self, *, system: str, prompt: str, schema: dict[str, Any]
    ) -> LlmResponse: ...


class GeminiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,  # 테스트용 MockTransport
    ) -> None:
        assert settings.gemini_api_key is not None
        self.model_name = settings.gemini_model
        self._key = settings.gemini_api_key.get_secret_value()
        base = str(settings.gemini_api_base).rstrip("/")
        self._url = f"{base}/models/{settings.gemini_model}:generateContent"
        self._timeout = settings.gemini_timeout_seconds
        self._max_output_tokens = settings.gemini_max_output_tokens
        self._transport = transport

    async def generate(self, *, system: str, prompt: str, schema: dict[str, Any]) -> LlmResponse:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
                "maxOutputTokens": self._max_output_tokens,
                "temperature": 0.2,
            },
        }
        headers = {"x-goog-api-key": self._key, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException:
            raise LlmError("LLM_TIMEOUT", "Gemini request timed out", retryable=True) from None
        except httpx.HTTPError as exc:
            logger.warning("gemini request failed", extra={"error_type": type(exc).__name__})
            raise LlmError(
                "LLM_UNAVAILABLE", "Gemini request failed", retryable=True, called=False
            ) from None

        status = response.status_code
        if status >= 400:
            logger.warning("gemini error response", extra={"status": status})
            if status == 429:
                raise LlmError("LLM_RATE_LIMITED", "Gemini rate limit", retryable=True)
            if status >= 500:
                raise LlmError("LLM_UNAVAILABLE", f"Gemini responded {status}", retryable=True)
            if status in (401, 403):
                raise LlmError("LLM_AUTH_FAILED", "Gemini API key rejected", retryable=False)
            raise LlmError("LLM_BAD_REQUEST", f"Gemini responded {status}", retryable=False)

        try:
            data = response.json()
        except ValueError:
            raise LlmError(
                "LLM_INVALID_RESPONSE", "Gemini returned non-JSON", retryable=True
            ) from None
        usage = data.get("usageMetadata") or {}
        input_tokens = int(usage.get("promptTokenCount") or 0)
        # 출력 토큰 = 응답 + 사고(thinking) 토큰 (둘 다 출력 단가로 과금)
        output_tokens = int(usage.get("candidatesTokenCount") or 0) + int(
            usage.get("thoughtsTokenCount") or 0
        )

        def fail(code: str, message: str, *, retryable: bool) -> LlmError:
            error = LlmError(code, message, retryable=retryable)
            error.input_tokens, error.output_tokens = input_tokens, output_tokens
            return error

        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise fail("LLM_BLOCKED", f"Prompt blocked ({block})", retryable=False)
        candidates = data.get("candidates") or []
        if not candidates:
            raise fail("LLM_EMPTY_RESPONSE", "Gemini returned no candidates", retryable=True)
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish == "MAX_TOKENS":
            raise fail("LLM_OUTPUT_TRUNCATED", "Output hit the token limit", retryable=False)
        if finish not in (None, "STOP"):
            raise fail("LLM_BLOCKED", f"Generation stopped ({finish})", retryable=False)
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise fail("LLM_EMPTY_RESPONSE", "Gemini returned empty text", retryable=True)
        return LlmResponse(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish,
            model_name=self.model_name,
        )


def build_llm(settings: Settings) -> SummaryLlm | None:
    if not (settings.ai_summary_active and settings.gemini_configured):
        return None
    return GeminiClient(settings)
