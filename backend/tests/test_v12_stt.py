"""v1.2 STT: 미술 용어 힌트, 문맥 보정의 안전 검사 (외부 호출 없음)."""

import json
from typing import Any

import pytest

from app.integrations.ai.stt import vocabulary_kwargs
from app.services import stt_correction as sc
from app.services.art_glossary import ART_TERMS, STT_INITIAL_PROMPT, themes_in
from tests.conftest import make_settings

# ------------------------------------------------------------------ 용어 힌트


def _new_whisper(
    audio: Any, language: str, hotwords: str | None = None, initial_prompt: Any = None
):  # type: ignore[no-untyped-def]
    """faster-whisper ≥ 1.0.2 와 같은 인자를 받는 가짜."""


def _old_whisper(audio: Any, language: str, initial_prompt: Any = None):  # type: ignore[no-untyped-def]
    """hotwords를 모르는 이전 버전."""


def _minimal(audio: Any, language: str):  # type: ignore[no-untyped-def]
    """힌트 인자를 하나도 받지 않는 엔진."""


def test_vocabulary_hints_use_supported_arguments_only() -> None:
    settings = make_settings()
    kwargs = vocabulary_kwargs(_new_whisper, settings)
    assert kwargs["initial_prompt"] == STT_INITIAL_PROMPT
    for term in ("기초디자인", "타원", "소실점", "반사광", "덩어리감", "그라데이션", "붓질"):
        assert term in kwargs["hotwords"]
    # 모르는 옵션은 보내지 않는다
    assert vocabulary_kwargs(_old_whisper, settings) == {"initial_prompt": STT_INITIAL_PROMPT}
    assert vocabulary_kwargs(_minimal, settings) == {}


def test_vocabulary_hints_can_be_turned_off() -> None:
    assert vocabulary_kwargs(_new_whisper, make_settings(stt_vocabulary_hints=False)) == {}


def test_glossary_covers_requested_terms_and_initial_prompt_is_not_a_term_list() -> None:
    requested = [
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
    ]
    assert set(requested) <= set(ART_TERMS)
    # 무음 구간에 용어가 그대로 출력되는 환각을 피하려고 용어 나열을 넣지 않는다
    assert not any(t in STT_INITIAL_PROMPT for t in ("타원", "소실점", "반사광"))


# ------------------------------------------------------------------ 문맥 보정 안전 검사


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("컵 위에 타원이 너무 납작해.", "컵 위의 타원이 너무 납작해."),  # 조사
        ("오른쪽 사과 명함이 너무 약해", "오른쪽 사과 명암이 너무 약해"),  # 용어 오인식
        ("반사과는 조금만 남겨", "반사광은 조금만 남겨"),
        ("손잡이 연결도 부자연스러워", "손잡이 연결도 부자연스러워."),  # 문장부호
        ("소실 점을 하나로 맞춰", "소실점을 하나로 맞춰"),  # 띄어쓰기
    ],
)
def test_safe_corrections_are_accepted(before: str, after: str) -> None:
    assert sc.is_safe_correction(before, after)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        # 원문에 없는 평가 추가
        ("타원이 너무 납작해", "타원이 너무 납작하고 명암도 부족해"),
        # 칭찬 → 지적 (의미 왜곡)
        ("명암은 지난번보다 좋아졌네", "명암은 지난번보다 부족하네"),
        # 부정 추가·삭제
        ("구도는 괜찮아", "구도는 안 괜찮아"),
        ("명암이 안 좋아", "명암이 좋아"),
        ("명암이 좋아", "명암이 안좋아"),  # 띄어쓰기 없는 부정
        ("타원 정리했어", "타원 정리 안했어"),
        ("형태를 못 잡았어", "형태를 잡았어"),
        # 숫자 변경
        ("톤을 2단계 더 눌러", "톤을 3단계 더 눌러"),
        # 알아들을 수 없는 부분을 추측해서 채움
        ("어 그 부분 음 좀", "그 부분 명암 대비를 높여"),
        # 비움
        ("타원이 납작해", "   "),
    ],
)
def test_meaning_changes_are_rejected(before: str, after: str) -> None:
    assert not sc.is_safe_correction(before, after)


