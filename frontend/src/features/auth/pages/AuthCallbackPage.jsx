import { Navigate } from 'react-router-dom'
import AuthStatusScreen from '../../../app/AuthStatusScreen'
import { useAuth } from '../../../app/providers/AuthContext'
import FullScreenStatus from '../../../components/layout/FullScreenStatus'
import { Button } from '../../../components/ui'

/** 인증 메일 링크로 돌아오는 곳. Supabase SDK가 URL의 토큰을 자동으로 세션으로 바꿈 */
export default function AuthCallbackPage() {
  const { status } = useAuth()

  if (status === 'ready') return <Navigate to="/home" replace />
  if (status === 'needsProfile') return <Navigate to="/onboarding" replace />
  if (status === 'signedOut') {
    return (
      <FullScreenStatus
        title="인증 링크가 만료됐어요"
        description="이미 사용했거나 시간이 지난 링크예요. 로그인해 주세요."
      >
        <Button onClick={() => window.location.replace('/login')}>로그인하기</Button>
      </FullScreenStatus>
    )
  }
  return <AuthStatusScreen />
}
