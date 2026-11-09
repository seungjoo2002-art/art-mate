"""음성 → 텍스트 (STT). 기본 구현: faster-whisper (서버 내부 실행, 외부 STT API 미사용).

- `SpeechToText` 프로토콜만 서비스가 의존한다. 테스트는 가짜 구현을 쓴다.
- faster-whisper는 Worker 전용 선택 의존성(`uv sync --extra stt`)이다.
  API 프로세스는 import하지 않는다.
- 호출은 블로킹이므로 Worker가 스레드(`asyncio.to_thread`)에서 실행한다. 시간 제한은 구간을 하나씩
  꺼낼 때마다 확인한다 (faster-whisper는 구간을 지연 생성하므로 중간에 멈출 수 있다).
- 로그에 음성·전사 내용을 남기지 않는다.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings

logger = logging.getLogger(__name__)


class SttError(Exception):
    """전사 실패. `code`는 작업 오류 코드로 저장된다 (메시지에 전사 내용을 넣지 않는다)."""

    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    index: int
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    language: str
    duration_ms: int | None
    segments: list[TranscriptSegment]
    engine: str
    model_name: str

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments).strip()


class SpeechToText(Protocol):
    engine: str
    model_name: str

    def transcribe(
        self, audio: bytes, *, language: str, deadline: float, max_audio_seconds: int
    ) -> TranscriptionResult:
        """블로킹. `deadline`은 time.monotonic() 기준 마감 시각."""
        ...


class FasterWhisperSTT:
    engine = "faster-whisper"

    def __init__(self, settings: Settings) -> None:
        self.model_name = settings.stt_model
        self._settings = settings
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                try:
                    from faster_whisper import WhisperModel
                except ImportError as exc:  # pragma: no cover - 설치 안내
                    raise SttError(
                        "STT_NOT_INSTALLED",
                        "faster-whisper is not installed (uv sync --extra stt)",
                        retryable=False,
                    ) from exc
                s = self._settings
                started = time.monotonic()
                self._model = WhisperModel(
                    s.stt_model,
                    device=s.stt_device,
                    compute_type=s.stt_compute_type,
                    cpu_threads=s.stt_cpu_threads,
                    download_root=s.stt_model_dir,
                )
                logger.info(
                    "stt model loaded",
                    extra={
                        "model": s.stt_model,
                        "load_ms": int((time.monotonic() - started) * 1000),
                    },
                )
        return self._model

    def transcribe(
        self, audio: bytes, *, language: str, deadline: float, max_audio_seconds: int
    ) -> TranscriptionResult:
        model = self._load()
        try:
            segments_iter, info = model.transcribe(
                io.BytesIO(audio),
                language=language,
                beam_size=self._settings.stt_beam_size,
                vad_filter=True,  # 무음 구간 제거 → 처리 시간·환각 감소
                condition_on_previous_text=False,  # 반복 환각 완화
            )
        except Exception as exc:  # 디코딩 실패 (손상 파일 등)
            raise SttError(
                "AUDIO_DECODE_FAILED",
                f"Audio could not be decoded ({type(exc).__name__})",
                retryable=False,
            ) from None
        duration = getattr(info, "duration", None)
        if duration is not None and duration > max_audio_seconds:
            raise SttError("AUDIO_TOO_LONG", "Audio is longer than the STT limit", retryable=False)

        segments: list[TranscriptSegment] = []
        for segment in segments_iter:
            if time.monotonic() > deadline:
                raise SttError("STT_TIMEOUT", "Transcription timed out", retryable=True)
            text = segment.text.strip()
            if text:
                segments.append(
                    TranscriptSegment(
                        index=len(segments),
                        start_ms=int(segment.start * 1000),
                        end_ms=int(segment.end * 1000),
                        text=text,
                    )
                )
        if not segments:
            raise SttError("EMPTY_TRANSCRIPT", "No speech was recognized", retryable=False)
        return TranscriptionResult(
            language=getattr(info, "language", language) or language,
            duration_ms=int(duration * 1000) if duration is not None else None,
            segments=segments,
            engine=self.engine,
            model_name=self.model_name,
        )


def build_stt(settings: Settings) -> SpeechToText | None:
    return FasterWhisperSTT(settings) if settings.stt_enabled else None
