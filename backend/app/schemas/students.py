"""학원 내 학생 표시 정보 (작품·과제 응답 공통).

v0.5.1: 출석(schemas/attendance.py) 제거에 따라 이 모듈로 옮겼다.
"""

import uuid

from pydantic import BaseModel

from app.models.membership import AcademyMembership
from app.models.profile import Profile


class StudentRef(BaseModel):
    """학원 내 학생 표시 정보 (이메일 등 계정 정보는 포함하지 않음)."""

    membership_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    avatar_path: str | None


def student_ref(membership: AcademyMembership, profile: Profile) -> StudentRef:
    return StudentRef(
        membership_id=membership.id,
        user_id=profile.id,
        display_name=profile.display_name,
        avatar_path=profile.avatar_path,
    )
