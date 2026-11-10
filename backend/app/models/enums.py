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


# v0.5.1: 출석·시험 타이머·질문 콜은 서비스에서 제외됐다. 아래 해당 enum은 보존 중인 테이블의
# CHECK 제약·ORM 모델과 맞추기 위해서만 남겨 둔다 (API에서 사용하지 않음).


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


# --------------------------------------------------------------------------- v0.4 작품·시험


class ArtworkStage(StrEnum):
    """작품 사진 단계 (작업 순서대로)."""

    SKETCH = "SKETCH"
    PROGRESS = "PROGRESS"
    FINAL = "FINAL"


ARTWORK_STAGE_ORDER: tuple[ArtworkStage, ...] = (
    ArtworkStage.SKETCH,
    ArtworkStage.PROGRESS,
    ArtworkStage.FINAL,
)


class ArtworkProgress(StrEnum):
    """작품 진행 상태 (응답 전용, 업로드된 사진 중 가장 늦은 단계)."""

    NOT_STARTED = "NOT_STARTED"
    SKETCH = "SKETCH"
    PROGRESS = "PROGRESS"
    FINAL = "FINAL"


class PhotoStatus(StrEnum):
    PENDING = "PENDING"  # 업로드 URL 발급됨, 완료 처리 전
    ACTIVE = "ACTIVE"  # 검증 완료, 작품에 연결됨
    DELETED = "DELETED"  # 삭제·교체됨 (Storage 파일 정리는 storage_cleanup_pending)


class ExamSessionStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class ExamEndReason(StrEnum):
    MANUAL = "MANUAL"  # 강사가 종료
    TIME_UP = "TIME_UP"  # 총시간 경과


class ExamWorkStage(StrEnum):
    """시험 중 학생의 현재 작업 단계."""

    NOT_STARTED = "NOT_STARTED"
    SKETCH = "SKETCH"
    PROGRESS = "PROGRESS"
    FINAL = "FINAL"
    DONE = "DONE"


EXAM_WORK_STAGE_ORDER: tuple[ExamWorkStage, ...] = tuple(ExamWorkStage)


# ----------------------------------------------------------------- v0.5 질문 콜(제외)·녹음


class HelpRequestStatus(StrEnum):
    WAITING = "WAITING"  # 대기 중 (순번 있음)
    CALLED = "CALLED"  # 강사가 호출함 (학생이 오기를 기다림)
    IN_PROGRESS = "IN_PROGRESS"  # 질문 처리 중
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"  # 학생 또는 강사가 취소
    SKIPPED = "SKIPPED"  # 호출했지만 응답 없음 등으로 건너뜀


ACTIVE_HELP_STATUSES: frozenset[HelpRequestStatus] = frozenset(
    {HelpRequestStatus.WAITING, HelpRequestStatus.CALLED, HelpRequestStatus.IN_PROGRESS}
)


class HelpQueueEventType(StrEnum):
    CREATED = "CREATED"
    CALLED = "CALLED"
    REQUEUED = "REQUEUED"  # 호출 취소 → 원래 순번으로 대기열 복귀
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SKIPPED = "SKIPPED"


class EstimateSource(StrEnum):
    """예상 대기시간 근거 (응답 전용)."""

    RECENT_AVERAGE = "RECENT_AVERAGE"  # 이 반의 최근 완료 질문 평균 처리시간
    DEFAULT = "DEFAULT"  # 기록이 부족해 기본값 사용


class RecordingStatus(StrEnum):
    PENDING = "PENDING"  # 업로드 URL 발급됨, 완료 처리 전
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class TranscriptionStatus(StrEnum):
    """STT 처리 상태 (v0.6에서 사용, v0.5는 항상 NOT_REQUESTED)."""

    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ConsentType(StrEnum):
    VOICE_RECORDING = "VOICE_RECORDING"


