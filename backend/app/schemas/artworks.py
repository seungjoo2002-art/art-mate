import datetime as dt
import uuid
from typing import Annotated, ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, model_validator

from app.models.artwork import MAX_ARTWORK_STAGES, MAX_STAGE_NAME, MAX_WORK_MINUTES
from app.models.enums import (
    ArtworkExamStageCode,
    ArtworkProgress,
    ArtworkStage,
    ArtworkWorkCategory,
    ArtworkWorkStatus,
    FeedbackSource,
    FeedbackStatus,
    PhotoKind,
    PhotoStatus,
    PracticalType,
    TimerEventType,
    TimerState,
    TimeSource,
    TranscriptionStatus,
)
from app.schemas.fields import InputModel, PatchModel, Title
from app.schemas.image_refs import ImageRefsRead
from app.schemas.students import StudentRef

ArtworkDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
FileName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Topic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ExamMaterials = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]
WorkMethod = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Minutes = Annotated[int, Field(ge=1, le=MAX_WORK_MINUTES)]
StageName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_STAGE_NAME)
]


class StageSpecIn(InputModel):
    """작품 단계 1개 (v0.9.7). 배열 순서 = 단계 순서."""

    id: uuid.UUID | None = Field(
        default=None,
        description="기존 단계 (이름·순서 변경, 숨긴 단계 복원). 새 단계면 생략",
    )
    name: StageName = Field(examples=["스케치"], description=f"1~{MAX_STAGE_NAME}자")
    target_minutes: Minutes | None = Field(default=None, description="시험 모드 단계 목표 시간(분)")


StageList = Annotated[list[StageSpecIn], Field(min_length=1, max_length=MAX_ARTWORK_STAGES)]


class ArtworkStageRead(BaseModel):
    id: uuid.UUID
    name: str
    position: int = Field(description="0부터. 숨긴 단계는 의미 없음")
    target_minutes: int | None
    archived: bool = Field(description="연결된 데이터가 있어 지우지 않고 숨긴 단계")
    legacy_stage: ArtworkStage = Field(
        description="[호환] 위치로 정한 이전 고정 단계: 첫 SKETCH / 중간 PROGRESS / 마지막 FINAL"
    )


class ArtworkStagesUpdate(InputModel):
    stages: StageList = Field(
        description=(
            "바꿀 단계 목록 (순서대로). 빠진 기존 단계는 데이터가 있으면 숨기고, 없으면 지운다"
        )
    )


class ArtworkStagesResult(BaseModel):
    stages: list[ArtworkStageRead] = Field(description="활성 단계 (순서대로)")
    archived_stage_ids: list[uuid.UUID] = Field(
        description="사진·피드백이 있어 지우지 않고 숨긴 단계 (다시 목록에 넣으면 복원)"
    )
    deleted_stage_ids: list[uuid.UUID] = Field(description="연결된 데이터가 없어 지운 단계")


class ArtworkCreate(InputModel):
    title: Title = Field(examples=["석고 아그리파 소묘"])
    description: ArtworkDescription | None = None
    work_date: dt.date | None = Field(
        default=None, description="작업 날짜 (Asia/Seoul). 기본: 오늘"
    )
    academy_id: uuid.UUID | None = Field(
        default=None, description="학원 연결(선택). 그 학원에 학생으로 ACTIVE 소속이어야 한다"
    )
    class_id: uuid.UUID | None = Field(default=None, description="수업(반) 연결. academy_id 필요")
    task_id: uuid.UUID | None = Field(default=None, description="과제 연결. 본인에게 배정된 과제")
    practical_type: PracticalType | None = Field(
        default=None,
        description="실기 유형 (선택). 프로필의 practical_type을 기본값으로 채워 보내도 된다",
    )
    work_category: ArtworkWorkCategory | None = Field(
        default=None, description="작업 목적 (선택): MOCK_EXAM / PERSONAL_PRACTICE / CLASS_WORK"
    )
    # v0.9 F-2
    topic: Topic | None = Field(default=None, description="실기 주제 (시험 제시어 등)")
    exam_materials: ExamMaterials | None = Field(
        default=None, description="v0.9.8 시험 제시물 (예: 유리컵, 사과 2개, 흰 천)"
    )
    work_method: WorkMethod | None = Field(default=None, description="작업 방식 (재료·기법)")
    actual_minutes: Minutes | None = Field(
        default=None, description="실제 소요 시간(분, 1~1440). 타이머를 쓰면 종료 시 자동 기록"
    )
    time_limit_minutes: Minutes | None = Field(
        default=None, description="제한 시간(분, 1~1440). 모의 실기시험이면 입력"
    )
    # v0.9.7 사용자 정의 단계 (생략하면 스케치 / 채색 / 완성)
    stages: StageList | None = Field(
        default=None, description="작품 제작 단계 (1~10개, 순서대로). 생략하면 스케치·채색·완성"
    )
    # v0.9 F-8
    recommendation_id: uuid.UUID | None = Field(
        default=None,
        description="이 작품을 수행 작품으로 연결할 개인 맞춤 과제 (채택·완료된 본인 과제)",
    )


class ArtworkUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"title", "work_date"})

    title: Title | None = None
    description: ArtworkDescription | None = None
    work_date: dt.date | None = None
    academy_id: uuid.UUID | None = None
    class_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    practical_type: PracticalType | None = Field(default=None, description="null이면 미분류")
    work_category: ArtworkWorkCategory | None = Field(default=None, description="null이면 미분류")
    topic: Topic | None = None
    exam_materials: ExamMaterials | None = Field(default=None, description="v0.9.8 시험 제시물")
    work_method: WorkMethod | None = None
    actual_minutes: Minutes | None = Field(
        default=None, description="직접 입력(time_source=MANUAL). null이면 삭제"
    )
    time_limit_minutes: Minutes | None = Field(default=None, description="null이면 삭제")


class StageSummary(BaseModel):
    stage: ArtworkStage
    photo_count: int
    representative_photo_id: uuid.UUID | None
    first_uploaded_at: dt.datetime | None
    last_uploaded_at: dt.datetime | None


class ArtworkProgressRead(BaseModel):
    artwork_id: uuid.UUID
    progress: ArtworkProgress = Field(description="사진이 있는 가장 늦은 단계")
    completed: bool = Field(
        description="[호환용] FINAL 사진이 있음 (= has_final_photo). 작품 완료 여부는 work_status"
    )
    has_final_photo: bool = Field(description="FINAL 단계 사진이 있음 (작품 완료 처리 조건)")
    work_status: ArtworkWorkStatus = Field(description="학생이 직접 완료 처리한 작업 상태")
    stages: list[StageSummary]


class ArtworkRead(BaseModel):
    id: uuid.UUID
    title: str
    description: str | None
    work_date: dt.date
    academy_id: uuid.UUID | None
    student_membership_id: uuid.UUID | None
    class_id: uuid.UUID | None
    task_id: uuid.UUID | None
    practical_type: PracticalType | None = Field(description="실기 유형 (미분류면 null)")
    work_category: ArtworkWorkCategory | None = Field(description="작업 목적 (미분류면 null)")
    work_status: ArtworkWorkStatus = Field(description="IN_PROGRESS 작업 중 / COMPLETED 작품 완료")
    completed_at: dt.datetime | None = Field(description="작품 완료 시각 (COMPLETED일 때만)")
    progress: ArtworkProgress = Field(description="사진 단계 진행 (업로드된 가장 늦은 단계)")
    photo_count: int
    recording_count: int = Field(
        description="재생 가능한(ACTIVE) 피드백 녹음 수. 삭제·업로드 미완료 녹음 제외"
    )
    cover_photo_id: uuid.UUID | None = Field(description="대표 사진 (가장 늦은 단계의 대표 사진)")
    # v0.9 F-2
    topic: str | None = None
    exam_materials: str | None = None
    work_method: str | None = None
    actual_minutes: int | None = Field(default=None, description="실제 소요 시간 (분)")
    time_limit_minutes: int | None = Field(default=None, description="제한 시간 (분)")
    time_source: TimeSource | None = Field(default=None, description="MANUAL 직접 입력 / TIMER")
    over_time_limit: bool | None = Field(
        default=None, description="실제 시간 > 제한 시간 (둘 다 있을 때만 판단)"
    )
    created_at: dt.datetime
    updated_at: dt.datetime


class StaffArtworkRead(ArtworkRead):
    student: StudentRef


class PhotoRead(BaseModel):
    id: uuid.UUID
    artwork_id: uuid.UUID
    stage: ArtworkStage = Field(description="[호환] 이전 고정 단계 (stage_id의 위치로 계산)")
    stage_id: uuid.UUID | None = Field(default=None, description="작품 단계 (v0.9.7)")
    kind: PhotoKind = Field(
        default=PhotoKind.STAGE, description="STAGE 단계 사진 / REVISION 피드백 반영 수정 사진"
    )
    feedback_note_id: uuid.UUID | None = Field(
        default=None, description="수정 사진이 반영한 글 첨삭"
    )
    feedback_recording_id: uuid.UUID | None = Field(
        default=None, description="수정 사진이 반영한 녹음 첨삭"
    )
    status: PhotoStatus
    content_type: str
    size_bytes: int | None
    width: int | None
    height: int | None
    is_representative: bool
    uploaded_at: dt.datetime | None
    created_at: dt.datetime
    url: str | None = Field(default=None, description="include_urls=true일 때 Signed URL")
    url_expires_at: dt.datetime | None = None


