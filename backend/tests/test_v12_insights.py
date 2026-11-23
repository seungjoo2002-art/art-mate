"""v1.2 아카이브 분석(반복 실수·강점·개선 추세)과 홈 브리핑 문장 (규칙 기반, AI·DB 없음)."""

import uuid
from datetime import UTC, date, datetime
from typing import Any

from app.models.enums import (
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    FeedbackItemKind,
    FeedbackSource,
    WeaknessCategory,
)
from app.services.growth_analytics import ArtworkFact, Dataset, FeedbackFact, ItemFact
from app.services.growth_briefing import MSG_INSUFFICIENT, MSG_NO_RECORDS, compose_briefing
from app.services.growth_insights import build_insights, summarize_insights, tag_entry

C = WeaknessCategory
K = FeedbackItemKind


def build(specs: list[dict[str, Any]]) -> Dataset:
    """specs[i] = {day: date, items: [(kind, category, text)], source, mock}."""
    artworks, feedbacks, items = [], [], []
    categories: dict[uuid.UUID, set[WeaknessCategory]] = {}
    for i, spec in enumerate(specs):
        aid, fid = uuid.uuid4(), uuid.uuid4()
        day: date = spec["day"]
        stamp = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
        artworks.append(
            ArtworkFact(
                id=aid,
                title=f"작품 {i}",
                work_date=day,
                created_at=stamp,
                updated_at=stamp,
                work_status=ArtworkWorkStatus.COMPLETED,
                completed_at=stamp,
                practical_type=None,
                work_category=ArtworkWorkCategory.MOCK_EXAM if spec.get("mock") else None,
            )
        )
        feedbacks.append(
            FeedbackFact(fid, aid, stamp, 1, spec.get("source", FeedbackSource.INSTRUCTOR))
        )
        weak: set[WeaknessCategory] = set()
        for kind, category, text in spec.get("items", []):
            items.append(ItemFact(uuid.uuid4(), fid, aid, kind, category, day, stamp, text))
            if kind in (K.WEAKNESS, K.FIX) and category is not None:
                weak.add(category)
        categories[fid] = weak
    return Dataset(artworks, feedbacks, categories, items)


def counts(**overrides: int) -> dict[str, Any]:
    base = {
        "artwork_count": 3,
        "instructor_feedback_count": 3,
        "pending_review_count": 0,
        "processing_count": 0,
    }
    return base | overrides


def contents(data: Dataset) -> dict[str, str]:
    return {str(i.id): i.content for i in data.items}


# 11월 3일·8일·15일 — 요청 예시 그대로 (표현은 다르지만 같은 실수)
ELLIPSE = [
    {"day": date(2026, 11, 3), "items": [(K.WEAKNESS, C.FORM, "컵 타원이 납작하다.")]},
    {
        "day": date(2026, 11, 8),
        "items": [(K.WEAKNESS, C.PROPORTION, "원통형 물체의 윗부분 비례가 어색하다.")],
    },
    {"day": date(2026, 11, 15), "items": [(K.FIX, C.FORM, "타원 형태를 다시 확인해라.")]},
]

# 11월 1일·10일·18일 — 명암 개선 예시
VALUE_IMPROVING = [
    {"day": date(2026, 11, 1), "items": [(K.WEAKNESS, C.VALUE, "명암 대비가 너무 약하다.")]},
    {"day": date(2026, 11, 10), "items": [(K.STRENGTH, C.VALUE, "명암이 지난번보다 좋아졌다.")]},
    {"day": date(2026, 11, 18), "items": [(K.STRENGTH, C.VALUE, "명암은 이제 안정적이다.")]},
]


# ------------------------------------------------------------------ 반복 실수


def test_repeated_mistake_groups_semantically_similar_feedback() -> None:
    data = build(ELLIPSE)
    insights = build_insights(data, min_artworks=3)
    assert insights["sufficient"] and insights["repeated_mistakes"] == ["FORM_PROPORTION"]
    form = tag_entry(insights, "FORM_PROPORTION")
    assert form["issue_artwork_count"] == 3
    assert form["last_issue_date"] == "2026-11-15"
    assert form["progress"] == "NEEDS_WORK"
    ellipse = form["themes"][0]
    assert (ellipse["code"], ellipse["artwork_count"]) == ("ELLIPSE", 3)
    assert len(form["issue_artwork_ids"]) == 3 and len(form["issue_item_ids"]) == 3


