import { createBrowserRouter, Navigate } from 'react-router-dom'
import AppLayout from '../components/layout/AppLayout'
import SubLayout from '../components/layout/SubLayout'
import ArtworkCreatePage from '../features/artworks/pages/ArtworkCreatePage'
import ArtworkDetailPage from '../features/artworks/pages/ArtworkDetailPage'
import ArtworkEditPage from '../features/artworks/pages/ArtworkEditPage'
import ArtworkFeedbackPage from '../features/artworks/pages/ArtworkFeedbackPage'
import AiRevisionLink from '../features/artworks/aiRevisions/AiRevisionLink'
import AiRevisionRedirect from '../features/artworks/aiRevisions/AiRevisionRedirect'
import AiRevisionsPage from '../features/artworks/aiRevisions/AiRevisionsPage'
import RevisionPanel from '../features/artworks/aiRevisions/RevisionPanel'
import PostDetailPage from '../features/community/pages/PostDetailPage'
import PostEditPage from '../features/community/pages/PostEditPage'
import PostWritePage from '../features/community/pages/PostWritePage'
import FeedbackList from '../features/feedback/components/FeedbackList'
import FeedbackTimeline from '../features/feedback/components/FeedbackTimeline'
import AiConsentPage from '../features/feedback/pages/AiConsentPage'
import GrowthReportPage from '../features/growth/pages/GrowthReportPage'
import RecommendationPage from '../features/growth/pages/RecommendationPage'
import RecommendationsPage from '../features/growth/pages/RecommendationsPage'
import FeedbackRecordPage from '../features/feedback/pages/FeedbackRecordPage'
import FeedbackReviewPage from '../features/feedback/pages/FeedbackReviewPage'
import RecordingProcessingPage from '../features/feedback/pages/RecordingProcessingPage'
import GuardianConsentPage from '../features/feedback/pages/GuardianConsentPage'
import NoteFormPage from '../features/feedback/pages/NoteFormPage'
import SttBenchPage from '../features/feedback/stt/SttBenchPage'
import TranscriptPage from '../features/feedback/pages/TranscriptPage'
import AuthCallbackPage from '../features/auth/pages/AuthCallbackPage'
import CheckEmailPage from '../features/auth/pages/CheckEmailPage'
import LandingPage from '../features/auth/pages/LandingPage'
import LoginPage from '../features/auth/pages/LoginPage'
import OnboardingPage from '../features/auth/pages/OnboardingPage'
import ProfileEditPage from '../features/auth/pages/ProfileEditPage'
import SetupPage from '../features/auth/pages/SetupPage'
import SignupPage from '../features/auth/pages/SignupPage'
import NotificationsPage from '../features/notifications/pages/NotificationsPage'
import NotFoundPage from '../pages/NotFoundPage'
import ExamProgressPage from '../pages/exam/ExamProgressPage'
import ExamResultPage from '../pages/exam/ExamResultPage'
import UiPreviewPage from '../pages/UiPreviewPage'
import ArchivePage from '../pages/student/ArchivePage'
import CommunityPage from '../pages/student/CommunityPage'
import HomePage from '../pages/student/HomePage'
import MyPage from '../pages/student/MyPage'
import MySettingsPage from '../pages/student/MySettingsPage'
import PracticePage from '../pages/student/PracticePage'
import ProtectedRoute from './ProtectedRoute'
import PublicOnlyRoute from './PublicOnlyRoute'

// v1.3 AI 수정본: 단계 '피드백 보기' 아래 버튼, 사진 피드백 아래 '피드백 반영 수정하기'
const renderStageRevisions = ({ artworkId, stageId, title, photoId }) => (
  <AiRevisionLink artworkId={artworkId} stageId={stageId} stageLabel={title} photoId={photoId} />
)
const renderPhotoRevision = (props) => <RevisionPanel key={props.photo.id} {...props} />
const renderArtworkTimeline = (props) => (
  <FeedbackTimeline {...props} renderStageExtras={renderStageRevisions} />
)
const renderArtworkFeedback = (props) => (
  <FeedbackList {...props} renderPhotoExtras={renderPhotoRevision} />
)

