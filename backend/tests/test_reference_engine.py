"""F-15 추천 순위·공유용 파생 이미지 단위 테스트 (DB·Storage 없음)."""

import io
import uuid
from datetime import UTC, datetime, timedelta

from PIL import Image

from app.models.enums import (
    ArtworkWorkCategory,
    AuthorDisplay,
    PracticalType,
    WeaknessCategory,
)
from app.services.reference_engine import Candidate, StudentContext, rank_candidates
from app.services.sharing import derive_shared_image

C = WeaknessCategory
NOW = datetime(2026, 11, 1, tzinfo=UTC)


def _candidate(category, *, artwork=None, practical=None, work=None, days=0) -> Candidate:  # type: ignore[no-untyped-def]
    return Candidate(
        review_id=uuid.uuid4(),
        artwork_id=artwork or uuid.uuid4(),
        owner_id=uuid.uuid4(),
        category=category,
        note="기준선 처리 참고",
        reviewed_at=NOW + timedelta(days=days),
        practical_type=practical,
        work_category=work,
        consent_id=uuid.uuid4(),
        author_display=AuthorDisplay.ANONYMOUS,
        image_id=uuid.uuid4(),
    )


CONTEXT = StudentContext(
    viewer_id=uuid.uuid4(),
    weaknesses=[C.PROPORTION, C.VALUE],
    practical_type=PracticalType.DRAWING,
    work_categories=frozenset({ArtworkWorkCategory.MOCK_EXAM}),
)


def test_rank_prefers_top_weakness_then_same_practical_type() -> None:
    value_same_type = _candidate(C.VALUE, practical=PracticalType.DRAWING)
    proportion_other = _candidate(C.PROPORTION, practical=PracticalType.WATERCOLOR)
    proportion_same = _candidate(
        C.PROPORTION, practical=PracticalType.DRAWING, work=ArtworkWorkCategory.MOCK_EXAM
    )
    ranked = rank_candidates(
        CONTEXT, [value_same_type, proportion_other, proportion_same], per_weakness=3, max_results=9
    )
    assert [r.candidate for r in ranked] == [proportion_same, proportion_other, value_same_type]
    codes = [r["code"] for r in ranked[0].reasons]
    assert codes == [
        "VERIFIED_EXEMPLAR",
        "MATCHES_WEAKNESS",
        "SAME_PRACTICAL_TYPE",
        "SAME_WORK_CATEGORY",
    ]
    assert "강사가 확인한 작품" in ranked[0].reasons[0]["message"]
    assert "소묘" in ranked[0].reasons[2]["message"]
    assert [r["code"] for r in ranked[1].reasons] == ["VERIFIED_EXEMPLAR", "MATCHES_WEAKNESS"]


def test_same_artwork_counted_once_and_limits() -> None:
    shared = uuid.uuid4()
    duplicates = [_candidate(C.PROPORTION, artwork=shared), _candidate(C.VALUE, artwork=shared)]
    ranked = rank_candidates(CONTEXT, duplicates, per_weakness=3, max_results=9)
    assert len(ranked) == 1 and ranked[0].candidate.category == C.PROPORTION

    many = [_candidate(C.PROPORTION, days=i) for i in range(5)] + [_candidate(C.VALUE)]
    ranked = rank_candidates(CONTEXT, many, per_weakness=2, max_results=3)
    assert [r.candidate.category for r in ranked] == [C.PROPORTION, C.PROPORTION, C.VALUE]
    # 같은 점수면 최근에 확인된 사례 먼저
    assert ranked[0].candidate.reviewed_at > ranked[1].candidate.reviewed_at
    assert rank_candidates(CONTEXT, [], per_weakness=3, max_results=9) == []


def _jpeg_with_exif(size: tuple[int, int], orientation: int = 1) -> bytes:
    image = Image.new("RGB", size, "red")
    exif = Image.Exif()
    exif[0x0112] = orientation  # Orientation
    exif[0x010F] = "SecretCam"  # Make
    exif[0x8825] = {2: (37.0, 33.0, 0.0)}  # GPS
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif.tobytes())
    return out.getvalue()


def test_derived_image_strips_metadata_and_resizes() -> None:
    original = _jpeg_with_exif((3000, 2000))
    assert Image.open(io.BytesIO(original)).getexif()
    data, width, height = derive_shared_image(original, max_px=1600, quality=82)
    with Image.open(io.BytesIO(data)) as shared:
        assert shared.format == "JPEG"
        assert (shared.width, shared.height) == (width, height) == (1600, 1067)
        assert not shared.getexif()  # 촬영 정보·위치 제거
        assert "exif" not in shared.info
    assert b"SecretCam" not in data


def test_derived_image_applies_orientation_and_converts_png() -> None:
    rotated = _jpeg_with_exif((400, 200), orientation=6)  # 90도 회전 표시
    _, width, height = derive_shared_image(rotated, max_px=1600, quality=82)
    assert (width, height) == (200, 400)
    png = io.BytesIO()
    Image.new("RGBA", (100, 50), (0, 0, 255, 128)).save(png, format="PNG")
    data, width, height = derive_shared_image(png.getvalue(), max_px=1600, quality=82)
    assert (width, height) == (100, 50) and data[:2] == b"\xff\xd8"  # 업스케일 안 함, JPEG
