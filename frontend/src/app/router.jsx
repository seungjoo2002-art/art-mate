import { createBrowserRouter, Navigate } from 'react-router-dom'
import AppLayout from '../components/layout/AppLayout'
import NotFoundPage from '../pages/NotFoundPage'
import UiPreviewPage from '../pages/UiPreviewPage'
import ArchivePage from '../pages/student/ArchivePage'
import CommunityPage from '../pages/student/CommunityPage'
import HomePage from '../pages/student/HomePage'
import MyPage from '../pages/student/MyPage'
import PracticePage from '../pages/student/PracticePage'

// TODO(v0.2): 랜딩·유형 선택·회원가입 라우트 추가, 탭 화면을 로그인 보호 라우트로 감싸기
export const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/home" replace /> },
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
  ...(import.meta.env.DEV ? [{ path: '/dev/ui', element: <UiPreviewPage /> }] : []),
  { path: '*', element: <NotFoundPage /> },
])