def test_unrelated_feedback_is_not_forced_into_one_theme() -> None:
    data = build(
        [
            {"day": date(2026, 11, 1), "items": [(K.WEAKNESS, C.FORM, "컵 타원이 납작하다.")]},
            {"day": date(2026, 11, 2), "items": [(K.WEAKNESS, C.FORM, "병 어깨선이 기울었다.")]},
            {"day": date(2026, 11, 3), "items": [(K.WEAKNESS, C.COLOR, "배경색이 탁하다.")]},
        ]
    )
    insights = build_insights(data, min_artworks=3)
    form = tag_entry(insights, "FORM_PROPORTION")
    assert form["issue_artwork_count"] == 2
    assert form["themes"] == []  # 타원은 1개 작품뿐 → 세부 주제로 묶지 않음
    assert "COLOR" not in insights["repeated_mistakes"]  # 1개 작품만


def test_uncategorized_issue_is_not_assigned_to_a_tag() -> None:
    data = build(
        [{"day": date(2026, 11, d), "items": [(K.FIX, None, "다시 해 봐.")]} for d in (1, 2, 3)]
    )
    insights = build_insights(data, min_artworks=3)
    assert insights["tags"] == [] and insights["repeated_mistakes"] == []


# ------------------------------------------------------------------ 강점·개선 추세


def test_improvement_trend_requires_issue_then_actual_praise() -> None:
    insights = build_insights(build(VALUE_IMPROVING), min_artworks=3)
    value = tag_entry(insights, "VALUE")
    assert value["progress"] == "IMPROVING"
    assert value["improvement_confirmed"] is True
    assert value["positive_since_last_issue"] == 2
    assert value["first_issue_date"] == "2026-11-01"
    assert insights["improving"] == ["VALUE"]
    assert [e["polarity"] for e in value["events"]] == ["NEG", "POS", "POS"]


def test_single_praise_after_issue_is_an_early_signal_only() -> None:
    insights = build_insights(build(VALUE_IMPROVING[:2] + ELLIPSE[:1]), min_artworks=3)
    value = tag_entry(insights, "VALUE")
    assert value["progress"] == "IMPROVING" and value["improvement_confirmed"] is False


def test_latest_issue_or_mixed_feedback_is_not_improvement() -> None:
    mixed = {
        "day": date(2026, 11, 20),
        "items": [
            (K.STRENGTH, C.VALUE, "명암은 좋아졌는데"),
            (K.WEAKNESS, C.VALUE, "반사광이 너무 밝다."),
        ],
    }
    specs = [*VALUE_IMPROVING, mixed]
    value = tag_entry(build_insights(build(specs), min_artworks=3), "VALUE")
    assert value["progress"] == "NEEDS_WORK"
    assert value["events"][-1]["polarity"] == "MIXED"


def test_strength_needs_real_positive_feedback_not_absence_of_issues() -> None:
    specs = [
        {
            "day": date(2026, 11, d),
            "items": [
                (K.STRENGTH, C.VALUE, "명암 표현이 안정적이다."),
                (K.WEAKNESS, C.COMPOSITION, "구도가 한쪽으로 쏠렸다."),
            ],
        }
        for d in (1, 5, 9)
    ]
    insights = build_insights(build(specs), min_artworks=3)
    assert insights["strengths"] == ["VALUE"]
    assert tag_entry(insights, "VALUE")["progress"] == "CONSISTENT_STRENGTH"
    # 색채는 언급이 없었다 → 강점도 약점도 아님 (태그 자체가 없음)
    assert all(t["tag"] != "COLOR" for t in insights["tags"])


def test_self_notes_and_peer_opinions_are_not_used() -> None:
    specs = [dict(s, source=FeedbackSource.SELF_NOTE) for s in ELLIPSE]
    insights = build_insights(build(specs), min_artworks=3)
    assert insights["analyzed_artwork_count"] == 0 and insights["tags"] == []


# ------------------------------------------------------------------ 데이터 부족 기준


def test_insufficient_data_withholds_trends_and_lists() -> None:
    insights = build_insights(build(VALUE_IMPROVING[:2]), min_artworks=3)
    assert not insights["sufficient"]
    assert insights["improving"] == insights["strengths"] == insights["repeated_mistakes"] == []
    summary = summarize_insights(insights)
    assert summary["sufficient"] is False and summary["improving"] == []


# ------------------------------------------------------------------ 홈 브리핑 문장


