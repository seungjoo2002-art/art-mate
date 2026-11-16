"""v1.0 학생 성장 분석: 9개 태그 반복 실수·강점, 비교 맥락, 최근 연습 과제 (규칙 기반, AI 없음)."""

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from app.models.enums import (
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    FeedbackItemKind,
    FeedbackSource,
    PracticalType,
    WeaknessCategory,
)
from app.services.growth_analytics import ArtworkFact, Dataset, FeedbackFact, ItemFact, analyze

C = WeaknessCategory
K = FeedbackItemKind
BASE = date(2026, 9, 1)


def build(specs: list[dict], *, source: FeedbackSource = FeedbackSource.INSTRUCTOR) -> Dataset:
    """specs[i] = {weak: set, strong: set, tips: [category|None], extra_items: int, mock: bool}."""
    artworks, feedbacks, items = [], [], []
    categories: dict[uuid.UUID, set[WeaknessCategory]] = {}
    for i, spec in enumerate(specs):
        aid, fid = uuid.uuid4(), uuid.uuid4()
        work_date = BASE + timedelta(days=i * 7)
        stamp = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(days=i * 7)
        artworks.append(
            ArtworkFact(
                id=aid,
                title=f"작품 {i}",
                work_date=work_date,
                created_at=stamp,
                updated_at=stamp,
                work_status=ArtworkWorkStatus.COMPLETED,
                completed_at=stamp,
                practical_type=spec.get("type", PracticalType.DRAWING),
                work_category=ArtworkWorkCategory.MOCK_EXAM if spec.get("mock") else None,
            )
        )
        feedbacks.append(FeedbackFact(fid, aid, stamp, 1, source))
        categories[fid] = set(spec.get("weak", set()))
        for c in spec.get("weak", set()):
            items.append(ItemFact(uuid.uuid4(), fid, aid, K.WEAKNESS, c, work_date, stamp))
        for c in spec.get("strong", set()):
            items.append(ItemFact(uuid.uuid4(), fid, aid, K.STRENGTH, c, work_date, stamp))
        for c in spec.get("tips", []):
            items.append(ItemFact(uuid.uuid4(), fid, aid, K.NEXT_TIP, c, work_date, stamp))
        for _ in range(spec.get("extra_items", 0)):
            items.append(ItemFact(uuid.uuid4(), fid, aid, K.FIX, None, work_date, stamp))
    return Dataset(artworks, feedbacks, categories, items)


def run(data: Dataset, window: int = 2) -> dict:
    return analyze(data, min_artworks=3, recent_window=window)


def tag(metrics: dict, code: str) -> dict:
    return next(t for t in metrics["tags"] if t["tag"] == code)


def test_form_and_proportion_merge_without_double_counting() -> None:
    # 작품 0: 형태+비례 둘 다 → 형태·비례 태그는 작품 1개로 센다
    m = run(
        build([{"weak": {C.FORM, C.PROPORTION}}, {"weak": {C.PROPORTION}}, {"weak": {C.VALUE}}])
    )
    fp = tag(m, "FORM_PROPORTION")
    assert fp["weakness_artwork_count"] == 2
    assert fp["categories"] == ["FORM", "PROPORTION"]
    assert fp["repeated"] is True
    assert m["top_tags"] == ["FORM_PROPORTION"]
    # 기존 11개 카테고리 통계는 그대로
    assert {w["category"] for w in m["weaknesses"]} == {"FORM", "PROPORTION", "VALUE"}
    # 텍스처·묘사도 한 태그로
    m2 = run(build([{"weak": {C.TEXTURE}}, {"weak": {C.RENDERING}}, {}]))
    assert tag(m2, "TEXTURE_EXPRESSION")["weakness_artwork_count"] == 2


def test_strengths_are_counted_per_tag_separately_from_weaknesses() -> None:
    m = run(
        build([{"strong": {C.COMPOSITION}}, {"strong": {C.COMPOSITION}, "weak": {C.VALUE}}, {}])
    )
    comp = tag(m, "COMPOSITION")
    assert (comp["strength_artwork_count"], comp["weakness_artwork_count"]) == (2, 0)
    assert comp["trend"] == "INSUFFICIENT_DATA" and comp["repeated"] is False
    assert tag(m, "VALUE")["strength_artwork_count"] == 0


