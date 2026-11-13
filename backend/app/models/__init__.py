"""SQLAlchemy ORM 모델.

새 모델을 추가하면 반드시 이 파일에서 import 하세요. Alembic autogenerate는
`app.models`를 import 한 뒤 `Base.metadata`를 비교하므로, 여기 없는 모델은 감지되지 않습니다.
설계는 docs/database-design.md 참고.
"""

from app.db.base import Base
from app.models.academy import Academy
from app.models.academy_class import (
    AcademyClass,
    ClassMembership,
    ClassSchedule,
    ScheduleException,
)
from app.models.ai_feedback import (
    AiProcessingConsent,
    AiProcessingJob,
    FeedbackCategory,
    FeedbackItem,
    FeedbackNote,
    FeedbackReviewHistory,
    FeedbackSummary,
    FeedbackTranscript,
)
from app.models.artwork import Artwork, ArtworkExamStage, ArtworkPhoto, ArtworkTimerEvent
from app.models.attendance import AttendanceAuditLog, AttendanceRecord
from app.models.community import (
    ArtworkSharingConsent,
    CommunityBookmark,
    CommunityComment,
    CommunityLike,
    CommunityModerationLog,
    CommunityPost,
    CommunityReport,
    ReferenceArtworkReview,
    ReferenceRecommendation,
    SharedArtworkImage,
)
from app.models.dataset import DatasetConsent, FeedbackImageRef, FeedbackLabel
from app.models.exam import (
    ExamParticipant,
    ExamSession,
    ExamSessionStage,
    ExamStageTarget,
    ExamTemplate,
)
from app.models.growth import (
    GrowthReport,
    PracticeRecommendation,
    PracticeRecommendationArtwork,
    PracticeRecommendationHistory,
)
from app.models.help import HelpQueueEvent, HelpRequest
from app.models.membership import AcademyJoinRequest, AcademyMembership
from app.models.notification import Notification, NotificationPreference
from app.models.personal_todo import PersonalTodo
from app.models.profile import Profile, TargetUniversity
from app.models.recording import FeedbackRecording, RecordingConsent
from app.models.task import LessonTopic, Task, TaskAssignment

__all__ = [
    "Academy",
    "AcademyClass",
    "AcademyJoinRequest",
    "AcademyMembership",
    "AiProcessingConsent",
    "AiProcessingJob",
    "Artwork",
    "ArtworkExamStage",
    "ArtworkPhoto",
    "ArtworkSharingConsent",
    "ArtworkTimerEvent",
    "AttendanceAuditLog",
    "AttendanceRecord",
    "Base",
    "ClassMembership",
    "ClassSchedule",
    "CommunityBookmark",
    "CommunityComment",
    "CommunityLike",
    "CommunityModerationLog",
    "CommunityPost",
    "CommunityReport",
    "DatasetConsent",
    "ExamParticipant",
    "ExamSession",
    "ExamSessionStage",
    "ExamStageTarget",
    "ExamTemplate",
    "FeedbackCategory",
    "FeedbackImageRef",
    "FeedbackItem",
    "FeedbackLabel",
    "FeedbackNote",
    "FeedbackRecording",
    "FeedbackReviewHistory",
    "FeedbackSummary",
    "FeedbackTranscript",
    "GrowthReport",
    "HelpQueueEvent",
    "HelpRequest",
    "LessonTopic",
    "Notification",
    "NotificationPreference",
    "PersonalTodo",
    "PracticeRecommendation",
    "PracticeRecommendationArtwork",
    "PracticeRecommendationHistory",
    "Profile",
    "RecordingConsent",
    "ReferenceArtworkReview",
    "ReferenceRecommendation",
    "ScheduleException",
    "SharedArtworkImage",
    "TargetUniversity",
    "Task",
    "TaskAssignment",
]
