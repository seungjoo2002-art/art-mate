import { createContext, useContext } from 'react'

export const AuthContext = createContext(null)

/**
 * status:
 *  - 'loading'       세션·프로필 확인 중
 *  - 'signedOut'     로그인 안 함
 *  - 'needsProfile'  로그인했지만 프로필 없음 → 온보딩
 *  - 'ready'         로그인 + 프로필 있음
 *  - 'error'         프로필 조회 실패 (서버 장애, 비활성 계정 등)
 *  - 'misconfigured' frontend/.env.local 없음
 */
export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside <AuthProvider>')
  return value
}