class ArtworkDetail(ArtworkRead):
    stages: list[StageSummary]
    photos: list[PhotoRead] = Field(description="활성 단계의 사진 (단계 사진·수정 사진)")
    stage_plan: list[ArtworkStageRead] = Field(
        default_factory=list, description="작품 제작 단계 (v0.9.7, 활성 단계만 순서대로)"
    )


class StaffArtworkDetail(ArtworkDetail):
    student: StudentRef


class UploadRequest(InputModel):
    stage: ArtworkStage | None = Field(
        default=None,
        description="[호환] SKETCH / PROGRESS / FINAL → 그 위치의 단계. v0.9.7부터는 stage_id 사용",
    )
    stage_id: uuid.UUID | None = Field(default=None, description="작품 단계 (v0.9.7, 우선)")
    kind: PhotoKind = Field(
        default=PhotoKind.STAGE,
        description="STAGE 단계 사진 / REVISION 피드백 반영 수정 사진 (피드백 1개 필수)",
    )
    feedback_note_id: uuid.UUID | None = Field(default=None, description="REVISION: 반영한 글 첨삭")
    feedback_recording_id: uuid.UUID | None = Field(
        default=None, description="REVISION: 반영한 녹음 첨삭"
    )
    content_type: str = Field(examples=["image/jpeg"])
    file_size: int = Field(gt=0, description="바이트")
    file_name: FileName | None = Field(default=None, description="확장자 검증용 (저장하지 않음)")
    replaces_photo_id: uuid.UUID | None = Field(
        default=None, description="교체할 기존 사진. 완료 처리 시 기존 사진이 삭제된다"
    )


class UploadTarget(BaseModel):
    bucket: str
    path: str
    url: str = Field(description="Signed upload URL (PUT으로 파일 업로드)")
    token: str = Field(description="supabase-js uploadToSignedUrl(path, token, file)용")
    expires_at: dt.datetime = Field(description="이 시각 전에 업로드 + 완료 처리")


class UploadTicket(BaseModel):
    photo: PhotoRead
    upload: UploadTarget


class PhotoUpdate(InputModel):
    is_representative: bool = Field(description="true: 이 사진을 단계 대표 사진으로 지정")


class SignedUrl(BaseModel):
    photo_id: uuid.UUID
    url: str
    expires_at: dt.datetime


# ============================================================================ v0.9 F-2 타이머


class TimerEventCreate(InputModel):
    event: TimerEventType = Field(description="START / PAUSE / RESUME / STOP / RESET")
    occurred_at: AwareDatetime | None = Field(
        default=None,
        description="오프라인에서 모아 보낸 이벤트의 실제 시각 (생략하면 서버 시각). "
        "직전 이벤트보다 이르거나 미래·24시간 이전이면 422 `TIMER_INVALID_TIME`",
    )


class TimerEventRead(BaseModel):
    id: uuid.UUID
    event: TimerEventType
    occurred_at: dt.datetime
    elapsed_seconds: int = Field(description="이 이벤트 직후 누적 작업 시간 (초)")


class TimerRead(BaseModel):
    """저장된 이벤트로 계산한 현재 상태. 새로고침·앱 재시작 후 이 값으로 화면을 복원한다."""

    artwork_id: uuid.UUID
    state: TimerState
    elapsed_seconds: int = Field(description="현재 세션 누적 작업 시간 (RUNNING이면 지금까지)")
    running_since: dt.datetime | None = Field(
        description="RUNNING일 때 마지막 시작·재개 시각 (클라이언트가 이어서 표시)"
    )
    session_started_at: dt.datetime | None
    time_limit_minutes: int | None
    remaining_seconds: int | None = Field(description="제한 시간이 있으면 남은 시간 (음수 = 초과)")
    over_time_limit: bool | None
    actual_minutes: int | None = Field(description="작품에 기록된 실제 소요 시간 (분)")
    time_source: TimeSource | None
    server_time: dt.datetime = Field(description="계산 기준 서버 시각")
    events: list[TimerEventRead] = Field(description="현재 세션 이벤트 (최근 50개)")


# ============================================================================ VER.2 실기시험 단계


