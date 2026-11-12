"""선택지 목록 API (v0.5.1).

프론트엔드가 실기 유형·작품 분류·작업 상태의 코드와 한국어 라벨을 하드코딩하지 않도록 서버가
한 곳에서 내려준다. 회원가입 화면(프로필 생성 전)에서도 쓰므로 인증이 필요 없다.
값은 코드 배포로만 바뀌므로 응답을 캐시해도 된다 (Cache-Control 1시간).
"""

import datetime as dt
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from app.models.enums import (
    FEEDBACK_ITEM_KIND_LABELS,
    FEEDBACK_SOURCE_LABELS,
    GRADE_LABELS,
    PRACTICAL_TYPE_LABELS,
    WEAKNESS_CATEGORY_LABELS,
    WORK_CATEGORY_LABELS,
    WORK_STATUS_LABELS,
)
from app.services.worker_dispatch import WorkerDispatcher, queue_health

router = APIRouter(prefix="/meta", tags=["meta"])

CACHE_SECONDS = 3600


class Option(BaseModel):
    code: str = Field(description="API에 보내고 받는 값", examples=["BASIC_DESIGN"])
    label: str = Field(description="화면 표시용 한국어 이름", examples=["기초디자인"])


class Options(BaseModel):
    practical_types: list[Option] = Field(description="실기 유형 (프로필·작품 공통)")
    work_categories: list[Option] = Field(description="작품 작업 목적")
    work_statuses: list[Option] = Field(description="작품 작업 상태")
    weakness_categories: list[Option] = Field(description="첨삭 약점 카테고리 (v0.6)")
    feedback_item_kinds: list[Option] = Field(description="첨삭 항목 종류 (v0.6)")
    # v0.9
    grades: list[Option] = Field(default_factory=list, description="학년 (v0.9)")
    feedback_sources: list[Option] = Field(
        default_factory=list, description="첨삭 출처 (v0.9). INSTRUCTOR만 반복 약점 통계에 집계"
    )
    data_policy: "DataPolicy | None" = Field(default=None, description="데이터 이용 정책 (v0.9)")


class DataPolicy(BaseModel):
    recording_audio_retention_days: int = Field(
        description="음성 원본 보관 기간 (일, 0 = 기한 없음). 지나면 음성만 삭제, 전사·첨삭은 유지"
    )
    model_training_data_collection: bool = Field(
        description="음성·전사·첨삭을 AI 모델 학습 데이터로 수집하는지 (항상 false)"
    )
    speaker_consent_verified_by_service: bool = Field(
        description="강사의 녹음 동의를 서비스가 직접 확인하는지 (false: 학생 기록만 보관)"
    )


Options.model_rebuild()


def _options(labels: dict) -> list[Option]:  # type: ignore[type-arg]
    return [Option(code=code.value, label=label) for code, label in labels.items()]


@router.get(
    "/options",
    summary="선택지 목록 (실기 유형·작품 분류·작업 상태)",
    description="표시 순서는 배열 순서를 따른다. 인증 불필요.",
)
async def get_options(request: Request, response: Response) -> Options:
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    settings = request.app.state.settings
    return Options(
        grades=_options(GRADE_LABELS),
        feedback_sources=_options(FEEDBACK_SOURCE_LABELS),
        data_policy=DataPolicy(
            recording_audio_retention_days=settings.recording_audio_retention_days,
            model_training_data_collection=False,
            speaker_consent_verified_by_service=False,
        ),
        practical_types=_options(PRACTICAL_TYPE_LABELS),
        work_categories=_options(WORK_CATEGORY_LABELS),
        work_statuses=_options(WORK_STATUS_LABELS),
        weakness_categories=_options(WEAKNESS_CATEGORY_LABELS),
        feedback_item_kinds=_options(FEEDBACK_ITEM_KIND_LABELS),
    )


