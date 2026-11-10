"""성장 코치 API (v0.7).

- 학생:  /growth/me/...                       본인 데이터 (scope=ALL/PERSONAL/ACADEMY)
- 강사:  /academies/{academy_id}/growth/...   담당 학생의 그 학원 연결 작품만

통계(약점 분석·리포트 통계)는 규칙 기반으로 즉시 계산한다. AI 설명문·AI 추천 과제는 GROWTH_COACHING
동의 후 Worker가 비동기로 만든다.
추천 과제는 자동 배포하지 않는다 (학원: 강사 승인·배포, 개인: 본인 채택).
"""

import datetime as dt
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    AcademyStaff,
    ActiveProfile,
    AppSettings,
    DbSession,
    OptionalStorage,
    require_user_types,
)
from app.api.responses import AUTH_ERRORS, error_responses
from app.core.exceptions import UnprocessableError
from app.core.security import CurrentUser
from app.models.enums import (
    ArtworkWorkCategory,
    GrowthScope,
    PracticalType,
    RecommendationStatus,
    UserType,
    WeaknessCategory,
)
from app.models.profile import Profile
from app.schemas.ai_feedback import JobRead
from app.schemas.common import Page, PaginationQuery
from app.schemas.growth import (
    ArtworkComparison,
    FollowUp,
    GenerationResult,
    GrowthSummary,
    LinkedArtwork,
    RecommendationArtworkLink,
    RecommendationCompletion,
    RecommendationDecision,
    RecommendationDistribute,
    RecommendationGenerate,
    RecommendationHistoryRead,
    RecommendationRead,
    RecommendationReject,
    RecommendationStart,
    RecommendationUpdate,
    ReportCreate,
    ReportListItem,
    ReportRead,
    ReportRegenerate,
    ReviewerRecommendationRead,
    StudentGrowthRow,
    TimelineArtwork,
    WeaknessAnalysis,
    WeaknessHistoryItem,
)
from app.services.growth import GrowthService, Scope

me = APIRouter(prefix="/growth/me", tags=["growth"])
staff = APIRouter(prefix="/academies/{academy_id}/growth", tags=["growth"])

Student = Annotated[Profile, Depends(require_user_types(UserType.STUDENT))]
READ = AUTH_ERRORS | error_responses(404, 422)
WRITE = AUTH_ERRORS | error_responses(404, 409, 422)

ScopeQ = Annotated[
    GrowthScope,
    Query(description="ALL(모든 작품) / PERSONAL(학원 미연결) / ACADEMY(academy_id 필요)"),
]
FromQ = Annotated[dt.date | None, Query(alias="from", description="작업일 시작 (포함)")]
ToQ = Annotated[dt.date | None, Query(alias="to", description="작업일 끝 (포함)")]
PracticalQ = Annotated[list[PracticalType] | None, Query(description="실기 유형 (여러 개 OR)")]
CategoryQ = Annotated[list[ArtworkWorkCategory] | None, Query(description="작업 목적 (여러 개 OR)")]
WindowQ = Annotated[int | None, Query(ge=2, le=50, description="최근 비교 구간 작품 수 (기본 5)")]
BucketQ = Annotated[Literal["week", "month"], Query(description="기간별 추이 단위")]
StatusQ = Annotated[list[RecommendationStatus] | None, Query(alias="status")]


def _svc(session, settings) -> GrowthService:  # type: ignore[no-untyped-def]
    return GrowthService(session, settings)


