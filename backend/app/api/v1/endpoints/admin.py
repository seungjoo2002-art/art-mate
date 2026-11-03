"""시스템 관리자(ADMIN) 전용 API. 학원 등록 신청 심사."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_user_types
from app.api.responses import AUTH_ERRORS, error_responses
from app.models.enums import AcademyStatus, UserType
from app.models.profile import Profile
from app.schemas.academy import AcademyAdminRead, AcademyReview
from app.schemas.common import Page, PaginationQuery
from app.services.academies import AcademyService

router = APIRouter(prefix="/admin", tags=["admin"])

SystemAdmin = Annotated[Profile, Depends(require_user_types(UserType.ADMIN))]


@router.get("/academies", summary="학원 심사 목록 (ADMIN)", responses=AUTH_ERRORS)
async def list_academies_for_review(
    _: SystemAdmin,
    session: DbSession,
    pagination: PaginationQuery,
    academy_status: Annotated[
        AcademyStatus, Query(alias="status")
    ] = AcademyStatus.PENDING_APPROVAL,
) -> Page[AcademyAdminRead]:
    academies, total = await AcademyService(session).list_for_review(academy_status, pagination)
    items = [AcademyAdminRead.model_validate(academy) for academy in academies]
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@router.patch(
    "/academies/{academy_id}",
    summary="학원 등록 승인·거절 (ADMIN)",
    responses=AUTH_ERRORS | error_responses(404, 409, 422),
)
async def review_academy(
    academy_id: uuid.UUID, data: AcademyReview, admin: SystemAdmin, session: DbSession
) -> AcademyAdminRead:
    academy = await AcademyService(session).review(academy_id, admin, data)
    return AcademyAdminRead.model_validate(academy)
