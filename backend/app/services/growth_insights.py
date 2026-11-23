"""성장 아카이브 분석 (v1.2): 반복 실수·강점·개선 추세 (규칙 기반, 순수 함수, 외부 호출 없음).

입력은 v0.7~v1.0 성장 분석과 같은 `Dataset` (승인된 첨삭만). 이 모듈은 숫자를 만들지 않고
"어느 작품의 어느 첨삭 항목이 근거인지"만 정리한다. 근거 문장은 조회 시점에 DB에서 다시 읽는다
(첨삭이 수정·삭제되면 결과가 바로 바뀐다).

판정 규칙 (docs/feedback-archive-v1.2.md §4에 같은 내용)
- 집계 대상: 강사 첨삭(INSTRUCTOR) 승인본. 자기 메모·다른 학생 의견은 쓰지 않는다 (v0.9 원칙 유지).
- 작품 1개 = 태그마다 사건 1개. 그 작품의 승인 첨삭에서
    지적(NEG)  = 개선할 점(WEAKNESS)·수정 방법(FIX) 항목 또는 약점 카테고리가 그 태그
    긍정(POS)  = 잘한 점(STRENGTH) 항목이 그 태그
    둘 다(MIXED) = 같은 작품에서 칭찬과 지적이 함께 나옴
- 반복 실수: 지적이 나온 작품이 2개 이상인 태그. 세부 주제(예: 타원·원통형)는 지적 항목 문장의
  용어 키워드로 묶고, 2개 이상 작품에서 나온 주제만 보여 준다 (키워드가 없으면 묶지 않음).
- 강점: 잘한 점 항목이 나온 작품이 2개 이상인 태그. 지적이 없다는 이유로 강점이라 하지 않는다.
- 개선 추세(IMPROVING): 작업일 순으로 지적(NEG/MIXED)이 먼저 있고, 가장 최근 사건이 긍정(POS)인 태그.
  지적 뒤 긍정이 2개 작품 이상이면 confirmed, 1개면 초기 신호(confirmed=false).
- 여전히 개선 필요(NEEDS_WORK): 가장 최근 사건이 지적(NEG/MIXED)인 태그.
- 꾸준한 강점(CONSISTENT_STRENGTH): 지적 없이 긍정만 2개 작품 이상.
- 그 밖(사건 1개뿐 등) = INSUFFICIENT → 판단 보류.
- 전체 분석은 분석 대상 작품(승인 강사 첨삭이 있는 작품)이 growth_min_artworks 이상일 때만.
  그보다 적으면 추세·강점·반복 실수를 내지 않고 최근 첨삭만 보여 준다.
- 성장률·점수·백분율은 만들지 않는다. 숫자는 실제 작품 수·날짜뿐이다.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

from app.models.enums import (
    CATEGORY_TAG,
    FEEDBACK_TAG_LABELS,
    FeedbackItemKind,
    FeedbackSource,
    FeedbackTag,
    WeaknessCategory,
)
from app.services.art_glossary import THEME_BY_CODE, themes_in
from app.services.growth_analytics import Dataset

INSIGHTS_VERSION = "growth-insights-v1"
MIN_REPEAT_ARTWORKS = 2
MIN_STRENGTH_ARTWORKS = 2
MIN_THEME_ARTWORKS = 2
MAX_ITEMS = 3
MAX_ARTWORKS = 10

Polarity = Literal["NEG", "POS", "MIXED"]
Progress = Literal["IMPROVING", "NEEDS_WORK", "CONSISTENT_STRENGTH", "INSUFFICIENT"]

NEGATIVE_KINDS = (FeedbackItemKind.WEAKNESS, FeedbackItemKind.FIX)
PRACTICE_KINDS = (FeedbackItemKind.NEXT_TIP, FeedbackItemKind.FIX)


@dataclass
class _Event:
    artwork_id: uuid.UUID
    work_date: date
    approved_at: datetime
    neg: bool = False
    pos: bool = False

    @property
    def polarity(self) -> Polarity:
        if self.neg and self.pos:
            return "MIXED"
        return "NEG" if self.neg else "POS"


@dataclass
class _TagData:
    events: dict[uuid.UUID, _Event] = field(default_factory=dict)
    # (work_date, approved_at, item_id) — 최신순 정렬용
    neg_items: list[tuple[date, datetime, uuid.UUID, uuid.UUID, str]] = field(default_factory=list)
    pos_items: list[tuple[date, datetime, uuid.UUID, uuid.UUID, str]] = field(default_factory=list)
    practice_items: list[tuple[date, datetime, uuid.UUID, uuid.UUID, str]] = field(
        default_factory=list
    )


def _tag(category: WeaknessCategory | None) -> FeedbackTag:
    return CATEGORY_TAG[category or WeaknessCategory.OTHER]


def _latest_ids(rows: list[tuple[date, datetime, uuid.UUID, uuid.UUID, str]]) -> list[str]:
    """최신순, 작품당 1개 항목 ID (최대 MAX_ITEMS)."""
    seen: set[uuid.UUID] = set()
    out: list[str] = []
    for _, _, item_id, artwork_id, _ in sorted(rows, key=lambda r: (r[0], r[1]), reverse=True):
        if artwork_id in seen:
            continue
        seen.add(artwork_id)
        out.append(str(item_id))
        if len(out) == MAX_ITEMS:
            break
    return out


def _progress(events: list[_Event]) -> tuple[Progress, int]:
    """(판정, 마지막 지적 뒤 긍정 작품 수)."""
    if len(events) < 2:
        return "INSUFFICIENT", 0
    last_issue = max((i for i, e in enumerate(events) if e.neg), default=None)
    if last_issue is None:
        positives = sum(1 for e in events if e.pos)
        return ("CONSISTENT_STRENGTH" if positives >= MIN_STRENGTH_ARTWORKS else "INSUFFICIENT"), 0
    after = events[last_issue + 1 :]
    if after and all(e.polarity == "POS" for e in after):
        return "IMPROVING", len(after)
    if events[-1].neg:
        return "NEEDS_WORK", 0
    return "INSUFFICIENT", 0


def build_insights(dataset: Dataset, *, min_artworks: int) -> dict[str, Any]:
    artworks = {a.id: a for a in dataset.artworks}
    verified = {
        f.id: f
        for f in dataset.feedbacks
        if f.source == FeedbackSource.INSTRUCTOR and f.artwork_id in artworks
    }
    first_approved: dict[uuid.UUID, datetime] = {}
    for f in verified.values():
        current = first_approved.get(f.artwork_id)
        first_approved[f.artwork_id] = (
            f.approved_at if current is None else min(current, f.approved_at)
        )
    analyzed = len(first_approved)
    tags: dict[FeedbackTag, _TagData] = defaultdict(_TagData)

    def event(tag: FeedbackTag, artwork_id: uuid.UUID) -> _Event:
        data = tags[tag]
        if artwork_id not in data.events:
            data.events[artwork_id] = _Event(
                artwork_id, artworks[artwork_id].work_date, first_approved[artwork_id]
            )
        return data.events[artwork_id]

    # 약점 카테고리 (feedback_categories) → 지적
    for feedback_id, categories in dataset.categories.items():
        f = verified.get(feedback_id)
        if f is None:
            continue
        for category in categories:
            event(_tag(category), f.artwork_id).neg = True

    theme_artworks: dict[FeedbackTag, dict[str, set[uuid.UUID]]] = defaultdict(
        lambda: defaultdict(set)
    )
    theme_items: dict[FeedbackTag, dict[str, list[tuple[date, datetime, uuid.UUID]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for item in dataset.items:
        if item.feedback_id not in verified or item.artwork_id not in artworks:
            continue
        tag = _tag(item.category)
        row = (item.work_date, item.approved_at, item.id, item.artwork_id, item.content)
        if item.kind == FeedbackItemKind.STRENGTH:
            event(tag, item.artwork_id).pos = True
            tags[tag].pos_items.append(row)
        elif item.kind in NEGATIVE_KINDS:
            if item.category is None:
                continue  # 카테고리 없는 지적은 태그에 억지로 넣지 않는다
            event(tag, item.artwork_id).neg = True
            tags[tag].neg_items.append(row)
            for theme in themes_in(item.content):
                theme_artworks[tag][theme].add(item.artwork_id)
                theme_items[tag][theme].append((item.work_date, item.approved_at, item.id))
        if item.kind in PRACTICE_KINDS and item.category is not None:
            tags[tag].practice_items.append(row)

    order = list(FeedbackTag)
    per_tag: list[dict[str, Any]] = []
    for tag, data in tags.items():
        events = sorted(
            data.events.values(), key=lambda e: (e.work_date, e.approved_at, str(e.artwork_id))
        )
        neg_events = [e for e in events if e.neg]
        pos_events = [e for e in events if e.pos]
        progress, positive_after = _progress(events)
        themes = sorted(
            (
                {
                    "code": code,
                    "label": THEME_BY_CODE[code].label,
                    "artwork_count": len(ids),
                    "item_ids": [
                        str(i)
                        for _, _, i in sorted(theme_items[tag][code], reverse=True)[:MAX_ITEMS]
                    ],
                }
                for code, ids in theme_artworks[tag].items()
                if len(ids) >= MIN_THEME_ARTWORKS
            ),
            key=lambda t: (-t["artwork_count"], t["code"]),
        )
        per_tag.append(
            {
                "tag": tag.value,
                "label": FEEDBACK_TAG_LABELS[tag],
                "progress": progress,
                "issue_artwork_count": len(neg_events),
                "positive_artwork_count": len(pos_events),
                "first_issue_date": neg_events[0].work_date.isoformat() if neg_events else None,
                "last_issue_date": neg_events[-1].work_date.isoformat() if neg_events else None,
                "last_positive_date": pos_events[-1].work_date.isoformat() if pos_events else None,
                "positive_since_last_issue": positive_after,
                "improvement_confirmed": progress == "IMPROVING"
                and positive_after >= MIN_STRENGTH_ARTWORKS,
                "themes": themes,
                "issue_item_ids": _latest_ids(data.neg_items),
                "positive_item_ids": _latest_ids(data.pos_items),
                "practice_item_ids": _latest_ids(data.practice_items),
                # 관련 작품 (최신순)
                "issue_artwork_ids": [str(e.artwork_id) for e in reversed(neg_events)][
                    :MAX_ARTWORKS
                ],
                "positive_artwork_ids": [str(e.artwork_id) for e in reversed(pos_events)][
                    :MAX_ARTWORKS
                ],
                "events": [
                    {
                        "artwork_id": str(e.artwork_id),
                        "work_date": e.work_date.isoformat(),
                        "polarity": e.polarity,
                    }
                    for e in events
                ],
            }
        )
    per_tag.sort(key=lambda t: order.index(FeedbackTag(t["tag"])))

    def latest(t: dict[str, Any], key: str) -> str:
        return t[key] or ""

    sufficient = analyzed >= min_artworks
    # 정렬: 작품 수 많은 순 → 최근 날짜 순 (안정 정렬 두 번)
    repeated = sorted(
        (t for t in per_tag if t["issue_artwork_count"] >= MIN_REPEAT_ARTWORKS),
        key=lambda t: latest(t, "last_issue_date"),
        reverse=True,
    )
    repeated.sort(key=lambda t: -t["issue_artwork_count"])
    strengths = sorted(
        (t for t in per_tag if t["positive_artwork_count"] >= MIN_STRENGTH_ARTWORKS),
        key=lambda t: latest(t, "last_positive_date"),
        reverse=True,
    )
    strengths.sort(key=lambda t: -t["positive_artwork_count"])
    improving = sorted(
        (t for t in per_tag if t["progress"] == "IMPROVING"),
        key=lambda t: latest(t, "last_positive_date"),
        reverse=True,
    )
    needs_work = sorted(
        (t for t in per_tag if t["progress"] == "NEEDS_WORK"),
        key=lambda t: latest(t, "last_issue_date"),
        reverse=True,
    )
    needs_work.sort(key=lambda t: -t["issue_artwork_count"])
    return {
        "insights_version": INSIGHTS_VERSION,
        "analyzed_artwork_count": analyzed,
        "required_artwork_count": min_artworks,
        "sufficient": sufficient,
        "tags": per_tag,
        # 데이터가 부족하면 추세·강점·반복 실수를 내지 않는다 (무리한 분석 금지)
        "repeated_mistakes": [t["tag"] for t in repeated] if sufficient else [],
        "strengths": [t["tag"] for t in strengths] if sufficient else [],
        "improving": [t["tag"] for t in improving] if sufficient else [],
        "needs_work": [t["tag"] for t in needs_work] if sufficient else [],
    }


def tag_entry(insights: dict[str, Any], tag: str) -> dict[str, Any]:
    return next(t for t in insights["tags"] if t["tag"] == tag)


def summarize_insights(insights: dict[str, Any]) -> dict[str, Any]:
    """리포트 지표에 저장할 짧은 요약 (태그·라벨·작품 수만, 근거 문장 없음)."""

    def entry(code: str) -> dict[str, Any]:
        t = tag_entry(insights, code)
        return {
            "tag": code,
            "label": t["label"],
            "issue_artwork_count": t["issue_artwork_count"],
            "positive_artwork_count": t["positive_artwork_count"],
            "improvement_confirmed": t["improvement_confirmed"],
            "themes": [th["label"] for th in t["themes"]],
        }

    return {
        "insights_version": insights["insights_version"],
        "sufficient": insights["sufficient"],
        "repeated_mistakes": [entry(c) for c in insights["repeated_mistakes"]],
        "strengths": [entry(c) for c in insights["strengths"]],
        "improving": [entry(c) for c in insights["improving"]],
        "needs_work": [entry(c) for c in insights["needs_work"]],
    }
