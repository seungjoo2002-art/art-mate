"""학습 목표: 복수 지망 대학 (v0.9 F-1). 사용자가 직접 입력한다 (외부 입시 정보·합격 예측 없음)."""

import datetime as dt
import uuid
from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.models.enums import PracticalType, StudentGrade
from app.schemas.fields import InputModel, PatchModel

MAX_TARGET_UNIVERSITIES = 10

Name100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Note200 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class TargetUniversityCreate(InputModel):
    university_name: Name100
    department: Name100 | None = Field(default=None, description="학과·전공 (선택)")
    admission_note: Note200 | None = Field(
        default=None, description="전형·메모 (예: 수시 실기 / 정시) — 자유 입력"
    )
    priority: int | None = Field(
        default=None,
        ge=1,
        le=MAX_TARGET_UNIVERSITIES,
        description="지망 순위 (1 = 1지망). 생략하면 맨 뒤. 지정하면 그 자리에 넣고 뒤로 민다",
    )


class TargetUniversityUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"university_name", "priority"})

    university_name: Name100 | None = None
    department: Name100 | None = None
    admission_note: Note200 | None = None
    priority: int | None = Field(
        default=None, ge=1, le=MAX_TARGET_UNIVERSITIES, description="다른 순위로 이동"
    )


class TargetUniversityOrder(InputModel):
    ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=MAX_TARGET_UNIVERSITIES,
        description="새 순서 (1지망부터). 내 지망 대학 전체를 빠짐없이 한 번씩",
    )

    @model_validator(mode="after")
    def _unique(self) -> "TargetUniversityOrder":
        if len(set(self.ids)) != len(self.ids):
            raise ValueError("duplicate id")
        return self


class TargetUniversityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    university_name: str
    department: str | None
    admission_note: str | None
    priority: int
    created_at: dt.datetime
    updated_at: dt.datetime


class LearningContext(BaseModel):
    """성장 분석·리포트에 함께 내려 주는 학습 목표 맥락 (AI 외부 전송에는 쓰지 않는다)."""

    practical_type: PracticalType | None
    grade: StudentGrade | None
    learning_goal: str | None
    learning_goal_updated_at: dt.datetime | None
    target_universities: list[TargetUniversityRead]
