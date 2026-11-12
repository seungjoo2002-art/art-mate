import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from app.models.enums import PracticalType, StudentGrade, UserType
from app.schemas.common import APIModel

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
RealName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
LearningGoal = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]

# Storage 객체 경로: avatars/<user_id>/<파일명>. URL·상위 경로(..)·절대 경로는 허용하지 않는다.
_AVATAR_PATH = re.compile(r"^avatars/[0-9a-f-]{36}/(?!\.{1,2}$)[A-Za-z0-9._-]{1,200}$")


class ProfileCreate(BaseModel):
    """회원가입 직후 1회 호출. ADMIN은 선택할 수 없다."""

    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName
    user_type: Literal[UserType.STUDENT, UserType.INSTRUCTOR] = Field(
        description="STUDENT 또는 INSTRUCTOR (ADMIN 불가)"
    )
    practical_type: PracticalType | None = Field(
        default=None,
        description="실기 유형 (선택). 선택지: GET /api/v1/meta/options 의 practical_types",
    )
    real_name: RealName | None = Field(
        default=None,
        description="VER.2 실명 (선택, 본인에게만 보임). display_name은 공개 닉네임",
    )


class ProfileUpdate(BaseModel):
    """본인 프로필 수정. user_type·is_active 등은 변경할 수 없다 (보내면 422).

    practical_type: 보내지 않으면 유지, null이면 미선택으로 되돌린다.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName | None = None
    avatar_path: str | None = Field(
        default=None,
        max_length=512,
        description="Supabase Storage 경로 `avatars/<본인 user_id>/<파일명>`. null이면 삭제",
    )
    practical_type: PracticalType | None = Field(
        default=None, description="실기 유형. null이면 미선택으로 변경"
    )
    grade: StudentGrade | None = Field(default=None, description="학년 (v0.9). null이면 미선택")
    real_name: RealName | None = Field(
        default=None, description="VER.2 실명 (본인에게만 보임). null이면 삭제"
    )
    learning_goal: LearningGoal | None = Field(
        default=None,
        description="개인 학습 목표 (v0.9, 500자). 바꾸면 수정일 갱신, null이면 삭제",
    )

    @field_validator("avatar_path")
    @classmethod
    def _validate_avatar_path(cls, value: str | None) -> str | None:
        if value is not None and not _AVATAR_PATH.fullmatch(value):
            raise ValueError("avatar_path must look like 'avatars/<user_id>/<file name>'")
        return value

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "ProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        if "display_name" in self.model_fields_set and self.display_name is None:
            raise ValueError("display_name cannot be null")
        return self


class ProfileRead(APIModel):
    id: uuid.UUID
    display_name: str
    user_type: UserType
    avatar_path: str | None
    practical_type: PracticalType | None = Field(description="실기 유형 (미선택이면 null)")
    grade: StudentGrade | None = Field(default=None, description="학년 (v0.9)")
    learning_goal: str | None = Field(default=None, description="개인 학습 목표 (v0.9)")
    learning_goal_updated_at: datetime | None = Field(
        default=None, description="학습 목표 수정일 (v0.9)"
    )
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MeRead(ProfileRead):
    real_name: str | None = Field(
        default=None, description="VER.2 실명 (이 응답에만 포함, 공개 응답에는 없음)"
    )
    email: str | None = Field(
        default=None, description="Supabase Auth 계정 이메일 (토큰에서 읽음, DB에 저장하지 않음)"
    )


# ============================================================================ VER.2 기본 시험 목표
# 시간


class UserExamDefaultsRead(BaseModel):
    stages: list[dict] = Field(  # type: ignore[type-arg]
        description="[{stage, target_minutes}] 순서대로 (ArtworkExamPlan과 같은 모양)"
    )
    source: Literal["ACCOUNT", "DEFAULT"] = Field(
        description="ACCOUNT: 계정에 저장된 값 / DEFAULT: 아직 저장 안 함 (앱 기본값)"
    )
