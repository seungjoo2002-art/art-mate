import { createBrowserRouter, Navigate } from 'react-router-dom'
import AppLayout from '../components/layout/AppLayout'
import SubLayout from '../components/layout/SubLayout'
import ArtworkCreatePage from '../features/artworks/pages/ArtworkCreatePage'
import ArtworkDetailPage from '../features/artworks/pages/ArtworkDetailPage'
import ArtworkEditPage from '../features/artworks/pages/ArtworkEditPage'
import PostDetailPage from '../features/community/pages/PostDetailPage'
import PostEditPage from '../features/community/pages/PostEditPage'
import PostWritePage from '../features/community/pages/PostWritePage'
import FeedbackTimeline from '../features/feedback/components/FeedbackTimeline'
import AiConsentPage from '../features/feedback/pages/AiConsentPage'
import GrowthReportPage from '../features/growth/pages/GrowthReportPage'
import GrowthReportsPage from '../features/growth/pages/GrowthReportsPage'
import RecommendationPage from '../features/growth/pages/RecommendationPage'
import RecommendationsPage from '../features/growth/pages/RecommendationsPage'
import FeedbackRecordPage from '../features/feedback/pages/FeedbackRecordPage'
import FeedbackReviewPage from '../features/feedback/pages/FeedbackReviewPage'
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
import PracticePage from '../pages/student/PracticePage'
import AdminAcademiesPage from '../features/admin/AdminAcademiesPage'
import StudentAcademiesPage from '../features/academy/StudentAcademiesPage'
import AcademyScope from '../features/instructor/AcademyScope'
import InstructorLayout from '../features/instructor/InstructorLayout'
import AcademyDashboardPage from '../features/instructor/pages/AcademyDashboardPage'
import AcademyManagePage from '../features/instructor/pages/AcademyManagePage'
import ClassPage from '../features/instructor/pages/ClassPage'
import InstructorHomePage from '../features/instructor/pages/InstructorHomePage'
import ReviewQueuePage from '../features/instructor/pages/ReviewQueuePage'
import StaffArtworkPage from '../features/instructor/pages/StaffArtworkPage'
import StaffArtworksPage from '../features/instructor/pages/StaffArtworksPage'
import StaffFeedbackPage from '../features/instructor/pages/StaffFeedbackPage'
import ProtectedRoute from './ProtectedRoute'
import PublicOnlyRoute from './PublicOnlyRoute'

const renderArtworkTimeline = (props) => <FeedbackTimeline {...props} />

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
          { path: '/my/academies', element: <StudentAcademiesPage /> },
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
          { path: '/artworks/:artworkId/recordings/new', element: <FeedbackRecordPage /> },
          { path: '/artworks/:artworkId/exam', element: <ExamProgressPage /> },
          { path: '/artworks/:artworkId/exam/result', element: <ExamResultPage /> },
          { path: '/feedbacks/:feedbackId', element: <FeedbackReviewPage /> },
          {
            path: '/artworks/:artworkId/recordings/:recordingId/transcript',
            element: <TranscriptPage />,
          },
          { path: '/artworks/:artworkId/notes/new', element: <NoteFormPage /> },
          { path: '/feedback-notes/:noteId/edit', element: <NoteFormPage /> },
          { path: '/ai-consent', element: <AiConsentPage /> },
          { path: '/growth/reports', element: <GrowthReportsPage /> },
          { path: '/growth/reports/:reportId', element: <GrowthReportPage /> },
          { path: '/growth/recommendations', element: <RecommendationsPage /> },
          { path: '/growth/recommendations/:recommendationId', element: <RecommendationPage /> },
        ],
      },
    ],
  },

  // v1.0 강사·원장 웹 (데스크톱 우선). 학원 데이터 권한은 서버가 소속·역할로 다시 검사
  {
    element: <ProtectedRoute area="INSTRUCTOR" />,
    children: [
      {
        path: '/instructor',
        element: <InstructorLayout />,
        children: [
          { index: true, element: <InstructorHomePage /> },
          { path: 'start', element: <InstructorHomePage /> },
          {
            path: 'academies/:academyId',
            element: <AcademyScope />,
            children: [
              { index: true, element: <AcademyDashboardPage /> },
              { path: 'feedbacks', element: <ReviewQueuePage /> },
              { path: 'feedbacks/:feedbackId', element: <StaffFeedbackPage /> },
              { path: 'artworks', element: <StaffArtworksPage /> },
              { path: 'artworks/:artworkId', element: <StaffArtworkPage /> },
              { path: 'manage', element: <AcademyManagePage /> },
              { path: 'classes/:classId', element: <ClassPage /> },
            ],
          },
        ],
      },
    ],
  },
  // v1.0 시스템 관리자: 학원 등록 심사
  {
    element: <ProtectedRoute area="ADMIN" />,
    children: [{ path: '/admin/academies', element: <AdminAcademiesPage /> }],
  },

  ...(import.meta.env.DEV ? [{ path: '/dev/ui', element: <UiPreviewPage /> }] : []),
  { path: '/index.html', element: <Navigate to="/" replace /> },
  { path: '/signup/role', element: <Navigate to="/signup" replace /> }, // 예전 유형 선택 주소
  { path: '*', element: <NotFoundPage /> },
])
