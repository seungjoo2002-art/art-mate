"""학원 과제 API (F-02).

- 강사 이상: 반 전체 또는 특정 학생에게 배포, 수정, 취소, 학생별 완료 현황
  (OWNER/MANAGER 또는 그 반 담당 강사)
- 학생: 받은 과제 조회, 완료 체크
"""

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, status

from app.api.deps import AcademyStaff, AcademyStudent, DbSession
from app.api.responses import AUTH_ERRORS, error_responses
from app.models.enums import TaskStatus
from app.schemas.common import Page, PaginationQuery
from app.schemas.tasks import (
    MyTask,
    TaskCompletionUpdate,
    TaskCreate,
    TaskDetail,
    TaskRead,
    TaskUpdate,
)
from app.services.tasks import TaskService

router = APIRouter(prefix="/academies/{academy_id}/tasks", tags=["tasks"])

READ_ERRORS = AUTH_ERRORS | error_responses(404)
WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422)


@router.post(
    "",
    summary="과제 배포 (강사 이상)",
    description="target_type=CLASS: 지금 반에 배정된 학생 전원, STUDENTS: 지정한 반 학생. "
    "대상은 배포 시점에 확정된다.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_task(
    academy_id: uuid.UUID, data: TaskCreate, actor: AcademyStaff, session: DbSession
) -> TaskDetail:
    return await TaskService(session).create(actor, data)


@router.get(
    "",
    summary="배포한 과제 목록 (강사 이상, 최신순)",
    description=(
        "담당 반의 과제 (OWNER/MANAGER는 전체). `created_on`: 그날(Asia/Seoul) 배포한 과제."
    ),
    responses=READ_ERRORS,
)
async def list_tasks(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    pagination: PaginationQuery,
    class_id: uuid.UUID | None = None,
    task_status: Annotated[TaskStatus | None, Query(alias="status")] = TaskStatus.ACTIVE,
    created_on: dt.date | None = None,
) -> Page[TaskRead]:
    items, total = await TaskService(session).list_tasks(
        actor, pagination, class_id=class_id, status=task_status, created_on=created_on
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


# 주의: "/me"는 "/{task_id}"보다 먼저 선언해야 한다.
@router.get(
    "/me",
    summary="내가 받은 과제 (학생)",
    description="진행 중(ACTIVE) 과제만. 마감 임박 순. `completion`: open / completed / all.",
    responses=READ_ERRORS,
)
async def my_tasks(
    academy_id: uuid.UUID,
    student: AcademyStudent,
    session: DbSession,
    pagination: PaginationQuery,
    completion: Literal["open", "completed", "all"] = "all",
) -> Page[MyTask]:
    completed = {"open": False, "completed": True, "all": None}[completion]
    items, total = await TaskService(session).list_mine(student, pagination, completed)
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.get("/{task_id}", summary="과제 상세 + 학생별 완료 현황 (강사 이상)", responses=READ_ERRORS)
async def get_task(
    academy_id: uuid.UUID, task_id: uuid.UUID, actor: AcademyStaff, session: DbSession
) -> TaskDetail:
    return await TaskService(session).get(actor, task_id)


@router.patch("/{task_id}", summary="과제 수정 (강사 이상)", responses=WRITE_ERRORS)
async def update_task(
    academy_id: uuid.UUID,
    task_id: uuid.UUID,
    data: TaskUpdate,
    actor: AcademyStaff,
    session: DbSession,
) -> TaskDetail:
    return await TaskService(session).update(actor, task_id, data)


@router.delete(
    "/{task_id}",
    summary="과제 취소 (강사 이상)",
    description="status=CANCELLED. 학생 화면에서 사라진다. 이미 취소된 과제도 204.",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def cancel_task(
    academy_id: uuid.UUID, task_id: uuid.UUID, actor: AcademyStaff, session: DbSession
) -> None:
    await TaskService(session).cancel(actor, task_id)


@router.put(
    "/{task_id}/completion",
    summary="과제 완료 체크 / 해제 (학생)",
    description="본인에게 배정된 과제만. 취소된 과제는 409 TASK_CANCELLED.",
    responses=WRITE_ERRORS,
)
async def set_completion(
    academy_id: uuid.UUID,
    task_id: uuid.UUID,
    data: TaskCompletionUpdate,
    student: AcademyStudent,
    session: DbSession,
) -> MyTask:
    return await TaskService(session).set_completion(student, task_id, data.completed)
