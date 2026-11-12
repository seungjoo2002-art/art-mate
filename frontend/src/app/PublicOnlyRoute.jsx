import { useEffect } from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import AuthStatusScreen from './AuthStatusScreen'
import { useAuth } from './providers/AuthContext'
import { clearReturnPath, peekReturnPath } from './returnPath'

/** 랜딩·로그인·회원가입: 이미 로그인한 사용자는 홈(또는 온보딩)으로 보냄 */
export default function PublicOnlyRoute() {
  const { status } = useAuth()

  // 돌아갈 경로는 한 번만 쓴다 (렌더는 여러 번 될 수 있어 지우기는 effect에서)
  useEffect(() => {
    if (status === 'ready') clearReturnPath()
  }, [status])

  if (status === 'signedOut') return <Outlet />
  if (status === 'ready') return <Navigate to={peekReturnPath() ?? '/home'} replace />
  if (status === 'needsProfile') return <Navigate to="/onboarding" replace />
  return <AuthStatusScreen />
}