def _check_range(date_from: dt.date | None, date_to: dt.date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise UnprocessableError("from must be on or before to")


async def _student_scope(
    svc: GrowthService, owner: Profile, scope: GrowthScope, academy_id: uuid.UUID | None
) -> Scope:
    return await svc.student_scope(owner, scope, academy_id)


# ============================================================================ 학생


@me.get("/summary", summary="나의 성장 요약 (대시보드)", responses=READ)
async def my_summary(
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    scope: ScopeQ = GrowthScope.ALL,
    academy_id: uuid.UUID | None = None,
) -> GrowthSummary:
    svc = _svc(session, settings)
    return await svc.summary(await _student_scope(svc, owner, scope, academy_id))


@me.get(
    "/timeline",
    summary="작품·첨삭 통합 이력 (최근 작업일순)",
    description="작품별 단계 사진 요약, 완료 상태, 승인된 첨삭(요약·잘한 점·부족한 점·수정 지시), "
    "연결된 과제. 미승인 첨삭은 포함하지 않는다.",
    responses=READ,
)
async def my_timeline(
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
    scope: ScopeQ = GrowthScope.ALL,
    academy_id: uuid.UUID | None = None,
    date_from: FromQ = None,
    date_to: ToQ = None,
    practical_type: PracticalQ = None,
    work_category: CategoryQ = None,
) -> Page[TimelineArtwork]:
    _check_range(date_from, date_to)
    svc = _svc(session, settings)
    items, total = await svc.timeline(
        await _student_scope(svc, owner, scope, academy_id),
        pagination,
        start=date_from,
        end=date_to,
        practical_types=practical_type or (),
        work_categories=work_category or (),
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@me.get(
    "/weaknesses",
    summary="반복 약점 분석 (규칙 기반 통계)",
    description="작품 단위 집계, 최근 N개 vs 이전 N개 비교, 기간별 추이, 근거 첨삭. "
    "데이터가 부족하면 status=INSUFFICIENT_DATA.",
    responses=READ,
)
async def my_weaknesses(
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    scope: ScopeQ = GrowthScope.ALL,
    academy_id: uuid.UUID | None = None,
    date_from: FromQ = None,
    date_to: ToQ = None,
    practical_type: PracticalQ = None,
    work_category: CategoryQ = None,
    recent_window: WindowQ = None,
    bucket: BucketQ = "month",
) -> WeaknessAnalysis:
    _check_range(date_from, date_to)
    svc = _svc(session, settings)
    return await svc.weaknesses(
        await _student_scope(svc, owner, scope, academy_id),
        start=date_from,
        end=date_to,
        practical_types=practical_type or (),
        work_categories=work_category or (),
        recent_window=recent_window,
        bucket=bucket,
    )


@me.post(
    "/reports",
    summary="성장 리포트 생성",
    description="통계는 즉시 계산해 저장한다. 같은 범위·기간·같은 데이터면 기존 리포트를 200으로 "
    "반환한다. include_ai_narrative=true면 AI 설명문을 비동기로 만든다 (동의·설정이 없으면 "
    "ai_narrative.status=SKIPPED + error_code).",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE | {200: {"model": ReportRead, "description": "같은 데이터의 기존 리포트"}},
)
async def create_my_report(
    data: ReportCreate,
    response: Response,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ReportRead:
    svc = _svc(session, settings)
    scope = await _student_scope(svc, owner, data.scope, data.academy_id)
    report, created = await svc.create_report(scope, data, owner)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return report


@me.get("/reports", summary="내 성장 리포트 목록 (최신순)", responses=READ)
async def list_my_reports(
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
    scope: Annotated[GrowthScope | None, Query()] = None,
) -> Page[ReportListItem]:
    svc = _svc(session, settings)
    items, total = await svc.list_reports(Scope(owner.id, GrowthScope.ALL), pagination, scope)
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@me.get("/reports/{report_id}", summary="성장 리포트 상세", responses=READ)
async def get_my_report(
    report_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> ReportRead:
    svc = _svc(session, settings)
    scope = Scope(owner.id, GrowthScope.ALL)
    return await svc.report_read(scope, await svc.get_report(scope, report_id))


@me.post(
    "/reports/{report_id}/regenerate",
    summary="성장 리포트 재생성 (현재 데이터로)",
    description="데이터가 바뀌었으면 새 리포트(201), 같으면 기존 리포트(200). "
    "AI 설명문이 실패·건너뜀이었다면 다시 요청한다.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE,
)
async def regenerate_my_report(
    report_id: uuid.UUID,
    response: Response,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    data: ReportRegenerate | None = None,
) -> ReportRead:
    svc = _svc(session, settings)
    data = data or ReportRegenerate()
    report, created = await svc.regenerate_report(
        Scope(owner.id, GrowthScope.ALL), report_id, owner, data.include_ai_narrative
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return report


@me.post(
    "/recommendations",
    summary="맞춤 연습 과제 추천 생성",
    description=(
        "반복 약점(2개 이상 작품에서 지적)마다 과제 1개. use_ai=false: 규칙 기반 즉시 생성(201). "
        "use_ai=true: Gemini 비동기(202, job 폴링). "
        "같은 데이터로 이미 만든 추천이 있으면 200 EXISTING. "
        "scope=PERSONAL은 본인이 채택, scope=ACADEMY는 담당 강사 검토 대기로 들어간다. "
        "데이터 부족·반복 약점 없음은 409 INSUFFICIENT_DATA."
    ),
    status_code=status.HTTP_201_CREATED,
    responses=WRITE | error_responses(503),
)
async def generate_my_recommendations(
    data: RecommendationGenerate,
    response: Response,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> GenerationResult:
    svc = _svc(session, settings)
    scope = await _student_scope(svc, owner, data.scope, data.academy_id)
    result = await svc.generate_recommendations(scope, data, owner)
    response.status_code = {"CREATED": 201, "EXISTING": 200, "QUEUED": 202}[result.status]
    return result


@me.get(
    "/recommendations",
    summary="내 연습 과제 추천 목록",
    description="개인 추천 전부(대체됨 제외) + 학원 추천 중 강사가 배포한 것.",
    responses=READ,
)
async def list_my_recommendations(
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
    status_filter: StatusQ = None,
    scope: ScopeQ = GrowthScope.ALL,
    academy_id: uuid.UUID | None = None,
) -> Page[ReviewerRecommendationRead | RecommendationRead]:
    svc = _svc(session, settings)
    items, total = await svc.list_recommendations(
        await _student_scope(svc, owner, scope, academy_id), pagination, status_filter or []
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@me.get(
    "/recommendations/{recommendation_id}",
    summary="연습 과제 추천 상세",
    response_model=ReviewerRecommendationRead | RecommendationRead,
    responses=READ,
)
async def get_my_recommendation(
    recommendation_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> ReviewerRecommendationRead | RecommendationRead:
    return await _svc(session, settings).owner_view(owner, recommendation_id)


@me.patch(
    "/recommendations/{recommendation_id}",
    summary="개인 추천 수정 (본인)",
    description="개인 범위 추천만. 학원 추천은 강사가 수정한다 (403).",
    response_model=ReviewerRecommendationRead | RecommendationRead,
    responses=WRITE,
)
async def update_my_recommendation(
    recommendation_id: uuid.UUID,
    data: RecommendationUpdate,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerRecommendationRead | RecommendationRead:
    return await _svc(session, settings).update(owner, recommendation_id, data)


@me.post(
    "/recommendations/{recommendation_id}/adopt",
    summary="개인 추천 채택 (본인)",
    response_model=ReviewerRecommendationRead | RecommendationRead,
    responses=WRITE,
)
async def adopt_my_recommendation(
    recommendation_id: uuid.UUID,
    data: RecommendationDecision,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerRecommendationRead | RecommendationRead:
    return await _svc(session, settings).adopt(owner, recommendation_id, data)


@me.post(
    "/recommendations/{recommendation_id}/reject",
    summary="개인 추천 거절 (본인)",
    response_model=ReviewerRecommendationRead | RecommendationRead,
    responses=WRITE,
)
async def reject_my_recommendation(
    recommendation_id: uuid.UUID,
    data: RecommendationReject,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerRecommendationRead | RecommendationRead:
    return await _svc(session, settings).reject(owner, recommendation_id, data)


@me.put(
    "/recommendations/{recommendation_id}/completion",
    summary="개인 추천 완료 기록 / 해제 (본인)",
    description="채택(ADOPTED)한 개인 추천만. 학원에서 배포된 과제는 "
    "PUT /academies/{id}/tasks/{task_id}/completion 을 사용한다. "
    "v0.9: artwork_id를 함께 보내면 수행 작품으로 연결한다 (완료할 때만, 본인 작품).",
    response_model=ReviewerRecommendationRead | RecommendationRead,
    responses=WRITE,
)
async def complete_my_recommendation(
    recommendation_id: uuid.UUID,
    data: RecommendationCompletion,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerRecommendationRead | RecommendationRead:
    return await _svc(session, settings).set_completion(owner, recommendation_id, data)


@me.get(
    "/recommendations/{recommendation_id}/history",
    summary="개인 추천 수정·채택 이력",
    responses=READ,
)
async def my_recommendation_history(
    recommendation_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> list[RecommendationHistoryRead]:
    return await _svc(session, settings).owner_history(owner, recommendation_id)


# ============================================================================ v0.9 F-8 과제 수행


@me.post(
    "/recommendations/{recommendation_id}/start",
    summary="개인 과제 시작 (본인, v0.9)",
    description="채택(ADOPTED)한 개인 과제의 시작 시각을 기록한다. 이미 시작했으면 그대로.",
    response_model=ReviewerRecommendationRead | RecommendationRead,
    responses=WRITE,
)
async def start_my_recommendation(
    recommendation_id: uuid.UUID,
    data: RecommendationStart,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerRecommendationRead | RecommendationRead:
    return await _svc(session, settings).start(owner, recommendation_id, data)


@me.get(
    "/recommendations/{recommendation_id}/artworks",
    summary="개인 과제에 연결된 수행 작품 (v0.9)",
    description="작품별 후속 강사 첨삭 수와 과제 약점이 다시 지적됐는지(weakness_mentioned).",
    responses=READ,
)
async def my_recommendation_artworks(
    recommendation_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> list[LinkedArtwork]:
    return await _svc(session, settings).linked_artworks(owner, recommendation_id)


@me.post(
    "/recommendations/{recommendation_id}/artworks",
    summary="개인 과제에 수행 작품 연결 (본인 작품, v0.9)",
    description="새 작품은 POST /artworks 의 recommendation_id로도 연결할 수 있다. 기존 작품도 "
    "연결 가능. 채택·완료된 개인 과제만 (아니면 409 `RECOMMENDATION_INVALID_STATE`), "
    "다른 사람 작품은 404. 이미 연결돼 있으면 그대로 (멱등). 과제당 최대 20개.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE,
)
async def link_my_recommendation_artwork(
    recommendation_id: uuid.UUID,
    data: RecommendationArtworkLink,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> list[LinkedArtwork]:
    return await _svc(session, settings).link_artwork(owner, recommendation_id, data.artwork_id)


@me.delete(
    "/recommendations/{recommendation_id}/artworks/{artwork_id}",
    summary="수행 작품 연결 해제 (v0.9)",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=READ,
)
async def unlink_my_recommendation_artwork(
    recommendation_id: uuid.UUID,
    artwork_id: uuid.UUID,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
) -> None:
    await _svc(session, settings).unlink_artwork(owner, recommendation_id, artwork_id)


@me.get(
    "/recommendations/{recommendation_id}/follow-up",
    summary="과제 후속 분석: 약점 재등장 여부 (v0.9)",
    description="연결 작품의 승인된 강사 첨삭에서 과제의 약점이 다시 지적됐는지. "
    "completed(과제 완료)와 status(후속 첨삭 결과)는 별개다. NOT_MENTIONED도 향상의 증거가 아니다.",
    responses=READ,
)
async def my_recommendation_follow_up(
    recommendation_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> FollowUp:
    return await _svc(session, settings).follow_up(owner, recommendation_id)


# ============================================================================ v0.9 F-5 아카이브


@me.get(
    "/weaknesses/{category}/feedbacks",
    summary="특정 약점의 과거 첨삭 (최근순, v0.9)",
    description="이 카테고리가 지적된 승인 첨삭 항목과 원문 근거. 기본은 강사 첨삭만, "
    "include_unverified=true면 자기 메모·다른 학생 의견도 (source로 구분).",
    responses=READ,
)
async def my_weakness_history(
    category: WeaknessCategory,
    owner: Student,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
    scope: ScopeQ = GrowthScope.ALL,
    academy_id: uuid.UUID | None = None,
    include_unverified: bool = False,
) -> Page[WeaknessHistoryItem]:
    svc = _svc(session, settings)
    items, total = await svc.weakness_history(
        await _student_scope(svc, owner, scope, academy_id),
        category,
        pagination,
        include_unverified=include_unverified,
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@me.get(
    "/compare",
    summary="이전 작품과 현재 작품 비교 (v0.9)",
    description="두 작품의 메타데이터·시간·단계별 대표 사진(짧은 Signed URL)과 강사 첨삭 카테고리 "
    "차이. previous_artwork_id를 생략하면 같은 실기 유형의 직전 작품 (없으면 409 "
    "`ARTWORK_NOT_COMPARABLE`). AI가 사진을 평가하지 않는다.",
    responses=READ,
)
async def compare_my_artworks(
    current_artwork_id: uuid.UUID,
    owner: Student,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
    storage: OptionalStorage,
    previous_artwork_id: uuid.UUID | None = None,
) -> ArtworkComparison:
    svc = _svc(session, settings)
    return await svc.compare(
        await _student_scope(svc, owner, GrowthScope.ALL, None),
        current_artwork_id,
        previous_artwork_id,
        storage=storage,
        token=user.access_token,
    )


@me.get("/jobs/{job_id}", summary="AI 생성 작업 상태 (리포트 설명문·AI 추천)", responses=READ)
async def my_growth_job(
    job_id: uuid.UUID, owner: Student, session: DbSession, settings: AppSettings
) -> JobRead:
    return await _svc(session, settings).job_for_owner(owner, job_id)


# ============================================================================ 강사


@staff.get(
    "/students",
    summary="담당 학생 성장 현황",
    description="담당 학생별 분석 작품 수, 반복 약점, 최근 승인 첨삭 시각, 검토 대기 추천 수.",
    responses=READ,
)
async def staff_students(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
) -> Page[StudentGrowthRow]:
    items, total = await _svc(session, settings).staff_students(actor, pagination)
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@staff.get(
    "/students/{student_membership_id}/summary", summary="학생 성장 요약 (강사)", responses=READ
)
async def staff_student_summary(
    academy_id: uuid.UUID,
    student_membership_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
) -> GrowthSummary:
    svc = _svc(session, settings)
    scope = await svc.staff_scope(actor, student_membership_id)
    return await svc.summary(scope, await svc.student_ref_for(scope))


@staff.get(
    "/students/{student_membership_id}/timeline", summary="학생 학습 이력 (강사)", responses=READ
)
async def staff_student_timeline(
    academy_id: uuid.UUID,
    student_membership_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
    date_from: FromQ = None,
    date_to: ToQ = None,
    practical_type: PracticalQ = None,
    work_category: CategoryQ = None,
) -> Page[TimelineArtwork]:
    _check_range(date_from, date_to)
    svc = _svc(session, settings)
    items, total = await svc.timeline(
        await svc.staff_scope(actor, student_membership_id),
        pagination,
        start=date_from,
        end=date_to,
        practical_types=practical_type or (),
        work_categories=work_category or (),
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@staff.get(
    "/students/{student_membership_id}/weaknesses",
    summary="학생 반복 약점 분석 (강사)",
    responses=READ,
)
async def staff_student_weaknesses(
    academy_id: uuid.UUID,
    student_membership_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    date_from: FromQ = None,
    date_to: ToQ = None,
    practical_type: PracticalQ = None,
    work_category: CategoryQ = None,
    recent_window: WindowQ = None,
    bucket: BucketQ = "month",
) -> WeaknessAnalysis:
    _check_range(date_from, date_to)
    svc = _svc(session, settings)
    return await svc.weaknesses(
        await svc.staff_scope(actor, student_membership_id),
        start=date_from,
        end=date_to,
        practical_types=practical_type or (),
        work_categories=work_category or (),
        recent_window=recent_window,
        bucket=bucket,
    )


@staff.post(
    "/students/{student_membership_id}/reports",
    summary="학생 성장 리포트 생성 (강사, 학원 작품 기준)",
    description="scope는 항상 ACADEMY(이 학원). 요청 본문의 scope·academy_id는 무시된다.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE,
)
async def staff_create_report(
    academy_id: uuid.UUID,
    student_membership_id: uuid.UUID,
    data: ReportCreate,
    response: Response,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReportRead:
    svc = _svc(session, settings)
    scope = await svc.staff_scope(actor, student_membership_id)
    data = data.model_copy(update={"scope": GrowthScope.ACADEMY, "academy_id": academy_id})
    report, created = await svc.create_report(scope, data, profile)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return report


@staff.get(
    "/students/{student_membership_id}/reports",
    summary="학생 성장 리포트 목록 (강사)",
    responses=READ,
)
async def staff_list_reports(
    academy_id: uuid.UUID,
    student_membership_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
) -> Page[ReportListItem]:
    svc = _svc(session, settings)
    items, total = await svc.list_reports(
        await svc.staff_scope(actor, student_membership_id), pagination
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@staff.get("/reports/{report_id}", summary="성장 리포트 상세 (강사)", responses=READ)
async def staff_get_report(
    academy_id: uuid.UUID,
    report_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
) -> ReportRead:
    svc = _svc(session, settings)
    scope, report = await svc.staff_report_scope(actor, report_id)
    return await svc.report_read(scope, report)


@staff.post(
    "/reports/{report_id}/regenerate",
    summary="성장 리포트 재생성 (강사)",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE,
)
async def staff_regenerate_report(
    academy_id: uuid.UUID,
    report_id: uuid.UUID,
    response: Response,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
    data: ReportRegenerate | None = None,
) -> ReportRead:
    svc = _svc(session, settings)
    scope, _ = await svc.staff_report_scope(actor, report_id)
    data = data or ReportRegenerate()
    report, created = await svc.regenerate_report(
        scope, report_id, profile, data.include_ai_narrative
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return report


@staff.post(
    "/students/{student_membership_id}/recommendations",
    summary="학생 맞춤 연습 과제 추천 생성 (강사)",
    description="학원 작품 기준(ACADEMY). 결과는 검토 대기(DRAFT). use_ai=true는 학생의 "
    "GROWTH_COACHING 동의 필요.",
    status_code=status.HTTP_201_CREATED,
    responses=WRITE | error_responses(503),
)
async def staff_generate_recommendations(
    academy_id: uuid.UUID,
    student_membership_id: uuid.UUID,
    data: RecommendationGenerate,
    response: Response,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> GenerationResult:
    svc = _svc(session, settings)
    scope = await svc.staff_scope(actor, student_membership_id)
    data = data.model_copy(update={"scope": GrowthScope.ACADEMY, "academy_id": academy_id})
    result = await svc.generate_recommendations(scope, data, profile)
    response.status_code = {"CREATED": 201, "EXISTING": 200, "QUEUED": 202}[result.status]
    return result


@staff.get(
    "/recommendations",
    summary="추천 과제 검토 대기·목록 (강사)",
    description="기본: DRAFT, IN_REVIEW. 담당 학생 것만. 최신순.",
    responses=READ,
)
async def staff_list_recommendations(
    academy_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
    pagination: PaginationQuery,
    status_filter: StatusQ = None,
    student_membership_id: uuid.UUID | None = None,
) -> Page[ReviewerRecommendationRead | RecommendationRead]:
    svc = _svc(session, settings)
    scope = Scope(actor.user_id, GrowthScope.ACADEMY, actor.academy_id, staff=actor)
    items, total = await svc.list_recommendations(
        scope,
        pagination,
        status_filter or [RecommendationStatus.DRAFT, RecommendationStatus.IN_REVIEW],
        student_membership_id,
    )
    return Page(items=items, total=total, limit=pagination.limit, offset=pagination.offset)


@staff.get("/recommendations/{recommendation_id}", summary="추천 과제 상세 (강사)", responses=READ)
async def staff_get_recommendation(
    academy_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerRecommendationRead:
    return await _svc(session, settings).staff_view(actor, recommendation_id)


@staff.patch(
    "/recommendations/{recommendation_id}",
    summary="추천 과제 수정 (강사)",
    description="과제명·설명·연습 방법·소요 시간·난이도·실기 유형. DRAFT → IN_REVIEW.",
    response_model=ReviewerRecommendationRead | RecommendationRead,
    responses=WRITE,
)
async def staff_update_recommendation(
    academy_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    data: RecommendationUpdate,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerRecommendationRead | RecommendationRead:
    return await _svc(session, settings).update(profile, recommendation_id, data, actor)


@staff.post(
    "/recommendations/{recommendation_id}/approve",
    summary="추천 과제 승인 (강사)",
    response_model=ReviewerRecommendationRead | RecommendationRead,
    responses=WRITE,
)
async def staff_approve_recommendation(
    academy_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    data: RecommendationDecision,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerRecommendationRead | RecommendationRead:
    return await _svc(session, settings).approve(profile, recommendation_id, data, actor)


@staff.post(
    "/recommendations/{recommendation_id}/reject",
    summary="추천 과제 반려 (강사)",
    response_model=ReviewerRecommendationRead | RecommendationRead,
    responses=WRITE,
)
async def staff_reject_recommendation(
    academy_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    data: RecommendationReject,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerRecommendationRead | RecommendationRead:
    return await _svc(session, settings).reject(profile, recommendation_id, data, actor)


@staff.post(
    "/recommendations/{recommendation_id}/distribute",
    summary="승인된 추천 과제 배포 (강사 → 기존 과제 시스템)",
    description="v0.3 과제(tasks)를 그 학생 1명 대상(STUDENTS)으로 만든다. class_id 생략 시 학생이 "
    "담당 반 1개에만 있어야 한다 (아니면 422 CLASS_REQUIRED, details.class_ids).",
    response_model=ReviewerRecommendationRead | RecommendationRead,
    responses=WRITE,
)
async def staff_distribute_recommendation(
    academy_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    data: RecommendationDistribute,
    actor: AcademyStaff,
    profile: ActiveProfile,
    session: DbSession,
    settings: AppSettings,
) -> ReviewerRecommendationRead | RecommendationRead:
    return await _svc(session, settings).distribute(profile, recommendation_id, data, actor)


@staff.get(
    "/recommendations/{recommendation_id}/history",
    summary="추천 과제 수정·승인 이력 (강사)",
    responses=READ,
)
async def staff_recommendation_history(
    academy_id: uuid.UUID,
    recommendation_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
) -> list[RecommendationHistoryRead]:
    return await _svc(session, settings).staff_history(actor, recommendation_id)


@staff.get("/jobs/{job_id}", summary="AI 생성 작업 상태 (강사)", responses=READ)
async def staff_growth_job(
    academy_id: uuid.UUID,
    job_id: uuid.UUID,
    actor: AcademyStaff,
    session: DbSession,
    settings: AppSettings,
) -> JobRead:
    return await _svc(session, settings).job_for_staff(actor, job_id)
