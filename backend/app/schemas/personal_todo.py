import datetime as dt
import uuid
from typing import Annotated, ClassVar

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.fields import InputModel, PatchModel, Title

TodoNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class PersonalTodoCreate(InputModel):
    title: Title = Field(examples=["크로키 10장"])
    note: TodoNote | None = None
    due_date: dt.date | None = Field(default=None, description="Asia/Seoul 날짜. null = 날짜 없음")


class PersonalTodoUpdate(PatchModel):
    NOT_NULLABLE: ClassVar[frozenset[str]] = frozenset({"title", "is_done"})

    title: Title | None = None
    note: TodoNote | None = None
    due_date: dt.date | None = None
    is_done: bool | None = None


class PersonalTodoRead(BaseModel):
    id: uuid.UUID
    title: str
    note: str | None
    due_date: dt.date | None
    is_done: bool
    completed_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime
