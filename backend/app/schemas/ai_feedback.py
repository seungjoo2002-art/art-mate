"""AI 첨삭 기록 API 요청·응답 (v0.6)."""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.models.enums import (
    AiAgeBand,
    AiConsentPurpose,
    AiJobStatus,
    AiJobType,
    AiProvider,
    ConsentGrantor,
    FeedbackItemKind,
    FeedbackItemOrigin,
    FeedbackSource,
    FeedbackStatus,
    GuardianRelationship,
    ReviewAction,
    ReviewMode,
    TranscriptionStatus,
    WeaknessCategory,
)
from app.schemas.fields import InputModel
from app.schemas.students import StudentRef

# ----------------------------------------------------------------------------- consent


class AiConsentCreate(InputModel):
    purpose: AiConsentPurpose = Field(
        default=AiConsentPurpose.FEEDBACK_SUMMARY,
        description="FEEDBACK_SUMMARY(첨삭 요약, v0.6) / "
        "GROWTH_COACHING(성장 분석·맞춤 과제, v0.7)",
    )
    policy_version: str = Field(
        min_length=1,
        max_length=20,
        description="GET /ai-processing-consents/me 의 required_version",
    )
    agreed: Literal[True] = Field(description="전사문의 외부 AI 전송에 동의함 (true만 허용)")
    birth_year_month: str | None = Field(
        default=None,
        pattern=r"^(19|20)\d{2}-(0[1-9]|1[0-2])$",
        description="(v0.9.6 필수) 생년월 YYYY-MM. 연령 구간 계산에만 쓰고 저장하지 않는다. "
        "만 18세 미만이면 보호자 확인 링크가 발급되고, 보호자가 확인해야 동의가 유효해진다",
        examples=["2009-03"],
    )
    granted_by: ConsentGrantor | None = Field(
        default=None,
        description="(v0.9.6부터 무시) 연령 구간으로 서버가 정한다: 성인 SELF, 미성년자 GUARDIAN",
    )


class AiConsentRead(BaseModel):
    id: uuid.UUID
    provider: AiProvider
    purpose: AiConsentPurpose
    policy_version: str
    granted_by: ConsentGrantor
    granted_at: dt.datetime
    revoked_at: dt.datetime | None
    age_band: AiAgeBand | None = Field(
        description="UNDER_14 / TEEN(만 14~17세) / ADULT (이전 동의는 null)"
    )
    guardian_relationship: GuardianRelationship | None
    guardian_confirmed_at: dt.datetime | None = Field(description="보호자가 확인한 시각")


class AiConsentStatus(BaseModel):
    provider: AiProvider = Field(description="지금 전사문을 받는 AI 제공자 (AI_PROVIDER)")
    purpose: AiConsentPurpose
    required_version: str
    is_valid: bool = Field(description="현재 버전에 유효한 동의가 있음 → AI 요약 요청 가능")
    reason: (
        Literal["NOT_CONSENTED", "TEEN_NOT_ENABLED", "UNDER_14_BLOCKED", "GUARDIAN_PENDING"] | None
    ) = Field(
        default=None,
        description="유효하지 않은 이유: NOT_CONSENTED 동의 없음·이전 버전·다른 제공자 / "
        "TEEN_NOT_ENABLED 만 14~17세 전송을 운영자가 아직 열지 않음 / UNDER_14_BLOCKED 만 14세 "
        "미만(법정대리인 확인·데이터 무보관 승인 전) / GUARDIAN_PENDING 보호자 확인 대기",
    )
    consent: AiConsentRead | None
    guardian_token: str | None = Field(
        default=None,
        description="보호자 확인 링크용 토큰 — 동의·링크 재발급 응답에서 한 번만 내려준다. "
        "링크: {프론트}/guardian-consent/{token}",
    )
    guardian_token_expires_at: dt.datetime | None = None


class GuardianConsentView(BaseModel):
    """보호자 확인 화면 (로그인 없이 링크로 연다). 학생 이름·작품·전사 내용은 보여 주지 않는다."""

    provider: AiProvider
    purpose: AiConsentPurpose
    policy_version: str
    age_band: AiAgeBand
    status: Literal["PENDING", "CONFIRMED"]
    expires_at: dt.datetime | None


class GuardianToken(InputModel):
    """보호자 확인 링크 토큰 (URL 조각 #에서 읽어 요청 본문으로만 보낸다)."""

    token: str = Field(min_length=20, max_length=100)


class GuardianConsentConfirm(GuardianToken):
    guardian_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
    ] = Field(description="보호자(법정대리인) 성명")
    relationship: GuardianRelationship
    agreed: Literal[True] = Field(description="자녀의 전사문을 외부 AI로 보내는 데 동의함")


# ----------------------------------------------------------------------------- jobs


class TranscriptionRequest(InputModel):
    auto_summarize: bool = Field(
        default=False,
        description="전사가 끝나면 AI 요약을 자동으로 요청 "
        "(그 시점에 학생의 AI 전송 동의가 있어야 함)",
    )
    defer_seconds: int = Field(
        default=0,
        ge=0,
        le=21600,
        description="(v0.9.3) 이 시간 뒤에 서버 처리 시작. "
        "기기(브라우저)에서 변환하는 동안 만들어 두는 백업 작업용: "
        "기기 전사가 저장되면 취소되고, 브라우저가 닫히면 서버가 이어서 처리한다. "
        "서버 상한(STT_MAX_DEFER_SECONDS)을 넘으면 상한으로 줄인다. "
        "0으로 다시 요청하면 대기 중인 백업 작업을 바로 처리하도록 앞당긴다.",
    )


class JobRead(BaseModel):
    """처리 작업 상태. 내부 Signed URL·오류 상세는 내보내지 않는다."""

    id: uuid.UUID
    job_type: AiJobType
    status: AiJobStatus
    attempts: int
    max_attempts: int
    next_attempt_at: dt.datetime | None = Field(description="QUEUED일 때 다음 실행 예정 시각")
    error_code: str | None = Field(description="마지막 실패 코드 (재시도 중이어도 남아 있음)")
    retryable: bool = Field(description="FAILED/CANCELLED → 재시도 API 사용 가능")
    created_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None


class TranscriptMeta(BaseModel):
    id: uuid.UUID
    language: str
    duration_ms: int | None
    segment_count: int
    engine: str
    model_name: str
    origin: Literal["SERVER", "BROWSER", "EDITED"] = Field(
        default="SERVER",
        description="v0.9.2: SERVER(서버·GitHub Actions faster-whisper) / BROWSER(학생 기기에서 "
        "전사) / EDITED(학생이 수정한 버전)",
    )
    created_at: dt.datetime


class TranscriptionStatusRead(BaseModel):
    recording_id: uuid.UUID
    transcription_status: TranscriptionStatus
    job: JobRead | None = Field(description="가장 최근 전사 작업")
    transcript: TranscriptMeta | None = Field(description="완료된 최신 전사 (원문은 /transcript)")


class Segment(BaseModel):
    index: int
    start_ms: int
    end_ms: int
    text: str


class TranscriptRead(TranscriptMeta):
    recording_id: uuid.UUID
    text: str
    segments: list[Segment]
    edited: bool = Field(default=False, description="사람이 수정한 버전 (v0.9)")
    edited_from_id: uuid.UUID | None = Field(default=None, description="수정 전 전사 (보존됨)")


SegmentText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]


class SegmentEdit(InputModel):
    index: int = Field(ge=0)
    text: SegmentText


class TranscriptEdit(InputModel):
    """STT 결과 수정 (v0.9). 구간 수·시각은 그대로, 문장만 고친다 (근거 연결 유지)."""

    base_transcript_id: uuid.UUID = Field(
        description="수정한 전사 id (지금 최신 전사여야 함, 아니면 409 FEEDBACK_VERSION_CONFLICT)"
    )
    segments: list[SegmentEdit] = Field(
        min_length=1, max_length=2000, description="바꾼 구간만 보내도 된다"
    )

    @model_validator(mode="after")
    def _unique(self) -> "TranscriptEdit":
        indexes = [s.index for s in self.segments]
        if len(indexes) != len(set(indexes)):
            raise ValueError("duplicate segment index")
        return self


class SummaryStatusRead(BaseModel):
    recording_id: uuid.UUID
    job: JobRead | None = Field(description="가장 최근 요약 작업")
    feedback_id: uuid.UUID | None = Field(description="현재 첨삭 (DRAFT/IN_REVIEW/APPROVED)")
    feedback_status: FeedbackStatus | None
    review_mode: ReviewMode | None = Field(
        description="INSTRUCTOR: 담당 강사가 확정, SELF: 학생 본인이 확정 (학원 미연결 작품)"
    )


# ----------------------------------------------------------------------------- feedback


class Evidence(BaseModel):
    """근거 원문 구간. 녹음 전사면 시각(재생 위치)이 있고, 텍스트 첨삭이면 시각이 없다."""

    index: int
    start_ms: int | None = None
    end_ms: int | None = None
    text: str | None = Field(default=None, description="근거 원문 문장 (v0.9)")


