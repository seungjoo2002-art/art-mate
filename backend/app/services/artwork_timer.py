"""작품 타이머 (v0.9 F-2). 서버는 이벤트를 기록하고 상태를 계산만 한다 (장시간 프로세스 없음).

상태 전이
    IDLE ─START→ RUNNING ─PAUSE→ PAUSED ─RESUME→ RUNNING
    RUNNING/PAUSED ─STOP→ STOPPED (누적 시간 → artworks.actual_minutes, time_source=TIMER)
    STOPPED ─START→ RUNNING (새 세션, 0초부터) / 어느 상태든 ─RESET→ IDLE (기록 버림)

검증: 허용되지 않는 전이 409 `TIMER_INVALID_TRANSITION`, 시각이 직전 이벤트보다 이르거나
미래·24시간 이전이면 422 `TIMER_INVALID_TIME`, 누적이 24시간을 넘으면 422 `TIMER_TOO_LONG`
(RESET으로 버리거나 actual_minutes를 직접 입력). 같은 작품의 이벤트는 작품 행 잠금으로 직렬화.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import ConflictError, ErrorCode, UnprocessableError
from app.models.artwork import MAX_WORK_MINUTES, Artwork, ArtworkTimerEvent
from app.models.enums import TimerEventType, TimerState, TimeSource
from app.models.profile import Profile
from app.schemas.artworks import TimerEventCreate, TimerEventRead, TimerRead
from app.services.artworks import ArtworkService
from app.services.exam_stages import latest_boundary, on_timer_event

MAX_SECONDS = MAX_WORK_MINUTES * 60
CLOCK_SKEW = timedelta(minutes=2)
MAX_BACKDATE = timedelta(hours=24)

ALLOWED: dict[TimerState, set[TimerEventType]] = {
    TimerState.IDLE: {TimerEventType.START},
    TimerState.RUNNING: {TimerEventType.PAUSE, TimerEventType.STOP, TimerEventType.RESET},
    TimerState.PAUSED: {TimerEventType.RESUME, TimerEventType.STOP, TimerEventType.RESET},
    TimerState.STOPPED: {TimerEventType.START, TimerEventType.RESET},
}


@dataclass
class Replay:
    state: TimerState = TimerState.IDLE
    elapsed: float = 0.0  # 직전 이벤트까지 누적 (초)
    running_since: datetime | None = None
    session_started_at: datetime | None = None
    last_at: datetime | None = None
    session_events: list[ArtworkTimerEvent] = field(default_factory=list)

    def apply(self, event_type: TimerEventType, at: datetime) -> None:
        if event_type == TimerEventType.START:
            self.state, self.elapsed = TimerState.RUNNING, 0.0
            self.running_since = self.session_started_at = at
            self.session_events = []
        elif event_type == TimerEventType.PAUSE:
            self.elapsed += self._run(at)
            self.state, self.running_since = TimerState.PAUSED, None
        elif event_type == TimerEventType.RESUME:
            self.state, self.running_since = TimerState.RUNNING, at
        elif event_type == TimerEventType.STOP:
            self.elapsed += self._run(at)
            self.state, self.running_since = TimerState.STOPPED, None
        else:  # RESET
            self.state, self.elapsed = TimerState.IDLE, 0.0
            self.running_since = self.session_started_at = None
            self.session_events = []
        self.last_at = at

    def _run(self, at: datetime) -> float:
        return (at - self.running_since).total_seconds() if self.running_since else 0.0

    def elapsed_at(self, now: datetime) -> int:
        extra = self._run(now) if self.state == TimerState.RUNNING else 0.0
        return max(0, int(self.elapsed + extra))


def replay(events: list[ArtworkTimerEvent]) -> Replay:
    r = Replay()
    for e in events:
        r.apply(e.event_type, e.occurred_at)
        if e.event_type != TimerEventType.RESET:
            r.session_events.append(e)
    return r


class ArtworkTimerService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.artworks = ArtworkService(session, settings)

    async def _events(self, artwork_id: uuid.UUID) -> list[ArtworkTimerEvent]:
        return list(
            (
                await self.session.execute(
                    select(ArtworkTimerEvent)
                    .where(ArtworkTimerEvent.artwork_id == artwork_id)
                    .order_by(ArtworkTimerEvent.occurred_at, ArtworkTimerEvent.created_at)
                )
            ).scalars()
        )

    def _read(self, artwork: Artwork, r: Replay, now: datetime) -> TimerRead:
        elapsed = r.elapsed_at(now)
        limit = artwork.time_limit_minutes
        remaining = limit * 60 - elapsed if limit is not None else None
        return TimerRead(
            artwork_id=artwork.id,
            state=r.state,
            elapsed_seconds=elapsed,
            running_since=r.running_since if r.state == TimerState.RUNNING else None,
            session_started_at=r.session_started_at,
            time_limit_minutes=limit,
            remaining_seconds=remaining,
            over_time_limit=(remaining < 0) if remaining is not None else None,
            actual_minutes=artwork.actual_minutes,
            time_source=artwork.time_source,
            server_time=now,
            events=[
                TimerEventRead(
                    id=e.id,
                    event=e.event_type,
                    occurred_at=e.occurred_at,
                    elapsed_seconds=e.elapsed_seconds,
                )
                for e in r.session_events[-50:]
            ],
        )

    async def read(self, artwork: Artwork) -> TimerRead:
        """이미 권한을 확인한 작품의 현재 타이머 상태."""
        return self._read(artwork, replay(await self._events(artwork.id)), clock.utc_now())

    async def get(self, owner: Profile, artwork_id: uuid.UUID) -> TimerRead:
        artwork = await self.artworks.owned(owner, artwork_id)
        return self._read(artwork, replay(await self._events(artwork.id)), clock.utc_now())

    async def record(
        self, owner: Profile, artwork_id: uuid.UUID, data: TimerEventCreate
    ) -> TimerRead:
        artwork = await self.artworks.owned(owner, artwork_id, for_update=True)
        r = replay(await self._events(artwork.id))
        now = clock.utc_now()
        if data.event not in ALLOWED[r.state]:
            raise ConflictError(
                f"{data.event.value} is not allowed while the timer is {r.state.value}",
                code=ErrorCode.TIMER_INVALID_TRANSITION,
                details={
                    "state": r.state.value,
                    "allowed": sorted(e.value for e in ALLOWED[r.state]),
                },
            )
        at = data.occurred_at or now
        if at > now + CLOCK_SKEW or at < now - MAX_BACKDATE or (r.last_at and at < r.last_at):
            raise UnprocessableError(
                "occurred_at must be between the previous event and now",
                code=ErrorCode.TIMER_INVALID_TIME,
            )
        at = min(at, now)
        boundary = await latest_boundary(self.session, artwork.id)
        if boundary is not None and at < boundary and data.event != TimerEventType.RESET:
            # 단계 전환 뒤에 그보다 이른 시각의 이벤트(오프라인 큐 등)가 오면 시간 역전
            raise UnprocessableError(
                "occurred_at is earlier than the last exam stage change",
                code=ErrorCode.TIMER_INVALID_TIME,
            )
        r.apply(data.event, at)
        elapsed = r.elapsed_at(at)
        if data.event != TimerEventType.RESET and elapsed > MAX_SECONDS:
            raise UnprocessableError(
                "The timer ran longer than 24 hours; reset it or enter the time manually",
                code=ErrorCode.TIMER_TOO_LONG,
                details={"max_minutes": MAX_WORK_MINUTES},
            )
        event = ArtworkTimerEvent(
            id=uuid.uuid4(),
            artwork_id=artwork.id,
            owner_id=owner.id,
            event_type=data.event,
            occurred_at=at,
            elapsed_seconds=elapsed,
        )
        self.session.add(event)
        # VER.2 실기시험 단계: START → 첫 단계 시작, STOP → 현재 단계 종료, RESET → 초기화
        await on_timer_event(self.session, artwork.id, data.event, elapsed, at)
        if data.event == TimerEventType.STOP:
            artwork.actual_minutes = min(MAX_WORK_MINUTES, max(1, math.ceil(elapsed / 60)))
            artwork.time_source = TimeSource.TIMER
        await self.session.commit()
        await self.session.refresh(artwork)
        return self._read(artwork, replay(await self._events(artwork.id)), clock.utc_now())
