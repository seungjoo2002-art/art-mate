"""API v1 라우터 집합.

새 도메인 추가 시: endpoints/<domain>.py 에 `router = APIRouter(prefix="/<domain>s", tags=[...])`
를 만들고 아래에 include_router 한 줄을 추가한다 (알파벳 순).
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    academies,
    admin,
    artworks,
    attendance,
    classes,
    dashboard,
    exams,
    health,
    lesson_topics,
    personal_todos,
    schedules,
    tasks,
    users,
)

api_v1_router = APIRouter()
api_v1_router.include_router(academies.router)
api_v1_router.include_router(admin.router)
api_v1_router.include_router(artworks.router)
api_v1_router.include_router(artworks.staff_router)
api_v1_router.include_router(attendance.router)
api_v1_router.include_router(classes.router)
api_v1_router.include_router(dashboard.router)
api_v1_router.include_router(exams.sessions)
api_v1_router.include_router(exams.templates)
api_v1_router.include_router(health.router)
api_v1_router.include_router(lesson_topics.router)
api_v1_router.include_router(personal_todos.router)
api_v1_router.include_router(schedules.router)
api_v1_router.include_router(tasks.router)
api_v1_router.include_router(users.router)
