"""요약·성장 분석 LLM 선택 (v0.9.6). AI_PROVIDER에 따라 OpenAI 또는 Gemini.

둘 다 같은 `SummaryLlm` 인터페이스·오류 코드를 쓰므로 프롬프트·검증·저장·화면은 제공자와 무관하다.
배포 환경에서는 운영자 확인(AI_PROVIDER_TERMS_CONFIRMED) 전에는 만들지 않는다 (`ai_summary_active`).
"""

from __future__ import annotations

from app.core.config import Settings
from app.integrations.ai.gemini import GeminiClient, SummaryLlm
from app.integrations.ai.openai_llm import OpenAiClient


def build_llm(settings: Settings) -> SummaryLlm | None:
    if not (settings.ai_summary_active and settings.llm_configured):
        return None
    if settings.ai_provider == "openai":
        return OpenAiClient(settings)
    return GeminiClient(settings)