def test_briefing_for_new_user_does_not_invent_feedback() -> None:
    empty = build_insights(Dataset([], [], {}, []), min_artworks=3)
    out = compose_briefing(
        counts=counts(artwork_count=0, instructor_feedback_count=0),
        insights=empty,
        contents={},
        has_self_notes=False,
    )
    assert out["status"] == "NO_RECORDS" and out["headline"] == MSG_NO_RECORDS
    assert out["evidence_item_ids"] == [] and out["focus"] is None


def test_briefing_waits_for_confirmation_or_processing() -> None:
    empty = build_insights(Dataset([], [], {}, []), min_artworks=3)
    waiting = compose_briefing(
        counts=counts(instructor_feedback_count=0, pending_review_count=2),
        insights=empty,
        contents={},
        has_self_notes=False,
    )
    assert waiting["status"] == "NEEDS_CONFIRMATION" and "2건" in waiting["headline"]
    busy = compose_briefing(
        counts=counts(instructor_feedback_count=0, processing_count=1),
        insights=empty,
        contents={},
        has_self_notes=False,
    )
    assert busy["status"] == "PROCESSING"
    self_only = compose_briefing(
        counts=counts(instructor_feedback_count=0),
        insights=empty,
        contents={},
        has_self_notes=True,
    )
    assert self_only["status"] == "NO_FEEDBACK" and "자기 메모" in self_only["lines"][0]


def test_briefing_with_one_feedback_uses_only_that_feedback() -> None:
    data = build(ELLIPSE[:1])
    out = compose_briefing(
        counts=counts(artwork_count=1, instructor_feedback_count=1),
        insights=build_insights(data, min_artworks=3),
        contents=contents(data),
        has_self_notes=False,
    )
    assert out["status"] == "INSUFFICIENT_DATA"
    assert out["headline"] == "최근 첨삭에서 형태·비례에 대한 지적이 있었어요."
    assert out["focus"]["reason"] == "RECENT"
    assert MSG_INSUFFICIENT in out["lines"]
    assert len(out["evidence_item_ids"]) == 1


def test_briefing_with_enough_data_names_repeated_theme_and_quotes_real_fix() -> None:
    data = build(ELLIPSE + VALUE_IMPROVING)
    out = compose_briefing(
        counts=counts(artwork_count=6, instructor_feedback_count=6, pending_review_count=1),
        insights=build_insights(data, min_artworks=3),
        contents=contents(data),
        has_self_notes=False,
    )
    assert out["status"] == "READY"
    assert out["headline"] == "최근 타원·원통형 형태에 대한 첨삭이 3개 작품에서 반복되고 있어요."
    assert out["focus"]["theme_label"] == "타원·원통형 형태"
    # 개선 추세는 실제 긍정 첨삭이 있는 명암
    assert out["highlight"] == {
        "tag": "VALUE",
        "label": "명암",
        "kind": "IMPROVING",
        "artwork_count": 2,
    }
    assert "명암 부분은 이전 지적 이후 좋아졌다는 첨삭이 이어지고 있어요." in out["lines"]
    # 오늘의 연습은 강사의 실제 수정 지시 인용
    practice = contents(data)[out["practice_item_id"]]
    assert practice == "타원 형태를 다시 확인해라."
    assert any("“타원 형태를 다시 확인해라.”" in ln for ln in out["lines"])
    assert any("확정을 기다리는 첨삭이 1건" in ln for ln in out["lines"])
    # 근거 없는 수치(백분율·점수)를 만들지 않는다
    text = " ".join([out["headline"], *out["lines"]])
    assert "%" not in text and "점수" not in text
    # 모든 근거 ID는 실제 항목
    assert set(out["evidence_item_ids"]) <= set(contents(data))


def test_briefing_with_no_issues_highlights_strength_only() -> None:
    specs = [
        {"day": date(2026, 11, d), "items": [(K.STRENGTH, C.COMPOSITION, "구도가 안정적이다.")]}
        for d in (1, 5, 9)
    ]
    data = build(specs)
    out = compose_briefing(
        counts=counts(),
        insights=build_insights(data, min_artworks=3),
        contents=contents(data),
        has_self_notes=False,
    )
    assert out["status"] == "READY" and out["focus"] is None
    assert out["headline"] == "최근 첨삭에서 반복되는 지적은 없어요."
    assert out["lines"][0].startswith("구도 부분은 3개 작품에서 좋다는 첨삭을 받았어요.")
