"""앱 내부 알림 (v0.9 F-9). 푸시·이메일은 보내지 않는다.

생성 시점
- REPORT_READY: 성장 리포트가 만들어짐 (학생 본인 또는 담당 강사가 생성) — 리포트당 1번
- TASK_RECOMMENDED: 개인 맞춤 과제 추천 묶음이 생김(규칙·AI) / 학원 과제로 배포됨 — 묶음·배포당 1번
- TASK_REMINDER: 채택 후 N일(설정, 기본 3일) 동안 완료하지 않은 개인 과제 — 과제당 주 1회, 최대 3회
- GOAL_CHECK: 학습 목표를 30일 넘게 확인·수정하지 않음 (또는 아직 없음) — 월 1회

중복 방지: (user_id, dedupe_key) 유니크 + INSERT ... ON CONFLICT DO NOTHING
(동시 요청·Worker 여러 대에서도 1건). 사용자가 끈 유형은 만들지 않는다.
정기 안내(미완료·목표)는 Worker가 주기적으로, 그리고 사용자가 알림 목록을 열 때 그 사용자만
다시 계산한다 (Worker가 멈춰도 동작).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.exceptions import NotFoundError
from app.models.enums import (
    WEAKNESS_CATEGORY_LABELS,
    GrowthScope,
    NotificationType,
    RecommendationStatus,
    UserType,
)
from app.models.growth import PracticeRecommendation
from app.models.notification import Notification, NotificationPreference
from app.models.profile import Profile
from app.repositories.pagination import fetch_page
from app.schemas.common import PaginationParams
from app.schemas.notifications import (
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationRead,
)

MAX_REMINDERS_PER_TASK = 3
MAX_REMINDERS_PER_SWEEP = 3
GOAL_CHECK_DAYS = 30
NEW_ACCOUNT_GRACE_DAYS = 7
SWEEP_BATCH = 500

PREF_FIELD = {
    NotificationType.REPORT_READY: "report_ready",
    NotificationType.TASK_RECOMMENDED: "task_recommended",
    NotificationType.TASK_REMINDER: "task_reminder",
    NotificationType.GOAL_CHECK: "goal_check",
}
DEFAULT_PREFS: dict[str, Any] = {
    "report_ready": True,
    "task_recommended": True,
    "task_reminder": True,
    "goal_check": True,
    "reminder_after_days": 3,
}


def read(n: Notification) -> NotificationRead:
    return NotificationRead(
        id=n.id,
        type=n.type,
        title=n.title,
        body=n.body,
        report_id=n.report_id,
        recommendation_id=n.recommendation_id,
        is_read=n.read_at is not None,
        read_at=n.read_at,
        created_at=n.created_at,
    )


class NotificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ 설정

    async def _prefs(self, user_id: uuid.UUID) -> dict[str, Any]:
        row = await self.session.get(NotificationPreference, user_id)
        if row is None:
            return dict(DEFAULT_PREFS)
        return {k: getattr(row, k) for k in DEFAULT_PREFS}

    async def preferences(self, user: Profile) -> NotificationPreferenceRead:
        return NotificationPreferenceRead(**await self._prefs(user.id))

    async def update_preferences(
        self, user: Profile, data: NotificationPreferenceUpdate
    ) -> NotificationPreferenceRead:
        values = {**await self._prefs(user.id), **data.model_dump(exclude_unset=True)}
        await self.session.execute(
            insert(NotificationPreference)
            .values(user_id=user.id, **values)
            .on_conflict_do_update(
                index_elements=[NotificationPreference.user_id],
                set_={**values, "updated_at": func.now()},
            )
        )
        await self.session.commit()
        return NotificationPreferenceRead(**values)

    # ------------------------------------------------------------------ 생성

    async def notify(
        self,
        user_id: uuid.UUID,
        type_: NotificationType,
        *,
        title: str,
        body: str | None,
        dedupe_key: str,
        report_id: uuid.UUID | None = None,
        recommendation_id: uuid.UUID | None = None,
    ) -> bool:
        """알림 1건 (같은 dedupe_key면 만들지 않음). 호출자가 commit 한다."""
        prefs = await self._prefs(user_id)
        if not prefs[PREF_FIELD[type_]]:
            return False
        inserted = (
            await self.session.execute(
                insert(Notification)
                .values(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    type=type_,
                    title=title[:100],
                    body=body[:300] if body else None,
                    report_id=report_id,
                    recommendation_id=recommendation_id,
                    dedupe_key=dedupe_key[:150],
                )
                .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
                .returning(Notification.id)
            )
        ).first()
        return inserted is not None

    async def report_ready(self, user_id: uuid.UUID, report_id: uuid.UUID) -> None:
        await self.notify(
            user_id,
            NotificationType.REPORT_READY,
            title="새 성장 리포트가 준비됐어요",
            body="최근 첨삭 기록을 바탕으로 한 성장 리포트를 확인해 보세요.",
            dedupe_key=f"report:{report_id}",
            report_id=report_id,
        )

    async def tasks_recommended(
        self, user_id: uuid.UUID, recs: list[PracticeRecommendation], key: str
    ) -> None:
        if not recs:
            return
        labels = ", ".join(
            dict.fromkeys(WEAKNESS_CATEGORY_LABELS[r.weakness_category] for r in recs)
        )
        await self.notify(
            user_id,
            NotificationType.TASK_RECOMMENDED,
            title="새 맞춤 연습 과제가 추천됐어요",
            body=f"반복해서 지적된 '{labels}'을(를) 위한 연습 과제 {len(recs)}개",
            dedupe_key=key,
            recommendation_id=recs[0].id,
        )

    async def task_distributed(self, rec: PracticeRecommendation) -> None:
        await self.notify(
            rec.owner_id,
            NotificationType.TASK_RECOMMENDED,
            title="선생님이 맞춤 연습 과제를 보냈어요",
            body=rec.title,
            dedupe_key=f"task-distributed:{rec.id}",
            recommendation_id=rec.id,
        )

    # ------------------------------------------------------------------ 정기 안내

    async def sweep_user(self, user_id: uuid.UUID, now: datetime | None = None) -> int:
        """미완료 과제·학습 목표 안내 (한 사용자). 만든 알림 수. 호출자가 commit 한다."""
        now = now or clock.utc_now()
        profile = await self.session.get(Profile, user_id)
        if profile is None or not profile.is_active or profile.user_type != UserType.STUDENT:
            return 0
        prefs = await self._prefs(user_id)
        created = 0
        if prefs["task_reminder"]:
            created += await self._reminders(profile, now, prefs["reminder_after_days"])
        if prefs["goal_check"]:
            created += await self._goal_check(profile, now)
        return created

    async def _reminders(self, profile: Profile, now: datetime, after_days: int) -> int:
        cutoff = now - timedelta(days=after_days)
        recs = list(
            (
                await self.session.execute(
                    select(PracticeRecommendation)
                    .where(
                        PracticeRecommendation.owner_id == profile.id,
                        PracticeRecommendation.scope == GrowthScope.PERSONAL,
                        PracticeRecommendation.status == RecommendationStatus.ADOPTED,
                        PracticeRecommendation.approved_at <= cutoff,
                    )
                    .order_by(PracticeRecommendation.approved_at)
                )
            ).scalars()
        )
        if not recs:
            return 0
        sent = dict(
            (
                await self.session.execute(
                    select(Notification.recommendation_id, func.count())
                    .where(
                        Notification.user_id == profile.id,
                        Notification.type == NotificationType.TASK_REMINDER,
                        Notification.recommendation_id.in_([r.id for r in recs]),
                    )
                    .group_by(Notification.recommendation_id)
                )
            ).all()
        )
        year, week, _ = now.isocalendar()
        created = 0
        for rec in recs:
            if created >= MAX_REMINDERS_PER_SWEEP:
                break
            if sent.get(rec.id, 0) >= MAX_REMINDERS_PER_TASK:
                continue
            if await self.notify(
                profile.id,
                NotificationType.TASK_REMINDER,
                title="아직 완료하지 않은 연습 과제가 있어요",
                body=rec.title,
                dedupe_key=f"task-reminder:{rec.id}:{year}-W{week:02d}",
                recommendation_id=rec.id,
            ):
                created += 1
        return created

    async def _goal_check(self, profile: Profile, now: datetime) -> int:
        if profile.created_at > now - timedelta(days=NEW_ACCOUNT_GRACE_DAYS):
            return 0
        updated = profile.learning_goal_updated_at
        if updated is not None and updated > now - timedelta(days=GOAL_CHECK_DAYS):
            return 0
        local = clock.to_local(now)
        body = (
            "지금의 학습 목표가 맞는지 확인하고 필요하면 바꿔 보세요."
            if profile.learning_goal
            else "학습 목표와 지망 대학을 적어 두면 성장 리포트에서 함께 볼 수 있어요."
        )
        created = await self.notify(
            profile.id,
            NotificationType.GOAL_CHECK,
            title="학습 목표를 확인해 보세요",
            body=body,
            dedupe_key=f"goal-check:{local.year}-{local.month:02d}",
        )
        return int(created)

    async def sweep_all(self, now: datetime | None = None) -> int:
        """Worker 정기 작업: 안내 대상이 될 수 있는 학생만 골라 sweep_user (배치마다 commit)."""
        now = now or clock.utc_now()
        candidates = set(
            (
                await self.session.execute(
                    select(PracticeRecommendation.owner_id)
                    .where(
                        PracticeRecommendation.scope == GrowthScope.PERSONAL,
                        PracticeRecommendation.status == RecommendationStatus.ADOPTED,
                    )
                    .distinct()
                    .limit(SWEEP_BATCH)
                )
            ).scalars()
        )
        goal_cutoff = now - timedelta(days=GOAL_CHECK_DAYS)
        candidates |= set(
            (
                await self.session.execute(
                    select(Profile.id)
                    .where(
                        Profile.user_type == UserType.STUDENT,
                        Profile.is_active,
                        Profile.created_at <= now - timedelta(days=NEW_ACCOUNT_GRACE_DAYS),
                        (Profile.learning_goal_updated_at.is_(None))
                        | (Profile.learning_goal_updated_at <= goal_cutoff),
                    )
                    .limit(SWEEP_BATCH)
                )
            ).scalars()
        )
        created = 0
        for user_id in candidates:
            created += await self.sweep_user(user_id, now)
            await self.session.commit()
        return created

    # ------------------------------------------------------------------ 조회·읽음·숨김

    async def list(
        self, user: Profile, params: PaginationParams, *, unread_only: bool
    ) -> tuple[list[NotificationRead], int, int]:
        if await self.sweep_user(user.id):
            await self.session.commit()
        base = [Notification.user_id == user.id, Notification.hidden_at.is_(None)]
        stmt = select(Notification).where(*base)
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        stmt = stmt.order_by(Notification.created_at.desc(), Notification.id)
        rows, total = await fetch_page(self.session, stmt, params)
        unread = (
            await self.session.execute(
                select(func.count())
                .select_from(Notification)
                .where(*base, Notification.read_at.is_(None))
            )
        ).scalar_one()
        return [read(r[0]) for r in rows], total, unread

    async def _own(self, user: Profile, notification_id: uuid.UUID) -> Notification:
        row = (
            await self.session.execute(
                select(Notification).where(
                    Notification.id == notification_id,
                    Notification.user_id == user.id,
                    Notification.hidden_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Notification not found")
        return row

    async def mark_read(self, user: Profile, notification_id: uuid.UUID) -> NotificationRead:
        row = await self._own(user, notification_id)
        if row.read_at is None:
            row.read_at = clock.utc_now()
            await self.session.commit()
            await self.session.refresh(row)
        return read(row)

    async def mark_all_read(self, user: Profile) -> int:
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.user_id == user.id,
                Notification.read_at.is_(None),
                Notification.hidden_at.is_(None),
            )
            .values(read_at=func.now(), updated_at=func.now())
            .returning(Notification.id)
        )
        count = len(result.all())
        await self.session.commit()
        return count

    async def hide(self, user: Profile, notification_id: uuid.UUID) -> None:
        """삭제(숨김). 행은 남겨 같은 이벤트 알림이 다시 생기지 않게 한다."""
        row = await self._own(user, notification_id)
        row.hidden_at = clock.utc_now()
        row.read_at = row.read_at or row.hidden_at
        await self.session.commit()
