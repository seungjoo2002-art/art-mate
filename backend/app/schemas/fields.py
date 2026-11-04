"""v0.3 입력 스키마가 공유하는 필드 타입과 검증 도우미."""

import datetime as dt
from typing import Annotated, Any, ClassVar, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, model_validator

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Location = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


def _naive_wall_time(value: dt.time) -> dt.time:
    if value.tzinfo is not None:
        raise ValueError("시간대 없는 학원 현지 시간(HH:MM)으로 보내세요 (예: 16:00)")
    return value.replace(second=0, microsecond=0)


# 학원 현지(Asia/Seoul) 벽시계 시간. "16:00" 또는 "16:00:00", 초는 버린다.
WallTime = Annotated[dt.time, AfterValidator(_naive_wall_time)]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatchModel(InputModel):
    """부분 수정 스키마. 보내지 않은 필드는 바꾸지 않고, `null`은 '값 지우기'를 뜻한다.

    `NOT_NULLABLE`에 적은 필드는 null로 지울 수 없다 (보내지 않으면 유지).
    """

    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_null_for_required(self) -> Self:
        for name in sorted(self.NOT_NULLABLE & self.model_fields_set):
            if getattr(self, name) is None:
                raise ValueError(f"'{name}' cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)
