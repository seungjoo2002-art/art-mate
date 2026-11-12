import { isAuthRetryableFetchError } from '@supabase/supabase-js'
import { hasStoredSession, supabase } from './supabase'

const BASE = `${import.meta.env.VITE_API_BASE_URL}/api/v1`

export class ApiError extends Error {
  constructor(status, error) {
    super(error?.message ?? `HTTP ${status}`)
    this.status = status
    this.code = error?.code // 화면 분기는 code로 (message는 바뀔 수 있음)
    this.details = error?.details
    this.requestId = error?.request_id
  }
}

async function accessToken() {
  const { data } = await supabase.auth.getSession() // SDK가 만료 전에 자동 갱신
  return data.session?.access_token ?? null
}

const networkError = () =>
  new ApiError(0, { code: 'NETWORK_ERROR', message: 'Network request failed' })

export async function api(path, { method = 'GET', body, retry = true } = {}) {
  const token = await accessToken()
  // 저장된 세션이 있는데 토큰을 못 받음 = 갱신 요청이 네트워크 문제로 실패 (로그아웃 아님)
  if (!token && hasStoredSession()) throw networkError()

  let res
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw networkError()
  }

  if (res.status === 204) return null
  const json = await res.json().catch(() => null)
  if (res.ok) return json

  const error = json?.error
  // access token 만료: 한 번만 갱신 후 재시도
  if (res.status === 401 && error?.code === 'TOKEN_EXPIRED' && retry) {
    const { error: refreshError } = await supabase.auth.refreshSession()
    if (!refreshError) return api(path, { method, body, retry: false })
    // 갱신이 네트워크 문제로 실패했으면 로그아웃시키지 않는다 (작업 중 화면이 랜딩으로 튕기던 원인)
    if (isAuthRetryableFetchError(refreshError)) throw networkError()
  }
  if (res.status === 401) await supabase.auth.signOut() // 무효 토큰 → 로그인 화면으로
  throw new ApiError(res.status, error)
}
