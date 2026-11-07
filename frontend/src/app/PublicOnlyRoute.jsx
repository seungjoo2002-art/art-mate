import { Navigate, Outlet } from 'react-router-dom'
import AuthStatusScreen from './AuthStatusScreen'
import { useAuth } from './providers/AuthContext'

/** 랜딩·로그인·회원가입: 이미 로그인한 사용자는 홈(또는 온보딩)으로 보냄 */
export default function PublicOnlyRoute() {
  const { status } = useAuth()

  if (status === 'signedOut') return <Outlet />
  if (status === 'ready') return <Navigate to="/home" replace />
  if (status === 'needsProfile') return <Navigate to="/onboarding" replace />
  return <AuthStatusScreen />
}
