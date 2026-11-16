"""반복 약점·성장 통계 (규칙 기반, 순수 함수). AI는 이 결과를 설명만 하고 숫자를 만들지 않는다.

분석 단위와 규칙
- 입력: 범위·기간 안의 (삭제되지 않은) 작품과 그 작품의 **승인된(APPROVED) 첨삭**만.
  초안·반려·대체된
  첨삭은 쓰지 않는다. 녹음·작품을 삭제하면 첨삭도 삭제되므로 자동으로 빠진다.
- 작품 단위 집계: 한 작품에 첨삭이 여러 개이거나 같은 카테고리가 여러 번 나와도 그 작품은 1번만 센다
  (`artwork_count`). 첨삭 단위 횟수는 `mention_count`로 따로 보여 준다 (feedback_categories는
  첨삭당 카테고리 1행이므로 첨삭 안에서는 이미 중복이 없다).
- 분석 대상 작품(analyzed) = 승인된 첨삭이 1개 이상 있는 작품. 비율의 분모다.
- 반복 약점 = 2개 이상 작품에서 지적된 카테고리. 순위: 작품 수 → 최근 구간 비율 → 첨삭 횟수.
- 최근 변화: 분석 대상 작품을 작업일 순으로 정렬해
  최근 N개와 그 이전 N개의 작품 단위 비율을 비교한다.
  두 구간이 모두 N개일 때만 비교하고, 차이가 0.2 미만이면 비슷함.
- 신뢰도: 분석 대상 작품 수 기준 (min 미만 = 리포트 INSUFFICIENT_DATA, <8 = LOW/MEDIUM, ≥8 = HIGH).

v0.9 (기능명세서 V2 F-7)
- 출처 구분: 반복 약점·추세·근거는 **강사 첨삭(INSTRUCTOR)** 승인본만 쓴다.
  자기 메모(SELF_NOTE)·다른 학생 의견(PEER)은 `unverified_mentions`에 참고로만 따로 센다
  (같은 신뢰도로 섞지 않음).
- 학습 시간: 작품의 실제 소요 시간(분)·제한 시간으로 기간별 학습 시간·모의시험 시간 초과를 집계한다.
  시간 기록이 없는 작품은 시간 통계에서 빠진다 (0분으로 세지 않음).
- 데이터가 부족하면 `guidance`로 다음에 무엇을 기록하면 되는지 안내한다.

해석 원칙 (응답 notes로 함께 내려 보낸다)
- 지적이 줄어든 것은 실력 향상의 증거가 아니다 (첨삭에서 언급되지 않았을 수 있음).
- 강사마다 첨삭 방식이 달라 지표가 달라질 수 있다.
- 이 통계는 첨삭 기록 집계이며 AI가 실기 능력을 채점한 것이 아니다.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

from app.models.enums import (
    CATEGORY_TAG,
    FEEDBACK_TAG_LABELS,
    WEAKNESS_CATEGORY_LABELS,
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    Confidence,
    FeedbackItemKind,
    FeedbackSource,
    FeedbackTag,
    PracticalType,
    ReportStatus,
    TrendDirection,
    WeaknessCategory,
)

ANALYSIS_VERSION = "growth-v2"
TREND_THRESHOLD = 0.2
HIGH_CONFIDENCE_ARTWORKS = 8
MAX_EVIDENCE = 3
# v1.0 학생 성장 분석
MAX_PRACTICE_TIPS = 8
VOLUME_CHANGE = 0.3  # 첨삭 1건당 항목 수가 이만큼(30%) 넘게 달라지면 비교 주의 안내
MIX_CHANGE = 0.3  # 모의시험 비중이 이만큼 달라지면 비교 주의 안내

NOTES = [
    "이 통계는 강사가 승인한 첨삭 기록을 집계한 것이며, AI가 실기 능력을 채점한 결과가 아닙니다.",
    "첨삭에서 언급되지 않은 약점이 개선되었다는 뜻은 아닙니다.",
    "강사마다 첨삭 방식과 표현이 달라 지적 빈도가 달라질 수 있습니다.",
    "자기 메모와 다른 학생 의견은 반복 약점 통계에 넣지 않고 참고로만 보여 줍니다.",
    "과제를 완료했다는 것과 실력이 향상되었다는 것은 같은 뜻이 아닙니다.",
]
INSUFFICIENT_MESSAGE = "분석에 필요한 기록이 부족합니다."

Bucket = Literal["week", "month"]


@dataclass(frozen=True)
class ArtworkFact:
    id: uuid.UUID
    title: str
    work_date: date
    created_at: datetime
    updated_at: datetime
    work_status: ArtworkWorkStatus
    completed_at: datetime | None
    practical_type: PracticalType | None
    work_category: ArtworkWorkCategory | None
    # v0.9 시간 기록 (분)
    actual_minutes: int | None = None
    time_limit_minutes: int | None = None


@dataclass(frozen=True)
class FeedbackFact:
    id: uuid.UUID
    artwork_id: uuid.UUID
    approved_at: datetime
    version: int
    # v0.9 출처. INSTRUCTOR만 반복 약점 통계에 집계
    source: FeedbackSource = FeedbackSource.INSTRUCTOR


@dataclass(frozen=True)
class ItemFact:
    id: uuid.UUID
    feedback_id: uuid.UUID
    artwork_id: uuid.UUID
    kind: FeedbackItemKind
    category: WeaknessCategory | None
    work_date: date
    approved_at: datetime


@dataclass
class Dataset:
    artworks: list[ArtworkFact]
    feedbacks: list[FeedbackFact]
    categories: dict[uuid.UUID, set[WeaknessCategory]]  # feedback_id → 카테고리
    items: list[ItemFact] = field(default_factory=list)


def confidence_for(analyzed: int) -> Confidence:
    if analyzed < 3:
        return Confidence.LOW
    if analyzed < HIGH_CONFIDENCE_ARTWORKS:
        return Confidence.MEDIUM
    return Confidence.HIGH


def fingerprint(dataset: Dataset) -> str:
    """사용한 데이터의 지문. 첨삭 승인·수정, 작품 수정·삭제·완료가 바뀌면 달라진다."""
    parts = sorted(f"f:{f.id}:{f.version}" for f in dataset.feedbacks) + sorted(
        f"a:{a.id}:{a.updated_at.isoformat()}:{a.work_status.value}" for a in dataset.artworks
    )
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _bucket_start(day: date, bucket: Bucket) -> date:
    if bucket == "week":
        return day - timedelta(days=day.weekday())
    return day.replace(day=1)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def _window(order: list[uuid.UUID], present: set[uuid.UUID]) -> dict[str, Any]:
    hits = sum(1 for a in order if a in present)
    return {
        "analyzed_artwork_count": len(order),
        "artwork_count": hits,
        "ratio": _ratio(hits, len(order)),
    }


def analyze(
    dataset: Dataset,
    *,
    min_artworks: int,
    recent_window: int,
    bucket: Bucket = "month",
) -> dict[str, Any]:
    artworks = {a.id: a for a in dataset.artworks}
    in_scope = [f for f in dataset.feedbacks if f.artwork_id in artworks]
    # 반복 약점·추세·근거는 강사 첨삭만 (자기 메모·다른 학생 의견은 참고 통계로 분리)
    feedbacks = [f for f in in_scope if f.source == FeedbackSource.INSTRUCTOR]
    verified_ids = {f.id for f in feedbacks}
    by_artwork: dict[uuid.UUID, list[FeedbackFact]] = defaultdict(list)
    for f in feedbacks:
        by_artwork[f.artwork_id].append(f)

    # 분석 대상 작품: 작업일 → 첫 승인 시각 순 (오래된 것 먼저)
    analyzed = sorted(
        by_artwork,
        key=lambda a: (artworks[a].work_date, min(f.approved_at for f in by_artwork[a]), str(a)),
    )
    analyzed_count = len(analyzed)

    # 카테고리 → 지적된 작품 집합 / 첨삭 횟수
    category_artworks: dict[WeaknessCategory, set[uuid.UUID]] = defaultdict(set)
    mentions: Counter[WeaknessCategory] = Counter()
    for f in feedbacks:
        for category in dataset.categories.get(f.id, set()):
            category_artworks[category].add(f.artwork_id)
            mentions[category] += 1

    recent = analyzed[-recent_window:]
    previous = (
        analyzed[-2 * recent_window : -recent_window] if analyzed_count > recent_window else []
    )
    comparable = len(recent) == recent_window and len(previous) == recent_window

    items_by_category: dict[WeaknessCategory, list[ItemFact]] = defaultdict(list)
    strength_items: list[ItemFact] = []
    for item in sorted(dataset.items, key=lambda i: (i.work_date, i.approved_at), reverse=True):
        if item.artwork_id not in artworks or item.feedback_id not in verified_ids:
            continue
        if item.kind == FeedbackItemKind.STRENGTH:
            strength_items.append(item)
        elif item.category is not None:
            items_by_category[item.category].append(item)

    weaknesses = []
    for category, present in category_artworks.items():
        recent_stats = _window(recent, present)
        previous_stats = _window(previous, present)
        if comparable:
            diff = (recent_stats["ratio"] or 0) - (previous_stats["ratio"] or 0)
            trend = (
                TrendDirection.SIMILAR
                if abs(diff) < TREND_THRESHOLD
                else TrendDirection.MORE_FREQUENT
                if diff > 0
                else TrendDirection.LESS_FREQUENT
            )
        else:
            trend = TrendDirection.INSUFFICIENT_DATA
        evidence_items = items_by_category.get(category, [])
        # FIX(수정 지시)·WEAKNESS 우선, 작품당 1개
        seen: set[uuid.UUID] = set()
        evidence = []
        for item in sorted(
            evidence_items,
            key=lambda i: (i.kind != FeedbackItemKind.WEAKNESS, -i.work_date.toordinal()),
        ):
            if item.artwork_id in seen:
                continue
            seen.add(item.artwork_id)
            evidence.append(
                {
                    "item_id": str(item.id),
                    "feedback_id": str(item.feedback_id),
                    "artwork_id": str(item.artwork_id),
                }
            )
            if len(evidence) == MAX_EVIDENCE:
                break
        weaknesses.append(
            {
                "category": category.value,
                "label": WEAKNESS_CATEGORY_LABELS[category],
                "mention_count": mentions[category],
                "artwork_count": len(present),
                "artwork_ratio": _ratio(len(present), analyzed_count),
                "recent": recent_stats,
                "previous": previous_stats if comparable else None,
                "trend": trend.value,
                "repeated": len(present) >= 2,
                "last_seen_work_date": max(artworks[a].work_date for a in present).isoformat(),
                "evidence": evidence,
            }
        )
    weaknesses.sort(
        key=lambda w: (
            -w["artwork_count"],
            -(w["recent"]["ratio"] or 0),
            -w["mention_count"],
            w["category"],
        )
    )
    top = [w["category"] for w in weaknesses if w["repeated"]][:3]

    # 잘한 점: 승인된 STRENGTH 항목 (카테고리별 작품 수)
    strength_artworks: dict[str | None, set[uuid.UUID]] = defaultdict(set)
    for item in strength_items:
        strength_artworks[item.category.value if item.category else None].add(item.artwork_id)
    strengths = sorted(
        (
            {
                "category": key,
                "label": WEAKNESS_CATEGORY_LABELS[WeaknessCategory(key)] if key else "기타",
                "artwork_count": len(ids),
                "evidence": [
                    {
                        "item_id": str(i.id),
                        "feedback_id": str(i.feedback_id),
                        "artwork_id": str(i.artwork_id),
                    }
                    for i in strength_items
                    if (i.category.value if i.category else None) == key
                ][:MAX_EVIDENCE],
            }
            for key, ids in strength_artworks.items()
        ),
        key=lambda s: (-s["artwork_count"], s["category"] or "~"),
    )

    # 기간별 출현: 버킷(주/월)마다 분석 대상 작품 수와 카테고리별 작품 수
    buckets: dict[date, dict[str, Any]] = {}
    for artwork_id in analyzed:
        start = _bucket_start(artworks[artwork_id].work_date, bucket)
        entry = buckets.setdefault(start, {"analyzed": set(), "categories": defaultdict(set)})
        entry["analyzed"].add(artwork_id)
    for category, present in category_artworks.items():
        for artwork_id in present:
            start = _bucket_start(artworks[artwork_id].work_date, bucket)
            buckets[start]["categories"][category.value].add(artwork_id)
            # v1.0 9개 태그 기준 (한 작품에 형태·비례가 함께 있어도 1번)
            tag_sets = buckets[start].setdefault("tags", defaultdict(set))
            tag_sets[CATEGORY_TAG[category].value].add(artwork_id)
    for f in feedbacks:
        start = _bucket_start(artworks[f.artwork_id].work_date, bucket)
        buckets[start]["feedback_count"] = buckets[start].get("feedback_count", 0) + 1
    timeline = [
        {
            "bucket_start": start.isoformat(),
            "analyzed_artwork_count": len(entry["analyzed"]),
            "categories": {c: len(ids) for c, ids in sorted(entry["categories"].items())},
            "tags": {t: len(ids) for t, ids in sorted(entry.get("tags", {}).items())},
            "feedback_count": entry.get("feedback_count", 0),
        }
        for start, entry in sorted(buckets.items())
    ]

    # 다음 학습 목표 (규칙): 반복 약점별 최근 수정 지시를 근거로
    next_goals = []
    for category_code in top:
        category = WeaknessCategory(category_code)
        fix = next(
            (i for i in items_by_category.get(category, []) if i.kind == FeedbackItemKind.FIX), None
        )
        next_goals.append(
            {
                "category": category_code,
                "goal": (
                    f"다음 작품에서 '{WEAKNESS_CATEGORY_LABELS[category]}'을(를) "
                    "스케치 단계부터 의식적으로 점검하기"
                ),
                "based_on_item_id": str(fix.id) if fix else None,
            }
        )

    # v1.0 9개 태그 기준 (기존 11개 카테고리 통계는 그대로)
    tags, top_tags = tag_stats(
        analyzed, artworks, category_artworks, strength_items, recent, previous, comparable
    )
    verified_items = [
        i for i in dataset.items if i.artwork_id in artworks and i.feedback_id in verified_ids
    ]
    practice_tips = recent_practice_tips(verified_items, tags)

    practical = Counter(
        a.practical_type.value if a.practical_type else None for a in artworks.values()
    )
    purpose = Counter(a.work_category.value if a.work_category else None for a in artworks.values())
    status = (
        ReportStatus.READY if analyzed_count >= min_artworks else ReportStatus.INSUFFICIENT_DATA
    )
    return {
        "analysis_version": ANALYSIS_VERSION,
        "status": status.value,
        "message": INSUFFICIENT_MESSAGE if status == ReportStatus.INSUFFICIENT_DATA else None,
        "required_artwork_count": min_artworks,
        "confidence": confidence_for(analyzed_count).value,
        "recent_window": recent_window,
        "totals": {
            "artwork_count": len(artworks),
            "completed_artwork_count": sum(
                1 for a in artworks.values() if a.work_status == ArtworkWorkStatus.COMPLETED
            ),
            "approved_feedback_count": len(feedbacks),
            "analyzed_artwork_count": analyzed_count,
        },
        "practical_type_distribution": [
            {"practical_type": k, "artwork_count": v}
            for k, v in sorted(practical.items(), key=lambda kv: (-kv[1], kv[0] or "~"))
        ],
        "work_category_distribution": [
            {"work_category": k, "artwork_count": v}
            for k, v in sorted(purpose.items(), key=lambda kv: (-kv[1], kv[0] or "~"))
        ],
        "weaknesses": weaknesses,
        "top_weaknesses": top,
        # v1.0 9개 태그 기준 반복 실수·강점, 비교 맥락, 최근 연습 과제
        "tags": tags,
        "top_tags": top_tags,
        "comparison_context": comparison_context(
            feedbacks, verified_items, recent, previous, artworks, comparable
        ),
        "practice_tips": practice_tips,
        "strengths": strengths,
        "timeline_bucket": bucket,
        "timeline": timeline,
        "next_goals": next_goals,
        "analyzed_artwork_ids": [str(a) for a in analyzed],
        "time_stats": time_stats(list(artworks.values())),
        "activity": activity(list(artworks.values()), bucket),
        "source_breakdown": {
            s.value: sum(1 for f in in_scope if f.source == s) for s in FeedbackSource
        },
        "unverified_mentions": unverified_mentions(in_scope, dataset.categories),
        "guidance": guidance(
            analyzed_count, min_artworks, list(artworks.values()), in_scope, status
        ),
        "notes": NOTES,
    }


# ---------------------------------------------------------------- v1.0 9개 태그·비교 맥락·연습 과제


def _trend(recent: dict[str, Any], previous: dict[str, Any], comparable: bool) -> TrendDirection:
    if not comparable:
        return TrendDirection.INSUFFICIENT_DATA
    diff = (recent["ratio"] or 0) - (previous["ratio"] or 0)
    if abs(diff) < TREND_THRESHOLD:
        return TrendDirection.SIMILAR
    return TrendDirection.MORE_FREQUENT if diff > 0 else TrendDirection.LESS_FREQUENT


def tag_stats(
    analyzed: list[uuid.UUID],
    artworks: dict[uuid.UUID, ArtworkFact],
    category_artworks: dict[WeaknessCategory, set[uuid.UUID]],
    strength_items: list[ItemFact],
    recent: list[uuid.UUID],
    previous: list[uuid.UUID],
    comparable: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    """9개 태그별 지적(개선할 점)·강점 작품 수와 최근/이전 비교. 작품당 태그마다 1번만 센다."""
    weak: dict[FeedbackTag, set[uuid.UUID]] = defaultdict(set)
    strong: dict[FeedbackTag, set[uuid.UUID]] = defaultdict(set)
    members: dict[FeedbackTag, set[WeaknessCategory]] = defaultdict(set)
    for category, present in category_artworks.items():
        tag = CATEGORY_TAG[category]
        weak[tag] |= present
        members[tag].add(category)
    for item in strength_items:
        category = item.category or WeaknessCategory.OTHER
        tag = CATEGORY_TAG[category]
        strong[tag].add(item.artwork_id)
        members[tag].add(category)
    order = list(FeedbackTag)
    out = []
    for tag in order:
        present = weak.get(tag, set())
        if not present and tag not in strong:
            continue
        recent_stats = _window(recent, present)
        previous_stats = _window(previous, present)
        trend = (
            _trend(recent_stats, previous_stats, comparable)
            if present
            else TrendDirection.INSUFFICIENT_DATA
        )
        out.append(
            {
                "tag": tag.value,
                "label": FEEDBACK_TAG_LABELS[tag],
                "categories": [c.value for c in WeaknessCategory if c in members[tag]],
                "weakness_artwork_count": len(present),
                "weakness_ratio": _ratio(len(present), len(analyzed)),
                "strength_artwork_count": len(strong.get(tag, set())),
                "recent": recent_stats,
                "previous": previous_stats if comparable else None,
                "trend": trend.value,
                "repeated": len(present) >= 2,
                "last_seen_work_date": (
                    max(artworks[a].work_date for a in present).isoformat() if present else None
                ),
            }
        )
    out.sort(
        key=lambda t: (
            -t["weakness_artwork_count"],
            -t["strength_artwork_count"],
            order.index(FeedbackTag(t["tag"])),
        )
    )
    return out, [t["tag"] for t in out if t["repeated"]][:3]


def comparison_context(
    feedbacks: list[FeedbackFact],
    items: list[ItemFact],
    recent: list[uuid.UUID],
    previous: list[uuid.UUID],
    artworks: dict[uuid.UUID, ArtworkFact],
    comparable: bool,
) -> dict[str, Any] | None:
    """최근·이전 비교가 공정한지 보여 주는 맥락 (첨삭 분량·작품 조건). 비교 불가면 None.

    지적 비율이 줄어도 첨삭이 짧아졌거나 작품 조건이 달라졌을 수 있다
    → 실력 향상으로 단정하지 않는다.
    """
    if not comparable:
        return None
    per_feedback = Counter(i.feedback_id for i in items)

    def items_per_feedback(ids: list[uuid.UUID]) -> float | None:
        targets = set(ids)
        chosen = [f for f in feedbacks if f.artwork_id in targets]
        if not chosen:
            return None
        return round(sum(per_feedback[f.id] for f in chosen) / len(chosen), 2)

    def mock_ratio(ids: list[uuid.UUID]) -> float | None:
        mock = sum(1 for a in ids if artworks[a].work_category == ArtworkWorkCategory.MOCK_EXAM)
        return _ratio(mock, len(ids))

    def practical(ids: list[uuid.UUID]) -> set[str]:
        return {artworks[a].practical_type.value for a in ids if artworks[a].practical_type}

    recent_volume, previous_volume = items_per_feedback(recent), items_per_feedback(previous)
    recent_mock, previous_mock = mock_ratio(recent), mock_ratio(previous)
    cautions = []
    if recent_volume is not None and previous_volume:
        change = (recent_volume - previous_volume) / previous_volume
        if abs(change) >= VOLUME_CHANGE:
            more = "많아" if change > 0 else "적어"
            cautions.append(
                f"최근 첨삭은 이전보다 정리된 항목 수가 {more}요 (첨삭 1건당 평균 "
                f"{previous_volume:g}개 → {recent_volume:g}개). 지적 비율 변화에 첨삭 분량 차이가 "
                "섞여 있을 수 있어요."
            )
    if abs((recent_mock or 0) - (previous_mock or 0)) >= MIX_CHANGE:
        cautions.append(
            "최근 작품과 이전 작품의 모의시험 비중이 달라요. 시간 제한·난이도 차이가 지적 빈도에 "
            "영향을 줄 수 있어요."
        )
    if practical(recent) != practical(previous):
        cautions.append(
            "최근 작품과 이전 작품의 실기 유형 구성이 달라요. "
            "유형마다 자주 지적되는 항목이 다를 수 있어요."
        )
    return {
        "recent_items_per_feedback": recent_volume,
        "previous_items_per_feedback": previous_volume,
        "recent_mock_exam_ratio": recent_mock,
        "previous_mock_exam_ratio": previous_mock,
        "cautions": cautions,
    }


def recent_practice_tips(items: list[ItemFact], tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """최근 승인 첨삭의 '다음 작품 연습 과제'(NEXT_TIP). 반복 실수 태그와 관련된 것을 표시."""
    repeated = {t["tag"] for t in tags if t["repeated"]}
    tips = sorted(
        (i for i in items if i.kind == FeedbackItemKind.NEXT_TIP),
        key=lambda i: (i.work_date, i.approved_at),
        reverse=True,
    )[:MAX_PRACTICE_TIPS]
    out = []
    for item in tips:
        tag = CATEGORY_TAG[item.category or WeaknessCategory.OTHER].value
        out.append(
            {
                "item_id": str(item.id),
                "feedback_id": str(item.feedback_id),
                "artwork_id": str(item.artwork_id),
                "tag": tag,
                "related_repeated": tag in repeated,
            }
        )
    return out


# ---------------------------------------------------------------- v0.9 시간·출처·안내


def time_stats(artworks: list[ArtworkFact]) -> dict[str, Any]:
    """실제 소요 시간이 기록된 작품만 집계. 모의시험(MOCK_EXAM)은 제한 시간 대비 따로."""
    timed = [a for a in artworks if a.actual_minutes is not None]
    total = sum(a.actual_minutes or 0 for a in timed)
    mock = [a for a in artworks if a.work_category == ArtworkWorkCategory.MOCK_EXAM]
    mock_timed = [
        a for a in mock if a.actual_minutes is not None and a.time_limit_minutes is not None
    ]
    ratios = [a.actual_minutes / a.time_limit_minutes for a in mock_timed]  # type: ignore[operator]
    return {
        "recorded_artwork_count": len(timed),
        "unrecorded_artwork_count": len(artworks) - len(timed),
        "total_minutes": total,
        "average_minutes": round(total / len(timed), 1) if timed else None,
        "mock_exam": {
            "artwork_count": len(mock),
            "timed_count": len(mock_timed),
            "over_limit_count": sum(1 for r in ratios if r > 1),
            "average_time_ratio": round(sum(ratios) / len(ratios), 3) if ratios else None,
        },
    }


def activity(artworks: list[ArtworkFact], bucket: Bucket) -> list[dict[str, Any]]:
    """기간(주/월)별 작품 수·학습 시간·모의시험 수 (첨삭 유무와 무관한 모든 작품)."""
    buckets: dict[date, dict[str, Any]] = {}
    for a in artworks:
        start = _bucket_start(a.work_date, bucket)
        entry = buckets.setdefault(
            start,
            {
                "artwork_count": 0,
                "timed_artwork_count": 0,
                "study_minutes": 0,
                "mock_exam_count": 0,
            },
        )
        entry["artwork_count"] += 1
        if a.actual_minutes is not None:
            entry["timed_artwork_count"] += 1
            entry["study_minutes"] += a.actual_minutes
        if a.work_category == ArtworkWorkCategory.MOCK_EXAM:
            entry["mock_exam_count"] += 1
    return [{"bucket_start": s.isoformat(), **e} for s, e in sorted(buckets.items())]


def unverified_mentions(
    feedbacks: list[FeedbackFact], categories: dict[uuid.UUID, set[WeaknessCategory]]
) -> list[dict[str, Any]]:
    """자기 메모·다른 학생 의견에서 언급된 카테고리 (참고용, 반복 약점 판정에 쓰지 않음)."""
    counts: dict[WeaknessCategory, Counter[str]] = defaultdict(Counter)
    for f in feedbacks:
        if f.source == FeedbackSource.INSTRUCTOR:
            continue
        for category in categories.get(f.id, set()):
            counts[category][f.source.value] += 1
    return sorted(
        (
            {
                "category": c.value,
                "label": WEAKNESS_CATEGORY_LABELS[c],
                "mention_count": sum(n.values()),
                "by_source": dict(n),
            }
            for c, n in counts.items()
        ),
        key=lambda m: (-m["mention_count"], m["category"]),
    )


def guidance(
    analyzed: int,
    min_artworks: int,
    artworks: list[ArtworkFact],
    feedbacks: list[FeedbackFact],
    status: ReportStatus,
) -> list[str]:
    """신규·데이터 부족 사용자에게 다음 기록 안내 (단정적 평가 없음)."""
    tips: list[str] = []
    if not artworks:
        tips.append("첫 작품을 등록하고 단계별 사진을 올려 보세요.")
    if status == ReportStatus.INSUFFICIENT_DATA:
        tips.append(
            f"강사 첨삭을 기록하고 확정한 작품이 {min_artworks}개 이상이면 반복 약점을 분석합니다 "
            f"(현재 {analyzed}개)."
        )
    if artworks and all(a.actual_minutes is None for a in artworks):
        tips.append("작품마다 실제 작업 시간을 기록하면 학습 시간 변화를 함께 볼 수 있습니다.")
    if any(f.source != FeedbackSource.INSTRUCTOR for f in feedbacks) and analyzed == 0:
        tips.append(
            "자기 메모·다른 학생 의견은 참고로만 보여 주며 반복 약점 분석에는 쓰지 않습니다."
        )
    return tips
