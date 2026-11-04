"""시간대 처리 원칙 (v0.3~).

- 시각 (출석 체크 시각, 과제 마감, 생성·수정 일시): `timestamptz`.
  UTC로 저장하고 응답은 ISO 8601 + 오프셋.
- 운영 날짜 (출석일, 수업일, 주제 날짜, 개인 할 일 날짜): `date`.
  학원 현지(Asia/Seoul) 달력 날짜.
- 정규 수업 시간 (매주 화 16:00~18:00): `time` (시간대 없음). 학원 현지 벽시계 시간.

- "오늘"은 항상 `local_today()` (Asia/Seoul) 로 계산한다. 서버 OS 시간대에 의존하지 않는다.
- 정규 수업의 실제 시각은 날짜 + 벽시계 시간을 Asia/Seoul로 해석해 aware datetime으로 응답한다.
- 학원별 시간대 컬럼은 아직 없다. 해외 학원을 지원할 때 `academies.timezone`을 추가하고
  아래 함수에 시간대를 인자로 넘기도록 확장한다.

테스트에서 현재 시각을 고정하려면 `app.core.timezone.utc_now`를 monkeypatch 한다
(서비스는 `clock.utc_now()` 형태로 모듈 속성을 통해 호출한다).
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

ACADEMY_TIMEZONE_NAME = "Asia/Seoul"
ACADEMY_TZ = ZoneInfo(ACADEMY_TIMEZONE_NAME)


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_local(value: datetime) -> datetime:
    return value.astimezone(ACADEMY_TZ)


def local_today() -> date:
    return to_local(utc_now()).date()


def local_datetime(day: date, wall_time: time) -> datetime:
    """학원 현지 날짜 + 벽시계 시간 → aware datetime (+09:00)."""
    return datetime.combine(day, wall_time, tzinfo=ACADEMY_TZ)


def local_day_bounds(day: date) -> tuple[datetime, datetime]:
    """현지 날짜 하루의 [시작, 다음 날 시작) 구간 (UTC aware)."""
    start = local_datetime(day, time.min)
    end = local_datetime(day + timedelta(days=1), time.min)
    return start.astimezone(UTC), end.astimezone(UTC)