class AiFeatures(BaseModel):
    """AI·음성 변환 기능 사용 가능 여부 (화면 표시용, 설정값·키는 포함하지 않음)."""

    browser_transcription: bool = Field(
        description="기기(브라우저) 음성 변환 — 기기 지원 여부는 화면에서 확인"
    )
    server_transcription: bool = Field(
        description="서버 음성 변환 요청 가능 (처리는 주기 작업, 지연 가능)"
    )
    ai_summary: bool = Field(description="AI 첨삭 정리 요청 가능")
    ai_provider: Literal["openai", "gemini"] = Field(
        description="전사문을 받는 외부 AI 제공자 (동의서 표시용, v0.9.6)"
    )
    ai_summary_status: Literal["ENABLED", "DISABLED", "TERMS_UNCONFIRMED"] = Field(
        description="ENABLED 사용 가능 / DISABLED 기능 꺼짐 / TERMS_UNCONFIRMED 운영자의 외부 AI "
        "약관·유료 등급 확인 전이라 전송 차단 (v0.9.5)"
    )
    ai_summary_daily_limit: int = Field(
        description="학생 1명의 하루 AI 정리 요청 한도 (0 = 제한 없음)"
    )


class WorkerDispatchInfo(BaseModel):
    at: dt.datetime
    reason: str = Field(description="job / transcription / summary / stale ...")
    ok: bool
    status: int | None = Field(description="GitHub 응답 코드 (204 정상, 401·403 토큰, 404 이름)")


class WorkerStatus(BaseModel):
    """Worker 연결 상태 (운영 확인용, v0.9.6). 토큰 값·작업 내용·사용자 정보는 포함하지 않는다."""

    dispatch_configured: bool = Field(description="API 서버에 WORKER_DISPATCH_TOKEN이 있음")
    due_jobs: int | None = Field(
        description="지금 처리할 수 있는 대기 작업 수 (DB 미설정이면 null)"
    )
    oldest_due_minutes: int | None = Field(description="가장 오래 기다린 작업의 대기 시간(분)")
    last_dispatch: WorkerDispatchInfo | None = Field(
        description="이 서버 프로세스가 마지막으로 보낸 실행 요청 결과 (재시작하면 비어 있음)"
    )


@router.get(
    "/worker-status",
    summary="Worker 연결 상태 (운영 확인용)",
    description="즉시 실행 토큰 설정 여부, 대기 작업 수·대기 시간, 마지막 실행 요청 결과.",
)
async def get_worker_status(request: Request, response: Response) -> WorkerStatus:
    response.headers["Cache-Control"] = "no-store"
    state = request.app.state
    settings = state.settings
    dispatcher = getattr(state, "worker_dispatcher", None)
    due = oldest = None
    if state.database is not None:
        try:
            async with state.database.session_factory() as session:
                health = await queue_health(session)
            due = health.due_jobs
            if health.oldest_due_at is not None:
                waited = dt.datetime.now(dt.UTC) - health.oldest_due_at
                oldest = max(0, int(waited.total_seconds() // 60))
        except Exception:  # DB 장애 시에도 나머지 정보는 보여 준다
            due = oldest = None
    last = dispatcher.last_result if dispatcher is not None else None
    return WorkerStatus(
        dispatch_configured=WorkerDispatcher.enabled(settings),
        due_jobs=due,
        oldest_due_minutes=oldest,
        last_dispatch=(
            WorkerDispatchInfo(at=last.at, reason=last.reason, ok=last.ok, status=last.status)
            if last
            else None
        ),
    )


@router.get(
    "/ai-features",
    summary="AI·음성 변환 기능 사용 가능 여부",
    description="꺼진 기능은 화면에서 미리 안내한다 (요청 후 503을 받기 전에). 인증 불필요.",
)
async def get_ai_features(request: Request, response: Response) -> AiFeatures:
    response.headers["Cache-Control"] = "public, max-age=60"
    settings = request.app.state.settings
    return AiFeatures(
        browser_transcription=True,
        server_transcription=settings.stt_enabled,
        ai_summary=settings.ai_summary_active,
        ai_provider=settings.ai_provider,
        ai_summary_status=(
            "ENABLED"
            if settings.ai_summary_active
            else "TERMS_UNCONFIRMED"
            if settings.ai_summary_enabled
            else "DISABLED"
        ),
        ai_summary_daily_limit=settings.ai_summary_daily_limit,
    )
