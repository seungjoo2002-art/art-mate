"""v0.9.9 첨삭 분류 태그 (저장된 항목 카테고리 → 9개 표시 태그)."""

import datetime as dt
import uuid

from app.models.enums import (
    CATEGORY_TAG,
    FEEDBACK_TAG_LABELS,
    FeedbackItemKind,
    FeedbackItemOrigin,
    FeedbackSource,
    FeedbackStatus,
    FeedbackTag,
    ReviewMode,
    WeaknessCategory,
)
from app.schemas.ai_feedback import FeedbackItemRead, FeedbackRead, feedback_tags

K = FeedbackItemKind
C = WeaknessCategory


def _item(kind: FeedbackItemKind, category: WeaknessCategory | None) -> FeedbackItemRead:
    return FeedbackItemRead(
        id=uuid.uuid4(),
        kind=kind,
        position=0,
        content="내용",
        category=category,
        evidence=[],
        origin=FeedbackItemOrigin.AI,
    )


def test_every_category_maps_to_exactly_one_labelled_tag() -> None:
    assert set(CATEGORY_TAG) == set(WeaknessCategory)
    assert set(CATEGORY_TAG.values()) == set(FeedbackTag)
    assert set(FEEDBACK_TAG_LABELS) == set(FeedbackTag)
    # 요청된 9개 표시 태그
    assert [FEEDBACK_TAG_LABELS[t] for t in FeedbackTag] == [
        "구도",
        "형태·비례",
        "명암",
        "색채",
        "원근·공간감",
        "질감·표현",
        "완성도",
        "시간 관리",
        "기타",
    ]


def test_tags_cover_strengths_and_next_tips_not_only_weaknesses() -> None:
    # 운영 사례(2026-11-16): 잘한 점=구도, 연습 과제=형태, 약점 카테고리=비례·명암
    items = [
        _item(K.STRENGTH, C.COMPOSITION),
        _item(K.WEAKNESS, C.PROPORTION),
        _item(K.FIX, C.PROPORTION),
        _item(K.FIX, C.VALUE),
        _item(K.NEXT_TIP, C.FORM),
    ]
    tags = feedback_tags(items, [C.PROPORTION, C.VALUE])
    assert [t.code for t in tags] == [
        FeedbackTag.COMPOSITION,
        FeedbackTag.FORM_PROPORTION,
        FeedbackTag.VALUE,
    ]
    composition, form, value = tags
    assert (composition.label, composition.needs_work, composition.kinds) == (
        "구도",
        False,
        [K.STRENGTH],
    )
    # 형태(연습 과제)와 비례(약점)는 한 태그로 묶인다 (복수 카테고리)
    assert form.categories == [C.FORM, C.PROPORTION]
    assert form.kinds == [K.WEAKNESS, K.FIX, K.NEXT_TIP]
    assert form.needs_work is True
    assert value.needs_work is True


def test_no_items_no_tags_and_uncategorised_items_ignored() -> None:
    # 내용이 부족한 첨삭(insufficient_content): 항목이 없으면 태그도 없다 (만들어내지 않음)
    assert feedback_tags([], []) == []
    assert feedback_tags([_item(K.STRENGTH, None)], []) == []


def test_weakness_category_without_item_still_counts_as_needs_work() -> None:
    # 사람이 항목을 지웠어도 확정된 약점 카테고리는 태그에 남는다 (기존 categories와 일관)
    (tag,) = feedback_tags([], [C.TIME_MANAGEMENT])
    assert (tag.code, tag.needs_work, tag.kinds) == (FeedbackTag.TIME_MANAGEMENT, True, [])


def test_feedback_read_serialises_tags_and_keeps_categories() -> None:
    now = dt.datetime.now(dt.UTC)
    read = FeedbackRead(
        id=uuid.uuid4(),
        recording_id=None,
        note_id=uuid.uuid4(),
        source=FeedbackSource.INSTRUCTOR,
        artwork_id=uuid.uuid4(),
        status=FeedbackStatus.DRAFT,
        review_mode=ReviewMode.SELF,
        version=1,
        summary="요약",
        strengths=[_item(K.STRENGTH, C.COLOR)],
        weaknesses=[_item(K.WEAKNESS, C.RENDERING)],
        fixes=[],
        next_tips=[],
        categories=[C.RENDERING],
        approved_at=None,
        approved_by_name=None,
        created_at=now,
        updated_at=now,
    )
    data = read.model_dump(mode="json")
    assert data["categories"] == ["RENDERING"]  # 기존 필드 그대로
    assert [(t["code"], t["label"], t["needs_work"]) for t in data["tags"]] == [
        ("COLOR", "색채", False),
        ("TEXTURE_EXPRESSION", "질감·표현", True),
    ]
    # 응답을 다시 읽어도(클라이언트 캐시 등) tags 입력은 무시하고 다시 계산한다
    again = FeedbackRead.model_validate(data)
    assert again.model_dump(mode="json")["tags"] == data["tags"]
