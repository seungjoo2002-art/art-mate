"""API v1 라우터 집합.

새 도메인 추가 시: endpoints/<domain>.py 에 `router = APIRouter(prefix="/<domain>s", tags=[...])`
를 만들고 아래에 include_router 한 줄을 추가한다 (알파벳 순).

v0.5.1 기획 변경으로 제외한 기능 (라우터·서비스 제거, DB 테이블은 보존):
출석(attendance), 오늘 할 일(personal_todos, /users/me/today), 강사 대시보드(dashboard),
질문 콜·대기열(help), 시험 타이머(exams). 테이블 처리 계획은 docs/v0.5.1-planning-changes.md.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    academies,
    admin,
    ai_feedback,
    artworks,
    classes,
    community,
    growth,
    health,
    lesson_topics,
    meta,
    notifications,
    recordings,
    schedules,
    tasks,
    users,
)

api_v1_router = APIRouter()
api_v1_router.include_router(academies.router)
api_v1_router.include_router(admin.router)
api_v1_router.include_router(ai_feedback.consents)
api_v1_router.include_router(ai_feedback.guardian_consents)
api_v1_router.include_router(ai_feedback.owner_processing)
api_v1_router.include_router(ai_feedback.staff_processing)
api_v1_router.include_router(ai_feedback.owner_feedback)
api_v1_router.include_router(ai_feedback.archive)
api_v1_router.include_router(ai_feedback.staff_feedback)
api_v1_router.include_router(ai_feedback.artwork_notes)
api_v1_router.include_router(ai_feedback.notes)
api_v1_router.include_router(artworks.router)
api_v1_router.include_router(artworks.staff_router)
api_v1_router.include_router(classes.router)
api_v1_router.include_router(community.sharing)
api_v1_router.include_router(community.references_me)
api_v1_router.include_router(community.references_staff)
api_v1_router.include_router(community.community)
api_v1_router.include_router(community.admin)
api_v1_router.include_router(growth.me)
api_v1_router.include_router(growth.staff)
api_v1_router.include_router(health.router)
api_v1_router.include_router(lesson_topics.router)
api_v1_router.include_router(meta.router)
api_v1_router.include_router(notifications.router)
api_v1_router.include_router(recordings.consents)
api_v1_router.include_router(recordings.router)
api_v1_router.include_router(recordings.staff_router)
api_v1_router.include_router(schedules.router)
api_v1_router.include_router(tasks.router)
api_v1_router.include_router(users.router)
