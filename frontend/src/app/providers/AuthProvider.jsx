import { useCallback, useEffect, useMemo, useState } from 'react'
import { createMe, getMe } from '../../features/auth/api'
import { clearPendingProfile, readPendingProfile } from '../../features/auth/pendingProfile'
import { supabase } from '../../lib/supabase'
import { AuthContext } from './AuthContext'

/** 프로필 조회. 없으면 회원가입 때 저장해 둔 입력값으로 생성 */
async function fetchOrCreateProfile(email) {
  try {
    return await getMe()
  } catch (error) {
    const pending = readPendingProfile(email)
    if (error.code !== 'PROFILE_NOT_FOUND' || !pending) throw error
    const profile = await createMe(pending)
    clearPendingProfile()
    return profile
  }
}

export default function AuthProvider({ children }) {
  const [session, setSession] = useState(undefined) // undefined = 아직 확인 전
  // 어떤 사용자의 결과인지 함께 저장해서, 계정이 바뀌면 자동으로 loading 상태가 됨
  const [result, setResult] = useState({ userId: null, profile: null, error: null })

  useEffect(() => {
    if (!supabase) return
    // 콜백 안에서 다른 supabase 호출을 await하면 교착될 수 있어 세션만 저장
    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  const userId = session?.user?.id ?? null
  const email = session?.user?.email ?? null

  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    if (!userId) return
    let cancelled = false // 그 사이 계정이 바뀌면 이전 응답은 버림
    fetchOrCreateProfile(email).then(
      (profile) => !cancelled && setResult({ userId, profile, error: null }),
      (error) => !cancelled && setResult({ userId, profile: null, error }),
    )
    return () => {
      cancelled = true
    }
  }, [userId, email, reloadKey])

  const retry = useCallback(() => {
    setResult({ userId: null, profile: null, error: null })
    setReloadKey((key) => key + 1)
  }, [])

  const createProfile = useCallback(
    async (values) => {
      const profile = await createMe(values)
      setResult({ userId, profile, error: null })
    },
    [userId],
  )

  const signOut = useCallback(async () => {
    clearPendingProfile()
    await supabase.auth.signOut()
  }, [])

  const value = useMemo(() => {
    let status
    if (!supabase) status = 'misconfigured'
    else if (session === undefined) status = 'loading'
    else if (session === null) status = 'signedOut'
    else if (result.userId !== userId) status = 'loading'
    else if (result.error?.code === 'PROFILE_NOT_FOUND') status = 'needsProfile'
    else if (result.error) status = 'error'
    else status = 'ready'

    return {
      status,
      session,
      profile: status === 'ready' ? result.profile : null,
      error: status === 'error' ? result.error : null,
      retry,
      createProfile,
      signOut,
    }
  }, [session, userId, result, retry, createProfile, signOut])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