class FeedbackItemRead(BaseModel):
    id: uuid.UUID
    kind: FeedbackItemKind
    position: int
    content: str
    category: WeaknessCategory | None
    evidence: list[Evidence] = Field(description="근거 원문 구간 (녹음은 재생 위치 포함)")
    origin: FeedbackItemOrigin


class FeedbackRead(BaseModel):
    id: uuid.UUID
    recording_id: uuid.UUID | None = Field(description="녹음 첨삭이면 녹음 id")
    note_id: uuid.UUID | None = Field(default=None, description="텍스트 첨삭이면 원문 id (v0.9)")
    source: FeedbackSource = Field(
        default=FeedbackSource.INSTRUCTOR,
        description="INSTRUCTOR 강사 첨삭 / SELF_NOTE 자기 메모 / PEER 다른 학생 의견 (v0.9)",
    )
    artwork_id: uuid.UUID
    status: FeedbackStatus
    review_mode: ReviewMode
    version: int = Field(description="수정·승인 요청에 그대로 보낸다 (동시 수정 감지)")
    summary: str
    strengths: list[FeedbackItemRead]
    weaknesses: list[FeedbackItemRead]
    fixes: list[FeedbackItemRead]
    next_tips: list[FeedbackItemRead]
    categories: list[WeaknessCategory] = Field(description="약점 카테고리")
    approved_at: dt.datetime | None
    approved_by_name: str | None
    created_at: dt.datetime
    updated_at: dt.datetime


class ReviewerFeedbackRead(FeedbackRead):
    """검토자(담당 강사, 개인 작품의 학생 본인)용: AI 원본과 처리 정보 포함."""

    ai_draft: dict[str, Any] = Field(description="AI 응답 원본 (검증 통과본, 변경되지 않음)")
    model_name: str
    prompt_version: str
    dropped_item_count: int = Field(description="근거가 없어 저장하지 않은 AI 항목 수")
    rejected_reason: str | None
    artwork_title: str
    student: StudentRef | None = Field(description="강사 화면일 때 학생 정보")


class ReviewQueueItem(BaseModel):
    id: uuid.UUID
    recording_id: uuid.UUID | None
    note_id: uuid.UUID | None = None
    artwork_id: uuid.UUID
    artwork_title: str
    recording_title: str | None
    status: FeedbackStatus
    version: int
    summary: str
    categories: list[WeaknessCategory]
    student: StudentRef
    created_at: dt.datetime
    updated_at: dt.datetime


ContentText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]
SummaryText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)
]
ReasonText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class FeedbackItemInput(InputModel):
    id: uuid.UUID | None = Field(
        default=None, description="기존 항목 수정이면 id, 새 항목이면 생략"
    )
    kind: FeedbackItemKind
    content: ContentText
    category: WeaknessCategory | None = None
    evidence_segment_ids: list[int] | None = Field(
        default=None,
        max_length=20,
        description="근거 구간 번호. 생략하면 기존 항목의 근거 유지(새 항목은 빈 배열)",
    )


class FeedbackUpdate(InputModel):
    """첨삭 전체 교체 (보낸 목록이 최종 상태). 빠진 기존 항목은 삭제된다."""

    version: int = Field(ge=1, description="조회한 version (다르면 409 FEEDBACK_VERSION_CONFLICT)")
    summary: SummaryText
    items: list[FeedbackItemInput] = Field(max_length=60)
    categories: list[WeaknessCategory] = Field(max_length=10)
    note: ReasonText | None = Field(default=None, description="수정 메모 (이력에 기록)")

    @model_validator(mode="after")
    def _unique(self) -> "FeedbackUpdate":
        ids = [i.id for i in self.items if i.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate item id")
        if len(self.categories) != len(set(self.categories)):
            raise ValueError("duplicate category")
        return self


class FeedbackDecision(InputModel):
    version: int = Field(ge=1)
    note: ReasonText | None = None


class FeedbackReject(InputModel):
    version: int = Field(ge=1)
    reason: ReasonText


class ReviewHistoryRead(BaseModel):
    id: uuid.UUID
    action: ReviewAction
    from_status: FeedbackStatus | None
    to_status: FeedbackStatus
    version: int
    actor_name: str | None = Field(description="NULL = 시스템(AI 처리) 또는 탈퇴한 사용자")
    actor_mode: ReviewMode | None
    changes: dict[str, Any] | None = Field(description="변경 전후 (before/after)")
    note: str | None
    created_at: dt.datetime


# ----------------------------------------------------------------------------- v0.9 텍스트 첨삭

NoteBody = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]