def test_recent_vs_previous_trend_and_insufficient_data() -> None:
    # 4작품, 최근 2 / 이전 2: 명암은 이전 2개 모두 → 최근 0개 (LESS_FREQUENT, 개선 단정 아님)
    specs = [{"weak": {C.VALUE}}, {"weak": {C.VALUE}}, {"weak": {C.COLOR}}, {"weak": {C.COLOR}}]
    m = run(build(specs))
    value, color = tag(m, "VALUE"), tag(m, "COLOR")
    assert value["trend"] == "LESS_FREQUENT" and value["recent"]["ratio"] == 0
    assert value["previous"]["ratio"] == 1.0
    assert color["trend"] == "MORE_FREQUENT"
    # 비교 구간이 부족하면 추세 없음
    few = run(build(specs[:3]))
    assert tag(few, "VALUE")["trend"] == "INSUFFICIENT_DATA"
    assert tag(few, "VALUE")["previous"] is None
    assert few["comparison_context"] is None


def test_comparison_context_warns_about_feedback_volume_and_conditions() -> None:
    specs = [
        {"weak": {C.VALUE}, "extra_items": 6},
        {"weak": {C.VALUE}, "extra_items": 6},
        {"weak": {C.COLOR}, "mock": True, "type": PracticalType.WATERCOLOR},
        {"weak": {C.COLOR}, "mock": True, "type": PracticalType.WATERCOLOR},
    ]
    ctx = run(build(specs))["comparison_context"]
    assert ctx["previous_items_per_feedback"] == 7.0
    assert ctx["recent_items_per_feedback"] == 1.0
    assert (ctx["previous_mock_exam_ratio"], ctx["recent_mock_exam_ratio"]) == (0.0, 1.0)
    text = " ".join(ctx["cautions"])
    assert "항목 수가 적어요" in text and "모의시험 비중" in text and "실기 유형" in text
    # 조건이 같으면 주의 문구 없음
    same = run(build([{"weak": {C.VALUE}}] * 4))["comparison_context"]
    assert same["cautions"] == []


def test_timeline_has_tag_counts_and_feedback_counts() -> None:
    m = analyze(
        build([{"weak": {C.FORM, C.PROPORTION}}, {"weak": {C.VALUE}}, {}]),
        min_artworks=3,
        recent_window=2,
        bucket="month",
    )
    (bucket,) = m["timeline"]
    assert bucket["feedback_count"] == 3
    assert bucket["tags"] == {"FORM_PROPORTION": 1, "VALUE": 1}


def test_practice_tips_recent_first_and_linked_to_repeated_mistakes() -> None:
    specs = [
        {"weak": {C.PROPORTION}, "tips": [C.FORM]},
        {"weak": {C.PROPORTION}, "tips": [None]},
        {"weak": {C.COLOR}, "tips": [C.VALUE]},
    ]
    tips = run(build(specs))["practice_tips"]
    assert [t["tag"] for t in tips] == ["VALUE", "OTHER", "FORM_PROPORTION"]  # 최신순
    assert [t["related_repeated"] for t in tips] == [False, False, True]


def test_self_notes_do_not_feed_tags_or_tips() -> None:
    data = build([{"weak": {C.VALUE}, "tips": [C.VALUE]}] * 3, source=FeedbackSource.SELF_NOTE)
    m = run(data)
    assert m["tags"] == [] and m["practice_tips"] == [] and m["status"] == "INSUFFICIENT_DATA"


def test_tags_only_from_artworks_in_scope() -> None:
    data = build([{"weak": {C.VALUE}}, {"weak": {C.VALUE}}, {}])
    # 범위 밖 작품(삭제 등)의 첨삭은 무시
    stray = replace(data.feedbacks[0], id=uuid.uuid4(), artwork_id=uuid.uuid4())
    data.feedbacks.append(stray)
    data.categories[stray.id] = {C.COLOR}
    assert [t["tag"] for t in run(data)["tags"]] == ["VALUE"]
