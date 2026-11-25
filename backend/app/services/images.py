"""업로드된 이미지 바이트 검증 (확장자·MIME 선언과 별개로 실제 파일 형식을 확인한다)."""

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from app.core.exceptions import ErrorCode, UnprocessableError

# Pillow 형식 이름 → MIME
FORMAT_MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
# MIME → 저장 확장자, 허용되는 원본 파일 확장자
MIME_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "image/jpeg": ("jpg", "jpeg"),
    "image/png": ("png",),
    "image/webp": ("webp",),
}


# 일부 휴대폰·앱이 보내는 비표준 JPEG MIME (같은 형식으로 취급)
MIME_ALIASES = {"image/jpg": "image/jpeg", "image/pjpeg": "image/jpeg"}
# HEIC·HEIF(ISO BMFF 'ftyp' 상자): 앱이 JPEG로 바꿔 올린다. 그대로 오면 형식 안내 오류
_HEIF_BRANDS = (b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1", b"heif")


def normalize_content_type(content_type: str) -> str:
    """클라이언트가 알려 준 MIME 정리 (대소문자·공백·비표준 JPEG 별칭)."""
    value = content_type.strip().lower()
    return MIME_ALIASES.get(value, value)


def _looks_like_heif(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and any(brand in data[8:64] for brand in _HEIF_BRANDS)


@dataclass(frozen=True, slots=True)
class ImageInfo:
    content_type: str
    width: int
    height: int
    size_bytes: int
    sha256: str


def storage_extension(content_type: str) -> str:
    return MIME_EXTENSIONS[content_type][0]


def check_declared_file(
    content_type: str,
    file_name: str | None,
    file_size: int,
    *,
    allowed: list[str],
    max_bytes: int,
) -> None:
    """업로드 요청 단계의 1차 검증 (파일을 받기 전, 클라이언트가 알려준 정보)."""
    if content_type not in allowed:
        raise UnprocessableError(
            f"Unsupported file type. Allowed: {', '.join(allowed)}",
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
        )
    if file_name is not None:
        extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if extension not in MIME_EXTENSIONS[content_type]:
            raise UnprocessableError(
                "File extension does not match content_type",
                code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            )
    if file_size > max_bytes:
        raise UnprocessableError(
            f"File is larger than {max_bytes} bytes", code=ErrorCode.FILE_TOO_LARGE
        )


def inspect_image(
    data: bytes, *, declared_type: str, allowed: list[str], max_bytes: int, max_pixels: int
) -> ImageInfo:
    """실제 바이트로 형식·크기·픽셀 수를 검증한다. 실패하면 422."""
    if len(data) > max_bytes:
        raise UnprocessableError(
            f"File is larger than {max_bytes} bytes", code=ErrorCode.FILE_TOO_LARGE
        )
    if not data:
        raise UnprocessableError("Uploaded file is empty", code=ErrorCode.INVALID_IMAGE)
    if _looks_like_heif(data):
        raise UnprocessableError(
            "HEIC/HEIF must be converted to JPEG before upload",
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image_format = image.format
                width, height = image.size
                if width * height > max_pixels:
                    raise UnprocessableError(
                        "Image has too many pixels", code=ErrorCode.INVALID_IMAGE
                    )
                image.verify()  # 잘린 파일·손상된 데이터 검출
    except UnprocessableError:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise UnprocessableError(
            "The file is not a valid image", code=ErrorCode.INVALID_IMAGE
        ) from None

    actual = FORMAT_MIME.get(image_format or "")
    if actual is None or actual not in allowed:
        raise UnprocessableError("Unsupported image format", code=ErrorCode.UNSUPPORTED_FILE_TYPE)
    if actual != declared_type:
        raise UnprocessableError(
            "File content does not match the declared content_type",
            code=ErrorCode.INVALID_IMAGE,
        )
    return ImageInfo(
        content_type=actual,
        width=width,
        height=height,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