export const router = createBrowserRouter([
  // 로그인 전
  {
    element: <PublicOnlyRoute />,
    children: [
      { path: '/', element: <LandingPage /> },
      { path: '/login', element: <LoginPage /> },
      { path: '/signup', element: <SignupPage /> },
      { path: '/signup/check-email', element: <CheckEmailPage /> },
    ],
  },
  { path: '/auth/callback', element: <AuthCallbackPage /> },
  // 보호자(법정대리인) AI 전송 동의 확인 — 로그인 없이 학생이 보낸 링크로 (v0.9.6)
  { path: '/guardian-consent', element: <GuardianConsentPage /> },
  // 기기 음성 인식 성능 측정 (로그인 불필요, 서버로 아무것도 보내지 않음)
  { path: '/tools/stt-bench', element: <SttBenchPage /> },
  { path: '/onboarding', element: <OnboardingPage /> },

  // 로그인 + 프로필 필요
  {
    element: <ProtectedRoute />,
    children: [
      { path: '/setup', element: <SetupPage /> },
      {
        element: <AppLayout />,
        children: [
          { path: '/home', element: <HomePage /> },
          { path: '/practice', element: <PracticePage /> },
          { path: '/archive', element: <ArchivePage /> },
          { path: '/community', element: <CommunityPage /> },
          { path: '/my', element: <MyPage /> },
        ],
      },
      {
        element: <SubLayout />,
        children: [
          { path: '/my/edit', element: <ProfileEditPage /> },
          { path: '/my/settings', element: <MySettingsPage /> },
          { path: '/notifications', element: <NotificationsPage /> },
          { path: '/community/write', element: <PostWritePage /> },
          { path: '/community/posts/:postId', element: <PostDetailPage /> },
          { path: '/community/posts/:postId/edit', element: <PostEditPage /> },
          { path: '/artworks/new', element: <ArtworkCreatePage /> },
          { path: '/artworks/:artworkId/edit', element: <ArtworkEditPage /> },
          {
            path: '/artworks/:artworkId',
            element: <ArtworkDetailPage renderTimeline={renderArtworkTimeline} />,
          },
          {
            // 단계별 피드백 (?stage=단계 id&photo=사진 id) · 작품 전체 피드백 (stage 없음)
            path: '/artworks/:artworkId/feedback',
            element: <ArtworkFeedbackPage renderFeedback={renderArtworkFeedback} />,
          },
          {
            // v1.3 단계별 AI 수정본 (?photo=사진 id&revision=수정본 id)
            path: '/artworks/:artworkId/stages/:stageId/ai-revisions',
            element: <AiRevisionsPage />,
          },
          { path: '/ai-revisions/:revisionId', element: <AiRevisionRedirect /> },
          { path: '/artworks/:artworkId/recordings/new', element: <FeedbackRecordPage /> },
          { path: '/artworks/:artworkId/exam', element: <ExamProgressPage /> },
          { path: '/artworks/:artworkId/exam/result', element: <ExamResultPage /> },
          { path: '/feedbacks/:feedbackId', element: <FeedbackReviewPage /> },
          {
            path: '/artworks/:artworkId/recordings/:recordingId/transcript',
            element: <TranscriptPage />,
          },
          {
            // 글로 변환하기·AI로 정리하기 진행 (필요한 서버 요청을 자동으로, 끝나면 결과 화면으로)
            path: '/artworks/:artworkId/recordings/:recordingId/processing',
            element: <RecordingProcessingPage />,
          },
          { path: '/artworks/:artworkId/notes/new', element: <NoteFormPage /> },
          { path: '/feedback-notes/:noteId/edit', element: <NoteFormPage /> },
          { path: '/ai-consent', element: <AiConsentPage /> },
          // 기간별 성장 리포트 목록은 분석 리포트 맨 아래 '기간별로 보기'로 합침
          { path: '/growth/reports', element: <Navigate to="/archive?tab=report" replace /> },
          { path: '/growth/reports/:reportId', element: <GrowthReportPage /> },
          { path: '/growth/recommendations', element: <RecommendationsPage /> },
          { path: '/growth/recommendations/:recommendationId', element: <RecommendationPage /> },
        ],
      },
    ],
  },

  ...(import.meta.env.DEV ? [{ path: '/dev/ui', element: <UiPreviewPage /> }] : []),
  { path: '/index.html', element: <Navigate to="/" replace /> },
  { path: '/signup/role', element: <Navigate to="/signup" replace /> }, // 예전 유형 선택 주소
  { path: '*', element: <NotFoundPage /> },
])
