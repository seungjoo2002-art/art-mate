"""반복 약점 통계·성장 AI 검증 단위 테스트 (DB·외부 호출 없음)."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from app.models.enums import (
    ArtworkWorkStatus,
    FeedbackItemKind,
    PracticalType,
    WeaknessCategory,
)
from app.services.growth_ai import (
    TEMPLATES,
    InvalidGrowthOutput,
    has_forbidden_claim,
    parse_narrative,
    parse_recommendations,
    pick_template,
)
from app.services.growth_analytics import (
    ArtworkFact,
    Dataset,
    FeedbackFact,
    ItemFact,
    analyze,
    fingerprint,
)

C = WeaknessCategory
BASE = date(2026, 9, 1)


def _dataset(per_artwork: list[list[set[WeaknessCategory]]]) -> Dataset:
    """per_artwork[i] = 그 작품의 승인 첨삭별 카테고리 목록. 작품 i의 작업일 = BASE + i일."""
    artworks, feedbacks, items = [], [], []
    categories: dict[uuid.UUID, set[WeaknessCategory]] = {}
    for i, feedback_sets in enumerate(per_artwork):
        artwork_id = uuid.uuid4()
        work_date = BASE + timedelta(days=i)
        stamp = datetime(2026, 9, 1, tzinfo=UTC) + timedelta(days=i)
        artworks.append(
            ArtworkFact(
                id=artwork_id,
                title=f"작품 {i}",
                work_date=work_date,
                created_at=stamp,
                updated_at=stamp,
                work_status=ArtworkWorkStatus.COMPLETED if i % 2 else ArtworkWorkStatus.IN_PROGRESS,
                completed_at=None,
                practical_type=PracticalType.DRAWING,
                work_category=None,
            )
        )
        for cats in feedback_sets:
            fid = uuid.uuid4()
            feedbacks.append(
                FeedbackFact(id=fid, artwork_id=artwork_id, approved_at=stamp, version=1)
            )
            categories[fid] = set(cats)
            for c in cats:
                for kind in (FeedbackItemKind.WEAKNESS, FeedbackItemKind.FIX):
                    items.append(ItemFact(uuid.uuid4(), fid, artwork_id, kind, c, work_date, stamp))
            items.append(
                ItemFact(
                    uuid.uuid4(),
                    fid,
                    artwork_id,
                    FeedbackItemKind.STRENGTH,
                    C.COMPOSITION,
                    work_date,
                    stamp,
                )
            )
    return Dataset(artworks, feedbacks, categories, items)


def _by(metrics: dict, category: WeaknessCategory) -> dict:
    return next(w for w in metrics["weaknesses"] if w["category"] == category.value)


def test_spec_example_proportion_is_top_repeated_weakness() -> None:
    data = _dataset(
        [
            [{C.PROPORTION, C.VALUE}],
            [{C.PROPORTION, C.COMPOSITION}],
            [{C.PROPORTION, C.VALUE}],
            [{C.COLOR, C.PROPORTION}],
        ]
    )
    metrics = analyze(data, min_artworks=3, recent_window=2)
    assert metrics["status"] == "READY"
    assert metrics["top_weaknesses"] == [
        "PROPORTION",
        "VALUE",
    ]  # 1개 작품뿐인 구도·색채는 반복 아님
    proportion = _by(metrics, C.PROPORTION)
    assert (proportion["artwork_count"], proportion["mention_count"]) == (4, 4)
    assert proportion["artwork_ratio"] == 1.0
    assert _by(metrics, C.COLOR)["repeated"] is False
    assert metrics["totals"] == {
        "artwork_count": 4,
        "completed_artwork_count": 2,
        "approved_feedback_count": 4,
        "analyzed_artwork_count": 4,
    }
    # 근거는 작품당 1개, 부족한 점(WEAKNESS) 우선, 최대 3개
    evidence = proportion["evidence"]
    assert len(evidence) == 3 and len({e["artwork_id"] for e in evidence}) == 3


def test_same_category_in_one_artwork_counts_once() -> None:
    """한 작품에 승인 첨삭 2개가 모두 '비례'여도 작품 수는 1, 첨삭 횟수는 2."""
    data = _dataset([[{C.PROPORTION}, {C.PROPORTION, C.VALUE}], [{C.VALUE}], [{C.FORM}]])
    metrics = analyze(data, min_artworks=3, recent_window=2)
    proportion = _by(metrics, C.PROPORTION)
    assert (proportion["artwork_count"], proportion["mention_count"]) == (1, 2)
    assert proportion["repeated"] is False
    assert metrics["top_weaknesses"] == ["VALUE"]
    assert metrics["totals"]["analyzed_artwork_count"] == 3


def test_insufficient_data_and_confidence() -> None:
    few = analyze(_dataset([[{C.VALUE}], [{C.VALUE}]]), min_artworks=3, recent_window=2)
    assert few["status"] == "INSUFFICIENT_DATA" and few["message"]
    assert few["confidence"] == "LOW"
    # 첨삭 없는 작품은 분석 대상이 아니다
    empty = analyze(_dataset([[], [], []]), min_artworks=3, recent_window=2)
    assert empty["status"] == "INSUFFICIENT_DATA"
    assert empty["totals"]["artwork_count"] == 3 and empty["totals"]["analyzed_artwork_count"] == 0
    many = analyze(_dataset([[{C.VALUE}]] * 8), min_artworks=3, recent_window=2)
    assert many["confidence"] == "HIGH"


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        # 이전 2개에는 없고 최근 2개에 모두 있음
        ([[{C.FORM}], [{C.FORM}], [{C.VALUE}], [{C.VALUE}]], "MORE_FREQUENT"),
        ([[{C.VALUE}], [{C.VALUE}], [{C.FORM}], [{C.FORM}]], "LESS_FREQUENT"),
        ([[{C.VALUE}], [{C.FORM}], [{C.VALUE}], [{C.FORM}]], "SIMILAR"),
        # 비교 구간이 모자라면 판단하지 않는다
        ([[{C.VALUE}], [{C.VALUE}], [{C.VALUE}]], "INSUFFICIENT_DATA"),
    ],
)
def test_trend(history: list, expected: str) -> None:
    metrics = analyze(_dataset(history), min_artworks=3, recent_window=2)
    assert _by(metrics, C.VALUE)["trend"] == expected


def test_timeline_buckets_strengths_goals_and_fingerprint() -> None:
    data = _dataset([[{C.VALUE}], [{C.VALUE, C.FORM}], [{C.FORM}]])
    metrics = analyze(data, min_artworks=3, recent_window=2, bucket="week")
    assert sum(b["analyzed_artwork_count"] for b in metrics["timeline"]) == 3
    assert metrics["strengths"][0]["category"] == "COMPOSITION"
    assert metrics["strengths"][0]["artwork_count"] == 3
    goals = metrics["next_goals"]
    assert [g["category"] for g in goals] == metrics["top_weaknesses"]
    assert all(g["based_on_item_id"] for g in goals)
    assert "%" not in json.dumps(metrics["notes"], ensure_ascii=False)

    before = fingerprint(data)
    data.feedbacks[0] = FeedbackFact(
        data.feedbacks[0].id, data.feedbacks[0].artwork_id, data.feedbacks[0].approved_at, 2
    )
    assert fingerprint(data) != before  # 첨삭 수정(버전) → 리포트 무효


# ----------------------------------------------------------------------------- AI 출력 검증


@pytest.mark.parametrize(
    ("text", "forbidden"),
    [
        ("실력이 30% 향상되었다", True),
        ("합격 가능성이 높아졌다", True),
        ("명암 점수 80점", True),
        ("두 배 좋아졌다", True),
        ("상위 10% 수준", True),
        ("비례를 스케치 단계에서 점검한다", False),
        ("명암을 3단계로 나눠 본다", False),
        ("그 부분을 2배 크기로 확대해 그린다", False),
        ("속도가 3배 빨라졌다", True),
        ("1점·2점 투시로 상자를 그린다", False),
    ],
)
def test_forbidden_claims(text: str, forbidden: bool) -> None:
    assert has_forbidden_claim(text) is forbidden


def _narrative(**overrides) -> str:  # type: ignore[no-untyped-def]
    data = {
        "overview": "최근 첨삭에서 비례가 여러 번 언급되었다.",
        "strengths_comment": "구도는 강사가 자주 긍정적으로 언급했다.",
        "improvement_comment": "기준선을 먼저 잡는 연습이 필요하다는 지적이 반복되었다.",
        "next_goals": [{"goal": "스케치 단계에서 기준선 먼저 긋기", "evidence": [1, 9]}],
    } | overrides
    return json.dumps(data, ensure_ascii=False)


def test_parse_narrative() -> None:
    output = parse_narrative(_narrative(), evidence_count=2)
    assert output.next_goals[0].evidence == [1]  # 없는 근거 번호 제거
    no_evidence = parse_narrative(
        _narrative(next_goals=[{"goal": "x", "evidence": [5]}]), evidence_count=2
    )
    assert no_evidence.next_goals == []
    for bad in (
        "not json",
        _narrative(overview="실력이 30% 향상되었다."),
        _narrative(improvement_comment="이대로면 합격할 수 있다."),
        json.dumps({"overview": "x"}),
    ):
        with pytest.raises(InvalidGrowthOutput):
            parse_narrative(bad, evidence_count=2)


def _rec(category: str, evidence: list[int], **overrides) -> dict:  # type: ignore[no-untyped-def]
    return {
        "category": category,
        "title": "기준선 비율 비교",
        "description": "기준 길이를 정해 비율을 비교한다.",
        "steps": ["기준선을 긋는다", "비율을 비교한다"],
        "estimated_minutes": 40,
        "difficulty": "EASY",
        "reason": "비례 지적이 반복되었다.",
        "evidence": evidence,
    } | overrides


def test_parse_recommendations_requires_matching_evidence() -> None:
    evidence = [
        {"item_id": "a", "category": "PROPORTION", "kind": "FIX", "content": "기준선"},
        {"item_id": "b", "category": "VALUE", "kind": "WEAKNESS", "content": "명암"},
    ]
    raw = json.dumps(
        {
            "recommendations": [
                _rec("PROPORTION", [1]),
                _rec("PROPORTION", [1]),  # 같은 카테고리 중복
                _rec("VALUE", [1]),  # 근거가 다른 카테고리 문장 → 근거 없음
                _rec("COLOR", [2]),  # 요청하지 않은 카테고리
                _rec("VALUE", [2], reason="이 과제로 실력이 2배 오른다"),  # 금지 표현
            ]
        },
        ensure_ascii=False,
    )
    kept, dropped = parse_recommendations(raw, evidence, ["PROPORTION", "VALUE"])
    assert [r.category.value for r in kept] == ["PROPORTION"]
    assert dropped == 4
    with pytest.raises(InvalidGrowthOutput):
        parse_recommendations(
            json.dumps({"recommendations": [_rec("VALUE", [1])]}), evidence, ["VALUE"]
        )
    with pytest.raises(InvalidGrowthOutput):
        parse_recommendations("[]", evidence, ["VALUE"])


def test_every_category_has_a_template() -> None:
    assert set(TEMPLATES) == set(WeaknessCategory)
    for category in WeaknessCategory:
        template = pick_template(category, PracticalType.DRAWING)
        assert template.steps and 5 <= template.minutes <= 480
        assert not has_forbidden_claim(
            template.title + template.description + "".join(template.steps)
        )
