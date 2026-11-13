"""AI 첨삭 학습 데이터셋 (v0.9.8): 학습 활용 동의 (학생), 데이터셋 통계·샘플 (시스템 ADMIN).

모델 학습·외부 API 호출은 하지 않는다.
동의·확인된 기준 이미지·강사 피드백이 갖춰진 것만 샘플이 된다.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AppSettings, DbSession, require_user_types
from app.api.responses import AUTH_ERRORS, error_responses
from app.models.enums import UserType
from app.models.profile import Profile
from app.schemas.dataset import (
    DatasetConsentCreate,
    DatasetConsentStatus,
    DatasetStats,
    TrainingSample,
)
from app.services.dataset import DatasetConsentService, DatasetService

consents = APIRouter(prefix="/dataset-consents", tags=["dataset"])
admin = APIRouter(prefix="/admin/dataset", tags=["dataset"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
SystemAdmin = Annotated[Profile, Depends(require_user_types(UserType.ADMIN))]


@consents.get("/me", summary="내 AI 학습 활용 동의 상태", responses=AUTH_ERRORS)
async def my_dataset_consent(
    user: Student, session: DbSession, settings: AppSettings
) -> DatasetConsentStatus:
    return await DatasetConsentService(session, settings).status(user)


@consents.post(
    "/me",
    summary="AI 학습 활용 동의",
    description=(
        "AI 요약 동의와 별개. `policy_version`은 GET의 `required_version`. "
        "만 14세 미만은 409 `DATASET_CONSENT_UNAVAILABLE` (보호자 동의 절차 준비 전)."
    ),
    status_code=status.HTTP_201_CREATED,
    responses=AUTH_ERRORS | error_responses(409, 422),
)
async def grant_dataset_consent(
    data: DatasetConsentCreate, user: Student, session: DbSession, settings: AppSettings
) -> DatasetConsentStatus:
    return await DatasetConsentService(session, settings).grant(user, data)


@consents.delete(
    "/me",
    summary="AI 학습 활용 동의 철회",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=AUTH_ERRORS,
)
async def revoke_dataset_consent(user: Student, session: DbSession, settings: AppSettings) -> None:
    await DatasetConsentService(session, settings).revoke(user)


@admin.get("/stats", summary="학습 데이터 후보·제외 사유 통계 (ADMIN)", responses=AUTH_ERRORS)
async def dataset_stats(_: SystemAdmin, session: DbSession, settings: AppSettings) -> DatasetStats:
    return await DatasetService(session, settings).stats()


@admin.get(
    "/samples",
    summary="학습 샘플 미리보기 (ADMIN, 가명 처리)",
    description="가명 처리 키(DATASET_PSEUDONYM_KEY)가 없으면 503 `DATASET_EXPORT_DISABLED`.",
    responses=AUTH_ERRORS | error_responses(503),
)
async def dataset_samples(
    _: SystemAdmin,
    session: DbSession,
    settings: AppSettings,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TrainingSample]:
    return await DatasetService(session, settings).samples(limit)
