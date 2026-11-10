"""선택지 목록 API (v0.5.1).

프론트엔드가 실기 유형·작품 분류·작업 상태의 코드와 한국어 라벨을 하드코딩하지 않도록 서버가
한 곳에서 내려준다. 회원가입 화면(프로필 생성 전)에서도 쓰므로 인증이 필요 없다.
값은 코드 배포로만 바뀌므로 응답을 캐시해도 된다 (Cache-Control 1시간).
"""

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
