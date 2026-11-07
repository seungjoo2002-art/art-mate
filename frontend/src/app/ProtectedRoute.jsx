import { Navigate, Outlet } from 'react-router-dom'
import AuthStatusScreen from './AuthStatusScreen'
import { useAuth } from './providers/AuthContext'

/** 로그인 + 프로필이 있어야 들어갈 수 있는 화면 */
export default function ProtectedRoute() {
  const { status } = useAuth()

  if (status === 'ready') return <Outlet />
  if (status === 'signedOut') return <Navigate to="/" replace />
  if (status === 'needsProfile') return <Navigate to="/onboarding" replace />
  return <AuthStatusScreen />
}
