import { Navigate, Outlet, useLocation } from 'react-router-dom'
import AuthStatusScreen from './AuthStatusScreen'
import { useAuth } from './providers/AuthContext'
import { rememberReturnPath } from './returnPath'
import { homePathFor, USER_TYPES } from './roles'

/**
 * 로그인 + 프로필이 있어야 들어갈 수 있는 화면.
 * area: 이 영역을 쓰는 사용자 유형 (v1.0: STUDENT | INSTRUCTOR | ADMIN). 다른 유형은 자기 첫 화면으로
 * 최종 권한 판단은 서버가 한다 (학원 소속·역할).
 */
export default function ProtectedRoute({ area = USER_TYPES.STUDENT }) {
  const { status, profile, signedOutBy } = useAuth()
  const { pathname, search } = useLocation()

  if (status === 'signedOut') {
    // 다시 로그인하면 보던 화면으로 돌아오게 (이전에는 항상 홈으로 이동)
    if (signedOutBy !== 'user') rememberReturnPath(pathname + search)
    return <Navigate to="/" replace />
  }
  if (status === 'needsProfile') return <Navigate to="/onboarding" replace />
  if (status !== 'ready') return <AuthStatusScreen />

  if (profile.user_type !== area) return <Navigate to={homePathFor(profile)} replace />
  // 학생: 학습 정보(실기 유형)를 아직 안 정했으면 먼저 설정 (v0.9 F-1)
  if (area === USER_TYPES.STUDENT && !profile.practical_type && pathname !== '/setup') {
    return <Navigate to="/setup" replace />
  }
  return <Outlet />
}
