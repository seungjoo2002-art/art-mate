"""외부 AI로 보내기 전 개인정보 최소화 (v0.9.6). 원문 대본·저장 구조는 바꾸지 않는다.

- 보낼 문장 사본에서만 가린다: 전화번호·이메일·주민등록번호·카드번호·URL·학생 본인 이름(실명·닉네임)
- 구간 번호·개수·시각은 그대로 → 근거 구간 연결, 원문 대본, 요약 결과, 성장 분석의 연결이 유지된다.
- 근거 대조도 가린 문장으로 한다 (AI가 본 문장 기준).

한계 (익명화가 아님 — 가명처리·최소화 수준):
- 강사·다른 학생 이름, 학교·학원명, 지역, 대회·작품 고유명은 일반적으로 찾을 수 없어 남을 수 있다.
- 말 속의 맥락(가족 이야기, 진학 학교 등)으로 사람을 알아볼 수 있다.
- 음성 인식 오류로 형태가 바뀐 이름·번호는 놓칠 수 있다.
따라서 국외 이전 동의는 "전사문(이름 등이 포함될 수 있음)" 기준으로 받는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# 순서 중요: 긴 숫자 형식(주민번호·카드)을 전화번호보다 먼저
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[이메일]"),
    (re.compile(r"https?://\S+|www\.\S+"), "[링크]"),
    (re.compile(r"\b\d{6}\s*-\s*[1-8]\d{6}\b"), "[주민번호]"),
    (re.compile(r"\b\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}\b"), "[카드번호]"),
    # 휴대폰·지역번호 (010-1234-5678, 010 1234 5678, 01012345678, 02-123-4567)
    (re.compile(r"(?<!\d)0\d{1,2}[\s.-]?\d{3,4}[\s.-]?\d{4}(?!\d)"), "[전화번호]"),
]
STUDENT = "[학생]"


@dataclass(frozen=True, slots=True)
class Redaction:
    segments: list[dict[str, Any]]
    replaced: int  # 가린 횟수 (내용은 기록하지 않음)


def _names(names: Iterable[str | None]) -> list[str]:
    """두 글자 이상 이름만, 긴 것부터 (부분 일치로 짧은 이름이 먼저 바뀌지 않도록)."""
    cleaned = {n.strip() for n in names if n and len(n.strip()) >= 2}
    return sorted(cleaned, key=len, reverse=True)


def redact_text(text: str, names: Iterable[str | None] = ()) -> tuple[str, int]:
    count = 0
    for pattern, label in _PATTERNS:
        text, n = pattern.subn(label, text)
        count += n
    for name in _names(names):
        n = text.count(name)
        if n:
            text = text.replace(name, STUDENT)
            count += n
    return text, count


def redact_segments(segments: list[dict[str, Any]], names: Iterable[str | None] = ()) -> Redaction:
    """구간 사본에서 text만 가린다 (index·start_ms·end_ms 등 나머지는 그대로)."""
    known = _names(names)
    out: list[dict[str, Any]] = []
    total = 0
    for segment in segments:
        text, n = redact_text(str(segment.get("text", "")), known)
        total += n
        out.append({**segment, "text": text})
    return Redaction(segments=out, replaced=total)
