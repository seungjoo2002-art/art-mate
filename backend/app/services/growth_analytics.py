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
    WEAKNESS_CATEGORY_LABELS,
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    Confidence,
    FeedbackItemKind,
    PracticalType,
    ReportStatus,
    TrendDirection,
    WeaknessCategory,
)

ANALYSIS_VERSION = "growth-v1"
TREND_THRESHOLD = 0.2
HIGH_CONFIDENCE_ARTWORKS = 8
MAX_EVIDENCE = 3

NOTES = [
    "이 통계는 강사가 승인한 첨삭 기록을 집계한 것이며, AI가 실기 능력을 채점한 결과가 아닙니다.",
    "첨삭에서 언급되지 않은 약점이 개선되었다는 뜻은 아닙니다.",
    "강사마다 첨삭 방식과 표현이 달라 지적 빈도가 달라질 수 있습니다.",
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


@dataclass(frozen=True)
class FeedbackFact:
    id: uuid.UUID
    artwork_id: uuid.UUID
    approved_at: datetime
    version: int


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
    feedbacks = [f for f in dataset.feedbacks if f.artwork_id in artworks]
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
        if item.artwork_id not in artworks:
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
    timeline = [
        {
            "bucket_start": start.isoformat(),
            "analyzed_artwork_count": len(entry["analyzed"]),
            "categories": {c: len(ids) for c, ids in sorted(entry["categories"].items())},
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
        "strengths": strengths,
        "timeline_bucket": bucket,
        "timeline": timeline,
        "next_goals": next_goals,
        "analyzed_artwork_ids": [str(a) for a in analyzed],
        "notes": NOTES,
    }
