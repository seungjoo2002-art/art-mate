"""이미지 실제 형식 검증 (DB·Storage 없이)."""

import pytest

from app.core.exceptions import UnprocessableError
from app.services.images import check_declared_file, inspect_image
from tests.fake_storage import image_bytes

ALLOWED = ["image/jpeg", "image/png", "image/webp"]
LIMITS = {"allowed": ALLOWED, "max_bytes": 1_000_000, "max_pixels": 10_000}


def _code(exc: pytest.ExceptionInfo[UnprocessableError]) -> str:
    return str(exc.value.code)


# ----------------------------------------------------------------------------- images


@pytest.mark.parametrize(
    ("fmt", "mime"), [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
def test_valid_images(fmt: str, mime: str) -> None:
    info = inspect_image(image_bytes(fmt, (40, 20)), declared_type=mime, **LIMITS)
    assert (info.content_type, info.width, info.height) == (mime, 40, 20)
    assert len(info.sha256) == 64


@pytest.mark.parametrize(
    ("data", "declared", "code"),
    [
        (b"not an image at all", "image/png", "INVALID_IMAGE"),
        (b"", "image/png", "INVALID_IMAGE"),
        # 확장자·MIME은 PNG로 선언했지만 실제는 JPEG
        (image_bytes("JPEG"), "image/png", "INVALID_IMAGE"),
        # 잘린 파일
        (image_bytes("PNG", (64, 64))[:60], "image/png", "INVALID_IMAGE"),
        # 허용하지 않는 실제 형식 (GIF)
        (image_bytes("GIF"), "image/png", "UNSUPPORTED_FILE_TYPE"),
        # 픽셀 수 초과 (디컴프레션 폭탄 방지)
        (image_bytes("PNG", (200, 200)), "image/png", "INVALID_IMAGE"),
        # 크기 초과
        (b"x" * 1_000_001, "image/png", "FILE_TOO_LARGE"),
    ],
)
def test_invalid_images(data: bytes, declared: str, code: str) -> None:
    with pytest.raises(UnprocessableError) as exc:
        inspect_image(data, declared_type=declared, **LIMITS)
    assert _code(exc) == code


@pytest.mark.parametrize(
    ("content_type", "file_name", "size", "code"),
    [
        ("image/gif", "a.gif", 10, "UNSUPPORTED_FILE_TYPE"),
        ("image/png", "a.jpg", 10, "UNSUPPORTED_FILE_TYPE"),
        ("image/png", "noext", 10, "UNSUPPORTED_FILE_TYPE"),
        ("image/jpeg", "a.JPEG", 2_000_000, "FILE_TOO_LARGE"),
    ],
)
def test_declared_file_checks(content_type: str, file_name: str, size: int, code: str) -> None:
    with pytest.raises(UnprocessableError) as exc:
        check_declared_file(content_type, file_name, size, allowed=ALLOWED, max_bytes=1_000_000)
    assert _code(exc) == code
    check_declared_file("image/jpeg", "photo.JPG", 10, allowed=ALLOWED, max_bytes=1_000_000)
