"""정규 수업 펼치기·예외 적용·시간대 (DB 없이)."""

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.core import timezone as clock
from app.core.exceptions import UnprocessableError
from app.models.enums import ScheduleExceptionKind
from app.services.schedules import expand_occurrences, is_occurrence, validate_range

CLASS_ID = uuid.uuid4()
NAMES = {CLASS_ID: "A반"}
MON = dt.date(2026, 11, 9)


def schedule(**kw: Any) -> Any:
    values = {
        "id": uuid.uuid4(),
        "class_id": CLASS_ID,
        "weekday": 1,
        "start_time": dt.time(16),
        "end_time": dt.time(18),
        "effective_from": MON,
        "effective_until": None,
        "location": None,
        "is_active": True,
    } | kw
    return SimpleNamespace(**values)


def exception(kind: ScheduleExceptionKind, **kw: Any) -> Any:
    values = {
        "id": uuid.uuid4(),
        "class_id": CLASS_ID,
        "kind": kind,
        "schedule_id": None,
        "original_date": None,
        "session_date": None,
        "start_time": None,
        "end_time": None,
        "location": None,
        "student_membership_id": None,
        "reason": None,
        "is_active": True,
    } | kw
    return SimpleNamespace(**values)


def _expand(schedules: list, exceptions: list, start: dt.date, end: dt.date, **kw: Any) -> list:
    return expand_occurrences(
        NAMES, schedules, exceptions, start, end, **({"student_id": None} | kw)
    )


def test_weekly_expansion_respects_effective_range() -> None:
    s = schedule(
        effective_from=MON + dt.timedelta(days=7), effective_until=MON + dt.timedelta(days=14)
    )
    result = _expand([s], [], MON, MON + dt.timedelta(days=30))
    assert [o.date for o in result] == [dt.date(2026, 11, 17)]
    assert result[0].starts_at.isoformat() == "2026-11-17T16:00:00+09:00"
    assert result[0].starts_at.astimezone(dt.UTC).hour == 7


def test_inactive_schedule_and_its_reschedule_are_hidden() -> None:
    s = schedule(is_active=False)
    moved = exception(
        ScheduleExceptionKind.RESCHEDULE,
        schedule_id=s.id,
        original_date=dt.date(2026, 11, 10),
        session_date=dt.date(2026, 11, 11),
        start_time=dt.time(9),
        end_time=dt.time(10),
    )
    assert _expand([s], [moved], MON, MON + dt.timedelta(days=6)) == []


def test_reschedule_to_another_week() -> None:
    s = schedule()
    moved = exception(
        ScheduleExceptionKind.RESCHEDULE,
        schedule_id=s.id,
        original_date=dt.date(2026, 11, 10),
        session_date=dt.date(2026, 11, 20),
        start_time=dt.time(9),
        end_time=dt.time(10),
    )
    assert _expand([s], [moved], MON, MON + dt.timedelta(days=6)) == []
    later = _expand([s], [moved], dt.date(2026, 11, 16), dt.date(2026, 11, 22))
    assert [(o.date, o.status, o.original_date) for o in later] == [
        (dt.date(2026, 11, 17), "SCHEDULED", None),
        (dt.date(2026, 11, 20), "RESCHEDULED", dt.date(2026, 11, 10)),
    ]


def test_individual_makeup_visibility() -> None:
    me, other = uuid.uuid4(), uuid.uuid4()
    makeups = [
        exception(
            ScheduleExceptionKind.MAKEUP,
            session_date=MON,
            start_time=dt.time(9),
            end_time=dt.time(10),
            student_membership_id=sid,
        )
        for sid in (me, other, None)
    ]
    mine = _expand([], makeups, MON, MON, student_id=me)
    assert {o.student_membership_id for o in mine} == {me, None}
    assert len(_expand([], makeups, MON, MON)) == 3


def test_is_occurrence_and_range_validation() -> None:
    s = schedule(effective_until=MON + dt.timedelta(days=8))
    assert is_occurrence(s, dt.date(2026, 11, 10))
    assert not is_occurrence(s, dt.date(2026, 11, 11))  # 수요일
    assert not is_occurrence(s, dt.date(2026, 11, 24))  # 종료 후
    validate_range(MON, MON, 1)
    with pytest.raises(UnprocessableError):
        validate_range(MON, MON - dt.timedelta(days=1), 10)
    with pytest.raises(UnprocessableError):
        validate_range(MON, MON + dt.timedelta(days=10), 10)


def test_seoul_day_bounds_and_today(monkeypatch: pytest.MonkeyPatch) -> None:
    start, end = clock.local_day_bounds(dt.date(2026, 11, 9))
    assert start == dt.datetime(2026, 11, 8, 15, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 11, 9, 15, tzinfo=dt.UTC)
    monkeypatch.setattr(clock, "utc_now", lambda: dt.datetime(2026, 11, 8, 15, tzinfo=dt.UTC))
    assert clock.local_today() == dt.date(2026, 11, 9)
