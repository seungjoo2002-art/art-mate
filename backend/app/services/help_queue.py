"""질문 콜·대기열 (F-07).

상태 전이
    WAITING ──call──▶ CALLED ──start──▶ IN_PROGRESS ──complete──▶ COMPLETED
       │  ▲              │  │                 │
       │  └──requeue─────┘  └──complete───────┤ (호출 후 바로 완료도 허용)
       ├──start (호출 없이 바로 처리)──────────┘
       ├──skip / CALLED─skip──▶ SKIPPED
       └──cancel (학생: WAITING·CALLED, 강사: + IN_PROGRESS) ──▶ CANCELLED

정책
- 같은 학생·같은 반의 활성 요청은 1개 (부분 유니크 인덱스, 동시 요청도 409)
- 처리 순서: queue_seq(DB identity, INSERT 순서) 오름차순. 순번은 서버에서 계산한다
- 다음 학생 호출은 `FOR UPDATE SKIP LOCKED`: 여러 강사가 동시에 눌러도 서로 다른 학생을 호출
- 개별 전이는 행 잠금 후 현재 상태를 확인 → 중복 호출·중복 완료는 409
- 모든 전이는 help_queue_events에 기록하고, 커밋 후 publisher로 알린다 (v0.5는 no-op, 폴링)

권한
- 요청·취소·내 상태: 그 반에 배정된 학생 본인
- 대기열·호출·처리: 그 반 담당 강사 또는 OWNER/MANAGER
"""

import math
import uuid
from datetime import datetime, timedelta

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.config import Settings
from app.core.exceptions import (
    ConflictError,
    ErrorCode,
    NotFoundError,
    UnprocessableError,
)
from app.models.academy_class import AcademyClass, ClassMembership
from app.models.artwork import Artwork
from app.models.enums import (
    ACTIVE_HELP_STATUSES,
    ClassMemberRole,
    ClassMemberStatus,
    EstimateSource,
    HelpQueueEventType,
    HelpRequestStatus,
)
from app.models.help import HelpQueueEvent, HelpRequest
from app.models.membership import AcademyMembership
from app.models.profile import Profile
from app.repositories.pagination import fetch_page
from app.schemas.attendance import StudentRef
from app.schemas.common import PaginationParams
from app.schemas.help import (
    ClassEstimate,
    HelpQueue,
    HelpRequestCreate,
    MyHelpRequest,
    StaffHelpRequest,
    WaitEstimate,
)
from app.services.access import AccessService
from app.services.classes import ensure_class_active
from app.services.help_events import HelpQueueChange, HelpQueuePublisher

W, C, P = HelpRequestStatus.WAITING, HelpRequestStatus.CALLED, HelpRequestStatus.IN_PROGRESS

# 강사 동작 → (허용되는 현재 상태, 다음 상태, 이벤트)
STAFF_TRANSITIONS: dict[
    str, tuple[frozenset[HelpRequestStatus], HelpRequestStatus, HelpQueueEventType]
] = {
    "call": (frozenset({W}), C, HelpQueueEventType.CALLED),
    "requeue": (frozenset({C}), W, HelpQueueEventType.REQUEUED),
    "start": (frozenset({W, C}), P, HelpQueueEventType.STARTED),
    "complete": (frozenset({C, P}), HelpRequestStatus.COMPLETED, HelpQueueEventType.COMPLETED),
    "skip": (frozenset({W, C}), HelpRequestStatus.SKIPPED, HelpQueueEventType.SKIPPED),
    "cancel": (frozenset({W, C, P}), HelpRequestStatus.CANCELLED, HelpQueueEventType.CANCELLED),
}
STUDENT_CANCELLABLE = frozenset({W, C})

# 권장 폴링 주기 (초): 강사 대기열 / 학생 내 상태
STAFF_POLL_SECONDS = 5
STUDENT_POLL_SECONDS = 10


def _queue_order(stmt: Select) -> Select:  # type: ignore[type-arg]
    return stmt.order_by(HelpRequest.queue_seq)


