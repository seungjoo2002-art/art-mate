"""v1.1 원본 제시물·시험 조건·표현 의도: 입력 검증과 v1.2 AI 비교 입력 구성 (AI 호출 없음)."""

import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

from app.models.artwork import Artwork, ArtworkPhoto, ArtworkReferencePhoto, ArtworkStageDef
from app.models.enums import ArtworkStage, ArtworkWorkStatus, ExpressionMethod, PhotoStatus
from app.schemas.artworks import ArtworkCreate, ArtworkRead, ArtworkUpdate, normalize_methods
from app.schemas.comparison import (
    INTENT_NOT_PROVIDED_RULE,
    INTENT_PROVIDED_RULE,
    ComparisonResultDraft,
)
from app.services.comparison_input import build_comparison_input

NOW = dt.datetime(2026, 11, 17, 9, tzinfo=dt.UTC)


def _artwork(**extra) -> Artwork:  # type: ignore[no-untyped-def]
    return Artwork(
        id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        title="유리컵 기초디자인",
        work_date=dt.date(2026, 11, 17),
        work_status=ArtworkWorkStatus.IN_PROGRESS,
        **extra,
    )


def _stage(position: int, name: str) -> ArtworkStageDef:
    return ArtworkStageDef(
        id=uuid.uuid4(), name=name, position=position, legacy_stage=ArtworkStage.SKETCH
    )


def _photo(
    stage: ArtworkStageDef, minutes: int, status=PhotoStatus.ACTIVE, rep=False
) -> ArtworkPhoto:  # type: ignore[no-untyped-def]
    return ArtworkPhoto(
        id=uuid.uuid4(),
        stage_id=stage.id,
        status=status,
        width=800,
        height=600,
        uploaded_at=NOW + dt.timedelta(minutes=minutes),
        created_at=NOW,
        is_representative=rep,
    )


def _ref(position: int, status=PhotoStatus.ACTIVE) -> ArtworkReferencePhoto:  # type: ignore[no-untyped-def]
    return ArtworkReferencePhoto(
        id=uuid.uuid4(),
        position=position,
        status=status,
        width=1200,
        height=900,
        uploaded_at=NOW,
        created_at=NOW,
    )


def test_methods_are_deduplicated_and_ordered_and_validated() -> None:
    assert normalize_methods(
        [ExpressionMethod.REARRANGE, ExpressionMethod.SCALE, ExpressionMethod.SCALE]
    ) == ["SCALE", "REARRANGE"]
    assert normalize_methods(None) is None
    created = ArtworkCreate(title="t", expression_methods=["ROTATE", "OTHER"], paper_size=" 4절 ")
    assert created.paper_size == "4절"
    with pytest.raises(ValidationError):
        ArtworkCreate(title="t", expression_methods=["MAGIC"])
    with pytest.raises(ValidationError):
        ArtworkCreate(title="t", expression_intent="x" * 1001)
    with pytest.raises(ValidationError):
        ArtworkUpdate(expression_methods=None)  # 비울 때는 [] (null 금지)
    assert ArtworkUpdate(expression_methods=[]).changes() == {"expression_methods": []}


def test_artwork_read_defaults_keep_old_responses_valid() -> None:
    # v1.1 이전 응답·기존 작품 dict에는 새 필드가 없다 → 기본값
    fields = ArtworkRead.model_fields
    assert fields["expression_methods"].is_required() is False
    for name in ("paper_size", "exam_conditions", "expression_intent"):
        assert fields[name].default is None


def test_comparison_input_without_intent_forbids_assuming_it() -> None:
    sketch, final = _stage(0, "스케치"), _stage(2, "완성")
    color = _stage(1, "채색")
    artwork = _artwork(topic="유리컵과 사과", expression_methods=[], expression_intent="  ")
    built = build_comparison_input(
        artwork,
        [_ref(1), _ref(0), _ref(2, PhotoStatus.DELETED)],
        [final, sketch, color],
        [
            _photo(sketch, 5, rep=True),
            _photo(sketch, 1),
            _photo(final, 9, PhotoStatus.PENDING),
        ],
    )
    assert built.schema_version == "comparison-input-v1"
    assert built.intent.status == "NOT_PROVIDED" and built.intent.rule == INTENT_NOT_PROVIDED_RULE
    assert built.intent.text is None and built.intent.methods == []
    assert [r.role for r in built.references] == ["REFERENCE", "REFERENCE"]  # 삭제 제외
    assert [s.name for s in built.stages] == ["스케치", "채색", "완성"]  # 단계 순서
    sketch_photos = built.stages[0].photos
    # 올린 순서, 대표 = 단계에서 가장 먼저 올린 사진 (예전에 직접 고른 값 rep=True는 읽지 않음)
    assert [p.is_representative for p in sketch_photos] == [True, False]
    assert built.stages[2].photos == []  # 업로드 미완료 제외
    assert built.readiness.ready is True and built.readiness.missing == []
    assert built.exam.topic == "유리컵과 사과"


def test_comparison_input_with_intent_and_missing_images() -> None:
    artwork = _artwork(
        expression_methods=["ROTATE", "SCALE"],
        expression_intent="유리컵을 기울여 역동적인 구도를 만들었다.",
        paper_size="4절",
        exam_conditions="제시물 2개 이상 사용",
        time_limit_minutes=240,
        description="자유 메모",
    )
    built = build_comparison_input(artwork, [], [_stage(0, "스케치")], [])
    assert built.intent.status == "PROVIDED" and built.intent.rule == INTENT_PROVIDED_RULE
    assert built.intent.methods == [ExpressionMethod.SCALE, ExpressionMethod.ROTATE]
    assert built.intent.method_labels == ["확대·축소", "회전·기울이기"]
    assert (built.exam.paper_size, built.exam.time_limit_minutes, built.exam.memo) == (
        "4절",
        240,
        "자유 메모",
    )
    assert built.readiness.ready is False
    assert built.readiness.missing == ["REFERENCE_PHOTO", "ARTWORK_PHOTO"]
    # 이미지 경로·URL은 입력에 넣지 않는다 (id 참조만)
    assert "storage_path" not in built.model_dump_json()


def test_result_schema_is_design_only_without_scores() -> None:
    fields = set(ComparisonResultDraft.model_fields)
    assert fields == {
        "input_version",
        "stage_id",
        "findings",
        "needs_confirmation",
        "image_quality_notes",
    }
    finding = ComparisonResultDraft.model_fields["findings"].annotation.__args__[0]  # type: ignore[union-attr]
    assert "score" not in finding.model_fields and "uncertainty" in finding.model_fields
