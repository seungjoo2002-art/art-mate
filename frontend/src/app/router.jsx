import { createBrowserRouter, Navigate } from 'react-router-dom'
import AppLayout from '../components/layout/AppLayout'
import AuthCallbackPage from '../features/auth/pages/AuthCallbackPage'
import CheckEmailPage from '../features/auth/pages/CheckEmailPage'
import LandingPage from '../features/auth/pages/LandingPage'
import LoginPage from '../features/auth/pages/LoginPage'
import OnboardingPage from '../features/auth/pages/OnboardingPage'
import RoleSelectPage from '../features/auth/pages/RoleSelectPage'
import SignupPage from '../features/auth/pages/SignupPage'
import NotFoundPage from '../pages/NotFoundPage'
import UiPreviewPage from '../pages/UiPreviewPage'
import ArchivePage from '../pages/student/ArchivePage'
import CommunityPage from '../pages/student/CommunityPage'
import MyPage from '../pages/student/MyPage'
import PracticePage from '../pages/student/PracticePage'
import ProtectedRoute from './ProtectedRoute'
import PublicOnlyRoute from './PublicOnlyRoute'
import RoleHome from './RoleHome'

export const router = createBrowserRouter([
  // 로그인 전
  {
    element: <PublicOnlyRoute />,
    children: [
      { path: '/', element: <LandingPage /> },
      { path: '/login', element: <LoginPage /> },
      { path: '/signup/role', element: <RoleSelectPage /> },
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
          { path: '/home', element: <RoleHome /> },
          { path: '/practice', element: <PracticePage /> },
          { path: '/archive', element: <ArchivePage /> },
          { path: '/community', element: <CommunityPage /> },
          { path: '/my', element: <MyPage /> },
        ],
      },
    ],
  },

  ...(import.meta.env.DEV ? [{ path: '/dev/ui', element: <UiPreviewPage /> }] : []),
  { path: '/index.html', element: <Navigate to="/" replace /> },
  { path: '*', element: <NotFoundPage /> },
])
