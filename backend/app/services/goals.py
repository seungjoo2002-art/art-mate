"""복수 지망 대학 (v0.9 F-1).

- 학원 가입과 무관하게 학생 본인이 등록·수정·삭제·순서 변경. 다른 사용자는 볼 수 없다.
- 우선순위는 1부터 빈칸 없이 유지한다. 같은 사용자의 변경은 프로필 행 잠금으로 직렬화하고,
  (user_id, priority) 유니크는 DEFERRABLE이라 트랜잭션 안에서 순서를 자유롭게 바꾼다.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ErrorCode, NotFoundError, UnprocessableError
from app.models.profile import Profile, TargetUniversity
from app.schemas.goals import (
    MAX_TARGET_UNIVERSITIES,
    LearningContext,
    TargetUniversityCreate,
    TargetUniversityOrder,
    TargetUniversityRead,
    TargetUniversityUpdate,
)


class GoalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _lock_owner(self, owner: Profile) -> None:
        await self.session.execute(
            select(Profile.id).where(Profile.id == owner.id).with_for_update()
        )

    async def _rows(self, owner_id: uuid.UUID) -> list[TargetUniversity]:
        return list(
            (
                await self.session.execute(
                    select(TargetUniversity)
                    .where(TargetUniversity.user_id == owner_id)
                    .order_by(TargetUniversity.priority, TargetUniversity.created_at)
                )
            ).scalars()
        )

    async def list(self, owner: Profile) -> list[TargetUniversityRead]:
        return [TargetUniversityRead.model_validate(r) for r in await self._rows(owner.id)]

    async def _save(self, owner: Profile, ordered: list[TargetUniversity]) -> None:
        for index, row in enumerate(ordered, start=1):
            if row.priority != index:
                row.priority = index
        await self.session.flush()
        await self.session.commit()

    async def create(self, owner: Profile, data: TargetUniversityCreate) -> TargetUniversityRead:
        await self._lock_owner(owner)
        rows = await self._rows(owner.id)
        if len(rows) >= MAX_TARGET_UNIVERSITIES:
            raise ConflictError(
                "Too many target universities",
                code=ErrorCode.TARGET_UNIVERSITY_LIMIT,
                details={"max": MAX_TARGET_UNIVERSITIES},
            )
        row = TargetUniversity(
            id=uuid.uuid4(),
            user_id=owner.id,
            university_name=data.university_name,
            department=data.department,
            admission_note=data.admission_note,
            priority=len(rows) + 1,
        )
        self.session.add(row)
        position = min(data.priority or len(rows) + 1, len(rows) + 1)
        rows.insert(position - 1, row)
        await self._save(owner, rows)
        await self.session.refresh(row)
        return TargetUniversityRead.model_validate(row)

    async def update(
        self, owner: Profile, target_id: uuid.UUID, data: TargetUniversityUpdate
    ) -> TargetUniversityRead:
        await self._lock_owner(owner)
        rows = await self._rows(owner.id)
        row = next((r for r in rows if r.id == target_id), None)
        if row is None:
            raise NotFoundError("Target university not found")
        changes = data.changes()
        if not changes:
            raise UnprocessableError("Nothing to update")
        for field in ("university_name", "department", "admission_note"):
            if field in changes:
                setattr(row, field, changes[field])
        if "priority" in changes:
            rows.remove(row)
            rows.insert(min(changes["priority"], len(rows) + 1) - 1, row)
        await self._save(owner, rows)
        await self.session.refresh(row)
        return TargetUniversityRead.model_validate(row)

    async def delete(self, owner: Profile, target_id: uuid.UUID) -> None:
        await self._lock_owner(owner)
        rows = await self._rows(owner.id)
        row = next((r for r in rows if r.id == target_id), None)
        if row is None:
            raise NotFoundError("Target university not found")
        await self.session.delete(row)
        rows.remove(row)
        await self.session.flush()
        await self._save(owner, rows)

    async def reorder(
        self, owner: Profile, data: TargetUniversityOrder
    ) -> list[TargetUniversityRead]:
        await self._lock_owner(owner)
        rows = await self._rows(owner.id)
        by_id = {r.id: r for r in rows}
        if set(data.ids) != set(by_id):
            raise UnprocessableError(
                "ids must list every target university exactly once",
                details={"expected_count": len(rows)},
            )
        await self._save(owner, [by_id[i] for i in data.ids])
        return await self.list(owner)

    async def context(self, owner_id: uuid.UUID) -> LearningContext:
        profile = await self.session.get(Profile, owner_id)
        assert profile is not None
        return LearningContext(
            practical_type=profile.practical_type,
            grade=profile.grade,
            learning_goal=profile.learning_goal,
            learning_goal_updated_at=profile.learning_goal_updated_at,
            target_universities=[
                TargetUniversityRead.model_validate(r) for r in await self._rows(owner_id)
            ],
        )
