"""STT 모델 비교 도구 (개발용, 운영 서비스와 무관).

같은 녹음 파일들을 여러 엔진으로 변환해 CER·미술 용어 정확도·처리 시간·예상 비용을 비교한다.
정답 대본은 녹음 파일 옆의 `<파일이름>.txt` (예: lesson1.m4a → lesson1.m4a.txt).

엔진
  local-small          서버와 같은 faster-whisper small·INT8·VAD (이 PC, 외부 전송 없음)
  groq-large-v3        Groq whisper-large-v3            ← 외부 전송
  groq-large-v3-turbo  Groq whisper-large-v3-turbo      ← 외부 전송
  openai-transcribe    OpenAI gpt-4o-transcribe (--openai-model로 변경)  ← 외부 전송
  (브라우저 Whisper base는 /tools/stt-bench에서 같은 파일·정답으로 측정)

외부 엔진은 실제 녹음을 회사 밖으로 보낸다. 녹음 당사자 동의와 운영자 승인이 확인된 경우에만
--allow-external 과 API 키(GROQ_API_KEY / OPENAI_API_KEY 환경변수)를 함께 줘야 실행된다.
그 밖에는 호출하지 않고 "skipped"로 표시한다.

사용:
  cd backend && uv sync --extra stt
  uv run python -m scripts.stt_compare lesson1.m4a lesson2.webm --engines local-small
  uv run python -m scripts.stt_compare *.m4a --engines local-small,groq-large-v3 --allow-external
결과: 표 출력 + --out results.jsonl (전사 원문 포함 — 개인정보이므로 공유 주의)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.services.stt_metrics import cer, term_accuracy

# 공개 가격 (USD, 오디오 1시간당). 2026-11 공개 자료 기준 근삿값 — 사용 전 공식 가격표 확인
PRICE_PER_HOUR = {
    "local-small": 0.0,
    "groq-large-v3": 0.111,
    "groq-large-v3-turbo": 0.04,
    "openai-transcribe": 0.36,  # gpt-4o-transcribe 분당 $0.006 기준
}
EXTERNAL = {"groq-large-v3", "groq-large-v3-turbo", "openai-transcribe"}
GROQ_MODELS = {"groq-large-v3": "whisper-large-v3", "groq-large-v3-turbo": "whisper-large-v3-turbo"}


@dataclass
class Row:
    engine: str
    file: str
    audio_s: float | None
    elapsed_s: float | None = None
    text: str = ""
    cer: float | None = None
    terms: str = ""
    cost_usd: float | None = None
    status: str = "ok"


def audio_seconds(path: Path) -> float | None:
    try:
        from faster_whisper.audio import decode_audio

        return len(decode_audio(str(path), sampling_rate=16000)) / 16000
    except Exception:
        return None


class LocalSmall:
    def __init__(self) -> None:
        from faster_whisper import WhisperModel

        self.model = WhisperModel("small", device="cpu", compute_type="int8")

    def __call__(self, path: Path) -> str:
        segments, _ = self.model.transcribe(
            str(path),
            language="ko",
            beam_size=1,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments)


def remote(url: str, key: str, model: str):  # type: ignore[no-untyped-def]
    def run(path: Path) -> str:
        with path.open("rb") as f:
            res = httpx.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                data={"model": model, "language": "ko", "response_format": "json"},
                files={"file": (path.name, f)},
                timeout=300,
            )
        res.raise_for_status()
        return str(res.json().get("text", ""))

    return run


def build(engine: str, args: argparse.Namespace):  # type: ignore[no-untyped-def]
    if engine == "local-small":
        return LocalSmall()
    if engine in EXTERNAL and not args.allow_external:
        return "외부 전송 미승인 (--allow-external 필요)"
    if engine in GROQ_MODELS:
        key = os.environ.get("GROQ_API_KEY")
        if not key:
            return "GROQ_API_KEY 없음"
        return remote(
            "https://api.groq.com/openai/v1/audio/transcriptions", key, GROQ_MODELS[engine]
        )
    if engine == "openai-transcribe":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            return "OPENAI_API_KEY 없음"
        return remote("https://api.openai.com/v1/audio/transcriptions", key, args.openai_model)
    return f"알 수 없는 엔진: {engine}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--engines", default="local-small")
    parser.add_argument("--allow-external", action="store_true")
    parser.add_argument("--openai-model", default="gpt-4o-transcribe")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    rows: list[Row] = []
    for engine in [e.strip() for e in args.engines.split(",") if e.strip()]:
        runner = build(engine, args)
        for path in args.files:
            seconds = audio_seconds(path)
            row = Row(engine=engine, file=path.name, audio_s=seconds)
            if isinstance(runner, str):
                row.status = f"skipped: {runner}"
                rows.append(row)
                continue
            started = time.monotonic()
            try:
                row.text = runner(path)
            except Exception as exc:  # 한 파일 실패가 비교 전체를 멈추지 않게
                row.status = f"error: {type(exc).__name__}"
            row.elapsed_s = round(time.monotonic() - started, 1)
            ref_path = path.with_name(path.name + ".txt")
            if ref_path.exists() and row.status == "ok":
                reference = ref_path.read_text(encoding="utf-8")
                value = cer(reference, row.text)
                row.cer = None if value is None else round(value * 100, 1)
                terms = term_accuracy(reference, row.text)
                row.terms = f"{terms.matched}/{terms.total}" + (
                    f" (놓침: {', '.join(terms.missed)})" if terms.missed else ""
                )
            if seconds is not None:
                row.cost_usd = round(PRICE_PER_HOUR[engine] * seconds / 3600, 5)
            rows.append(row)

    print(f"{'engine':22} {'file':20} {'audio':>6} {'time':>6} {'CER%':>6} terms / status")
    for r in rows:
        audio = f"{r.audio_s:.0f}s" if r.audio_s else "-"
        took = f"{r.elapsed_s}s" if r.elapsed_s is not None else "-"
        cer_text = "-" if r.cer is None else str(r.cer)
        detail = r.terms if r.status == "ok" else r.status
        print(f"{r.engine:22} {r.file[:20]:20} {audio:>6} {took:>6} {cer_text:>6} {detail}")
    if args.out:
        with args.out.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r.__dict__, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
