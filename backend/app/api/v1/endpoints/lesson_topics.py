"""수업 주제 API (F-02). 반의 수업 날짜별 주제, 미래 날짜는 '다음 수업 주제' 사전 공지.

- 조회: 강사 이상 또는 그 반에 배정된 학생
- 등록·수정·삭제: OWNER/MANAGER 또는 그 반 담당 강사
"""

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AcademyMember, DbSession
from app.api.responses import AUTH_ERRORS, error_responses
from app.core import timezone as clock
from app.schemas.common import Page, PaginationQuery
from app.schemas.tasks import LessonTopicCreate, LessonTopicRead, LessonTopicUpdate
from app.services.tasks import LessonTopicService

router = APIRouter(
    prefix="/academies/{academy_id}/classes/{class_id}/lesson-topics", tags=["lesson-topics"]
)

WRITE_ERRORS = AUTH_ERRORS | error_responses(404, 409, 422)


@router.post(
    "",
    summary="수업 주제 등록 / 다음 수업 주제 공지",
    description="반·날짜당 1건 (이미 있으면 409 LESSON_TOPIC_EXISTS).",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERRORS,
)
async def create_topic(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    data: LessonTopicCreate,
    actor: AcademyMember,
    session: DbSession,
) -> LessonTopicRead:
    topic = await LessonTopicService(session).create(actor, class_id, data)
    return LessonTopicRead.model_validate(topic)


@router.get(
    "",
    summary="수업 주제 목록 (날짜순)",
    description="기본: 오늘 이후 주제 (다음 수업 공지). 지난 주제는 `from`을 지정.",
    responses=AUTH_ERRORS | error_responses(404),
)
async def list_topics(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    actor: AcademyMember,
    session: DbSession,
    pagination: PaginationQuery,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
) -> Page[LessonTopicRead]:
    topics, total = await LessonTopicService(session).list_topics(
        actor, class_id, pagination, date_from or clock.local_today(), date_to
    )
    return Page(
        items=[LessonTopicRead.model_validate(t) for t in topics],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.patch("/{topic_id}", summary="수업 주제 수정", responses=WRITE_ERRORS)
async def update_topic(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    topic_id: uuid.UUID,
    data: LessonTopicUpdate,
    actor: AcademyMember,
    session: DbSession,
) -> LessonTopicRead:
    topic = await LessonTopicService(session).update(actor, class_id, topic_id, data)
    return LessonTopicRead.model_validate(topic)


@router.delete(
    "/{topic_id}",
    summary="수업 주제 삭제",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERRORS,
)
async def delete_topic(
    academy_id: uuid.UUID,
    class_id: uuid.UUID,
    topic_id: uuid.UUID,
    actor: AcademyMember,
    session: DbSession,
) -> None:
    await LessonTopicService(session).delete(actor, class_id, topic_id)