class ConsentGrantor(StrEnum):
    SELF = "SELF"  # 본인 동의
    GUARDIAN = "GUARDIAN"  # 법정대리인 동의 (만 14세 미만)


# --------------------------------------------------------------------------- v0.5.1 기획 변경


class PracticalType(StrEnum):
    """실기 유형 (profiles.practical_type, artworks.practical_type).

    값 추가: 여기에 멤버와 라벨을 추가하고 CHECK 제약을 바꾸는 마이그레이션을 만든다
    (varchar + CHECK 저장이라 테이블 재작성 없이 제약만 교체된다).
    이미 저장된 값은 삭제·변경하지 않는다.
    """

    BASIC_DESIGN = "BASIC_DESIGN"
    THINKING_SHIFT = "THINKING_SHIFT"
    IDEA_EXPRESSION = "IDEA_EXPRESSION"
    DRAWING = "DRAWING"
    WATERCOLOR = "WATERCOLOR"
    OTHER = "OTHER"


PRACTICAL_TYPE_LABELS: dict[PracticalType, str] = {
    PracticalType.BASIC_DESIGN: "기초디자인",
    PracticalType.THINKING_SHIFT: "사고의 전환",
    PracticalType.IDEA_EXPRESSION: "발상과 표현",
    PracticalType.DRAWING: "소묘",
    PracticalType.WATERCOLOR: "수채화",
    PracticalType.OTHER: "기타",
}


class ArtworkWorkCategory(StrEnum):
    """작업 목적 (artworks.work_category). 실기 유형과 독립 — 기초디자인 + 모의시험 조합 가능."""

    MOCK_EXAM = "MOCK_EXAM"
    PERSONAL_PRACTICE = "PERSONAL_PRACTICE"
    CLASS_WORK = "CLASS_WORK"


WORK_CATEGORY_LABELS: dict[ArtworkWorkCategory, str] = {
    ArtworkWorkCategory.MOCK_EXAM: "모의시험",
    ArtworkWorkCategory.PERSONAL_PRACTICE: "개인 연습",
    ArtworkWorkCategory.CLASS_WORK: "수업 작품",
}


class ArtworkWorkStatus(StrEnum):
    """작품 작업 상태 (artworks.work_status).

    사진 단계(progress)와 별개로 학생이 직접 완료 처리한다.
    """

    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


WORK_STATUS_LABELS: dict[ArtworkWorkStatus, str] = {
    ArtworkWorkStatus.IN_PROGRESS: "작업 중",
    ArtworkWorkStatus.COMPLETED: "작품 완료",
}


# --------------------------------------------------------------------------- v0.6 AI 첨삭


class AiJobType(StrEnum):
    TRANSCRIBE = "TRANSCRIBE"  # faster-whisper STT (서버 내부 처리)
    SUMMARIZE = "SUMMARIZE"  # Gemini 첨삭 요약·분류 (외부 전송)
    # v0.7 성장 코치 (Gemini, 외부 전송 · GROWTH_COACHING 동의 필요)
    GROWTH_REPORT = "GROWTH_REPORT"  # 성장 리포트 설명문
    PRACTICE_RECOMMEND = "PRACTICE_RECOMMEND"  # AI 맞춤 연습 과제


class AiJobStatus(StrEnum):
    QUEUED = "QUEUED"  # 대기 (run_after 이후 실행)
    RUNNING = "RUNNING"  # Worker가 처리 중 (lease 만료 시 다른 Worker가 회수)
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"  # 재시도 소진 또는 재시도 불가 오류 → 사용자가 재시도 요청 가능
    CANCELLED = "CANCELLED"  # 동의 철회·녹음 삭제 등으로 취소


ACTIVE_JOB_STATUSES: frozenset[AiJobStatus] = frozenset({AiJobStatus.QUEUED, AiJobStatus.RUNNING})


class AiProvider(StrEnum):
    GOOGLE_GEMINI = "GOOGLE_GEMINI"


