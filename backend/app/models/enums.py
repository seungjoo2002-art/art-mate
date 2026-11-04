"""도메인 상태·역할 값. DB에는 대문자 문자열 + CHECK 제약으로 저장한다."""

from enum import StrEnum


class UserType(StrEnum):
    """서비스 전체 사용자 유형 (profiles.user_type)."""

    STUDENT = "STUDENT"
    INSTRUCTOR = "INSTRUCTOR"
    # 시스템 관리자. API로는 절대 부여하지 않는다 (DB에서 수동 지정, docs 참고).
    ADMIN = "ADMIN"


# 회원가입(프로필 생성) 시 사용자가 스스로 고를 수 있는 유형
SELF_SELECTABLE_USER_TYPES: frozenset[UserType] = frozenset({UserType.STUDENT, UserType.INSTRUCTOR})


class AcademyStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"  # 강사가 등록 신청, 시스템 ADMIN 승인 대기
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"  # v0.3+ 운영 정지 (v0.2에는 전환 API 없음)


class MembershipRole(StrEnum):
    """학원 단위 역할. 시스템 ADMIN과 별개."""

    OWNER = "OWNER"  # 학원 등록자. 학원 관리자 권한 + MANAGER 지정/해제
    MANAGER = "MANAGER"  # OWNER가 지정한 강사. 가입 승인·멤버 관리
    INSTRUCTOR = "INSTRUCTOR"
    STUDENT = "STUDENT"


# 학원 관리자 권한(가입 승인, 멤버 관리)을 가진 역할
ACADEMY_ADMIN_ROLES: frozenset[MembershipRole] = frozenset(
    {MembershipRole.OWNER, MembershipRole.MANAGER}
)
# 강사 이상 (멤버 목록 조회 등)
ACADEMY_STAFF_ROLES: frozenset[MembershipRole] = ACADEMY_ADMIN_ROLES | {MembershipRole.INSTRUCTOR}


class MembershipStatus(StrEnum):
    """실제 소속 상태. 가입 '요청' 상태(JoinRequestStatus)와 구분한다."""

    ACTIVE = "ACTIVE"
    LEFT = "LEFT"  # 본인 탈퇴
    REMOVED = "REMOVED"  # 학원 관리자가 내보냄


class JoinRequestStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


# --------------------------------------------------------------------------- v0.3 학원 운영


class ClassStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"  # 종료된 반. 기록은 유지, 새 배정·과제·일정 불가


class ClassMemberRole(StrEnum):
    """반 안에서의 역할. 학원 역할에서 결정된다 (STUDENT → STUDENT, 그 외 → INSTRUCTOR)."""

    INSTRUCTOR = "INSTRUCTOR"  # 담당 강사
    STUDENT = "STUDENT"


class ClassMemberStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"  # 반 배정 해제 또는 학원 탈퇴·제외


class ScheduleExceptionKind(StrEnum):
    CANCELLATION = "CANCELLATION"  # 정규 수업 1회 휴강
    RESCHEDULE = "RESCHEDULE"  # 정규 수업 1회 날짜·시간 변경
    MAKEUP = "MAKEUP"  # 보강 (반 전체 또는 특정 학생)


class OccurrenceKind(StrEnum):
    """일정 조회 응답 전용 (DB에 저장하지 않음)."""

    REGULAR = "REGULAR"
    MAKEUP = "MAKEUP"


class OccurrenceStatus(StrEnum):
    """일정 조회 응답 전용 (DB에 저장하지 않음)."""

    SCHEDULED = "SCHEDULED"
    RESCHEDULED = "RESCHEDULED"  # 원래 날짜(original_date)에서 옮겨진 정규 수업
    CANCELLED = "CANCELLED"


class AttendanceStatus(StrEnum):
    PRESENT = "PRESENT"
    LATE = "LATE"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"  # 사유 결석 (병결 등)


class AttendanceSource(StrEnum):
    SELF_CHECK_IN = "SELF_CHECK_IN"  # 학생 출석 버튼
    INSTRUCTOR = "INSTRUCTOR"  # 강사가 직접 기록


class AttendanceAuditAction(StrEnum):
    CREATED = "CREATED"
    UPDATED = "UPDATED"


class TaskTargetType(StrEnum):
    CLASS = "CLASS"  # 배포 시점의 반 학생 전체
    STUDENTS = "STUDENTS"  # 반의 특정 학생


class TaskStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
