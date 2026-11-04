"""학생 개인 할 일. 모든 조회·수정 조건에 `user_id = 토큰의 사용자`가 들어간다.

다른 사람의 할 일 ID로 요청하면 404 (존재 여부 비노출). 학원 강사·관리자용 API는 없다.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import and_, case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import timezone as clock
from app.core.exceptions import NotFoundError
from app.models.personal_todo import PersonalTodo
from app.models.profile import Profile
from app.repositories.pagination import fetch_page
from app.schemas.common import PaginationParams
from app.schemas.personal_todo import PersonalTodoCreate, PersonalTodoRead, PersonalTodoUpdate


def todo_read(todo: PersonalTodo) -> PersonalTodoRead:
    return PersonalTodoRead(
        id=todo.id,
        title=todo.title,
        note=todo.note,
        due_date=todo.due_date,
        is_done=todo.completed_at is not None,
        completed_at=todo.completed_at,
        created_at=todo.created_at,
        updated_at=todo.updated_at,
    )


class PersonalTodoService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, owner: Profile, data: PersonalTodoCreate) -> PersonalTodo:
        todo = PersonalTodo(id=uuid.uuid4(), user_id=owner.id, **data.model_dump())
        self.session.add(todo)
        await self.session.commit()
        await self.session.refresh(todo)
        return todo

    async def list_todos(
        self,
        owner: Profile,
        params: PaginationParams,
        *,
        is_done: bool | None,
        due_from: date | None,
        due_to: date | None,
    ) -> tuple[list[PersonalTodo], int]:
        stmt = select(PersonalTodo).where(PersonalTodo.user_id == owner.id)
        if is_done is True:
            stmt = stmt.where(PersonalTodo.completed_at.is_not(None))
        elif is_done is False:
            stmt = stmt.where(PersonalTodo.completed_at.is_(None))
        if due_from is not None:
            stmt = stmt.where(PersonalTodo.due_date >= due_from)
        if due_to is not None:
            stmt = stmt.where(PersonalTodo.due_date <= due_to)
        stmt = stmt.order_by(
            PersonalTodo.due_date.asc().nulls_last(), PersonalTodo.created_at, PersonalTodo.id
        )
        rows, total = await fetch_page(self.session, stmt, params)
        return [row[0] for row in rows], total

    async def _owned(self, owner: Profile, todo_id: uuid.UUID) -> PersonalTodo:
        stmt = (
            select(PersonalTodo)
            .where(PersonalTodo.id == todo_id, PersonalTodo.user_id == owner.id)
            .with_for_update()
        )
        todo = (await self.session.execute(stmt)).scalar_one_or_none()
        if todo is None:
            raise NotFoundError("Todo not found")
        return todo

    async def update(
        self, owner: Profile, todo_id: uuid.UUID, data: PersonalTodoUpdate
    ) -> PersonalTodo:
        todo = await self._owned(owner, todo_id)
        changes = data.changes()
        is_done = changes.pop("is_done", None)
        for field, value in changes.items():
            setattr(todo, field, value)
        if is_done is True and todo.completed_at is None:
            todo.completed_at = clock.utc_now()
        elif is_done is False:
            todo.completed_at = None
        await self.session.commit()
        await self.session.refresh(todo)
        return todo

    async def delete(self, owner: Profile, todo_id: uuid.UUID) -> None:
        todo = await self._owned(owner, todo_id)
        await self.session.delete(todo)
        await self.session.commit()

    async def for_today(
        self, owner: Profile, day: date, bounds: tuple[datetime, datetime], limit: int
    ) -> list[PersonalTodo]:
        """오늘 할 일: 오늘 날짜 + 날짜 지난 미완료 + 날짜 없는 미완료 + 오늘 완료한 할 일."""
        open_ = PersonalTodo.completed_at.is_(None)
        stmt = (
            select(PersonalTodo)
            .where(
                PersonalTodo.user_id == owner.id,
                or_(
                    PersonalTodo.due_date == day,
                    and_(open_, or_(PersonalTodo.due_date.is_(None), PersonalTodo.due_date < day)),
                    and_(
                        PersonalTodo.completed_at >= bounds[0],
                        PersonalTodo.completed_at < bounds[1],
                    ),
                ),
            )
            .order_by(
                case((open_, 0), else_=1),
                PersonalTodo.due_date.asc().nulls_last(),
                PersonalTodo.created_at,
            )
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())
