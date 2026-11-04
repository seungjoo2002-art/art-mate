"""업로드된 오디오 바이트 검증 (파일 시그니처 기반, 외부 디코더 없음).

MediaRecorder 기본 형식
- Chrome·Edge·Firefox(최신): audio/webm;codecs=opus
- Firefox: audio/ogg;codecs=opus
- Safari(iOS·macOS): audio/mp4 (AAC)

녹음 길이는 브라우저가 측정한 값(duration_ms)을 범위 검증해서 저장한다. WebM/MP4/Ogg 헤더에는
길이가 없거나 신뢰하기 어려워서, 서버가 직접 계산하는 것은 WAV(헤더)뿐이다.
"""

import hashlib
import struct
from dataclasses import dataclass

from app.core.exceptions import ErrorCode, UnprocessableError

# MIME 별칭 → 표준 MIME
ALIASES = {
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/x-m4a": "audio/mp4",
    "audio/m4a": "audio/mp4",
    "audio/mp3": "audio/mpeg",
}
# 표준 MIME → (저장 확장자, 허용 원본 확장자)
EXTENSIONS: dict[str, tuple[str, ...]] = {
    "audio/webm": ("webm",),
    "audio/ogg": ("ogg", "oga", "opus"),
    "audio/mp4": ("m4a", "mp4"),
    "audio/mpeg": ("mp3",),
    "audio/wav": ("wav",),
}


def normalize_content_type(value: str) -> str:
    """'audio/webm;codecs=opus' → 'audio/webm', 별칭 정규화."""
    base = value.split(";", 1)[0].strip().lower()
    return ALIASES.get(base, base)


def storage_extension(content_type: str) -> str:
    return EXTENSIONS[content_type][0]


@dataclass(frozen=True, slots=True)
class AudioInfo:
    content_type: str
    size_bytes: int
    sha256: str
    duration_ms: int | None  # 서버가 계산한 길이 (WAV만)


def check_declared_audio(
    content_type: str,
    file_name: str | None,
    file_size: int,
    duration_ms: int,
    *,
    allowed: list[str],
    max_bytes: int,
    max_duration_seconds: int,
) -> None:
    if content_type not in allowed:
        raise UnprocessableError(
            f"Unsupported audio type. Allowed: {', '.join(allowed)}",
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
        )
    if file_name is not None:
        extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if extension not in EXTENSIONS[content_type]:
            raise UnprocessableError(
                "File extension does not match content_type", code=ErrorCode.UNSUPPORTED_FILE_TYPE
            )
    if file_size > max_bytes:
        raise UnprocessableError(
            f"File is larger than {max_bytes} bytes", code=ErrorCode.FILE_TOO_LARGE
        )
    if duration_ms > max_duration_seconds * 1000:
        raise UnprocessableError(
            f"Recording is longer than {max_duration_seconds} seconds",
            code=ErrorCode.AUDIO_TOO_LONG,
        )


def detect_audio_type(data: bytes) -> str | None:
    head = data[:4096]
    if head[:4] == b"\x1a\x45\xdf\xa3":  # EBML (Matroska/WebM)
        return "audio/webm" if b"webm" in head[:64] else None
    if head[:4] == b"OggS":
        return "audio/ogg" if (b"OpusHead" in head or b"\x01vorbis" in head) else None
    if len(head) >= 12 and head[4:8] == b"ftyp":
        return "audio/mp4"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    return None


def wav_duration_ms(data: bytes) -> int | None:
    """RIFF 청크를 따라가 fmt의 byte_rate와 data 크기로 길이를 계산한다."""
    offset, byte_rate, data_size = 12, None, None
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        (size,) = struct.unpack("<I", data[offset + 4 : offset + 8])
        body = offset + 8
        if chunk_id == b"fmt " and size >= 16:
            byte_rate = struct.unpack("<I", data[body + 8 : body + 12])[0]
        elif chunk_id == b"data":
            data_size = min(size, len(data) - body)
            break
        offset = body + size + (size % 2)
    if not byte_rate or data_size is None:
        return None
    return int(data_size * 1000 / byte_rate)


def inspect_audio(
    data: bytes,
    *,
    declared_type: str,
    allowed: list[str],
    max_bytes: int,
    max_duration_seconds: int,
) -> AudioInfo:
    if len(data) > max_bytes:
        raise UnprocessableError(
            f"File is larger than {max_bytes} bytes", code=ErrorCode.FILE_TOO_LARGE
        )
    if len(data) < 16:
        raise UnprocessableError("The file is not a valid audio file", code=ErrorCode.INVALID_AUDIO)
    actual = detect_audio_type(data)
    if actual is None:
        raise UnprocessableError("The file is not a valid audio file", code=ErrorCode.INVALID_AUDIO)
    if actual not in allowed:
        raise UnprocessableError("Unsupported audio format", code=ErrorCode.UNSUPPORTED_FILE_TYPE)
    if actual != declared_type:
        raise UnprocessableError(
            "File content does not match the declared content_type",
            code=ErrorCode.INVALID_AUDIO,
        )
    duration = None
    if actual == "audio/wav":
        duration = wav_duration_ms(data)
        if duration is None or duration <= 0:
            raise UnprocessableError("The WAV file has no audio data", code=ErrorCode.INVALID_AUDIO)
        if duration > max_duration_seconds * 1000:
            raise UnprocessableError(
                f"Recording is longer than {max_duration_seconds} seconds",
                code=ErrorCode.AUDIO_TOO_LONG,
            )
    return AudioInfo(
        content_type=actual,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        duration_ms=duration,
    )
