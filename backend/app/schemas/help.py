import datetime as dt
import uuid
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.enums import EstimateSource, HelpRequestStatus
from app.schemas.attendance import StudentRef
from app.schemas.fields import InputModel

HelpNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class HelpRequestCreate(InputModel):
    class_id: uuid.UUID
    note: HelpNote | None = Field(default=None, examples=["명암 단계가 헷갈려요"])
    artwork_id: uuid.UUID | None = Field(default=None, description="질문할 내 작품 (선택)")


class WaitEstimate(BaseModel):
    """예상 대기시간 (항상 추정치)."""

    estimated_wait_seconds: int
    ahead_count: int = Field(description="내 앞 대기 인원 + 현재 처리(호출) 중인 인원")
    active_handlers: int = Field(description="이 반 담당 강사 수 (최소 1로 계산)")
    average_handle_seconds: int = Field(description="질문 1건 평균 처리시간")
    sample_size: int = Field(description="평균 계산에 쓴 최근 완료 질문 수")
    source: EstimateSource
    is_default: bool = Field(description="true: 기록 부족으로 기본값 사용")


class HelpRequestBase(BaseModel):
    id: uuid.UUID
    class_id: uuid.UUID
    status: HelpRequestStatus
    note: str | None
    artwork_id: uuid.UUID | None
    requested_at: dt.datetime
    called_at: dt.datetime | None
    started_at: dt.datetime | None
    completed_at: dt.datetime | None
    closed_at: dt.datetime | None
    position: int | None = Field(description="대기 순번 (WAITING일 때만, 1부터)")
    called_by_name: str | None = Field(description="호출한 강사 표시 이름")
    handled_by_name: str | None


class MyHelpRequest(HelpRequestBase):
    class_name: str
    is_active: bool = Field(description="WAITING / CALLED / IN_PROGRESS")
    estimate: WaitEstimate | None = Field(description="WAITING일 때만")
    server_time: dt.datetime


class StaffHelpRequest(HelpRequestBase):
    student: StudentRef
    waiting_seconds: int = Field(description="요청 후 경과 시간 (초)")
    called_by: uuid.UUID | None
    handled_by: uuid.UUID | None


class HelpQueue(BaseModel):
    """반별 질문 대기열 (강사 화면). 폴링용 집계 응답."""

    class_id: uuid.UUID
    class_name: str
    server_time: dt.datetime
    waiting_count: int
    active_count: int = Field(description="CALLED + IN_PROGRESS")
    active: list[StaffHelpRequest] = Field(description="호출·처리 중 (호출 시각 순)")
    waiting: list[StaffHelpRequest] = Field(description="대기 중 (순번 순)")
    estimate_for_new_request: WaitEstimate
    last_changed_at: dt.datetime | None = Field(
        description="대기열 마지막 변경 시각. 폴링 시 값이 같으면 화면을 다시 그리지 않아도 된다"
    )
    recommended_poll_seconds: int


class ClassEstimate(BaseModel):
    class_id: uuid.UUID
    server_time: dt.datetime
    waiting_count: int
    active_count: int
    estimate: WaitEstimate
