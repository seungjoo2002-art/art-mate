"""AI 연동 단위 테스트 (DB·외부 호출 없음): 출력 검증, 프롬프트, Gemini HTTP 처리, STT 시간 제한."""

import json
import logging
import time
from types import SimpleNamespace

import httpx
import pytest

from app.integrations.ai.gemini import GeminiClient, LlmError
from app.integrations.ai.stt import FasterWhisperSTT, SttError
from app.models.enums import WeaknessCategory
from app.services.ai_summary import (
    RESPONSE_SCHEMA,
    SYSTEM_INSTRUCTION,
    InvalidAiOutput,
    build_prompt,
    parse_output,
)
from tests.conftest import make_settings
from tests.fake_ai import ai_json

SECRET_KEY = "test-gemini-key-do-not-log"

# ----------------------------------------------------------------------------- 출력 검증


def test_parse_output_valid() -> None:
    output, dropped = parse_output(ai_json(), segment_count=4)
    assert dropped == 0
    assert output.weaknesses[0].category == WeaknessCategory.VALUE
    # AI 목록(VALUE, FORM) + 부족한 점·수정 방법 항목 카테고리, 정의 순서
    assert output.weakness_categories == [WeaknessCategory.FORM, WeaknessCategory.VALUE]


def test_parse_output_drops_items_without_valid_evidence() -> None:
    raw = ai_json(
        strengths=[
            {"text": "근거 없는 칭찬", "category": None, "evidence": []},
            {"text": "없는 구간 근거", "category": None, "evidence": [99, -1]},
            {"text": "일부만 유효", "category": None, "evidence": [0, 7, 0]},
        ]
    )
    output, dropped = parse_output(raw, segment_count=4)
    assert dropped == 2
    assert [i.text for i in output.strengths] == ["일부만 유효"]
    assert output.strengths[0].evidence == [0]


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        json.dumps({"summary": ""}),
        ai_json(weakness_categories=["LIGHTING"]),
        ai_json(weaknesses=[{"text": "x", "category": "명암", "evidence": [1]}]),
        ai_json(summary="가" * 2000),
        ai_json(strengths=[{"text": "x", "category": None, "evidence": [0]}] * 11),
    ],
)
def test_parse_output_rejects_invalid(raw: str) -> None:
    with pytest.raises(InvalidAiOutput):
        parse_output(raw, segment_count=4)


def test_prompt_contains_only_transcript_segments() -> None:
    prompt = build_prompt(
        [{"index": 0, "start_ms": 61_000, "end_ms": 65_000, "text": "명암을 더 눌러"}]
    )
    assert "[0] 01:01 명암을 더 눌러" in prompt
    assert "근거" in SYSTEM_INSTRUCTION and "만들어내지" in SYSTEM_INSTRUCTION
    assert set(RESPONSE_SCHEMA["required"]) >= {"summary", "weaknesses", "weakness_categories"}
    item_enum = RESPONSE_SCHEMA["properties"]["weaknesses"]["items"]["properties"]["category"]
    assert set(item_enum["enum"]) - {None} == {c.value for c in WeaknessCategory}


# ----------------------------------------------------------------------------- Gemini HTTP


def _client(handler) -> GeminiClient:  # type: ignore[no-untyped-def]
    settings = make_settings(ai_summary_enabled=True, gemini_api_key=SECRET_KEY)
    return GeminiClient(settings, transport=httpx.MockTransport(handler))


def _ok(text: str, finish: str = "STOP", **usage) -> httpx.Response:  # type: ignore[no-untyped-def]
    return httpx.Response(
        200,
        json={
            "candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}],
            "usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 90} | usage,
        },
    )


async def test_gemini_success_request_shape_and_usage() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok(ai_json(), thoughtsTokenCount=10)

    response = await _client(handler).generate(system="sys", prompt="p", schema=RESPONSE_SCHEMA)
    assert (response.input_tokens, response.output_tokens) == (300, 100)
    request = seen[0]
    assert request.url.path.endswith("/models/gemini-3.1-flash-lite:generateContent")
    assert request.headers["x-goog-api-key"] == SECRET_KEY
    assert SECRET_KEY not in str(request.url)  # 키는 URL 쿼리에 넣지 않는다
    body = json.loads(request.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseJsonSchema"] == RESPONSE_SCHEMA
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"


@pytest.mark.parametrize(
    ("response", "code", "retryable"),
    [
        (httpx.Response(429, json={}), "LLM_RATE_LIMITED", True),
        (httpx.Response(503, json={}), "LLM_UNAVAILABLE", True),
        (httpx.Response(401, json={}), "LLM_AUTH_FAILED", False),
        (httpx.Response(400, json={}), "LLM_BAD_REQUEST", False),
        (httpx.Response(200, text="<html>"), "LLM_INVALID_RESPONSE", True),
        (
            httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}),
            "LLM_BLOCKED",
            False,
        ),
        (httpx.Response(200, json={"candidates": []}), "LLM_EMPTY_RESPONSE", True),
        (_ok("{}", finish="MAX_TOKENS"), "LLM_OUTPUT_TRUNCATED", False),
        (_ok("{}", finish="SAFETY"), "LLM_BLOCKED", False),
        (_ok("   "), "LLM_EMPTY_RESPONSE", True),
    ],
)
async def test_gemini_errors(response: httpx.Response, code: str, retryable: bool) -> None:
    with pytest.raises(LlmError) as exc:
        await _client(lambda _: response).generate(system="s", prompt="p", schema={})
    assert (exc.value.code, exc.value.retryable) == (code, retryable)
    assert SECRET_KEY not in str(exc.value)


