"""테스트용 STT·LLM·음성 다운로드 대체 구현.

실제 faster-whisper·Gemini·Storage를 호출하지 않는다.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

from app.integrations.ai.gemini import LlmError, LlmResponse
from app.integrations.ai.stt import SttError, TranscriptionResult, TranscriptSegment
from app.integrations.supabase.storage import StorageObjectNotFound
from tests.fake_storage import FakeStorage

SEGMENTS = [
    "전체적으로 구도는 안정적으로 잘 잡았어.",
    "근데 오른쪽 사과의 명암이 너무 약해서 형태가 떠 보여.",
    "어두운 면을 한 톤 더 눌러주고 반사광은 조금만 남겨.",
    "다음 작품에서는 처음부터 큰 덩어리 명암을 먼저 잡자.",
]


def stt_result(texts: list[str] | None = None) -> TranscriptionResult:
    texts = texts or SEGMENTS
    return TranscriptionResult(
        language="ko",
        duration_ms=len(texts) * 4000,
        segments=[
            TranscriptSegment(index=i, start_ms=i * 4000, end_ms=i * 4000 + 3500, text=t)
            for i, t in enumerate(texts)
        ],
        engine="fake-whisper",
        model_name="small",
    )


@dataclass
class FakeStt:
    engine: str = "fake-whisper"
    model_name: str = "small"
    # 순서대로 꺼내 쓸 결과 (TranscriptionResult 또는 SttError). 비면 기본 결과
    outcomes: deque[Any] = field(default_factory=deque)
    calls: list[int] = field(default_factory=list)  # 받은 음성 크기

    def transcribe(
        self, audio: bytes, *, language: str, deadline: float, max_audio_seconds: int
    ) -> TranscriptionResult:
        self.calls.append(len(audio))
        outcome = self.outcomes.popleft() if self.outcomes else stt_result()
        if isinstance(outcome, SttError):
            raise outcome
        return outcome


def ai_json(**overrides: Any) -> str:
    data: dict[str, Any] = {
        "summary": "구도는 안정적이나 오른쪽 사과의 명암이 약해 형태가 떠 보인다.",
        "strengths": [
            {"text": "구도를 안정적으로 잡았다.", "category": "COMPOSITION", "evidence": [0]}
        ],
        "weaknesses": [
            {
                "text": "오른쪽 사과의 명암이 약해 형태가 떠 보인다.",
                "category": "VALUE",
                "evidence": [1],
            }
        ],
        "fixes": [
            {
                "text": "어두운 면을 한 톤 더 누르고 반사광은 조금만 남긴다.",
                "category": "VALUE",
                "evidence": [2],
            }
        ],
        "next_tips": [
            {"text": "처음부터 큰 덩어리 명암을 먼저 잡는다.", "category": "VALUE", "evidence": [3]}
        ],
        "weakness_categories": ["VALUE", "FORM"],
        "insufficient_content": False,
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


@dataclass
class FakeLlm:
    model_name: str = "gemini-3.1-flash-lite"
    # 순서대로: str(응답 JSON) 또는 LlmError. 비면 기본 응답
    outcomes: deque[Any] = field(default_factory=deque)
    prompts: list[str] = field(default_factory=list)

    async def generate(self, *, system: str, prompt: str, schema: dict[str, Any]) -> LlmResponse:
        self.prompts.append(prompt)
        outcome = self.outcomes.popleft() if self.outcomes else ai_json()
        if isinstance(outcome, LlmError):
            raise outcome
        return LlmResponse(
            text=outcome,
            input_tokens=120,
            output_tokens=80,
            finish_reason="STOP",
            model_name=self.model_name,
        )


@dataclass
class FakeFetcher:
    """FakeStorage가 만든 Signed URL에서 경로를 꺼내 메모리 객체를 돌려준다."""

    storage: FakeStorage
    urls: list[str] = field(default_factory=list)

    async def fetch(self, url: str, *, max_bytes: int) -> bytes:
        self.urls.append(url)
        path = unquote(urlsplit(url).path).split(f"/object/sign/{self.storage.bucket}/", 1)[1]
        if path not in self.storage.objects:
            raise StorageObjectNotFound("missing")
        return self.storage.objects[path]
