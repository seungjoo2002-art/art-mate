import { createClient } from '@supabase/supabase-js'

const url = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

// .env.local이 없으면 null — 앱 전체가 죽지 않고 AuthProvider가 설정 안내 화면을 보여 줌
export const supabase = url && anonKey ? createClient(url, anonKey) : null

/**
 * 이 브라우저에 로그인 세션(refresh token)이 저장되어 있는지.
 * 새로고침 직후 토큰 갱신이 네트워크 문제로 잠깐 실패하면 SDK는 세션 없음(null)을 알리지만
 * 저장된 세션은 지우지 않는다 → 이때는 로그아웃이 아니라 "다시 연결 중"으로 본다.
 */
export function hasStoredSession() {
  if (!supabase) return false
  try {
    return Boolean(globalThis.localStorage?.getItem(supabase.auth.storageKey))
  } catch {
    return false
  }
}
