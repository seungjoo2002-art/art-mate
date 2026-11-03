import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.enums import (
    AcademyStatus,
    JoinRequestStatus,
    MembershipRole,
    MembershipStatus,
    ReviewDecision,
)
from app.schemas.common import APIModel

AcademyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


# ----------------------------------------------------------------------------- academies


class AcademyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: AcademyName
    description: Description | None = None


class MyMembership(APIModel):
    id: uuid.UUID
    role: MembershipRole
    status: MembershipStatus
    joined_at: datetime


class AcademySummary(APIModel):
    id: uuid.UUID
    name: str
    description: str | None
    status: AcademyStatus
    created_at: datetime


class AcademyListItem(AcademySummary):
    my_role: MembershipRole | None = None


class AcademyRead(AcademySummary):
    my_membership: MyMembership | None = None


class AcademyAdminRead(AcademySummary):
    created_by: uuid.UUID | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None


class AcademyReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecision
    note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


# ----------------------------------------------------------------------------- members


class MemberRead(APIModel):
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    avatar_path: str | None
    role: MembershipRole
    status: MembershipStatus
    joined_at: datetime
    left_at: datetime | None


class MemberRoleUpdate(BaseModel):
    """OWNER만 사용. 소속 강사를 MANAGER로 지정하거나 해제한다."""

    model_config = ConfigDict(extra="forbid")

    role: Literal[MembershipRole.MANAGER, MembershipRole.INSTRUCTOR]


# ----------------------------------------------------------------------------- join requests


class JoinRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: Note | None = None


class Applicant(APIModel):
    display_name: str
    avatar_path: str | None


class JoinRequestRead(APIModel):
    id: uuid.UUID
    academy_id: uuid.UUID
    user_id: uuid.UUID
    requested_role: MembershipRole
    status: JoinRequestStatus
    message: str | None
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime


class JoinRequestWithApplicant(JoinRequestRead):
    applicant: Applicant


class MyJoinRequest(JoinRequestRead):
    academy_name: str


class JoinRequestReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: ReviewDecision
    note: Note | None = None
