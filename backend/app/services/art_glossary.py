"""미술 입시 첨삭 용어 사전 (v1.2). 외부 호출 없음, 순수 데이터·함수.

쓰는 곳
- STT 용어 힌트: faster-whisper `hotwords`/`initial_prompt` (app/integrations/ai/stt.py)
- STT 문맥 보정: 보정 프롬프트의 용어 목록·안전 검사 (app/services/stt_correction.py)
- 반복 실수 세부 주제: 같은 태그 안에서 "타원"과 "원통 윗면"처럼 표현이 달라도 같은 주제로 묶는다
  (app/services/growth_insights.py). 단어 일치가 아니라 주제별 키워드 묶음으로 연결하고,
  키워드에 걸리지 않는 첨삭은 억지로 묶지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 강사가 자주 쓰는 용어 (STT가 틀리기 쉬운 순서로 앞에 둔다). 프롬프트 길이 제한(Whisper 224토큰)을
# 고려해 짧게 유지한다.
ART_TERMS: tuple[str, ...] = (
    "기초디자인",
    "정물",
    "원물",
    "타원",
    "투시",
    "소실점",
    "명암",
    "하이라이트",
    "반사광",
    "채도",
    "명도",
    "색상",
    "구도",
    "비례",
    "형태",
    "질감",
    "재질",
    "덩어리감",
    "양감",
    "공간감",
    "원근",
    "중첩",
    "묘사",
    "톤",
    "그라데이션",
    "터치",
    "붓질",
)

# Whisper에 앞 문맥으로 주는 짧은 문장. 실제 발화처럼 보이면 무음 구간에 그대로 출력(환각)될 수 있어
# 용어 나열이 아닌 상황 설명으로만 쓴다.
STT_INITIAL_PROMPT = "미술 입시 학원에서 강사가 학생 그림을 첨삭하는 대화입니다."


def stt_hotwords() -> str:
    return " ".join(ART_TERMS)


@dataclass(frozen=True, slots=True)
class Theme:
    code: str
    label: str
    # 항목 문장에 이 중 하나라도 있으면 이 주제로 본다 (공백 제거 후 부분 일치)
    keywords: tuple[str, ...]


# 반복 실수 세부 주제. 9개 태그보다 좁은 단위 (예: 형태·비례 안의 "타원·원통형").
THEMES: tuple[Theme, ...] = (
    Theme("ELLIPSE", "타원·원통형 형태", ("타원", "원통", "원기둥", "컵입구", "윗면", "입구")),
    Theme("PROPORTION_SIZE", "비례·크기", ("비례", "비율", "크기", "길이")),
    Theme("PERSPECTIVE", "투시·소실점", ("투시", "소실점", "원근", "시점")),
    Theme("VALUE_CONTRAST", "명암 대비·톤", ("대비", "명도", "톤", "어두운", "밝은", "명암")),
    Theme("REFLECTED_LIGHT", "반사광·하이라이트", ("반사광", "하이라이트")),
    Theme("SHADOW", "그림자", ("그림자", "그늘", "캐스트")),
    Theme("TEXTURE", "재질·질감", ("질감", "재질", "금속", "유리", "나무결")),
    Theme("COMPOSITION", "구도·배치", ("구도", "배치", "여백", "화면")),
    Theme("COLOR", "색채·채도", ("채도", "색상", "색감", "혼색", "색이")),
    Theme("VOLUME", "덩어리감·양감", ("덩어리", "양감", "입체")),
    Theme("SPACE", "공간감·중첩", ("공간감", "중첩", "앞뒤", "거리감")),
    Theme("JOINT", "연결 부분", ("연결", "이음", "손잡이")),
    Theme("RENDERING", "묘사·마무리", ("묘사", "디테일", "마무리")),
    Theme("STROKE", "터치·붓질", ("터치", "붓질", "선정리")),
)
THEME_BY_CODE = {t.code: t for t in THEMES}

_SPACES = re.compile(r"\s+")


def themes_in(text: str) -> set[str]:
    """문장에 나온 세부 주제 코드. 없으면 빈 집합 (추측해서 넣지 않는다)."""
    compact = _SPACES.sub("", text)
    return {t.code for t in THEMES if any(k in compact for k in t.keywords)}
