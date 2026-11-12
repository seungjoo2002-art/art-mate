import { useCallback, useEffect, useMemo, useState } from 'react'
import { isAuthRetryableFetchError } from '@supabase/supabase-js'
import { createMe, getMe, updateMe } from '../../features/auth/api'
import { clearPendingProfile, readPendingProfile } from '../../features/auth/pendingProfile'
import { hasStoredSession, supabase } from '../../lib/supabase'
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
  // 저장된 세션은 있는데 새로고침 직후 토큰 갱신이 네트워크 문제로 실패한 상태:
  // null(정상) | 'retrying'(다시 연결 중) | 'offline'(여러 번 실패 → 사용자에게 다시 시도 요청)
  const [reconnect, setReconnect] = useState(null)
  // 사용자가 직접 로그아웃했는지 (아니면 보던 화면을 기억했다가 다시 로그인 후 돌아감)
  const [userSignedOut, setUserSignedOut] = useState(false)
  // 어떤 사용자의 결과인지 함께 저장해서, 계정이 바뀌면 자동으로 loading 상태가 됨
  const [result, setResult] = useState({ userId: null, profile: null, error: null })

  useEffect(() => {
    if (!supabase) return
    // 콜백 안에서 다른 supabase 호출을 await하면 교착될 수 있어 세션만 저장
    const { data } = supabase.auth.onAuthStateChange((event, nextSession) => {
      // 새로고침 직후 갱신 실패: SDK는 세션 null을 알리지만 저장된 세션은 남아 있다.
      // 이전에는 이것을 로그아웃으로 보고 랜딩(/)으로 보냈고, 곧 갱신에 성공하면 홈(/home)으로
      // 이동했다 (= "새로고침 후 홈으로 튕김"). 이제는 다시 연결을 시도한다.
      if (event === 'INITIAL_SESSION' && !nextSession && hasStoredSession()) {
        setReconnect('retrying')
        return
      }
      setReconnect(null)
      if (nextSession) setUserSignedOut(false)
      setSession(nextSession)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  useEffect(() => {
    if (reconnect !== 'retrying') return
    let cancelled = false
    let attempt = 0
    let timer
    const tryRefresh = async () => {
      attempt += 1
      const { data, error } = await supabase.auth.refreshSession()
      if (cancelled) return
      if (data?.session) {
        setReconnect(null)
        setSession(data.session)
      } else if (error && !isAuthRetryableFetchError(error)) {
        // refresh token이 정말 만료·폐기됨 → 로그아웃
        setReconnect(null)
        setSession(null)
      } else if (attempt >= 4) {
        setReconnect('offline')
      } else {
        timer = setTimeout(tryRefresh, 1000 * 2 ** attempt)
      }
    }
    timer = setTimeout(tryRefresh, 300)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [reconnect])

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
    if (reconnect === 'offline') {
      setReconnect('retrying')
      return
    }
    setResult({ userId: null, profile: null, error: null })
    setReloadKey((key) => key + 1)
  }, [reconnect])

  const createProfile = useCallback(
    async (values) => {
      const profile = await createMe(values)
      setResult({ userId, profile, error: null })
    },
    [userId],
  )

  /** 프로필 수정 후 화면에 바로 반영 */
  const updateProfile = useCallback(
    async (patch) => {
      const profile = await updateMe(patch)
      setResult({ userId, profile, error: null })
      return profile
    },
    [userId],
  )

  const signOut = useCallback(async () => {
    clearPendingProfile()
    setUserSignedOut(true)
    setReconnect(null)
    await supabase.auth.signOut()
  }, [])

  const value = useMemo(() => {
    let status
    if (!supabase) status = 'misconfigured'
    else if (reconnect === 'offline') status = 'offline'
    else if (session === undefined || reconnect === 'retrying') status = 'loading'
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
      // 로그인이 풀린 이유: 'user'(직접 로그아웃) | 'session'(만료 등)
      signedOutBy: status === 'signedOut' ? (userSignedOut ? 'user' : 'session') : null,
      retry,
      createProfile,
      updateProfile,
      signOut,
    }
  }, [session, reconnect, userSignedOut, userId, result, retry, createProfile, updateProfile, signOut])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
