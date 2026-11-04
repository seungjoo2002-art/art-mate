"""이미지 실제 형식 검증과 시험 타이머 계산 (DB·Storage 없이)."""

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.exceptions import UnprocessableError
from app.models.enums import ArtworkStage, ExamSessionStatus, ExamWorkStage
from app.services.exam_timer import build_timer, effective_state, is_behind
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


# ----------------------------------------------------------------------------- timer

START = dt.datetime(2026, 11, 10, 7, 0, tzinfo=dt.UTC)  # 서울 16:00


def _session(status: ExamSessionStatus = ExamSessionStatus.RUNNING, **kw: Any) -> Any:
    values = {
        "status": status,
        "total_minutes": 240,
        "started_at": START,
        "ends_at": START + dt.timedelta(minutes=240),
        "ended_at": None,
        "end_reason": None,
    } | kw
    return SimpleNamespace(**values)


def _stages(started: bool = True) -> list[Any]:
    offsets = {ArtworkStage.SKETCH: 60, ArtworkStage.PROGRESS: 180, ArtworkStage.FINAL: 230}
    return [
        SimpleNamespace(
            stage=stage,
            offset_minutes=minutes,
            target_at=START + dt.timedelta(minutes=minutes) if started else None,
        )
        for stage, minutes in offsets.items()
    ]


def test_timer_during_sketch() -> None:
    now = START + dt.timedelta(minutes=30, seconds=15)
    timer = build_timer(_session(), _stages(), now)
    assert timer.status == "RUNNING"
    assert timer.elapsed_seconds == 30 * 60 + 15
    assert timer.remaining_seconds == 210 * 60 - 15
    assert timer.expected_stage == "SKETCH"
    assert timer.current_target is not None and timer.current_target.stage == "SKETCH"
    assert timer.current_target.seconds_remaining == 29 * 60 + 45
    assert timer.next_alert_at == START + dt.timedelta(minutes=60)
    assert [s.passed for s in timer.stages] == [False, False, False]
    assert is_behind(ExamWorkStage.SKETCH, timer) is False


def test_timer_after_targets_passed() -> None:
    now = START + dt.timedelta(minutes=200)
    timer = build_timer(_session(), _stages(), now)
    assert timer.expected_stage == "FINAL"
    assert [s.passed for s in timer.stages] == [True, True, False]
    assert timer.stages[0].seconds_remaining == 0
    assert is_behind(ExamWorkStage.PROGRESS, timer) is True
    assert is_behind(ExamWorkStage.FINAL, timer) is False

    # 모든 목표가 지났지만 종료 전: DONE 기대, 다음 알림은 종료 시각
    late = build_timer(_session(), _stages(), START + dt.timedelta(minutes=235))
    assert late.expected_stage == "DONE" and late.current_target is None
    assert late.next_alert_at == START + dt.timedelta(minutes=240)
    assert is_behind(ExamWorkStage.FINAL, late) is True


def test_timer_time_up_and_manual_end() -> None:
    now = START + dt.timedelta(minutes=241)
    timer = build_timer(_session(), _stages(), now)
    assert (timer.status, timer.end_reason) == ("ENDED", "TIME_UP")
    assert timer.ended_at == START + dt.timedelta(minutes=240)
    assert timer.remaining_seconds == 0 and timer.elapsed_seconds == 240 * 60
    assert timer.expected_stage is None and timer.next_alert_at is None
    assert effective_state(_session(), now).status == "ENDED"

    ended = _session(
        ExamSessionStatus.ENDED, ended_at=START + dt.timedelta(minutes=90), end_reason="MANUAL"
    )
    manual = build_timer(ended, _stages(), START + dt.timedelta(minutes=120))
    assert manual.elapsed_seconds == 90 * 60 and manual.remaining_seconds == 0
    assert is_behind(ExamWorkStage.SKETCH, manual) is False


def test_timer_before_start() -> None:
    scheduled = _session(ExamSessionStatus.SCHEDULED, started_at=None, ends_at=None)
    timer = build_timer(scheduled, _stages(started=False), START)
    assert timer.remaining_seconds == 240 * 60 and timer.elapsed_seconds == 0
    assert all(s.target_at is None and s.seconds_remaining is None for s in timer.stages)
    assert timer.expected_stage is None