class AiConsentPurpose(StrEnum):
    """외부 AI 전송 동의의 목적 (목적별로 따로 동의·철회한다)."""

    FEEDBACK_SUMMARY = "FEEDBACK_SUMMARY"  # v0.6: 첨삭 전사문 요약
    GROWTH_COACHING = "GROWTH_COACHING"  # v0.7: 누적 첨삭 기반 성장 리포트 설명·맞춤 과제


class FeedbackStatus(StrEnum):
    """첨삭(feedback_summaries) 검토 상태.

    DRAFT(AI 초안) → IN_REVIEW(검토·수정 중) → APPROVED(확정).
    REJECTED: 검토자가 초안을 쓰지 않기로 함 (재생성 가능). SUPERSEDED: 재생성으로 대체됨.
    """

    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


# 녹음당 하나만 존재할 수 있는 '현재' 첨삭 상태
CURRENT_FEEDBACK_STATUSES: frozenset[FeedbackStatus] = frozenset(
    {FeedbackStatus.DRAFT, FeedbackStatus.IN_REVIEW, FeedbackStatus.APPROVED}
)


class ReviewMode(StrEnum):
    """누가 확정하는가. 학원 연결 작품 = 담당 강사, 개인 작품 = 학생 본인."""

    INSTRUCTOR = "INSTRUCTOR"
    SELF = "SELF"


class FeedbackItemKind(StrEnum):
    STRENGTH = "STRENGTH"  # 잘한 점
    WEAKNESS = "WEAKNESS"  # 부족한 점
    FIX = "FIX"  # 구체적인 수정 방법
    NEXT_TIP = "NEXT_TIP"  # 다음 작품에서 주의할 점


class FeedbackItemOrigin(StrEnum):
    AI = "AI"  # AI 초안 그대로
    EDITED = "EDITED"  # AI 항목을 사람이 수정
    ADDED = "ADDED"  # 사람이 새로 추가


class WeaknessCategory(StrEnum):
    """약점 카테고리. v0.7 반복 약점 분석·v0.8 참고작 추천의 기준 키 (값 변경 금지, 추가만)."""

    COMPOSITION = "COMPOSITION"
    FORM = "FORM"
    PROPORTION = "PROPORTION"
    PERSPECTIVE = "PERSPECTIVE"
    VALUE = "VALUE"
    COLOR = "COLOR"
    TEXTURE = "TEXTURE"
    RENDERING = "RENDERING"
    FINISH = "FINISH"
    OTHER = "OTHER"
    # v0.9 (기능명세서 V2 F-4): 시간 관리 (제한 시간 안에 완성하지 못함 등)
    TIME_MANAGEMENT = "TIME_MANAGEMENT"


WEAKNESS_CATEGORY_LABELS: dict[WeaknessCategory, str] = {
    WeaknessCategory.COMPOSITION: "구도",
    WeaknessCategory.FORM: "형태",
    WeaknessCategory.PROPORTION: "비례",
    WeaknessCategory.PERSPECTIVE: "투시",
    WeaknessCategory.VALUE: "명암",
    WeaknessCategory.COLOR: "색채",
    WeaknessCategory.TEXTURE: "질감",
    WeaknessCategory.RENDERING: "묘사",
    WeaknessCategory.FINISH: "완성도",
    WeaknessCategory.OTHER: "기타",
    WeaknessCategory.TIME_MANAGEMENT: "시간 관리",
}

FEEDBACK_ITEM_KIND_LABELS: dict[FeedbackItemKind, str] = {
    FeedbackItemKind.STRENGTH: "잘한 점",
    FeedbackItemKind.WEAKNESS: "부족한 점",
    FeedbackItemKind.FIX: "수정 방법",
    FeedbackItemKind.NEXT_TIP: "다음 작품 주의점",
}


