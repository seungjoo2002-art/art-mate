"""STT 결과 평가 (모델 비교용). frontend/src/features/feedback/stt/sttMetrics.js와 같은 기준.

- CER: 정답 대본 대비 글자 오류율 (공백·문장부호 제외, 편집 거리 / 정답 글자 수)
- 미술 용어 정확도: 정답 대본에 나온 미술 용어 중 결과에도 나온 비율 (등장 횟수 기준)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ART_TERMS = (
    "구도", "소실점", "투시", "원근감", "명암", "명도", "채도", "색상", "보색", "대비",
    "반사광", "하이라이트", "그림자", "양감", "입체감", "공간감", "질감", "비례", "윤곽", "톤",
    "석고상", "정물", "기초디자인", "사고의 전환", "발상", "스케치", "묘사", "터치", "색감", "배경",
    "주제", "형태", "구성", "레이어", "농도", "번짐", "수채화", "소묘", "크로키", "여백",
)  # fmt: skip

_STRIP = re.compile(r"[\s.,!?·…'\"‘’“”()\[\]{}:;~-]")


def normalize_text(text: str | None) -> str:
    return _STRIP.sub("", text or "")


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(reference: str, hypothesis: str) -> float | None:
    ref = normalize_text(reference)
    if not ref:
        return None
    return edit_distance(ref, normalize_text(hypothesis)) / len(ref)


@dataclass(frozen=True)
class TermAccuracy:
    total: int
    matched: int
    missed: list[str] = field(default_factory=list)

    @property
    def ratio(self) -> float | None:
        return self.matched / self.total if self.total else None


def term_accuracy(
    reference: str, hypothesis: str, terms: tuple[str, ...] = ART_TERMS
) -> TermAccuracy:
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    total = matched = 0
    missed: list[str] = []
    for term in terms:
        t = normalize_text(term)
        want = ref.count(t)
        if not want:
            continue
        got = min(want, hyp.count(t))
        total += want
        matched += got
        if got < want:
            missed.append(term)
    return TermAccuracy(total=total, matched=matched, missed=missed)
