"""앱 내부 알림 API (v0.9 F-9). 본인 알림만 (다른 사용자의 알림 id는 404). 푸시·이메일 없음."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import ActiveProfile, DbSession
from app.api.responses import AUTH_ERRORS, error_responses
from app.schemas.common import PaginationQuery
from app.schemas.notifications import (
    NotificationPage,
    NotificationPreferenceRead,
    NotificationPreferenceUpdate,
    NotificationRead,
    ReadAllResult,
)
from app.services.notifications import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])

READ = AUTH_ERRORS | error_responses(404)
WRITE = AUTH_ERRORS | error_responses(404, 422)


@router.get(
    "",
    summary="내 알림 목록 (최신순, 안 읽은 수 포함)",
    description="열 때 미완료 과제·학습 목표 안내를 다시 계산한다 (중복 없음). "
    "unread_only=true면 안 읽은 것만.",
    responses=AUTH_ERRORS,
)
async def list_notifications(
    user: ActiveProfile,
    session: DbSession,
    pagination: PaginationQuery,
    unread_only: bool = False,
) -> NotificationPage:
    items, total, unread = await NotificationService(session).list(
        user, pagination, unread_only=unread_only
    )
    return NotificationPage(
        items=items,
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
        unread_count=unread,
    )


@router.post("/read-all", summary="모두 읽음 처리", responses=AUTH_ERRORS)
async def read_all(user: ActiveProfile, session: DbSession) -> ReadAllResult:
    return ReadAllResult(updated=await NotificationService(session).mark_all_read(user))


@router.get("/preferences", summary="알림 설정", responses=AUTH_ERRORS)
async def get_preferences(user: ActiveProfile, session: DbSession) -> NotificationPreferenceRead:
    return await NotificationService(session).preferences(user)


@router.patch(
    "/preferences", summary="알림 설정 변경 (유형별 끄기·미완료 안내 일수)", responses=WRITE
)
async def update_preferences(
    data: NotificationPreferenceUpdate, user: ActiveProfile, session: DbSession
) -> NotificationPreferenceRead:
    return await NotificationService(session).update_preferences(user, data)


@router.post("/{notification_id}/read", summary="읽음 처리", responses=READ)
async def mark_read(
    notification_id: uuid.UUID, user: ActiveProfile, session: DbSession
) -> NotificationRead:
    return await NotificationService(session).mark_read(user, notification_id)


@router.delete(
    "/{notification_id}",
    summary="알림 삭제 (목록에서 숨김)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=READ,
)
async def hide_notification(
    notification_id: uuid.UUID, user: ActiveProfile, session: DbSession
) -> None:
    await NotificationService(session).hide(user, notification_id)