def _segments(*texts: str) -> list[dict[str, Any]]:
    return [
        {"index": i, "start_ms": i * 1000, "end_ms": i * 1000 + 900, "text": t}
        for i, t in enumerate(texts)
    ]


def test_parse_keeps_original_for_rejected_or_locked_segments() -> None:
    original = _segments(
        "컵 위에 타원이 너무 납작해.",
        "명암은 지난번보다 좋아졌네.",
        "[학생] 명함 좀 봐",
        "다음엔 타원부터 잡아봐.",
    )
    raw = json.dumps(
        {
            "corrections": [
                {"index": 0, "text": "컵 위의 타원이 너무 납작해."},  # 통과
                {"index": 1, "text": "명암은 지난번보다 부족하네."},  # 의미 변경 → 거절
                {"index": 2, "text": "[학생] 명암 좀 봐"},  # 가림 구간 → 잠금
                {"index": 9, "text": "없는 구간"},  # 없는 번호 → 거절
                {"index": 0, "text": "중복"},  # 같은 번호 두 번 → 거절
                {"index": 3, "text": "다음엔 타원부터 잡아봐."},  # 변화 없음
            ]
        },
        ensure_ascii=False,
    )
    result = sc.parse_corrections(raw, original, locked={2})
    assert result.changed == [0]
    assert result.rejected == 4
    assert [s["text"] for s in result.segments] == [
        "컵 위의 타원이 너무 납작해.",
        "명암은 지난번보다 좋아졌네.",
        "[학생] 명함 좀 봐",
        "다음엔 타원부터 잡아봐.",
    ]
    # 구간 번호·시각은 그대로 (요약 근거 번호가 그대로 맞는다), 원본 목록은 바뀌지 않는다
    assert [(s["index"], s["start_ms"]) for s in result.segments] == [
        (s["index"], s["start_ms"]) for s in original
    ]
    assert original[0]["text"] == "컵 위에 타원이 너무 납작해."


def test_parse_rejects_non_json_and_wrong_shape() -> None:
    with pytest.raises(sc.InvalidCorrectionOutput):
        sc.parse_corrections("not json", _segments("타원"))
    with pytest.raises(sc.InvalidCorrectionOutput):
        sc.parse_corrections(json.dumps({"corrections": "x"}), _segments("타원"))


def test_apply_texts_moves_only_changed_segments() -> None:
    redacted = _segments("[학생] 타원 봐", "명함이 약해")
    corrected = _segments("김철수 타원 봐", "명암이 약해")
    out = sc.apply_texts(redacted, corrected, [1])
    assert [s["text"] for s in out] == ["[학생] 타원 봐", "명암이 약해"]


def test_prompt_contains_rules_and_glossary_but_no_personal_fields() -> None:
    prompt = sc.build_prompt(_segments("타원이 납작해"))
    assert "[0] 타원이 납작해" in prompt
    assert "추측" in sc.SYSTEM_INSTRUCTION and "소실점" in sc.SYSTEM_INSTRUCTION


# ------------------------------------------------------------------ 세부 주제 (반복 실수 묶기)


def test_themes_group_different_wordings_of_the_same_mistake() -> None:
    assert "ELLIPSE" in themes_in("컵 타원이 납작하다.")
    assert "ELLIPSE" in themes_in("원통형 물체의 윗부분 비례가 어색하다.")
    assert "ELLIPSE" in themes_in("타원 형태를 다시 확인해라.")
    # 키워드가 없으면 묶지 않는다 (추측 금지)
    assert themes_in("전체적으로 좀 더 신경 써.") == set()
    # 한 글자 키워드로 엉뚱하게 묶이지 않는다
    assert "TEXTURE" not in themes_in("천천히 다시 그려 봐")
