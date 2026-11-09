"""오디오 실제 형식 검증 (DB·Storage 없이)."""

import pytest

from app.core.exceptions import UnprocessableError
from app.services.audio import (
    check_declared_audio,
    detect_audio_type,
    inspect_audio,
    normalize_content_type,
)
from tests.fake_storage import audio_bytes, image_bytes

ALLOWED = ["audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav"]
LIMITS = {"allowed": ALLOWED, "max_bytes": 100_000, "max_duration_seconds": 600}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("audio/webm;codecs=opus", "audio/webm"),
        ("Audio/OGG; codecs=opus", "audio/ogg"),
        ("audio/x-m4a", "audio/mp4"),
        ("audio/x-wav", "audio/wav"),
        ("audio/mp3", "audio/mpeg"),
    ],
)
def test_normalize_content_type(raw: str, expected: str) -> None:
    assert normalize_content_type(raw) == expected


@pytest.mark.parametrize(
    ("kind", "mime"),
    [
        ("webm", "audio/webm"),
        ("ogg", "audio/ogg"),
        ("mp4", "audio/mp4"),
        ("mp3", "audio/mpeg"),
        ("wav", "audio/wav"),
    ],
)
def test_valid_audio(kind: str, mime: str) -> None:
    info = inspect_audio(audio_bytes(kind), declared_type=mime, **LIMITS)
    assert info.content_type == mime and len(info.sha256) == 64
    assert info.duration_ms == (1000 if kind == "wav" else None)


@pytest.mark.parametrize(
    ("data", "declared", "code"),
    [
        (b"#!/bin/sh\nrm -rf /\n" * 4, "audio/webm", "INVALID_AUDIO"),
        (image_bytes("PNG"), "audio/mpeg", "INVALID_AUDIO"),  # 이미지
        (audio_bytes("ogg"), "audio/webm", "INVALID_AUDIO"),  # 선언과 실제 형식 다름
        (b"OggS" + b"\x00" * 100, "audio/ogg", "INVALID_AUDIO"),  # Ogg지만 오디오 코덱 없음
        (b"RIFF\x00\x00\x00\x00WAVEfmt " + b"\x00" * 8, "audio/wav", "INVALID_AUDIO"),
        (b"short", "audio/webm", "INVALID_AUDIO"),
        (b"\x1a\x45\xdf\xa3" + b"\x00" * 200_000, "audio/webm", "FILE_TOO_LARGE"),
    ],
)
def test_invalid_audio(data: bytes, declared: str, code: str) -> None:
    with pytest.raises(UnprocessableError) as exc:
        inspect_audio(data, declared_type=declared, **LIMITS)
    assert str(exc.value.code) == code


def test_wav_too_long_and_mkv_rejected() -> None:
    with pytest.raises(UnprocessableError) as exc:
        inspect_audio(
            audio_bytes("wav"),
            declared_type="audio/wav",
            allowed=ALLOWED,
            max_bytes=100_000,
            max_duration_seconds=0,
        )
    assert str(exc.value.code) == "AUDIO_TOO_LONG"
    # Matroska지만 webm이 아닌 파일 (예: mkv 비디오)
    assert detect_audio_type(b"\x1a\x45\xdf\xa3" + b"\x42\x82\x88matroska" + b"\x00" * 40) is None


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"content_type": "video/mp4"}, "UNSUPPORTED_FILE_TYPE"),
        ({"file_name": "voice.exe"}, "UNSUPPORTED_FILE_TYPE"),
        ({"file_size": 200_000}, "FILE_TOO_LARGE"),
        ({"duration_ms": 601_000}, "AUDIO_TOO_LONG"),
    ],
)
def test_declared_audio_checks(kwargs: dict, code: str) -> None:  # type: ignore[type-arg]
    values = {
        "content_type": "audio/webm",
        "file_name": "voice.webm",
        "file_size": 1000,
        "duration_ms": 5000,
    } | kwargs
    with pytest.raises(UnprocessableError) as exc:
        check_declared_audio(
            values["content_type"],
            values["file_name"],
            values["file_size"],
            values["duration_ms"],
            allowed=ALLOWED,
            max_bytes=100_000,
            max_duration_seconds=600,
        )
    assert str(exc.value.code) == code
