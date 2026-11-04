"""시험 타이머 계산 (순수 함수, DB 없음).

- 남은 시간은 저장하지 않고 '지금'(서버 UTC)과 저장된 started_at / ends_at / 단계 target_at으로
  계산한다.
- 상태가 RUNNING이라도 ends_at이 지났으면 응답에서는 ENDED(TIME_UP)로 보여준다. DB 반영은 다음 쓰기
  작업(종료·단계 변경·같은 반의 새 시험 시작)에서 한다.
- 단계 목표의 의미: SKETCH target_at = 이 시각까지 스케치를 마치고 PROGRESS로 넘어간다.
  따라서 지금 해야 할 단계(expected_stage)는 '아직 목표 시각이 지나지 않은 첫 단계',
  모두 지났으면 DONE.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.models.enums import (
    ARTWORK_STAGE_ORDER,
    EXAM_WORK_STAGE_ORDER,
    ArtworkStage,
    ExamEndReason,
    ExamSessionStatus,
    ExamWorkStage,
)
from app.schemas.exams import ExamTimer, TimerStage


class _Session(Protocol):
    status: ExamSessionStatus
    total_minutes: int
    started_at: datetime | None
    ends_at: datetime | None
    ended_at: datetime | None
    end_reason: ExamEndReason | None


class _Stage(Protocol):
    stage: ArtworkStage
    offset_minutes: int
    target_at: datetime | None


@dataclass(frozen=True, slots=True)
class EffectiveState:
    status: ExamSessionStatus
    end_reason: ExamEndReason | None
    ended_at: datetime | None


def effective_state(session: _Session, now: datetime) -> EffectiveState:
    if (
        session.status == ExamSessionStatus.RUNNING
        and session.ends_at is not None
        and now >= session.ends_at
    ):
        return EffectiveState(ExamSessionStatus.ENDED, ExamEndReason.TIME_UP, session.ends_at)
    return EffectiveState(session.status, session.end_reason, session.ended_at)


def _seconds(delta_seconds: float) -> int:
    return max(0, int(delta_seconds))


def build_timer(session: _Session, stages: list[_Stage], now: datetime) -> ExamTimer:
    state = effective_state(session, now)
    running = state.status == ExamSessionStatus.RUNNING
    total = session.total_minutes * 60
    if session.started_at is None:
        elapsed = 0
    else:
        until = now if running else (state.ended_at or now)
        elapsed = min(total, _seconds((until - session.started_at).total_seconds()))
    remaining = (
        _seconds((session.ends_at - now).total_seconds()) if running and session.ends_at else 0
    )
    if state.status == ExamSessionStatus.SCHEDULED:
        remaining = total

    ordered = sorted(stages, key=lambda s: ARTWORK_STAGE_ORDER.index(s.stage))
    items = [
        TimerStage(
            stage=s.stage,
            offset_minutes=s.offset_minutes,
            target_at=s.target_at,
            seconds_remaining=_seconds((s.target_at - now).total_seconds())
            if running and s.target_at
            else None,
            passed=s.target_at is not None and now >= s.target_at,
        )
        for s in ordered
    ]
    upcoming = next((i for i in items if not i.passed), None) if running else None
    expected: ExamWorkStage | None = None
    if running:
        expected = ExamWorkStage(upcoming.stage) if upcoming else ExamWorkStage.DONE
    next_alert = None
    if running:
        next_alert = upcoming.target_at if upcoming and upcoming.target_at else session.ends_at
    return ExamTimer(
        server_time=now,
        status=state.status,
        end_reason=state.end_reason,
        started_at=session.started_at,
        ends_at=session.ends_at,
        ended_at=state.ended_at,
        total_seconds=total,
        elapsed_seconds=elapsed,
        remaining_seconds=remaining,
        stages=items,
        expected_stage=expected,
        current_target=upcoming,
        next_alert_at=next_alert,
    )


def is_behind(current: ExamWorkStage, timer: ExamTimer) -> bool:
    if timer.status != ExamSessionStatus.RUNNING or timer.expected_stage is None:
        return False
    return EXAM_WORK_STAGE_ORDER.index(current) < EXAM_WORK_STAGE_ORDER.index(timer.expected_stage)
