import { Navigate, Outlet, useLocation } from 'react-router-dom'
import FullScreenStatus from '../components/layout/FullScreenStatus'
import { Button } from '../components/ui'
import AuthStatusScreen from './AuthStatusScreen'
import { useAuth } from './providers/AuthContext'
import { rememberReturnPath } from './returnPath'

/** 로그인 + 프로필이 있어야 들어갈 수 있는 화면. 학생 전용 서비스 */
export default function ProtectedRoute() {
  const { status, profile, signOut, signedOutBy } = useAuth()
  const { pathname, search } = useLocation()

  if (status === 'signedOut') {
    // 다시 로그인하면 보던 화면으로 돌아오게 (이전에는 항상 홈으로 이동)
    if (signedOutBy !== 'user') rememberReturnPath(pathname + search)
    return <Navigate to="/" replace />
  }
  if (status === 'needsProfile') return <Navigate to="/onboarding" replace />
  if (status !== 'ready') return <AuthStatusScreen />

  // 예전에 강사로 가입한 계정
  if (profile.user_type !== 'STUDENT') {
    return (
      <FullScreenStatus
        title="학생 계정으로 이용해 주세요"
        description="ART MATE는 학생 계정으로만 이용할 수 있어요."
      >
        <Button variant="soft" onClick={signOut}>
          로그아웃
        </Button>
      </FullScreenStatus>
    )
  }
  // 학습 정보(실기 유형)를 아직 안 정했으면 먼저 설정 (v0.9 F-1)
  if (!profile.practical_type && pathname !== '/setup') return <Navigate to="/setup" replace />
  return <Outlet />
}