class ArtworkExamStageTarget(InputModel):
    stage: ArtworkExamStageCode = Field(
        description="IDEA 아이디어 / SKETCH 스케치 / COLOR 채색 / FINISH 마무리"
    )
    target_minutes: Minutes = Field(description="단계 목표 시간 (분)")


class ArtworkExamPlan(InputModel):
    """단계 순서 = 배열 순서. 시작 후에는 같은 구성으로 목표 시간만 바꿀 수 있다."""

    stages: list[ArtworkExamStageTarget] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _unique(self) -> "ArtworkExamPlan":
        if len({s.stage for s in self.stages}) != len(self.stages):
            raise ValueError("duplicate stage")
        return self


class ArtworkExamNext(InputModel):
    current_stage: ArtworkExamStageCode = Field(
        description="지금 화면의 단계 (서버의 현재 단계와 다르면 409 EXAM_STAGE_CONFLICT)"
    )


class ArtworkExamStageRead(BaseModel):
    stage: ArtworkExamStageCode
    label: str
    position: int
    target_minutes: int
    status: Literal["PENDING", "ACTIVE", "DONE"]
    elapsed_seconds: int = Field(description="단계 작업 시간 (일시정지 제외, ACTIVE면 지금까지)")
    over_target: bool
    started_at: dt.datetime | None
    ended_at: dt.datetime | None


class ArtworkExamRead(BaseModel):
    artwork_id: uuid.UUID
    stages: list[ArtworkExamStageRead] = Field(description="계획이 없으면 빈 배열")
    current_stage: ArtworkExamStageCode | None
    total_target_minutes: int
    timer: TimerRead = Field(description="기존 작품 타이머 상태 (같은 값)")


# ------------------------------------------------------------------ v0.9.7 단계 이력


class StageFeedbackEntry(BaseModel):
    """단계(또는 작품 전체)에 연결된 피드백 1개와 그 피드백을 반영한 수정 사진."""

    type: Literal["RECORDING", "NOTE"]
    id: uuid.UUID = Field(description="녹음 id 또는 글 첨삭 id")
    title: str | None = Field(description="녹음 제목 / 글 첨삭 첫 줄 (40자)")
    source: FeedbackSource | None = Field(description="글 첨삭의 출처 (녹음은 null)")
    feedback_at: dt.datetime | dt.date = Field(description="녹음 시각(업로드) / 첨삭 받은 날")
    transcription_status: TranscriptionStatus | None = Field(description="녹음 STT 상태")
    ai_feedback_id: uuid.UUID | None = Field(description="현재 AI 요약 (DRAFT/IN_REVIEW/APPROVED)")
    ai_feedback_status: FeedbackStatus | None
    revisions: list[PhotoRead] = Field(
        description="[호환] 이 피드백 뒤에 올린 사진으로 기록된 예전 수정 사진 (올린 순)"
    )
    revision_count: int
    image_refs: ImageRefsRead = Field(
        default_factory=ImageRefsRead, description="v0.9.8 이 피드백의 기준 이미지"
    )


class TimelineItem(BaseModel):
    """단계 타임라인 항목 (v0.9.8). 사진과 피드백을 올린 시각 순으로 섞는다."""

    type: Literal["PHOTO", "FEEDBACK"]
    at: dt.datetime
    photo: PhotoRead | None = None
    feedback: StageFeedbackEntry | None = None


class StageHistoryEntry(BaseModel):
    stage: ArtworkStageRead
    timeline: list[TimelineItem] = Field(
        default_factory=list,
        description="v0.9.8 이 단계의 사진(종류 무관)과 단계 피드백을 시각 순으로",
    )
    photos: list[PhotoRead] = Field(description="단계 사진 (피드백 전·일반 기록)")
    feedback: list[StageFeedbackEntry] = Field(description="이 단계의 피드백 (오래된 순)")
    unlinked_revisions: list[PhotoRead] = Field(
        description="연결된 피드백이 삭제된 수정 사진 (사진은 보존)"
    )
    revision_count: int = Field(description="이 단계에 올린 수정 사진 수")


class ArtworkStageHistory(BaseModel):
    """단계별 [사진 → 피드백 → 수정 사진] 이력. 수정이 잘 됐는지는 판단하지 않는다."""

    artwork_id: uuid.UUID
    stages: list[StageHistoryEntry] = Field(description="활성 단계 순서대로, 그 뒤 숨긴 단계")
    overall_feedback: list[StageFeedbackEntry] = Field(
        description="작품 전체 피드백 (단계 미지정). 수정 사진은 어느 단계에 있든 함께 표시"
    )
