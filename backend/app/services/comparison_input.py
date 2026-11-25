"""v1.1 AI 비교 첨삭 입력 만들기 (순수 함수, AI 호출 없음). v1.2 Worker가 그대로 쓴다."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.artwork import Artwork, ArtworkPhoto, ArtworkReferencePhoto, ArtworkStageDef
from app.models.enums import EXPRESSION_METHOD_LABELS, ExpressionMethod, PhotoStatus
from app.schemas.comparison import (
    INTENT_NOT_PROVIDED_RULE,
    INTENT_PROVIDED_RULE,
    ComparisonExam,
    ComparisonImageRef,
    ComparisonInput,
    ComparisonIntent,
    ComparisonReadiness,
    ComparisonStage,
)
from app.services.representative import representative_ids


def _intent(artwork: Artwork) -> ComparisonIntent:
    chosen = set(artwork.expression_methods or [])
    methods = [m for m in ExpressionMethod if m.value in chosen]
    text = (artwork.expression_intent or "").strip() or None
    provided = bool(methods or text)
    return ComparisonIntent(
        status="PROVIDED" if provided else "NOT_PROVIDED",
        methods=methods,
        method_labels=[EXPRESSION_METHOD_LABELS[m] for m in methods],
        text=text,
        rule=INTENT_PROVIDED_RULE if provided else INTENT_NOT_PROVIDED_RULE,
    )


def build_comparison_input(
    artwork: Artwork,
    references: Sequence[ArtworkReferencePhoto],
    stages: Sequence[ArtworkStageDef],
    photos: Sequence[ArtworkPhoto],
) -> ComparisonInput:
    """저장된 작품 데이터만으로 v1.2 입력을 만든다. 업로드 완료(ACTIVE) 사진만 쓴다."""
    refs = [
        ComparisonImageRef(
            photo_id=r.id,
            role="REFERENCE",
            width=r.width,
            height=r.height,
            uploaded_at=r.uploaded_at,
        )
        for r in sorted(references, key=lambda r: (r.position, r.uploaded_at or r.created_at))
        if r.status == PhotoStatus.ACTIVE
    ]
    representatives = representative_ids(photos)  # 단계마다 가장 먼저 등록한 사진
    by_stage: dict[object, list[ArtworkPhoto]] = {}
    for photo in photos:
        if photo.status == PhotoStatus.ACTIVE:
            by_stage.setdefault(photo.stage_id, []).append(photo)
    stage_rows = []
    for stage in sorted(stages, key=lambda s: s.position):
        stage_photos = sorted(
            by_stage.get(stage.id, []), key=lambda p: (p.uploaded_at or p.created_at, str(p.id))
        )
        stage_rows.append(
            ComparisonStage(
                stage_id=stage.id,
                name=stage.name,
                position=stage.position,
                photos=[
                    ComparisonImageRef(
                        photo_id=p.id,
                        role="ARTWORK",
                        width=p.width,
                        height=p.height,
                        uploaded_at=p.uploaded_at,
                        is_representative=p.id in representatives,
                    )
                    for p in stage_photos
                ],
            )
        )
    missing: list = []
    if not refs:
        missing.append("REFERENCE_PHOTO")
    if not any(s.photos for s in stage_rows):
        missing.append("ARTWORK_PHOTO")
    return ComparisonInput(
        artwork_id=artwork.id,
        title=artwork.title,
        work_date=artwork.work_date,
        work_status=artwork.work_status,
        exam=ComparisonExam(
            topic=artwork.topic,
            practical_type=artwork.practical_type,
            work_category=artwork.work_category,
            exam_materials=artwork.exam_materials,
            time_limit_minutes=artwork.time_limit_minutes,
            paper_size=artwork.paper_size,
            exam_conditions=artwork.exam_conditions,
            memo=artwork.description,
        ),
        intent=_intent(artwork),
        references=refs,
        stages=stage_rows,
        readiness=ComparisonReadiness(ready=not missing, missing=missing),
    )
