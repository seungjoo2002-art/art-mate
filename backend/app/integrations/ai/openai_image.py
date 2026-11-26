"""OpenAI 이미지 수정 API 연동 (v1.3 AI 시각적 첨삭). `POST {base}/images/edits` (multipart).

공식 문서 확인 (2026-11-26, developers.openai.com)
- gpt-image-2.5-flare·gpt-image-2.5-sunburst: `/v1/images/edits` 지원, 입력 텍스트·이미지 / 출력
  이미지.
  quality low·medium·high·xhigh·max·auto, size 1024x1024·1536x1024·1024x1536·auto·사용자 지정
  (16의 배수), output_format png·jpeg·webp, 응답 `data[].b64_json` + `usage`.
- 가격(1M 토큰): 텍스트 입력 $5, 이미지 입력 $8, 이미지 출력 $30. 입력 이미지는 이미지 입력
  토큰으로 과금.
- 데이터: API 입력은 기본적으로 학습에 쓰지 않음, 남용 감시 로그 최대 30일. 위 두 모델은 ZDR '호환'
  목록에 있으나 ZDR은 조직별 사전 승인 후에만 적용된다 (AI_ZDR_APPROVED).
- 최종 사용자 식별: `safety_identifier`(사용자 ID 해시, 원문·이메일 아님)를 보낸다.

오류 처리 (자동 재시도는 '처리되지 않았음이 확실한' 일시적 오류만)
- 연결 실패·연결/풀 타임아웃·요청 전송 중단(서버가 요청 전체를 받지 못함) → IMAGE_UNAVAILABLE,
  재시도
- 응답 대기 시간 초과·응답 수신 중 끊김 → IMAGE_RESULT_UNKNOWN, **재시도 안 함** (이미
  처리·과금됐을 수 있음)
- 429 rate limit → 재시도 / 429 insufficient_quota → 재시도 안 함 / 500·502·503 → 재시도
- 504 → 처리 여부 불분명 → 재시도 안 함 / 401·403 인증 / 404 모델 접근 불가 / 400 콘텐츠 정책 →
  재시도 안 함
요청·응답 본문(이미지·프롬프트)과 키는 로그에 남기지 않는다. 오류는 HTTP 상태와 OpenAI 오류 코드만.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings
from app.integrations.ai.openai_llm import _error_fields

logger = logging.getLogger(__name__)

PROVIDER = "openai"


class ImageEditError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool, called: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        # 요청이 OpenAI까지 전달됐을 수 있는지 (호출 수·비용 기록용)
        self.called = called


@dataclass(frozen=True, slots=True)
class EditImage:
    data: bytes
    content_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class ImageEditResult:
    image: bytes
    output_format: str
    input_tokens: int
    input_image_tokens: int
    input_text_tokens: int
    output_tokens: int
    model_name: str


class ImageEditor(Protocol):
    model_name: str

    async def edit(
        self,
        *,
        images: list[EditImage],
        prompt: str,
        size: str,
        user_key: str,
    ) -> ImageEditResult: ...


def safety_identifier(user_id: str) -> str:
    """OpenAI 남용 감지용 식별자: 사용자 ID의 해시 (원문·이메일·이름을 보내지 않음)."""
    return hashlib.sha256(f"artmate:{user_id}".encode()).hexdigest()[:64]


_RETRYABLE_STATUS = {500, 502, 503}


class OpenAiImageEditor:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,  # 테스트용 MockTransport
    ) -> None:
        assert settings.openai_api_key is not None
        self.model_name = settings.image_edit_model
        self._key = settings.openai_api_key.get_secret_value()
        self._url = f"{str(settings.openai_api_base).rstrip('/')}/images/edits"
        self._timeout = settings.image_edit_timeout_seconds
        self._quality = settings.image_edit_quality
        self._format = settings.image_edit_output_format
        self._compression = settings.image_edit_output_compression
        self._transport = transport

    def _form(self, prompt: str, size: str, user_key: str) -> dict[str, str]:
        form = {
            "model": self.model_name,
            "prompt": prompt,
            "n": "1",
            "quality": self._quality,
            "size": size,
            "output_format": self._format,
            "safety_identifier": safety_identifier(user_key),
        }
        if self._format in ("jpeg", "webp"):
            form["output_compression"] = str(self._compression)
        return form

    async def edit(
        self, *, images: list[EditImage], prompt: str, size: str, user_key: str
    ) -> ImageEditResult:
        field = "image" if len(images) == 1 else "image[]"
        files = [(field, (img.filename, img.data, img.content_type)) for img in images]
        headers = {"Authorization": f"Bearer {self._key}"}
        # 연결은 짧게, 응답 대기는 길게 (생성에 최대 2분)
        timeout = httpx.Timeout(self._timeout, connect=15.0, pool=15.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as client:
                response = await client.post(
                    self._url, data=self._form(prompt, size, user_key), files=files, headers=headers
                )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise ImageEditError(
                "IMAGE_UNAVAILABLE", "OpenAI connection failed", retryable=True, called=False
            ) from None
        except httpx.WriteTimeout:
            # 요청 본문을 다 보내지 못함 → OpenAI가 처리를 시작하지 않음
            raise ImageEditError(
                "IMAGE_UNAVAILABLE", "OpenAI upload timed out", retryable=True, called=False
            ) from None
        except httpx.ReadTimeout:
            raise ImageEditError(
                "IMAGE_RESULT_UNKNOWN",
                "OpenAI did not answer in time; the request may have been processed",
                retryable=False,
            ) from None
        except httpx.HTTPError as exc:
            logger.warning("openai image request failed", extra={"error_type": type(exc).__name__})
            raise ImageEditError(
                "IMAGE_RESULT_UNKNOWN",
                "OpenAI connection dropped; the request may have been processed",
                retryable=False,
            ) from None

        status = response.status_code
        if status >= 400:
            err_code, err_type = _error_fields(response)
            logger.warning(
                "openai image error response",
                extra={"status": status, "error_code": err_code, "error_type": err_type},
            )
            detail = f"{status} {err_code or err_type or ''}".strip()
            if status == 429 and err_code == "insufficient_quota":
                raise ImageEditError(
                    "IMAGE_QUOTA_EXCEEDED", f"OpenAI quota exceeded ({detail})", retryable=False
                )
            if status == 429:
                raise ImageEditError(
                    "IMAGE_RATE_LIMITED", f"OpenAI rate limit ({detail})", retryable=True
                )
            if status in _RETRYABLE_STATUS:
                raise ImageEditError(
                    "IMAGE_UNAVAILABLE", f"OpenAI responded {detail}", retryable=True
                )
            if status >= 500:
                raise ImageEditError(
                    "IMAGE_RESULT_UNKNOWN", f"OpenAI responded {detail}", retryable=False
                )
            if status in (401, 403):
                raise ImageEditError(
                    "IMAGE_AUTH_FAILED",
                    f"OpenAI rejected the key or organization ({detail})",
                    retryable=False,
                )
            if status == 404:
                raise ImageEditError(
                    "IMAGE_MODEL_UNAVAILABLE",
                    f"Model not available for this key ({detail})",
                    retryable=False,
                )
            if err_code in ("moderation_blocked", "content_policy_violation") or (
                err_type == "image_generation_user_error"
            ):
                raise ImageEditError(
                    "IMAGE_BLOCKED", f"Rejected by content policy ({detail})", retryable=False
                )
            raise ImageEditError("IMAGE_BAD_REQUEST", f"OpenAI responded {detail}", retryable=False)

        try:
            data = response.json()
            item = (data.get("data") or [None])[0] or {}
            encoded = item.get("b64_json")
            image = base64.b64decode(encoded, validate=True) if encoded else b""
        except (ValueError, TypeError, AttributeError):
            raise ImageEditError(
                "IMAGE_INVALID_RESPONSE", "OpenAI returned an unreadable result", retryable=False
            ) from None
        if not image:
            raise ImageEditError(
                "IMAGE_EMPTY_RESPONSE", "OpenAI returned no image", retryable=False
            )
        usage = data.get("usage") or {}
        details = usage.get("input_tokens_details") or {}
        return ImageEditResult(
            image=image,
            output_format=str(data.get("output_format") or self._format),
            input_tokens=int(usage.get("input_tokens") or 0),
            input_image_tokens=int(details.get("image_tokens") or 0),
            input_text_tokens=int(details.get("text_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            model_name=self.model_name,
        )


def build_image_editor(settings: Settings) -> ImageEditor | None:
    """Worker 전용. 기능이 켜져 있고 OpenAI 키가 있을 때만."""
    if not (settings.image_edit_active and settings.image_edit_configured):
        return None
    return OpenAiImageEditor(settings)