def estimate_wait(
    *,
    ahead: int,
    handlers: int,
    durations: list[float],
    min_samples: int,
    default_seconds: int,
) -> WaitEstimate:
    """앞 인원 × 평균 처리시간 ÷ 담당 강사 수. 표본이 부족하면 기본 처리시간을 쓴다."""
    handlers = max(1, handlers)
    if len(durations) >= min_samples:
        average = sum(durations) / len(durations)
        source = EstimateSource.RECENT_AVERAGE
    else:
        average = float(default_seconds)
        source = EstimateSource.DEFAULT
    return WaitEstimate(
        estimated_wait_seconds=math.ceil(ahead * average / handlers),
        ahead_count=ahead,
        active_handlers=handlers,
        average_handle_seconds=round(average),
        sample_size=len(durations) if source == EstimateSource.RECENT_AVERAGE else 0,
        source=source,
        is_default=source == EstimateSource.DEFAULT,
    )


class HelpQueueService:
    def __init__(
        self, session: AsyncSession, settings: Settings, publisher: HelpQueuePublisher
    ) -> None:
        self.session = session
        self.settings = settings
        self.publisher = publisher
        self.access = AccessService(session)

    # ------------------------------------------------------------------ helpers

    def _event(
        self,
        request: HelpRequest,
        event_type: HelpQueueEventType,
        from_status: HelpRequestStatus | None,
        actor_id: uuid.UUID | None,
        at: datetime,
    ) -> HelpQueueChange:
        # created_at은 행 잠금 이후 앱 시각 (now()=트랜잭션 시작 시각이면 순서가 틀어질 수 있음)
        self.session.add(
            HelpQueueEvent(
                id=uuid.uuid4(),
                academy_id=request.academy_id,
                help_request_id=request.id,
                class_id=request.class_id,
                event_type=event_type,
                from_status=from_status,
                to_status=request.status,
                actor_membership_id=actor_id,
                created_at=at,
            )
        )
        return HelpQueueChange(
            academy_id=request.academy_id,
            class_id=request.class_id,
            help_request_id=request.id,
            event_type=event_type,
            status=request.status,
            occurred_at=at,
        )

    async def _handler_count(self, class_id: uuid.UUID) -> int:
        stmt = select(func.count()).where(
            ClassMembership.class_id == class_id,
            ClassMembership.role == ClassMemberRole.INSTRUCTOR,
            ClassMembership.status == ClassMemberStatus.ACTIVE,
        )
        return (await self.session.execute(stmt)).scalar_one()

    async def _recent_durations(self, class_id: uuid.UUID, now: datetime) -> list[float]:
        start = func.coalesce(HelpRequest.started_at, HelpRequest.called_at)
        stmt = (
            select(func.extract("epoch", HelpRequest.completed_at - start))
            .where(
                HelpRequest.class_id == class_id,
                HelpRequest.status == HelpRequestStatus.COMPLETED,
                HelpRequest.completed_at
                >= now - timedelta(days=self.settings.help_eta_window_days),
                start.is_not(None),
            )
            .order_by(HelpRequest.completed_at.desc())
            .limit(self.settings.help_eta_sample_size)
        )
        return [max(0.0, float(v)) for v in (await self.session.execute(stmt)).scalars()]

    async def _counts(self, class_id: uuid.UUID) -> tuple[int, int]:
        rows = (
            await self.session.execute(
                select(HelpRequest.status, func.count())
                .where(HelpRequest.class_id == class_id, HelpRequest.status.in_([W, C, P]))
                .group_by(HelpRequest.status)
            )
        ).all()
        counts = {status: n for status, n in rows}
        return counts.get(W, 0), counts.get(C, 0) + counts.get(P, 0)

    async def _estimate(self, class_id: uuid.UUID, ahead: int, now: datetime) -> WaitEstimate:
        return estimate_wait(
            ahead=ahead,
            handlers=await self._handler_count(class_id),
            durations=await self._recent_durations(class_id, now),
            min_samples=self.settings.help_eta_min_samples,
            default_seconds=self.settings.help_default_handle_seconds,
        )

    async def _position(self, request: HelpRequest) -> int | None:
        if request.status != W:
            return None
        ahead = (
            await self.session.execute(
                select(func.count()).where(
                    HelpRequest.class_id == request.class_id,
                    HelpRequest.status == W,
                    HelpRequest.queue_seq < request.queue_seq,
                )
            )
        ).scalar_one()
        return ahead + 1

    async def _names(self, membership_ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
        ids = [m for m in membership_ids if m is not None]
        if not ids:
            return {}
        rows = await self.session.execute(
            select(AcademyMembership.id, Profile.display_name)
            .join(Profile, Profile.id == AcademyMembership.user_id)
            .where(AcademyMembership.id.in_(ids))
        )
        return {mid: name for mid, name in rows.all()}

    async def _my_view(self, request: HelpRequest, class_name: str | None = None) -> MyHelpRequest:
        now = clock.utc_now()
        position = await self._position(request)
        estimate = None
        if position is not None:
            _, active = await self._counts(request.class_id)
            estimate = await self._estimate(request.class_id, position - 1 + active, now)
        names = await self._names({request.called_by, request.handled_by})
        if class_name is None:
            academy_class = await self.session.get(AcademyClass, request.class_id)
            class_name = academy_class.name if academy_class else ""
        return MyHelpRequest(
            **self._base(request, position, names),
            class_name=class_name,
            is_active=request.status in ACTIVE_HELP_STATUSES,
            estimate=estimate,
            server_time=now,
        )

    @staticmethod
    def _base(request: HelpRequest, position: int | None, names: dict[uuid.UUID, str]) -> dict:  # type: ignore[type-arg]
        return {
            "id": request.id,
            "class_id": request.class_id,
            "status": request.status,
            "note": request.note,
            "artwork_id": request.artwork_id,
            "requested_at": request.requested_at,
            "called_at": request.called_at,
            "started_at": request.started_at,
            "completed_at": request.completed_at,
            "closed_at": request.closed_at,
            "position": position,
            "called_by_name": names.get(request.called_by) if request.called_by else None,
            "handled_by_name": names.get(request.handled_by) if request.handled_by else None,
        }

    async def _publish(self, changes: list[HelpQueueChange]) -> None:
        for change in changes:
            await self.publisher.publish(change)

    # ------------------------------------------------------------------ student

    async def create(self, student: AcademyMembership, data: HelpRequestCreate) -> MyHelpRequest:
        academy_class = await self.access.require_class_reader(student, data.class_id)
        if await self.access.class_role(data.class_id, student.id) != ClassMemberRole.STUDENT:
            raise NotFoundError("Class not found")
        ensure_class_active(academy_class)
        if data.artwork_id is not None:
            artwork = await self.session.get(Artwork, data.artwork_id)
            if (
                artwork is None
                or artwork.owner_id != student.user_id
                or artwork.deleted_at is not None
                or artwork.academy_id not in (None, student.academy_id)
            ):
                raise UnprocessableError(
                    "The artwork is not yours", code=ErrorCode.INVALID_ARTWORK_LINK
                )
        existing = (
            await self.session.execute(
                select(HelpRequest.id).where(
                    HelpRequest.class_id == data.class_id,
                    HelpRequest.student_membership_id == student.id,
                    HelpRequest.status.in_([W, C, P]),
                )
            )
        ).first()
        if existing is not None:
            raise self._already_active(existing[0])

        now = clock.utc_now()
        request = HelpRequest(
            id=uuid.uuid4(),
            academy_id=student.academy_id,
            class_id=data.class_id,
            student_membership_id=student.id,
            artwork_id=data.artwork_id,
            note=data.note,
            status=W,
            requested_at=now,
        )
        self.session.add(request)
        try:
            await self.session.flush()
        except IntegrityError:
            # 동시에 들어온 중복 요청: 부분 유니크 uq_help_requests_active_student
            await self.session.rollback()
            raise self._already_active(None) from None
        change = self._event(request, HelpQueueEventType.CREATED, None, student.id, now)
        await self.session.commit()
        await self._publish([change])
        return await self._my_view(request, academy_class.name)

    @staticmethod
    def _already_active(request_id: uuid.UUID | None) -> ConflictError:
        return ConflictError(
            "You already have an active help request in this class",
            code=ErrorCode.HELP_REQUEST_ALREADY_ACTIVE,
            details={"help_request_id": str(request_id)} if request_id else None,
        )

    async def _mine(
        self, student: AcademyMembership, request_id: uuid.UUID, *, for_update: bool = False
    ) -> HelpRequest:
        stmt = select(HelpRequest).where(
            HelpRequest.academy_id == student.academy_id,
            HelpRequest.id == request_id,
            HelpRequest.student_membership_id == student.id,
        )
        if for_update:
            stmt = stmt.with_for_update()
        request = (await self.session.execute(stmt)).scalar_one_or_none()
        if request is None:
            raise NotFoundError("Help request not found")
        return request

    async def my_requests(
        self, student: AcademyMembership, params: PaginationParams, *, active_only: bool
    ) -> tuple[list[MyHelpRequest], int]:
        stmt = (
            select(HelpRequest, AcademyClass.name)
            .join(AcademyClass, AcademyClass.id == HelpRequest.class_id)
            .where(
                HelpRequest.academy_id == student.academy_id,
                HelpRequest.student_membership_id == student.id,
            )
        )
        if active_only:
            stmt = stmt.where(HelpRequest.status.in_([W, C, P]))
        stmt = stmt.order_by(HelpRequest.requested_at.desc(), HelpRequest.id)
        rows, total = await fetch_page(self.session, stmt, params)
        return [await self._my_view(row[0], row[1]) for row in rows], total

    async def my_request(self, student: AcademyMembership, request_id: uuid.UUID) -> MyHelpRequest:
        return await self._my_view(await self._mine(student, request_id))

    async def cancel_mine(self, student: AcademyMembership, request_id: uuid.UUID) -> MyHelpRequest:
        request = await self._mine(student, request_id, for_update=True)
        if request.status not in STUDENT_CANCELLABLE:
            raise self._invalid_state(request, "cancel")
        before = request.status
        now = clock.utc_now()
        request.status = HelpRequestStatus.CANCELLED
        request.closed_at = now
        request.closed_by = student.id
        change = self._event(request, HelpQueueEventType.CANCELLED, before, student.id, now)
        await self.session.commit()
        await self._publish([change])
        return await self._my_view(request)

    async def class_estimate(self, actor: AcademyMembership, class_id: uuid.UUID) -> ClassEstimate:
        """지금 요청하면 예상 대기시간 (반 학생 또는 강사 이상)."""
        await self.access.require_class_reader(actor, class_id)
        now = clock.utc_now()
        waiting, active = await self._counts(class_id)
        return ClassEstimate(
            class_id=class_id,
            server_time=now,
            waiting_count=waiting,
            active_count=active,
            estimate=await self._estimate(class_id, waiting + active, now),
        )

    # ------------------------------------------------------------------ staff

    async def queue(self, actor: AcademyMembership, class_id: uuid.UUID) -> HelpQueue:
        academy_class = await self.access.require_class_manager(actor, class_id)
        now = clock.utc_now()
        rows = (
            await self.session.execute(
                _queue_order(
                    select(HelpRequest, AcademyMembership, Profile)
                    .join(
                        AcademyMembership, AcademyMembership.id == HelpRequest.student_membership_id
                    )
                    .join(Profile, Profile.id == AcademyMembership.user_id)
                    .where(HelpRequest.class_id == class_id, HelpRequest.status.in_([W, C, P]))
                )
            )
        ).all()
        names = await self._names(
            {r.called_by for r, _, _ in rows} | {r.handled_by for r, _, _ in rows}
        )
        waiting: list[StaffHelpRequest] = []
        active: list[StaffHelpRequest] = []
        for request, membership, profile in rows:
            position = len(waiting) + 1 if request.status == W else None
            item = self._staff_item(request, membership, profile, position, names, now)
            (waiting if request.status == W else active).append(item)
        active.sort(key=lambda r: (r.called_at or r.started_at or r.requested_at, str(r.id)))
        last_changed = (
            await self.session.execute(
                select(func.max(HelpQueueEvent.created_at)).where(
                    HelpQueueEvent.class_id == class_id
                )
            )
        ).scalar_one()
        return HelpQueue(
            class_id=class_id,
            class_name=academy_class.name,
            server_time=now,
            waiting_count=len(waiting),
            active_count=len(active),
            active=active,
            waiting=waiting,
            estimate_for_new_request=await self._estimate(
                class_id, len(waiting) + len(active), now
            ),
            last_changed_at=last_changed,
            recommended_poll_seconds=STAFF_POLL_SECONDS,
        )

    def _staff_item(
        self,
        request: HelpRequest,
        membership: AcademyMembership,
        profile: Profile,
        position: int | None,
        names: dict[uuid.UUID, str],
        now: datetime,
    ) -> StaffHelpRequest:
        return StaffHelpRequest(
            **self._base(request, position, names),
            student=StudentRef(
                membership_id=membership.id,
                user_id=profile.id,
                display_name=profile.display_name,
                avatar_path=profile.avatar_path,
            ),
            waiting_seconds=max(0, int((now - request.requested_at).total_seconds())),
            called_by=request.called_by,
            handled_by=request.handled_by,
        )

    async def _staff_view(self, request: HelpRequest) -> StaffHelpRequest:
        membership = await self.session.get(AcademyMembership, request.student_membership_id)
        assert membership is not None
        profile = await self.session.get(Profile, membership.user_id)
        assert profile is not None
        names = await self._names({request.called_by, request.handled_by})
        return self._staff_item(
            request, membership, profile, await self._position(request), names, clock.utc_now()
        )

    @staticmethod
    def _invalid_state(request: HelpRequest, action: str) -> ConflictError:
        return ConflictError(
            f"Cannot {action} a help request that is {request.status}",
            code=ErrorCode.HELP_REQUEST_INVALID_STATE,
            details={"status": str(request.status)},
        )

    def _apply(
        self, request: HelpRequest, action: str, actor: AcademyMembership, now: datetime
    ) -> HelpQueueChange:
        allowed, target, event = STAFF_TRANSITIONS[action]
        if request.status not in allowed:
            raise self._invalid_state(request, action)
        before = request.status
        if action == "call" or (action == "start" and request.called_at is None):
            request.called_at = now
            request.called_by = actor.id
        if action == "requeue":
            request.called_at = None
            request.called_by = None
        if action == "start":
            request.started_at = now
            request.handled_by = actor.id
        if action == "complete":
            request.completed_at = now
            request.handled_by = request.handled_by or actor.id
        if action in ("skip", "cancel"):
            request.closed_at = now
            request.closed_by = actor.id
        request.status = target
        return self._event(request, event, before, actor.id, now)

    async def transition(
        self, actor: AcademyMembership, request_id: uuid.UUID, action: str
    ) -> StaffHelpRequest:
        request = (
            await self.session.execute(
                select(HelpRequest)
                .where(HelpRequest.academy_id == actor.academy_id, HelpRequest.id == request_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if request is None:
            raise NotFoundError("Help request not found")
        await self.access.require_class_manager(actor, request.class_id)
        change = self._apply(request, action, actor, clock.utc_now())
        await self.session.commit()
        await self._publish([change])
        return await self._staff_view(request)

    async def call_next(self, actor: AcademyMembership, class_id: uuid.UUID) -> StaffHelpRequest:
        await self.access.require_class_manager(actor, class_id)
        # 다른 강사가 잠근(호출 중인) 행은 건너뛰고 그 다음 대기자를 잡는다
        request = (
            await self.session.execute(
                _queue_order(
                    select(HelpRequest).where(
                        HelpRequest.class_id == class_id, HelpRequest.status == W
                    )
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if request is None:
            raise ConflictError("No students are waiting", code=ErrorCode.HELP_QUEUE_EMPTY)
        change = self._apply(request, "call", actor, clock.utc_now())
        await self.session.commit()
        await self._publish([change])
        return await self._staff_view(request)
