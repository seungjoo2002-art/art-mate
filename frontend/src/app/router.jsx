import { createBrowserRouter, Navigate } from 'react-router-dom'
import AppLayout from '../components/layout/AppLayout'
import SubLayout from '../components/layout/SubLayout'
import ArtworkCreatePage from '../features/artworks/pages/ArtworkCreatePage'
import ArtworkDetailPage from '../features/artworks/pages/ArtworkDetailPage'
import FeedbackTimeline from '../features/feedback/components/FeedbackTimeline'
import AiConsentPage from '../features/feedback/pages/AiConsentPage'
import FeedbackRecordPage from '../features/feedback/pages/FeedbackRecordPage'
import FeedbackReviewPage from '../features/feedback/pages/FeedbackReviewPage'
import AuthCallbackPage from '../features/auth/pages/AuthCallbackPage'
import CheckEmailPage from '../features/auth/pages/CheckEmailPage'
import LandingPage from '../features/auth/pages/LandingPage'
import LoginPage from '../features/auth/pages/LoginPage'
import OnboardingPage from '../features/auth/pages/OnboardingPage'
import SignupPage from '../features/auth/pages/SignupPage'
import NotFoundPage from '../pages/NotFoundPage'
import UiPreviewPage from '../pages/UiPreviewPage'
import ArchivePage from '../pages/student/ArchivePage'
import CommunityPage from '../pages/student/CommunityPage'
import HomePage from '../pages/student/HomePage'
import MyPage from '../pages/student/MyPage'
import PracticePage from '../pages/student/PracticePage'
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
  { path: '/onboarding', element: <OnboardingPage /> },

  // 로그인 + 프로필 필요
  {
    element: <ProtectedRoute />,
    children: [
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
          { path: '/artworks/new', element: <ArtworkCreatePage /> },
          {
            path: '/artworks/:artworkId',
            element: <ArtworkDetailPage renderTimeline={renderArtworkTimeline} />,
          },
          { path: '/artworks/:artworkId/recordings/new', element: <FeedbackRecordPage /> },
          { path: '/feedbacks/:feedbackId', element: <FeedbackReviewPage /> },
          { path: '/ai-consent', element: <AiConsentPage /> },
        ],
      },
    ],
  },

  ...(import.meta.env.DEV ? [{ path: '/dev/ui', element: <UiPreviewPage /> }] : []),
  { path: '/index.html', element: <Navigate to="/" replace /> },
  { path: '/signup/role', element: <Navigate to="/signup" replace /> }, // 예전 유형 선택 주소
  { path: '*', element: <NotFoundPage /> },
])
