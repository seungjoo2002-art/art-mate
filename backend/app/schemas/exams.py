import datetime as dt
import uuid
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field, StringConstraints

from app.models.enums import (
    ArtworkStage,
    ExamEndReason,
    ExamSessionStatus,
    ExamWorkStage,
)
from app.schemas.attendance import StudentRef
from app.schemas.fields import InputModel, PatchModel

ExamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ExamType = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
ExamDescription = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
TotalMinutes = Annotated[int, Field(ge=1, le=720, description="총 시험 시간(분)")]


class StageTargetInput(InputModel):
    stage: ArtworkStage
    offset_minutes: int = Field(ge=1, le=720, description="시험 시작 후 이 시각(분)까지 단계 완료")


StageTargets = Annotated[
    list[StageTargetInput],
    Field(
        min_length=3,
        max_length=3,
        description="SKETCH·PROGRESS·FINAL 각 1개, 순서대로 증가, FINAL ≤ total_minutes",
    ),
]


# ----------------------------------------------------------------------------- templates


class ExamTemplateCreate(InputModel):
    name: ExamName = Field(examples=["기초디자인 실전 모의고사"])
    exam_type: ExamType = Field(examples=["기초디자인"])
    description: ExamDescription | None = None
    total_minutes: TotalMinutes
    stage_targets: StageTargets


class ExamTemplateUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"name", "exam_type", "total_minutes"})

    name: ExamName | None = None
    exam_type: ExamType | None = None
    description: ExamDescription | None = None
    total_minutes: TotalMinutes | None = None
    stage_targets: StageTargets | None = None


class StageTargetsUpdate(InputModel):
    stage_targets: StageTargets


class StageTargetRead(BaseModel):
    stage: ArtworkStage
    offset_minutes: int


class ExamTemplateRead(BaseModel):
    id: uuid.UUID
    academy_id: uuid.UUID
    name: str
    exam_type: str
    description: str | None
    total_minutes: int
    stage_targets: list[StageTargetRead]
    is_archived: bool
    created_by: uuid.UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime


# ----------------------------------------------------------------------------- sessions


class ExamSessionCreate(InputModel):
    template_id: uuid.UUID
    class_id: uuid.UUID
    title: ExamName | None = Field(default=None, description="기본: 템플릿 이름")
    start_now: bool = Field(default=False, description="true면 생성과 동시에 시작")


class TimerStage(BaseModel):
    stage: ArtworkStage
    offset_minutes: int
    target_at: dt.datetime | None = Field(description="목표 시각 (시작 전 null)")
    seconds_remaining: int | None = Field(
        description="목표 시각까지 남은 초 (진행 중일 때만, 지났으면 0)"
    )
    passed: bool


class ExamTimer(BaseModel):
    """서버가 계산한 타이머 상태.

    프론트는 `server_time`으로 시계 오차를 보정해 로컬에서 카운트다운한다.
    """

    server_time: dt.datetime
    status: ExamSessionStatus = Field(description="시간이 다 되면 ENDED (end_reason=TIME_UP)")
    end_reason: ExamEndReason | None
    started_at: dt.datetime | None
    ends_at: dt.datetime | None = Field(description="종료 예정 시각")
    ended_at: dt.datetime | None
    total_seconds: int
    elapsed_seconds: int
    remaining_seconds: int
    stages: list[TimerStage]
    expected_stage: ExamWorkStage | None = Field(
        description="지금 시각에 해야 할 단계 (진행 중일 때만). 모든 목표가 지나면 DONE"
    )
    current_target: TimerStage | None = Field(description="다음에 도래할 단계 목표")
    next_alert_at: dt.datetime | None = Field(
        description="다음 알림 시각 (다음 단계 목표 또는 종료). 진행 중일 때만"
    )


class ExamSessionSummary(BaseModel):
    id: uuid.UUID
    academy_id: uuid.UUID
    class_id: uuid.UUID
    class_name: str
    template_id: uuid.UUID | None
    title: str
    exam_type: str
    total_minutes: int
    created_at: dt.datetime
    timer: ExamTimer


class StageCount(BaseModel):
    stage: ExamWorkStage
    count: int


class ParticipantRead(BaseModel):
    id: uuid.UUID
    student: StudentRef
    current_stage: ExamWorkStage
    stage_updated_at: dt.datetime | None
    sketch_at: dt.datetime | None
    progress_at: dt.datetime | None
    final_at: dt.datetime | None
    done_at: dt.datetime | None
    behind_schedule: bool = Field(description="진행 중이고 현재 단계가 기대 단계보다 늦음")


class ExamSessionDetail(ExamSessionSummary):
    participant_count: int
    stage_counts: list[StageCount]
    behind_count: int
    participants: list[ParticipantRead]


class MyParticipation(BaseModel):
    current_stage: ExamWorkStage
    stage_updated_at: dt.datetime | None
    sketch_at: dt.datetime | None
    progress_at: dt.datetime | None
    final_at: dt.datetime | None
    done_at: dt.datetime | None
    behind_schedule: bool


class MyExam(ExamSessionSummary):
    me: MyParticipation


class StageChange(InputModel):
    stage: Literal[
        ExamWorkStage.SKETCH, ExamWorkStage.PROGRESS, ExamWorkStage.FINAL, ExamWorkStage.DONE
    ]
