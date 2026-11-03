"""API v1 라우터 집합.

새 도메인 추가 시: endpoints/<domain>.py 에 `router = APIRouter(prefix="/<domain>s", tags=[...])`
를 만들고 아래에 include_router 한 줄을 추가한다. (두 개발자가 이 파일에서만 짧게 겹치도록 유지)
"""

from fastapi import APIRouter

from app.api.v1.endpoints import health

api_v1_router = APIRouter()
api_v1_router.include_router(health.router)
