"""AI 수정본 이미지 처리 (v1.3): 외부로 보내기 전 원본 정리, 결과 검증, 요청 크기 선택.

- 원본: EXIF 방향을 적용해 똑바로 세우고(화면에 보이는 방향 그대로), EXIF·GPS 등 메타데이터를 모두
  지운
  새 JPEG/PNG로 다시 만든다 (위치 정보가 외부 AI로 나가지 않게). 긴 변은 설정값 이하로 줄인다(비율
  유지).
- 결과: 실제 이미지인지, 크기·픽셀 수가 상한 이내인지 확인한다.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

FORMAT_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_RESULT_PIXELS = 16_000_000
# 공식 지원 크기 (세로·가로·정사각)
PORTRAIT, LANDSCAPE, SQUARE = "1024x1536", "1536x1024", "1024x1024"


class InvalidImage(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PreparedImage:
    data: bytes
    content_type: str
    width: int
    height: int


def _open(data: bytes, max_pixels: int) -> Image.Image:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            if image.size[0] * image.size[1] > max_pixels:
                raise InvalidImage("too many pixels")
            image.load()
            return image
    except InvalidImage:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise InvalidImage("not a valid image") from None


def prepare_source(data: bytes, *, max_px: int, max_pixels: int = 50_000_000) -> PreparedImage:
    """외부로 보낼 원본 사본: 방향 적용·메타데이터 제거·긴 변 축소."""
    image = _open(data, max_pixels)
    image = ImageOps.exif_transpose(image)
    has_alpha = image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info)
    image = image.convert("RGBA" if has_alpha else "RGB")
    if max(image.size) > max_px:
        image.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    if has_alpha:
        image.save(out, format="PNG", optimize=True)
        content_type = "image/png"
    else:
        image.save(out, format="JPEG", quality=92, optimize=True)
        content_type = "image/jpeg"
    return PreparedImage(out.getvalue(), content_type, image.size[0], image.size[1])


def inspect_result(data: bytes, *, max_bytes: int) -> PreparedImage:
    if not data or len(data) > max_bytes:
        raise InvalidImage("result size out of range")
    image = _open(data, MAX_RESULT_PIXELS)
    content_type = FORMAT_MIME.get(image.format or "")
    if content_type is None:
        raise InvalidImage("unsupported result format")
    return PreparedImage(data, content_type, image.size[0], image.size[1])


def choose_size(width: int, height: int, setting: str) -> str:
    """요청 크기. 'match'는 원본 비율에 가장 가까운 공식 지원 크기 (비율 유지는 프롬프트로)."""
    if setting != "match":
        return setting
    ratio = width / height if height else 1.0
    if ratio < 0.83:
        return PORTRAIT
    if ratio > 1.2:
        return LANDSCAPE
    return SQUARE