class FeedbackNoteCreate(InputModel):
    source: FeedbackSource = Field(
        description="INSTRUCTOR(강사 첨삭을 받아 적음) / SELF_NOTE(자기 메모) / "
        "PEER(다른 학생 의견)"
    )
    body: NoteBody = Field(description="첨삭 원문 (5000자). 문장 단위로 나눠 근거 번호를 붙인다")
    feedback_date: dt.date | None = Field(default=None, description="첨삭 받은 날 (기본 오늘)")
    request_summary: bool = Field(
        default=False,
        description="저장 후 AI 요약·분류를 바로 요청 (AI 전송 동의 필요, 없으면 저장만 하고 "
        "summary_job=null)",
    )


class FeedbackNoteUpdate(InputModel):
    version: int = Field(ge=1, description="조회한 version (다르면 409 FEEDBACK_VERSION_CONFLICT)")
    source: FeedbackSource | None = None
    body: NoteBody | None = None
    feedback_date: dt.date | None = None

    @model_validator(mode="after")
    def _some(self) -> "FeedbackNoteUpdate":
        if not ({"source", "body", "feedback_date"} & self.model_fields_set):
            raise ValueError("Nothing to update")
        for name in ("source", "body", "feedback_date"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"'{name}' cannot be null")
        return self


class NoteSegment(BaseModel):
    index: int
    text: str


class FeedbackNoteRead(BaseModel):
    id: uuid.UUID
    artwork_id: uuid.UUID
    source: FeedbackSource
    body: str = Field(description="원문 (AI 결과와 별도로 보존)")
    segments: list[NoteSegment] = Field(description="문장 단위 구간 (AI 근거 번호)")
    feedback_date: dt.date
    version: int
    community_comment_id: uuid.UUID | None = Field(description="커뮤니티 피드백 채택으로 만든 경우")
    feedback_id: uuid.UUID | None = Field(description="현재 AI 요약 (DRAFT/IN_REVIEW/APPROVED)")
    feedback_status: FeedbackStatus | None
    review_mode: ReviewMode = Field(
        description="SELF: 학생 본인이 확정 / INSTRUCTOR: 학원 작품의 강사 첨삭은 담당 강사가 확정"
    )
    summary_job: JobRead | None = Field(description="가장 최근 요약 작업")
    created_at: dt.datetime
    updated_at: dt.datetime


class NoteSummaryRequest(InputModel):
    regenerate: bool = Field(default=False, description="초안이 있어도 다시 만든다")


# ----------------------------------------------------------------------------- v0.9.2 브라우저 STT

BROWSER_MODEL = r"^[A-Za-z0-9._/-]{1,100}$"


class BrowserSegment(InputModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: SegmentText


class BrowserTranscriptCreate(InputModel):
    """학생 기기(브라우저)에서 Whisper로 전사한 결과. 음성은 기기 밖으로 나가지 않는다."""

    device: Literal["webgpu", "wasm"] = Field(description="실행 장치")
    model_name: str = Field(
        pattern=BROWSER_MODEL, examples=["onnx-community/whisper-base"], description="사용한 모델"
    )
    language: Literal["ko"] = "ko"
    segments: list[BrowserSegment] = Field(min_length=1, max_length=2000)
    processing_ms: int | None = Field(
        default=None, ge=0, le=3_600_000, description="모델 로드를 뺀 실제 전사 시간 (통계용)"
    )
    auto_summarize: bool = Field(
        default=False,
        description="저장 후 AI 요약 요청 (AI 전송 동의·설정이 없으면 요약 없이 전사만 저장)",
    )

    @model_validator(mode="after")
    def _ordered(self) -> "BrowserTranscriptCreate":
        previous = -1
        for seg in self.segments:
            if seg.end_ms < seg.start_ms:
                raise ValueError("end_ms must be >= start_ms")
            if seg.start_ms < previous:
                raise ValueError("segments must be ordered by start_ms")
            previous = seg.start_ms
        return self


class BrowserTranscriptResult(BaseModel):
    transcript: TranscriptRead
    summary_job: JobRead | None = Field(description="auto_summarize로 만든 요약 작업 (없으면 null)")
    summary_status: Literal[
        "QUEUED", "NOT_REQUESTED", "AI_DISABLED", "CONSENT_REQUIRED", "LIMIT_REACHED"
    ] = Field(
        default="NOT_REQUESTED",
        description="요약 요청 결과: QUEUED 대기열 등록 / AI_DISABLED AI 정리 미설정 / "
        "CONSENT_REQUIRED AI 전송 동의 없음 / LIMIT_REACHED 오늘 한도 초과",
    )
