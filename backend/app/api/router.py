"""최상위 라우터.

- 버전 없는 공개 엔드포인트: `/`, `/health` (로드밸런서·Render 헬스체크용, DB와 무관)
- 버전 API: `/api/v1/...` (prefix는 설정값 API_V1_PREFIX)
"""

from fastapi import APIRouter

from app.api.deps import AppSettings
from app.api.v1.router import api_v1_router
from app.core.config import Settings
from app.schemas.health import HealthStatus, ServiceInfo

root_router = APIRouter(tags=["system"])


@root_router.get("/", summary="서버 기본 정보")
async def service_info(settings: AppSettings) -> ServiceInfo:
    return ServiceInfo(service=settings.app_name, version=settings.app_version)


@root_router.get("/health", summary="서버 프로세스 상태 (liveness)")
async def health() -> HealthStatus:
    return HealthStatus()


def build_api_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    router.include_router(root_router)
    router.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    return router
