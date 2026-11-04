"""학생 개인 할 일 API (F-05). 본인 것만 다루며 학원 강사·관리자에게 공개되지 않는다."""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, require_user_types
from app.api.responses import AUTH_ERRORS, error_responses
from app.models.enums import UserType
from app.models.profile import Profile
from app.schemas.common import Page, PaginationQuery
from app.schemas.personal_todo import PersonalTodoCreate, PersonalTodoRead, PersonalTodoUpdate
from app.services.personal_todos import PersonalTodoService, todo_read

router = APIRouter(prefix="/personal-todos", tags=["personal-todos"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 422)


@router.post(
    "",
    summary="개인 할 일 추가 (학생)",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_todo(
    data: PersonalTodoCreate, owner: Student, session: DbSession
) -> PersonalTodoRead:
    return todo_read(await PersonalTodoService(session).create(owner, data))


@router.get(
    "",
    summary="내 개인 할 일 목록 (날짜순, 날짜 없음은 마지막)",
    responses=AUTH_ERRORS | error_responses(422),
)
async def list_todos(
    owner: Student,
    session: DbSession,
    pagination: PaginationQuery,
    is_done: bool | None = None,
    due_from: Annotated[dt.date | None, Query()] = None,
    due_to: Annotated[dt.date | None, Query()] = None,
) -> Page[PersonalTodoRead]:
    todos, total = await PersonalTodoService(session).list_todos(
        owner, pagination, is_done=is_done, due_from=due_from, due_to=due_to
    )
    return Page(
        items=[todo_read(t) for t in todos],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.patch(
    "/{todo_id}",
    summary="개인 할 일 수정 / 완료·미완료 전환",
    description="`is_done: true|false`로 완료 전환. 보내지 않은 필드는 유지, null은 값 지우기.",
    responses=WRITE_ERRORS,
)
async def update_todo(
    todo_id: uuid.UUID, data: PersonalTodoUpdate, owner: Student, session: DbSession
) -> PersonalTodoRead:
    return todo_read(await PersonalTodoService(session).update(owner, todo_id, data))


@router.delete(
    "/{todo_id}",
    summary="개인 할 일 삭제",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def delete_todo(todo_id: uuid.UUID, owner: Student, session: DbSession) -> None:
    await PersonalTodoService(session).delete(owner, todo_id)
