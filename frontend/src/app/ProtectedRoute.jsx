import { Navigate, Outlet } from 'react-router-dom'
import FullScreenStatus from '../components/layout/FullScreenStatus'
import { Button } from '../components/ui'
import AuthStatusScreen from './AuthStatusScreen'
import { useAuth } from './providers/AuthContext'

/** 로그인 + 프로필이 있어야 들어갈 수 있는 화면. 학생 전용 서비스 */
export default function ProtectedRoute() {
  const { status, profile, signOut } = useAuth()

  if (status === 'signedOut') return <Navigate to="/" replace />
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
  return <Outlet />
}