class ReviewAction(StrEnum):
    CREATED = "CREATED"  # AI 초안 생성
    EDITED = "EDITED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REOPENED = "REOPENED"  # 승인 취소 → 다시 검토
    SUPERSEDED = "SUPERSEDED"  # 재생성으로 대체


# 녹음 단위 작업 (recording_id 필수)
RECORDING_JOB_TYPES: frozenset[AiJobType] = frozenset({AiJobType.TRANSCRIBE, AiJobType.SUMMARIZE})


# --------------------------------------------------------------------------- v0.7 성장 코치


class GrowthScope(StrEnum):
    """분석 대상 작품 범위."""

    ALL = "ALL"  # 학생 본인의 모든 작품 (학생만)
    PERSONAL = "PERSONAL"  # 학원 미연결 개인 작품 (학생만, 추천은 본인 채택)
    ACADEMY = "ACADEMY"  # 특정 학원에 연결된 작품 (학생 본인·담당 강사, 추천은 강사 승인)


class ReportPeriod(StrEnum):
    WEEK = "WEEK"  # 오늘 포함 최근 7일 (Asia/Seoul)
    MONTH = "MONTH"  # 오늘 포함 최근 30일
    ALL = "ALL"  # 전체 기간
    CUSTOM = "CUSTOM"  # from~to 지정


class ReportStatus(StrEnum):
    READY = "READY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"  # 분석에 필요한 승인 첨삭 작품이 부족


class NarrativeStatus(StrEnum):
    """리포트의 AI 설명문 상태 (통계와 별개)."""

    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"  # 동의 없음·기능 꺼짐·데이터 부족
    INVALIDATED = "INVALIDATED"  # 근거 첨삭이 삭제되어 설명문을 지움


class RecommendationSource(StrEnum):
    RULE = "RULE"  # 규칙 기반 (외부 호출 없음)
    AI = "AI"  # Gemini


class RecommendationStatus(StrEnum):
    """연습 과제 추천 상태.

    강사 검토(학원 작품): DRAFT → IN_REVIEW → APPROVED → DISTRIBUTED(tasks로 배포)
    본인 채택(개인 작품): DRAFT → IN_REVIEW → ADOPTED → COMPLETED
    공통: REJECTED(반려), SUPERSEDED(새 추천으로 대체)
    """

    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    DISTRIBUTED = "DISTRIBUTED"
    ADOPTED = "ADOPTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


OPEN_RECOMMENDATION_STATUSES: frozenset[RecommendationStatus] = frozenset(
    {RecommendationStatus.DRAFT, RecommendationStatus.IN_REVIEW}
)
# 같은 데이터로 다시 만들지 않는 상태 (중복 생성 방지 대상)
LIVE_RECOMMENDATION_STATUSES: frozenset[RecommendationStatus] = frozenset(
    {
        RecommendationStatus.DRAFT,
        RecommendationStatus.IN_REVIEW,
        RecommendationStatus.APPROVED,
        RecommendationStatus.DISTRIBUTED,
        RecommendationStatus.ADOPTED,
        RecommendationStatus.COMPLETED,
    }
)


class Difficulty(StrEnum):
    EASY = "EASY"
    NORMAL = "NORMAL"
    HARD = "HARD"


DIFFICULTY_LABELS: dict[Difficulty, str] = {
    Difficulty.EASY: "쉬움",
    Difficulty.NORMAL: "보통",
    Difficulty.HARD: "어려움",
}


class RecommendationAction(StrEnum):
    CREATED = "CREATED"
    EDITED = "EDITED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DISTRIBUTED = "DISTRIBUTED"
    ADOPTED = "ADOPTED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    # v0.9 F-8: 과제 시작, 작품 연결·해제
    STARTED = "STARTED"
    ARTWORK_LINKED = "ARTWORK_LINKED"
    ARTWORK_UNLINKED = "ARTWORK_UNLINKED"