async def test_gemini_timeout_and_network_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def network(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(LlmError) as exc:
        await _client(timeout).generate(system="s", prompt="p", schema={})
    assert exc.value.code == "LLM_TIMEOUT" and exc.value.retryable
    with pytest.raises(LlmError) as exc:
        await _client(network).generate(system="s", prompt="p", schema={})
    assert exc.value.code == "LLM_UNAVAILABLE" and not exc.value.called


# ----------------------------------------------------------------------------- STT (모델 대체)


class _FakeWhisper:
    def __init__(
        self, duration: float, segments: list[tuple[float, float, str]], delay=0.0
    ) -> None:  # type: ignore[no-untyped-def]
        self.duration, self.segments, self.delay = duration, segments, delay

    def transcribe(self, audio, **kwargs):  # type: ignore[no-untyped-def]
        def gen():  # type: ignore[no-untyped-def]
            for start, end, text in self.segments:
                time.sleep(self.delay)
                yield SimpleNamespace(start=start, end=end, text=text)

        return gen(), SimpleNamespace(duration=self.duration, language="ko")


def _stt(model: _FakeWhisper) -> FasterWhisperSTT:
    stt = FasterWhisperSTT(make_settings(stt_enabled=True))
    stt._model = model  # 실제 모델 로드 없이
    return stt


def test_stt_builds_segments() -> None:
    model = _FakeWhisper(
        9.5, [(0.0, 3.2, " 구도 좋아 "), (3.2, 4.0, "  "), (4.0, 9.5, "명암 약해")]
    )
    result = _stt(model).transcribe(
        b"x", language="ko", deadline=time.monotonic() + 10, max_audio_seconds=60
    )
    assert [(s.index, s.start_ms, s.end_ms, s.text) for s in result.segments] == [
        (0, 0, 3200, "구도 좋아"),
        (1, 4000, 9500, "명암 약해"),
    ]
    assert result.text == "구도 좋아 명암 약해" and result.duration_ms == 9500


@pytest.mark.parametrize(
    ("model", "deadline", "code", "retryable"),
    [
        (_FakeWhisper(100.0, [(0, 1, "a")]), 10, "AUDIO_TOO_LONG", False),
        (_FakeWhisper(5.0, [(0, 1, "  ")]), 10, "EMPTY_TRANSCRIPT", False),
        (_FakeWhisper(5.0, [(0, 1, "a"), (1, 2, "b")], delay=0.05), 0.01, "STT_TIMEOUT", True),
    ],
)
def test_stt_limits(model: _FakeWhisper, deadline: float, code: str, retryable: bool) -> None:
    with pytest.raises(SttError) as exc:
        _stt(model).transcribe(
            b"x", language="ko", deadline=time.monotonic() + deadline, max_audio_seconds=60
        )
    assert (exc.value.code, exc.value.retryable) == (code, retryable)


# ----------------------------------------------------------------------------- 로그 노출 방지


async def test_signed_url_fetch_does_not_log_url(caplog: pytest.LogCaptureFixture) -> None:
    from app.core.logging import configure_logging
    from app.integrations.supabase.storage import HttpSignedUrlFetcher, StorageError

    configure_logging(make_settings(log_level="DEBUG"))
    url = "https://storage.test/object/sign/feedback-audio/u/a/r.webm?token=SECRET-TOKEN"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"audio")

    fetcher = HttpSignedUrlFetcher(timeout=5, transport=httpx.MockTransport(handler))
    with caplog.at_level(logging.DEBUG):
        assert await fetcher.fetch(url, max_bytes=100) == b"audio"
        failing = HttpSignedUrlFetcher(
            timeout=5,
            transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("x"))),
        )
        with pytest.raises(StorageError):
            await failing.fetch(url, max_bytes=100)
    assert "SECRET-TOKEN" not in caplog.text
