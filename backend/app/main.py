"""ART MATE API 진입점.

실행: `uvicorn app.main:app --reload` (backend/ 디렉터리에서)
테스트·스크립트에서는 `create_app(settings)`로 독립된 앱 인스턴스를 만든다.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import build_api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.core.security import build_token_verifier
from app.db.session import create_database

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # 엔진 생성은 연결을 열지 않는다 → DB 장애가 있어도 서버는 기동하고 /health는 응답한다.
    app.state.database = create_database(settings)
    logger.info(
        "application startup",
        extra={
            "env": settings.app_env,
            "version": settings.app_version,
            "database_configured": settings.database_configured,
            "auth_configured": settings.auth_configured,
        },
    )
    if not settings.database_configured:
        logger.warning("DATABASE_URL is not set; database features are disabled")
    if not settings.auth_configured:
        logger.warning("SUPABASE_URL is not set; protected APIs will reject all requests")
    try:
        yield
    finally:
        if app.state.database is not None:
            await app.state.database.dispose()
        app.state.database = None
        logger.info("application shutdown")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    docs = settings.api_docs_enabled
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="AI 기반 미술 실기교육·학생관리 플랫폼 ART MATE 백엔드 API",
        debug=settings.debug,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url="/redoc" if docs else None,
        openapi_url="/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.database = None
    # 테스트에서는 서명 키를 고정한 verifier로 교체할 수 있다.
    app.state.token_verifier = build_token_verifier(settings)

    register_exception_handlers(app)

    # 미들웨어는 나중에 추가한 것이 바깥쪽.
    # CORS를 가장 바깥에 두어 에러 응답에도 CORS 헤더가 붙게 한다.
    app.add_middleware(RequestContextMiddleware)
    allow_any_origin = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # 와일드카드(개발 전용)에서는 자격증명(쿠키/Authorization) 허용 불가
        allow_credentials=not allow_any_origin,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
        max_age=600,
    )

    app.include_router(build_api_router(settings))
    return app


app = create_app()