class TrendDirection(StrEnum):
    """응답 전용: 최근 구간과 이전 구간의 작품 단위 지적 비율 비교."""

    MORE_FREQUENT = "MORE_FREQUENT"
    LESS_FREQUENT = "LESS_FREQUENT"
    SIMILAR = "SIMILAR"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Confidence(StrEnum):
    """응답 전용: 분석에 쓴 작품 수 기준의 신뢰도 표시."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# --------------------------------------------------------------------------- v0.8 참고작·커뮤니티


class SharingPurpose(StrEnum):
    """작품 공유 동의의 목적 (따로 동의·철회)."""

    COMMUNITY = "COMMUNITY"  # 커뮤니티 게시
    REFERENCE = "REFERENCE"  # F-15 참고작 추천에 활용


class SharingScope(StrEnum):
    ACADEMY = "ACADEMY"  # 작품이 연결된 학원의 ACTIVE 멤버에게만
    PLATFORM = "PLATFORM"  # 로그인한 ART MATE 사용자 전체


class AuthorDisplay(StrEnum):
    NAME = "NAME"  # 표시 이름 공개
    ANONYMOUS = "ANONYMOUS"  # '익명 학생'


class SharedImageStatus(StrEnum):
    PENDING = "PENDING"  # 파생 이미지 업로드 중
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"  # 공유 철회 (Storage 정리는 storage_cleanup_pending)


class ReferenceReviewStatus(StrEnum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ReferenceSetStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"  # 새로고침으로 대체


class ReferenceResultStatus(StrEnum):
    """응답 전용: 참고작 추천 결과 상태."""

    READY = "READY"
    NO_VERIFIED_REFERENCES = "NO_VERIFIED_REFERENCES"  # 검증된 우수 사례가 없음
    NO_REPEATED_WEAKNESS = "NO_REPEATED_WEAKNESS"  # 추천 기준이 될 반복 약점이 없음
    NOT_GENERATED = "NOT_GENERATED"  # 아직 새로고침하지 않음


class ReferenceReason(StrEnum):
    """응답 전용: 추천 근거 코드."""

    VERIFIED_EXEMPLAR = "VERIFIED_EXEMPLAR"  # 강사가 이 약점의 우수 사례로 확인
    MATCHES_WEAKNESS = "MATCHES_WEAKNESS"  # 학생의 반복 약점과 일치
    SAME_PRACTICAL_TYPE = "SAME_PRACTICAL_TYPE"
    SAME_WORK_CATEGORY = "SAME_WORK_CATEGORY"


class PostStatus(StrEnum):
    ACTIVE = "ACTIVE"
    HIDDEN = "HIDDEN"  # 관리자·자동 숨김 (작성자에게만 보임)
    DELETED = "DELETED"  # 작성자 삭제 또는 공유 철회


class CommentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    HIDDEN = "HIDDEN"
    DELETED = "DELETED"


class ReportTarget(StrEnum):
    POST = "POST"
    COMMENT = "COMMENT"


class ReportReason(StrEnum):
    SPAM = "SPAM"
    ABUSE = "ABUSE"  # 욕설·괴롭힘
    INAPPROPRIATE = "INAPPROPRIATE"
    COPYRIGHT = "COPYRIGHT"  # 타인 작품 도용
    PRIVACY = "PRIVACY"  # 개인정보 노출
    OTHER = "OTHER"


class CommunityReportStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"  # 조치함 (숨김 등)
    DISMISSED = "DISMISSED"  # 문제 없음


class ModerationAction(StrEnum):
    HIDE_POST = "HIDE_POST"
    UNHIDE_POST = "UNHIDE_POST"
    HIDE_COMMENT = "HIDE_COMMENT"
    UNHIDE_COMMENT = "UNHIDE_COMMENT"
    AUTO_HIDE_POST = "AUTO_HIDE_POST"  # 신고 누적 자동 숨김
    AUTO_HIDE_COMMENT = "AUTO_HIDE_COMMENT"
    RESOLVE_REPORT = "RESOLVE_REPORT"
    DISMISS_REPORT = "DISMISS_REPORT"


# --------------------------------------------------------------------------- v0.9 V2 1~2단계


class StudentGrade(StrEnum):
    """학년 (profiles.grade, 선택). 나이·학교명은 저장하지 않는다."""

    MIDDLE_SCHOOL = "MIDDLE_SCHOOL"  # 중학생
    HIGH_1 = "HIGH_1"
    HIGH_2 = "HIGH_2"
    HIGH_3 = "HIGH_3"
    GRADUATE = "GRADUATE"  # 졸업생 (N수)
    OTHER = "OTHER"


GRADE_LABELS: dict[StudentGrade, str] = {
    StudentGrade.MIDDLE_SCHOOL: "중학생",
    StudentGrade.HIGH_1: "고1",
    StudentGrade.HIGH_2: "고2",
    StudentGrade.HIGH_3: "고3",
    StudentGrade.GRADUATE: "졸업생(N수)",
    StudentGrade.OTHER: "기타",
}


class TimeSource(StrEnum):
    """artworks.actual_minutes 를 누가 기록했나."""

    MANUAL = "MANUAL"  # 학생이 직접 입력
    TIMER = "TIMER"  # 타이머 종료 기록에서 계산


class TimerEventType(StrEnum):
    """작품 타이머 이벤트 (artwork_timer_events, append-only)."""

    START = "START"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    STOP = "STOP"  # 종료 → actual_minutes 기록
    RESET = "RESET"  # 기록 버림 (다시 시작 가능)


class TimerState(StrEnum):
    IDLE = "IDLE"  # 시작 전 또는 RESET 후
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class FeedbackSource(StrEnum):
    """첨삭 출처. 성장 분석의 신뢰도 구분 기준 (INSTRUCTOR만 반복 약점 통계에 집계)."""

    INSTRUCTOR = "INSTRUCTOR"  # 강사의 첨삭 (녹음, 또는 학생이 받아 적은 텍스트)
    SELF_NOTE = "SELF_NOTE"  # 학생 본인의 학습 메모
    PEER = "PEER"  # 다른 학생의 의견 (커뮤니티 피드백 채택 포함)


FEEDBACK_SOURCE_LABELS: dict[FeedbackSource, str] = {
    FeedbackSource.INSTRUCTOR: "강사 첨삭",
    FeedbackSource.SELF_NOTE: "자기 메모",
    FeedbackSource.PEER: "다른 학생 의견",
}


class SpeakerConsentStatus(StrEnum):
    """녹음에 목소리가 담긴 다른 사람(강사)에 대한 고지·동의 상태 (학생 자기 신고값).

    학생의 기록일 뿐 강사의 동의를 법적으로 대신하지 않는다 (API 응답에도 그렇게 표시).
    """

    NOT_RECORDED = "NOT_RECORDED"  # v0.9 이전 녹음
    NOTICE_GIVEN = "NOTICE_GIVEN"  # 녹음 사실을 알림
    CONSENT_REPORTED = "CONSENT_REPORTED"  # 강사가 동의했다고 학생이 기록


class CommentType(StrEnum):
    GENERAL = "GENERAL"  # 일반 의견
    FEEDBACK = "FEEDBACK"  # 작품 피드백 (항목 지정 가능, 작성자가 채택하면 PEER 첨삭으로 기록)


class NotificationType(StrEnum):
    REPORT_READY = "REPORT_READY"  # 새 성장 리포트
    TASK_RECOMMENDED = "TASK_RECOMMENDED"  # 새 맞춤 과제 (개인 추천·학원 배포)
    TASK_REMINDER = "TASK_REMINDER"  # 채택 후 미완료 과제 안내
    GOAL_CHECK = "GOAL_CHECK"  # 학습 목표 확인 안내
