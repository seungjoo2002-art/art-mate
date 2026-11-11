"""실기시험 단계별 시간 (VER.2): 아이디어·스케치·채색·마무리.

기존 작품 타이머(artwork_timer_events)를 그대로 쓰고, 단계 경계만 타이머 누적 시간
(일시정지 제외)으로 기록한다. 서버에 장시간 프로세스가 없고, 다른 기기에서도 같은 상태를 본다.

전이
- 계획 저장(PUT plan): 단계 순서·목표 시간. 시작 전에만 구성(종류·순서)을 바꿀 수 있고,
  시작 후에는 목표 시간만 바꿀 수 있다. 목표 합계는 작품의 제한 시간이 된다.
- 타이머 START(새 세션) → 진행 기록 초기화 + 첫 단계 시작 (경과 0초)
- 다음 단계(POST next, current_stage 필수) → 현재 단계 종료 + 다음 단계 시작.
  보낸 current_stage가 지금 단계와 다르면 409 EXAM_STAGE_CONFLICT (중복 전환 방지)
- 타이머 STOP → 현재 단계 종료 / RESET → 진행 기록 초기화
시간 역전 방지: 단계 경계는 서버가 이벤트로 계산한 누적 시간이라 단조 증가한다 (CHECK로도 보장).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import ConflictError, ErrorCode, UnprocessableError
from app.models.artwork import Artwork, ArtworkExamStage
from app.models.enums import EXAM_STAGE_LABELS, TimerEventType, TimerState
from app.models.profile import Profile
from app.schemas.artworks import (
    ArtworkExamNext,
    ArtworkExamPlan,
    ArtworkExamRead,
    ArtworkExamStageRead,
)


async def stages_of(session: AsyncSession, artwork_id: uuid.UUID) -> list[ArtworkExamStage]:
    return list(
        (
            await session.execute(
                select(ArtworkExamStage)
                .where(ArtworkExamStage.artwork_id == artwork_id)
                .order_by(ArtworkExamStage.position)
                .with_for_update()
            )
        ).scalars()
    )


async def latest_boundary(session: AsyncSession, artwork_id: uuid.UUID) -> datetime | None:
    """가장 최근 단계 경계 시각. 이보다 이른 타이머 이벤트는 시간 역전이라 받지 않는다."""
    rows = (
        await session.execute(
            select(ArtworkExamStage.started_at, ArtworkExamStage.ended_at).where(
                ArtworkExamStage.artwork_id == artwork_id
            )
        )
    ).all()
    times = [t for row in rows for t in row if t is not None]
    return max(times) if times else None


def current_stage(stages: list[ArtworkExamStage]) -> ArtworkExamStage | None:
    return next((s for s in stages if s.started_at is not None and s.ended_at is None), None)


def _clear(stages: list[ArtworkExamStage]) -> None:
    for s in stages:
        s.started_elapsed = s.ended_elapsed = None
        s.started_at = s.ended_at = None


async def on_timer_event(
    session: AsyncSession, artwork_id: uuid.UUID, event: TimerEventType, elapsed: int, at: datetime
) -> None:
    """작품 타이머 이벤트에 맞춰 단계 진행을 갱신 (타이머 서비스가 같은 트랜잭션에서 호출)."""
    stages = await stages_of(session, artwork_id)
    if not stages:
        return
    if event == TimerEventType.START:
        _clear(stages)
        await session.flush()
        stages[0].started_elapsed, stages[0].started_at = 0, at
    elif event == TimerEventType.STOP:
        active = current_stage(stages)
        if active is not None:
            active.ended_elapsed, active.ended_at = max(elapsed, active.started_elapsed or 0), at
    elif event == TimerEventType.RESET:
        _clear(stages)


class ExamStageService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        from app.services.artwork_timer import ArtworkTimerService  # 순환 import 방지

        self.session = session
        self.timer = ArtworkTimerService(session, settings)

    async def _read(self, artwork: Artwork, stages: list[ArtworkExamStage]) -> ArtworkExamRead:
        timer = await self.timer.read(artwork)
        elapsed = timer.elapsed_seconds
        items = []
        for s in stages:
            if s.started_elapsed is None:
                spent, status = 0, "PENDING"
            elif s.ended_elapsed is not None:
                spent, status = s.ended_elapsed - s.started_elapsed, "DONE"
            else:
                spent, status = max(0, elapsed - s.started_elapsed), "ACTIVE"
            items.append(
                ArtworkExamStageRead(
                    stage=s.stage,
                    label=EXAM_STAGE_LABELS[s.stage],
                    position=s.position,
                    target_minutes=s.target_minutes,
                    status=status,  # type: ignore[arg-type]
                    elapsed_seconds=spent,
                    over_target=spent > s.target_minutes * 60,
                    started_at=s.started_at,
                    ended_at=s.ended_at,
                )
            )
        active = current_stage(stages)
        return ArtworkExamRead(
            artwork_id=artwork.id,
            stages=items,
            current_stage=active.stage if active else None,
            total_target_minutes=sum(s.target_minutes for s in stages),
            timer=timer,
        )

    async def get(self, owner: Profile, artwork_id: uuid.UUID) -> ArtworkExamRead:
        artwork = await self.timer.artworks.owned(owner, artwork_id)
        return await self._read(artwork, await stages_of(self.session, artwork.id))

    async def save_plan(
        self, owner: Profile, artwork_id: uuid.UUID, data: ArtworkExamPlan
    ) -> ArtworkExamRead:
        artwork = await self.timer.artworks.owned(owner, artwork_id, for_update=True)
        stages = await stages_of(self.session, artwork.id)
        started = any(s.started_at is not None for s in stages)
        wanted = [(p.stage, p.target_minutes) for p in data.stages]
        if started:
            if [s.stage for s in stages] != [stage for stage, _ in wanted]:
                raise ConflictError(
                    "Stages cannot be reordered after the exam started; only targets can change",
                    code=ErrorCode.EXAM_ALREADY_STARTED,
                )
            for s, (_, minutes) in zip(stages, wanted, strict=True):
                s.target_minutes = minutes
        else:
            for s in stages:
                await self.session.delete(s)
            await self.session.flush()
            for position, (stage, minutes) in enumerate(wanted):
                self.session.add(
                    ArtworkExamStage(
                        id=uuid.uuid4(),
                        artwork_id=artwork.id,
                        owner_id=owner.id,
                        stage=stage,
                        position=position,
                        target_minutes=minutes,
                    )
                )
        total = sum(minutes for _, minutes in wanted)
        if total > 1440:
            raise UnprocessableError("The total target time must be at most 1440 minutes")
        artwork.time_limit_minutes = total
        await self.session.commit()
        return await self.get(owner, artwork.id)

    async def next_stage(
        self, owner: Profile, artwork_id: uuid.UUID, data: ArtworkExamNext
    ) -> ArtworkExamRead:
        artwork = await self.timer.artworks.owned(owner, artwork_id, for_update=True)
        stages = await stages_of(self.session, artwork.id)
        if not stages:
            raise ConflictError("Save the exam stage plan first", code=ErrorCode.EXAM_PLAN_REQUIRED)
        timer = await self.timer.read(artwork)
        if timer.state not in (TimerState.RUNNING, TimerState.PAUSED):
            raise ConflictError(
                "Start the exam timer first",
                code=ErrorCode.EXAM_NOT_RUNNING,
                details={"timer_state": timer.state.value},
            )
        active = current_stage(stages)
        if active is None or active.stage != data.current_stage:
            raise ConflictError(
                "The exam is already on another stage; reload it",
                code=ErrorCode.EXAM_STAGE_CONFLICT,
                details={"current_stage": active.stage.value if active else None},
            )
        index = stages.index(active)
        if index == len(stages) - 1:
            raise ConflictError(
                "This is the last stage; stop the timer to finish", code=ErrorCode.EXAM_LAST_STAGE
            )
        now = clock.utc_now()
        elapsed = max(timer.elapsed_seconds, active.started_elapsed or 0)
        active.ended_elapsed, active.ended_at = elapsed, now
        following = stages[index + 1]
        following.started_elapsed, following.started_at = elapsed, now
        await self.session.commit()
        return await self.get(owner, artwork.id)
